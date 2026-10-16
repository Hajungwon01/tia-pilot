"""평면교차로 설계 지침(2004) 좌회전 차로 길이: 지침 53~54쪽 예시 6가지를 재현하고, 개선 후보·AI 입력·환각 점검에 연결됐는지 확인."""
import asyncio

import pytest

from app import design_criteria as DC
from app.agents.ai import AIAgent
from app.facts import build_facts, verify_text
from app.hcm_signal import DetailedApproach as A
from app.hcm_signal import DetailedIntersection as I
from app.hcm_signal import Phase as P
from app.pipeline import TIAPipeline
from app.schemas import ProjectInput
from app.state import ReportState


# (설계속도, 제약 여부, 차로폭, 좌회전 대수, 지침 예시의 L1, L2, 최종 길이) — 53쪽 ①②, 53쪽 ③④, 54쪽 ⑤⑥
EXAMPLES = [
    (80, False, 3.25, 5, 130, 70, 130),
    (80, True, 3.0, 5, 90, 70, 90),
    (60, False, 3.0, 4, 70, 60, 70),  # 지침은 L2를 56m로 적었으나 5m 단위 올림이면 60m, 최종값은 같다
    (60, True, 2.75, 4, 45, 60, 60),
    (40, False, 3.0, 3, 40, 45, 45),
    (40, True, 2.75, 3, 30, 45, 45),
]


@pytest.mark.parametrize("v,constrained,width,n,l1,l2,final", EXAMPLES)
def test_manual_examples_reproduced(v, constrained, width, n, l1, l2, final):
    r = DC.left_turn_lane_length(n, v, width, constrained=constrained)
    assert (r.l1_m, r.l2_m, r.length_m) == (l1, l2, final)


def test_tables_match_the_guideline():
    assert DC.DECEL_STANDARD == {30: 20, 40: 30, 50: 50, 60: 70, 70: 95, 80: 125}  # 표 3.6 기준치
    assert DC.DECEL_MIN == {30: 15, 40: 20, 50: 35, 60: 45, 70: 65, 80: 80}  # 표 3.6 최소치
    assert [DC.vehicle_length(x) for x in (5, 15, 30, 50)] == [6.0, 7.0, 7.8, 9.0]  # 표 3.7
    assert DC.vehicle_length(None) == 7.0 and DC.vehicle_length(10) == pytest.approx(6.5)  # 사이 값 보간


def test_intermediate_values_follow_formula():
    r = DC.left_turn_lane_length(5, 80, 3.25)
    assert r.taper_m == 50 and r.decel_m == 125 and r.queue_m == pytest.approx(52.5)  # T=3.25×15→50, l=125, Ls=1.5·5·7


def test_input_validation():
    with pytest.raises(ValueError, match="설계속도"):
        DC.left_turn_lane_length(3, 45)
    with pytest.raises(ValueError, match="0보다"):
        DC.left_turn_lane_length(0, 50)


def test_arrivals_per_cycle_rounds_up_with_minimum_one():
    assert DC.arrivals_per_cycle(150, 120) == 5 and DC.arrivals_per_cycle(151, 120) == 6 and DC.arrivals_per_cycle(1, 60) == 1


def test_minimum_length_never_below_twice_queue():
    for v in DC.SPEEDS:
        r = DC.left_turn_lane_length(6, v, 3.0)
        assert r.length_m >= 2.0 * 6 * 7.0 - 1e-9  # L ≥ 2.0·N·S


def four_leg():
    def ap(n, ph, vl, vt, vr, lanes=2, case=6, opp=None):
        return A(name=n, topology="four_way", left_case=case, lanes=lanes, v_left=vl, v_through=vt, v_right=vr, phase=ph, opposing=opp,
                 project_share_through=0.1)
    return I(name="T", cycle=120, phf=0.95, phases=[P(green=40), P(green=40), P(green=25)],
             approaches=[ap("EB", 0, 120, 900, 200, 3, 6, "WB"), ap("WB", 0, 100, 800, 150, 3, 6, "EB"),
                         ap("NB", 1, 150, 700, 120, 2, 4), ap("SB", 1, 140, 650, 100, 2, 4)])


def run_state():
    st = ReportState(project=ProjectInput(name="t", address="서울", households=1000, gross_floor_area_m2=120_000),
                     detailed_intersections=[four_leg()], background_growth_rate=0.02)
    return asyncio.run(TIAPipeline().run(st))


