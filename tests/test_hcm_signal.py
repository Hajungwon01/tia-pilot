"""도로용량편람 2013 제8장 풀이 예제(EB 접근로, 편람 p.261~273)로 신호교차로 엔진을 검증한다.

편람의 중간값은 반올림된 값을 이어서 쓰므로(예: P_LT=0.14, fHV=0.96) 비반올림 계산과 소수점 아래에서 어긋난다.
허용 오차는 반올림 영향 범위(대체로 1% 이내)로 둔다.
"""
import pytest

from app import hcm_signal as H
from app.hcm_signal import DetailedApproach, DetailedIntersection, Phase


def example_intersection(**eb_over) -> DetailedIntersection:
    eb = dict(
        name="EB", topology="four_way", left_case=6, lanes=3,
        v_left=90, v_through=600, v_right=320, opposing_through=600, left_radius_m=12,
        lane_width_m=3.3, grade_pct=0, heavy_pct=5,
        entering_vph=23, exiting_vph=20, bus_stops_vph=11, bus_distance_m=30, bus_class="medium",
        parking_allowed=True, parking_vph=10, ped_per_hour=400, ped_green_s=40,
        phase=0, coordinated=True, link_length_m=400, speed_kph=50, offset_s=10,
        initial_queue={"공용LT": 40},
    )
    eb.update(eb_over)
    return DetailedIntersection(
        name="A도로×B도로", cycle=120, phf=0.95,
        phases=[Phase(green=45, yellow=3), Phase(green=20, yellow=3), Phase(green=46, yellow=3)],
        approaches=[DetailedApproach(**eb)],
    )


@pytest.fixture(scope="module")
def eb():
    ix = example_intersection()
    return H.analyze_approach(ix.approaches[0], ix)


# ── 표·보정계수 ──
def test_tables_match_manual():
    assert H.interp(H.P_TABLE, 600) == pytest.approx(1.39)  # 표 8-8
    assert H.interp(H.P_TABLE, 500) == pytest.approx((2.57 + 1.39) / 2)  # 보간
    assert [H.ep_factor(r) for r in (9, 12, 15, 18, 20, 21)] == [1.14, 1.11, 1.09, 1.06, 1.05, 1.00]  # 표 8-9
    assert H.interp(H.EU1, 15) == pytest.approx(1.30)
    assert H.interp(H.EU2, 12) == pytest.approx(1.17 + 0.2 * (1.30 - 1.17))  # 편람 예: U턴 12% ≈ 1.2
    assert [H.fc_factor(x) for x in (400, 1000, 1500, 3000, 3500)] == [0.3, 0.6, 0.8, 0.9, 1.0]  # 표 8-13
    assert [H.fw_factor(w) for w in (3.3, 3.0, 2.9, 2.7, 2.6)] == [1.0, 1.0, 0.94, 0.94, 0.88]  # 표 8-15
    assert H.fg_factor(0) == 1.0 and H.fg_factor(3) == 0.96 and H.fg_factor(6) == 0.93 and H.fg_factor(-2) == 1.0
    assert H.fhv_factor(0.05) == pytest.approx(0.9615, abs=1e-4)  # 식 8-39 (편람은 0.96으로 반올림)
    assert (H.fu_factor(1, 632), H.fu_factor(2, 700), H.fu_factor(3, 900), H.fu_factor(5, 900)) == (1.0, 1.02, 1.05, 1.08)


def test_pf_table_corners_and_manual_example():
    assert H.pf_factor(0.0, 0.1) == 1.04 and H.pf_factor(0.5, 0.5) == 1.30 and H.pf_factor(1.0, 0.9) == 1.08
    assert H.pf_factor(0.157, 0.3725) == pytest.approx(0.56, abs=0.01)  # 편람 예제 PF=0.56
    assert H.pf_factor(1.157, 0.3725) == pytest.approx(H.pf_factor(0.157, 0.3725))  # TVO 정수 보정


# ── 편람 예제: 교통량 보정·차로군 분류 (운영분석표 2) ──
def test_example_corrected_volumes(eb):
    d = eb.detail
    assert d["VL"] == pytest.approx(95, abs=0.5)
    assert d["VTh"] == pytest.approx(632, abs=0.5)
    assert d["VR"] == pytest.approx(168, abs=0.5)
    assert d["FU"] == 1.0 and d["FR"] == 0.5


