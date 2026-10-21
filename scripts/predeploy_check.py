"""배포 전 점검: 환경변수 규칙과 운영과 같은 설정에서의 동작(로그인·분석·Word 다운로드·권한)을 확인한다.

사용법
    python scripts/predeploy_check.py --gen                 # SECRET_KEY·초대 코드 예시 생성(터미널에만 출력, 파일에 쓰지 않음)
    python scripts/predeploy_check.py --env-file prod.env   # 운영 환경변수 파일 점검(이 파일은 git에 올리지 말 것)
    python scripts/predeploy_check.py                       # 현재 셸의 환경변수 점검
    python scripts/predeploy_check.py --url https://xxx.up.railway.app --code 초대코드   # 배포된 서버 점검

종료 코드: FAIL이 하나라도 있으면 1. 점검은 LLM을 호출하지 않는다(분석 요청은 항상 use_llm=false).
키·코드 값은 출력하지 않는다(길이·개수만 보여 준다).
"""
import argparse
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK, WARN, FAIL = "OK", "WARN", "FAIL"
DATA_FILES = ["reflection_checklist.json", "eligibility_thresholds.json", "parking_rules.json", "unit_rates.json", "unit_rate_evidence.csv"]
SAMPLE = {"project": {"name": "배포점검", "address": "서울", "households": 1000, "gross_floor_area_m2": 120000,
                      "unit_types": [{"exclusive_area_m2": 84, "households": 1000}], "planned_parking_spaces": 1300}}


def generate() -> str:
    codes = ", ".join(secrets.token_urlsafe(9) for _ in range(3))
    return (f"SECRET_KEY={secrets.token_urlsafe(48)}\n"
            f"BETA_CODES={codes}\n"
            f"APP_ACCESS_CODE={secrets.token_urlsafe(9)}\n"
            "# 위 값은 지금 터미널에만 출력됐습니다. Railway Variables에 붙여 넣고 파일·채팅·git에는 남기지 마세요.")


# ── 1) 환경변수 점검 (값은 출력하지 않는다) ──
def check_settings(s) -> list[tuple[str, str]]:
    from app.auth import ConfigError, MIN_SECRET_LEN, validate_config

    r: list[tuple[str, str]] = []
    add = lambda level, msg: r.append((level, msg))  # noqa: E731
    add(OK if s.app_env == "production" else WARN, f"APP_ENV={s.app_env!r}" + ("" if s.app_env == "production" else " — 운영 배포는 production이어야 인증이 강제됩니다"))
    codes = s.beta_code_list
    if not codes:
        add(FAIL, "BETA_CODES가 비어 있음 — 초대 코드가 없으면 누구나 분석을 실행할 수 있습니다")
    else:
        add(OK, f"초대 코드 {len(codes)}개")
        if len(set(codes)) != len(codes):
            add(FAIL, "BETA_CODES에 중복된 코드가 있음")
        short = [c for c in codes if len(c) < 8]
        if short:
            add(WARN, f"8자 미만의 짧은 초대 코드 {len(short)}개 — 추측당하기 쉽습니다(로그인 시도 제한은 있음)")
    if len(s.secret_key) >= MIN_SECRET_LEN:
        add(OK, f"SECRET_KEY {len(s.secret_key)}자")
    else:
        add(FAIL, f"SECRET_KEY가 {len(s.secret_key)}자 — {MIN_SECRET_LEN}자 이상 무작위 문자열이어야 함(세션 쿠키 서명)")
    if s.secret_key and s.secret_key in codes:
        add(FAIL, "SECRET_KEY가 초대 코드와 같음")
    try:
        validate_config(s)
        add(OK, "앱 시작 검증(validate_config) 통과")
    except ConfigError as e:
        add(FAIL, f"앱이 시작되지 않음: {e}")
    if s.llm_mock_mode:
        add(OK, "LLM 키 없음 → mock 모드(과금 없음, 문단은 자리표시)")
    else:
        add(WARN, f"LLM 키 설정됨({s.llm_provider}, 모델 {s.model}) — 실제 호출은 APP_ACCESS_CODE와 시간당 {s.max_live_runs_per_hour}회로 제한. 크레딧 잔액을 확인하세요")
        add(OK if s.app_access_code else FAIL, "APP_ACCESS_CODE " + ("설정됨" if s.app_access_code else "없음 — LLM 키가 있으면 필수(과금 방지)"))
    add(OK if s.trust_proxy else WARN, f"TRUST_PROXY={s.trust_proxy}" + ("" if s.trust_proxy else " — Railway 같은 프록시 뒤에서는 true여야 로그인 시도 제한이 실제 IP로 동작"))
    db = Path(s.db_path)
    if not (db.is_absolute() or s.db_path.startswith("/")):  # 리눅스 컨테이너의 /data/... 경로는 Windows에서 점검해도 절대 경로로 본다
        add(WARN, f"DB_PATH={s.db_path!r}는 상대 경로 — 컨테이너 디스크는 재배포 때 사라집니다. 볼륨 경로(예: /data/app.db)를 쓰세요")
    else:
        if not db.parent.is_dir():  # 폴더를 만들지 않는다(로컬 PC에 엉뚱한 폴더가 생기지 않도록). 서버에서는 볼륨이 마운트돼 있어야 한다
            add(WARN, f"DB_PATH의 폴더 {db.parent}가 이 환경에 없음 — Railway 볼륨을 이 경로에 마운트했는지 배포 후 확인하세요(앱은 시작 시 파일을 만듭니다)")
        else:
            try:
                probe = db.parent / ".write_probe"
                probe.write_text("x")
                probe.unlink()
                add(OK, f"DB_PATH 쓰기 가능({db.parent})")
            except OSError as e:
                add(FAIL, f"DB_PATH 위치에 쓸 수 없음: {e}")
    for name in DATA_FILES:
        p = ROOT / "data" / name
        add(OK if p.is_file() else FAIL, f"data/{name}" + ("" if p.is_file() else " 없음 — 배포 이미지에 포함되지 않았습니다(.gitignore·커밋 확인)"))
    return r


