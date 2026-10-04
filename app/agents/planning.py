from app.state import ReportState

from .base import BaseAgent

# 지침 제5조②1 (건축물): (대상범위 배수 상한, 반경 km, 교차로 수)
SPATIAL_TIERS = [(4, 1.0, 4), (8, 1.5, 8), (float("inf"), 2.0, 12)]


def spatial_scope(multiple: float) -> dict:
    for upper, km, n in SPATIAL_TIERS:
        if multiple < upper:
            return {"radius_km": km, "min_intersections": n}
    raise AssertionError


class PlanningAgent(BaseAgent):
    """규모·범위 확인(규칙 기반). LLM 불필요."""

    name = "planning"

    async def run(self, state: ReportState) -> ReportState:
        p = state.project
        # TODO(TIA-11): 시행령 별표 1 확보 후 공동주택 평가 대상 최소규모로 배수를 계산한다.
        multiple = None
        scope = {
            "target_years": [1, 3],  # 제5조①1: 건축물 준공 후 1년, 3년
            "scale_multiple": multiple,
        }
        if multiple is None:
            scope.update(spatial_scope(0))  # 임시: 가장 작은 구간 적용
            scope["spatial_provisional"] = True
            state.warn("평가 대상 규모 배수 미확정(시행령 별표 1 미확보): 공간적 범위는 최소 구간(반경 1.0km·4개 교차로)으로 임시 적용")
        else:
            scope.update(spatial_scope(multiple))
        state.scope = scope

        state.put("intro.overview",
                  f"사업명 {p.name}, 위치 {p.address}, 용도 {p.land_use.value}, {p.households}세대.", self.name)
        state.put("scope.target_years", "목표년도: 준공 후 1년, 3년 (교통영향평가 지침 제5조①1)", self.name)
        state.put("scope.spatial",
                  f"공간적 범위: 주된 출입구 기준 반경 {scope['radius_km']}km 이내 "
                  f"교차로 {scope['min_intersections']}개 이상 (지침 제5조②1)"
                  + (" [임시 적용]" if scope.get("spatial_provisional") else ""), self.name)
        state.put("intro.scope", state.sections["scope.target_years"] + "\n" + state.sections["scope.spatial"], self.name)
        return state
