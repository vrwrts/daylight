"""Curve maths."""

from datetime import time

import pytest

from homeassistant.core import HomeAssistant

from custom_components.daylight.curve import (
    CurveSettings,
    blend,
    daylight_hours,
    target,
    winter_weight,
)
from custom_components.daylight.profile import time_of_day


def settings(wake: str = "07:00", sleep: str = "23:00", ramp: float = 120, cosine: bool = True) -> CurveSettings:
    def minutes(value: str) -> float:
        hours, mins = value.split(":")
        return int(hours) * 60 + int(mins)

    return CurveSettings(
        wake=minutes(wake),
        sleep=minutes(sleep),
        brightness=(65, 100, 30),
        kelvin=(2000, 3000, 2000),
        ramp=ramp,
        cosine=cosine,
    )


def at(curve: CurveSettings, clock: str) -> tuple[float, float]:
    hours, mins = clock.split(":")
    return target(curve, int(hours) * 60 + int(mins))


@pytest.mark.parametrize(
    ("clock", "expected"),
    [
        ("03:00", (30, 2000)),
        ("06:59", (30, 2000)),
        ("07:00", (65, 2000)),
        ("08:00", (82.5, 2500)),
        ("09:00", (100, 3000)),
        ("14:00", (100, 3000)),
        ("21:00", (100, 3000)),
        ("23:00", (30, 2000)),
    ],
)
def test_phases(clock: str, expected: tuple[float, float]) -> None:
    assert at(settings(), clock) == pytest.approx(expected)


def test_cosine_morning_eases_in_and_out() -> None:
    brightness, _ = at(settings(), "07:30")
    assert brightness == pytest.approx(65 + 35 * 0.146447, abs=1e-3)


def test_cosine_evening_eases_out() -> None:
    # Halfway through the evening ramp, sin(pi/4) of the way to sleep values.
    brightness, kelvin = at(settings(), "22:00")
    assert brightness == pytest.approx(100 - 70 * 0.707107, abs=1e-3)
    assert kelvin == pytest.approx(3000 - 1000 * 0.707107, abs=1e-2)


def test_linear() -> None:
    curve = settings(cosine=False)
    assert at(curve, "07:30") == pytest.approx((73.75, 2250))
    assert at(curve, "22:30") == pytest.approx((47.5, 2250))


def test_sleep_after_midnight() -> None:
    curve = settings(sleep="01:00")
    assert at(curve, "22:00") == pytest.approx((100, 3000))
    assert at(curve, "00:00")[0] == pytest.approx(100 - 70 * 0.707107, abs=1e-3)
    assert at(curve, "01:00") == pytest.approx((30, 2000))
    assert at(curve, "05:00") == pytest.approx((30, 2000))


def test_wake_after_sleep() -> None:
    # Night shift: awake from 20:00 until 12:00 the next day.
    curve = settings(wake="20:00", sleep="12:00")
    assert at(curve, "20:00") == pytest.approx((65, 2000))
    assert at(curve, "03:00") == pytest.approx((100, 3000))
    assert at(curve, "13:00") == pytest.approx((30, 2000))


def test_ramps_shrink_when_they_overlap() -> None:
    curve = settings(wake="07:00", sleep="09:00")
    assert at(curve, "07:30") == pytest.approx((82.5, 2500))
    assert at(curve, "08:00") == pytest.approx((100, 3000))
    assert at(curve, "09:00") == pytest.approx((30, 2000))


def test_no_ramp() -> None:
    assert at(settings(ramp=0), "07:00") == pytest.approx((100, 3000))


def test_equal_times_hold_sleep_values() -> None:
    assert at(settings(wake="07:00", sleep="07:00"), "12:00") == pytest.approx((30, 2000))


@pytest.mark.parametrize(
    ("latitude", "day", "low", "high"),
    [
        (0, 80, 12.0, 12.3),
        (52.37, 355, 7.5, 8.0),
        (52.37, 172, 16.6, 17.0),
        (70, 355, 0, 0),
        (70, 172, 24, 24),
    ],
)
def test_daylight_hours(latitude: float, day: int, low: float, high: float) -> None:
    assert low <= daylight_hours(latitude, day) <= high


def test_winter_weight_and_blend() -> None:
    assert winter_weight(20) == 0
    assert winter_weight(4) == 1
    assert winter_weight(12) == pytest.approx(0.5)
    assert blend(65, 90, 0.5) == pytest.approx(77.5)
    # Amsterdam in December lifts wake brightness most of the way.
    weight = winter_weight(daylight_hours(52.37, 355))
    assert 0.8 < weight < 0.9


@pytest.mark.parametrize(
    ("value", "minutes"),
    [
        ("2026-11-11T05:45:00+00:00", 405),  # timestamp sensor, tomorrow, UTC
        ("2026-11-11 06:30:00", 390),  # input_datetime with date and time
        ("07:15:00", 435),  # time entity or time-only input_datetime
        ("unavailable", 420),
        ("unknown", 420),
        ("not a time", 420),
        ("2026-11-11", 420),  # date-only input_datetime
        (None, 420),
    ],
)
async def test_time_of_day(hass: HomeAssistant, value: str | None, minutes: float) -> None:
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    assert time_of_day(value, time(7, 0)) == minutes
