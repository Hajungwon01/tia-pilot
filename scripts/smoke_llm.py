"""LLM 실연결 점검. 프로젝트 루트에서 실행: python scripts/smoke_llm.py

키 값은 출력하지 않는다. 1) 설정 확인 2) 짧은 호출 3) 파이프라인 1회 실행.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.core.llm_client import LLMClient  # noqa: E402
from app.pipeline import TIAPipeline  # noqa: E402
from app.schemas import Approach, ProjectInput  # noqa: E402
from app.state import IntersectionInput, ReportState  # noqa: E402


async def main() -> int:
    s = get_settings()
    print(f"모델: {s.llm_model} | 키 설정됨: {bool(s.anthropic_api_key)} | mock: {s.llm_mock_mode}")
    if s.llm_mock_mode:
        print("ANTHROPIC_API_KEY가 비어 있습니다. .env를 확인하세요 (프로젝트 루트에서 실행해야 .env를 읽습니다).")
        return 1

    llm = LLMClient()
    try:
        reply = await llm.complete("한 문장으로만 답하세요.", "연결 테스트입니다. '확인'이라고 답하세요.")
    except Exception as e:  # 인증·모델명·네트워크 오류를 구분해 보여준다
        print(f"호출 실패: {type(e).__name__}: {e}")
        return 2
    print("짧은 호출 OK:", reply[:80])

    state = ReportState(
        project=ProjectInput(name="점검용 단지", address="서울 OO동", households=1500, gross_floor_area_m2=180_000),
        intersections=[IntersectionInput(
            name="A교차로", cycle=120,
            approaches=[Approach(name="N", volume=400, saturation_flow=1800, green_time=40),
                        Approach(name="E", volume=500, saturation_flow=1800, green_time=40)])],
    )
    out = await TIAPipeline(llm).run(state)
    r = out.reflection
    print(f"파이프라인 OK | 통과 {r['passed']}/{r['auto_total']} | AI 섹션 미검증(mock) {len(r['unverified_mock'])} | 재시도 {out.iterations}")
    print("--- improve.roads_intersections 샘플 ---")
    print(out.sections.get("improve.roads_intersections", "(없음)")[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
