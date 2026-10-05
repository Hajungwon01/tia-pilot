import copy
import io

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.service import JobStore, RateLimiter

PAYLOAD = {
    "project": {"name": "테스트 단지", "address": "서울 OO동", "land_use": "apartment", "households": 1500,
                "gross_floor_area_m2": 180000, "floors": 25},
    "background_growth_rate": 0.02,
    "intersections": [{"name": "A교차로", "cycle": 120, "peak": "pm", "approaches": [
        {"name": "N", "volume": 400, "saturation_flow": 1800, "green_time": 40, "project_share": 0.4},
        {"name": "E", "volume": 500, "saturation_flow": 1800, "green_time": 40, "project_share": 0.1}]}],
}


def payload(**over):
    p = copy.deepcopy(PAYLOAD)
    p.update(over)
    return p


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "store", JobStore())
    monkeypatch.setattr(main, "limiter", RateLimiter())
    return TestClient(main.app)


def set_env(monkeypatch, **kv):
    for k, v in kv.items():
        monkeypatch.setenv(k, str(v))
    get_settings.cache_clear()


# ── 기본 동작 ──
def test_health_reports_llm_unavailable_without_key(client):
    j = client.get("/health").json()
    assert j["status"] == "ok" and j["llm"]["available"] is False


def test_index_page_has_form_and_disclaimer(client):
    r = client.get("/")
    assert r.status_code == 200
    for needle in ('id="households"', 'id="gfa"', 'id="addIx"', "교통기술사", "분석 실행"):
        assert needle in r.text, needle
    assert "disabled" in r.text  # 키가 없으면 실제 LLM 체크박스는 비활성


def test_analyze_returns_summary_with_three_stages(client):
    r = client.post("/api/analyze", json=PAYLOAD)
    assert r.status_code == 200
    j = r.json()
    assert j["llm"]["used"] is False and j["eligibility"]["eligible"] is True
    assert set(j["stages"]["A교차로"]) == {"1", "3"}
    assert j["reflection"]["passed"] > 0 and j["needs_input"] == []
    assert j["download_url"].endswith(".docx")


def test_docx_download_roundtrip(client):
    j = client.post("/api/analyze", json=PAYLOAD).json()
    r = client.get(j["download_url"])
    assert r.status_code == 200
    assert "wordprocessingml" in r.headers["content-type"]
    assert "filename*=UTF-8''" in r.headers["content-disposition"]
    d = Document(io.BytesIO(r.content))
    assert any("교통영향평가서" in p.text for p in d.paragraphs)


def test_unknown_job_is_404_json(client):
    r = client.get("/api/report/deadbeef.docx")
    assert r.status_code == 404 and "찾을 수 없습니다" in r.json()["detail"]


def test_ui_fragment_renders_and_escapes_html(client):
    p = payload()
    p["project"]["name"] = "<script>alert(1)</script>"
    r = client.post("/ui/analyze", json=p)
    assert r.status_code == 200
    assert "분석 결과" in r.text and "내려받기" in r.text and "3단계" in r.text
    assert "<script>alert(1)</script>" not in r.text  # 사용자 입력은 이스케이프


def test_missing_inputs_listed_not_assumed(client):
    p = payload(background_growth_rate=None, intersections=[])
    j = client.post("/api/analyze", json=p).json()
    keys = {n["key"] for n in j["needs_input"]}
    assert "los.intersections" in keys and j["stages"] == {}


# ── 입력 검증 ──
def test_pydantic_errors_are_readable_html(client):
    p = payload()
    p["project"]["households"] = 0
    r = client.post("/ui/analyze", json=p)
    assert r.status_code == 422 and "입력을 확인해 주세요" in r.text and "households" in r.text


