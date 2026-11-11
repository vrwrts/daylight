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

from .const import DOMAIN, SERVICE_RESUME
from .hub import DATA_HUB, Hub
from .profile import DaylightConfigEntry, Profile

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

RESUME_SCHEMA = probatio.Schema(cv.ENTITY_SERVICE_FIELDS)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Create the hub and register daylight.resume."""
    hub = hass.data[DATA_HUB] = Hub(hass)

    async def resume(call: ServiceCall) -> None:
        selection = TargetSelection(call.data)
        if not selection.has_any_target:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="resume_needs_target"
            )
        selected = async_extract_referenced_entity_ids(hass, selection, expand_group=False)
        await hub.async_resume(
            {
                e
                for e in selected.referenced | selected.indirectly_referenced
                if e.startswith("light.")
            }
        )

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
