from app.los import analyze_intersection
from app.stages import MEANINGFUL_REDUCTION, analyze_stages, grade_rank
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
            state.warn("LOS 등급 기준은 도로용량편람(2013) 값을 2차 출처로 확인한 것으로 원문과 대조하지 못했고, 지체식은 간이식(진행보정·초기대기지체 미반영)")
            self._run_stages(state)
        else:
            for key in ("survey.signal_geometry", "survey.count_days", "los.intersections"):
                if key not in state.needs_input:
                    state.needs_input.append(key)
        return state

    def _run_stages(self, state: ReportState) -> None:
        """사업 미시행 / 시행 / 개선 3단계 분석 (지침 제11조④)."""
        years = (state.scope or {}).get("target_years", [1, 3])
        g = state.background_growth_rate
        if g is None:
            g = 0.0
            state.warn("배경교통량 증가율 미입력: 0%로 가정해 미시행 교통량을 현황과 동일하게 둠")
            if "demand.background_growth_rate" not in state.needs_input:
                state.needs_input.append("demand.background_growth_rate")

        without_lines, stage_lines = [], []
        for ix in state.intersections:
            peak_total = getattr(state.trips, f"{ix.peak}_peak").total
            if sum(a.project_share for a in ix.approaches) == 0:
                state.warn(f"{ix.name}: 방면별 사업 교통량 배분율 미입력으로 시행 시 교통량이 미시행과 같음")
                if "demand.project_share" not in state.needs_input:
                    state.needs_input.append("demand.project_share")
            res = analyze_stages(ix.approaches, ix.cycle, years, g, peak_total)
            state.stages[ix.name] = res
            for y, st in res.items():
                w, p, im = st["without"], st["with"], st["improved"]
                without_lines.append(
                    f"{ix.name} 준공 후 {y}년({ix.peak.upper()} 첨두, 연 증가율 {g * 100:.1f}%): "
                    f"미시행 평균지체 {w['avg_delay']:.1f}초/대, LOS {w['grade']}")
                trend = "악화" if grade_rank(p["grade"]) > grade_rank(w["grade"]) else (
                    "동일" if p["grade"] == w["grade"] else "개선")
                red = st["delay_reduction"]
                eff = (f"{red:.1f}초 감소, 효과 있음" if red >= MEANINGFUL_REDUCTION
                       else f"{max(red, 0):.1f}초 감소, 효과 미미")
                stage_lines.append(
                    f"{ix.name} 준공 후 {y}년: 미시행 {w['avg_delay']:.1f}초/대(LOS {w['grade']}) → "
                    f"시행 {p['avg_delay']:.1f}초/대(LOS {p['grade']}, 등급 {trend}) → "
                    f"개선 후 {im['avg_delay']:.1f}초/대(LOS {im['grade']}, 지체 {eff})")
        state.put("demand.without_project", "\n".join(without_lines), self.name)
        state.put("demand.los_three_stage", "\n".join(stage_lines), self.name)
        state.warn("개선 후 분석은 신호주기 고정·녹색시간 재배분(접근로별 별도 현시 가정)만 반영한 간이 계산")
