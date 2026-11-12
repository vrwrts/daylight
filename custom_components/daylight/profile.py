"""A profile: one subentry, a set of lights with its own values along the shared curve."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
import logging
import time as monotonic_time
from typing import TYPE_CHECKING, Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_TRANSITION,
    ColorMode,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.target import (
    TargetStateChangedData,
    async_track_target_selector_state_change_event,
)
from homeassistant.util import dt as dt_util

from . import curve, light_data
from .const import (
    CONF_BRIGHTNESS,
    CONF_BRIGHTNESS_TOLERANCE,
    CONF_COLOR_TEMP,
    CONF_COLOR_TEMP_TOLERANCE,
    CONF_CURVE,
    CONF_ENABLED,
    CONF_ENTITY,
    CONF_LIGHTS,
    CONF_MODE,
    CONF_PEAK,
    CONF_PEAK_BRIGHTNESS,
    CONF_RAMP_DURATION,
    CONF_SLEEP,
    CONF_SLEEP_ENTITY,
    CONF_SLEEP_TIME,
    CONF_TIMEOUT,
    CONF_TRANSITION,
    CONF_WAKE,
    CONF_WAKE_BRIGHTNESS,
    CONF_WAKE_ENTITY,
    CONF_WAKE_TIME,
    CURVE_COSINE,
    MODE_TIMEOUT,
    QUIET_WINDOW_MARGIN,
    REASON_EXTERNAL_CHANGE,
    REASON_PAUSED,
    REASON_RESUME,
    REASON_TIMEOUT,
    REASON_TURNED_OFF,
    SECTION_BRIGHTNESS,
    SECTION_COLOR_TEMP,
    SECTION_CURVE,
    SECTION_MANUAL,
    SECTION_NIGHT,
    SECTION_SCHEDULE,
    SECTION_WINTER,
    SIGNAL_MANUAL_CONTROL,
)

if TYPE_CHECKING:
    from .hub import Hub

_LOGGER = logging.getLogger(__name__)

type DaylightConfigEntry = ConfigEntry[dict[str, Profile]]


@dataclass(slots=True)
class LightState:
    """What Daylight knows about one managed light."""

    manual: bool = False
    # Paused by daylight.pause: manual until daylight.resume, nothing else ends it.
    paused: bool = False
    manual_until: datetime | None = None
    last_sent: dict[str, Any] | None = None
    last_sent_at: float | None = None
    # Context of the last intercepted turn-on; its state changes are ours.
    intercepted_context: str | None = None
    # Until this monotonic time a turn_off is landing; sending would undo it.
    off_until: float | None = None
    inflight: asyncio.Task[Any] | None = field(default=None, repr=False)
    cancel_timer: CALLBACK_TYPE | None = field(default=None, repr=False)


def time_of_day(value: str | None, fallback: time) -> float:
    """Minutes since midnight from an entity state string, or the fallback.

    Timestamp sensors hold a full datetime (possibly tomorrow); only the local
    time of day is used.
    """
    parsed: time | None = None
    # A date-only input_datetime has no time of day to use.
    if value not in (None, STATE_UNAVAILABLE, STATE_UNKNOWN) and ":" in value:
        if (moment := dt_util.parse_datetime(value)) is not None:
            if moment.tzinfo is not None:
                moment = dt_util.as_local(moment)
            parsed = moment.time()
        else:
            parsed = dt_util.parse_time(value)
    chosen = parsed or fallback
    return chosen.hour * 60 + chosen.minute + chosen.second / 60


class Profile:
    """Runtime state and behaviour of one profile."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: DaylightConfigEntry,
        subentry: ConfigSubentry,
        hub: Hub,
    ) -> None:
        """Initialise from the entry's shared options and the subentry's own values."""
        self.hass = hass
        self.entry = entry
        self.subentry = subentry
        self.hub = hub
        shared, own = entry.options, subentry.data
        self.target_config: dict[str, Any] = own[CONF_LIGHTS]
        self.schedule = shared[SECTION_SCHEDULE]
        self.brightness = own[SECTION_BRIGHTNESS]
        self.color_temp = own[SECTION_COLOR_TEMP]
        self.curve = shared[SECTION_CURVE]
        self.winter = {**shared[SECTION_WINTER], **own[SECTION_WINTER]}
        self.manual_options = shared[SECTION_MANUAL]
        self.night = {**shared[SECTION_NIGHT], **own[SECTION_NIGHT]}
        self.transition = float(self.curve[CONF_TRANSITION])

        # Lights the target resolves to before and after expanding groups.
        self.direct: set[str] = set()
        self.groups: set[str] = set()
        self.resolved: set[str] = set()
        # Lights this profile adapts; excludes lights an older profile owns.
        self.lights: dict[str, LightState] = {}
        self.target: tuple[float, float] = (0.0, 0.0)
        self._unsubs: list[CALLBACK_TYPE] = []

    @property
    def title(self) -> str:
        """Profile name."""
        return self.subentry.title

    @property
    def subentry_id(self) -> str:
        """Id of the profile's subentry."""
        return self.subentry.subentry_id

    async def async_start(self) -> None:
        """Start tracking the profile's lights."""
        self.update_target()
        self.hub.async_add_profile(self)
        self._unsubs.append(
            await async_track_target_selector_state_change_event(
                self.hass,
                self.target_config,
                self._handle_direct_state,
                lambda ids: {e for e in ids if e.startswith("light.")},
                self._handle_entities_update,
            )
        )

    @callback
    def async_stop(self) -> None:
        """Stop everything and release the lights."""
        while self._unsubs:
            self._unsubs.pop()()
        self.hub.async_remove_profile(self)
        for light in self.lights.values():
            if light.cancel_timer:
                light.cancel_timer()
        self.lights.clear()

    # Target

    def update_target(self, now: datetime | None = None) -> tuple[float, float]:
        """Recompute and store the current (brightness %, kelvin)."""
        now = dt_util.as_local(now or dt_util.now())
        night_entity = self.night.get(CONF_ENTITY)
        if night_entity and (state := self.hass.states.get(night_entity)) and state.state == STATE_ON:
            self.target = (float(self.night[CONF_BRIGHTNESS]), float(self.night[CONF_COLOR_TEMP]))
            return self.target

        b_wake = float(self.brightness[CONF_WAKE])
        b_peak = float(self.brightness[CONF_PEAK])
        if self.winter[CONF_ENABLED]:
            hours = curve.daylight_hours(self.hass.config.latitude, now.timetuple().tm_yday)
            weight = curve.winter_weight(hours)
            b_wake = curve.blend(b_wake, float(self.winter[CONF_WAKE_BRIGHTNESS]), weight)
            b_peak = curve.blend(b_peak, float(self.winter[CONF_PEAK_BRIGHTNESS]), weight)

        settings = curve.CurveSettings(
            wake=self._schedule_time(CONF_WAKE_ENTITY, CONF_WAKE_TIME),
            sleep=self._schedule_time(CONF_SLEEP_ENTITY, CONF_SLEEP_TIME),
            brightness=(b_wake, b_peak, float(self.brightness[CONF_SLEEP])),
            kelvin=(
                float(self.color_temp[CONF_WAKE]),
                float(self.color_temp[CONF_PEAK]),
                float(self.color_temp[CONF_SLEEP]),
            ),
            ramp=float(self.curve[CONF_RAMP_DURATION]),
            cosine=self.curve[CONF_CURVE] == CURVE_COSINE,
        )
        minutes = now.hour * 60 + now.minute + now.second / 60
        self.target = curve.target(settings, minutes)
        return self.target

    def _schedule_time(self, entity_key: str, time_key: str) -> float:
        fallback = dt_util.parse_time(self.schedule[time_key]) or time(0)
        value = None
        if (entity_id := self.schedule.get(entity_key)) and (
            state := self.hass.states.get(entity_id)
        ):
            value = state.state
        return time_of_day(value, fallback)

    def light_data(self, state: State, *, brightness: bool = True, color: bool = True) -> dict[str, Any]:
        """Attributes to send to this light for the current target."""
        return light_data.build(
            state, self.target[0], self.target[1], brightness=brightness, color=color
        )

    # Membership

    async def _handle_entities_update(
        self, added: set[str], removed: set[str], states: Mapping[str, State | None]
    ) -> None:
        self.direct = (self.direct | added) - removed
        self.refresh_members()

    @callback
    def _handle_direct_state(self, data: TargetStateChangedData) -> None:
        # A light group's state carries its members; re-expand when it changes.
        if data.state_change_event.data["entity_id"] in self.groups:
            self.refresh_members()

    @callback
    def refresh_members(self) -> None:
        """Expand groups and hand the result to the hub."""
        self.resolved, self.groups = self.hub.expand(self.direct)
        self.hub.async_update_ownership()

    @callback
    def async_set_owned(self, owned: set[str]) -> None:
        """Called by the hub with the lights this profile now adapts."""
        for entity_id in set(self.lights) - owned:
            light = self.lights.pop(entity_id)
            if light.cancel_timer:
                light.cancel_timer()
        for entity_id in owned - set(self.lights):
            paused = entity_id in self.hub.paused
            self.lights[entity_id] = LightState(manual=paused, paused=paused)
            self.hass.async_create_task(self.async_adapt(entity_id))

    # Adapting

    async def async_adapt(
        self, entity_id: str, *, transition: float | None = None, force: bool = False
    ) -> None:
        """Send the current target to one light if it's on and not manual."""
        light = self.lights.get(entity_id)
        state = self.hass.states.get(entity_id)
        if light is None or light.manual or state is None or state.state != STATE_ON:
            return
        now = monotonic_time.monotonic()
        if light.off_until is not None and now < light.off_until:
            return
        data = self.light_data(state)
        if not data or (not force and data == light.last_sent):
            return
        light.last_sent = data
        light.last_sent_at = now
        service_data: dict[str, Any] = {ATTR_ENTITY_ID: entity_id, **data}
        if transition:
            service_data[ATTR_TRANSITION] = transition
        # Kept so an intercepted turn_off can wait for it to reach the light
        # first; otherwise our turn_on could land after the off and undo it.
        task = self.hass.async_create_task(
            self.hass.services.async_call(
                "light",
                "turn_on",
                service_data,
                blocking=True,
                context=self.hub.new_context(),
            )
        )
        light.inflight = task
        try:
            await task
        finally:
            if light.inflight is task:
                light.inflight = None

    async def async_adapt_all(self, *, transition: float | None = None) -> None:
        """Push the current target to every owned light."""
        await asyncio.gather(
            *(self.async_adapt(entity_id, transition=transition) for entity_id in self.lights)
        )

    # Manual control

    @callback
    def mark_manual(self, entity_id: str, reason: str) -> None:
        """Stop adapting a light, according to the configured mode or a pause."""
        light = self.lights.get(entity_id)
        if light is None:
            return
        was_manual = light.manual
        light.manual = True
        if reason == REASON_PAUSED:
            light.paused = True
        if light.paused:
            if light.cancel_timer:
                light.cancel_timer()
                light.cancel_timer = None
            light.manual_until = None
        elif self.manual_options[CONF_MODE] == MODE_TIMEOUT:
            if light.cancel_timer:
                light.cancel_timer()
            delay = float(self.manual_options[CONF_TIMEOUT]) * 60
            light.manual_until = dt_util.utcnow() + timedelta(seconds=delay)

            async def _expired(_now: datetime) -> None:
                light.cancel_timer = None
                self.clear_manual(entity_id, REASON_TIMEOUT)
                self.update_target()
                await self.async_adapt(entity_id, transition=self.transition, force=True)

            light.cancel_timer = async_call_later(self.hass, delay, _expired)
        if not was_manual:
            _LOGGER.debug("%s: %s under manual control (%s)", self.title, entity_id, reason)
            async_dispatcher_send(
                self.hass, SIGNAL_MANUAL_CONTROL, entity_id, True, reason, self
            )

    @callback
    def clear_manual(self, entity_id: str, reason: str) -> bool:
        """End manual control. Return whether the light was manual.

        Only daylight.resume ends a pause.
        """
        light = self.lights.get(entity_id)
        if light is None or not light.manual or (light.paused and reason != REASON_RESUME):
            return False
        if light.cancel_timer:
            light.cancel_timer()
            light.cancel_timer = None
        light.manual = False
        light.paused = False
        light.manual_until = None
        _LOGGER.debug("%s: %s back under Daylight (%s)", self.title, entity_id, reason)
        async_dispatcher_send(self.hass, SIGNAL_MANUAL_CONTROL, entity_id, False, reason, self)
        return True

    def _is_ours(self, light: LightState, state: State) -> bool:
        context = state.context
        return self.hub.is_ours(context) or (
            light.intercepted_context is not None
            and light.intercepted_context in (context.id, context.parent_id)
        )

    @callback
    def async_handle_light_state(self, event: Event[EventStateChangedData]) -> None:
        """React to a state change of an owned light (routed by the hub)."""
        entity_id = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        light = self.lights.get(entity_id)
        if light is None or new is None:
            return

        if new.state != STATE_ON:
            if new.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                return
            self.clear_manual(entity_id, REASON_TURNED_OFF)
            light.last_sent = None
            light.last_sent_at = None
            light.intercepted_context = None
            return

        if old is None or old.state != STATE_ON:
            # Turned on without going through interception (wall switch,
            # remote, toggle): correct it straight away.
            if not light.manual and not self._is_ours(light, new):
                light.off_until = None
                self.update_target()
                self.hass.async_create_task(self.async_adapt(entity_id, force=True))
            return

        changed = any(
            old.attributes.get(key) != new.attributes.get(key)
            for key in (ATTR_BRIGHTNESS, ATTR_COLOR_TEMP_KELVIN, ATTR_COLOR_MODE)
        )
        if not changed or self._is_ours(light, new):
            return
        if light.manual:
            if self.manual_options[CONF_MODE] == MODE_TIMEOUT:
                self.mark_manual(entity_id, REASON_EXTERNAL_CHANGE)
            return
        if light.last_sent_at is not None and (
            monotonic_time.monotonic() - light.last_sent_at
            < self.transition + QUIET_WINDOW_MARGIN
        ):
            return
        if self._differs(new, light.last_sent or self.light_data(new)):
            self.mark_manual(entity_id, REASON_EXTERNAL_CHANGE)

    def _differs(self, state: State, expected: dict[str, Any]) -> bool:
        if (want := expected.get(ATTR_BRIGHTNESS)) is not None:
            have = state.attributes.get(ATTR_BRIGHTNESS)
            tolerance = float(self.manual_options[CONF_BRIGHTNESS_TOLERANCE]) * 255 / 100
            if have is None or abs(have - want) > tolerance:
                return True
        if (want := expected.get(ATTR_COLOR_TEMP_KELVIN)) is not None:
            if state.attributes.get(ATTR_COLOR_MODE) != ColorMode.COLOR_TEMP:
                return True
            have = state.attributes.get(ATTR_COLOR_TEMP_KELVIN)
            tolerance = float(self.manual_options[CONF_COLOR_TEMP_TOLERANCE])
            if have is None or abs(have - want) > tolerance:
                return True
        return False