def test_left_bay_scenarios_carry_length_and_reference():
    st = run_state()
    sc = [s for s in st.stages["T"][1]["scenarios"]["scenarios"] if s["id"].startswith("left_bay")]
    assert sc
    for s in sc:
        d = s["design"]
        assert d["minimum_m"] <= d["standard_m"] and d["design_speed"] == 50 and "평면교차로 설계 지침" in d["ref"]
        assert any("필요 길이" in c and "설계속도 50km/h 가정" in c for c in s["changes"])
    add = [s for s in st.stages["T"][1]["scenarios"]["scenarios"] if s["id"].startswith("add_lane")]
    assert all(s["design"] is None for s in add)


def test_ai_input_lists_criteria_and_facts_accept_them():
    st = run_state()
    text = AIAgent(None)._facts(st) if False else AIAgent.__new__(AIAgent)._facts(st)
    assert "[설계 기준]" in text and "교통섬 최소 면적 9㎡" in text and "51~52쪽" in text
    f = build_facts(st)
    assert verify_text("교통섬은 최소 9㎡ 이상이어야 하며 용지 제약 시 도시지역 5㎡까지 허용됩니다.", f) == []
    assert verify_text("교통섬 최소 면적은 11㎡입니다.", f)  # 원문에 없는 수치
    d = next(s["design"] for s in st.stages["T"][1]["scenarios"]["scenarios"] if s["design"])
    assert verify_text(f"필요 길이는 약 {d['standard_m']:g}m입니다.", f) == []


# ── 도로 기능 → 설계속도(도로의 구조·시설 기준에 관한 규칙 제8조①, 도시지역) ──
def test_urban_design_speed_table_matches_the_rule():
    assert DC.URBAN_DESIGN_SPEED == {"arterial": 80, "sub_arterial": 60, "collector": 50, "local": 40}
    assert DC.design_speed_for("sub_arterial")[0] == 60 and "제8조" in DC.design_speed_for("sub_arterial")[1]
    v, basis = DC.design_speed_for(None)
    assert v == 50 == DC.DEFAULT_DESIGN_SPEED and "미입력" in basis and "가정" in basis
    assert all(v in DC.SPEEDS for v in DC.URBAN_DESIGN_SPEED.values())  # 표 3.6에 있는 속도만 쓴다


def test_faster_road_needs_longer_left_lane_and_note_says_basis():
    slow, _ = DC.left_lane_note(150, 120, 3.0, 5, "local")
    fast, d = DC.left_lane_note(150, 120, 3.0, 5, "arterial")
    assert d["design_speed"] == 80 and d["speed_assumed"] is False and "주간선도로(도시지역) 설계속도 80km/h" in fast
    assert DC.left_turn_lane_length(5, 80, 3.0).length_m > DC.left_turn_lane_length(5, 40, 3.0).length_m
    assert "설계속도 40km/h" in slow
    assumed, d0 = DC.left_lane_note(150, 120, 3.0, 5, None)
    assert d0["speed_assumed"] is True and "미입력" in assumed


def test_road_class_flows_from_input_to_scenario_and_ai_criteria():
    ix = four_leg()
    apps = [a.model_copy(update={"road_class": "sub_arterial"}) for a in ix.approaches]
    st = ReportState(project=ProjectInput(name="t", address="서울", households=1000, gross_floor_area_m2=120_000),
                     detailed_intersections=[ix.model_copy(update={"approaches": apps})], background_growth_rate=0.02)
    st = asyncio.run(TIAPipeline().run(st))
    sc = [s for s in st.stages["T"][1]["scenarios"]["scenarios"] if s["design"]]
    assert sc and all(s["design"]["design_speed"] == 60 and not s["design"]["speed_assumed"] for s in sc)
    text = AIAgent.__new__(AIAgent)._facts(st)
    assert "도시지역 설계속도 주간선도로 80" in text and "제8조" in text
    f = build_facts(st)
    assert verify_text("보조간선도로의 설계속도는 60km/h 이상입니다.", f) == []


def test_invalid_road_class_rejected():
    with pytest.raises(ValueError):
        A(name="x", road_class="highway")


def test_wizard_sends_road_class(tmp_path):
    from fastapi.testclient import TestClient

    from app import main
    js = TestClient(main.app).get("/static/wizard.js").text
    assert "dp-road" in js and "road_class" in js
