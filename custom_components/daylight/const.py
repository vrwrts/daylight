"""Constants for Daylight."""

from typing import Final

DOMAIN: Final = "daylight"

CONF_LIGHTS: Final = "lights"

SECTION_SCHEDULE: Final = "schedule"
CONF_WAKE_TIME: Final = "wake_time"
CONF_WAKE_ENTITY: Final = "wake_entity"
CONF_SLEEP_TIME: Final = "sleep_time"
CONF_SLEEP_ENTITY: Final = "sleep_entity"

SECTION_BRIGHTNESS: Final = "brightness"
SECTION_COLOR_TEMP: Final = "color_temp"
CONF_WAKE: Final = "wake"
CONF_PEAK: Final = "peak"
CONF_SLEEP: Final = "sleep"

SECTION_CURVE: Final = "curve"
CONF_RAMP_DURATION: Final = "ramp_duration"
CONF_CURVE: Final = "curve"
CONF_TRANSITION: Final = "transition"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CURVE_COSINE: Final = "cosine"
CURVE_LINEAR: Final = "linear"

SECTION_WINTER: Final = "winter"
CONF_ENABLED: Final = "enabled"
CONF_WAKE_BRIGHTNESS: Final = "wake_brightness"
CONF_PEAK_BRIGHTNESS: Final = "peak_brightness"

SECTION_MANUAL: Final = "manual_control"
CONF_MODE: Final = "mode"
CONF_TIMEOUT: Final = "timeout"
CONF_BRIGHTNESS_TOLERANCE: Final = "brightness_tolerance"
CONF_COLOR_TEMP_TOLERANCE: Final = "color_temp_tolerance"
MODE_UNTIL_OFF: Final = "until_off"
MODE_TIMEOUT: Final = "timeout"

SECTION_NIGHT: Final = "night_mode"
CONF_ENTITY: Final = "entity"
CONF_BRIGHTNESS: Final = "brightness"
CONF_COLOR_TEMP: Final = "color_temp"

DEFAULT_OPTIONS: Final = {
    SECTION_SCHEDULE: {CONF_WAKE_TIME: "07:00:00", CONF_SLEEP_TIME: "23:00:00"},
    SECTION_BRIGHTNESS: {CONF_WAKE: 65, CONF_PEAK: 100, CONF_SLEEP: 30},
    SECTION_COLOR_TEMP: {CONF_WAKE: 2000, CONF_PEAK: 3000, CONF_SLEEP: 2000},
    SECTION_CURVE: {
        CONF_RAMP_DURATION: 120,
        CONF_CURVE: CURVE_COSINE,
        CONF_TRANSITION: 10,
        CONF_UPDATE_INTERVAL: 60,
    },
    SECTION_WINTER: {
        CONF_ENABLED: False,
        CONF_WAKE_BRIGHTNESS: 90,
        CONF_PEAK_BRIGHTNESS: 100,
    },
    SECTION_MANUAL: {
        CONF_MODE: MODE_UNTIL_OFF,
        CONF_TIMEOUT: 30,
        CONF_BRIGHTNESS_TOLERANCE: 6,
        CONF_COLOR_TEMP_TOLERANCE: 150,
    },
    SECTION_NIGHT: {CONF_BRIGHTNESS: 1, CONF_COLOR_TEMP: 2000},
}

SERVICE_RESUME: Final = "resume"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"

SIGNAL_MANUAL_CONTROL: Final = f"{DOMAIN}_manual_control"

REASON_EXPLICIT_VALUES: Final = "explicit_values"
REASON_EXTERNAL_CHANGE: Final = "external_change"
REASON_TURNED_OFF: Final = "turned_off"
REASON_TIMEOUT: Final = "timeout"
REASON_RESUME: Final = "resume"

# Seconds after our own command during which reported changes are not treated
# as manual, on top of the transition (JEHA uses the same margin).
QUIET_WINDOW_MARGIN: Final = 5

# Longest an intercepted turn_off waits for our own command to the same light
# to finish, so a slow integration can't hold up the turn_off for long.
OFF_WAIT_TIMEOUT: Final = 2