def test_example_side_friction(eb):
    d = eb.detail
    assert d["Ldw"] == pytest.approx(49, abs=0.5)  # 0.9×23 + 1.4×20 = 48.7 (편람은 49로 표기)
    assert d["lb"] == pytest.approx(0.6)
    assert d["Lbb"] == pytest.approx(101, abs=0.5)  # 15.3 × 0.6 × 11
    assert d["Lp"] == pytest.approx(540)  # 360 + 18×10
    assert d["LH"] == pytest.approx(207, abs=0.5)
    assert d["fcGp"] == pytest.approx(12)


def test_example_left_and_right_equivalents(eb):
    d = eb.detail
    assert d["El"] == pytest.approx(3.39, abs=0.02)  # 식 8-5
    assert d["Ep"] == 1.11 and d["Eu"] == 1.0
    assert d["EL"] == pytest.approx(3.76, abs=0.03)
    assert d["ER"] == pytest.approx(3.00, abs=0.02)  # 식 8-11


def test_example_group_classification_inputs(eb):
    d = eb.detail
    assert d["VLF"] == pytest.approx(67, abs=1)  # 식 8-13
    assert d["VRF"] == pytest.approx(38, abs=1)  # 식 8-15
    assert d["VSTL"] == pytest.approx(141, abs=2)  # 식 8-17
    assert d["VSTR"] == pytest.approx(-6, abs=2)  # 식 8-20
    assert [g.label for g in eb.groups] == ["공용LT", "실질RT"]  # 표 8-14: 공용 좌회전 + 실질적 전용 우회전


# ── 편람 예제: 포화교통류율·용량 (운영분석표 3) ──
def test_example_saturation_and_capacity(eb):
    lt, rt = eb.groups
    assert (lt.volume, rt.volume) == (pytest.approx(689, abs=1.5), pytest.approx(206, abs=1.5))
    assert (lt.lanes, rt.lanes) == (2, 1)
    assert lt.saturation == pytest.approx(3046, rel=0.01)
    assert rt.saturation == pytest.approx(800, rel=0.01)
    assert lt.y == pytest.approx(0.226, abs=0.003) and rt.y == pytest.approx(0.258, abs=0.003)
    assert lt.g_over_c == pytest.approx(0.3725, abs=1e-4)  # (45−0.3)/120
    assert lt.capacity == pytest.approx(1136, rel=0.01) and rt.capacity == pytest.approx(298, rel=0.01)
    assert lt.x == pytest.approx(0.61, abs=0.01) and rt.x == pytest.approx(0.69, abs=0.01)


# ── 편람 예제: 지체 (운영분석표 4) ──
def test_example_delay_components(eb):
    lt, rt = eb.groups
    assert lt.d1 == pytest.approx(32.8, abs=0.5)  # 초기 대기차량 유형 I (식 8-48)
    assert rt.d1 == pytest.approx(31.8, abs=0.3)  # 식 8-47
    assert lt.d2 == pytest.approx(2.4, abs=0.2) and rt.d2 == pytest.approx(12.4, abs=0.3)  # 식 8-50
    assert lt.d3 == pytest.approx(22.7, abs=0.6) and rt.d3 == 0  # 식 8-51
    assert lt.pf == pytest.approx(0.56, abs=0.01) and rt.pf == pytest.approx(0.56, abs=0.01)


def test_example_final_delay_and_los(eb):
    lt, rt = eb.groups
    assert lt.delay == pytest.approx(43.5, abs=0.8) and rt.delay == pytest.approx(30.2, abs=0.5)
    assert lt.los == "C"
    # 우회전 차로군은 B/C 경계(30초): 편람은 반올림한 중간값으로 30.2(C), 비반올림 계산은 29.8(B)
    assert rt.los in ("B", "C")
    assert eb.delay == pytest.approx(40.4, abs=0.7)  # 접근로 지체(식 8-55, 교통량 가중평균)
    assert eb.los == "C"


# ── 기능 차이가 결과에 반영되는지(방향성) ──
def test_without_initial_queue_and_coordination_delay_changes():
    base = H.analyze_approach(example_intersection().approaches[0], example_intersection())
    ix = example_intersection(initial_queue={}, coordinated=False)
    plain = H.analyze_approach(ix.approaches[0], ix)
    lt_plain = plain.groups[0]
    assert lt_plain.d3 == 0 and lt_plain.pf == 1.0
    assert lt_plain.delay != pytest.approx(base.groups[0].delay, abs=1)


