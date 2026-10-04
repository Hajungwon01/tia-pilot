from app.state import ReportState

from .base import BaseAgent


class CreativeAgent(BaseAgent):
    """표·도표 생성. 지금은 마크다운 표만(이미지는 TIA-50/51에서 matplotlib로 확장)."""

    name = "creative"

    async def run(self, state: ReportState) -> ReportState:
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
        return state
