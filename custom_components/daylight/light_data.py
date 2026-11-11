"""What to send to a light, given its capabilities."""

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_BRIGHTNESS_STEP,
    ATTR_BRIGHTNESS_STEP_PCT,
    ATTR_COLOR_NAME,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_MAX_COLOR_TEMP_KELVIN,
    ATTR_MIN_COLOR_TEMP_KELVIN,
    ATTR_PROFILE,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_WHITE,
    ATTR_XY_COLOR,
    brightness_supported,
    color_temp_supported,
)
from homeassistant.core import State

# Keys in light.turn_on params after HA's preprocessing (brightness_pct is
# already converted to brightness by then).
BRIGHTNESS_KEYS = frozenset(
    {ATTR_BRIGHTNESS, ATTR_BRIGHTNESS_STEP, ATTR_BRIGHTNESS_STEP_PCT, ATTR_PROFILE}
)
COLOR_KEYS = frozenset(
    {
        ATTR_COLOR_TEMP_KELVIN,
        ATTR_HS_COLOR,
        ATTR_RGB_COLOR,
        ATTR_RGBW_COLOR,
        ATTR_RGBWW_COLOR,
        ATTR_XY_COLOR,
        ATTR_WHITE,
        ATTR_COLOR_NAME,
        ATTR_PROFILE,
    }
)


def build(
    state: State,
    brightness_pct: float,
    kelvin: float,
    *,
    brightness: bool = True,
    color: bool = True,
) -> dict[str, Any]:
    """Return light.turn_on attributes for this light.

    Brightness only for dimmable lights without colour temperature, nothing
    for on/off-only lights. Kelvin is clamped to the light's range.
    """
    modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES)
    data: dict[str, Any] = {}
    if brightness and brightness_supported(modes):
        data[ATTR_BRIGHTNESS] = max(1, round(brightness_pct * 255 / 100))
    if color and color_temp_supported(modes):
        value = round(kelvin)
        low = state.attributes.get(ATTR_MIN_COLOR_TEMP_KELVIN)
        high = state.attributes.get(ATTR_MAX_COLOR_TEMP_KELVIN)
        if low is not None:
            value = max(value, low)
        if high is not None:
            value = min(value, high)
        data[ATTR_COLOR_TEMP_KELVIN] = value
    return data