# ── 2) 동작 점검: 주어진 HTTP 클라이언트(TestClient 또는 requests 세션 어댑터)로 ──
def run_smoke(client, code: str, other_code: str | None = None, https: bool = True) -> list[tuple[str, str]]:
    r: list[tuple[str, str]] = []
    add = lambda level, msg: r.append((level, msg))  # noqa: E731

    def chk(cond, ok_msg, fail_msg, level=FAIL):
        add(OK if cond else level, ok_msg if cond else fail_msg)

    h = client.get("/health")
    chk(h.status_code == 200 and h.json().get("status") == "ok", "/health 200", f"/health 비정상({h.status_code})")
    if h.status_code == 200:
        chk(h.json().get("auth") is True, "인증 켜짐(/health auth=true)", "인증이 꺼져 있음 — 누구나 접근 가능")
    land = client.get("/")
    chk(land.status_code == 200 and "교통영향평가" in land.text, "첫 화면 200", f"첫 화면 비정상({land.status_code})")
    hd = {k.lower(): v for k, v in land.headers.items()}
    chk(hd.get("x-frame-options") == "DENY" and "default-src 'self'" in hd.get("content-security-policy", ""), "보안 헤더(X-Frame-Options·CSP)", "보안 헤더 누락")
    def docs_hidden(resp):  # 로그인 전에는 로그인 화면으로 이동(303)하거나 404 — 어느 쪽이든 Swagger가 보이면 안 된다
        return resp.status_code in (302, 303, 307, 404) and "swagger" not in resp.text.lower() and "openapi" not in resp.text.lower()
    chk(all(docs_hidden(client.get(p, follow_redirects=False)) for p in ("/docs", "/redoc", "/openapi.json")), "로그인 전 API 문서(/docs·/openapi.json) 비노출", "API 문서가 로그인 없이 노출됨")
    guard = client.get("/app", follow_redirects=False)
    chk(guard.status_code in (302, 303, 307) and "/login" in guard.headers.get("location", ""), "로그인 없이 /app → /login 이동", f"로그인 없이 /app 접근됨({guard.status_code})")
    chk(client.post("/api/analyze", json=SAMPLE).status_code == 401, "로그인 없이 /api/analyze 401", "로그인 없이 분석 API가 열려 있음")
    chk(client.post("/api/counts/parse", json={"text": "x"}).status_code == 401, "로그인 없이 CSV 파싱 401", "로그인 없이 CSV 파싱 API가 열려 있음")
    bad = client.post("/api/login", json={"code": "틀린-코드-" + secrets.token_hex(4)})
    chk(bad.status_code == 401, "잘못된 코드 401", f"잘못된 코드가 거부되지 않음({bad.status_code})")
    ok = client.post("/api/login", json={"code": code})
    chk(ok.status_code == 200, "로그인 성공", f"로그인 실패({ok.status_code}) — 코드 확인")
    if ok.status_code != 200:
        return r
    sc = ok.headers.get("set-cookie", "").lower()
    chk("httponly" in sc and "samesite=lax" in sc, "세션 쿠키 HttpOnly·SameSite=Lax", "세션 쿠키 속성 부족")
    chk("secure" in sc or not https, "세션 쿠키 Secure", "세션 쿠키에 Secure 없음(운영은 production이어야 함)")
    ui = client.post("/ui/analyze", json=SAMPLE)
    chk(ui.status_code == 200 and "평가 대상" in ui.text, "분석 실행(/ui/analyze, mock)", f"분석 실패({ui.status_code}): {ui.text[:120]}")
    api = client.post("/api/analyze", json=SAMPLE)
    job = api.json().get("job_id") if api.status_code == 200 else None
    chk(job is not None, "분석 API job_id 발급", f"분석 API 실패({api.status_code})")
    if job:
        doc = client.get(f"/api/report/{job}.docx")
        ctype = doc.headers.get("content-type", "")
        chk(doc.status_code == 200 and "wordprocessingml" in ctype and len(doc.content) > 10_000 and doc.content[:2] == b"PK",
            f"Word 다운로드({len(doc.content):,}바이트)", f"Word 다운로드 실패({doc.status_code}, {len(doc.content)}바이트)")
        if other_code and hasattr(client, "app"):
            other = type(client)(client.app, base_url=str(client.base_url))
            other.post("/api/login", json={"code": other_code})
            chk(other.get(f"/api/report/{job}.docx").status_code == 404, "다른 사용자는 내 보고서를 못 받음(404)", "다른 사용자가 내 보고서를 받을 수 있음 — 권한 분리 실패")
        else:
            add(WARN, "사용자 간 권한 분리 점검은 건너뜀(로컬 점검에서 초대 코드가 2개 이상일 때만 수행)")
    chk(all(client.get(p, follow_redirects=False).status_code == 404 for p in ("/docs", "/openapi.json")), "로그인 후에도 API 문서 꺼짐(404)", "로그인 후 API 문서가 열려 있음")
    out = client.post("/api/logout")
    chk(out.status_code == 200, "로그아웃", "로그아웃 실패", WARN)
    return r


