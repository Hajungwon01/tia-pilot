"""에이전트들이 공유하는 보고서 상태. 각 에이전트는 이 객체를 읽고 자기 몫만 채운다."""
from typing import Literal

from pydantic import BaseModel, Field

from .schemas import Approach, IntersectionResult, ProjectInput, TripGenerationResult


class IntersectionInput(BaseModel):
    """사용자가 입력하는 교차로 실측값(현장 조사는 자동화 불가 → 하이브리드)."""

    name: str
    cycle: float
    approaches: list[Approach]
    peak: Literal["am", "pm"] = "pm"  # 입력 교통량을 조사한 첨두시


# 지침 제24조⑧ 참여정도 구분
PARTICIPATION_ROLES = ["책임자", "교통환경 현황조사", "관련자료 수집", "평가지표 설정", "교통수요예측",
                       "문제점 도출·분석", "교통개선대책 수립"]


class StaffMember(BaseModel):
    """평가 대행용역 참여전문인력(지침 제24조⑦). 사람 정보라 서비스가 만들지 않고 입력받는다."""

    name: str
    affiliation: str = ""
    position: str = ""
    period: str = ""  # 근무기간
    qualification: str = ""  # 자격명·자격번호
    roles: list[str] = Field(default_factory=list)  # PARTICIPATION_ROLES 중에서
    registered: bool = True  # 규칙 별표 1 등록 기술인력 여부(미등록이면 별도 구분 표기)


class AgencyInfo(BaseModel):
    """평가대행업체·사업자 정보(지침 제24조⑤~⑥). 비어 있으면 문서에 [기재 필요]로 남는다."""

    agency_name: str = ""
    registration_no: str = ""
    registration_date: str = ""
    lead_name: str = ""  # 책임자(평가대행자)
    submission_date: str = ""
    service_period: str = ""
    printer: str = ""
    concept_design_firm: str = ""  # 구상용역 수행업체
    agency_address: str = ""
    agency_phone: str = ""
    client_name: str = ""
    client_address: str = ""
    client_phone: str = ""
    staff: list[StaffMember] = Field(default_factory=list)
    cost_basis_attached: bool = False  # 대행비용 산정근거 첨부 여부
    contract_copy_attached: bool = False  # 용역계약서 사본 첨부 여부


class ReportState(BaseModel):
    project: ProjectInput
    agency: AgencyInfo | None = None  # 표지·제출문·끝문에 쓰는 업체·인력 정보(입력)
    intersections: list[IntersectionInput] = Field(default_factory=list)  # 사용자 입력
    background_growth_rate: float | None = None  # 사업 미시행 시 배경교통량 연 증가율(예: 0.01 = 1%)

    # Planning
    scope: dict | None = None
    # Data
    trips: TripGenerationResult | None = None
    los: dict[str, dict] = Field(default_factory=dict)  # 교차로명 -> {results, avg_delay, grade}
    stages: dict[str, dict] = Field(default_factory=dict)  # 교차로명 -> {목표년도 -> {without, with, improved}}
    # Creative
    artifacts: dict[str, str] = Field(default_factory=dict)  # 표/도표 (마크다운)
    # 보고서 섹션: 체크리스트 key -> 본문. 작성한 에이전트가 소유.
    sections: dict[str, str] = Field(default_factory=dict)
    section_owner: dict[str, str] = Field(default_factory=dict)

    warnings: list[str] = Field(default_factory=list)
    needs_input: list[str] = Field(default_factory=list)  # 사용자 입력이 필요한 key
    document: str = ""
    reflection: dict | None = None
    iterations: int = 0

    def put(self, key: str, text: str, owner: str) -> None:
        self.sections[key] = text
        self.section_owner[key] = owner

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)
