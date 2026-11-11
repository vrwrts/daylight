"""Daylight: adjust brightness and colour temperature of lights through the day."""

from __future__ import annotations

import probatio

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)
from homeassistant.helpers.typing import ConfigType

from .const import ATTR_CONFIG_ENTRY_ID, DOMAIN, SERVICE_RESUME
from .hub import DATA_HUB, Hub
from .profile import DaylightConfigEntry, Profile

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

RESUME_SCHEMA = probatio.Schema(
    {
        **cv.ENTITY_SERVICE_FIELDS,
        probatio.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Create the hub and register daylight.resume."""
    hub = hass.data[DATA_HUB] = Hub(hass)

    async def resume(call: ServiceCall) -> None:
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        selection = TargetSelection(call.data)
        if not selection.has_any_target and entry_id is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="resume_needs_target"
            )
        entity_ids: set[str] | None = None
        if selection.has_any_target:
            selected = async_extract_referenced_entity_ids(
                hass, selection, expand_group=False
            )
            entity_ids = selected.referenced | selected.indirectly_referenced
        if entry_id is not None and entry_id not in hub.profiles:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_profile",
                translation_placeholders={"entry_id": entry_id},
            )
        await hub.async_resume(entity_ids, entry_id)

    hass.services.async_register(DOMAIN, SERVICE_RESUME, resume, RESUME_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DaylightConfigEntry) -> bool:
    """Start a profile."""
    profile = Profile(hass, entry, hass.data[DATA_HUB])
    entry.runtime_data = profile
    try:
        await profile.async_start()
    except Exception:
        profile.async_stop()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DaylightConfigEntry) -> bool:
    """Stop a profile."""
    entry.runtime_data.async_stop()
    return True
