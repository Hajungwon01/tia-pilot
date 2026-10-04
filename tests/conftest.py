"""테스트는 항상 mock LLM으로 돈다. 프로젝트 .env에 실제 키가 있어도 외부 호출·과금이 생기지 않게 막는다."""
import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    # 환경변수는 .env보다 우선하므로 빈 값으로 덮어쓰면 mock 모드가 된다.
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
