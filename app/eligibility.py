"""교통영향평가 대상 여부·규모 배수 판정 (공동주택, 서울).

기준: 서울특별시 교통영향평가에 관한 조례 별표 — 아파트 건축 연면적 50,000㎡ 이상.
복합용도(Swa)·증축·용도변경(별표 비고 5)·약식 평가(지침 제23조) 가능 여부도 판정한다.
기준값은 data/eligibility_thresholds.json (출처·확인일 포함).
"""
import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.schemas import ProjectInput

THRESHOLDS_PATH = Path(__file__).resolve().parent.parent / "data" / "eligibility_thresholds.json"

# 지침 제5조②1 (건축물): (배수 상한, 반경 km, 최소 교차로 수)
SPATIAL_TIERS = [(4, 1.0, 4), (8, 1.5, 8), (float("inf"), 2.0, 12)]


@lru_cache
def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Abbreviated(BaseModel):
    """지침 제23조 약식 교통영향평가 적용 가능 여부."""

    possible: bool | None  # None: 판정에 필요한 입력 부족
    applied: bool = False  # 가능하고 사용자가 적용을 선택한 경우
    cases: list[str] = Field(default_factory=list)  # district(제1항 제3호) · change(제1항 제4호)
    complex_only: bool = False  # 제1항 제3호: 공간적 범위가 대지에 접하거나 연결되는 도로의 교차로(서울 지침; 국토부 지침은 공동주택이면 단지 내)
    reasons: list[str] = Field(default_factory=list)
    basis: str = ""


class Eligibility(BaseModel):
    eligible: bool | None  # None: 입력 부족으로 판정 불가
    gross_floor_area_m2: float | None  # 판정에 쓴 면적(증축은 준공 면적 + 증축 합계)
    threshold_m2: float
    multiple: float | None  # Swa/10,000 (= 연면적/대상 기준, 지침 제5조 공간적 범위 구간 결정)
    basis: str
    committee_review_likely: bool | None = None  # 시행령 제13조의4②·조례 제5조②1 일부만 반영
    kind: str = "new"
    swa: float | None = None  # 복합용도 식 값 (아파트 단일이면 연면적/50,000×10,000)
    mixed_use: bool = False
    notes: list[str] = Field(default_factory=list)
    abbreviated: Abbreviated | None = None


def assess_eligibility(gross_floor_area_m2: float | None, region: str = "seoul",
                       floors: int | None = None, thresholds: dict | None = None) -> Eligibility:
    cfg = (thresholds or load_thresholds())["apartment"][region]
    thr = cfg["threshold_m2"]
    if gross_floor_area_m2 is None:
        return Eligibility(eligible=None, gross_floor_area_m2=None, threshold_m2=thr,
                           multiple=None, basis=cfg["source"])
    review = None
    if floors is not None or gross_floor_area_m2 >= 100_000:
        review = gross_floor_area_m2 >= 100_000 or (floors or 0) >= 21
    return Eligibility(
        eligible=gross_floor_area_m2 >= thr,
        gross_floor_area_m2=gross_floor_area_m2,
        threshold_m2=thr,
        multiple=gross_floor_area_m2 / thr,
        basis=cfg["source"],
        committee_review_likely=review,
    )


def spatial_scope(multiple: float) -> dict:
    """지침 제5조②1: 대상 기준 배수 → 반경(km)·최소 교차로 수."""
    for upper, km, n in SPATIAL_TIERS:
        if multiple < upper:
            return {"radius_km": km, "min_intersections": n}
    raise AssertionError("unreachable")


# ── 복합용도·증축·용도변경·약식 평가 ──


def use_table(thresholds: dict | None = None) -> dict[str, dict]:
    return {i["key"]: i for i in (thresholds or load_thresholds())["seoul_uses"]["items"]}


def _swa(apartment_m2: float, other_uses, uses: dict[str, dict], apt_thr: float) -> float:
    """Swa = Σ(Pia/Mia) × 10,000 (공동주택 포함)."""
    total = apartment_m2 / apt_thr
    for u in other_uses:
        if u.use not in uses:
            raise ValueError(f"알 수 없는 용도 '{u.use}' (복합용도 용도 목록에 없음)")
        total += u.area_m2 / uses[u.use]["threshold_m2"]
    return total * 10_000


