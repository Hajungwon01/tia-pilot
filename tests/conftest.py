"""테스트는 항상 mock LLM·인증 꺼짐·임시 DB로 돈다.

프로젝트 .env에 실제 키·초대 코드가 있어도 외부 호출·과금·저장소 오염이 생기지 않게 막는다.
"""
import os
import tempfile
from pathlib import Path

# app.main이 임포트 시점에 DB를 여므로, 임포트 전에 임시 경로를 지정한다(.env보다 환경변수가 우선).
os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="tia-test-")) / "test.db")

import pytest  # noqa: E402

from app.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    # 환경변수는 .env보다 우선하므로 빈 값으로 덮어쓰면 해당 기능이 꺼진다.
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "BETA_CODES", "SECRET_KEY", "APP_ACCESS_CODE"):
        monkeypatch.setenv(k, "")
    monkeypatch.setenv("APP_ENV", "dev")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
