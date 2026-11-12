"""Domain-wide state shared by all profiles."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import logging
import time as monotonic_time
from typing import Any

from homeassistant.components.light import ATTR_EFFECT, ATTR_FLASH, ATTR_TRANSITION
from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_FLOOR_ID,
    ATTR_LABEL_ID,
    ENTITY_MATCH_ALL,
    EVENT_STATE_CHANGED,
    STATE_ON,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    ServiceCall,
    callback,
)
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)
from homeassistant.util.hass_dict import HassKey

from . import interceptor
from .const import (
    DOMAIN,
    OFF_WAIT_TIMEOUT,
    QUIET_WINDOW_MARGIN,
    REASON_EXPLICIT_VALUES,
    REASON_RESUME,
)
from .light_data import BRIGHTNESS_KEYS, COLOR_KEYS
from .profile import Profile

_LOGGER = logging.getLogger(__name__)

DATA_HUB: HassKey[Hub] = HassKey(DOMAIN)

TARGET_KEYS = (ATTR_ENTITY_ID, ATTR_DEVICE_ID, ATTR_AREA_ID, ATTR_FLOOR_ID, ATTR_LABEL_ID)
# How long a context we created is recognised as ours.
CONTEXT_TTL = 600


class Hub:
    """Owns the interceptor, light ownership and our contexts."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise."""
        self.hass = hass
        self.profiles: dict[str, Profile] = {}
        self.owner: dict[str, Profile] = {}
        self._contexts: OrderedDict[str, float] = OrderedDict()
        self._remove_interceptor: CALLBACK_TYPE | None = None
        self._remove_off_interceptor: CALLBACK_TYPE | None = None
        self._remove_toggle_interceptor: CALLBACK_TYPE | None = None
        self._unsub_state: CALLBACK_TYPE | None = None
        self._overlaps: dict[str, frozenset[str]] = {}

    # Contexts

    def new_context(self, parent: Context | None = None) -> Context:
        """Create a context that marks a command as Daylight's own."""
        context = Context(parent_id=parent.id if parent else None)
        now = monotonic_time.monotonic()
        self._contexts[context.id] = now
        while self._contexts and next(iter(self._contexts.values())) < now - CONTEXT_TTL:
            self._contexts.popitem(last=False)
        return context

    def is_ours(self, context: Context | None) -> bool:
        """Whether a context was created by Daylight."""
        return context is not None and context.id in self._contexts

    # Profiles and ownership

    @callback
    def async_add_profile(self, profile: Profile) -> None:
        """Register a profile; install the interceptor for the first one."""
        if self._remove_interceptor is None:
            try:
                self._remove_interceptor = interceptor.async_install(
                    self.hass, "light", "turn_on", self._async_intercept
                )
                self._remove_off_interceptor = interceptor.async_install(
                    self.hass, "light", "turn_off", self._async_intercept_off
                )
                self._remove_toggle_interceptor = interceptor.async_install(
                    self.hass, "light", "toggle", self._async_intercept_toggle
                )
            except interceptor.InterceptorError as err:
                if self._remove_interceptor:
                    self._remove_interceptor()
                    self._remove_interceptor = None
                if self._remove_off_interceptor:
                    self._remove_off_interceptor()
                    self._remove_off_interceptor = None
                raise ConfigEntryError(
                    f"Can't intercept light services, Home Assistant's internals changed: {err}"
                ) from err
            self._unsub_state = self.hass.bus.async_listen(
                EVENT_STATE_CHANGED, self._handle_state, self._filter_state
            )
        self.profiles[profile.entry.entry_id] = profile

    @callback
    def async_remove_profile(self, profile: Profile) -> None:
        """Unregister a profile; remove the interceptor after the last one."""
        self.profiles.pop(profile.entry.entry_id, None)
        ir.async_delete_issue(self.hass, DOMAIN, f"overlap_{profile.entry.entry_id}")
        self._overlaps.pop(profile.entry.entry_id, None)
        if self.profiles:
            self.async_update_ownership()
            return
        self.owner.clear()
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._remove_interceptor:
            self._remove_interceptor()
            self._remove_interceptor = None
        if self._remove_off_interceptor:
            self._remove_off_interceptor()
            self._remove_off_interceptor = None
        if self._remove_toggle_interceptor:
            self._remove_toggle_interceptor()
            self._remove_toggle_interceptor = None

    def expand(self, entity_ids: set[str]) -> tuple[set[str], set[str]]:
        """Replace HA light groups by their members. Return (lights, groups)."""
        registry = er.async_get(self.hass)
        lights: set[str] = set()
        groups: set[str] = set()
        pending = list(entity_ids)
        while pending:
            entity_id = pending.pop()
            if entity_id in groups or entity_id in lights:
                continue
            if self._is_light_group(registry, entity_id):
                groups.add(entity_id)
                state = self.hass.states.get(entity_id)
                members = state.attributes.get(ATTR_ENTITY_ID, []) if state else []
                pending.extend(m for m in members if m.startswith("light."))
            else:
                lights.add(entity_id)
        return lights, groups

    def _is_light_group(self, registry: er.EntityRegistry, entity_id: str) -> bool:
        # Only HA's own light groups forward calls to member entities.
        if (entry := registry.async_get(entity_id)) is not None:
            return entry.platform == "group"
        state = self.hass.states.get(entity_id)
        return state is not None and isinstance(state.attributes.get(ATTR_ENTITY_ID), list)

    @callback
    def async_update_ownership(self) -> None:
        """Give each light to the oldest profile that includes it."""
        owner: dict[str, Profile] = {}
        contested: dict[str, dict[str, Profile]] = {}
        for profile in sorted(self.profiles.values(), key=lambda p: p.entry.created_at):
            for entity_id in profile.resolved:
                if (winner := owner.get(entity_id)) is None:
                    owner[entity_id] = profile
                else:
                    contested.setdefault(profile.entry.entry_id, {})[entity_id] = winner
        self.owner = owner
        for profile in self.profiles.values():
            profile.async_set_owned(
                {e for e, p in owner.items() if p is profile}
            )
            self._report_overlap(profile, contested.get(profile.entry.entry_id, {}))

    def _report_overlap(self, profile: Profile, lights: dict[str, Profile]) -> None:
        entry_id = profile.entry.entry_id
        issue_id = f"overlap_{entry_id}"
        key = frozenset(f"{e}:{p.entry.entry_id}" for e, p in lights.items())
        if self._overlaps.get(entry_id) == key:
            return
        self._overlaps[entry_id] = key
        if not lights:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        listing = ", ".join(f"{e} (owned by {p.title})" for e, p in sorted(lights.items()))
        _LOGGER.warning(
            "Profile %s includes lights that an older profile already adapts; leaving them alone: %s",
            profile.title,
            listing,
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            config_entry_id=entry_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="overlap",
            translation_placeholders={"profile": profile.title, "lights": listing},
        )

    def status(self, entity_id: str) -> str | None:
        """'manual', 'adapting', or None if no profile adapts the light."""
        if (profile := self.owner.get(entity_id)) is None:
            return None
        light = profile.lights.get(entity_id)
        if light is None:
            return None
        return "manual" if light.manual else "adapting"

    # State routing

    @callback
    def _filter_state(self, data: EventStateChangedData) -> bool:
        return data["entity_id"] in self.owner

    @callback
    def _handle_state(self, event: Event[EventStateChangedData]) -> None:
        if (profile := self.owner.get(event.data["entity_id"])) is not None:
            profile.async_handle_light_state(event)

    # Resume

    async def async_resume(self, entity_ids: set[str]) -> None:
        """Clear manual control and adapt straight away.

        Each light is resumed by the profile that owns it; lights no profile
        owns are ignored.
        """
        tasks = []
        for entity_id in self.expand(entity_ids)[0]:
            if (profile := self.owner.get(entity_id)) is None:
                continue
            profile.clear_manual(entity_id, REASON_RESUME)
            profile.update_target()
            tasks.append(profile.async_adapt(entity_id, transition=profile.transition, force=True))
        await asyncio.gather(*tasks)

    # Interception

    def _call_targets(self, data: dict[str, Any]) -> set[str]:
        if data.get(ATTR_ENTITY_ID) == ENTITY_MATCH_ALL:
            return set(self.hass.states.async_entity_ids("light"))
        selected = async_extract_referenced_entity_ids(
            self.hass, TargetSelection(data), expand_group=False
        )
        return {
            e
            for e in selected.referenced | selected.indirectly_referenced
            if e.startswith("light.")
        }

    async def _async_intercept(self, call: ServiceCall) -> dict[str, Any] | None:
        """Fill in light.turn_on for managed lights. Return new data or None."""
        if self.is_ours(call.context):
            return None
        params: dict[str, Any] = dict(call.data.get("params", {}))
        targets = self._call_targets(dict(call.data))
        managed = {e for e in targets if e in self.owner}
        if not managed:
            return None
        if ATTR_FLASH in params or ATTR_EFFECT in params:
            # Leave flashes and effects alone, including the turn-on they cause.
            for entity_id in managed:
                if light := self.owner[entity_id].lights.get(entity_id):
                    light.intercepted_context = call.context.id
            return None

        explicit_brightness = not BRIGHTNESS_KEYS.isdisjoint(params)
        explicit_color = not COLOR_KEYS.isdisjoint(params)
        fills: dict[str, dict[str, Any]] = {}
        now = monotonic_time.monotonic()
        for entity_id in managed:
            profile = self.owner[entity_id]
            light = profile.lights.get(entity_id)
            state = self.hass.states.get(entity_id)
            if light is None or state is None:
                continue
            # A manual light is already on (turning off clears it); leave it.
            # A light already handled for this call is reached again when a
            # light group in the same call forwards it to its members.
            if light.manual or light.intercepted_context == call.context.id:
                continue
            light.off_until = None
            if explicit_brightness or explicit_color:
                profile.mark_manual(entity_id, REASON_EXPLICIT_VALUES)
            profile.update_target()
            fill = profile.light_data(
                state, brightness=not explicit_brightness, color=not explicit_color
            )
            light.intercepted_context = call.context.id
            light.last_sent = profile.light_data(state)
            light.last_sent_at = now
            if fill:
                fills[entity_id] = fill

        if not fills:
            return None
        distinct = {tuple(sorted(f.items())) for f in fills.values()}
        if set(fills) == targets and len(distinct) == 1:
            return {**call.data, "params": {**params, **next(iter(fills.values()))}}

        # Mixed call: send managed lights their own values, and run the
        # original call for everything else.
        buckets: dict[tuple, list[str]] = {}
        for entity_id, fill in fills.items():
            buckets.setdefault(tuple(sorted(fill.items())), []).append(entity_id)
        context = self.new_context(call.context)
        await asyncio.gather(
            *(
                self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {**params, **dict(fill), ATTR_ENTITY_ID: sorted(entity_ids)},
                    blocking=True,
                    context=context,
                )
                for fill, entity_ids in buckets.items()
            )
        )
        data = {k: v for k, v in call.data.items() if k not in TARGET_KEYS}
        data[ATTR_ENTITY_ID] = sorted(targets - set(fills))
        return data

    async def _async_intercept_off(self, call: ServiceCall) -> None:
        """Make sure our own commands can't undo a light.turn_off.

        Something reacting to the same event (night mode turning on) may have
        just sent a turn_on with new values. Let that finish before the off
        goes out, and send nothing more until the off has landed.
        """
        if self.is_ours(call.context):
            return None
        params = call.data.get("params", call.data)
        until = (
            monotonic_time.monotonic()
            + float(params.get(ATTR_TRANSITION) or 0)
            + QUIET_WINDOW_MARGIN
        )
        pending = []
        for entity_id in self._call_targets(dict(call.data)):
            if (profile := self.owner.get(entity_id)) is None:
                continue
            if (light := profile.lights.get(entity_id)) is None:
                continue
            light.off_until = until
            if light.inflight is not None:
                pending.append(light.inflight)
        if pending:
            await asyncio.wait(pending, timeout=OFF_WAIT_TIMEOUT)
        return None

    async def _async_intercept_toggle(self, call: ServiceCall) -> dict[str, Any] | None:
        """Send managed lights a light.turn_on or light.turn_off instead.

        Whether a toggle turns a light on or off is decided per light, so
        there is no single set of values to fill in. Splitting it lets the
        turn_on and turn_off interceptors handle each light as usual.
        """
        if self.is_ours(call.context):
            return None
        targets = self._call_targets(dict(call.data))
        managed = {e for e in targets if e in self.owner}
        if not managed:
            return None
        params: dict[str, Any] = dict(call.data.get("params", {}))
        on = {
            e for e in managed if (state := self.hass.states.get(e)) and state.state == STATE_ON
        }
        calls = []
        if managed - on:
            calls.append(("turn_on", params, managed - on))
        if on:
            # Like a toggle, drop what a turn-off doesn't take.
            off_params = {k: params[k] for k in (ATTR_TRANSITION, ATTR_FLASH) if k in params}
            calls.append(("turn_off", off_params, on))
        # The caller's context, not ours, so the interceptors treat these as
        # the caller's calls, as with a light group forwarding to members.
        await asyncio.gather(
            *(
                self.hass.services.async_call(
                    "light",
                    service,
                    {**data, ATTR_ENTITY_ID: sorted(entity_ids)},
                    blocking=True,
                    context=call.context,
                )
                for service, data, entity_ids in calls
            )
        )
        data = {k: v for k, v in call.data.items() if k not in TARGET_KEYS}
        data[ATTR_ENTITY_ID] = sorted(targets - managed)
        return data
