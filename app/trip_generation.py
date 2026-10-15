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

        ev = derive_rates(car_occupancy=project.car_occupancy)
        return ev.rates, ev.notes
    rates = load_rates()
    if project.car_occupancy is not None:  # 임시값 모드에서도 입력한 재차인원은 반영(나머지는 임시값이라 상태는 PROVISIONAL)
        rates = {**rates, project.land_use.value: {**rates[project.land_use.value], "car_occupancy": project.car_occupancy}}
    return rates, []


def estimate_trips(project: ProjectInput, rates: dict | None = None) -> TripGenerationResult:
    notes: list[str] = []
    if rates is None:
        rates, notes = rates_for(project)
    r = rates[project.land_use.value]

    daily_person = project.households * r["daily_person_trips_per_household"]
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
