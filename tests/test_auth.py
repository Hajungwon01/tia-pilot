import copy

import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.config import Settings, get_settings
from app.storage import Database, LlmRunLog, SqliteJobStore
from test_api import PAYLOAD  # 같은 폴더(tests/)의 공용 요청 예시

SECRET = "s" * 40
ALPHA, BETA = "alpha-code", "beta-code"


def set_env(monkeypatch, **kv):
    for k, v in kv.items():
        monkeypatch.setenv(k, str(v))
    get_settings.cache_clear()


@pytest.fixture
def app_env(monkeypatch, tmp_path):
    db = Database(tmp_path / "a.db")
    monkeypatch.setattr(main, "store", SqliteJobStore(db))
    monkeypatch.setattr(main, "limiter", LlmRunLog(db))
    monkeypatch.setattr(main, "throttle", auth.LoginThrottle())
    set_env(monkeypatch, BETA_CODES=f"{ALPHA},{BETA}", SECRET_KEY=SECRET)


def new_client():
    return TestClient(main.app, follow_redirects=False)


def login(c, code=ALPHA):
    return c.post("/api/login", json={"code": code})


# ── 접근 통제 ──
def test_everything_but_login_health_and_intro_pages_requires_auth(app_env):
    c = new_client()
    r = c.get("/app")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    for open_path in ("/", "/guide", "/static/site.css", "/static/site.js"):
        assert c.get(open_path).status_code == 200, open_path  # 소개·안내·정적 파일은 로그인 없이
    assert c.get("/static/wizard.js").status_code == 200  # 코드는 비밀이 아니며 데이터는 api에서만 나온다
    assert c.get("/login").status_code == 200
    assert c.get("/health").json()["auth"] is True
    assert c.post("/api/analyze", json=PAYLOAD).status_code == 401
    assert c.post("/ui/analyze", json=PAYLOAD).status_code == 401
    assert c.get("/api/report/abc.docx").status_code == 401


def test_login_flow_sets_hardened_cookie(app_env):
    c = new_client()
    assert login(c, "wrong").status_code == 401
    r = login(c)
    assert r.status_code == 200
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=lax" in sc and "tia_session=" in sc
    assert c.get("/app").status_code == 200
    assert c.post("/api/analyze", json=PAYLOAD).status_code == 200
    assert c.get("/login").status_code == 303  # 이미 로그인했으면 폼으로


def test_logout_revokes_browser_session(app_env):
    c = new_client()
    login(c)
    assert c.post("/api/logout").status_code == 200
    assert c.get("/app").status_code == 303


def test_login_page_is_not_shown_when_auth_disabled(monkeypatch):
    set_env(monkeypatch, BETA_CODES="")
    r = new_client().get("/login")
    assert r.status_code == 303 and r.headers["location"] == "/app"


# ── 토큰 변조·만료 ──
def test_tampered_forged_and_expired_tokens_rejected(app_env):
    s = get_settings()
    good = auth.make_token("u_x", s)
    assert auth.read_token(good, s) == "u_x"
    body, sig = good.split(".")
    assert auth.read_token(f"{body}.{'0' * len(sig)}", s) is None  # 서명 변조
    assert auth.read_token(auth.make_token("u_x", Settings(secret_key="o" * 40)), s) is None  # 다른 키로 서명
    forged_body = auth._b64(b'{"u":"u_admin","exp":9999999999}')
    assert auth.read_token(f"{forged_body}.{sig}", s) is None  # 본문만 바꾼 위조
    assert auth.read_token(auth.make_token("u_x", s, now=0), s) is None  # 만료
    for junk in (None, "", "no-dot", "a.b", "....", "ÿ.ÿ"):
        assert auth.read_token(junk, s) is None


def test_cookie_with_bad_signature_is_treated_as_logged_out(app_env):
    c = new_client()
    c.cookies.set(auth.COOKIE, auth.make_token("u_x", get_settings(), now=0))  # 만료 토큰
    assert c.get("/app").status_code == 303
    assert c.post("/api/analyze", json=PAYLOAD).status_code == 401


def test_token_and_user_id_do_not_contain_the_invite_code(app_env):
    s = get_settings()
    uid = auth.match_code(ALPHA, s)
    assert uid and ALPHA not in uid and uid == auth.user_id_for(ALPHA)
    assert ALPHA not in auth.make_token(uid, s) and auth.match_code("nope", s) is None


