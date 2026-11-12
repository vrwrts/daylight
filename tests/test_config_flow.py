"""Config, options and profile subentry flows."""

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.daylight.const import (
    CONF_LIGHTS,
    DEFAULT_CENTRAL,
    DEFAULT_PROFILE,
    DOMAIN,
    SECTION_BRIGHTNESS,
    SECTION_SCHEDULE,
    SUBENTRY_PROFILE,
)

from .conftest import MockLight, add_profile

TARGET = {"entity_id": ["light.desk"], "label_id": ["circadian"], "area_id": ["hall"]}


async def test_user_flow(hass: HomeAssistant, setup_lights: dict[str, MockLight]) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Daylight"
    assert result["data"] == {}
    assert result["options"] == DEFAULT_CENTRAL
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow(hass: HomeAssistant, setup_lights: dict[str, MockLight]) -> None:
    profile = await add_profile(hass, {"entity_id": ["light.desk"]})
    entry = profile.entry
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert {str(key) for key in result["data_schema"].schema} == {
        "schedule", "curve", "winter", "manual_control", "night_mode"
    }

    new = {key: dict(value) for key, value in entry.options.items()}
    new[SECTION_SCHEDULE] = {"wake_time": "07:00:00", "sleep_time": "07:00:00"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], new)
    assert result["errors"] == {"base": "same_times"}

    new[SECTION_SCHEDULE] = {
        "wake_time": "06:30:00",
        "wake_entity": "sensor.next_alarm",
        "sleep_time": "00:30:00",
    }
    new["night_mode"] = {"entity": "input_boolean.sleep_mode"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], new)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options[SECTION_SCHEDULE]["wake_entity"] == "sensor.next_alarm"
    assert entry.options["night_mode"] == {"entity": "input_boolean.sleep_mode"}
    # Saving reloads the entry, so the profile runs with the new settings.
    assert profile.runtime_data.schedule["wake_entity"] == "sensor.next_alarm"
    assert profile.runtime_data.night == {
        "entity": "input_boolean.sleep_mode", "brightness": 1, "color_temp": 2000
    }


async def test_add_profile(hass: HomeAssistant, setup_lights: dict[str, MockLight]) -> None:
    existing = await add_profile(hass, {"entity_id": ["light.sofa"]})
    entry = existing.entry
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PROFILE), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert {str(key) for key in result["data_schema"].schema} == {
        "name", "lights", "brightness", "color_temp", "winter", "night_mode"
    }

    values = {
        "name": "Hallway",
        CONF_LIGHTS: {},
        **{key: dict(value) for key, value in DEFAULT_PROFILE.items()},
    }
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], values)
    assert result["errors"] == {CONF_LIGHTS: "no_lights"}

    values[CONF_LIGHTS] = TARGET
    values[SECTION_BRIGHTNESS] = {"wake": 20, "peak": 60, "sleep": 5}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], values)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    subentry = list(entry.subentries.values())[-1]
    assert subentry.title == "Hallway"
    assert subentry.subentry_type == SUBENTRY_PROFILE
    assert subentry.data[CONF_LIGHTS] == TARGET
    assert subentry.data[SECTION_BRIGHTNESS] == {"wake": 20, "peak": 60, "sleep": 5}
    assert "name" not in subentry.data
    # Adding a profile reloads the entry, which now runs both.
    assert set(entry.runtime_data) == set(entry.subentries)
    assert set(existing.runtime_data.lights) == {"light.sofa"}
    assert set(entry.runtime_data[subentry.subentry_id].lights) == {"light.desk"}


async def test_reconfigure_profile(
    hass: HomeAssistant, setup_lights: dict[str, MockLight]
) -> None:
    profile = await add_profile(hass, {"entity_id": ["light.desk"]})
    entry = profile.entry
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PROFILE),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": profile.subentry_id},
    )
    assert result["type"] is FlowResultType.FORM

    values = {
        "name": "Desk",
        CONF_LIGHTS: {"entity_id": ["light.desk", "light.sofa"]},
        **{key: dict(value) for key, value in DEFAULT_PROFILE.items()},
    }
    values[SECTION_BRIGHTNESS] = {"wake": 20, "peak": 60, "sleep": 5}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], values)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    subentry = entry.subentries[profile.subentry_id]
    assert subentry.title == "Desk"
    assert subentry.data[SECTION_BRIGHTNESS] == {"wake": 20, "peak": 60, "sleep": 5}
    assert set(profile.runtime_data.lights) == {"light.desk", "light.sofa"}
    assert profile.runtime_data.brightness == {"wake": 20, "peak": 60, "sleep": 5}
