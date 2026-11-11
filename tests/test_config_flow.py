"""Config and options flows."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.daylight.const import (
    CONF_LIGHTS,
    DEFAULT_OPTIONS,
    DOMAIN,
    SECTION_BRIGHTNESS,
    SECTION_SCHEDULE,
)

from .conftest import MockLight, add_profile

TARGET = {"entity_id": ["light.desk"], "label_id": ["circadian"], "area_id": ["hall"]}


async def test_user_flow(hass: HomeAssistant, setup_lights: dict[str, MockLight]) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Hallway", CONF_LIGHTS: {}}
    )
    assert result["errors"] == {CONF_LIGHTS: "no_lights"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Hallway", CONF_LIGHTS: TARGET}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hallway"
    assert result["data"] == {}
    options = result["options"]
    assert options[CONF_LIGHTS] == TARGET
    for key, value in DEFAULT_OPTIONS.items():
        assert options[key] == value


async def test_options_flow(hass: HomeAssistant, setup_lights: dict[str, MockLight]) -> None:
    entry = await add_profile(hass, {"entity_id": ["light.desk"]})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    sections = {
        key
        for key in result["data_schema"].schema
        if str(key) != CONF_LIGHTS
    }
    assert {str(s) for s in sections} == {
        "schedule", "brightness", "color_temp", "curve", "winter", "manual_control", "night_mode"
    }

    new = {key: dict(value) for key, value in entry.options.items() if key != CONF_LIGHTS}
    new[CONF_LIGHTS] = {"entity_id": ["light.desk", "light.sofa"]}

    new[SECTION_SCHEDULE] = {"wake_time": "07:00:00", "sleep_time": "07:00:00"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], new)
    assert result["errors"] == {"base": "same_times"}

    new[SECTION_SCHEDULE] = {
        "wake_time": "06:30:00",
        "wake_entity": "sensor.next_alarm",
        "sleep_time": "00:30:00",
    }
    new[SECTION_BRIGHTNESS] = {"wake": 20, "peak": 60, "sleep": 5}
    result = await hass.config_entries.options.async_configure(result["flow_id"], new)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options[CONF_LIGHTS] == {"entity_id": ["light.desk", "light.sofa"]}
    assert entry.options[SECTION_SCHEDULE]["wake_entity"] == "sensor.next_alarm"
    assert entry.options[SECTION_BRIGHTNESS] == {"wake": 20, "peak": 60, "sleep": 5}
    # Saving reloads the profile with the new lights.
    assert set(entry.runtime_data.lights) == {"light.desk", "light.sofa"}
