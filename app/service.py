"""웹/API가 공유하는 분석 실행 로직: 요청 검증, 비용 안전장치, 결과 요약."""
import logging
import secrets

from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.core.llm_client import LLMClient
from app.docx_export import NEEDS_INPUT_LABELS
from app.facts import review_sections
from app.hcm_signal import DetailedIntersection
from app.pipeline import TIAPipeline
from app.schemas import ProjectInput
from app.state import AgencyInfo, IntersectionInput, ReportState
from app.storage import LlmRunLog, SqliteJobStore

log = logging.getLogger("tia.service")


class ServiceError(Exception):
    """사용자에게 보여줄 수 있는 오류(HTTP 상태 코드 포함)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class AnalyzeRequest(BaseModel):
    """분석 요청. 비율은 소수(0.02 = 2%)로 받는다(웹 폼은 %로 입력받아 변환)."""

    project: ProjectInput
    agency: AgencyInfo | None = None
    intersections: list[IntersectionInput] = Field(default_factory=list)  # 간이 입력(포화교통류율 직접 입력)
    detailed_intersections: list[DetailedIntersection] = Field(default_factory=list)  # 편람 운영분석 상세 입력
    background_growth_rate: float | None = Field(default=None, ge=-0.2, le=0.5)
    use_llm: bool = False  # 실제 LLM으로 문장 작성(비용 발생). 기본 꺼짐
    access_code: str = ""


def validate_request(req: AnalyzeRequest, s: Settings) -> None:
    if len(req.intersections) > s.max_intersections:
        raise ServiceError(422, f"교차로는 최대 {s.max_intersections}개까지 입력할 수 있습니다.")
    for ix in req.intersections:
        where = f"교차로 '{ix.name}'"
        if not 1 <= len(ix.approaches) <= s.max_approaches:
            raise ServiceError(422, f"{where}: 접근로는 1~{s.max_approaches}개여야 합니다.")
        names = [a.name for a in ix.approaches]
        if len(set(names)) != len(names):
            raise ServiceError(422, f"{where}: 접근로 이름이 중복됩니다.")
        if ix.cycle <= 0:
            raise ServiceError(422, f"{where}: 신호주기는 0보다 커야 합니다.")
        for a in ix.approaches:
            if a.green_time >= ix.cycle:
                raise ServiceError(422, f"{where} {a.name} 접근로: 녹색시간({a.green_time:g}초)은 신호주기({ix.cycle:g}초)보다 짧아야 합니다.")
        if sum(a.project_share for a in ix.approaches) > 1.0001:
            raise ServiceError(422, f"{where}: 접근로별 사업 교통량 배분율의 합이 100%를 넘습니다.")
    if len(req.intersections) + len(req.detailed_intersections) > s.max_intersections:
        raise ServiceError(422, f"교차로는 간이·상세 합쳐 최대 {s.max_intersections}개까지 입력할 수 있습니다.")
    for ix in req.detailed_intersections:
        where = f"상세 교차로 '{ix.name}'"
        if not 1 <= len(ix.approaches) <= s.max_approaches:
            raise ServiceError(422, f"{where}: 접근로는 1~{s.max_approaches}개여야 합니다.")
        if len(ix.phases) > 8:
            raise ServiceError(422, f"{where}: 현시는 최대 8개까지 입력할 수 있습니다.")
        share = sum(a.project_share_left + a.project_share_through + a.project_share_right for a in ix.approaches)
        if share > 1.0001:
            raise ServiceError(422, f"{where}: 이동류별 사업 교통량 배분율의 합이 100%를 넘습니다.")
        for a in ix.approaches:
            if a.lanes > 8 or a.left_lanes > 4 or a.right_lanes > 4:
                raise ServiceError(422, f"{where} {a.name}: 차로 수가 허용 범위를 벗어났습니다.")
    names = [ix.name for ix in req.intersections] + [ix.name for ix in req.detailed_intersections]
    if len(set(names)) != len(names):
        raise ServiceError(422, "교차로 이름이 중복됩니다.")


def check_llm_allowed(req: AnalyzeRequest, s: Settings, limiter: LlmRunLog) -> None:
    if not req.use_llm:
        return
    if s.llm_mock_mode:
        raise ServiceError(400, "서버에 LLM 키가 설정되어 있지 않아 실제 LLM을 사용할 수 없습니다. 체크를 해제하세요.")
    if s.app_access_code and not secrets.compare_digest(req.access_code.encode(), s.app_access_code.encode()):
        raise ServiceError(403, "접근 코드가 올바르지 않습니다.")
    if not limiter.allow(s.max_live_runs_per_hour):
        raise ServiceError(429, f"실제 LLM 분석은 시간당 {s.max_live_runs_per_hour}회로 제한되어 있습니다. 잠시 후 다시 시도하세요.")


async def run_analysis(req: AnalyzeRequest, store: SqliteJobStore, limiter: LlmRunLog, owner: str,
                       settings: Settings | None = None) -> tuple[str, ReportState]:
    s = settings or get_settings()
    validate_request(req, s)
    check_llm_allowed(req, s, limiter)
    state = ReportState(project=req.project, agency=req.agency, intersections=req.intersections,
                        detailed_intersections=req.detailed_intersections,
                        background_growth_rate=req.background_growth_rate)
    llm = LLMClient(force_mock=not req.use_llm)
    state.llm_used = not llm.mock_mode
    try:
        state = await TIAPipeline(llm).run(state)
    except ValueError as e:  # 입력 조합이 계산 불가능한 경우(예: 최소 녹색시간 부족)
        raise ServiceError(422, f"입력값으로 계산할 수 없습니다: {e}") from e
    except Exception as e:  # LLM 호출 실패 등. 상세는 서버 로그에만 남긴다.
        log.exception("분석 실패")
        raise ServiceError(502, f"분석 중 오류가 발생했습니다({type(e).__name__}).") from e
    return store.put(state, owner), state


def summarize(state: ReportState, job_id: str) -> dict:
    """화면·API 응답용 요약(JSON 직렬화 가능)."""
    flagged = review_sections(state)
    r = state.reflection or {}
    return {
        "job_id": job_id,
        "download_url": f"/api/report/{job_id}.docx",
        "project": state.project.model_dump(mode="json"),
        "llm": {"used": state.llm_used, "mock_sections": r.get("unverified_mock", [])},
        "eligibility": (state.scope or {}).get("eligibility"),
        "scope": {k: v for k, v in (state.scope or {}).items() if k != "eligibility"},
        "trips": state.trips.model_dump(mode="json") if state.trips else None,
        "stages": {n: {str(y): st for y, st in years.items()} for n, years in state.stages.items()},
        "los": state.los,
        "reflection": {"passed": r.get("passed"), "auto_total": r.get("auto_total"),
                       "missing": r.get("missing", []), "manual": r.get("manual", []),
                       "flagged": flagged},
        "needs_input": [{"key": k, "label": NEEDS_INPUT_LABELS.get(k, k)} for k in state.needs_input],
        "warnings": state.warnings,
        "document_markdown": state.document,
    }