def _report(results: list[tuple[str, str]]) -> int:
    for level, msg in results:
        print(f"[{level:4}] {msg}")
    fails = sum(1 for lv, _ in results if lv == FAIL)
    warns = sum(1 for lv, _ in results if lv == WARN)
    print(f"\n결과: FAIL {fails} · WARN {warns} · OK {sum(1 for lv, _ in results if lv == OK)}")
    return 1 if fails else 0


class _RemoteClient:
    """배포된 서버를 점검하기 위한 requests 어댑터(쿠키 유지)."""

    def __init__(self, base: str):
        try:
            import requests
        except ImportError:  # 배포 서버 점검에만 필요(앱 실행에는 불필요)
            raise SystemExit("--url 점검에는 requests가 필요합니다: pip install requests")
        self.base_url, self.s = base.rstrip("/"), requests.Session()

    def _call(self, method, path, **kw):
        kw.setdefault("timeout", 60)
        kw["allow_redirects"] = kw.pop("follow_redirects", True)
        return self.s.request(method, self.base_url + path, **kw)

    def get(self, path, **kw):
        return self._call("GET", path, **kw)

    def post(self, path, **kw):
        return self._call("POST", path, **kw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gen", action="store_true", help="SECRET_KEY·초대 코드 예시를 생성해 출력")
    ap.add_argument("--env-file", help="점검할 환경변수 파일(.env 형식)")
    ap.add_argument("--no-smoke", action="store_true", help="환경변수 점검만 하고 동작 점검은 건너뜀")
    ap.add_argument("--url", help="배포된 서버 주소(동작 점검만 수행)")
    ap.add_argument("--code", help="--url 점검에 쓸 초대 코드")
    a = ap.parse_args(argv)
    if a.gen:
        print(generate())
        return 0
    if a.url:
        if not a.code:
            print("--url에는 --code(초대 코드)가 필요합니다.")
            return 2
        return _report(run_smoke(_RemoteClient(a.url), a.code, https=a.url.startswith("https")))

    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "BETA_CODES", "SECRET_KEY", "APP_ACCESS_CODE", "APP_ENV", "DB_PATH", "TRUST_PROXY"):
        if a.env_file:
            os.environ.pop(k, None)  # 파일의 값만 보도록 현재 셸 값은 지운다
    from app.config import Settings

    s = Settings(_env_file=a.env_file)  # None이면 파일 없이 현재 셸 환경변수만(프로젝트의 개발용 .env는 읽지 않는다)
    results = check_settings(s)
    startup_failed = any(lv == FAIL and "앱이 시작되지 않음" in msg for lv, msg in results)
    if not a.no_smoke and not startup_failed:
        # 운영과 같은 설정으로 앱을 임시 DB·mock LLM에서 실행(실제 키는 넘기지 않는다)
        env = {"APP_ENV": s.app_env, "BETA_CODES": s.beta_codes, "SECRET_KEY": s.secret_key, "TRUST_PROXY": str(s.trust_proxy).lower(),
               "APP_ACCESS_CODE": s.app_access_code, "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "",
               "DB_PATH": str(Path(tempfile.mkdtemp(prefix="tia-predeploy-")) / "check.db")}
        os.environ.update(env)
        from app.auth import ConfigError, validate_config
        from app.config import get_settings

        get_settings.cache_clear()
        try:
            validate_config(get_settings())
        except ConfigError:
            results.append((WARN, "설정이 유효하지 않아 동작 점검을 건너뜀"))
        else:
            from fastapi.testclient import TestClient

            from app.main import app

            codes = get_settings().beta_code_list
            client = TestClient(app, base_url="https://testserver")
            results += run_smoke(client, codes[0], codes[1] if len(codes) > 1 else None, https=True)
    return _report(results)


if __name__ == "__main__":
    sys.exit(main())
