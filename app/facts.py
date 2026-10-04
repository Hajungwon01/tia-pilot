"""AI가 쓴 문장을 계산 결과와 대조하는 환각 점검.

LLM은 숫자를 만들지 못한다는 원칙을 코드로 강제한다:
1) 단위가 붙은 숫자는 계산 결과(facts)에 있는 값이어야 한다.
2) 'LOS X' 등급은 계산된 등급이어야 한다.
3) 용량 초과·포화 단정은 v/c ≥ 1인 접근로가 있을 때만 허용한다.
"""
import re

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


class FactTable:
    def __init__(self) -> None:
        self.numbers: set[float] = set()
        self.grades: set[str] = set()
        self.max_vc: float | None = None

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
    f.add(p.households, p.gross_floor_area_m2, p.floors, 1, 3)
    if state.scope:
        f.add(state.scope.get("radius_km"), state.scope.get("min_intersections"),
              state.scope.get("eligibility", {}).get("threshold_m2"))
    t = state.trips
    if t:
        for pk in (t.am_peak, t.pm_peak):
            f.add(pk.in_trips, pk.out_trips, pk.total)
        f.add(t.daily_vehicle_trips, t.daily_person_trips)
    vcs = []
    for v in state.los.values():
        f.add(v["avg_delay"])
        f.grades.add(v["grade"])
        for r in v["results"]:
            f.add(r["capacity"], r["vc_ratio"], r["vc_ratio"] * 100, r["delay"])
            f.grades.add(r["los"])
            vcs.append(r["vc_ratio"])
    for ix in state.intersections:
        f.add(ix.cycle)
        for a in ix.approaches:
            f.add(a.volume, a.saturation_flow, a.green_time)
    if state.background_growth_rate is not None:
        f.add(state.background_growth_rate * 100)
    for years in state.stages.values():
        for y, st in years.items():
            f.add(y, st.get("delay_reduction"))
            for stage in ("without", "with", "improved"):
                d = st[stage]
                f.add(d["avg_delay"], d["max_vc"])
                f.grades.add(d["grade"])
                vcs.append(d["max_vc"])
                for g in d["greens"].values():
                    f.add(g)
                for v in d["volumes"].values():
                    f.add(v)
                for r in d["results"]:
                    f.add(r["capacity"], r["vc_ratio"], r["vc_ratio"] * 100, r["delay"])
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
