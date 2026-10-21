"""극단 입력 점검(2026-10-21 임의 입력 4,000건 + API 1,200건)에서 찾은 문제의 회귀 테스트와 무작위 입력 점검."""
import asyncio
import math
import random

import pytest

from app.hcm_signal import MIN_GROUP_FACTOR, DetailedApproach, DetailedIntersection, Phase, analyze_detailed
from app.hcm_stages import analyze_stages_detailed
from app.pipeline import TIAPipeline
from app.schemas import ProjectInput
from app.state import ReportState


def one(**kw) -> DetailedIntersection:
    base = dict(name="A", topology="four_way", left_case=6, lanes=3, v_left=100, v_through=800, v_right=200, phase=0)
    base.update(kw)
    return DetailedIntersection(name="t", cycle=120, phf=0.95, phases=[Phase(green=40), Phase(green=40)], approaches=[DetailedApproach(**base)])


def finite(res) -> bool:
    return all(math.isfinite(v) for g in res.groups for v in (g.volume, g.saturation, g.capacity, g.x, g.d1, g.d2, g.d3, g.delay))


def test_unprotected_left_equivalent_never_below_one_even_with_tiny_left_volume():
    """식 8-5가 좌회전 1대/시·직진 5,000대/시에서 E_L=−11만처럼 음수가 되던 문제: E_L ≥ 1.0."""
    ix = one(v_left=1, v_through=5000, v_right=30, opposing_through=1464, heavy_pct=100, left_radius_m=40, u_turn=200, lanes=4)
    res = analyze_detailed(ix)
    d = res.approaches[0].detail
    assert d["El"] >= 1.0 and d["EL"] >= 1.0 and finite(res)
    assert all(g.saturation > 0 for g in res.groups)


def test_extreme_roadside_friction_is_clamped_not_negative_and_reported():
    """노변마찰이 1시간을 넘는 입력으로 전용 우회전 보정계수가 음수가 되던 문제."""
    ix = one(topology="y_dedicated", lanes=4, left_lanes=1, right_lanes=1, v_left=120, v_through=0, v_right=1,
             entering_vph=500, exiting_vph=500, bus_stops_vph=300, bus_class="large", bus_distance_m=1, parking_allowed=True, parking_vph=400, ped_per_hour=400, ped_green_s=40)  # 노변마찰 LH≈4,665초(>3,600)
    res = analyze_detailed(ix)
    ap = res.approaches[0]
    assert finite(res) and all(g.saturation > 0 for g in res.groups)
    assert ap.detail["clamped"] and any("전용RT" in c for c in ap.detail["clamped"])
    assert min(ap.detail["factors"].values()) >= MIN_GROUP_FACTOR - 1e-3


def test_normal_inputs_do_not_trigger_the_clamp():
    assert analyze_detailed(one()).approaches[0].detail["clamped"] == []
    heavy_but_real = one(topology="y_dedicated", lanes=4, left_lanes=1, right_lanes=1, v_left=120, v_through=0, v_right=1, entering_vph=80,
                         exiting_vph=80, bus_stops_vph=60, bus_class="large", bus_distance_m=1, parking_allowed=True, parking_vph=40, ped_per_hour=400, ped_green_s=40)
    ap = analyze_detailed(heavy_but_real).approaches[0]
    assert ap.detail["clamped"] == [] and ap.detail["factors"]["전용RT"] == pytest.approx(0.587, abs=0.01)  # 마찰이 커도 현실 범위면 하한에 걸리지 않는다


def test_stage_analysis_survives_nan_prone_inputs_that_used_to_crash():
    """NaN 지체가 녹색 재배분으로 번져 pf_factor에서 'cannot convert float NaN to integer'로 죽던 입력."""
    ix = one(v_left=1, v_through=5000, v_right=30, opposing_through=1464, heavy_pct=100, left_radius_m=40, u_turn=200, lanes=4,
             coordinated=True, link_length_m=400, speed_kph=50, offset_s=10)
    out = analyze_stages_detailed(ix, [1, 3], 0.02, 300.0)
    assert all(math.isfinite(st["improved"]["avg_delay"]) for st in out.values())


