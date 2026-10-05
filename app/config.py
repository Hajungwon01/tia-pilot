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

    # 인증·저장소
    app_env: str = "dev"  # "production"이면 BETA_CODES와 SECRET_KEY가 없을 때 앱이 시작되지 않는다(fail closed)
    beta_codes: str = ""  # 쉼표로 구분한 베타 초대 코드. 비어 있으면(dev) 인증 없이 열림
    secret_key: str = ""  # 세션 쿠키 서명용(32자 이상 무작위 문자열)
    session_ttl_hours: int = 12
    login_max_failures: int = 10  # 같은 IP에서 10분 안에 로그인 실패 허용 횟수
    trust_proxy: bool = False  # True면 X-Forwarded-For의 첫 주소를 클라이언트 IP로 사용(프록시 뒤 배포 시)
    db_path: str = "data/app.db"  # SQLite 파일. 배포 시 영구 볼륨 경로로 지정
    job_ttl_hours: int = 72  # 분석 결과 보관 시간

    @property
    def beta_code_list(self) -> list[str]:
        return [c.strip() for c in self.beta_codes.split(",") if c.strip()]

    @property
    def auth_enabled(self) -> bool:
        return bool(self.beta_code_list)

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
