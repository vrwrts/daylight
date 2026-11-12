"""Merging version 1 entries, one per profile, into one entry."""

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory

from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry

from custom_components.daylight.const import (
    CONF_LIGHTS,
    DEFAULT_CENTRAL,
    DEFAULT_PROFILE,
    DOMAIN,
    SUBENTRY_PROFILE,
)

from .conftest import NOON, MockLight, turn_on

START = datetime(2026, 11, 1, tzinfo=dt_util.UTC)


def _old_entry(
    title: str, target: dict[str, Any], age: int, **sections: dict[str, Any]
) -> MockConfigEntry:
    """A version 1 entry, which held every setting itself."""
    options: dict[str, Any] = {CONF_LIGHTS: target}
    for name in DEFAULT_CENTRAL.keys() | DEFAULT_PROFILE.keys():
        options[name] = {
            **deepcopy(DEFAULT_CENTRAL.get(name, {})),
            **deepcopy(DEFAULT_PROFILE.get(name, {})),
            **sections.get(name, {}),
        }
    return MockConfigEntry(
        domain=DOMAIN,
        title=title,
        version=1,
        options=options,
        created_at=START + timedelta(days=age),
        disabled_by=sections.pop("disabled_by", None),
    )


async def test_merge(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    # Added out of order, so the order must come from created_at.
    dimmed = _old_entry(
        "Dimmed",
        {"entity_id": ["light.desk", "light.hall"]},
        2,
        brightness={"peak": 20},
        night_mode={"entity": "input_boolean.sleep_mode", "brightness": 5},
        winter={"wake_brightness": 50},
    )
    normal = _old_entry(
        "Normal",
        {"entity_id": ["light.desk", "light.sofa"]},
        1,
        night_mode={"entity": "input_boolean.sleep_mode"},
    )
    spare = _old_entry(
        "Spare",
        {"entity_id": ["light.dimmer"]},
        3,
        curve={"transition": 30},
        night_mode={"entity": "input_boolean.sleep_mode"},
        disabled_by=ConfigEntryDisabler.USER,
    )
    for entry in (dimmed, normal, spare):
        entry.add_to_hass(hass)
    hass.states.async_set("input_boolean.sleep_mode", "off")

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert entries == [normal]
    assert normal.version == 2
    assert normal.title == "Daylight"
    assert normal.state is ConfigEntryState.LOADED
    assert normal.options["night_mode"] == {"entity": "input_boolean.sleep_mode"}
    assert normal.options["winter"] == {"enabled": False}
    assert normal.options["curve"]["transition"] == 10

    profiles = list(normal.subentries.values())
    assert [p.title for p in profiles] == ["Normal", "Dimmed", "Spare"]
    assert {p.subentry_type for p in profiles} == {SUBENTRY_PROFILE}
    assert profiles[1].data == {
        CONF_LIGHTS: {"entity_id": ["light.desk", "light.hall"]},
        "brightness": {"wake": 65, "peak": 20, "sleep": 30},
        "color_temp": {"wake": 2000, "peak": 3000, "sleep": 2000},
        "winter": {"wake_brightness": 50, "peak_brightness": 100},
        "night_mode": {"brightness": 5, "color_temp": 2000},
    }

    # The disabled entry's profile runs, and the oldest profile still owns
    # the light it shared with a newer one.
    runtime = normal.runtime_data
    assert set(runtime[profiles[0].subentry_id].lights) == {"light.desk", "light.sofa"}
    assert set(runtime[profiles[1].subentry_id].lights) == {"light.hall"}
    assert set(runtime[profiles[2].subentry_id].lights) == {"light.dimmer"}
    await turn_on(hass, "light.hall")
    assert setup_lights["light.hall"].calls == [{"brightness": 51, "color_temp_kelvin": 3000}]

    issue = ir.async_get(hass).async_get_issue(DOMAIN, "migration_dropped_settings")
    assert issue is not None
    assert issue.is_persistent
    assert issue.translation_placeholders == {"source": "Normal", "profiles": "Spare (curve)"}


async def test_merge_same_settings_keeps_enabled_entry(
    hass: HomeAssistant, setup_lights: dict[str, MockLight]
) -> None:
    disabled = _old_entry(
        "Old", {"entity_id": ["light.sofa"]}, 1, disabled_by=ConfigEntryDisabler.USER
    )
    enabled = _old_entry("Normal", {"entity_id": ["light.desk"]}, 2)
    for entry in (disabled, enabled):
        entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    # Keeping the disabled entry would turn Daylight off.
    assert hass.config_entries.async_entries(DOMAIN) == [enabled]
    assert enabled.state is ConfigEntryState.LOADED
    assert [p.title for p in enabled.subentries.values()] == ["Old", "Normal"]
    assert ir.async_get(hass).async_get_issue(DOMAIN, "migration_dropped_settings") is None
