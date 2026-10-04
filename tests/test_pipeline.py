import asyncio

from app.agents.ai import AI_SECTIONS
from app.core.llm_client import MOCK_PREFIX
from app.pipeline import TIAPipeline
from app.schemas import Approach, ProjectInput
from app.state import IntersectionInput, ReportState


class FakeLLM:
    """첫 호출은 빈 응답(누락 유도), 재시도부터 정상 문장을 돌려주는 가짜 LLM."""

    mock_mode = False

    def __init__(self, fail_first=True):
        self.calls = 0
        self.fail_first = fail_first

    async def complete(self, system, user):
        self.calls += 1
        if self.fail_first and self.calls <= len(AI_SECTIONS):
            return ""  # 빈 응답 → 섹션 누락으로 취급되어야 함
        return "현황 및 문제점, 개선방안을 서술한 본문"


def make_state(with_intersections=False):
    s = ReportState(project=ProjectInput(name="테스트단지", address="서울 OO동", households=300))
    if with_intersections:
        s.intersections = [IntersectionInput(
            name="A교차로", cycle=120,
            approaches=[Approach(name="N", volume=400, saturation_flow=1800, green_time=40),
                        Approach(name="E", volume=500, saturation_flow=1800, green_time=40)])]
    return s


def test_mock_mode_runs_end_to_end_and_flags_unverified():
    st = asyncio.run(TIAPipeline().run(make_state(with_intersections=True)))
    assert st.scope["target_years"] == [1, 3]
    assert st.trips is not None and "A교차로" in st.los
    assert st.artifacts["los_table"].startswith("| 교차로")
    r = st.reflection
    assert set(r["unverified_mock"]) == set(AI_SECTIONS)  # MOCK은 통과로 안 침
    assert all(k in r["missing"] for k in AI_SECTIONS)
    assert "초안 작성 지원 도구" in st.document
    assert any("임시" in w for w in st.warnings)


def test_without_field_inputs_asks_user():
    st = asyncio.run(TIAPipeline().run(make_state()))
    assert "survey.count_days" in st.needs_input
    assert "[미작성]" in st.document


def test_provisional_scope_warning():
    st = asyncio.run(TIAPipeline().run(make_state()))
    assert st.scope["spatial_provisional"] is True
    assert any("별표 1" in w for w in st.warnings)


def test_reflection_retry_loop_fills_ai_sections(monkeypatch):
    monkeypatch.setenv("MAX_REFLECTION_RETRIES", "1")
    from app.config import get_settings
    get_settings.cache_clear()
    llm = FakeLLM(fail_first=True)
    st = asyncio.run(TIAPipeline(llm).run(make_state(with_intersections=True)))
    get_settings.cache_clear()
    assert st.iterations == 1
    assert not any(k in st.reflection["missing"] for k in AI_SECTIONS)
    assert not st.reflection["unverified_mock"]
    assert llm.calls == 2 * len(AI_SECTIONS)  # 최초 + 재작성


def test_mock_prefix_constant():
    assert MOCK_PREFIX == "[MOCK]"
