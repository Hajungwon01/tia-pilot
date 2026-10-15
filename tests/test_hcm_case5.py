"""좌회전 CASE 5(맨 왼쪽 전용 + 공용 좌회전 2차로, 직좌 동시신호)를 편람 <예제 2>(PDF 358~363쪽, 편람 332~337쪽)로 검증한다.

예제 2: 네갈래, 동서 접근로 CASE 2(양방보호, 우회전 도류화), 남북 접근로 CASE 5(N=5, 동시신호), 주기 120초, PHF 0.95.
편람 표의 E_R 값(NB 1.91, SB 2.11)은 N_T=N(=5)으로 계산한 값이고, 식 8-11 해설과 설계분석 예제(편람 277쪽)는 N_T=N−1이다.
엔진은 식 해설(N_T=N−1)을 따르고, 예제의 표값은 `through_capable_lanes`를 N으로 바꿔 재현해 CASE 5의 나머지 부분을 검증한다.
"""
import pytest

from app import hcm_signal as H
from app.hcm_signal import DetailedApproach, DetailedIntersection, Phase, analyze_detailed


def ex2() -> DetailedIntersection:
    common = dict(topology="four_way", ped_green_s=0, coordinated=True, offset_s=30)
    ew = dict(common, lanes=4, left_case=2, left_phase=0, phase=1, right_channelized=True, lane_width_m=3.4, left_radius_m=18,
              heavy_pct=5, bus_stops_vph=60, bus_distance_m=60, bus_class="bay", link_length_m=600, speed_kph=70, ped_green_s=37)
    ns = dict(common, lanes=5, left_case=5, lane_width_m=3.3, left_radius_m=20, heavy_pct=5, bus_distance_m=60, bus_class="large",
              link_length_m=500, speed_kph=60, ped_green_s=27)
    aps = [
        DetailedApproach(name="EB", v_left=490, v_through=1700, v_right=200, ped_per_hour=300, **ew),
        DetailedApproach(name="WB", v_left=441, v_through=1600, v_right=1186, u_turn=80, ped_per_hour=400,
                         initial_queue={"전용LT": 8}, **ew),
        DetailedApproach(name="NB", v_left=160, v_through=1200, v_right=350, entering_vph=30, exiting_vph=40, bus_stops_vph=18,
                         ped_per_hour=250, phase=2, initial_queue={"실질RT": 12}, **{k: v for k, v in ns.items() if k != "phase"}),
        DetailedApproach(name="SB", v_left=400, v_through=1300, v_right=200, u_turn=60, entering_vph=20, exiting_vph=50, bus_stops_vph=18,
                         ped_per_hour=200, phase=3, **{k: v for k, v in ns.items() if k != "phase"}),
    ]
    return DetailedIntersection(name="가×나", cycle=120, phf=0.95, peak="pm",
                                phases=[Phase(green=17), Phase(green=37), Phase(green=27), Phase(green=27)], approaches=aps)


@pytest.fixture(scope="module")
def manual_style():
    """편람 예제 표와 같은 N_T=N(E_R 표값 재현)으로 계산."""
    mp = pytest.MonkeyPatch()
    mp.setattr(H, "through_capable_lanes", lambda a: a.lanes)
    try:
        res = analyze_detailed(ex2())  # 패치는 계산하는 동안만 켠다(모듈 끝까지 켜 두면 다른 테스트가 오염된다)
    finally:
        mp.undo()
    return res, {ap.name: ap for ap in res.approaches}


def group(res, label):
    return next(g for g in res.groups if g.approach == label[0] and g.label == label[1])


