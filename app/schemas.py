from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class LandUse(str, Enum):
    APARTMENT = "apartment"


class UseArea(BaseModel):
    """복합용도 건축물의 공동주택 외 용도별 면적. use는 data/eligibility_thresholds.json seoul_uses의 key."""

    use: str
    area_m2: float = Field(gt=0)  # 해당 용도의 건축 연면적(㎡) 또는 부지면적(동·식물원 등 부지면적 기준 용도)


class ProjectOverview(BaseModel):
    """사업의 개요 필수 기재 항목(서울 수립지침 제24조③)에서 이 도구가 계산하지 못하는 값. 비우면 보고서에 [기재 필요]로 남는다."""

    permit_laws: str = Field(default="", max_length=200)  # 인·허가 관련 법규
    project_period: str = Field(default="", max_length=100)  # 사업기간
    urban_planning: str = Field(default="", max_length=200)  # 도시계획사항(용도지역·지구단위계획 등)
    actual_use: str = Field(default="", max_length=100)  # 실제 용도
    site_area_m2: float | None = Field(default=None, gt=0)  # 대지면적
    building_coverage_pct: float | None = Field(default=None, ge=0, le=100)  # 건폐율
    floor_area_ratio_pct: float | None = Field(default=None, ge=0, le=2000)  # 용적률
    basement_floors: int | None = Field(default=None, ge=0, le=30)  # 지하 층수
    entrances: int | None = Field(default=None, ge=0, le=50)  # 사업지 진출입구 수
    parking_self: int | None = Field(default=None, ge=0)  # 자주식 주차대수
    parking_mechanical: int | None = Field(default=None, ge=0)  # 기계식 주차대수
    parking_accessible: int | None = Field(default=None, ge=0)  # 장애인 주차
    parking_women: int | None = Field(default=None, ge=0)  # 여성 주차
    parking_compact: int | None = Field(default=None, ge=0)  # 경차 주차
    parking_tour_bus: int | None = Field(default=None, ge=0)  # 관광버스 주차


class RateOverrides(BaseModel):
    """사용자가 직접 조사·인용한 유발 원단위. 값을 넣은 항목은 유사시설 자료·임시값보다 우선한다(출처는 보고서에 남는다)."""

    person_trips_per_household: float | None = Field(default=None, gt=0, le=30)  # 세대당 일 발생(인/일)
    car_share_pct: float | None = Field(default=None, ge=0, le=100)  # 승용차 분담률(%)
    # 승용차 외 수단분담률(%): 넷을 모두 넣고 승용차 분담률과 합이 100(±1)이어야 한다. 별지 서식의 수단분담률 표에 그대로 들어간다.
    taxi_share_pct: float | None = Field(default=None, ge=0, le=100)
    bus_share_pct: float | None = Field(default=None, ge=0, le=100)
    subway_share_pct: float | None = Field(default=None, ge=0, le=100)  # 도시철도(전철)
    other_share_pct: float | None = Field(default=None, ge=0, le=100)  # 도보·자전거·기타
    am_in_pct: float | None = Field(default=None, ge=0, le=100)  # 오전 첨두시 유입(일 유입 대비 %)
    am_out_pct: float | None = Field(default=None, ge=0, le=100)
    pm_in_pct: float | None = Field(default=None, ge=0, le=100)
    pm_out_pct: float | None = Field(default=None, ge=0, le=100)
    source: str = Field(default="", max_length=300)  # 조사·자료 출처

    @model_validator(mode="after")
    def _modes(self):
        others = (self.taxi_share_pct, self.bus_share_pct, self.subway_share_pct, self.other_share_pct)
        if all(v is None for v in others):
            return self
        if any(v is None for v in others) or self.car_share_pct is None:
            raise ValueError("수단분담률은 승용차·택시·버스·전철·도보 및 기타를 모두 입력하세요.")
        total = self.car_share_pct + sum(others)
        if abs(total - 100) > 1.0:
            raise ValueError(f"수단분담률의 합이 {total:g}%입니다(100%여야 합니다).")
        return self

    @model_validator(mode="after")
    def _pairs(self):
        for a, b, name in ((self.am_in_pct, self.am_out_pct, "오전"), (self.pm_in_pct, self.pm_out_pct, "오후")):
            if (a is None) != (b is None):
                raise ValueError(f"{name} 첨두 유입·유출은 둘 다 입력하세요.")
            if a is not None and a + b <= 0:
                raise ValueError(f"{name} 첨두 유입·유출의 합이 0입니다.")
        return self

    def given(self) -> bool:
        return any(v is not None for k, v in self.model_dump().items() if k != "source")


class UnitType(BaseModel):
    """주택형(전용면적) 구성. 법정 주차대수 산정에 쓴다."""

    exclusive_area_m2: float = Field(gt=0)  # 세대당 전용면적(㎡)
    households: int = Field(gt=0)


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

    overview: ProjectOverview = Field(default_factory=ProjectOverview)  # 사업의 개요 필수 기재(서울 지침 제24조③)

    # 주차 (지침 제15조, 별표 2 8.가⒁)
    unit_types: list[UnitType] = Field(default_factory=list)  # 주택형별 전용면적·세대수(합계가 세대수와 같아야 함)
    planned_parking_spaces: int | None = Field(default=None, ge=0)  # 건축계획상 총 주차대수
    parking_demand_per_household: float | None = Field(default=None, gt=0)  # 세대당 주차수요 원단위(대/세대), 없으면 임시값
    parking_demand_source: str = Field(default="", max_length=300)  # 원단위 자료 출처(조사 사례·관련 자료)
    # 원단위 근거: provisional=임시값, evidence=교통영향평가정보지원시스템 유사시설 조사 중앙값(app/unit_evidence.py)
    rate_basis: Literal["provisional", "evidence"] = "provisional"
    # 유사시설 값·직접 입력한 '세대당 일 발생원단위(인/일)'가 가리키는 방향. inflow=하루 동안 단지로 들어오는 사람(한 방향, 경기연구원 2023 연구의
    # 활동인구 발생원단위 정의), both=유입+유출 합계. 일 총 통행은 유입 기준이면 ×2(유출=유입 가정). 임시값(8인/일)은 항상 양방향 합계.
    rate_direction: Literal["inflow", "both"] = "inflow"
    # 승용차 평균 재차인원(명/대, 운전자 포함). 유사시설 자료에 없는 값이라 직접 조사·인용해 입력한다. 없으면 임시값.
    car_occupancy: float | None = Field(default=None, ge=1.0, le=8.0)
    rate_overrides: RateOverrides = Field(default_factory=RateOverrides)  # 직접 입력한 발생·분담률·첨두 원단위
    car_occupancy_source: str = Field(default="", max_length=300)

    # 개선 후보 탐색 조건(비우면 임의 기본값 7초·60~180초). 현장 신호운영 기준(보행 횡단시간 등)으로 입력하는 것이 맞다.
    min_green_s: float | None = Field(default=None, gt=0, le=60)
    cycle_search_min_s: float | None = Field(default=None, ge=30, le=300)
    cycle_search_max_s: float | None = Field(default=None, ge=30, le=300)

    @model_validator(mode="after")
    def _cycle_range(self):
        lo, hi = self.cycle_search_min_s, self.cycle_search_max_s
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("신호주기 탐색 범위의 최소가 최대보다 큽니다.")
        return self

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
    rates_status: str  # PROVISIONAL이면 결과 미검증, PARTIAL_EVIDENCE면 일부(재차인원)만 임시
    rate_notes: list[str] = Field(default_factory=list)  # 원단위 근거의 한계·대체 내역


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
