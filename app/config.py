from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경 설정(.env/환경변수). ANTHROPIC_API_KEY가 없으면 LLMClient는 mock 모드."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5-5"
    max_reflection_retries: int = 1

    @property
    def llm_mock_mode(self) -> bool:
        return not self.anthropic_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
