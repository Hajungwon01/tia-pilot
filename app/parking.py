"""주차수요 예측(원단위법, 지침 제15조)과 법정 주차대수·계획주차대수 비교.

- 법정 주차대수: 주택건설기준 등에 관한 규정 제27조제1항(특별시 면적당 대수 + 세대당 최소), 복합용도의 다른 용도는
  서울 주차장 조례 별표 2. 기준값은 data/parking_rules.json(원문 확인).
- 주차수요: 세대수 × 세대당 원단위 × 이용효율. 원단위는 입력값이 없으면 임시값(PROVISIONAL).
코드가 계산하고 문장은 쓰지 않는다(문장은 Data 에이전트가 숫자만 채워 넣음).
"""
import json
import math
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.eligibility import use_table
from app.schemas import ProjectInput
from app.trip_generation import load_rates

RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "parking_rules.json"


@lru_cache
def load_rules(path: Path = RULES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ParkingResult(BaseModel):
    legal_apartment: int | None = None  # 공동주택 법정 대수
    legal_others: dict[str, float] = Field(default_factory=dict)  # 용도 라벨 → 산정 대수(소수 첫째 자리)
    legal_others_total: int = 0
    legal_total: int | None = None
    legal_complete: bool = False  # 공동주택·다른 용도 모두 산정됨
    area_based: float | None = None  # 전용면적 합계 기준 산정치(올림 전)
    household_min: float | None = None  # 세대당 최소 기준 산정치
    binding: str | None = None  # area | household_min
    total_exclusive_area_m2: float | None = None
    demand: float | None = None  # 원단위법 주차수요(대)
    demand_per_household: float | None = None
    utilization: float = 1.0
    rate_status: str = "PROVISIONAL"  # PROVISIONAL | USER
    rate_source: str = ""
    planned: int | None = None
    cap_pct: float = 130
    cap: float | None = None  # 법정 × 상한 비율
    planned_vs_legal_pct: float | None = None
    planned_vs_demand: float | None = None  # 계획 - 수요(대), 음수면 부족
    notes: list[str] = Field(default_factory=list)


def _half_up(x: float) -> int:
    return int(math.floor(x + 0.5 + 1e-9))


def legal_apartment(unit_types, rules: dict | None = None) -> tuple[int, float, float, float]:
    """(법정 대수, 면적 기준 산정치, 세대당 최소 산정치, 전용면적 합계)."""
    r = (rules or load_rules())["apartment_legal"]
    per = r["m2_per_space"]
    area_based = hh_min = total_area = 0.0
    for u in unit_types:
        area = u.exclusive_area_m2 * u.households
        total_area += area
        area_based += area / (per["le85"] if u.exclusive_area_m2 <= 85 else per["gt85"])
        hh_min += u.households * (r["min_per_household"]["le60"] if u.exclusive_area_m2 <= 60 else r["min_per_household"]["default"])
    value = max(area_based, hh_min)
    return math.ceil(value - 1e-9), area_based, hh_min, total_area


def legal_other_uses(other_uses, rules: dict | None = None, uses: dict | None = None) -> tuple[dict[str, float], int, list[str]]:
    """공동주택 외 용도의 법정 대수. 각 용도는 소수 첫째 자리까지, 합계는 0.5 이상 올림(조례 별표 2 비고 4·6)."""
    r = (rules or load_rules())["other_uses"]
    uses = uses or use_table()
    out: dict[str, float] = {}
    notes: list[str] = []
    for u in other_uses:
        label = uses[u.use]["label"]
        rate = r["m2_per_space"].get(u.use)
        if rate is None:
            notes.append(f"'{label}'는 시설면적당 설치기준이 없어(정원·부지 기준 등) 법정 주차대수에 포함하지 못함")
            continue
        out[label] = round(u.area_m2 / rate, 1)
    return out, _half_up(sum(out.values())), notes


def assess_parking(p: ProjectInput) -> ParkingResult:
    rules = load_rules()
    res = ParkingResult(planned=p.planned_parking_spaces)
    res.cap_pct = rules["planned_cap"]["seoul_pct"]  # 서울 고정(이 도구는 서울 공동주택 대상)

    # 법정 대수
    if p.unit_types:
        if sum(u.households for u in p.unit_types) != p.households:
            res.notes.append("주택형별 세대수 합계가 세대수와 달라 법정 주차대수를 신뢰할 수 없음")
        n, area_based, hh_min, total_area = legal_apartment(p.unit_types, rules)
        res.legal_apartment, res.area_based, res.household_min, res.total_exclusive_area_m2 = n, area_based, hh_min, total_area
        res.binding = "household_min" if hh_min > area_based else "area"
    else:
        res.notes.append("주택형별 전용면적·세대수를 입력해야 법정 주차대수를 산정할 수 있음")
    others, others_total, other_notes = legal_other_uses(p.other_uses, rules)
    res.legal_others, res.legal_others_total = others, others_total
    res.notes += other_notes
    res.legal_complete = res.legal_apartment is not None and not other_notes
    if res.legal_apartment is not None:
        res.legal_total = res.legal_apartment + others_total
        res.cap = res.legal_total * res.cap_pct / 100
        if res.planned is not None and res.legal_total > 0:
            res.planned_vs_legal_pct = res.planned / res.legal_total * 100

    # 주차수요 (원단위법)
    prov = load_rates()["apartment"]["parking"]
    if p.parking_demand_per_household is not None:
        res.demand_per_household, res.rate_status = p.parking_demand_per_household, "USER"
        res.rate_source = p.parking_demand_source.strip()
    else:
        res.demand_per_household = prov["demand_per_household"]
        res.rate_source = "임시값(근거 자료 없음)"
    res.utilization = prov["utilization"]
    res.demand = p.households * res.demand_per_household * res.utilization
    if p.other_uses:
        res.notes.append("복합용도의 주차수요는 공동주택 원단위만 계산하며 다른 용도는 포함하지 않음(지침 제15조④·⑨의 복합용도 수요 산정은 별도 필요)")
    if res.planned is not None:
        res.planned_vs_demand = res.planned - res.demand
    return res
