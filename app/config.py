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
    # 웹 서비스 비용 안전장치: 실제 LLM을 쓰는 분석에만 적용한다.
    app_access_code: str = ""  # 비어 있지 않으면 실제 LLM 사용 시 이 코드를 요구
    max_live_runs_per_hour: int = 10  # 실제 LLM 분석 시간당 최대 횟수(서버 전체)
    max_intersections: int = 12  # 요청당 교차로 수 상한
    max_approaches: int = 8  # 교차로당 접근로 수 상한

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
