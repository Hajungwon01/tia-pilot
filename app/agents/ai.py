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
    "[규칙]\n"
    "1. 숫자는 [분석 결과]에 있는 값만 그대로 인용하세요. 새 수치를 만들거나 계산하지 마세요. "
    "개선방안에도 구체 수치(예: 녹색시간 N초 연장, 차로 N개 증설)를 제안하지 말고 '검토 필요'처럼 방향만 쓰세요.\n"
    "2. [분석 결과]에 없는 사실(도로 구조, 차로수, 현재 설계의 적정성, 사고 이력 등)은 단정하지 말고 "
    "'현장 조사 필요'라고 쓰세요.\n"
    "3. 원인을 단정하지 마세요. 특히 용량 초과·포화는 [분석 결과]에서 v/c가 1 이상일 때만 쓸 수 있습니다. "
    "v/c가 1 미만이면 '용량 이내이나 지체가 발생'처럼 사실대로 쓰세요.\n"
    "4. 지침 조문이나 법령을 지어내지 마세요.\n"
    "5. [유의사항]에 '임시' 표시가 있으면 해당 수치가 잠정값임을 문장에 밝히세요.\n"
    "6. 초안이며 전문가 검토가 필요함을 전제로 쓰세요."
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
            for r in v["results"]:
                lines.append(f"  - {r['approach']} 접근로: 용량 {r['capacity']:.0f}대/시, v/c {r['vc_ratio']:.2f}, "
                             f"지체 {r['delay']:.1f}초/대, LOS {r['los']}")
        if not state.los:
            lines.append("교차로 실측 입력 없음")
        if state.warnings:
            lines.append("[유의사항] " + " / ".join(state.warnings))
        return "\n".join(lines)

    async def run(self, state: ReportState, only: list[str] | None = None,
                  feedback: dict[str, str] | None = None) -> ReportState:
        keys = only or list(AI_SECTIONS)
        facts = self._facts(state)
        for key in keys:
            fb = (feedback or {}).get(key, "")
            user = f"[분석 결과]\n{facts}\n\n[작성할 항목]\n{AI_SECTIONS[key]}\n{fb}"
            state.put(key, await self.llm.complete(SYSTEM, user), self.name)
        return state
