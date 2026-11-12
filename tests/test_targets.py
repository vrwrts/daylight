"""Target resolution and overlapping profiles."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    entity_registry as er,
    floor_registry as fr,
    issue_registry as ir,
    label_registry as lr,
)

from custom_components.daylight.const import DOMAIN

from .conftest import NOON, MockLight, add_profile, turn_on


async def test_area_and_floor_targets(
    hass: HomeAssistant, setup_lights: dict[str, MockLight]
) -> None:
    floor = fr.async_get(hass).async_create("Ground floor")
    kitchen = ar.async_get(hass).async_create("Kitchen", floor_id=floor.floor_id)
    office = ar.async_get(hass).async_create("Office")
    entities = er.async_get(hass)
    entities.async_update_entity("light.desk", area_id=office.id)
    entities.async_update_entity("light.sofa", area_id=kitchen.id)

    by_area = await add_profile(hass, {"area_id": [office.id]}, title="Area")
    by_floor = await add_profile(hass, {"floor_id": [floor.floor_id]}, title="Floor")
    assert set(by_area.runtime_data.lights) == {"light.desk"}
    assert set(by_floor.runtime_data.lights) == {"light.sofa"}

    # Moving a light to another area moves it between profiles.
    entities.async_update_entity("light.desk", area_id=kitchen.id)
    await hass.async_block_till_done()
    assert set(by_area.runtime_data.lights) == set()
    assert set(by_floor.runtime_data.lights) == {"light.desk", "light.sofa"}


async def test_label_joins_and_leaves(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    label = lr.async_get(hass).async_create("Circadian")
    entry = await add_profile(hass, {"label_id": [label.label_id]})
    assert entry.runtime_data.lights == {}

    sofa = setup_lights["light.sofa"]
    await turn_on(hass, "light.sofa")
    assert sofa.calls == [{}]

    entities = er.async_get(hass)
    entities.async_update_entity("light.sofa", labels={label.label_id})
    await hass.async_block_till_done()
    assert set(entry.runtime_data.lights) == {"light.sofa"}
    # It was on, so it's adapted as soon as it joins.
    assert sofa.calls[-1] == {"brightness": 255, "color_temp_kelvin": 3000}

    entities.async_update_entity("light.sofa", labels=set())
    await hass.async_block_till_done()
    assert entry.runtime_data.lights == {}


async def test_overlapping_profiles(
    hass: HomeAssistant, setup_lights: dict[str, MockLight], freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    older = await add_profile(hass, {"entity_id": ["light.desk", "light.sofa"]}, title="Normal")
    freezer.tick(timedelta(seconds=1))
    newer = await add_profile(
        hass,
        {"entity_id": ["light.desk", "light.hall"]},
        title="Dimmed",
        brightness={"peak": 20},
    )

    # The oldest profile wins; the other leaves the light alone.
    assert set(older.runtime_data.lights) == {"light.desk", "light.sofa"}
    assert set(newer.runtime_data.lights) == {"light.hall"}
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"overlap_{newer.subentry_id}")
    assert issue is not None
    assert "light.desk (owned by Normal)" in issue.translation_placeholders["lights"]
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"overlap_{older.subentry_id}") is None

    await turn_on(hass, ["light.desk", "light.hall"])
    assert setup_lights["light.desk"].calls == [{"brightness": 255, "color_temp_kelvin": 3000}]
    assert setup_lights["light.hall"].calls == [{"brightness": 51, "color_temp_kelvin": 3000}]

    # Removing the older profile hands the light over and clears the issue.
    hass.config_entries.async_remove_subentry(older.entry, older.subentry_id)
    await hass.async_block_till_done()
    assert set(newer.runtime_data.lights) == {"light.desk", "light.hall"}
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"overlap_{newer.subentry_id}") is None
    assert setup_lights["light.desk"].calls[-1] == {"brightness": 51, "color_temp_kelvin": 3000}
