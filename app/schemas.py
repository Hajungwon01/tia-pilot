from enum import Enum

from pydantic import BaseModel, Field


class LandUse(str, Enum):
    APARTMENT = "apartment"


class ProjectInput(BaseModel):
    """Planning 에이전트 입력: 프로젝트 규모/위치/용도."""

    name: str
    address: str
    land_use: LandUse = LandUse.APARTMENT
    households: int = Field(gt=0)


class PeakTrips(BaseModel):
    in_trips: float
    out_trips: float

    @property
    def total(self) -> float:
        return self.in_trips + self.out_trips


class TripGenerationResult(BaseModel):
    daily_person_trips: float
    daily_vehicle_trips: float
    am_peak: PeakTrips  # 첨두시 승용차 유발 통행(대/시)
    pm_peak: PeakTrips
    rates_status: str  # PROVISIONAL이면 결과 미검증


class Approach(BaseModel):
    """신호교차로 한 접근로(차로군)."""

    name: str
    volume: float = Field(ge=0)  # 교통량 (대/시)
    saturation_flow: float = Field(gt=0)  # 포화교통류율 (대/시)
    green_time: float = Field(gt=0)  # 유효녹색시간 (초)


class IntersectionResult(BaseModel):
    approach: str
    capacity: float
    vc_ratio: float
    delay: float  # 평균 제어지체 (초/대)
    los: str
