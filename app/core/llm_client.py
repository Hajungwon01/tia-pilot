"""LLM 호출 래퍼. API 키가 없으면 mock 응답(접두어 MOCK_PREFIX)을 돌려준다."""
import asyncio

from app.config import get_settings

MOCK_PREFIX = "[MOCK]"


class LLMClient:
    def __init__(self) -> None:
        s = get_settings()
        self.mock_mode = s.llm_mock_mode
        self.model = s.llm_model
        self._client = None
        if not self.mock_mode:
            import anthropic  # 키가 있을 때만 지연 임포트

            self._client = anthropic.Anthropic(api_key=s.anthropic_api_key)

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        if self.mock_mode:
            return f"{MOCK_PREFIX} 실제 LLM 미연결 상태의 자리표시 문장입니다."
        resp = await asyncio.to_thread(
            self._client.messages.create,
            model=self.model,
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return resp.content[0].text
