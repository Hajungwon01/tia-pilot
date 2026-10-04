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
    # 도로용량편람(2013) <표 8-2> (원문 확인): A≤15, B≤30, C≤50, D≤70, E≤100, F≤220, FF≤340, FFF>340 (초/대)
    for delay, grade in [(15, "A"), (15.1, "B"), (30, "B"), (30.1, "C"), (50, "C"), (50.1, "D"),
                         (70, "D"), (70.1, "E"), (100, "E"), (100.1, "F"), (220, "F"), (220.1, "FF"),
                         (340, "FF"), (340.1, "FFF")]:
        assert los_from_delay(delay) == grade, (delay, grade)


def test_incremental_delay_matches_manual_worked_example():
    # 도로용량편람 2013 p.271 예제: 공용 좌회전 차로군 X=0.61, c=1,136vph, T=0.25h → d2 = 2.4초/대 (원문)
    import math
    X, c, T = 0.61, 1136, 0.25
    d2_manual_formula = 900 * T * ((X - 1) + math.sqrt((X - 1) ** 2 + 4 * X / (c * T)))
    assert d2_manual_formula == pytest.approx(2.4, abs=0.15)
    # 구현(analyze_approach)의 d2와 같은 값인지: g/C → 0 근사가 아니라 식 자체를 대조
    from app.los import analyze_approach
    # S=1800, C=100, g=c*C/S 로 용량 c를 맞추고 V=X*c. d1을 빼고 d2만 비교한다.
    g = c * 100 / 1800
    a = Approach(name="LT", volume=X * c, saturation_flow=1800, green_time=g)
    res = analyze_approach(a, cycle=100)
    g_c = g / 100
    d1 = 0.5 * 100 * (1 - g_c) ** 2 / (1 - min(1.0, X) * g_c)
    assert res.delay - d1 == pytest.approx(d2_manual_formula, abs=1e-6)


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
