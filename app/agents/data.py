from app.los import analyze_intersection
from app.state import ReportState
from app.trip_generation import estimate_trips

from .base import BaseAgent


class DataAgent(BaseAgent):
    """유발교통량·LOS 계산(코드). 현장 실측값이 없는 항목은 needs_input으로 돌려준다."""

    name = "data"

    async def run(self, state: ReportState) -> ReportState:
        t = estimate_trips(state.project)
        state.trips = t
        if t.rates_status != "PROVISIONAL":
            pass
        else:
            state.warn("유발 원단위가 임시값(KTDB 승인 전): 수요 결과는 검증되지 않음")

        state.put(
            "demand.with_project",
            f"일 승용차 유발 {t.daily_vehicle_trips:.0f}대/일, "
            f"AM 첨두 유입 {t.am_peak.in_trips:.0f}·유출 {t.am_peak.out_trips:.0f}대/시, "
            f"PM 첨두 유입 {t.pm_peak.in_trips:.0f}·유출 {t.pm_peak.out_trips:.0f}대/시 "
            f"(원단위 상태: {t.rates_status})",
            self.name,
        )
        state.put("demand.method", "교통유발 원단위를 활용한 직접수요예측기법 (지침 제11조③)", self.name)
        state.put("unitrate.peak_split", "첨두시(AM/PM)를 구분한 원단위 적용", self.name)

        if state.intersections:
            for ix in state.intersections:
                results, avg, grade = analyze_intersection(ix.approaches, ix.cycle)
                state.los[ix.name] = {
                    "results": [r.model_dump() for r in results],
                    "avg_delay": avg,
                    "grade": grade,
                }
            state.put(
                "los.intersections",
                "\n".join(f"{n}: 평균지체 {v['avg_delay']:.1f}초/대, LOS {v['grade']}" for n, v in state.los.items()),
                self.name,
            )
            state.warn("LOS 등급 기준이 HCM 임시값(도로용량편람 미적용)")
        else:
            for key in ("survey.signal_geometry", "survey.count_days", "los.intersections"):
                if key not in state.needs_input:
                    state.needs_input.append(key)
        return state
