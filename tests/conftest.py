"""Fixtures for Daylight tests."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pytest

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import Context, HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import (
    MockConfigEntry,
    setup_test_component_platform,
)

from custom_components.daylight.const import (
    CONF_LIGHTS,
    DEFAULT_CENTRAL,
    DEFAULT_PROFILE,
    DOMAIN,
    SUBENTRY_PROFILE,
)
from custom_components.daylight.profile import Profile


class MockLight(LightEntity):
    """A light that applies what it is sent and records the calls."""

    _attr_should_poll = False
    _attr_supported_features = LightEntityFeature.TRANSITION | LightEntityFeature.FLASH

    def __init__(
        self,
        name: str,
        modes: set[ColorMode] | None = None,
        *,
        on: bool = False,
        min_kelvin: int = 2200,
        max_kelvin: int = 6500,
    ) -> None:
        """Initialise."""
        self._attr_name = name
        self._attr_unique_id = name
        self._attr_supported_color_modes = modes or {ColorMode.COLOR_TEMP}
        self._attr_color_mode = (
            ColorMode.COLOR_TEMP
            if ColorMode.COLOR_TEMP in self._attr_supported_color_modes
            else next(iter(self._attr_supported_color_modes))
        )
        self._attr_min_color_temp_kelvin = min_kelvin
        self._attr_max_color_temp_kelvin = max_kelvin
        self._attr_is_on = on
        self._attr_brightness = 128 if on else None
        self._attr_color_temp_kelvin = 4000 if on else None
        self.calls: list[dict[str, Any]] = []

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Apply the call."""
        self.calls.append(kwargs)
        self._attr_is_on = True
        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
        elif self._attr_brightness is None:
            self._attr_brightness = 255
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            self._attr_color_temp_kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            self._attr_color_mode = ColorMode.COLOR_TEMP
        if ATTR_HS_COLOR in kwargs:
            self._attr_hs_color = kwargs[ATTR_HS_COLOR]
            self._attr_color_mode = ColorMode.HS
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        self._attr_is_on = False
        self.async_write_ha_state()

    def external(self, **attrs: Any) -> None:
        """Simulate a change made outside Home Assistant (a remote)."""
        for key, value in attrs.items():
            setattr(self, f"_attr_{key}", value)
        self.async_set_context(Context())
        self.async_write_ha_state()


@pytest.fixture
def lights() -> dict[str, MockLight]:
    """Lights available in every test, keyed by entity id."""
    return {
        "light.desk": MockLight("desk", {ColorMode.COLOR_TEMP, ColorMode.HS}),
        "light.sofa": MockLight("sofa"),
        "light.hall": MockLight("hall"),
        "light.dimmer": MockLight("dimmer", {ColorMode.BRIGHTNESS}),
        "light.plug": MockLight("plug", {ColorMode.ONOFF}),
        "light.narrow": MockLight("narrow", min_kelvin=2700, max_kelvin=4000),
    }


@pytest.fixture
async def setup_lights(hass: HomeAssistant, lights: dict[str, MockLight]) -> dict[str, MockLight]:
    """Set up the mock lights."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    hass.config.latitude = 52.37
    setup_test_component_platform(hass, "light", list(lights.values()))
    assert await async_setup_component(hass, "light", {"light": {"platform": "test"}})
    await hass.async_block_till_done()
    return lights


def split_sections(
    sections: dict[str, dict[str, Any]], shared: Mapping[str, Any] = DEFAULT_CENTRAL
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Overrides on top of `shared` and the profile defaults, split into the
    Daylight entry's options and a profile's data."""
    central = deepcopy(dict(shared))
    own = deepcopy(DEFAULT_PROFILE)
    for name, values in sections.items():
        for key, value in values.items():
            target = own if key in DEFAULT_PROFILE.get(name, {}) else central
            target[name][key] = value
    return central, own


def make_entry(
    target: dict[str, Any], title: str = "Main", **sections: dict[str, Any]
) -> MockConfigEntry:
    """A Daylight entry with one profile, not yet added to hass."""
    central, own = split_sections(sections)
    return MockConfigEntry(
        domain=DOMAIN,
        title="Daylight",
        version=2,
        options=central,
        subentries_data=[
            {
                "data": {CONF_LIGHTS: target, **own},
                "subentry_type": SUBENTRY_PROFILE,
                "title": title,
                "unique_id": None,
            }
        ],
    )


@dataclass
class ProfileHandle:
    """A profile's subentry; looks up the running Profile, which a reload replaces."""

    entry: MockConfigEntry
    subentry_id: str

    @property
    def runtime_data(self) -> Profile:
        """The running profile."""
        return self.entry.runtime_data[self.subentry_id]


async def add_profile(
    hass: HomeAssistant, target: dict[str, Any], title: str = "Main", **sections: dict[str, Any]
) -> ProfileHandle:
    """Add a profile to the Daylight entry, creating and loading the entry if needed.

    Shared settings in `sections` replace the entry's options.
    """
    if entries := hass.config_entries.async_entries(DOMAIN):
        entry = entries[0]
        central, own = split_sections(sections, entry.options)
        subentry = ConfigSubentry(
            data=MappingProxyType({CONF_LIGHTS: target, **own}),
            subentry_type=SUBENTRY_PROFILE,
            title=title,
            unique_id=None,
        )
        hass.config_entries.async_update_entry(entry, options=central)
        hass.config_entries.async_add_subentry(entry, subentry)
    else:
        entry = make_entry(target, title, **sections)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return ProfileHandle(entry, list(entry.subentries)[-1])


NOON = "2026-11-10 12:00:00+01:00"


async def turn_on(hass: HomeAssistant, entity_id: str | list[str], **data: Any) -> None:
    """Call light.turn_on and wait for everything it causes."""
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": entity_id, **data}, blocking=True
    )
    await hass.async_block_till_done()


async def turn_off(hass: HomeAssistant, entity_id: str | list[str]) -> None:
    """Call light.turn_off and wait."""
    await hass.services.async_call(
        "light", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()
