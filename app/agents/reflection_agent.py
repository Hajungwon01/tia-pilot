from app.core.llm_client import MOCK_PREFIX
from app.facts import review_sections
from app.guideline_rules import evaluate_rules
from app.reflection import check_report
from app.state import ReportState

from .base import BaseAgent


class ReflectionAgent(BaseAgent):
    """체크리스트(v0.3)로 누락을 점검하고 정량 기준(rule)을 판정한다. MOCK 문장은 '작성됨'으로 인정하지 않는다."""

    name = "reflection"

    async def run(self, state: ReportState) -> ReportState:
        flagged = review_sections(state)  # 계산 결과와 어긋난 AI 문장은 작성된 것으로 인정하지 않는다
        real = {k for k, v in state.sections.items()
                if v.strip() and not v.startswith(MOCK_PREFIX) and k not in flagged}
        unverified = sorted(k for k, v in state.sections.items() if v.startswith(MOCK_PREFIX))
        r = check_report(real)
        state.reflection = {
            "passed": r["passed"],
            "auto_total": r["auto_total"],
            "missing": [i["key"] for i in r["missing"]],
            "manual": [i["id"] for i in r["manual"]],
            "rules": evaluate_rules(state),
            "unverified_mock": unverified,
            "flagged": flagged,
        }
        return state
