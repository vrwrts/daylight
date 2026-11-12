"""Daylight: adjust brightness and colour temperature of lights through the day."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import probatio

from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    ServiceCall,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ENTITY,
    CONF_SLEEP_ENTITY,
    CONF_TRANSITION,
    CONF_UPDATE_INTERVAL,
    CONF_WAKE_ENTITY,
    DOMAIN,
    SECTION_CURVE,
    SECTION_NIGHT,
    SECTION_SCHEDULE,
    SERVICE_PAUSE,
    SERVICE_RESUME,
    SUBENTRY_PROFILE,
)
from .hub import DATA_HUB, Hub
from .migrate import async_merge_entries
from .profile import DaylightConfigEntry, Profile

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

TARGET_SCHEMA = probatio.Schema(cv.ENTITY_SERVICE_FIELDS)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Create the hub, merge old entries and register the actions."""
    hub = hass.data[DATA_HUB] = Hub(hass)
    await hub.async_load()
    # Runs before Home Assistant sets up any entry of this domain.
    await async_merge_entries(hass)

    def lights(call: ServiceCall) -> set[str]:
        selection = TargetSelection(call.data)
        if not selection.has_any_target:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=f"{call.service}_needs_target",
            )
        selected = async_extract_referenced_entity_ids(hass, selection, expand_group=False)
        return {
            e
            for e in selected.referenced | selected.indirectly_referenced
            if e.startswith("light.")
        }

    async def resume(call: ServiceCall) -> None:
        await hub.async_resume(lights(call))

    async def pause(call: ServiceCall) -> None:
        hub.async_pause(lights(call))

    hass.services.async_register(DOMAIN, SERVICE_RESUME, resume, TARGET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_PAUSE, pause, TARGET_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DaylightConfigEntry) -> bool:
    """Start every profile, and the updates they share."""
    hub = hass.data[DATA_HUB]
    profiles = entry.runtime_data = {}
    try:
        for subentry in entry.get_subentries_of_type(SUBENTRY_PROFILE):
            profile = profiles[subentry.subentry_id] = Profile(hass, entry, subentry, hub)
            await profile.async_start()
    except Exception:
        _stop(entry)
        raise

    transition = float(entry.options[SECTION_CURVE][CONF_TRANSITION])

    async def update(*_: datetime | Event[EventStateChangedData]) -> None:
        for profile in profiles.values():
            profile.update_target()
        await asyncio.gather(
            *(profile.async_adapt_all(transition=transition) for profile in profiles.values())
        )

    watched = [
        entity
        for entity in (
            entry.options[SECTION_SCHEDULE].get(CONF_WAKE_ENTITY),
            entry.options[SECTION_SCHEDULE].get(CONF_SLEEP_ENTITY),
            entry.options[SECTION_NIGHT].get(CONF_ENTITY),
        )
        if entity
    ]
    if watched:
        entry.async_on_unload(async_track_state_change_event(hass, watched, update))
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            update,
            timedelta(seconds=float(entry.options[SECTION_CURVE][CONF_UPDATE_INTERVAL])),
            name=DOMAIN,
        )
    )
    # Adding, changing or removing a profile updates the entry without reloading it.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: DaylightConfigEntry) -> None:
    hass.config_entries.async_schedule_reload(entry.entry_id)


def _stop(entry: DaylightConfigEntry) -> None:
    # Newest first, so stopping a profile never hands its lights to another
    # profile that is about to stop as well.
    for profile in reversed(list(entry.runtime_data.values())):
        profile.async_stop()


async def async_unload_entry(hass: HomeAssistant, entry: DaylightConfigEntry) -> bool:
    """Stop every profile."""
    _stop(entry)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: DaylightConfigEntry) -> None:
    """Forget pauses, so adding Daylight again starts clean."""
    # Old entries removed while merging them must not wipe anything.
    if entry.version > 1:
        await hass.data[DATA_HUB].async_clear()
