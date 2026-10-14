"""FastAPI 앱: 입력 폼(웹), 분석 API, DOCX 다운로드, 베타 초대 코드 로그인.

실행: uvicorn app.main:app --reload --port 8000
"""
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import ValidationError

from app import auth
from app.charts import chart_rows, render_svg
from app.config import get_settings
from app.counts import CountsError, parse_counts
from app.docx_export import build_docx
from app.eligibility import use_table
from app.reflection import load_checklist
from app.service import AnalyzeRequest, ServiceError, run_analysis, summarize
from app.state import PARTICIPATION_ROLES
from app.storage import Database, LlmRunLog, SqliteJobStore

BASE = Path(__file__).resolve().parent
DISCLAIMER = "본 서비스는 교통영향평가서 초안 작성 지원 도구입니다. 실제 인허가 제출용이 아니며, 최종 검토·날인은 교통기술사 등 전문가가 수행해야 합니다."

_s = get_settings()
db = Database(_s.db_path)
store = SqliteJobStore(db, ttl_sec=_s.job_ttl_hours * 3600)
limiter = LlmRunLog(db)
throttle = auth.LoginThrottle()


@asynccontextmanager
async def lifespan(_: FastAPI):
    auth.validate_config(get_settings())  # 운영 설정이 위험하면 시작하지 않는다
    yield


app = FastAPI(title="교통영향평가 초안 자동화", version="0.2.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)  # 공개 API 문서는 끈다
templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.globals["render_svg"] = lambda spec: Markup(render_svg(spec))  # 계산 결과로만 만든 SVG(라벨은 escape됨)
templates.env.globals["chart_rows"] = chart_rows

OPEN_PAGES = {"/", "/guide"}  # 소개·안내 페이지는 로그인 없이 볼 수 있다(분석·다운로드는 로그인 필요)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                               "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


@app.middleware("http")
async def guard(request: Request, call_next):
    s = get_settings()
    path = request.url.path
    if path in auth.PUBLIC_PATHS or path in OPEN_PAGES or path.startswith("/static/"):
        user = auth.current_user(request, s) or auth.ANON
    else:
        user = auth.current_user(request, s)
        if user is None:
            if path.startswith(("/api", "/ui")):
                resp = JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
            else:
                resp = RedirectResponse("/login", status_code=303)
            for k, v in SECURITY_HEADERS.items():
                resp.headers[k] = v
            return resp
    request.state.user = user
    resp = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    if request.url.path != "/health":
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(ServiceError)
async def service_error_handler(_: Request, exc: ServiceError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


@app.get("/health")
async def health():
    s = get_settings()
    return {"status": "ok", "llm": {"available": not s.llm_mock_mode, "access_code_required": bool(s.app_access_code)},
            "auth": s.auth_enabled}


# ── 로그인 ──
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    s = get_settings()
    if not s.auth_enabled or auth.current_user(request, s):
        return RedirectResponse("/app", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"disclaimer": DISCLAIMER})


@app.post("/api/login")
async def api_login(request: Request):
    s = get_settings()
    if not s.auth_enabled:
        return {"ok": True}
    ip = auth.client_ip(request, s)
    if throttle.blocked(ip, s.login_max_failures):
        return JSONResponse({"detail": "로그인 시도가 너무 많습니다. 10분 뒤 다시 시도하세요."}, status_code=429)
    try:
        code = str((json.loads(await request.body()) or {}).get("code", ""))
    except (json.JSONDecodeError, AttributeError):
        return JSONResponse({"detail": "요청 형식이 올바르지 않습니다."}, status_code=400)
    user = auth.match_code(code, s)
    if user is None:
        throttle.fail(ip)
        return JSONResponse({"detail": "초대 코드가 올바르지 않습니다."}, status_code=401)
    throttle.reset(ip)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(auth.COOKIE, auth.make_token(user, s), max_age=s.session_ttl_hours * 3600, httponly=True,
                    samesite="lax", secure=(s.app_env == "production"), path="/")
    return resp


@app.post("/api/logout")
async def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


# ── 화면·분석 ──
@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    items = load_checklist()["items"]
    stats = {"checklist": len(items), "sections": sum(1 for i in items if i["check"] == "key"), "uses": len(use_table())}
    return templates.TemplateResponse(request, "landing.html", {"disclaimer": DISCLAIMER, "page": "home", "stats": stats})


@app.get("/guide", response_class=HTMLResponse)
async def guide(request: Request):
    return templates.TemplateResponse(request, "guide.html", {"disclaimer": DISCLAIMER, "page": "guide"})


@app.get("/app", response_class=HTMLResponse)
async def index(request: Request):
    s = get_settings()
    return templates.TemplateResponse(request, "app.html", {
        "disclaimer": DISCLAIMER, "page": "app", "llm_available": not s.llm_mock_mode, "llm_provider": s.llm_provider,
        "llm_model": s.model, "needs_code": bool(s.app_access_code), "auth_enabled": s.auth_enabled,
        "boot": {"roles": PARTICIPATION_ROLES,
                 "uses": [{"key": k, "label": v["label"], "metric": v["metric"]} for k, v in use_table().items() if k != "apartment"]},
    })


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest, request: Request):
    job_id, state = await run_analysis(req, store, limiter, request.state.user)
    return summarize(state, job_id)


MAX_COUNTS_BYTES = 2_000_000


@app.post("/api/counts/parse")
async def api_counts_parse(request: Request):
    """교통량 조사 CSV 본문({"text": "..."})에서 AM·PM 첨두시, PHF, 접근로별 이동류 교통량을 뽑는다(저장하지 않음)."""
    if int(request.headers.get("content-length") or 0) > MAX_COUNTS_BYTES:
        return JSONResponse({"detail": "파일이 너무 큽니다(최대 2MB)."}, status_code=413)
    try:
        text = (json.loads(await request.body()) or {}).get("text")
    except (json.JSONDecodeError, AttributeError):
        return JSONResponse({"detail": "요청 형식이 올바르지 않습니다."}, status_code=400)
    if not isinstance(text, str) or not text.strip():
        return JSONResponse({"detail": "CSV 내용이 비어 있습니다."}, status_code=400)
    if len(text.encode()) > MAX_COUNTS_BYTES:
        return JSONResponse({"detail": "파일이 너무 큽니다(최대 2MB)."}, status_code=413)
    try:
        return parse_counts(text)
    except CountsError as e:
        return JSONResponse({"detail": str(e)}, status_code=422)


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
        job_id, state = await run_analysis(req, store, limiter, request.state.user)
    except ServiceError as e:
        return err(e.status, [e.message])
    return templates.TemplateResponse(request, "partials/result.html",
                                      {"s": summarize(state, job_id), "disclaimer": DISCLAIMER})


@app.get("/api/report/{job_id}.docx")
async def report_docx(job_id: str, request: Request):
    state = store.get(job_id, request.state.user)  # 소유자만 조회 가능
    if state is None:
        raise ServiceError(404, "결과를 찾을 수 없습니다(만료되었거나 다른 계정의 결과일 수 있습니다). 다시 분석하세요.")
    buf = io.BytesIO()
    build_docx(state).save(buf)
    name = quote(f"교통영향평가서_초안_{state.project.name}.docx")
    return Response(
        buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"},
    )
