"""AI 문장의 방향·의미 점검(app/semantic_rules.py, app/facts.py)과 AI 입력의 주차 판정.

2026-10-27 실제 LLM(gpt-4o-mini) 실행에서 수치 점검은 통과했지만 해석이 뒤집힌 문장들을 그대로 회귀 테스트로 남긴다.
"""
import asyncio

import pytest

from app.agents.ai import SYSTEM, AIAgent
from app.facts import build_facts, verify_text
from app.hcm_signal import DetailedApproach as A
from app.hcm_signal import DetailedIntersection as I
from app.hcm_signal import Phase as P
from app.parking import judgement_lines
from app.pipeline import TIAPipeline
from app.schemas import ProjectInput, UnitType
from app.state import ReportState


def make_state(planned=2200) -> ReportState:
    def ap(n, ph, vl, vt, vr, lanes=2, case=6, opp=None):
        return A(name=n, topology="four_way", left_case=case, lanes=lanes, v_left=vl, v_through=vt, v_right=vr, phase=ph, opposing=opp, project_share_through=0.1)
    ix = I(name="사거리 샘플", cycle=120, phf=0.95, phases=[P(green=40), P(green=40), P(green=25)],
           approaches=[ap("EB", 0, 120, 900, 200, 3, 6, "WB"), ap("WB", 0, 100, 800, 150, 3, 6, "EB"), ap("NB", 1, 150, 700, 120, 2, 4), ap("SB", 1, 140, 650, 100, 2, 4)])
    proj = ProjectInput(name="샘플", address="서울", households=1500, gross_floor_area_m2=180000, rate_basis="evidence", car_occupancy=1.3,
                        unit_types=[UnitType(exclusive_area_m2=59, households=300), UnitType(exclusive_area_m2=84, households=900), UnitType(exclusive_area_m2=114, households=300)],
                        planned_parking_spaces=planned)
    return asyncio.run(TIAPipeline().run(ReportState(project=proj, detailed_intersections=[ix], background_growth_rate=0.02)))


# ── 주차 판정(코드가 방향을 확정) ──
@pytest.mark.parametrize("planned,needle,absent", [
    (2200, "법정 이상이며 권장 상한 130% 이내", "미달"),  # 124% — 실제 LLM이 '부족'으로 뒤집은 사례
    (1500, "미달 — 법정 기준으로 부족함", "부족하지 않음"),
    (2500, "권장 상한 130%", "부족하지 않음"),  # 141% 초과
])
def test_judgement_states_the_direction(planned, needle, absent):
    st = make_state(planned)
    text = " / ".join(judgement_lines(st.parking))
    assert needle in text and absent not in text
    assert "서로 다른 기준" in text


def test_judgement_without_planned_parking_refuses_to_judge():
    assert "판단하지 않음" in judgement_lines({"planned": None})[0]


def test_ai_input_contains_judgement_no_data_notice_and_inout_explanation():
    text = AIAgent.__new__(AIAgent)._facts(make_state())
    assert "[주차 판정]" in text and "주차대수를 더 늘리라고 제안하지 말 것" in text
    assert "[자료 없음]" in text and "대중교통" in text
    assert "시간에 따른 증가·감소가 아님" in text
    assert "[주차 판정]" in SYSTEM and "[자료 없음]" in SYSTEM


# ── 실제 LLM이 쓴 잘못된 문장 ──
BAD = [
    ("계획 주차 2200이 법정 이상인데 부족", "법정 수요 대비 124%에 해당합니다. 이는 충분한 주차 공간 확보가 이루어지지 않은 상태임을 나타냅니다."),
    ("주차를 늘리라고 제안", "계획된 주차 공간을 2,200대로 늘리는 방안에 대한 검토가 필요합니다."),
    ("수요가 법정을 초과", "이는 주차 수요가 법정 수요를 초과하고 있음에도 불구하고 개선이 필요합니다."),
    ("근거 없는 대중교통 단정", "대중교통 이용은 평일 기준으로 다소 저조하게 나타나고 있습니다."),
    ("근거 없는 대중교통 의존도", "AM 첨두 시간대 대중교통 의존도가 낮다는 것을 드러냅니다."),
    ("유입을 시간 변화로 풀이", "사업 시행 후 AM 첨두 시 유입 트래픽은 35대/시에서 452대/시까지 증가했습니다."),
]
GOOD = [
    "계획 주차대수 2,200대는 법정 1,771대의 124%로 법정 기준으로는 부족하지 않으며, 원단위법 수요 1,755대 대비 445대 여유가 있습니다.",
    "대중교통 현황은 입력된 자료가 없어 현황 자료 없음, 조사 필요합니다.",
    "AM 첨두 시간대 유입은 35대/시, 유출은 452대/시로 방향별 값이 다릅니다.",
    "녹색시간 재배분을 하면 평균 지체가 2.4초/대 감소합니다.",
]


