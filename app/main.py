"""FastAPI 앱: 입력 폼(웹), 분석 API, DOCX 다운로드.

실행: uvicorn app.main:app --reload --port 8000
"""
import io
import json
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.config import get_settings
from app.docx_export import build_docx
from app.service import AnalyzeRequest, JobStore, RateLimiter, ServiceError, run_analysis, summarize
from app.state import PARTICIPATION_ROLES

BASE = Path(__file__).resolve().parent
DISCLAIMER = "본 서비스는 교통영향평가서 초안 작성 지원 도구입니다. 실제 인허가 제출용이 아니며, 최종 검토·날인은 교통기술사 등 전문가가 수행해야 합니다."

app = FastAPI(title="교통영향평가 초안 자동화", version="0.1.0")
templates = Jinja2Templates(directory=str(BASE / "templates"))
store = JobStore()
limiter = RateLimiter()


@app.exception_handler(ServiceError)
async def service_error_handler(_: Request, exc: ServiceError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


@app.get("/health")
async def health():
    s = get_settings()
    return {"status": "ok", "llm": {"provider": s.llm_provider, "model": s.model, "available": not s.llm_mock_mode,
                                    "access_code_required": bool(s.app_access_code)}}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    s = get_settings()
    return templates.TemplateResponse(request, "index.html", {
        "disclaimer": DISCLAIMER, "llm_available": not s.llm_mock_mode, "llm_provider": s.llm_provider,
        "llm_model": s.model, "needs_code": bool(s.app_access_code), "roles": PARTICIPATION_ROLES,
    })


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest):
    job_id, state = await run_analysis(req, store, limiter)
    return summarize(state, job_id)


def _format_validation(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        loc = " → ".join(str(x) for x in err["loc"] if x != "body")
        out.append(f"{loc}: {err['msg']}")
    return out


@app.post("/ui/analyze", response_class=HTMLResponse)
async def ui_analyze(request: Request):
    """폼이 보낸 JSON을 분석하고 결과 HTML 조각을 돌려준다(오류도 HTML 조각)."""
    def err(status: int, messages: list[str]):
        return templates.TemplateResponse(request, "partials/error.html", {"messages": messages}, status_code=status)

    try:
        req = AnalyzeRequest.model_validate(json.loads(await request.body()))
    except json.JSONDecodeError:
        return err(400, ["요청 형식이 올바르지 않습니다."])
    except ValidationError as e:
        return err(422, _format_validation(e))
    try:
        job_id, state = await run_analysis(req, store, limiter)
    except ServiceError as e:
        return err(e.status, [e.message])
    return templates.TemplateResponse(request, "partials/result.html",
                                      {"s": summarize(state, job_id), "disclaimer": DISCLAIMER})


@app.get("/api/report/{job_id}.docx")
async def report_docx(job_id: str):
    state = store.get(job_id)
    if state is None:
        raise ServiceError(404, "결과를 찾을 수 없습니다(만료되었거나 서버가 재시작되었을 수 있습니다). 다시 분석하세요.")
    buf = io.BytesIO()
    build_docx(state).save(buf)
    name = quote(f"교통영향평가서_초안_{state.project.name}.docx")
    return Response(
        buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"},
    )