# ── 편람 332~336쪽 표의 중간값 ──
def test_nb_intermediate_values_match_manual(manual_style):
    _, ap = manual_style
    d = ap["NB"].detail
    assert d["FU"] == pytest.approx(1.02) and d["FR"] == 0.5
    assert d["VL"] == pytest.approx(168, abs=0.6) and d["VTh"] == pytest.approx(1288, abs=1) and d["VR"] == pytest.approx(184, abs=0.5)
    assert (d["El"], d["Ep"], d["Eu"]) == (1.02, 1.05, 1.0) and d["EL"] == pytest.approx(1.07, abs=0.005)  # 표 8-7·8-9·8-10
    assert d["VLF"] == pytest.approx(115, abs=0.5) and d["VRF"] == pytest.approx(53, abs=1.0)  # 식 8-14·8-16(편람 값은 반올림한 중간값으로 계산)
    assert d["VSTL"] == pytest.approx(548, abs=1.5) and d["VSTR"] == pytest.approx(12, abs=1.5)  # 식 8-18·8-20
    assert d["LH"] == pytest.approx(50, abs=1) and d["ER"] == pytest.approx(1.91, abs=0.01)


def test_sb_intermediate_values_match_manual(manual_style):
    _, ap = manual_style
    d = ap["SB"].detail
    assert d["Eu"] == pytest.approx(1.21, abs=0.005) and d["EL"] == pytest.approx(1.30, abs=0.01)  # U턴 13% → 표 8-11(2차로) 보간
    assert d["VLF"] == pytest.approx(50, abs=0.5) and d["VRF"] == pytest.approx(100, abs=1.0)
    assert d["VSTL"] == pytest.approx(319, abs=1.5) and d["VSTR"] == pytest.approx(211, abs=1.5)
    assert d["ER"] == pytest.approx(2.11, abs=0.01)


def test_case5_group_classification_matches_manual(manual_style):
    _, ap = manual_style
    nb = {g.label: g for g in ap["NB"].groups}
    assert set(nb) == {"공용LT", "실질RT"}  # V_STL>V_LF(공용 좌회전), V_STR<V_RF(실질 전용 우회전)
    assert nb["공용LT"].lanes == 4 and nb["공용LT"].volume == pytest.approx(1403, abs=2)  # N−1차로, V_Th−V_RF+V_L
    assert nb["실질RT"].lanes == 1 and nb["실질RT"].volume == pytest.approx(237, abs=1)  # V_RF+V_R
    sb = {g.label: g for g in ap["SB"].groups}
    assert set(sb) == {"통합"} and sb["통합"].lanes == 5 and sb["통합"].volume == pytest.approx(1922, abs=2)  # 모두 통합(맨 왼쪽 차로 포함 N)


# ── 지체·서비스수준(편람 336쪽) ──
def test_nb_sb_delays_and_los_match_manual(manual_style):
    _, ap = manual_style
    nb = {g.label: g for g in ap["NB"].groups}
    assert nb["공용LT"].d1 == pytest.approx(43.5, abs=0.3) and nb["공용LT"].d2 == pytest.approx(2.8, abs=0.3)
    assert nb["공용LT"].delay == pytest.approx(39.3, abs=1.0) and nb["공용LT"].los == "C"
    assert nb["실질RT"].d1 == pytest.approx(46.5, abs=0.3) and nb["실질RT"].d2 == pytest.approx(27.8, abs=1.0)
    assert nb["실질RT"].d3 == pytest.approx(93.5, abs=3.0) and nb["실질RT"].delay == pytest.approx(160.4, abs=4.0) and nb["실질RT"].los == "F"
    sb = ap["SB"].groups[0]
    assert sb.d1 == pytest.approx(45.6, abs=0.3) and sb.d2 == pytest.approx(8.1, abs=0.3) and sb.delay == pytest.approx(46.4, abs=0.8)
    assert ap["NB"].delay == pytest.approx(56.8, abs=2.0) and ap["SB"].delay == pytest.approx(46.4, abs=0.8)


def test_whole_intersection_matches_manual(manual_style):
    res, ap = manual_style
    # 동서 접근로(CASE 2)는 v/c≈1 부근이라 반올림한 중간값(E_L 1.11 등)의 차이가 지체에 크게 번진다(WB 전용 좌회전 d3 포함)
    assert ap["EB"].delay == pytest.approx(43.9, abs=1.5) and ap["WB"].delay == pytest.approx(65.3, abs=5.0)
    assert ap["EB"].los == "C" and ap["WB"].los == "D"
    assert res.delay == pytest.approx(53.5, abs=1.5) and res.los == "D"