def test_invalid_json_body_is_400(client):
    r = client.post("/ui/analyze", content=b"not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400


@pytest.mark.parametrize("mutate,msg", [
    (lambda p: p["intersections"][0]["approaches"][0].update(green_time=130), "신호주기"),
    (lambda p: p["intersections"][0]["approaches"][0].update(project_share=0.95), "100%"),  # 0.95+0.1 > 1
    (lambda p: p["intersections"][0]["approaches"][1].update(name="N"), "중복"),
    (lambda p: p["intersections"][0].update(approaches=[]), "접근로는"),
    (lambda p: p["intersections"].append(copy.deepcopy(p["intersections"][0])), "교차로 이름이 중복"),
])
def test_semantic_validation_errors_are_422_with_reason(client, mutate, msg):
    p = payload()
    mutate(p)
    r = client.post("/api/analyze", json=p)
    assert r.status_code == 422 and msg in r.json()["detail"]


def test_infeasible_signal_plan_is_422_not_500(client):
    p = payload()
    p["intersections"][0]["approaches"] = [
        {"name": n, "volume": 100, "saturation_flow": 1800, "green_time": 5, "project_share": 0} for n in "NES"]
    r = client.post("/api/analyze", json=p)  # 총 녹색 15초 < 3×최소 7초
    assert r.status_code == 422 and "계산할 수 없습니다" in r.json()["detail"]


def test_request_size_limits_from_settings(client, monkeypatch):
    set_env(monkeypatch, MAX_INTERSECTIONS=1)
    p = payload()
    p["intersections"].append({**copy.deepcopy(p["intersections"][0]), "name": "B교차로"})
    r = client.post("/api/analyze", json=p)
    assert r.status_code == 422 and "최대 1개" in r.json()["detail"]
    get_settings.cache_clear()


# ── 비용 안전장치 ──
class FakeLLM:
    mock_mode = False
    provider = "openai"

    def __init__(self, *a, **k):
        pass

    async def complete(self, system, user):
        return "A교차로 평균 지체는 계산 결과와 같습니다. 개선방안은 현장 조사 후 검토가 필요합니다."


@pytest.fixture
def live(monkeypatch):
    """서버에 키가 있는 상태를 흉내 내되 실제 호출은 FakeLLM으로 대체."""
    set_env(monkeypatch, OPENAI_API_KEY="sk-test-not-real", LLM_PROVIDER="openai")
    monkeypatch.setattr("app.service.LLMClient", lambda force_mock=False: FakeLLM() if not force_mock else _mock())
    yield
    get_settings.cache_clear()


def _mock():
    from app.core.llm_client import LLMClient
    return LLMClient(force_mock=True)


def test_llm_not_used_by_default_even_when_server_has_key(client, live):
    j = client.post("/api/analyze", json=PAYLOAD).json()  # use_llm 기본 false
    assert j["llm"]["used"] is False


def test_use_llm_without_server_key_is_400(client):
    r = client.post("/api/analyze", json=payload(use_llm=True))
    assert r.status_code == 400 and "키가 설정되어 있지 않아" in r.json()["detail"]


def test_use_llm_with_key_works(client, live):
    r = client.post("/api/analyze", json=payload(use_llm=True))
    assert r.status_code == 200 and r.json()["llm"]["used"] is True


def test_access_code_enforced_for_live_llm_only(client, live, monkeypatch):
    set_env(monkeypatch, APP_ACCESS_CODE="s3cret")
    assert client.post("/api/analyze", json=payload(use_llm=True)).status_code == 403
    assert client.post("/api/analyze", json=payload(use_llm=True, access_code="wrong")).status_code == 403
    assert client.post("/api/analyze", json=payload(use_llm=True, access_code="s3cret")).status_code == 200
    assert client.post("/api/analyze", json=PAYLOAD).status_code == 200  # mock 분석은 코드 불필요


def test_live_llm_rate_limited_per_hour(client, live, monkeypatch):
    set_env(monkeypatch, MAX_LIVE_RUNS_PER_HOUR=2)
    codes = [client.post("/api/analyze", json=payload(use_llm=True)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert client.post("/api/analyze", json=PAYLOAD).status_code == 200  # mock은 제한 없음


def test_llm_failure_is_502_without_leaking_details(client, live, monkeypatch):
    class Boom(FakeLLM):
        async def complete(self, system, user):
            raise RuntimeError("secret internal detail sk-xxxx")

    monkeypatch.setattr("app.service.LLMClient", lambda force_mock=False: Boom())
    r = client.post("/api/analyze", json=payload(use_llm=True))
    assert r.status_code == 502 and "sk-xxxx" not in r.text and "secret" not in r.text


# ── 저장소·제한기 단위 ──
def test_rate_limiter_window():
    rl = RateLimiter()
    assert rl.allow(2, now=0) and rl.allow(2, now=10) and not rl.allow(2, now=20)
    assert rl.allow(2, now=3601)  # 첫 기록이 1시간 지나 풀림


def test_job_store_ttl_and_capacity(monkeypatch):
    import time as _t
    from app.schemas import ProjectInput
    from app.state import ReportState
    mk = lambda: ReportState(project=ProjectInput(name="x", address="y", households=1))  # noqa: E731
    s = JobStore(max_items=2, ttl_sec=100)
    a, b, c = s.put(mk()), s.put(mk()), s.put(mk())
    assert s.get(a) is None and s.get(b) and s.get(c)  # 용량 초과 시 오래된 것부터 제거
    now = _t.time()
    monkeypatch.setattr("app.service.time.time", lambda: now + 101)
    assert s.get(b) is None  # TTL 만료
