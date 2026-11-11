"""Circadian curve, ported from JEHA (src/circadian/curve.rs and season.rs).

Pure functions without Home Assistant imports. Times are minutes since local
midnight, brightness is in percent and colour temperature in kelvin.
"""

from dataclasses import dataclass
import math

MINUTES_PER_DAY = 1440

SUNRISE_ALTITUDE_DEG = -0.833
LONG_DAY_HOURS = 18.0
SHORT_DAY_HOURS = 6.0


@dataclass(frozen=True, slots=True)
class CurveSettings:
    """Inputs for one curve evaluation."""

    wake: float
    sleep: float
    brightness: tuple[float, float, float]  # wake, peak, sleep
    kelvin: tuple[float, float, float]  # wake, peak, sleep
    ramp: float
    cosine: bool


def _factor(t: float, cosine: bool, morning: bool) -> float:
    if not cosine:
        return t
    # JEHA eases in and out in the morning, but only eases out in the evening.
    if morning:
        return (1 - math.cos(t * math.pi)) / 2
    return math.sin(t * math.pi / 2)


def _lerp(start: float, end: float, factor: float) -> float:
    return start + (end - start) * factor


def target(settings: CurveSettings, now: float) -> tuple[float, float]:
    """Return (brightness %, kelvin) at `now`.

    JEHA compares clock times directly, so a sleep time after midnight puts
    the whole day at night values. Measuring everything from wake time
    instead handles sleep after midnight and wake after sleep.
    """
    b_wake, b_peak, b_sleep = settings.brightness
    k_wake, k_peak, k_sleep = settings.kelvin

    day = (settings.sleep - settings.wake) % MINUTES_PER_DAY
    position = (now - settings.wake) % MINUTES_PER_DAY
    if day == 0 or position >= day:
        return b_sleep, k_sleep

    # JEHA jumps when the two ramps overlap; shrink them to meet instead.
    ramp = min(settings.ramp, day / 2)
    if ramp > 0 and position < ramp:
        f = _factor(position / ramp, settings.cosine, morning=True)
        return _lerp(b_wake, b_peak, f), _lerp(k_wake, k_peak, f)
    if ramp > 0 and position >= day - ramp:
        f = _factor((position - (day - ramp)) / ramp, settings.cosine, morning=False)
        return _lerp(b_peak, b_sleep, f), _lerp(k_peak, k_sleep, f)
    return b_peak, k_peak


def daylight_hours(latitude: float, day_of_year: int) -> float:
    """Hours between sunrise and sunset (JEHA season.rs)."""
    declination = math.radians(-23.44) * math.cos(
        2 * math.pi * (day_of_year + 10) / 365
    )
    lat = math.radians(latitude)
    cos_hour_angle = (
        math.sin(math.radians(SUNRISE_ALTITUDE_DEG))
        - math.sin(lat) * math.sin(declination)
    ) / (math.cos(lat) * math.cos(declination))
    if cos_hour_angle <= -1:
        return 24.0
    if cos_hour_angle >= 1:
        return 0.0
    return 2 * math.degrees(math.acos(cos_hour_angle)) / 15


def winter_weight(hours: float) -> float:
    """0 at 18 or more hours of daylight, 1 at 6 or fewer, linear between."""
    weight = (LONG_DAY_HOURS - hours) / (LONG_DAY_HOURS - SHORT_DAY_HOURS)
    return min(max(weight, 0.0), 1.0)


def blend(regular: float, winter: float, weight: float) -> float:
    """Blend a regular brightness toward its winter value."""
    return regular + (winter - regular) * weight
