import asyncio

import pytest

from app.agents.ai import AI_SECTIONS
from app.agents.data import DataAgent
from app.agents.planning import PlanningAgent
from app.facts import build_facts, review_sections, verify_text
from app.pipeline import TIAPipeline
from app.schemas import Approach, ProjectInput
from app.state import IntersectionInput, ReportState


def make_state(volume_e=500):
    st = ReportState(
        project=ProjectInput(name="t", address="서울", households=1500, gross_floor_area_m2=180_000),
        intersections=[IntersectionInput(name="A교차로", cycle=120, approaches=[
            Approach(name="N", volume=400, saturation_flow=1800, green_time=40),
            Approach(name="E", volume=volume_e, saturation_flow=1800, green_time=40)])])
    asyncio.run(PlanningAgent().run(st))
    asyncio.run(DataAgent().run(st))
    return st


GOOD = "AM 첨두 유입 87대/시, 유출 204대/시로 추정됩니다. A교차로 평균 지체 45.4초/대, LOS D입니다. 신호 조정을 검토해야 합니다."


def test_legit_numbers_pass():
    f = build_facts(make_state())
    assert verify_text(GOOD, f) == []


def test_invented_number_flagged():
    f = build_facts(make_state())
    issues = verify_text("녹색시간을 10초 연장하고 차로 3개를 증설합니다. 유입 999대/시.", f)
    assert any("10초" in i for i in issues) and any("999대/시" in i for i in issues)


def test_rounded_values_accepted_but_wrong_ones_not():
    f = build_facts(make_state())
    assert verify_text("평균 지체 45초/대", f) == []  # 45.4를 정수로 반올림해도 허용
    assert verify_text("평균 지체 47초/대", f) != []


def test_wrong_los_grade_flagged():
    f = build_facts(make_state())
    assert any("LOS F" in i for i in verify_text("A교차로는 LOS F 수준입니다.", f))


def test_capacity_claim_only_when_vc_over_one():
    ok = build_facts(make_state(volume_e=500))  # 최대 v/c 0.83
    bad = verify_text("유입 교통량이 교차로 용량을 초과하여 혼잡합니다.", ok)
    assert any("용량 초과" in i for i in bad)
    over = build_facts(make_state(volume_e=700))  # v/c > 1
    assert over.max_vc > 1
    assert verify_text("유입 교통량이 교차로 용량을 초과하여 혼잡합니다.", over) == []


def test_capacity_claim_without_any_los_input_flagged():
    st = ReportState(project=ProjectInput(name="t", address="서울", households=10))
    assert any("용량 초과" in i for i in verify_text("교차로 포화 상태입니다.", build_facts(st)))


def test_review_sections_skips_mock_and_other_owners():
    st = make_state()
    st.put("improve.access", "[MOCK] 999대/시", "ai")
    st.put("improve.parking", "유입 999대/시", "planning")  # 다른 소유자는 점검 대상 아님
    st.put("improve.safety", "유입 999대/시", "ai")
    assert list(review_sections(st)) == ["improve.safety"]


class BadThenGoodLLM:
    """첫 호출은 지어낸 수치·주장, 재작성 요청(피드백 포함)부터는 정상 문장."""

    mock_mode = False

    def __init__(self):
        self.prompts = []

    async def complete(self, system, user):
        self.prompts.append(user)
        if "[재작성 요청]" in user:
            return "A교차로 평균 지체 45.4초/대, LOS D입니다. 개선방안은 현장 조사 후 검토가 필요합니다."
        return "교통량이 용량을 초과하여 녹색시간 10초 연장이 필요합니다."


def test_pipeline_rewrites_flagged_sections(monkeypatch):
    monkeypatch.setenv("MAX_REFLECTION_RETRIES", "1")
    from app.config import get_settings
    get_settings.cache_clear()
    llm = BadThenGoodLLM()
    st = asyncio.run(TIAPipeline(llm).run(make_state()))
    assert st.iterations == 1
    assert st.reflection["flagged"] == {}
    assert not any(k in st.reflection["missing"] for k in AI_SECTIONS)
    retry_prompts = [p for p in llm.prompts if "[재작성 요청]" in p]
    assert len(retry_prompts) == len(AI_SECTIONS)
    assert "용량 초과" in retry_prompts[0] and "10초" in retry_prompts[0]  # 사유가 모델에 전달됨


def test_unfixable_text_stays_flagged_in_document(monkeypatch):
    class AlwaysBad(BadThenGoodLLM):
        async def complete(self, system, user):
            return "유입 999대/시가 발생합니다."

    monkeypatch.setenv("MAX_REFLECTION_RETRIES", "1")
    from app.config import get_settings
    get_settings.cache_clear()
    st = asyncio.run(TIAPipeline(AlwaysBad()).run(make_state()))
    assert set(st.reflection["flagged"]) == set(AI_SECTIONS)
    assert "검토 필요" in st.document
    assert all(k in st.reflection["missing"] for k in AI_SECTIONS)  # 통과로 치지 않음


def test_hallucination_prompt_rules_present():
    from app.agents.ai import SYSTEM
    assert "v/c" in SYSTEM and "새 수치" in SYSTEM


def test_units_followed_by_korean_particles_are_checked():
    f = build_facts(make_state())
    assert verify_text("유입 999대/시가 발생합니다.", f) != []
    assert verify_text("평균 지체 88초로 증가합니다.", f) != []
    assert verify_text("AM 첨두 유입 87대/시가 예상됩니다.", f) == []  # 정상 수치는 조사가 붙어도 통과


def test_unit_lookalike_words_are_not_numbers():
    f = build_facts(make_state())
    # '10초과', '3분석', '2개선' 같은 낱말은 수치로 보지 않는다
    assert verify_text("기준을 10초과하는 경우, 3분석 결과, 2개선안", f) == []
