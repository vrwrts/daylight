"""Periodic updates, manual control, night mode and daylight.resume."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.light import ColorMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import (
    async_fire_time_changed,
    setup_test_component_platform,
)

from custom_components.daylight.const import DOMAIN

from .conftest import NOON, MockLight, add_profile, turn_off, turn_on

TARGET = {"entity_id": ["light.desk", "light.sofa"]}


def settle(light_state) -> None:
    """Pretend our last command was long ago, outside the quiet window."""
    light_state.last_sent_at -= 3600


async def tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_periodic_update(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-11-10 19:00:00+01:00")
    await add_profile(hass, TARGET)
    desk = setup_lights["light.desk"]
    await turn_on(hass, "light.desk")
    assert desk.calls == [{"brightness": 255, "color_temp_kelvin": 3000}]

    # Still on the plateau: nothing would change, so nothing is sent.
    await tick(hass, freezer, timedelta(seconds=61))
    assert len(desk.calls) == 1

    # Halfway through the evening ramp: new values with the configured transition.
    await tick(hass, freezer, timedelta(hours=3, seconds=-61))
    assert desk.calls[-1]["transition"] == 10
    assert desk.calls[-1]["color_temp_kelvin"] == 2293
    # Lights that are off get nothing.
    assert setup_lights["light.sofa"].calls == []


async def test_external_change_is_manual_until_off(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-11-10 21:00:00+01:00")
    entry = await add_profile(hass, TARGET)
    desk = setup_lights["light.desk"]
    state = entry.runtime_data.lights["light.desk"]
    await turn_on(hass, "light.desk")

    # A remote press during the transition is ignored (quiet window).
    desk.external(brightness=50)
    await hass.async_block_till_done()
    assert not state.manual

    settle(state)
    # Within tolerance: ignored.
    desk.external(brightness=245)
    await hass.async_block_till_done()
    assert not state.manual

    desk.external(brightness=120)
    await hass.async_block_till_done()
    assert state.manual

    calls = len(desk.calls)
    await tick(hass, freezer, timedelta(hours=1))
    assert len(desk.calls) == calls

    await turn_off(hass, "light.desk")
    assert not state.manual


async def test_colour_change_is_manual(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    entry = await add_profile(hass, TARGET)
    state = entry.runtime_data.lights["light.desk"]
    await turn_on(hass, "light.desk")
    settle(state)
    setup_lights["light.desk"].external(color_mode=ColorMode.HS, hs_color=(10, 80))
    await hass.async_block_till_done()
    assert state.manual


async def test_timeout_mode(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    entry = await add_profile(hass, TARGET, manual_control={"mode": "timeout", "timeout": 30})
    desk = setup_lights["light.desk"]
    state = entry.runtime_data.lights["light.desk"]
    await turn_on(hass, "light.desk", brightness_pct=20)
    assert state.manual

    await tick(hass, freezer, timedelta(minutes=20))
    # A new manual change restarts the timer.
    desk.external(brightness=10)
    await hass.async_block_till_done()
    await tick(hass, freezer, timedelta(minutes=20))
    assert state.manual

    await tick(hass, freezer, timedelta(minutes=11))
    assert not state.manual
    assert desk.calls[-1] == {"brightness": 255, "color_temp_kelvin": 3000, "transition": 10}


async def test_turning_off_clears_timeout(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    entry = await add_profile(hass, TARGET, manual_control={"mode": "timeout"})
    state = entry.runtime_data.lights["light.desk"]
    await turn_on(hass, "light.desk", brightness_pct=20)
    await turn_off(hass, "light.desk")
    assert not state.manual
    assert state.cancel_timer is None


async def test_external_turn_on_is_adapted(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    entry = await add_profile(hass, TARGET)
    desk = setup_lights["light.desk"]
    desk.external(is_on=True, brightness=20, color_temp_kelvin=5000)
    await hass.async_block_till_done()
    assert desk.calls == [{"brightness": 255, "color_temp_kelvin": 3000}]
    assert not entry.runtime_data.lights["light.desk"].manual


async def test_light_on_at_start_is_adapted(
    hass: HomeAssistant, lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    lights["light.desk"] = MockLight("desk", on=True)
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    setup_test_component_platform(hass, "light", list(lights.values()))
    assert await async_setup_component(hass, "light", {"light": {"platform": "test"}})
    await hass.async_block_till_done()

    await add_profile(hass, TARGET)
    assert lights["light.desk"].calls == [{"brightness": 255, "color_temp_kelvin": 3000}]


@pytest.mark.parametrize("by", ["target", "profile"])
async def test_resume(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory, by: str
) -> None:
    freezer.move_to(NOON)
    entry = await add_profile(hass, TARGET)
    await turn_on(hass, "light.desk", brightness_pct=20)
    assert entry.runtime_data.lights["light.desk"].manual

    data = {"entity_id": "light.desk"} if by == "target" else {"config_entry_id": entry.entry_id}
    await hass.services.async_call(DOMAIN, "resume", data, blocking=True)
    await hass.async_block_till_done()
    assert not entry.runtime_data.lights["light.desk"].manual
    assert setup_lights["light.desk"].calls[-1] == {
        "brightness": 255,
        "color_temp_kelvin": 3000,
        "transition": 10,
    }


async def test_resume_needs_target(
    hass: HomeAssistant, setup_lights: dict[str, MockLight]
) -> None:
    await add_profile(hass, TARGET)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "resume", {}, blocking=True)


async def test_night_mode(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"sleep_mode": {}}})
    entry = await add_profile(hass, TARGET, night_mode={"entity": "input_boolean.sleep_mode"})
    await turn_on(hass, ["light.desk", "light.sofa"])
    await turn_on(hass, "light.sofa", brightness_pct=40)  # sofa now manual

    await hass.services.async_call(
        "input_boolean", "turn_on", {"entity_id": "input_boolean.sleep_mode"}, blocking=True
    )
    await hass.async_block_till_done()
    assert setup_lights["light.desk"].calls[-1] == {
        "brightness": 3,
        "color_temp_kelvin": 2200,
        "transition": 10,
    }
    assert setup_lights["light.sofa"].calls[-1] == {"brightness": 102, "color_temp_kelvin": 3000}

    # Manual control still works in night mode.
    state = entry.runtime_data.lights["light.desk"]
    settle(state)
    setup_lights["light.desk"].external(brightness=200)
    await hass.async_block_till_done()
    assert state.manual

    await hass.services.async_call(
        "input_boolean", "turn_off", {"entity_id": "input_boolean.sleep_mode"}, blocking=True
    )
    await hass.async_block_till_done()
    assert setup_lights["light.desk"].calls[-1]["brightness"] == 3


async def test_schedule_entity(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-11-10 06:30:00+01:00")
    hass.states.async_set("sensor.next_alarm", "unavailable", {"device_class": "timestamp"})
    entry = await add_profile(hass, TARGET, schedule={"wake_entity": "sensor.next_alarm"})
    profile = entry.runtime_data
    # Falls back to 07:00: still night.
    assert profile.update_target() == (30, 2000)

    await turn_on(hass, "light.desk")
    # Alarm at 05:30 UTC (06:30 local) tomorrow: the day starts now.
    hass.states.async_set(
        "sensor.next_alarm", "2026-11-11T05:30:00+00:00", {"device_class": "timestamp"}
    )
    await hass.async_block_till_done()
    assert profile.target == (65, 2000)
    assert setup_lights["light.desk"].calls[-1] == {
        "brightness": 166,
        "color_temp_kelvin": 2200,
        "transition": 10,
    }