def test_pipeline_warns_when_a_factor_hits_the_floor():
    ix = one(topology="y_dedicated", lanes=4, left_lanes=1, right_lanes=1, v_left=120, v_through=0, v_right=1, entering_vph=500, exiting_vph=500,
             bus_stops_vph=300, bus_class="large", bus_distance_m=1, parking_allowed=True, parking_vph=400, ped_per_hour=400, ped_green_s=40,
             project_share_through=0.05)
    st = asyncio.run(TIAPipeline().run(ReportState(project=ProjectInput(name="t", address="서울", households=1000, gross_floor_area_m2=120000),
                                                    detailed_intersections=[ix], background_growth_rate=0.02)))
    assert any("보정계수가 하한(0.05)에 걸림" in w and "전용RT" in w for w in st.warnings)


def random_intersection(rng: random.Random):
    def vol(zero_p=0.25, hi=2500):
        return 0 if rng.random() < zero_p else rng.choice([1, 5, 30, 120, 400, 900, rng.uniform(0, hi), hi * 2])
    nph, cycle = rng.choice([2, 3, 4]), rng.choice([60, 90, 120, 180])
    greens = [rng.uniform(8, (cycle - 3 * nph) / nph) for _ in range(nph)]
    apps = []
    for k in range(rng.choice([1, 2, 3, 4])):
        topo = rng.choice(["four_way", "four_way", "t_no_left", "t_no_right", "y_dedicated"])
        case = rng.choice([1, 2, 3, 4, 5, 6])
        lanes = rng.choice([1, 2, 3, 4, 5, 8])
        if topo != "four_way" and case == 5:
            case = 4
        if case == 5 and lanes < 4:
            lanes = 4
        apps.append(DetailedApproach(
            name=f"A{k}", topology=topo, left_case=case, lanes=lanes, v_left=vol(), v_through=vol(0.1), v_right=vol(), u_turn=vol(0.8, 100),
            phase=rng.randrange(nph), left_phase=rng.randrange(nph), opposing_through=vol(0.3), heavy_pct=rng.choice([0, 5, 100]),
            lane_width_m=rng.choice([2.5, 3.0, 3.5]), right_channelized=rng.random() < .3, entering_vph=vol(0.7, 80), exiting_vph=vol(0.7, 80),
            bus_stops_vph=vol(0.7, 60), bus_distance_m=rng.choice([0, 30, 75]), bus_class=rng.choice(["small", "medium", "large", "bay"]),
            parking_allowed=rng.random() < .2, parking_vph=vol(0.7, 40), ped_per_hour=vol(0.5, 3500), ped_green_s=rng.choice([0, 10, 40]),
            left_lanes=rng.choice([0, 1, 2]), right_lanes=rng.choice([0, 1, 2]), left_radius_m=rng.choice([5, 12, 25, 40]),
            project_share_through=0.05, coordinated=rng.random() < .3, link_length_m=rng.choice([50, 400, 1500]), speed_kph=rng.choice([20, 50, 80]),
            offset_s=rng.uniform(-60, 60)))
    try:
        return DetailedIntersection(name="T", cycle=cycle, phf=rng.choice([0.7, 0.95, 1.0]), phases=[Phase(green=g) for g in greens], approaches=apps)
    except ValueError:
        return None  # 입력 검증이 거부한 조합


def test_random_inputs_always_give_finite_positive_results():
    """고정 시드 무작위 600건: 엔진·3단계·개선 시나리오가 어떤 유효 입력에서도 죽거나 NaN/음수를 내지 않는다."""
    rng = random.Random(20261021)
    checked = 0
    for _ in range(600):
        ix = random_intersection(rng)
        if ix is None:
            continue
        res = analyze_detailed(ix)
        assert finite(res), ix
        assert all(g.saturation > 0 and g.lanes > 0 for g in res.groups), ix
        out = analyze_stages_detailed(ix, [1, 3], 0.02, 300.0)
        for st in out.values():
            for k in ("without", "with", "improved"):
                assert math.isfinite(st[k]["avg_delay"]) and st[k]["avg_delay"] >= 0
            for s in st["scenarios"]["scenarios"]:
                assert math.isfinite(s["avg_delay"]) and s["delay_reduction"] > 0
        checked += 1
    assert checked > 450
