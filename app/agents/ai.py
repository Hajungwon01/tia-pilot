from app.design_criteria import criteria_lines
from app.parking import judgement_lines
from app.improvement import scenario_lines
from app.state import ReportState

from .base import BaseAgent

# AI 에이전트가 작성하는 보고서 섹션 (체크리스트 key -> 주제)
AI_SECTIONS = {
    "improve.roads_intersections": "주변가로 및 교차로: 현황 및 문제점, 개선방안",
    "improve.access": "진·출입 동선: 현황 및 문제점, 개선방안",
    "improve.transit": "대중교통: 현황 및 문제점, 개선방안",
    "improve.walk": "보행: 현황 및 문제점, 개선방안",
    "improve.bike": "자전거: 현황 및 문제점, 개선방안",
    "improve.parking": "주차: 현황 및 문제점, 개선방안",
    "improve.safety": "교통안전 및 기타: 현황 및 문제점, 개선방안",
}

SYSTEM = (
    "당신은 교통영향평가 보고서 초안의 '문제점 및 개선방안' 문단을 쓰는 보조자입니다.\n"
    "[규칙]\n"
    "1. 숫자는 [분석 결과]에 있는 값만 그대로 인용하세요. 새 수치를 만들거나 계산하지 마세요. "
    "개선방안에는 [분석 결과]에 없는 구체 수치(예: 녹색시간 N초 연장)를 제안하지 말고 '검토 필요'처럼 방향만 쓰세요. "
    "[개선 후보]가 있으면 그 후보와 수치만 인용할 수 있고, '물리적 개선'은 용지·도로폭·교통안전 검토 전의 검토 후보라고 밝히세요. "
    "시행 가능성은 [설계 기준]에 적힌 기준과 쪽수만 근거로 인용하고(없는 기준을 지어내지 말 것), 설계속도는 가정값이라고 밝히세요.\n"
    "2. [분석 결과]에 없는 사실(도로 구조, 차로수, 현재 설계의 적정성, 사고 이력 등)은 단정하지 말고 "
    "'현장 조사 필요'라고 쓰세요.\n"
    "3. 원인을 단정하지 마세요. 특히 용량 초과·포화는 [분석 결과]에서 v/c가 1 이상일 때만 쓸 수 있습니다. "
    "v/c가 1 미만이면 '용량 이내이나 지체가 발생'처럼 사실대로 쓰세요.\n"
    "4. 지침 조문이나 법령을 지어내지 마세요.\n"
    "5. [유의사항]에 '임시' 표시가 있으면 해당 수치가 잠정값임을 문장에 밝히세요.\n"
    "6. [3단계 분석]이 있으면 사업 미시행→시행→개선 후 변화를 해당 수치로 비교해 서술하세요. "
    "악화·개선 여부는 수치 비교로만 판단하고, 개선방안의 근거로는 [3단계 분석]의 '개선 후' 계산만 인용하세요.\n"
    "7. 초안이며 전문가 검토가 필요함을 전제로 쓰세요.\n"
    "8. 주차는 [주차 판정]의 방향(부족·여유·초과)을 그대로 따르세요. 계획이 법정 이상이면 '부족'이라 쓰지 말고, 주차대수를 늘리라고 제안하지 마세요. "
    "법정 대수와 원단위법 수요는 서로 다른 기준이므로 한쪽이 다른 쪽을 '초과'한다고 쓰지 마세요.\n"
    "9. [자료 없음]으로 표시된 항목(대중교통·보행·자전거 현황)은 이용 수준이나 불편을 단정하지 말고 '현황 자료 없음, 조사 필요'라고만 쓰세요. "
    "차량 유입·유출은 같은 시간대의 방향별 값이므로 '유입이 35에서 452로 증가'처럼 시간 변화로 풀이하지 마세요."
)


class AIAgent(BaseAgent):
    """분석 결과를 해석해 문제점·개선대책 문구 생성(LLM)."""

    name = "ai"

    def _facts(self, state: ReportState) -> str:
        t = state.trips
        lines = [f"사업: {state.project.name} ({state.project.households}세대)"]
        if t:
            lines.append(f"사업지 승용차 발생: AM 첨두 유입 {t.am_peak.in_trips:.0f}/유출 {t.am_peak.out_trips:.0f}대/시, "
                         f"PM 첨두 유입 {t.pm_peak.in_trips:.0f}/유출 {t.pm_peak.out_trips:.0f}대/시 "
                         "(유입=단지로 들어오는 차량, 유출=단지에서 나가는 차량. 같은 시간대의 방향별 값이며 시간에 따른 증가·감소가 아님)")
        pk = state.parking
        if pk:
            lines.append(f"주차: 원단위법 수요 {pk['demand']:,.0f}대"
                         + (f"(원단위 {pk['demand_per_household']:g}대/세대, 임시값)" if pk["rate_status"] == "PROVISIONAL" else "")
                         + (f", 법정 {pk['legal_total']:,}대" if pk["legal_total"] is not None else ", 법정 대수 미산정")
                         + (f", 계획 {pk['planned']:,}대" if pk["planned"] is not None else ", 계획 대수 미입력")
                         + (f", 법정 대비 {pk['planned_vs_legal_pct']:.0f}%" if pk["planned_vs_legal_pct"] is not None else ""))
        if pk:
            lines.append("[주차 판정] " + " / ".join(judgement_lines(pk)))
        lines.append("[자료 없음] 대중교통 이용률·노선·정류장, 보행·자전거 이용 현황과 시설은 입력된 자료가 없음 — 현황을 단정하지 말고 '현황 자료 없음, 조사 필요'로 쓸 것")
        for n, v in state.los.items():
            lines.append(f"{n}: 평균지체 {v['avg_delay']:.1f}초/대, LOS {v['grade']}")
            for r in v["results"]:
                lines.append(f"  - {r['approach']} 접근로: 용량 {r['capacity']:.0f}대/시, v/c {r['vc_ratio']:.2f}, "
                             f"지체 {r['delay']:.1f}초/대, LOS {r['los']}")
        for n, years in state.stages.items():
            for y, st in years.items():
                lines.append(f"[3단계 분석] {n} 준공 후 {y}년:")
                for label, k in (("사업 미시행", "without"), ("사업 시행", "with"), ("개선 후(녹색시간 재배분)", "improved")):
                    d = st[k]
                    lines.append(f"  - {label}: 평균지체 {d['avg_delay']:.1f}초/대, LOS {d['grade']}, 최대 v/c {d['max_vc']:.2f}")
                gi = ", ".join(f"{a} {g:.1f}초" for a, g in st["improved"]["greens"].items())
                gw = ", ".join(f"{a} {g:.1f}초" for a, g in st["with"]["greens"].items())
                lines.append(f"  - 녹색시간 변경: 현행 {gw} → 개선 {gi}")
                lines.append(f"  - 녹색시간 재배분에 의한 지체 감소: {st['delay_reduction']:.1f}초/대")
                if st.get("scenarios"):
                    lines += scenario_lines(n, y, st["scenarios"])
        if any(st.get("scenarios", {}).get("scenarios") for years in state.stages.values() for st in years.values()):
            lines.append("[설계 기준] 개선 후보의 물리적 시행 가능성을 검토할 때 인용할 수 있는 기준(원문 확인분):")
            lines += criteria_lines()
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
