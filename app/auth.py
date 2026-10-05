"""베타 초대 코드 로그인 + 서명된 세션 쿠키.

- 사용자 식별자는 코드의 해시 앞부분이라 쿠키·DB에 코드 자체가 남지 않는다.
- 쿠키는 HMAC-SHA256으로 서명(SECRET_KEY)하고 만료 시각을 포함한다. HttpOnly, SameSite=Lax, 운영에서는 Secure.
- 인증이 켜져 있는데(BETA_CODES) 서명 키가 없거나, 운영(APP_ENV=production)인데 인증이 꺼져 있으면 앱이 시작되지 않는다.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque

from fastapi import Request

from app.config import Settings

COOKIE = "tia_session"
ANON = "anonymous"
PUBLIC_PATHS = {"/health", "/login", "/api/login", "/api/logout"}
MIN_SECRET_LEN = 32


class ConfigError(RuntimeError):
    pass


def validate_config(s: Settings) -> None:
    """운영 환경의 위험한 설정을 시작 단계에서 막는다."""
    if s.auth_enabled and len(s.secret_key) < MIN_SECRET_LEN:
        raise ConfigError(f"BETA_CODES를 쓰려면 SECRET_KEY가 {MIN_SECRET_LEN}자 이상이어야 합니다.")
    if s.app_env == "production":
        if not s.auth_enabled:
            raise ConfigError("APP_ENV=production에서는 BETA_CODES를 반드시 설정해야 합니다(인증 없이 공개 금지).")
        if not s.app_access_code and not s.llm_mock_mode:
            raise ConfigError("운영에서 LLM 키가 설정돼 있으면 APP_ACCESS_CODE도 설정해야 합니다(과금 방지).")


def user_id_for(code: str) -> str:
    return "u_" + hashlib.sha256(code.encode()).hexdigest()[:12]


def match_code(code: str, s: Settings) -> str | None:
    """입력 코드가 등록된 코드와 일치하면 사용자 id를 돌려준다(모든 코드를 상수 시간으로 비교)."""
    found = None
    for c in s.beta_code_list:
        if secrets.compare_digest(code.encode(), c.encode()):
            found = user_id_for(c)
    return found


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user: str, s: Settings, now: float | None = None) -> str:
    now = time.time() if now is None else now
    body = _b64(json.dumps({"u": user, "exp": now + s.session_ttl_hours * 3600}).encode())
    sig = hmac.new(s.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_token(token: str | None, s: Settings, now: float | None = None) -> str | None:
    if not token or "." not in token:
        return None
    body, _, sig = token.partition(".")
    good = hmac.new(s.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(sig.encode(), good.encode()):
        return None
    try:
        data = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    now = time.time() if now is None else now
    if not isinstance(data, dict) or data.get("exp", 0) < now or not data.get("u"):
        return None
    return str(data["u"])


def current_user(request: Request, s: Settings) -> str | None:
    """인증이 꺼져 있으면 익명, 켜져 있으면 유효한 세션의 사용자 id(없으면 None)."""
    if not s.auth_enabled:
        return ANON
    return read_token(request.cookies.get(COOKIE), s)


class LoginThrottle:
    """같은 IP의 로그인 실패를 10분 창으로 제한한다(프로세스 메모리, 재시작하면 초기화)."""

    def __init__(self) -> None:
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, ip: str, now: float) -> deque:
        q = self._fails[ip]
        while q and now - q[0] > 600:
            q.popleft()
        return q

    def blocked(self, ip: str, limit: int, now: float | None = None) -> bool:
        return len(self._prune(ip, time.time() if now is None else now)) >= limit

    def fail(self, ip: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._prune(ip, now).append(now)

    def reset(self, ip: str) -> None:
        self._fails.pop(ip, None)


def client_ip(request: Request, s: Settings) -> str:
    if s.trust_proxy:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
