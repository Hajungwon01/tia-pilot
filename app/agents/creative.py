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
        return state
