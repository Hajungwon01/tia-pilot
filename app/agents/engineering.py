from app.facts import review_sections
from app.reflection import load_checklist
from app.state import ReportState

from .base import BaseAgent

DISCLAIMER = "※ 본 문서는 초안 작성 지원 도구가 생성한 초안이며, 최종 검토·날인은 교통기술사 등 전문가가 수행해야 합니다."


class EngineeringAgent(BaseAgent):
    """섹션을 별표 1 순서로 조립해 문서 초안(마크다운)을 만든다. 없는 섹션은 [미작성]으로 남긴다."""

    name = "engineering"

    async def run(self, state: ReportState) -> ReportState:
        flagged = review_sections(state)
        out = [f"# 교통영향평가서 초안 — {state.project.name}", DISCLAIMER, ""]
        for item in load_checklist()["items"]:
            if item["check"] != "key":
                continue
            body = state.sections.get(item["key"])
            out.append(f"## [{item['id']}] {item['text']}")
            out.append(body if body else "[미작성] 입력 또는 작성 필요")
            if item["key"] in flagged:
                out.append("> ⚠ 검토 필요(계산 결과와 불일치 가능): " + "; ".join(flagged[item["key"]]))
            out.append("")
        if state.artifacts.get("los_table"):
            out += ["## 부록: LOS 요약표", state.artifacts["los_table"], ""]
        if state.warnings:
            out += ["## 작성 시 주의", *[f"- {w}" for w in state.warnings]]
        state.document = "\n".join(out)
        return state
