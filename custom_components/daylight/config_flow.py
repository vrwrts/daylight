"""Config and options flows for Daylight."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import probatio

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TargetSelector,
    TargetSelectorConfig,
    TextSelector,
    TimeSelector,
)
from homeassistant.helpers.target import TargetSelection

from .const import (
    CONF_BRIGHTNESS,
    CONF_BRIGHTNESS_TOLERANCE,
    CONF_COLOR_TEMP,
    CONF_COLOR_TEMP_TOLERANCE,
    CONF_CURVE,
    CONF_ENABLED,
    CONF_ENTITY,
    CONF_LIGHTS,
    CONF_MODE,
    CONF_PEAK,
    CONF_PEAK_BRIGHTNESS,
    CONF_RAMP_DURATION,
    CONF_SLEEP,
    CONF_SLEEP_ENTITY,
    CONF_SLEEP_TIME,
    CONF_TIMEOUT,
    CONF_TRANSITION,
    CONF_UPDATE_INTERVAL,
    CONF_WAKE,
    CONF_WAKE_BRIGHTNESS,
    CONF_WAKE_ENTITY,
    CONF_WAKE_TIME,
    CURVE_COSINE,
    CURVE_LINEAR,
    DEFAULT_OPTIONS,
    DOMAIN,
    MODE_TIMEOUT,
    MODE_UNTIL_OFF,
    SECTION_BRIGHTNESS,
    SECTION_COLOR_TEMP,
    SECTION_CURVE,
    SECTION_MANUAL,
    SECTION_NIGHT,
    SECTION_SCHEDULE,
    SECTION_WINTER,
)

LIGHTS_SELECTOR = TargetSelector(TargetSelectorConfig(entity={"domain": "light"}))
SCHEDULE_ENTITY_SELECTOR = EntitySelector(
    EntitySelectorConfig(
        filter=[
            {"domain": "sensor", "device_class": "timestamp"},
            {"domain": "input_datetime"},
            {"domain": "time"},
        ]
    )
)
NIGHT_ENTITY_SELECTOR = EntitySelector(
    EntitySelectorConfig(domain=["input_boolean", "binary_sensor", "switch"])
)


def _number(low: float, high: float, unit: str, step: float = 1) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=low, max=high, step=step, unit_of_measurement=unit, mode=NumberSelectorMode.BOX
        )
    )


PERCENT = _number(1, 100, "%")
KELVIN = _number(1000, 10000, "K", 50)


def _select(options: list[str], key: str) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options, translation_key=key, mode=SelectSelectorMode.DROPDOWN
        )
    )


def _optional_entity(key: str, values: dict[str, Any]) -> probatio.Optional:
    # Suggested rather than default, so the field can be cleared.
    return probatio.Optional(key, description={"suggested_value": values.get(key)})


def _options_schema(options: dict[str, Any]) -> probatio.Schema:
    s = options[SECTION_SCHEDULE]
    b = options[SECTION_BRIGHTNESS]
    k = options[SECTION_COLOR_TEMP]
    c = options[SECTION_CURVE]
    w = options[SECTION_WINTER]
    m = options[SECTION_MANUAL]
    n = options[SECTION_NIGHT]
    return probatio.Schema(
        {
            probatio.Required(CONF_LIGHTS, default=options[CONF_LIGHTS]): LIGHTS_SELECTOR,
            probatio.Required(SECTION_SCHEDULE): section(
                probatio.Schema(
                    {
                        probatio.Required(CONF_WAKE_TIME, default=s[CONF_WAKE_TIME]): TimeSelector(),
                        _optional_entity(CONF_WAKE_ENTITY, s): SCHEDULE_ENTITY_SELECTOR,
                        probatio.Required(CONF_SLEEP_TIME, default=s[CONF_SLEEP_TIME]): TimeSelector(),
                        _optional_entity(CONF_SLEEP_ENTITY, s): SCHEDULE_ENTITY_SELECTOR,
                    }
                )
            ),
            probatio.Required(SECTION_BRIGHTNESS): section(
                probatio.Schema(
                    {
                        probatio.Required(key, default=b[key]): PERCENT
                        for key in (CONF_WAKE, CONF_PEAK, CONF_SLEEP)
                    }
                )
            ),
            probatio.Required(SECTION_COLOR_TEMP): section(
                probatio.Schema(
                    {
                        probatio.Required(key, default=k[key]): KELVIN
                        for key in (CONF_WAKE, CONF_PEAK, CONF_SLEEP)
                    }
                )
            ),
            probatio.Required(SECTION_CURVE): section(
                probatio.Schema(
                    {
                        probatio.Required(
                            CONF_RAMP_DURATION, default=c[CONF_RAMP_DURATION]
                        ): _number(0, 720, "min"),
                        probatio.Required(CONF_CURVE, default=c[CONF_CURVE]): _select(
                            [CURVE_COSINE, CURVE_LINEAR], CONF_CURVE
                        ),
                        probatio.Required(
                            CONF_TRANSITION, default=c[CONF_TRANSITION]
                        ): _number(0, 300, "s"),
                        probatio.Required(
                            CONF_UPDATE_INTERVAL, default=c[CONF_UPDATE_INTERVAL]
                        ): _number(5, 3600, "s"),
                    }
                )
            ),
            probatio.Required(SECTION_WINTER): section(
                probatio.Schema(
                    {
                        probatio.Required(CONF_ENABLED, default=w[CONF_ENABLED]): BooleanSelector(),
                        probatio.Required(
                            CONF_WAKE_BRIGHTNESS, default=w[CONF_WAKE_BRIGHTNESS]
                        ): PERCENT,
                        probatio.Required(
                            CONF_PEAK_BRIGHTNESS, default=w[CONF_PEAK_BRIGHTNESS]
                        ): PERCENT,
                    }
                ),
                {"collapsed": True},
            ),
            probatio.Required(SECTION_MANUAL): section(
                probatio.Schema(
                    {
                        probatio.Required(CONF_MODE, default=m[CONF_MODE]): _select(
                            [MODE_UNTIL_OFF, MODE_TIMEOUT], CONF_MODE
                        ),
                        probatio.Required(CONF_TIMEOUT, default=m[CONF_TIMEOUT]): _number(
                            1, 1440, "min"
                        ),
                        probatio.Required(
                            CONF_BRIGHTNESS_TOLERANCE, default=m[CONF_BRIGHTNESS_TOLERANCE]
                        ): _number(0, 50, "%"),
                        probatio.Required(
                            CONF_COLOR_TEMP_TOLERANCE, default=m[CONF_COLOR_TEMP_TOLERANCE]
                        ): _number(0, 2000, "K", 10),
                    }
                )
            ),
            probatio.Required(SECTION_NIGHT): section(
                probatio.Schema(
                    {
                        _optional_entity(CONF_ENTITY, n): NIGHT_ENTITY_SELECTOR,
                        probatio.Required(CONF_BRIGHTNESS, default=n[CONF_BRIGHTNESS]): PERCENT,
                        probatio.Required(CONF_COLOR_TEMP, default=n[CONF_COLOR_TEMP]): KELVIN,
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


def _has_lights(target: dict[str, Any] | None) -> bool:
    return bool(target) and TargetSelection(target).has_any_target


class DaylightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a profile."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for name and lights."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if _has_lights(user_input[CONF_LIGHTS]):
                options = deepcopy(DEFAULT_OPTIONS)
                options[CONF_LIGHTS] = user_input[CONF_LIGHTS]
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data={}, options=options
                )
            errors[CONF_LIGHTS] = "no_lights"
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_NAME): TextSelector(),
                        probatio.Required(CONF_LIGHTS): LIGHTS_SELECTOR,
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DaylightOptionsFlow:
        """Return the options flow."""
        return DaylightOptionsFlow()


class DaylightOptionsFlow(OptionsFlowWithReload):
    """Edit a profile."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show all settings, grouped in sections."""
        errors: dict[str, str] = {}
        current = self.config_entry.options
        if user_input is not None:
            schedule = user_input[SECTION_SCHEDULE]
            if not _has_lights(user_input.get(CONF_LIGHTS)):
                errors[CONF_LIGHTS] = "no_lights"
            elif schedule[CONF_WAKE_TIME] == schedule[CONF_SLEEP_TIME]:
                errors["base"] = "same_times"
            else:
                return self.async_create_entry(data=user_input)
            current = user_input
        return self.async_show_form(
            step_id="init", data_schema=_options_schema(dict(current)), errors=errors
        )
