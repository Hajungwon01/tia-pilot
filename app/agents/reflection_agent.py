from app.core.llm_client import MOCK_PREFIX
from app.reflection import check_report
from app.state import ReportState

from .base import BaseAgent


class ReflectionAgent(BaseAgent):
    """체크리스트(v0.1)로 누락을 점검한다. MOCK 문장은 '작성됨'으로 인정하지 않는다."""

    name = "reflection"

    async def run(self, state: ReportState) -> ReportState:
        real = {k for k, v in state.sections.items() if v.strip() and not v.startswith(MOCK_PREFIX)}
        unverified = sorted(k for k, v in state.sections.items() if v.startswith(MOCK_PREFIX))
        r = check_report(real)
        state.reflection = {
            "passed": r["passed"],
            "auto_total": r["auto_total"],
            "missing": [i["key"] for i in r["missing"]],
            "manual": [i["id"] for i in r["manual"]],
            "unverified_mock": unverified,
        }
        return state
