"""유발교통량 추정: 세대수 × 표준 원단위. (Data 에이전트)"""
import json
from functools import lru_cache
from pathlib import Path

from .schemas import LandUse, PeakTrips, ProjectInput, TripGenerationResult

RATES_PATH = Path(__file__).resolve().parent.parent / "data" / "unit_rates.json"


@lru_cache
def load_rates(path: Path = RATES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rates_for(project: ProjectInput) -> tuple[dict, list[str]]:
    """사업이 고른 원단위 근거(임시값 | 유사시설 조사)에 따른 원단위 표와 근거의 한계 목록."""
    if project.rate_basis == "evidence":
        from app.unit_evidence import derive_rates  # 지연 import: unit_evidence가 load_rates를 쓴다

        ev = derive_rates(car_occupancy=project.car_occupancy, overrides=project.rate_overrides)
        return _with_direction(ev.rates, project, ev.notes)
    from app.unit_evidence import apply_overrides, status_from_sources

    base = load_rates()
    key = project.land_use.value
    apt = {**base[key], "mode_share": dict(base[key]["mode_share"]), "peak_hour": {k: dict(v) for k, v in base[key]["peak_hour"].items()}}
    sources = {k: "provisional" for k in ("person_trips", "car_share", "am_peak", "pm_peak", "occupancy")}
    notes: list[str] = []
    apply_overrides(apt, sources, project.rate_overrides, notes)  # 임시값 모드에서도 직접 입력한 값은 반영한다
    if project.car_occupancy is not None:
        apt["car_occupancy"] = project.car_occupancy
        sources["occupancy"] = "user"
    rates = {**base, key: apt, "_sources": sources, "_status": status_from_sources(sources, evidence_mode=False)}
    return _with_direction(rates, project, notes)


def _with_direction(rates: dict, project: ProjectInput, notes: list[str]) -> tuple[dict, list[str]]:
    """세대당 발생원단위의 방향을 정한다: 근거·직접 입력값은 project.rate_direction, 임시값은 항상 양방향 합계(8인/일은 합계로 정한 값)."""
    given = rates.get("_sources", {}).get("person_trips", "provisional") != "provisional"
    direction = project.rate_direction if given else "both"
    out = {**rates, "_direction": direction}
    if given:
        notes = notes + ([ "세대당 발생원단위를 유입(하루 동안 단지로 들어오는 사람) 기준으로 해석 — 일 총 통행은 유입×2(유출=유입 가정). 경기연구원(2023)이 활동인구 발생원단위를 유입통행량으로 정의했으나 국토부 시스템 문서로는 확정하지 못함"]
                         if direction == "inflow" else
                         ["세대당 발생원단위를 유입+유출 양방향 합계로 해석(유입 기준으로 보면 일 통행이 이 값의 2배)"])
    return out, notes


def estimate_trips(project: ProjectInput, rates: dict | None = None) -> TripGenerationResult:
    notes: list[str] = []
    if rates is None:
        rates, notes = rates_for(project)
    r = rates[project.land_use.value]

    mult = 2.0 if rates.get("_direction") == "inflow" else 1.0  # 유입 기준 원단위는 하루 유출입을 합쳐 2배
    daily_person = project.households * r["daily_person_trips_per_household"] * mult
    car_person = daily_person * r["mode_share"]["car"]
    daily_vehicle = car_person / r["car_occupancy"]

    def peak(key: str) -> PeakTrips:
        p = r["peak_hour"][key]
        total = daily_vehicle * p["ratio_of_daily"]
        return PeakTrips(in_trips=total * p["in_ratio"], out_trips=total * (1 - p["in_ratio"]))

    return TripGenerationResult(
        daily_person_trips=daily_person,
        daily_vehicle_trips=daily_vehicle,
        am_peak=peak("am"),
        pm_peak=peak("pm"),
        rates_status=rates.get("_status", "UNKNOWN"),
        rate_notes=notes,
    )