def test_initial_queue_types():
    # 식 8-44~46: Qb와 (1−X)cT 비교로 유형 선택
    V, S, g, G, C = 500, 3000, 44.7, 45, 120
    I = H._delay_components(V, S, g, G, C, 40, 1.0)
    II = H._delay_components(V, S, g, G, C, 400, 1.0)  # (1−X)cT = 약 (1−0.45)×1117×0.25=153 < 400
    III = H._delay_components(2000, S, g, G, C, 50, 1.0)  # X>1 → (1−X)cT<0
    assert I["d3"] > 0 and I["d1"] > H._delay_components(V, S, g, G, C, 0, 1.0)["d1"] * 0.5
    assert II["d1"] == pytest.approx((C - G) / 2) and III["d1"] == pytest.approx((C - G) / 2)
    assert III["d3"] == pytest.approx(3600 * 50 / (S * g / C))


# ── 케이스·형태별 ──
def simple(**kw):
    a = dict(name="X", topology="four_way", left_case=1, lanes=2, v_through=600, phase=0)
    a.update(kw)
    return DetailedIntersection(name="t", cycle=100, phf=1.0, phases=[Phase(green=40), Phase(green=20)],
                                approaches=[DetailedApproach(**a)])


def test_through_only_approach_uses_basic_saturation():
    r = H.analyze_approach(*(lambda ix: (ix.approaches[0], ix))(simple()))
    g = r.groups[0]
    assert g.label == "직진" and g.lanes == 2
    assert g.saturation == pytest.approx(2200 * 2)  # 보정 없음


def test_correction_factors_reduce_saturation():
    ix = simple(heavy_pct=10, lane_width_m=2.8, grade_pct=3)
    g = H.analyze_approach(ix.approaches[0], ix).groups[0]
    assert g.saturation == pytest.approx(2200 * 2 * 0.94 * 0.96 * (1 / 1.08))


def test_protected_dedicated_left_group_and_phase():
    ix = simple(left_case=1, v_left=100, left_phase=1, lanes=2)
    r = H.analyze_approach(ix.approaches[0], ix)
    lt = next(g for g in r.groups if g.label == "전용LT")
    assert lt.phase == 1 and lt.lanes == 1 and lt.saturation == pytest.approx(2200)  # EL=1.0·Ep(25m)=1.0 → f=1
    assert lt.g_over_c == pytest.approx((20 - 0.3) / 100)


def test_two_dedicated_left_lanes_use_e105():
    ix = simple(left_case=2, v_left=100, left_phase=1)
    lt = next(g for g in H.analyze_approach(ix.approaches[0], ix).groups if g.label == "전용LT")
    assert lt.lanes == 2 and lt.saturation == pytest.approx(2200 * 2 / 1.05)


def test_protected_left_requires_phase():
    with pytest.raises(ValueError, match="left_phase"):
        simple(left_case=1, v_left=100)


def test_permissive_left_gets_slower_with_more_opposing_traffic():
    lo = simple(left_case=3, v_left=100, opposing_through=300, lanes=2)
    hi = simple(left_case=3, v_left=100, opposing_through=900, lanes=2)
    s_lo = next(g for g in H.analyze_approach(lo.approaches[0], lo).groups if g.label == "전용LT").saturation
    s_hi = next(g for g in H.analyze_approach(hi.approaches[0], hi).groups if g.label == "전용LT").saturation
    assert s_hi < s_lo


def test_t_junction_no_left_is_through_and_right_only():
    ix = simple(topology="t_no_left", v_right=200, lanes=2)
    labels = [g.label for g in H.analyze_approach(ix.approaches[0], ix).groups]
    assert "전용LT" not in labels and labels  # 좌회전 없음


def test_t_junction_no_right_shared_left_uses_eq_8_36():
    ix = simple(topology="t_no_right", left_case=4, v_left=150, v_through=500, lanes=2)
    groups = H.analyze_approach(ix.approaches[0], ix).groups
    assert groups and all(g.saturation > 0 for g in groups)
    assert sum(g.volume for g in groups) == pytest.approx(650, rel=0.02)  # 직진+좌회전 보존


