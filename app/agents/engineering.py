from app.facts import review_sections
from app.reflection import load_checklist
from app.state import ReportState

from .base import BaseAgent

DISCLAIMER = "※ 본 문서는 초안 작성 지원 도구가 생성한 초안이며, 최종 검토·날인은 교통기술사 등 전문가가 수행해야 합니다."


def build_tables(state: ReportState) -> None:
    """LOS 요약표·3단계 비교표(마크다운)를 계산 결과로 만들어 state.artifacts에 둔다."""
    if state.los:
        lines = ["| 교차로 | 평균지체(초/대) | LOS |", "|---|---|---|"]
        for n, v in state.los.items():
            lines.append(f"| {n} | {v['avg_delay']:.1f} | {v['grade']} |")
        state.artifacts["los_table"] = "\n".join(lines)
    if state.stages:
        lines = ["| 교차로 | 목표년도 | 미시행 지체(LOS) | 시행 지체(LOS) | 개선 후 지체(LOS) |", "|---|---|---|---|---|"]
        for n, years in state.stages.items():
            for y, st in years.items():
                cell = lambda k: f"{st[k]['avg_delay']:.1f} ({st[k]['grade']})"
                lines.append(f"| {n} | 준공 후 {y}년 | {cell('without')} | {cell('with')} | {cell('improved')} |")
        state.artifacts["los_stage_table"] = "\n".join(lines)


class EngineeringAgent(BaseAgent):
    """표를 만들고 섹션을 별표 1 순서로 조립해 문서 초안(마크다운)을 만든다. 없는 섹션은 [미작성]으로 남긴다."""

    name = "engineering"

    async def run(self, state: ReportState) -> ReportState:
        build_tables(state)
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
        if state.artifacts.get("los_stage_table"):
            out += ["## 부록: 3단계 LOS 비교표 (지침 제11조④)", state.artifacts["los_stage_table"], ""]
        if state.warnings:
            out += ["## 작성 시 주의", *[f"- {w}" for w in state.warnings]]
        state.document = "\n".join(out)
        return state
