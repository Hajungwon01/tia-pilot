"""배포 설정 파일과 배포 전 점검 스크립트(scripts/predeploy_check.py) 검증."""
import importlib.util
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.config import Settings, get_settings
from app.storage import Database, LlmRunLog, SqliteJobStore

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("predeploy_check", ROOT / "scripts" / "predeploy_check.py")
PD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PD)

GOOD = dict(app_env="production", beta_codes="alpha-code-1,bravo-code-2", secret_key="k" * 40, trust_proxy=True, db_path="/data/app.db")


def settings(**kw):
    return Settings(_env_file=None, **{**GOOD, **kw})


def levels(results):
    return {lv: [m for l, m in results if l == lv] for lv in (PD.OK, PD.WARN, PD.FAIL)}


# ── 설정 파일 ──
def test_railway_config_uses_documented_keys_and_health_endpoint():
    cfg = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    d = cfg["deploy"]
    assert cfg["$schema"] == "https://railway.com/railway.schema.json"
    assert set(d) <= {"startCommand", "healthcheckPath", "healthcheckTimeout", "restartPolicyType", "restartPolicyMaxRetries"}
    assert d["healthcheckPath"] == "/health" and d["restartPolicyType"] in {"ON_FAILURE", "ALWAYS", "NEVER"}
    assert "app.main:app" in d["startCommand"] and "0.0.0.0" in d["startCommand"] and "${PORT" in d["startCommand"]
    assert not (ROOT / "Dockerfile").exists()  # Dockerfile이 있으면 Railway가 그걸 우선한다(문서)


def test_python_version_file_and_requirements_cover_runtime():
    assert (ROOT / ".python-version").read_text().strip() == "3.12"
    req = (ROOT / "requirements.txt").read_text().lower()
    for pkg in ("fastapi", "uvicorn", "pydantic-settings", "jinja2", "python-docx"):
        assert pkg in req, pkg


def test_deploy_doc_lists_every_required_env_var_and_example_file_mentions_it():
    doc = (ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in ("APP_ENV", "BETA_CODES", "SECRET_KEY", "DB_PATH", "TRUST_PROXY", "APP_ACCESS_CODE", "OPENAI_API_KEY", "MAX_LIVE_RUNS_PER_HOUR"):
        assert f"`{name}`" in doc and name in example, name
    assert "predeploy_check.py" in doc and "/health" in doc


def test_env_example_contains_no_secrets():
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if re.match(r"^(OPENAI_API_KEY|ANTHROPIC_API_KEY|SECRET_KEY|BETA_CODES|APP_ACCESS_CODE)=.+", line):
            pytest.fail(f"예시 파일에 값이 들어 있음: {line.split('=')[0]}")


# ── 환경변수 점검 ──
def test_good_production_settings_pass_without_fail():
    r = levels(PD.check_settings(settings()))
    assert r[PD.FAIL] == [] and r[PD.WARN] == []


@pytest.mark.parametrize("kw,needle", [
    (dict(beta_codes=""), "BETA_CODES가 비어"),
    (dict(secret_key="short"), "SECRET_KEY가"),
    (dict(beta_codes="a-code-123,a-code-123"), "중복"),
    (dict(secret_key="alpha-code-1" + "x" * 30, beta_codes="alpha-code-1" + "x" * 30), "초대 코드와 같음"),
    (dict(openai_api_key="sk-test", llm_provider="openai", app_access_code=""), "APP_ACCESS_CODE"),
])
def test_bad_settings_fail_with_reason(kw, needle):
    r = levels(PD.check_settings(settings(**kw)))
    assert any(needle in m for m in r[PD.FAIL]), r


def test_warnings_for_risky_but_startable_settings():
    r = levels(PD.check_settings(settings(trust_proxy=False, db_path="data/app.db", beta_codes="short1,short2", app_env="dev")))
    joined = " ".join(r[PD.WARN])
    assert "TRUST_PROXY" in joined and "상대 경로" in joined and "8자 미만" in joined and "APP_ENV" in joined


def test_llm_key_present_warns_to_check_credit_and_never_prints_values():
    res = PD.check_settings(settings(openai_api_key="sk-secret-value", llm_provider="openai", app_access_code="acc-secret"))
    text = " ".join(m for _, m in res)
    assert "sk-secret-value" not in text and "acc-secret" not in text and "크레딧" in text


def test_db_folder_is_not_created_by_the_check(tmp_path):
    missing = tmp_path / "no_such_dir" / "app.db"
    r = levels(PD.check_settings(settings(db_path=str(missing))))
    assert any("볼륨" in m for m in r[PD.WARN]) and not missing.parent.exists()


def test_generate_produces_strong_values_and_a_notice():
    text = PD.generate()
    secret = re.search(r"SECRET_KEY=(\S+)", text).group(1)
    codes = [c.strip() for c in re.search(r"BETA_CODES=(.+)", text).group(1).split(",")]
    assert len(secret) >= 32 and len(codes) == 3 and len(set(codes)) == 3 and all(len(c) >= 8 for c in codes)
    assert PD.generate() != text  # 매번 다르다


# ── 동작 점검(운영과 같은 설정으로 앱 실행) ──
@pytest.fixture
def prod_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BETA_CODES", "alpha-code-1,bravo-code-2")
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    get_settings.cache_clear()
    db = Database(tmp_path / "t.db")
    monkeypatch.setattr(main, "store", SqliteJobStore(db))
    monkeypatch.setattr(main, "limiter", LlmRunLog(db))
    monkeypatch.setattr(main, "throttle", auth.LoginThrottle())
    yield TestClient(main.app, base_url="https://testserver")
    get_settings.cache_clear()


def test_smoke_passes_on_correctly_configured_app(prod_client):
    r = levels(PD.run_smoke(prod_client, "alpha-code-1", "bravo-code-2"))
    assert r[PD.FAIL] == [], r[PD.FAIL]
    ok = " ".join(r[PD.OK])
    for needle in ("Word 다운로드", "다른 사용자는 내 보고서를 못 받음", "로그인 없이 /api/analyze 401", "세션 쿠키 Secure", "API 문서"):
        assert needle in ok, needle


def test_smoke_reports_wrong_code_without_crashing(prod_client):
    r = levels(PD.run_smoke(prod_client, "wrong-code-xyz"))
    assert any("로그인 실패" in m for m in r[PD.FAIL])


def test_smoke_detects_an_app_running_without_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("BETA_CODES", "")
    get_settings.cache_clear()
    db = Database(tmp_path / "t.db")
    monkeypatch.setattr(main, "store", SqliteJobStore(db))
    monkeypatch.setattr(main, "limiter", LlmRunLog(db))
    monkeypatch.setattr(main, "throttle", auth.LoginThrottle())
    r = levels(PD.run_smoke(TestClient(main.app, base_url="https://testserver"), "x"))
    get_settings.cache_clear()
    assert any("인증이 꺼져" in m for m in r[PD.FAIL]) and any("로그인 없이" in m for m in r[PD.FAIL])


def test_report_exit_code_follows_fail_count(capsys):
    assert PD._report([(PD.OK, "a"), (PD.WARN, "b")]) == 0
    assert PD._report([(PD.OK, "a"), (PD.FAIL, "c")]) == 1
    assert "FAIL 1" in capsys.readouterr().out
