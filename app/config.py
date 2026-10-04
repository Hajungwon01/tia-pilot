from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "openai": "gpt-4o-mini"}


class Settings(BaseSettings):
    """환경 설정(.env/환경변수). 선택한 제공자의 키가 없으면 LLMClient는 mock 모드."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "anthropic"  # "anthropic" | "openai"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    llm_model: str = ""  # 비우면 제공자별 기본 모델
    max_reflection_retries: int = 1

    @property
    def api_key(self) -> str:
        return self.openai_api_key if self.llm_provider == "openai" else self.anthropic_api_key

    @property
    def model(self) -> str:
        return self.llm_model or DEFAULT_MODELS.get(self.llm_provider, "")

    @property
    def llm_mock_mode(self) -> bool:
        return not self.api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
