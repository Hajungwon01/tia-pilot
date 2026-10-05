from app.eligibility import abbreviated_scope, assess_project, spatial_scope, use_table
from app.reflection import load_checklist
from app.state import ReportState

from .base import BaseAgent

KIND_LABELS = {"new": "신축", "expansion": "증축", "use_change": "용도변경"}


class PlanningAgent(BaseAgent):
    """대상 여부·규모·범위 판정(규칙 기반). LLM 불필요."""

    name = "planning"

    async def run(self, state: ReportState) -> ReportState:
        p = state.project
        elig = assess_project(p)
        ab = elig.abbreviated
        applied = bool(ab and ab.applied)

        scope = {"target_years": [1, 3], "eligibility": elig.model_dump()}  # 지침 제5조①1
        if elig.multiple is None:
            # 면적 미입력: 판정 불가. 공간적 범위는 최소 구간 임시 적용.
            scope.update(spatial_scope(0))
            scope["spatial_provisional"] = True
            key = "project.expansion_areas" if p.project_kind == "expansion" else "project.gross_floor_area_m2"
            if key not in state.needs_input:
                state.needs_input.append(key)
            state.warn("건축 연면적 미입력: 평가 대상 여부 판정 불가, 공간적 범위는 최소 구간(반경 1.0km·4개 교차로)으로 임시 적용"
                       if key == "project.gross_floor_area_m2" else
                       "증축 판정에 필요한 기존 준공 연면적·증축 연면적이 입력되지 않아 대상 여부를 판정할 수 없음(공간적 범위는 최소 구간 임시 적용)")
        else:
            scope.update(spatial_scope(elig.multiple))
            if not elig.eligible:
                if p.project_kind == "new" and not elig.mixed_use:
                    state.warn(
                        f"연면적 {p.gross_floor_area_m2:,.0f}㎡가 서울시 대상 기준 {elig.threshold_m2:,.0f}㎡ 미만: "
                        "교통영향평가 대상이 아닐 수 있음(다른 대상 요건·조례 확인 필요)")
                else:
                    state.warn(f"{KIND_LABELS[p.project_kind]}{'(복합용도)' if elig.mixed_use else ''} 판정 결과 평가 대상이 아닐 수 있음 "
                               "(대상 기준 미만, 다른 대상 요건·조례 확인 필요)")
            if elig.committee_review_likely:
                state.warn("시행령 제13조의4②·조례 제5조②1 해당 가능(21층 이상, 연면적 10만㎡ 이상, 판매·운수시설 포함): 심의 주체 확인 필요")
        for note in elig.notes:
            state.warn(note)
        if p.project_kind == "expansion":
            state.warn(f"증축: 유발교통량은 입력한 세대수({p.households}세대)로 계산함 — 증축으로 늘어나는 세대수인지 확인 필요")

        if ab:
            if applied:
                scope.update(abbreviated_scope(ab))
                scope["abbreviated"] = True
                state.warn("약식 교통영향평가(지침 제23조)로 작성: 시간적 범위는 준공 후 1년, 공간적 범위는 "
                           + ("공동주택 단지 내" if ab.complex_only else "영향 큰 2개 이내 교차로")
                           + ". 승인관청이 약식 적용을 인정하는지 확인 필요")
            elif ab.possible and not p.request_abbreviated:
                state.warn("약식 교통영향평가 적용 가능(" + "; ".join(ab.reasons) + "). 적용하려면 '약식 적용'을 선택하세요(지침상 '할 수 있다')")
            elif p.request_abbreviated:
                state.warn("약식 적용을 요청했지만 적용하지 않음: " + "; ".join(ab.reasons))
        state.scope = scope

        state.put("intro.overview", self._overview(state, elig), self.name)
        if elig.eligible is not None:
            verdict = "해당" if elig.eligible else "미해당"
            state.put(
                "intro.reason_timing",
                f"{KIND_LABELS[p.project_kind]}, 판정 면적 {elig.gross_floor_area_m2:,.0f}㎡, 기준 {elig.threshold_m2:,.0f}㎡"
                + (f", Swa {elig.swa:,.0f}(기준 10,000)" if elig.mixed_use and elig.swa is not None else "")
                + f" → 대상 {verdict} ({elig.basis}). "
                "제출 시기: 건축법 제11조에 따른 허가 전(시행령 별표 1 비고 4).",
                self.name,
            )
        if applied:
            state.put("scope.target_years", "목표년도: 준공 후 1년 (약식 교통영향평가, 교통영향평가 지침 제23조②1가)", self.name)
            spatial = ("공간적 범위: 공동주택 단지 내 (약식 교통영향평가, 지침 제23조②2가 단서)" if ab.complex_only else
                       "공간적 범위: 건축으로 교통에 영향을 많이 받는 2개 이내 교차로 (약식 교통영향평가, 지침 제23조②2가)")
            state.put("scope.spatial", spatial, self.name)
        else:
            state.put("scope.target_years", "목표년도: 준공 후 1년, 3년 (교통영향평가 지침 제5조①1)", self.name)
            state.put(
                "scope.spatial",
                f"공간적 범위: 주된 출입구 기준 반경 {scope['radius_km']}km 이내 교차로 {scope['min_intersections']}개 이상 (지침 제5조②1)"
                + (" [임시 적용]" if scope.get("spatial_provisional") else ""),
                self.name,
            )
        state.put("intro.scope", "\n".join([state.sections["scope.target_years"], state.sections["scope.spatial"],
                                            focus_items_text()]), self.name)
        return state

    @staticmethod
    def _overview(state: ReportState, elig) -> str:
        p = state.project
        text = f"사업명 {p.name}, 위치 {p.address}, 용도 {p.land_use.value}, {p.households}세대, 사업 유형 {KIND_LABELS[p.project_kind]}"
        if p.project_kind == "expansion" and p.existing_gfa_m2 and p.expansion_gfa_m2:
            text += (f", 기존 준공 연면적 {p.existing_gfa_m2:,.0f}㎡, 증축 연면적 "
                     f"{p.expansion_gfa_m2 + p.prior_expansion_gfa_m2:,.0f}㎡(이전 증축 포함)")
        elif p.gross_floor_area_m2:
            text += f", 건축 연면적 {p.gross_floor_area_m2:,.0f}㎡"
        if p.other_uses:
            table = use_table()
            text += ", 복합용도: " + ", ".join(f"{table[u.use]['label']} {u.area_m2:,.0f}㎡" for u in p.other_uses)
        return text + "."


def focus_items_text() -> str:
    """별표 3 중점분석 항목(개별 건축물, 6.)을 보고서 범위 문단으로 옮긴다. 원천은 체크리스트 JSON."""
    cl = load_checklist()
    rows = [f"- {i['ref'][-1]}. {i['text'].removeprefix('중점분석: ')}" for i in cl["items"] if i.get("group") == "annex3"]
    return ("중점분석 항목 (지침 별표 3 6. 개별 건축물 준용 — 공동주택은 별표 3에 따로 열거되지 않아 확인 필요):\n"
            + "\n".join(rows))
