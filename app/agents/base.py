from abc import ABC, abstractmethod

from app.core.llm_client import LLMClient
from app.state import ReportState


class BaseAgent(ABC):
    """모든 에이전트는 공유 상태를 받아 자기 몫을 채우고 반환한다.

    계산·규칙 판정은 코드로, 문장 생성이 필요한 부분만 LLM을 쓴다(LLM이 숫자를 만들지 않음).
    """

    name = "base"

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    @abstractmethod
    async def run(self, state: ReportState) -> ReportState: ...
