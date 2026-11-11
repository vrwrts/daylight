"""Conditions on whether Daylight is adapting a light."""

from __future__ import annotations

from typing import Unpack, cast, override

import probatio

from homeassistant.const import CONF_OPTIONS, CONF_TARGET
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.condition import (
    ATTR_BEHAVIOR,
    BEHAVIOR_ALL,
    BEHAVIOR_ANY,
    Condition,
    ConditionCheckParams,
    ConditionConfig,
)
from homeassistant.helpers.typing import ConfigType

from .hub import DATA_HUB
from .trigger import resolve_lights

CONDITION_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_TARGET): cv.TARGET_FIELDS,
        probatio.Required(CONF_OPTIONS, default={}): {
            probatio.Required(ATTR_BEHAVIOR, default=BEHAVIOR_ANY): probatio.In(
                [BEHAVIOR_ANY, BEHAVIOR_ALL]
            ),
        },
    }
)


class StatusCondition(Condition):
    """Passes when lights in the target have the given Daylight status."""

    _status: str

    @override
    @classmethod
    async def async_validate_config(
        cls, hass: HomeAssistant, config: ConfigType
    ) -> ConfigType:
        """Validate config."""
        return cast(ConfigType, CONDITION_SCHEMA(config))

    def __init__(self, hass: HomeAssistant, config: ConditionConfig) -> None:
        """Initialise."""
        super().__init__(hass, config)
        assert config.target is not None and config.options is not None
        self._target = config.target
        self._match = all if config.options[ATTR_BEHAVIOR] == BEHAVIOR_ALL else any

    @override
    def _async_check(self, **kwargs: Unpack[ConditionCheckParams]) -> bool:
        """Check the lights."""
        lights = resolve_lights(self._hass, self._target)
        if not lights or (hub := self._hass.data.get(DATA_HUB)) is None:
            return False
        return self._match(hub.status(e) == self._status for e in lights)


class IsAdaptingCondition(StatusCondition):
    """A profile owns the light and it isn't under manual control."""

    _status = "adapting"


class IsManuallyControlledCondition(StatusCondition):
    """A profile owns the light and it is under manual control."""

    _status = "manual"


CONDITIONS: dict[str, type[Condition]] = {
    "is_adapting": IsAdaptingCondition,
    "is_manually_controlled": IsManuallyControlledCondition,
}


async def async_get_conditions(hass: HomeAssistant) -> dict[str, type[Condition]]:
    """Return the conditions for Daylight."""
    return CONDITIONS