@pytest.mark.parametrize("name,text", BAD)
def test_flags_the_misreadings_seen_in_real_llm_output(name, text):
    facts = build_facts(make_state())
    assert facts.parking_not_short is True
    issues = verify_text(text, facts)
    assert issues, f"점검기가 놓침: {name}"


@pytest.mark.parametrize("text", GOOD)
def test_correct_sentences_are_not_flagged(text):
    assert verify_text(text, build_facts(make_state())) == []


def test_shortage_wording_is_allowed_when_planned_is_really_below_legal():
    st = make_state(1500)
    facts = build_facts(st)
    assert facts.parking_not_short is False
    assert verify_text("계획 주차대수가 법정에 미달하여 주차 공간이 부족합니다.", facts) == []  # 수치는 모두 입력·계산값(1,500·1,771)이라 통과


def test_transit_claim_allowed_only_when_data_exists():
    facts = build_facts(make_state())
    claim = "대중교통 이용이 저조합니다."
    assert verify_text(claim, facts)
    facts.transit_data = True  # 향후 이용률 입력 항목이 생기면 허용
    assert not any("대중교통" in i for i in verify_text(claim, facts))


def test_sentence_boundaries_prevent_cross_sentence_false_positives():
    facts = build_facts(make_state())
    text = "계획 주차대수는 법정 이상입니다. 한편 교차로 용량은 충분히 확보되어 있습니다."
    assert verify_text(text, facts) == []


def test_honest_no_data_sentences_are_not_flagged_but_claims_in_the_same_text_are():
    """실제 재실행에서 '단정적인 판단이 불가능'의 '적'이 오탐이던 문제와, 정직한 문장이 막히지 않는지."""
    facts = build_facts(make_state())
    honest = ("대중교통 현황 자료가 입력되지 않아 현재 대중교통 이용 수준에 대한 단정적인 판단이 불가능합니다. "
              "따라서 관련 자료의 조사가 필요합니다.")
    assert verify_text(honest, facts) == []
    mixed = honest + " 그러나 대중교통 이용은 저조한 편입니다."
    assert any("대중교통" in i for i in verify_text(mixed, facts))  # 같은 글 안에서도 다른 문장의 단정은 잡는다


def test_split_sentences_handles_periods_and_newlines():
    from app.semantic_rules import split_sentences
    assert split_sentences("가나다. 라마바\n사아자. ") == ["가나다.", "라마바", "사아자."]


# ── 부정 표현 처리: 실제 LLM이 정확하게 쓴 '부족하지 않다' 문장이 오탐으로 막히던 문제(5회 중 3회 최종 불통과) ──
CORRECT_NEGATIONS = [
    "이로 인해 법정 기준에 비춰볼 때 주차는 부족하지 않으며, 원단위법 수요(1,755대) 대비 445대의 여유가 있는 상황입니다.",
    "따라서 법정 기준으로 주차가 부족하지 않음을 확인할 수 있습니다.",
    "법정 기준 이상으로 확보되어 있으나, 주차 부족 문제는 발생하지 않습니다.",
    "주차 부족이 없습니다.",
]
STILL_WRONG = [
    "충분한 주차 공간 확보가 이루어지지 않은 상태임을 나타냅니다.",  # 부정형이지만 '부족'을 뜻하는 표현
    "계획된 주차 공간을 2,200대로 늘리는 방안에 대한 검토가 필요합니다.",
    "주차가 부족합니다.",
    "법정 주차대수에 미달합니다.",
    "주차 부족 문제가 발생할 수 있습니다.",
]


@pytest.mark.parametrize("text", CORRECT_NEGATIONS)
def test_negated_shortage_is_correct_and_not_flagged(text):
    from app.semantic_rules import parking_shortage_claims
    assert parking_shortage_claims(text) == []
    assert verify_text(text, build_facts(make_state())) == []


@pytest.mark.parametrize("text", STILL_WRONG)
def test_real_shortage_claims_are_still_flagged(text):
    from app.semantic_rules import parking_shortage_claims
    assert parking_shortage_claims(text)
