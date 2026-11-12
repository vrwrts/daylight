"""Merge version 1 entries, one per profile, into one entry with profile subentries."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_LIGHTS,
    DEFAULT_CENTRAL,
    DEFAULT_PROFILE,
    DOMAIN,
    SUBENTRY_PROFILE,
)

_LOGGER = logging.getLogger(__name__)


def _shared(options: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    # Everything that isn't a profile value, so optional entity keys come along.
    return {
        name: {
            key: value
            for key, value in options.get(name, {}).items()
            if key not in DEFAULT_PROFILE.get(name, {})
        }
        for name in DEFAULT_CENTRAL
    }


def _own(options: Mapping[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {CONF_LIGHTS: options[CONF_LIGHTS]}
    for name, defaults in DEFAULT_PROFILE.items():
        values = options.get(name, {})
        data[name] = {key: values.get(key, default) for key, default in defaults.items()}
    return data


async def async_merge_entries(hass: HomeAssistant) -> None:
    """Merge all version 1 entries into one, before any entry is set up.

    The oldest enabled entry is kept and its shared settings win, so Daylight
    stays enabled. Every old entry, disabled ones included, becomes a profile
    in creation order, which keeps which profile owns a light in two of them.
    """
    old = sorted(
        (e for e in hass.config_entries.async_entries(DOMAIN, include_ignore=False) if e.version == 1),
        key=lambda e: e.created_at,
    )
    if not old:
        return
    kept = next((e for e in old if e.disabled_by is None), old[0])
    source = kept.title
    shared = _shared(kept.options)
    # Read before the kept entry's options are replaced.
    profiles = [(entry.title, _own(entry.options)) for entry in old]

    dropped = []
    for entry in old:
        if differ := sorted(
            name for name, values in _shared(entry.options).items() if values != shared[name]
        ):
            dropped.append(f"{entry.title} ({', '.join(differ)})")

    hass.config_entries.async_update_entry(
        kept, version=2, title="Daylight", data={}, options=shared
    )
    for title, data in profiles:
        hass.config_entries.async_add_subentry(
            kept,
            ConfigSubentry(
                data=MappingProxyType(data),
                subentry_type=SUBENTRY_PROFILE,
                title=title,
                unique_id=None,
            ),
        )
    for entry in old:
        ir.async_delete_issue(hass, DOMAIN, f"overlap_{entry.entry_id}")
        if entry is not kept:
            await hass.config_entries.async_remove(entry.entry_id)

    _LOGGER.info("Merged %d Daylight entries into profiles of one entry", len(old))
    if dropped:
        _LOGGER.warning(
            "These profiles had their own schedule, curve, manual control, winter or"
            " night mode settings, which are now shared and taken from %s: %s",
            source,
            "; ".join(dropped),
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            "migration_dropped_settings",
            config_entry_id=kept.entry_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="migration_dropped_settings",
            translation_placeholders={"source": source, "profiles": "; ".join(dropped)},
        )

