"""유발교통량 추정: 세대수 × 표준 원단위. (Data 에이전트)"""
import json
from functools import lru_cache
from pathlib import Path

from .schemas import LandUse, PeakTrips, ProjectInput, TripGenerationResult

RATES_PATH = Path(__file__).resolve().parent.parent / "data" / "unit_rates.json"


@lru_cache
def load_rates(path: Path = RATES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def estimate_trips(project: ProjectInput, rates: dict | None = None) -> TripGenerationResult:
    rates = rates or load_rates()
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
    )