def test_y_junction_dedicated_left_and_right():
    ix = simple(topology="y_dedicated", v_left=200, v_right=300, left_lanes=1, right_lanes=1, left_case=1, left_phase=1,
                v_through=0)
    r = H.analyze_approach(ix.approaches[0], ix)
    assert {g.label for g in r.groups} == {"전용LT", "전용RT"}
    rt = next(g for g in r.groups if g.label == "전용RT")
    f = rt.saturation / 2200
    assert f == pytest.approx(0.86 * (1 - 0 - 0), abs=0.2)  # 식 8-37 범위(보행·마찰 없으면 0.86)


def test_integrated_single_lane_group():
    ix = simple(left_case=4, v_left=50, v_right=60, v_through=200, lanes=1)
    r = H.analyze_approach(ix.approaches[0], ix)
    assert [g.label for g in r.groups] == ["통합"] and r.groups[0].lanes == 1


def test_intersection_weighted_delay_and_critical_vc():
    ix = DetailedIntersection(
        name="t", cycle=100, phf=1.0, phases=[Phase(green=40), Phase(green=30)],
        approaches=[DetailedApproach(name="N", lanes=2, v_through=500, phase=0),
                    DetailedApproach(name="E", lanes=2, v_through=900, phase=1)])
    res = H.analyze_detailed(ix)
    assert len(res.approaches) == 2 and res.groups
    tot = sum(g.volume for g in res.groups)
    assert res.delay == pytest.approx(sum(g.volume * g.delay for g in res.groups) / tot)
    assert set(res.phase_y) == {0, 1} and res.critical_vc and res.critical_vc > 0


# ── 입력 검증 ──
def test_phase_times_cannot_exceed_cycle():
    with pytest.raises(ValueError, match="신호주기"):
        DetailedIntersection(name="t", cycle=60, phases=[Phase(green=40), Phase(green=30)],
                             approaches=[DetailedApproach(name="N", phase=0)])


def test_unknown_phase_index_rejected():
    with pytest.raises(ValueError, match="현시 번호"):
        DetailedIntersection(name="t", cycle=100, phases=[Phase(green=40)],
                             approaches=[DetailedApproach(name="N", phase=3)])


def test_delay_equations_reproduce_manual_exactly_with_manual_rounded_inputs():
    """편람이 이어 쓴 반올림 중간값(V, S, PF)을 그대로 넣으면 식 8-43~8-53 결과가 편람 값과 일치한다."""
    lt = H._delay_components(V=689, S=3046, g=45 - 0.3, G=45, C=120, Qb=40, pf=0.56)
    rt = H._delay_components(V=206, S=800, g=45 - 0.3, G=45, C=120, Qb=0, pf=0.56)
    # 편람은 g/C를 0.373으로 반올림(3046×0.373=1136); 여기서는 (45−0.3)/120=0.3725 → 1134.6
    assert lt["c"] == pytest.approx(1136, abs=2) and lt["x"] == pytest.approx(0.61, abs=0.01)
    assert lt["d1"] == pytest.approx(32.8, abs=0.1)  # 식 8-48 (유형 I)
    assert lt["d2"] == pytest.approx(2.4, abs=0.1)  # 식 8-50
    assert lt["d3"] == pytest.approx(22.7, abs=0.1)  # 식 8-51
    assert lt["delay"] == pytest.approx(43.5, abs=0.15)
    assert rt["d1"] == pytest.approx(31.8, abs=0.1) and rt["d2"] == pytest.approx(12.4, abs=0.1)
    assert rt["delay"] == pytest.approx(30.2, abs=0.1)
    # 접근로 지체: 교통량 가중평균 (식 8-55) = 40.4, 편람 판정 LOS C
    avg = (689 * lt["delay"] + 206 * rt["delay"]) / (689 + 206)
    assert avg == pytest.approx(40.4, abs=0.15) and H.los_from_delay(rt["delay"]) == "C"


def test_manual_rounded_factors_reproduce_manual_saturation():
    f_lt = 1 / (1 + 0.14 * (3.76 - 1))  # 식 8-30, P_LT=0.14
    f_rt = 1 / (1 + 0.82 * (3.00 - 1))  # 식 8-31, P_R=0.82
    assert f_lt == pytest.approx(0.721, abs=0.001) and f_rt == pytest.approx(0.379, abs=0.001)
    assert 2200 * 2 * f_lt * 1.0 * 1.0 * 0.96 == pytest.approx(3046, abs=2)  # 식 8-38
    assert 2200 * 1 * f_rt * 0.96 == pytest.approx(800, abs=2)