# ── 사용자별 분리 ──
def test_reports_are_isolated_between_users(app_env):
    alice, bob = new_client(), new_client()
    login(alice, ALPHA)
    login(bob, BETA)
    job = alice.post("/api/analyze", json=PAYLOAD).json()
    assert alice.get(job["download_url"]).status_code == 200
    r = bob.get(job["download_url"])  # job_id를 알아도 다른 계정은 못 본다
    assert r.status_code == 404


# ── 무차별 대입 ──
def test_login_brute_force_is_throttled_even_for_correct_code(app_env, monkeypatch):
    set_env(monkeypatch, LOGIN_MAX_FAILURES=3)
    c = new_client()
    assert [login(c, f"bad{i}").status_code for i in range(3)] == [401, 401, 401]
    assert login(c, ALPHA).status_code == 429  # 차단 중에는 올바른 코드도 거부


def test_throttle_ignores_spoofed_forwarded_for_unless_proxy_trusted(app_env, monkeypatch):
    set_env(monkeypatch, LOGIN_MAX_FAILURES=2)
    c = new_client()
    for i in range(2):
        c.post("/api/login", json={"code": "bad"}, headers={"X-Forwarded-For": f"9.9.9.{i}"})
    r = c.post("/api/login", json={"code": ALPHA}, headers={"X-Forwarded-For": "7.7.7.7"})
    assert r.status_code == 429  # 헤더를 바꿔도 제한을 우회하지 못한다(프록시 신뢰 꺼짐)

    set_env(monkeypatch, TRUST_PROXY="true")
    monkeypatch.setattr(main, "throttle", auth.LoginThrottle())
    for _ in range(2):
        c.post("/api/login", json={"code": "bad"}, headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1"})
    assert c.post("/api/login", json={"code": ALPHA}, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 429
    assert c.post("/api/login", json={"code": ALPHA}, headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200


def test_login_bad_body_is_400(app_env):
    c = new_client()
    assert c.post("/api/login", content=b"nope", headers={"Content-Type": "application/json"}).status_code == 400


# ── 운영 설정 검증(fail closed) ──
def test_validate_config_rules():
    ok = Settings(app_env="production", beta_codes="a", secret_key="k" * 40)
    auth.validate_config(ok)
    with pytest.raises(auth.ConfigError, match="BETA_CODES"):
        auth.validate_config(Settings(app_env="production", secret_key="k" * 40))  # 인증 없이 운영 금지
    with pytest.raises(auth.ConfigError, match="SECRET_KEY"):
        auth.validate_config(Settings(beta_codes="a", secret_key="short"))
    with pytest.raises(auth.ConfigError, match="APP_ACCESS_CODE"):  # LLM 키가 있는데 접근 코드가 없으면 과금 위험
        auth.validate_config(Settings(app_env="production", beta_codes="a", secret_key="k" * 40, openai_api_key="sk-x",
                                      llm_provider="openai"))
    auth.validate_config(Settings(app_env="production", beta_codes="a", secret_key="k" * 40, openai_api_key="sk-x",
                                  llm_provider="openai", app_access_code="code"))
    auth.validate_config(Settings())  # 개발 기본값은 허용


def test_app_refuses_to_start_in_production_without_auth(monkeypatch):
    set_env(monkeypatch, APP_ENV="production", BETA_CODES="")
    with pytest.raises(auth.ConfigError):
        with TestClient(main.app):
            pass


def test_production_cookie_is_secure(monkeypatch, tmp_path):
    db = Database(tmp_path / "p.db")
    monkeypatch.setattr(main, "store", SqliteJobStore(db))
    set_env(monkeypatch, APP_ENV="production", BETA_CODES=ALPHA, SECRET_KEY=SECRET)
    r = login(new_client())
    assert r.status_code == 200 and "secure" in r.headers["set-cookie"].lower()


# ── 응답 헤더·문서 노출 ──
def test_security_headers_and_no_public_api_docs(app_env):
    c = new_client()
    login(c)
    r = c.get("/app")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert "x-frame-options" in c.get("/login").headers
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(p).status_code == 404
