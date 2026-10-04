import asyncio

import pytest

from app.config import get_settings
from app.core.llm_client import MOCK_PREFIX, LLMClient


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    for k in ("LLM_PROVIDER", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(__import__("tempfile").gettempdir())  # 프로젝트의 실제 .env를 읽지 않도록
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_no_key_is_mock_for_both_providers(monkeypatch):
    for provider in ("openai", "anthropic"):
        monkeypatch.setenv("LLM_PROVIDER", provider)
        get_settings.cache_clear()
        c = LLMClient()
        assert c.mock_mode
        assert asyncio.run(c.complete("s", "u")).startswith(MOCK_PREFIX)


def test_only_selected_providers_key_counts(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")  # 다른 제공자 키는 무시
    get_settings.cache_clear()
    assert LLMClient().mock_mode


def test_default_model_per_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    get_settings.cache_clear()
    assert get_settings().model == "gpt-4o-mini"
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    get_settings.cache_clear()
    assert get_settings().model == "claude-sonnet-5-5"
    monkeypatch.setenv("LLM_MODEL", "custom-model")
    get_settings.cache_clear()
    assert get_settings().model == "custom-model"


def test_openai_client_built_with_key_and_calls_sdk(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    get_settings.cache_clear()
    c = LLMClient()
    assert not c.mock_mode and c.provider == "openai"

    calls = {}

    class FakeCompletions:
        def create(self, **kw):
            calls.update(kw)
            msg = type("M", (), {"content": "응답"})()
            return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    c._client = type("Cl", (), {"chat": type("Ch", (), {"completions": FakeCompletions()})()})()
    assert asyncio.run(c.complete("sys", "usr")) == "응답"
    assert calls["messages"][0] == {"role": "system", "content": "sys"}
    assert calls["model"] == "gpt-4o-mini" and "max_completion_tokens" in calls


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "foo")
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        LLMClient()
