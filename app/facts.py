"""AI가 쓴 문장을 계산 결과와 대조하는 환각 점검.

LLM은 숫자를 만들지 못한다는 원칙을 코드로 강제한다:
1) 단위가 붙은 숫자는 계산 결과(facts)에 있는 값이어야 한다.
2) 'LOS X' 등급은 계산된 등급이어야 한다.
3) 용량 초과·포화 단정은 v/c ≥ 1인 접근로가 있을 때만 허용한다.
"""
import re

from app.semantic_rules import DEMAND_OVER_LEGAL, INOUT_AS_TREND, NO_DATA_HEDGE, UNSUPPORTED_USE, parking_shortage_claims, split_sentences
from app.state import ReportState

# 단위 뒤에는 조사(가·로·의…)가 흔히 붙으므로 허용하고, 다른 낱말의 일부인 경우만 제외한다
# (초과·분석·분포·개선·개발·개월·개인·년도·min 등).
UNIT_NUM = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(대/시|대/일|초/대|초|%|㎡|km|세대|개소|개|년|분|m)"
    r"(?!과|석|류|포|리|산|선|발|략|별|인|요|월|도|[A-Za-z])"
)
# \b는 한글을 단어 문자로 보므로 "LOS F입니다"를 놓친다 → 뒤에 영문자만 아니면 허용
LOS_MENTION = re.compile(r"LOS\s*(FFF|FF|[A-F])(?![A-Za-z])")
OVER_CAPACITY = re.compile(r"용량\s*(?:을\s*)?초과|통행능력\s*(?:을\s*)?초과|포화\s*(?:상태|되)|v/c[^.\n]{0,12}1\s*(?:을\s*)?(?:초과|넘)")


# 평면교차로 설계 지침(2004) 인용 기준에 나오는 수치(app/design_criteria.CITED_CRITERIA): 길이 계수 1.5·2.0, 자동차 길이 7.0m,
# 차로 테이퍼 1:8·1:15·1:4, 교통섬 9·5·7㎡, 회전반경 15·12·10·6m, 쪽수 50·51·52·61·70, 도시지역 설계속도 80·60·50·40km/h·감속 20km/h
DESIGN_CRITERIA_NUMBERS = (1.5, 2.0, 7.0, 8, 15, 4, 9, 5, 7, 12, 10, 6, 50, 51, 52, 61, 70, 80, 60, 40, 20)


class FactTable:
    def __init__(self) -> None:
        self.numbers: set[float] = set()
        self.grades: set[str] = set()
        self.max_vc: float | None = None
        self.parking_not_short: bool = False  # 계획 ≥ 법정(또는 법정 미산정이면 판단 안 함)
        self.transit_data: bool = False  # 대중교통·보행·자전거 이용 자료가 입력됨(현재 입력 항목이 없어 항상 False)

    def add(self, *vals: float | int | None) -> None:
        for v in vals:
            if v is not None:
                self.numbers.add(float(v))

    def has_number(self, x: float, decimals: int) -> bool:
        tol = 0.5 * 10 ** (-decimals) + 1e-9
        return any(abs(x - f) <= tol for f in self.numbers)