def _committee(project: ProjectInput, area: float | None, th: dict) -> tuple[bool | None, list[str]]:
    """시행령 제13조의4②: 21층 이상·연면적 10만㎡ 이상·판매시설·운수시설(조례가 정한 추가 대상은 확인 불가)."""
    ab = th["abbreviated"]
    uses = use_table(th)
    reasons = []
    gfa_total = (area or 0) + sum(u.area_m2 for u in project.other_uses if uses.get(u.use, {}).get("metric") == "gfa")
    if (project.floors or 0) >= ab["committee_floors"]:
        reasons.append(f"{project.floors}층(21층 이상)")
    if gfa_total >= ab["committee_gfa_m2"]:
        reasons.append(f"연면적 {gfa_total:,.0f}㎡(10만㎡ 이상)")
    if any(u.use.startswith("retail_") or u.use == "transport" for u in project.other_uses):
        reasons.append("판매시설·운수시설 용도 포함")
    if reasons:
        return True, reasons
    return (None if project.floors is None else False), []


def _abbreviated(project: ProjectInput, eligible: bool | None, committee: bool | None, committee_reasons: list[str],
                 expansion_triggered: bool | None, added_total: float | None, apt_thr: float, th: dict) -> Abbreviated:
    ab = th["abbreviated"]
    out = Abbreviated(possible=None, basis=ab["source"])
    if eligible is not True:
        out.possible = False if eligible is False else None
        out.reasons.append("평가 대상이 아니거나 대상 여부를 판정할 수 없어 약식 여부를 판단하지 않음")
        return out
    ok_cases: list[str] = []
    blockers: list[str] = []
    unknown: list[str] = []

    # 제1항 제3호: 평가를 실시한 사업지구에 건축하는 공동주택(시행령 제13조의4제2항 비해당)
    if project.in_evaluated_district:
        if committee is True:
            blockers.append("제1항 제3호 불가: 시행령 제13조의4제2항 해당(" + ", ".join(committee_reasons) + ")")
        elif committee is None:
            unknown.append("제1항 제3호: 최고 층수를 입력해야 시행령 제13조의4제2항(21층 이상) 해당 여부를 판단할 수 있음")
        else:
            ok_cases.append("district")
    elif project.in_evaluated_district is None:
        unknown.append("제1항 제3호: 교통영향평가를 실시한 사업지구 안에 건축하는지 입력 필요")

    # 제1항 제4호: 변경심의 대상(별표 1 비고 5 가목·나목)
    if project.project_kind in ("expansion", "use_change"):
        if project.existing_evaluated is not True:
            blockers.append("제1항 제4호 불가: 기존 사업이 교통영향평가 심의를 받고 완료된 경우가 아님(또는 미입력)")
        elif project.project_kind == "expansion" and expansion_triggered is False:
            blockers.append("제1항 제4호 해당 없음: 증축이 30% 이하이고 대상규모 미만이라 변경심의 대상이 아님")
        else:
            within_7 = None if project.years_since_completion is None else project.years_since_completion < ab["change_years"]
            below_range = project.project_kind == "expansion" and added_total is not None and added_total < apt_thr
            if within_7 or below_range:
                ok_cases.append("change")
            elif within_7 is None:
                unknown.append("제1항 제4호: 심의·완료 후 경과 연수 입력 필요(7년 미경과 여부)")
            else:
                blockers.append("제1항 제4호 불가: 완료 후 7년이 경과했고 증축 규모도 대상사업 범위 이상")

    out.cases = ok_cases
    out.complex_only = "district" in ok_cases
    if ok_cases:
        out.possible = True
        labels = {"district": "제1항 제3호: 평가를 실시한 사업지구의 공동주택으로 시행령 제13조의4제2항에 해당하지 않음",
                  "change": "제1항 제4호: 변경심의 대상이며 7년 미경과 또는 증축 규모가 대상범위 미만"}
        out.reasons = [labels[c] for c in ok_cases]
        if "change" in ok_cases and added_total is not None and added_total >= apt_thr:
            out.reasons.append("주의: 증축 규모가 대상규모 이상인데 문언상 7년 미경과만으로 약식이 가능함 — 승인관청 확인 필요")
    elif unknown:
        out.possible = None
        out.reasons = unknown + blockers
    else:
        out.possible = False
        out.reasons = blockers or ["약식 적용 요건(지침 제23조제1항 제3호·제4호)에 해당하지 않음"]
    out.applied = bool(project.request_abbreviated and out.possible)
    return out


