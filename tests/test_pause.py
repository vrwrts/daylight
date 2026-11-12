"""daylight.pause, and the updates profiles share."""

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.daylight.const import DOMAIN

from .conftest import NOON, MockLight, add_profile, turn_off, turn_on
from .test_manual import tick
from .test_triggers_conditions import _automations, _reasons

TARGET = {"entity_id": ["light.desk", "light.sofa"]}
ADAPTED = {"brightness": 255, "color_temp_kelvin": 3000}


async def _pause(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(DOMAIN, "pause", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


async def _resume(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(DOMAIN, "resume", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


async def test_pause_until_resume(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    profile = await add_profile(hass, TARGET, manual_control={"mode": "timeout", "timeout": 30})
    desk = setup_lights["light.desk"]
    desk_calls = await _automations(
        hass,
        ("manual_control_started", {"entity_id": "light.desk"}),
        ("manual_control_ended", {"entity_id": "light.desk"}),
    )
    await turn_on(hass, "light.desk")
    await _pause(hass, "light.desk")
    state = profile.runtime_data.lights["light.desk"]
    assert state.manual and state.paused
    assert _reasons(desk_calls, "manual_control_started") == ["paused"]

    # Turning off, a manual change and the timeout don't end a pause.
    await turn_off(hass, "light.desk")
    await turn_on(hass, "light.desk")
    assert desk.calls[-1] == {}
    desk.external(brightness=10)
    await hass.async_block_till_done()
    await tick(hass, freezer, timedelta(minutes=31))
    assert state.manual and state.paused
    assert state.cancel_timer is None
    assert desk.calls[-1] == {}
    assert _reasons(desk_calls, "manual_control_ended") == []

    await _resume(hass, "light.desk")
    assert not state.manual and not state.paused
    assert desk.calls[-1] == {**ADAPTED, "transition": 10}
    assert _reasons(desk_calls, "manual_control_ended") == ["resume"]
    assert profile.runtime_data.hub.paused == set()


async def test_pause_survives_reload_and_restart(
    hass: HomeAssistant,
    setup_lights: dict[str, MockLight],
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    freezer.move_to(NOON)
    # Paused before the last restart.
    hass_storage[DOMAIN] = {
        "version": 1,
        "minor_version": 1,
        "key": DOMAIN,
        "data": {"paused": ["light.desk"]},
    }
    profile = await add_profile(hass, TARGET)
    assert profile.runtime_data.lights["light.desk"].paused
    await turn_on(hass, ["light.desk", "light.sofa"])
    assert setup_lights["light.desk"].calls == [{}]
    assert setup_lights["light.sofa"].calls == [ADAPTED]

    await _pause(hass, "light.sofa")
    await tick(hass, freezer, timedelta(seconds=2))
    assert hass_storage[DOMAIN]["data"] == {"paused": ["light.desk", "light.sofa"]}

    assert await hass.config_entries.async_reload(profile.entry.entry_id)
    await hass.async_block_till_done()
    lights = profile.runtime_data.lights
    assert lights["light.desk"].paused and lights["light.sofa"].paused

    await _resume(hass, "light.desk")
    await tick(hass, freezer, timedelta(seconds=2))
    assert hass_storage[DOMAIN]["data"] == {"paused": ["light.sofa"]}


async def test_pause_counts_as_manual(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    await add_profile(hass, TARGET)
    calls = await _automations(
        hass,
        ("manual_control_started", {"entity_id": "light.desk"}),
        condition={
            "condition": f"{DOMAIN}.is_manually_controlled",
            "target": {"entity_id": "light.desk"},
        },
    )
    await _pause(hass, "light.desk")
    assert _reasons(calls, "manual_control_started") == ["paused"]


async def test_pause_ignores_other_lights(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    profile = await add_profile(hass, TARGET)
    await _pause(hass, "light.hall")
    assert profile.runtime_data.hub.paused == set()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "pause", {}, blocking=True)


async def test_removing_daylight_forgets_pauses(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    profile = await add_profile(hass, TARGET)
    hub = profile.runtime_data.hub
    await _pause(hass, "light.desk")
    await hass.config_entries.async_remove(profile.entry.entry_id)
    await hass.async_block_till_done()
    assert hub.paused == set()

    profile = await add_profile(hass, TARGET)
    assert not profile.runtime_data.lights["light.desk"].manual


async def test_profiles_share_updates(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-11-10 19:00:00+01:00")
    hass.states.async_set("input_boolean.sleep_mode", "off")
    await add_profile(
        hass, {"entity_id": ["light.desk"]}, night_mode={"entity": "input_boolean.sleep_mode"}
    )
    await add_profile(
        hass, {"entity_id": ["light.sofa"]}, title="Dimmed", brightness={"peak": 20, "sleep": 10}
    )
    desk, sofa = setup_lights["light.desk"], setup_lights["light.sofa"]
    await turn_on(hass, ["light.desk", "light.sofa"])

    # The shared interval moves both profiles along the evening ramp.
    await tick(hass, freezer, timedelta(seconds=61))
    await tick(hass, freezer, timedelta(hours=3, seconds=-61))
    assert desk.calls[-1]["color_temp_kelvin"] == sofa.calls[-1]["color_temp_kelvin"] == 2293
    assert desk.calls[-1]["brightness"] > sofa.calls[-1]["brightness"]

    # The shared night mode entity switches both, each to its own night values.
    hass.states.async_set("input_boolean.sleep_mode", "on")
    await hass.async_block_till_done()
    assert desk.calls[-1] == {"brightness": 3, "color_temp_kelvin": 2200, "transition": 10}
    assert sofa.calls[-1] == {"brightness": 3, "color_temp_kelvin": 2200, "transition": 10}
