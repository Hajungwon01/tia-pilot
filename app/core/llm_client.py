"""LLM 호출 래퍼(Anthropic/OpenAI 선택). 키가 없으면 mock 응답(접두어 MOCK_PREFIX)을 돌려준다."""
import asyncio

from app.config import get_settings

MOCK_PREFIX = "[MOCK]"
SUPPORTED = ("anthropic", "openai")


class LLMClient:
    def __init__(self, force_mock: bool = False) -> None:
        """force_mock=True면 키가 설정돼 있어도 외부 호출 없이 mock으로 동작한다(웹 기본값)."""
        s = get_settings()
        if s.llm_provider not in SUPPORTED:
            raise ValueError(f"지원하지 않는 LLM_PROVIDER: {s.llm_provider!r} (가능: {', '.join(SUPPORTED)})")
        self.provider = s.llm_provider
        self.mock_mode = force_mock or s.llm_mock_mode
        self.model = s.model
        self._client = None
        if not self.mock_mode:
            if self.provider == "openai":
                import openai  # 키가 있을 때만 지연 임포트

                self._client = openai.OpenAI(api_key=s.api_key)
            else:
                import anthropic

                self._client = anthropic.Anthropic(api_key=s.api_key)

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        if self.mock_mode:
            return f"{MOCK_PREFIX} 실제 LLM 미연결 상태의 자리표시 문장입니다."
        return await asyncio.to_thread(self._call, system_prompt, user_prompt)

    def _call(self, system_prompt: str, user_prompt: str) -> str:
        if self.provider == "openai":
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_prompt}],
                max_completion_tokens=1500,
            )
            return resp.choices[0].message.content or ""
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return resp.content[0].text