def assess_project(project: ProjectInput, region: str = "seoul", thresholds: dict | None = None) -> Eligibility:
    """사업 유형(신축·증축·용도변경)·복합용도·약식 가능 여부까지 반영한 대상 판정."""
    th = thresholds or load_thresholds()
    cfg = th["apartment"][region]
    apt_thr = cfg["threshold_m2"]
    uses = use_table(th)
    sc = th["special_cases"]
    notes: list[str] = []
    basis = cfg["source"]
    kind = project.project_kind
    expansion_triggered: bool | None = None
    added_total: float | None = None
    area: float | None = project.gross_floor_area_m2
    mixed = bool(project.other_uses)
    swa: float | None = None
    eligible: bool | None = None

    if kind == "expansion":
        if mixed:
            notes.append("증축 판정에는 복합용도 합산(Swa)을 적용하지 않고 공동주택 기준만 사용함")
        if project.existing_gfa_m2 is None or project.expansion_gfa_m2 is None:
            area = None
        else:
            added_total = project.expansion_gfa_m2 + project.prior_expansion_gfa_m2
            area = project.existing_gfa_m2 + added_total
            ratio = added_total / project.existing_gfa_m2
            basis = sc["source"] + " 5.가: " + sc["expansion_rule"]
            if project.existing_evaluated is False:
                eligible = area >= apt_thr
                basis = "서울시 조례 별표 비고 5.바·사 준용(기존 건축물이 평가를 받지 않았으므로 증축 후 합산 면적을 대상규모와 비교)"
                notes.append("기존 건축물이 평가를 받지 않았다면 허가 당시 대상 여부와 기준 개정 시점에 따라 결론이 달라질 수 있음(비고 5.바·사)")
            else:
                expansion_triggered = ratio > sc["expansion_ratio"] or added_total >= apt_thr
                eligible = expansion_triggered
                if project.existing_evaluated is None:
                    notes.append("기존 건축물의 교통영향평가 이행 여부가 입력되지 않아 평가를 받고 준공된 것으로 보고 판정함")
                if not expansion_triggered:
                    notes.append(f"증축 합계 {added_total:,.0f}㎡는 기존의 {ratio * 100:.0f}%로 30% 이하이고 대상규모({apt_thr:,.0f}㎡) 미만이라 "
                                 "신규 평가 대상이 아님. 다만 시행령 제13조의8 변경심의(통보 후 5년 이내 규모 30% 이상 증가 등) 해당 여부는 별도 확인")
        swa = None if area is None else area / apt_thr * 10_000
    else:
        if kind == "use_change":
            notes.append("용도변경: 변경 후 용도별 건축 연면적으로 판정함(비고 5.나)")
            basis = sc["source"] + " 5.나: " + sc["use_change_rule"]
        if area is not None:
            swa = _swa(area, project.other_uses, uses, apt_thr)
            if mixed:
                basis = th["mixed_use"]["source"] + " — " + th["mixed_use"]["formula"]
                notes.append("복합용도의 유발교통량은 공동주택 원단위만 계산하며 다른 용도는 포함하지 않음")
                notes.append("복합용도의 공간적 범위 배수는 Swa/10,000으로 간주함(지침 제5조에 복합용도 규정이 없어 확인 필요)")
                eligible = swa >= th["mixed_use"]["swa_threshold"] - 1e-9
            else:
                eligible = area >= apt_thr

    multiple = None if swa is None else swa / 10_000
    committee, creasons = _committee(project, area, th)
    ab = _abbreviated(project, eligible, committee, creasons, expansion_triggered, added_total, apt_thr, th)
    return Eligibility(
        eligible=eligible, gross_floor_area_m2=area, threshold_m2=apt_thr, multiple=multiple, basis=basis,
        committee_review_likely=committee, kind=kind, swa=swa, mixed_use=mixed, notes=notes, abbreviated=ab)


def abbreviated_scope(ab: Abbreviated) -> dict:
    """지침 제23조②: 약식 평가의 시간적·공간적 범위."""
    return {"target_years": [1], "spatial_mode": "site_adjacent" if ab.complex_only else "two_intersections",
            "radius_km": None, "min_intersections": None, "max_intersections": None if ab.complex_only else 2}
