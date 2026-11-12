"""Interception of light.turn_on and light.toggle, groups, and unloading."""

from freezegun.api import FrozenDateTimeFactory

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

from custom_components.daylight.const import DOMAIN

from .conftest import NOON, MockLight, add_profile, make_options, toggle, turn_on

ALL = {
    "entity_id": [
        "light.desk",
        "light.sofa",
        "light.dimmer",
        "light.plug",
        "light.narrow",
    ]
}


async def test_fills_missing_values(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    entry = await add_profile(hass, ALL)

    await turn_on(hass, "light.desk")
    assert setup_lights["light.desk"].calls == [
        {"brightness": 255, "color_temp_kelvin": 3000}
    ]
    assert not entry.runtime_data.lights["light.desk"].manual


async def test_capabilities(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-11-10 03:00:00+01:00")  # sleep values: 30%, 2000 K
    await add_profile(hass, ALL)

    await turn_on(hass, ["light.desk", "light.dimmer", "light.plug", "light.narrow"])
    # Clamped to each light's own range.
    assert setup_lights["light.desk"].calls == [{"brightness": 76, "color_temp_kelvin": 2200}]
    assert setup_lights["light.narrow"].calls == [{"brightness": 76, "color_temp_kelvin": 2700}]
    assert setup_lights["light.dimmer"].calls == [{"brightness": 76}]
    assert setup_lights["light.plug"].calls == [{}]


async def test_explicit_values_stick(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    entry = await add_profile(hass, ALL)

    await turn_on(hass, "light.desk", brightness_pct=30)
    assert setup_lights["light.desk"].calls == [{"brightness": 76, "color_temp_kelvin": 3000}]
    assert entry.runtime_data.lights["light.desk"].manual

    await turn_on(hass, "light.sofa", color_temp_kelvin=4500)
    assert setup_lights["light.sofa"].calls == [{"brightness": 255, "color_temp_kelvin": 4500}]
    assert entry.runtime_data.lights["light.sofa"].manual

    # A bare turn-on of a light under manual control leaves it alone.
    await turn_on(hass, "light.desk")
    assert setup_lights["light.desk"].calls[-1] == {}


async def test_toggle_on_fills_values(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    entry = await add_profile(hass, ALL)

    await toggle(hass, "light.desk")
    assert setup_lights["light.desk"].calls == [
        {"brightness": 255, "color_temp_kelvin": 3000}
    ]
    assert not entry.runtime_data.lights["light.desk"].manual

    await toggle(hass, "light.sofa", brightness_pct=30)
    assert setup_lights["light.sofa"].calls == [{"brightness": 76, "color_temp_kelvin": 3000}]
    assert entry.runtime_data.lights["light.sofa"].manual


async def test_toggle_mixed(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    await add_profile(hass, {"entity_id": ["light.desk", "light.sofa"]})
    await turn_on(hass, "light.sofa")

    await toggle(hass, ["light.desk", "light.sofa", "light.hall"], transition=2)
    assert setup_lights["light.desk"].calls == [
        {"brightness": 255, "color_temp_kelvin": 3000, "transition": 2}
    ]
    assert hass.states.get("light.sofa").state == "off"
    assert setup_lights["light.hall"].calls == [{"transition": 2}]


async def test_homeassistant_toggle(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    assert await async_setup_component(hass, "homeassistant", {})
    await add_profile(hass, ALL)

    await hass.services.async_call(
        "homeassistant", "toggle", {"entity_id": "light.desk"}, blocking=True
    )
    await hass.async_block_till_done()
    assert setup_lights["light.desk"].calls == [
        {"brightness": 255, "color_temp_kelvin": 3000}
    ]


async def test_unmanaged_lights_untouched(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    await add_profile(hass, {"entity_id": ["light.desk"]})

    await turn_on(hass, ["light.desk", "light.hall"], transition=2)
    assert setup_lights["light.desk"].calls == [
        {"brightness": 255, "color_temp_kelvin": 3000, "transition": 2}
    ]
    assert setup_lights["light.hall"].calls == [{"transition": 2}]


async def test_flash_and_effect_pass_through(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    await add_profile(hass, ALL)
    await turn_on(hass, "light.desk", flash="short")
    assert setup_lights["light.desk"].calls == [{"flash": "short"}]


async def test_unload_removes_interceptor(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    original = hass.services._services["light"]["turn_on"]
    original_off = hass.services._services["light"]["turn_off"]
    original_toggle = hass.services._services["light"]["toggle"]
    entry = await add_profile(hass, ALL)
    assert hass.services._services["light"]["turn_on"] is not original
    assert hass.services._services["light"]["turn_off"] is not original_off
    assert hass.services._services["light"]["toggle"] is not original_toggle

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.services._services["light"]["turn_on"] is original
    assert hass.services._services["light"]["turn_off"] is original_off
    assert hass.services._services["light"]["toggle"] is original_toggle

    await turn_on(hass, "light.desk")
    assert setup_lights["light.desk"].calls == [{}]


async def test_interceptor_fails_loudly(
    hass: HomeAssistant, setup_lights: dict[str, MockLight]
) -> None:
    del hass.services._services["light"]["turn_on"]
    entry = MockConfigEntry(domain=DOMAIN, title="Main", options=make_options(ALL))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert "internals changed" in (entry.reason or "")


async def _light_group(hass: HomeAssistant, members: list[str]) -> str:
    group = MockConfigEntry(
        domain="group",
        title="Living",
        options={
            "group_type": "light",
            "name": "Living",
            "entities": members,
            "hide_members": False,
            "all": False,
        },
    )
    group.add_to_hass(hass)
    assert await hass.config_entries.async_setup(group.entry_id)
    await hass.async_block_till_done()
    return "light.living"


async def test_group_members_managed_individually(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    group = await _light_group(hass, ["light.desk", "light.narrow"])
    entry = await add_profile(hass, {"entity_id": [group]})
    assert set(entry.runtime_data.lights) == {"light.desk", "light.narrow"}

    await turn_on(hass, group)
    # Filled once per member through the group's forwarded call.
    assert setup_lights["light.desk"].calls == [{"brightness": 255, "color_temp_kelvin": 3000}]
    assert setup_lights["light.narrow"].calls == [{"brightness": 255, "color_temp_kelvin": 3000}]


async def test_group_and_member_in_one_call(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-11-10 03:00:00+01:00")
    group = await _light_group(hass, ["light.desk", "light.narrow"])
    await add_profile(hass, {"entity_id": [group]})

    await turn_on(hass, [group, "light.desk"])
    adapted = [c for c in setup_lights["light.desk"].calls if c]
    assert adapted == [{"brightness": 76, "color_temp_kelvin": 2200}]
    assert [c for c in setup_lights["light.narrow"].calls if c] == [
        {"brightness": 76, "color_temp_kelvin": 2700}
    ]


async def test_group_membership_change(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    group = await _light_group(hass, ["light.desk"])
    entry = await add_profile(hass, {"entity_id": [group]})
    assert set(entry.runtime_data.lights) == {"light.desk"}

    group_entry = hass.config_entries.async_entries("group")[0]
    hass.config_entries.async_update_entry(
        group_entry, options={**group_entry.options, "entities": ["light.desk", "light.sofa"]}
    )
    # The group's options flow reloads it; do the same here.
    await hass.config_entries.async_reload(group_entry.entry_id)
    await hass.async_block_till_done()
    assert set(entry.runtime_data.lights) == {"light.desk", "light.sofa"}


async def test_toggle_group(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    group = await _light_group(hass, ["light.desk", "light.narrow"])
    await add_profile(hass, {"entity_id": [group]})

    await toggle(hass, group)
    assert setup_lights["light.desk"].calls == [{"brightness": 255, "color_temp_kelvin": 3000}]
    assert setup_lights["light.narrow"].calls == [{"brightness": 255, "color_temp_kelvin": 3000}]

    await toggle(hass, group)
    assert hass.states.get("light.desk").state == "off"
    assert hass.states.get("light.narrow").state == "off"
