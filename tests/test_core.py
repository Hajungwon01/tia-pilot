import pytest

from app.los import analyze_approach, analyze_intersection, los_from_delay
from app.schemas import Approach, ProjectInput
from app.trip_generation import estimate_trips

RATES = {
    "_status": "TEST",
    "apartment": {
        "daily_person_trips_per_household": 10.0,
        "mode_share": {"car": 0.5},
        "car_occupancy": 1.0,
        "peak_hour": {
            "am": {"ratio_of_daily": 0.1, "in_ratio": 0.3},
            "pm": {"ratio_of_daily": 0.1, "in_ratio": 0.6},
        },
    },
}


def test_trip_generation_hand_calc():
    r = estimate_trips(ProjectInput(name="t", address="서울", households=300), RATES)
    assert r.daily_person_trips == 3000
    assert r.daily_vehicle_trips == 1500
    assert r.am_peak.in_trips == pytest.approx(45)
    assert r.am_peak.out_trips == pytest.approx(105)
    assert r.pm_peak.total == pytest.approx(150)
    assert r.rates_status == "TEST"


def test_default_rates_flagged_provisional():
    r = estimate_trips(ProjectInput(name="t", address="서울", households=300))
    assert r.rates_status == "PROVISIONAL"


def test_los_grade_boundaries():
    assert los_from_delay(10) == "A"
    assert los_from_delay(10.1) == "B"
    assert los_from_delay(80) == "E"
    assert los_from_delay(80.1) == "F"


def test_low_volume_is_good_los():
    res = analyze_approach(Approach(name="N", volume=100, saturation_flow=1800, green_time=30), cycle=100)
    assert res.vc_ratio == pytest.approx(100 / 540)
    assert res.los in ("B", "C")


def test_oversaturated_is_f():
    res = analyze_approach(Approach(name="N", volume=700, saturation_flow=1800, green_time=30), cycle=100)
    assert res.vc_ratio > 1
    assert res.los == "F"


def test_delay_monotonic_in_volume():
    d = [
        analyze_approach(Approach(name="N", volume=v, saturation_flow=1800, green_time=40), cycle=120).delay
        for v in (100, 300, 500, 700)
    ]
    assert d == sorted(d)


def test_intersection_weighted():
    aps = [
        Approach(name="N", volume=100, saturation_flow=1800, green_time=40),
        Approach(name="E", volume=600, saturation_flow=1800, green_time=40),
    ]
    results, avg, grade = analyze_intersection(aps, cycle=120)
    assert len(results) == 2
    assert results[0].delay < avg < results[1].delay
    assert grade == los_from_delay(avg)


def test_invalid_green():
    with pytest.raises(ValueError):
        analyze_approach(Approach(name="N", volume=1, saturation_flow=1800, green_time=100), cycle=100)
