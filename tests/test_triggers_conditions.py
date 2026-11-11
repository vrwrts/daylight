"""Manual-control triggers and Daylight conditions."""

from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er, label_registry as lr
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import async_mock_service

from custom_components.daylight.const import DOMAIN

from .conftest import NOON, MockLight, add_profile, turn_off, turn_on

TARGET = {"entity_id": ["light.desk", "light.sofa"]}


async def _automations(
    hass: HomeAssistant,
    *triggers: tuple[str, dict[str, Any]],
    condition: dict[str, Any] | None = None,
) -> list[ServiceCall]:
    calls = async_mock_service(hass, "test", "automation")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "triggers": [{"trigger": f"{DOMAIN}.{trigger}", "target": target}],
                    "conditions": [condition] if condition else [],
                    "actions": [
                        {
                            "action": "test.automation",
                            "data": {
                                "trigger": trigger,
                                "entity_id": "{{ trigger.entity_id }}",
                                "reason": "{{ trigger.reason }}",
                                "profile": "{{ trigger.profile }}",
                            },
                        }
                    ],
                }
                for trigger, target in triggers
            ]
        },
    )
    await hass.async_block_till_done()
    return calls


def _reasons(calls: list[ServiceCall], trigger: str) -> list[str]:
    return [c.data["reason"] for c in calls if c.data["trigger"] == trigger]


async def test_started_and_ended(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    await add_profile(hass, TARGET, title="Normal")
    desk = {"entity_id": "light.desk"}
    calls = await _automations(
        hass, ("manual_control_started", desk), ("manual_control_ended", desk)
    )

    await turn_on(hass, "light.sofa", brightness_pct=30)  # not in the trigger's target
    assert calls == []

    await turn_on(hass, "light.desk", brightness_pct=30)
    assert [c.data for c in calls] == [
        {
            "trigger": "manual_control_started",
            "entity_id": "light.desk",
            "reason": "explicit_values",
            "profile": "Normal",
        }
    ]

    await turn_off(hass, "light.desk")
    assert _reasons(calls, "manual_control_ended") == ["turned_off"]

    await turn_on(hass, "light.desk")
    state = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.lights["light.desk"]
    state.last_sent_at -= 3600
    setup_lights["light.desk"].external(brightness=20)
    await hass.async_block_till_done()
    assert _reasons(calls, "manual_control_started") == ["explicit_values", "external_change"]

    await hass.services.async_call(DOMAIN, "resume", {"entity_id": "light.desk"}, blocking=True)
    await hass.async_block_till_done()
    assert _reasons(calls, "manual_control_ended") == ["turned_off", "resume"]


async def test_trigger_label_target_in_night_mode(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"sleep_mode": {"initial": True}}}
    )
    label = lr.async_get(hass).async_create("Bedroom")
    await add_profile(hass, TARGET, night_mode={"entity": "input_boolean.sleep_mode"})
    started = await _automations(hass, ("manual_control_started", {"label_id": label.label_id}))

    # The label is added after the automation was set up.
    er.async_get(hass).async_update_entity("light.sofa", labels={label.label_id})
    await hass.async_block_till_done()
    await turn_on(hass, "light.sofa", color_temp_kelvin=4000)
    assert [c.data["entity_id"] for c in started] == ["light.sofa"]


@pytest.mark.parametrize(
    ("condition", "behavior", "target", "expected"),
    [
        ("is_adapting", "any", ["light.sofa"], True),  # off, not manual
        ("is_adapting", "any", ["light.desk"], False),  # manual
        ("is_adapting", "any", ["light.hall"], False),  # in no profile
        ("is_adapting", "any", ["light.desk", "light.sofa"], True),
        ("is_adapting", "all", ["light.desk", "light.sofa"], False),
        ("is_manually_controlled", "any", ["light.desk"], True),
        ("is_manually_controlled", "any", ["light.sofa"], False),
        ("is_manually_controlled", "any", ["light.hall"], False),
        ("is_manually_controlled", "all", ["light.desk", "light.sofa"], False),
    ],
)
async def test_conditions(
    hass: HomeAssistant,
    setup_lights: dict[str, MockLight],
    freezer: FrozenDateTimeFactory,
    condition: str,
    behavior: str,
    target: list[str],
    expected: bool,
) -> None:
    freezer.move_to(NOON)
    await add_profile(hass, TARGET)
    calls = await _automations(
        hass,
        ("manual_control_started", {"entity_id": "light.desk"}),
        condition={
            "condition": f"{DOMAIN}.{condition}",
            "target": {"entity_id": target},
            "options": {"behavior": behavior},
        },
    )
    # Firing the trigger also makes light.desk manual before the check.
    await turn_on(hass, "light.desk", brightness_pct=30)
    assert bool(calls) is expected
