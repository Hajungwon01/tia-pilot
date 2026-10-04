from app.state import ReportState

from .base import BaseAgent

# AI 에이전트가 작성하는 보고서 섹션 (체크리스트 key -> 주제)
AI_SECTIONS = {
    "improve.roads_intersections": "주변가로 및 교차로: 현황 및 문제점, 개선방안",
    "improve.access": "진·출입 동선: 현황 및 문제점, 개선방안",
    "improve.transit_walk_bike": "대중교통, 자전거 및 보행: 현황 및 문제점, 개선방안",
    "improve.parking": "주차: 현황 및 문제점, 개선방안",
    "improve.safety": "교통안전 및 기타: 현황 및 문제점, 개선방안",
}

SYSTEM = (
    "당신은 교통영향평가 보고서 초안의 '문제점 및 개선방안' 문단을 쓰는 보조자입니다.\n"
    "규칙: 1) 숫자는 [분석 결과]에 주어진 값만 인용하고 새 수치를 만들지 마세요. "
    "2) 근거가 없는 항목은 '현장 조사 필요'라고 쓰세요. "
    "3) 지침 조문이나 법령을 지어내지 마세요. 4) 초안이며 전문가 검토가 필요함을 전제로 쓰세요."
)


class AIAgent(BaseAgent):
    """분석 결과를 해석해 문제점·개선대책 문구 생성(LLM)."""

    name = "ai"

    def _facts(self, state: ReportState) -> str:
        t = state.trips
        lines = [f"사업: {state.project.name} ({state.project.households}세대)"]
        if t:
            lines.append(f"AM 첨두 유입 {t.am_peak.in_trips:.0f}/유출 {t.am_peak.out_trips:.0f}대/시, "
                         f"PM 첨두 유입 {t.pm_peak.in_trips:.0f}/유출 {t.pm_peak.out_trips:.0f}대/시")
        for n, v in state.los.items():
            lines.append(f"{n}: 평균지체 {v['avg_delay']:.1f}초/대, LOS {v['grade']}")
        if not state.los:
            lines.append("교차로 실측 입력 없음")
        return "\n".join(lines)

    async def run(self, state: ReportState, only: list[str] | None = None, feedback: str = "") -> ReportState:
        keys = only or list(AI_SECTIONS)
        facts = self._facts(state)
        for key in keys:
            user = f"[분석 결과]\n{facts}\n\n[작성할 항목]\n{AI_SECTIONS[key]}\n{feedback}"
            state.put(key, await self.llm.complete(SYSTEM, user), self.name)
        return state
