"""TIAPipeline: Planning → Data → (Creative ∥ AI) → Engineering → Reflection (+재시도 루프)."""
import asyncio

from app.agents.ai import AI_SECTIONS, AIAgent
from app.agents.creative import CreativeAgent
from app.agents.data import DataAgent
from app.agents.engineering import EngineeringAgent
from app.agents.planning import PlanningAgent
from app.agents.reflection_agent import ReflectionAgent
from app.config import get_settings
from app.core.llm_client import LLMClient
from app.state import ReportState


class TIAPipeline:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()
        self.planning = PlanningAgent(self.llm)
        self.data = DataAgent(self.llm)
        self.creative = CreativeAgent(self.llm)
        self.ai = AIAgent(self.llm)
        self.engineering = EngineeringAgent(self.llm)
        self.reflection = ReflectionAgent(self.llm)

    async def run(self, state: ReportState) -> ReportState:
        state = await self.planning.run(state)
        state = await self.data.run(state)
        # Creative와 AI는 Data 결과만 필요하므로 병렬. 서로 다른 필드를 쓰므로 안전.
        await asyncio.gather(self.creative.run(state), self.ai.run(state))
        state = await self.engineering.run(state)
        state = await self.reflection.run(state)

        # Reflection이 AI 소유 섹션 누락을 지적하면 해당 섹션만 재작성 (LLM이 실연결일 때만 의미 있음)
        retries = get_settings().max_reflection_retries
        while not self.llm.mock_mode and state.iterations < retries:
            redo = [k for k in state.reflection["missing"] if k in AI_SECTIONS]
            if not redo:
                break
            state.iterations += 1
            await self.ai.run(state, only=redo, feedback="이전 초안에서 누락·미흡으로 지적됨. 해당 항목을 빠짐없이 작성하세요.")
            state = await self.engineering.run(state)
            state = await self.reflection.run(state)
        return state
