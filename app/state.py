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


class ReportState(BaseModel):
    project: ProjectInput
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