# ── 식 해설(N_T=N−1)을 따르는 엔진 ──
def test_engine_follows_formula_text_nt_equals_n_minus_1_and_differs_from_table_value():
    ix = ex2()
    res = analyze_detailed(ix)
    nb = next(a for a in res.approaches if a.name == "NB")
    assert H.through_capable_lanes(ix.approaches[2]) == 4 and H.through_capable_lanes(ix.approaches[0]) == 4  # CASE 5는 5−1, CASE 2(N=4)는 N
    assert nb.detail["ER"] == pytest.approx(1.85, abs=0.01)  # 표의 1.91은 N_T=N=5로 계산한 값
    assert {g.label for g in nb.groups} == {"공용LT", "실질RT"}  # 분류는 같다
    assert res.los == "D" and abs(res.delay - 53.5) < 6  # 식 해설을 따라도 교차로 결과는 크게 달라지지 않는다


# ── CASE 5 고유 동작 ──
def test_case5_requires_four_way_and_at_least_four_lanes():
    with pytest.raises(ValueError, match="4개 이상"):
        DetailedApproach(name="A", left_case=5, lanes=3, v_left=100, v_through=500)
    with pytest.raises(ValueError, match="네갈래"):
        DetailedApproach(name="A", topology="t_no_right", left_case=5, lanes=4, v_left=100, v_through=500)


def one(**kw):
    base = dict(name="A", topology="four_way", left_case=5, lanes=5, v_left=160, v_through=1200, v_right=350, phase=0)
    base.update(kw)
    ix = DetailedIntersection(name="t", cycle=120, phf=1.0, phases=[Phase(green=60)], approaches=[DetailedApproach(**base)])
    return analyze_detailed(ix).approaches[0]


def test_equilibrium_property_of_vstl_and_vstr():
    """V_STL·V_STR은 '모든 차로의 부하가 같다'는 가정에서 나온 값이어야 한다(식 8-18·8-20 유도 검산)."""
    d = one(v_right=200).detail
    N, EL, ER, VTh, VL, VR = 5, d["EL"], d["ER"], d["VTh"], d["VL"], d["VR"]
    X = (VTh + ER * VR + EL * VL) / N  # 차로당 부하
    assert d["VSTL"] == pytest.approx(2 * X - EL * VL)  # 전용+공용 두 좌회전 차로가 같은 부하 X
    assert d["VSTR"] == pytest.approx(X - ER * VR)


def test_without_left_traffic_leftmost_lane_is_unused_and_n_minus_1_lanes_serve_through():
    ap = one(v_left=0)
    assert sum(g.lanes for g in ap.groups) == 4  # 5차로 중 맨 왼쪽 전용 차로는 비어 있다


def test_very_heavy_left_makes_two_lane_de_facto_left_group():
    ap = one(v_left=1500, v_through=300, v_right=0, lanes=5)
    g = {g.label: g for g in ap.groups}
    assert "실질LT" in g and g["실질LT"].lanes == 2 and g["직진"].lanes == 3


def test_case5_pipeline_stage_analysis_runs():
    import asyncio

    from app.pipeline import TIAPipeline
    from app.schemas import ProjectInput
    from app.state import ReportState
    ix = ex2()
    apps = [a.model_copy(update={"project_share_through": 0.05}) for a in ix.approaches]
    st = asyncio.run(TIAPipeline().run(ReportState(project=ProjectInput(name="t", address="서울", households=1000),
                                                    detailed_intersections=[ix.model_copy(update={"approaches": apps})],
                                                    background_growth_rate=0.01)))
    assert st.stages["가×나"][1]["with"]["avg_delay"] > 0
    assert not any("CASE 5" in w and "미지원" in w for w in st.warnings)
