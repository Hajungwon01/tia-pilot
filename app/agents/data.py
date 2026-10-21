from app.hcm_signal import analyze_detailed
from app.hcm_stages import analyze_stages_detailed
from app.improvement import Params, scenario_lines
from app.hcm_stages import summarize as summarize_detailed
from app.los import analyze_intersection
from app.parking import assess_parking
from app.stages import MEANINGFUL_REDUCTION, analyze_stages, grade_rank
from app.state import ReportState
from app.trip_generation import estimate_trips

from .base import BaseAgent

SIMPLE_WARN = ("LOS는 도로용량편람(2013) 기준(<표 8-2>, d1·d2 식 원문 확인)으로 계산하되, 포화교통류율은 입력값을 쓰고 "
               "연동계수(PF=1.0)·초기대기지체(d3=0)는 반영하지 않은 간이 분석")
DETAILED_WARN = ("LOS는 도로용량편람(2013) 운영분석 절차(차로군 분류·직진환산·보정계수·연동계수·초기대기지체, 식 8-1~8-56)로 계산 "
                 "— 편람 풀이 예제로 검증. 미지원: 우회전 2차로 이상 공용(편람에 식 없음)")  # 개선 시나리오는 app/improvement.py


class DataAgent(BaseAgent):
    """유발교통량·LOS 계산(코드). 현장 실측값이 없는 항목은 needs_input으로 돌려준다."""

    name = "data"

    async def run(self, state: ReportState) -> ReportState:
        t = estimate_trips(state.project)
        state.trips = t
        if t.rates_status == "PROVISIONAL":
            state.warn("유발 원단위가 임시값(KTDB 승인 전): 수요 결과는 검증되지 않음")
        elif t.rates_status == "USER":
            state.warn("유발 원단위는 모두 사용자가 직접 입력한 값(출처는 원단위 근거 부록 참조)")
            for n in t.rate_notes:
                state.warn(n)
        elif t.rates_status == "EVIDENCE":
            state.warn("유발 원단위는 교통영향평가정보지원시스템 유사시설 조사 중앙값(서울 우선, 조사일 3년 이내)이고 평균 재차인원은 입력값"
                       + (f"(출처: {state.project.car_occupancy_source.strip()})" if state.project.car_occupancy_source.strip() else "(출처 미기재)")
                       + " — 유사시설 선정 적정성 확인 필요")
            for n in t.rate_notes:
                state.warn(n)
        elif t.rates_status == "PARTIAL_EVIDENCE":
            state.warn("유발 원단위는 교통영향평가정보지원시스템 유사시설 조사 중앙값(서울 우선, 조사일 3년 이내)이며 평균 재차인원만 임시값 — "
                       "평가서 제출 전 재차인원 조사와 유사시설 선정 적정성 확인 필요")
            for n in t.rate_notes:
                state.warn(n)
        p = state.project
        if p.rate_basis == "evidence" and p.rate_overrides.person_trips_per_household is None:  # 유사시설 발생원단위를 쓴 경우 정의의 한계를 알린다
            state.warn("유사시설 '발생원단위(인/일)'의 방향은 국토부 시스템 문서로 확정하지 못했음: "
                       + ("평가 실무 문헌(김익기·송태호 2004)과 경기연구원(2023) 연구에 따라 유입 기준(일 총 통행=유입×2)으로 해석 — 양방향 합계라면 승용차 통행은 절반"
                          if p.rate_direction == "inflow" else
                          "양방향 합계로 해석 — 유입 기준이라면 승용차 통행은 2배")
                       + ". 직접 조사한 원단위가 있으면 직접 입력")

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
        self._parking(state)

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

    def _parking(self, state: ReportState) -> None:
        """주차수요 예측(원단위법, 지침 제15조)과 법정·계획 주차대수 비교."""
        p = state.project
        r = assess_parking(p)
        state.parking = r.model_dump()
        prov = r.rate_status == "PROVISIONAL"
        if prov:
            state.warn("주차수요 원단위가 임시값(근거 자료 없음): 주차수요 결과는 검증되지 않음 — 유사 건축물 현지조사 1개소 이상과 "
                       "관련 자료 3개 이상으로 산출(지침 제15조①)하거나 원단위를 직접 입력해야 함")
        if r.legal_apartment is None:
            self._need(state, "project.unit_types")
        if r.planned is None:
            self._need(state, "project.planned_parking_spaces")
        for n in r.notes:
            state.warn(n)

        rate_txt = f"세대당 {r.demand_per_household:g}대" + ("(임시 원단위)" if prov else f"({'입력' if r.rate_status == 'USER' else '유사시설 조사'} 원단위{', 출처: ' + r.rate_source if r.rate_source else ''})")
        lines = [f"원단위법 주차수요: {rate_txt} × {p.households}세대 × 이용효율 {r.utilization:g} = {r.demand:,.0f}대 (단기·장기 동일 원단위 적용)"]
        if r.legal_total is not None:
            basis = ("전용면적 합계 기준" if r.binding == "area" else "세대당 최소 기준")
            lines.append(f"법정 주차대수: 공동주택 {r.legal_apartment:,}대({basis}, 주택건설기준 등에 관한 규정 제27조제1항)"
                         + (f" + 다른 용도 {r.legal_others_total:,}대(서울 주차장 조례 별표 2)" if r.legal_others else "")
                         + f" = {r.legal_total:,}대" + ("" if r.legal_complete else " (일부 용도 미산정)"))
        else:
            lines.append("법정 주차대수: 주택형별 전용면적·세대수 입력 필요")
        if r.planned is not None:
            tail = ""
            if r.planned_vs_legal_pct is not None:
                tail = f", 법정 대비 {r.planned_vs_legal_pct:.0f}%(권장 상한 {r.cap_pct:g}%)"
            lines.append(f"계획 주차대수: {r.planned:,}대{tail}")
            if r.planned_vs_demand is not None:
                if r.planned_vs_demand < 0:
                    lines.append(f"원단위법 수요 대비 계획 대수가 {-r.planned_vs_demand:,.0f}대 부족")
                else:
                    lines.append(f"원단위법 수요 대비 계획 대수가 {r.planned_vs_demand:,.0f}대 여유")
        else:
            lines.append("계획 주차대수: 입력 필요")
        state.put("demand.parking", "\n".join(lines), self.name)
        state.put("parking.method",
                  "주차수요예측기법: 원단위법(지침 제15조②). 법정 주차대수는 주택건설기준 등에 관한 규정과 서울 주차장 조례를 적용. "
                  "유사 건축물 현지조사 1개소 이상과 관련 자료 3개 이상의 비교·분석(제15조①)은 이 도구가 수행하지 않았으므로 작성자 보완 필요.",
                  self.name)
        if r.planned is not None and r.legal_total is not None:
            if r.planned < r.legal_total:
                state.warn(f"계획 주차대수({r.planned:,}대)가 법정 주차대수({r.legal_total:,}대)에 미달")
            elif r.cap is not None and r.planned > r.cap:
                state.warn(f"계획 주차대수({r.planned:,}대)가 법정 대비 권장 상한 {r.cap_pct:g}%({r.cap:,.0f}대)를 초과: 사유 명시 필요(지침 별표 2 8.가⒁)")
        if r.planned_vs_demand is not None and r.planned_vs_demand < 0:
            state.warn(f"원단위법 주차수요({r.demand:,.0f}대)가 계획 주차대수({r.planned:,}대)를 초과" + (" — 임시 원단위 기준" if prov else ""))

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
        params = Params.from_project(state.project)
        if not params.is_default:
            state.warn(f"개선 후보 탐색 조건(입력값): 최소 녹색시간 {params.min_green:g}초, 신호주기 {params.cycle_min:g}~{params.cycle_max:g}초")
        else:
            state.warn(f"개선 후보 탐색 조건이 기본값(최소 녹색시간 {params.min_green:g}초, 신호주기 {params.cycle_min:g}~{params.cycle_max:g}초): "
                       "현장 신호운영 기준에 맞게 입력하면 개선 결과가 달라질 수 있음")

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
            res = analyze_stages(ix.approaches, ix.cycle, years, g, peak_total, params.min_green)
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
                if ap.detail.get("clamped"):
                    state.warn(f"{ix.name} {ap.name}: 입력값이 극단적이라 차로군 보정계수가 하한(0.05)에 걸림 — {', '.join(ap.detail['clamped'])}. "
                               "노변마찰(진출입·버스·주차)·횡단보행자·교통량 입력을 확인하세요(결과 신뢰 불가)")
                if ap.detail.get("unused_queue"):
                    labels = ", ".join(sorted({g.label for g in ap.groups})) or "없음"
                    state.warn(f"{ix.name} {ap.name}: 초기 대기차량 키 {ap.detail['unused_queue']}에 해당하는 차로군이 없어 "
                               f"적용되지 않음(이 접근로의 차로군: {labels})")
            idle = [i + 1 for i in range(len(ix.phases)) if i not in used]
            if idle:
                state.warn(f"{ix.name}: 현시 {', '.join(map(str, idle))}에는 입력된 접근로가 없어 녹색시간을 그대로 두고 "
                           "교통량이 입력된 현시끼리만 재배분함(나머지 접근로 교통량을 입력하면 개선 효과가 달라질 수 있음)")
            res = analyze_stages_detailed(ix, years, g, peak_total, params)
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
            state.warn("상세 입력의 '개선 후'는 신호주기·황색 고정, 현시별 녹색시간을 임계 V/S에 비례해 재배분한 계산. "
                       "차로 증설·전용 좌회전 차로·주기 조정은 '개선 시나리오'로 따로 비교(물리적 개선은 용지·도로폭·안전 검토 전의 검토 후보)")
            lines = []
            for n in (ix.name for ix in state.detailed_intersections):
                for y, st in state.stages.get(n, {}).items():
                    lines += scenario_lines(n, y, st["scenarios"])
            state.artifacts["improve_scenarios"] = "\n".join(lines)
