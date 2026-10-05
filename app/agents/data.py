from app.hcm_signal import analyze_detailed
from app.hcm_stages import analyze_stages_detailed
from app.hcm_stages import summarize as summarize_detailed
from app.los import analyze_intersection
from app.stages import MEANINGFUL_REDUCTION, analyze_stages, grade_rank
from app.state import ReportState
from app.trip_generation import estimate_trips

from .base import BaseAgent

SIMPLE_WARN = ("LOS는 도로용량편람(2013) 기준(<표 8-2>, d1·d2 식 원문 확인)으로 계산하되, 포화교통류율은 입력값을 쓰고 "
               "연동계수(PF=1.0)·초기대기지체(d3=0)는 반영하지 않은 간이 분석")
DETAILED_WARN = ("LOS는 도로용량편람(2013) 운영분석 절차(차로군 분류·직진환산·보정계수·연동계수·초기대기지체, 식 8-1~8-56)로 계산 "
                 "— 편람 풀이 예제로 검증. 미지원: 좌회전 CASE 5, 우회전 다차로 공용")


class DataAgent(BaseAgent):
    """유발교통량·LOS 계산(코드). 현장 실측값이 없는 항목은 needs_input으로 돌려준다."""

    name = "data"

    async def run(self, state: ReportState) -> ReportState:
        t = estimate_trips(state.project)
        state.trips = t
        if t.rates_status == "PROVISIONAL":
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

        names = [ix.name for ix in state.intersections] + [ix.name for ix in state.detailed_intersections]
        if len(set(names)) != len(names):
            raise ValueError("교차로 이름이 중복됩니다(간이 입력과 상세 입력 포함).")

        if names:
            for ix in state.intersections:
                results, avg, grade = analyze_intersection(ix.approaches, ix.cycle)
                state.los[ix.name] = {
                    "results": [r.model_dump() for r in results],
                    "avg_delay": avg,
                    "grade": grade,
                }
            if state.intersections:
                state.warn(SIMPLE_WARN)
            for ix in state.detailed_intersections:
                res = analyze_detailed(ix)
                s = summarize_detailed(ix, res)
                state.los[ix.name] = {"results": s["results"], "avg_delay": res.delay, "grade": res.los,
                                      "engine": "hcm_detailed", "critical_vc": res.critical_vc}
            if state.detailed_intersections:
                state.warn(DETAILED_WARN)
            state.put(
                "los.intersections",
                "\n".join(f"{n}: 평균지체 {v['avg_delay']:.1f}초/대, LOS {v['grade']}" for n, v in state.los.items()),
                self.name,
            )
            self._run_stages(state)
        else:
            for key in ("survey.signal_geometry", "survey.count_days", "los.intersections"):
                if key not in state.needs_input:
                    state.needs_input.append(key)
        return state

    def _need(self, state: ReportState, key: str) -> None:
        if key not in state.needs_input:
            state.needs_input.append(key)

    def _run_stages(self, state: ReportState) -> None:
        """사업 미시행 / 시행 / 개선 3단계 분석 (지침 제11조④)."""
        years = (state.scope or {}).get("target_years", [1, 3])
        g = state.background_growth_rate
        if g is None:
            g = 0.0
            state.warn("배경교통량 증가율 미입력: 0%로 가정해 미시행 교통량을 현황과 동일하게 둠")
            self._need(state, "demand.background_growth_rate")

        without_lines, stage_lines = [], []

        def add_lines(name: str, peak: str, res: dict) -> None:
            for y, st in res.items():
                w, p, im = st["without"], st["with"], st["improved"]
                without_lines.append(
                    f"{name} 준공 후 {y}년({peak.upper()} 첨두, 연 증가율 {g * 100:.1f}%): "
                    f"미시행 평균지체 {w['avg_delay']:.1f}초/대, LOS {w['grade']}")
                trend = "악화" if grade_rank(p["grade"]) > grade_rank(w["grade"]) else (
                    "동일" if p["grade"] == w["grade"] else "개선")
                red = st["delay_reduction"]
                eff = (f"{red:.1f}초 감소, 효과 있음" if red >= MEANINGFUL_REDUCTION
                       else f"{max(red, 0):.1f}초 감소, 효과 미미")
                stage_lines.append(
                    f"{name} 준공 후 {y}년: 미시행 {w['avg_delay']:.1f}초/대(LOS {w['grade']}) → "
                    f"시행 {p['avg_delay']:.1f}초/대(LOS {p['grade']}, 등급 {trend}) → "
                    f"개선 후 {im['avg_delay']:.1f}초/대(LOS {im['grade']}, 지체 {eff})")

        for ix in state.intersections:
            peak_total = getattr(state.trips, f"{ix.peak}_peak").total
            if sum(a.project_share for a in ix.approaches) == 0:
                state.warn(f"{ix.name}: 방면별 사업 교통량 배분율 미입력으로 시행 시 교통량이 미시행과 같음")
                self._need(state, "demand.project_share")
            res = analyze_stages(ix.approaches, ix.cycle, years, g, peak_total)
            state.stages[ix.name] = res
            add_lines(ix.name, ix.peak, res)

        for ix in state.detailed_intersections:
            peak_total = getattr(state.trips, f"{ix.peak}_peak").total
            shares = sum(a.project_share_left + a.project_share_through + a.project_share_right for a in ix.approaches)
            if shares == 0:
                state.warn(f"{ix.name}: 이동류별 사업 교통량 배분율 미입력으로 시행 시 교통량이 미시행과 같음")
                self._need(state, "demand.project_share")
            base = analyze_detailed(ix)
            used = {gr.phase for gr in base.groups}
            for ap in base.approaches:
                if ap.detail.get("unused_queue"):
                    labels = ", ".join(sorted({g.label for g in ap.groups})) or "없음"
                    state.warn(f"{ix.name} {ap.name}: 초기 대기차량 키 {ap.detail['unused_queue']}에 해당하는 차로군이 없어 "
                               f"적용되지 않음(이 접근로의 차로군: {labels})")
            idle = [i + 1 for i in range(len(ix.phases)) if i not in used]
            if idle:
                state.warn(f"{ix.name}: 현시 {', '.join(map(str, idle))}에는 입력된 접근로가 없어 녹색시간을 그대로 두고 "
                           "교통량이 입력된 현시끼리만 재배분함(나머지 접근로 교통량을 입력하면 개선 효과가 달라질 수 있음)")
            res = analyze_stages_detailed(ix, years, g, peak_total)
            for y, st in res.items():
                for note in st.get("notes", []):
                    state.warn(f"{ix.name} 준공 후 {y}년: {note}")
            state.stages[ix.name] = res
            add_lines(ix.name, ix.peak, res)

        state.put("demand.without_project", "\n".join(without_lines), self.name)
        state.put("demand.los_three_stage", "\n".join(stage_lines), self.name)
        if state.intersections:
            state.warn("간이 입력의 개선 후 분석은 신호주기 고정·녹색시간 재배분(접근로별 별도 현시 가정)만 반영한 간이 계산")
        if state.detailed_intersections:
            state.warn("상세 입력의 개선 후 분석은 신호주기·황색 고정, 현시별 녹색시간을 임계 V/S에 비례해 재배분한 계산(차로 증설 등은 미반영)")