def build_facts(state: ReportState) -> FactTable:
    f = FactTable()
    p = state.project
    f.add(p.households, p.gross_floor_area_m2, p.floors, 1, 3, p.existing_gfa_m2, p.expansion_gfa_m2)
    f.add(*[u.area_m2 for u in p.other_uses])
    if state.scope:
        elig = state.scope.get("eligibility", {})
        f.add(state.scope.get("radius_km"), state.scope.get("min_intersections"), state.scope.get("max_intersections"),
              elig.get("threshold_m2"), elig.get("gross_floor_area_m2"), elig.get("swa"))
    t = state.trips
    if t:
        for pk in (t.am_peak, t.pm_peak):
            f.add(pk.in_trips, pk.out_trips, pk.total)
        f.add(t.daily_vehicle_trips, t.daily_person_trips)
    if state.parking:
        pk = state.parking
        if pk.get("planned") is not None and pk.get("legal_total") is not None:
            f.parking_not_short = pk["planned"] >= pk["legal_total"]
            f.add(abs(pk["planned"] - pk["legal_total"]))
        if pk.get("planned") is not None and pk.get("demand") is not None:
            f.add(abs(pk["planned"] - pk["demand"]))
        f.add(pk.get("demand"), pk.get("legal_apartment"), pk.get("legal_total"), pk.get("planned"), pk.get("cap"),
              pk.get("cap_pct"), pk.get("planned_vs_legal_pct"), pk.get("demand_per_household"), pk.get("legal_others_total"))
    vcs = []
    for v in state.los.values():
        f.add(v["avg_delay"])
        f.grades.add(v["grade"])
        f.add(v.get("critical_vc"))
        for r in v["results"]:
            f.add(r["capacity"], r["vc_ratio"], r["vc_ratio"] * 100, r["delay"])
            f.add(r.get("volume"), r.get("saturation"), r.get("y"), r.get("lanes"), r.get("phase"))  # 편람 차로군 값
            f.grades.add(r["los"])
            vcs.append(r["vc_ratio"])
    for ix in state.intersections:
        f.add(ix.cycle)
        for a in ix.approaches:
            f.add(a.volume, a.saturation_flow, a.green_time)
    for ix in state.detailed_intersections:
        f.add(ix.cycle, ix.phf, len(ix.phases), len(ix.approaches))
        for p in ix.phases:
            f.add(p.green, p.yellow)
        for a in ix.approaches:
            f.add(a.v_left, a.v_through, a.v_right, a.lanes, a.opposing_through, a.heavy_pct, a.lane_width_m,
                  a.speed_kph, a.link_length_m, a.offset_s, a.left_radius_m)
            f.add(a.lanes + 1)  # 개선 시나리오의 차로 증설 후 차로수
            f.add(a.project_share_left * 100, a.project_share_through * 100, a.project_share_right * 100)
    if state.background_growth_rate is not None:
        f.add(state.background_growth_rate * 100)
    for years in state.stages.values():
        for y, st in years.items():
            f.add(y, st.get("delay_reduction"))
            sc = st.get("scenarios")
            if sc:
                f.add(sc["base_delay"])
                f.grades.add(sc["base_grade"])
                for s in sc["scenarios"]:
                    f.add(s["avg_delay"], s["delay_reduction"], s["max_vc"], s["critical_vc"], s["cycle"], *s["greens"].values())
                    d = s.get("design")
                    if d:
                        f.add(d["arrivals"], d["design_speed"], d["standard_m"], d["minimum_m"])
                if sc["scenarios"]:
                    f.add(*DESIGN_CRITERIA_NUMBERS)  # [설계 기준]은 개선 후보가 있을 때만 AI 입력에 들어가므로 그때만 인용을 허용한다
                    f.grades.add(s["grade"])
                    vcs.append(s["max_vc"])
            for stage in ("without", "with", "improved"):
                d = st[stage]
                f.add(d["avg_delay"], d["max_vc"], d.get("critical_vc"))
                f.grades.add(d["grade"])
                vcs.append(d["max_vc"])
                for g in d["greens"].values():
                    f.add(g)
                for v in d["volumes"].values():
                    f.add(v)
                for r in d["results"]:
                    f.add(r["capacity"], r["vc_ratio"], r["vc_ratio"] * 100, r["delay"])
                    f.add(r.get("volume"), r.get("saturation"), r.get("y"), r.get("lanes"), r.get("phase"))
                    f.grades.add(r["los"])
    for ix in state.intersections:
        for a in ix.approaches:
            f.add(a.project_share * 100)
    f.max_vc = max(vcs) if vcs else None
    return f


def verify_text(text: str, facts: FactTable) -> list[str]:
    """문장에서 근거 없는 주장을 찾아 사람이 읽을 수 있는 목록으로 반환한다(빈 목록이면 통과)."""
    issues: list[str] = []
    for num, unit in UNIT_NUM.findall(text):
        raw = num.replace(",", "")
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if not facts.has_number(float(raw), decimals):
            issues.append(f"근거 없는 수치 '{num}{unit}'")
    for g in LOS_MENTION.findall(text):
        if g not in facts.grades:
            issues.append(f"계산되지 않은 등급 'LOS {g}'")
    if facts.parking_not_short and parking_shortage_claims(text):
        issues.append("계획 주차대수가 법정 이상인데 부족하다고 서술하거나 주차대수를 늘리라고 제안(주차 판정과 반대)")
    if DEMAND_OVER_LEGAL.search(text):
        issues.append("원단위법 수요와 법정 대수를 서로 '초과'로 비교(서로 다른 기준)")
    if not facts.transit_data and any(UNSUPPORTED_USE.search(sent) and not NO_DATA_HEDGE.search(sent) for sent in split_sentences(text)):
        issues.append("입력 자료가 없는 대중교통·보행·자전거 이용 수준을 단정(현황 자료 없음, 조사 필요로 써야 함)")
    if INOUT_AS_TREND.search(text):
        issues.append("유입·유출(같은 시간대의 방향별 값)을 시간에 따른 증가·감소로 서술")
    if OVER_CAPACITY.search(text) and not (facts.max_vc is not None and facts.max_vc >= 1.0):
        vc = "계산된 v/c 없음" if facts.max_vc is None else f"최대 v/c {facts.max_vc:.2f}"
        issues.append(f"용량 초과·포화 단정(근거: {vc})")
    return list(dict.fromkeys(issues))


def review_sections(state: ReportState, owner: str = "ai") -> dict[str, list[str]]:
    """LLM(owner)이 쓴 섹션을 계산 결과와 대조해 {key: 문제 목록}을 반환한다. MOCK·빈 문장은 제외."""
    from app.core.llm_client import MOCK_PREFIX

    facts = build_facts(state)
    flagged: dict[str, list[str]] = {}
    for key, text in state.sections.items():
        if state.section_owner.get(key) != owner or not text.strip() or text.startswith(MOCK_PREFIX):
            continue
        issues = verify_text(text, facts)
        if issues:
            flagged[key] = issues
    return flagged
