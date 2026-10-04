"""교통영향평가 대상 여부·규모 배수 판정 (공동주택, 서울).

기준: 서울특별시 교통영향평가에 관한 조례 별표 — 아파트 건축 연면적 50,000㎡ 이상.
기준값은 data/eligibility_thresholds.json (출처·확인일 포함).
"""
import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

THRESHOLDS_PATH = Path(__file__).resolve().parent.parent / "data" / "eligibility_thresholds.json"

# 지침 제5조②1 (건축물): (배수 상한, 반경 km, 최소 교차로 수)
SPATIAL_TIERS = [(4, 1.0, 4), (8, 1.5, 8), (float("inf"), 2.0, 12)]


@lru_cache
def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Eligibility(BaseModel):
    eligible: bool | None  # None: 연면적 미입력으로 판정 불가
    gross_floor_area_m2: float | None
    threshold_m2: float
    multiple: float | None  # 연면적 / 대상 기준 (지침 제5조 공간적 범위 구간 결정)
    basis: str
    committee_review_likely: bool | None = None  # 조례 제5조②1(21층↑ 또는 10만㎡↑) 일부만 반영


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
