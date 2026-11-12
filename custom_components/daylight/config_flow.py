"""Config, options and profile subentry flows for Daylight."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import probatio

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
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
    DEFAULT_CENTRAL,
    DEFAULT_PROFILE,
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
    SUBENTRY_PROFILE,
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


def _central_schema(options: dict[str, Any]) -> probatio.Schema:
    s = options[SECTION_SCHEDULE]
    c = options[SECTION_CURVE]
    w = options[SECTION_WINTER]
    m = options[SECTION_MANUAL]
    n = options[SECTION_NIGHT]
    return probatio.Schema(
        {
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
                    {probatio.Required(CONF_ENABLED, default=w[CONF_ENABLED]): BooleanSelector()}
                )
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
                probatio.Schema({_optional_entity(CONF_ENTITY, n): NIGHT_ENTITY_SELECTOR})
            ),
        }
    )


def _profile_schema(values: dict[str, Any]) -> probatio.Schema:
    b = values[SECTION_BRIGHTNESS]
    k = values[SECTION_COLOR_TEMP]
    w = values[SECTION_WINTER]
    n = values[SECTION_NIGHT]
    return probatio.Schema(
        {
            probatio.Required(
                CONF_NAME, description={"suggested_value": values.get(CONF_NAME)}
            ): TextSelector(),
            probatio.Required(
                CONF_LIGHTS, description={"suggested_value": values.get(CONF_LIGHTS)}
            ): LIGHTS_SELECTOR,
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
            probatio.Required(SECTION_WINTER): section(
                probatio.Schema(
                    {
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
            probatio.Required(SECTION_NIGHT): section(
                probatio.Schema(
                    {
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
    """Create the Daylight entry that holds the shared settings."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry with defaults; profiles are added to it afterwards."""
        return self.async_create_entry(
            title="Daylight", data={}, options=deepcopy(DEFAULT_CENTRAL)
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DaylightOptionsFlow:
        """Return the options flow."""
        return DaylightOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Profiles are subentries."""
        return {SUBENTRY_PROFILE: ProfileSubentryFlow}


class DaylightOptionsFlow(OptionsFlow):
    """Edit the shared settings. The entry's update listener reloads it."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the shared settings, grouped in sections."""
        errors: dict[str, str] = {}
        current = self.config_entry.options
        if user_input is not None:
            schedule = user_input[SECTION_SCHEDULE]
            if schedule[CONF_WAKE_TIME] == schedule[CONF_SLEEP_TIME]:
                errors["base"] = "same_times"
            else:
                return self.async_create_entry(data=user_input)
            current = user_input
        return self.async_show_form(
            step_id="init", data_schema=_central_schema(dict(current)), errors=errors
        )


class ProfileSubentryFlow(ConfigSubentryFlow):
    """Add or change a profile."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for name, lights and the profile's values."""
        return await self._async_step_form("user", deepcopy(DEFAULT_PROFILE), user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a profile."""
        subentry = self._get_reconfigure_subentry()
        values = {CONF_NAME: subentry.title, **subentry.data}
        return await self._async_step_form("reconfigure", values, user_input)

    async def _async_step_form(
        self, step_id: str, values: dict[str, Any], user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(user_input)
            title = data.pop(CONF_NAME)
            if _has_lights(data.get(CONF_LIGHTS)):
                if step_id == "user":
                    return self.async_create_entry(title=title, data=data)
                return self.async_update_and_abort(
                    self._get_entry(),
                    self._get_reconfigure_subentry(),
                    title=title,
                    data=data,
                )
            errors[CONF_LIGHTS] = "no_lights"
            values = user_input
        return self.async_show_form(
            step_id=step_id, data_schema=_profile_schema(values), errors=errors
        )
