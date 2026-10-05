from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class LandUse(str, Enum):
    APARTMENT = "apartment"


class UseArea(BaseModel):
    """복합용도 건축물의 공동주택 외 용도별 면적. use는 data/eligibility_thresholds.json seoul_uses의 key."""

    use: str
    area_m2: float = Field(gt=0)  # 해당 용도의 건축 연면적(㎡) 또는 부지면적(동·식물원 등 부지면적 기준 용도)


class ProjectInput(BaseModel):
    """Planning 에이전트 입력: 프로젝트 규모/위치/용도."""

    name: str
    address: str
    land_use: LandUse = LandUse.APARTMENT
    households: int = Field(gt=0)
    # 신축·용도변경: 공동주택 건축 연면적(용도변경은 변경 후 면적). 증축은 아래 기존·증축 면적으로 판정한다.
    gross_floor_area_m2: float | None = Field(default=None, gt=0)
    floors: int | None = Field(default=None, gt=0)  # 최고 층수

    # 사업 유형과 복합용도·증축 (시행령 별표 1 2.나·비고 5)
    project_kind: Literal["new", "expansion", "use_change"] = "new"
    other_uses: list[UseArea] = Field(default_factory=list)  # 동일 건축물·부지의 공동주택 외 용도(복합용도)
    existing_gfa_m2: float | None = Field(default=None, gt=0)  # 증축: 증축 전 준공 연면적
    expansion_gfa_m2: float | None = Field(default=None, gt=0)  # 증축: 이번 증축 연면적
    prior_expansion_gfa_m2: float = Field(default=0.0, ge=0)  # 증축: 이전에 이미 증축한 연면적 합계
    existing_evaluated: bool | None = None  # 기존 건축물이 교통영향평가를 받고 준공됐는지

    # 약식 평가 (지침 제23조)
    in_evaluated_district: bool | None = None  # 교통영향평가를 실시한 사업지구 안에 건축하는지
    years_since_completion: float | None = Field(default=None, ge=0)  # 기존 사업 심의·완료 후 경과 연수
    request_abbreviated: bool = False  # 약식 적용 가능하면 적용(지침상 '할 수 있다'라 사용자가 선택)


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
    project_share: float = Field(default=0.0, ge=0, le=1)  # 이 접근로에 실리는 사업 유발 첨두교통량 비율(방면별 배분율)


class IntersectionResult(BaseModel):
    approach: str
    capacity: float
    vc_ratio: float
    delay: float  # 평균 제어지체 (초/대)
    los: str
