from app.eligibility import assess_eligibility, spatial_scope
from app.state import ReportState

from .base import BaseAgent


class PlanningAgent(BaseAgent):
    """대상 여부·규모·범위 판정(규칙 기반). LLM 불필요."""

    name = "planning"

    async def run(self, state: ReportState) -> ReportState:
        p = state.project
        elig = assess_eligibility(p.gross_floor_area_m2, floors=p.floors)

        scope = {"target_years": [1, 3], "eligibility": elig.model_dump()}  # 지침 제5조①1
        if elig.multiple is None:
            # 연면적 미입력: 판정 불가. 공간적 범위는 최소 구간 임시 적용.
            scope.update(spatial_scope(0))
            scope["spatial_provisional"] = True
            if "project.gross_floor_area_m2" not in state.needs_input:
                state.needs_input.append("project.gross_floor_area_m2")
            state.warn("건축 연면적 미입력: 평가 대상 여부 판정 불가, 공간적 범위는 최소 구간(반경 1.0km·4개 교차로)으로 임시 적용")
        else:
            scope.update(spatial_scope(elig.multiple))
            if not elig.eligible:
                state.warn(
                    f"연면적 {p.gross_floor_area_m2:,.0f}㎡가 서울시 대상 기준 {elig.threshold_m2:,.0f}㎡ 미만: "
                    "교통영향평가 대상이 아닐 수 있음(다른 대상 요건·조례 확인 필요)")
            if elig.committee_review_likely:
                state.warn("조례 제5조②1 해당 가능(21층 이상 또는 연면적 10만㎡ 이상): 심의 주체 확인 필요")
        state.scope = scope

        state.put("intro.overview",
                  f"사업명 {p.name}, 위치 {p.address}, 용도 {p.land_use.value}, {p.households}세대"
                  + (f", 건축 연면적 {p.gross_floor_area_m2:,.0f}㎡" if p.gross_floor_area_m2 else "") + ".",
                  self.name)
        if elig.eligible is not None:
            verdict = "해당" if elig.eligible else "미해당"
            state.put(
                "intro.reason_timing",
                f"연면적 {elig.gross_floor_area_m2:,.0f}㎡, 기준 {elig.threshold_m2:,.0f}㎡ → 대상 {verdict} ({elig.basis}). "
                "제출 시기: 건축법 제11조에 따른 허가 전(시행령 별표 1 비고 4).",
                self.name,
            )
        state.put("scope.target_years", "목표년도: 준공 후 1년, 3년 (교통영향평가 지침 제5조①1)", self.name)
        state.put(
            "scope.spatial",
            f"공간적 범위: 주된 출입구 기준 반경 {scope['radius_km']}km 이내 교차로 {scope['min_intersections']}개 이상 (지침 제5조②1)"
            + (" [임시 적용]" if scope.get("spatial_provisional") else ""),
            self.name,
        )
        state.put("intro.scope", state.sections["scope.target_years"] + "\n" + state.sections["scope.spatial"], self.name)
        return state
