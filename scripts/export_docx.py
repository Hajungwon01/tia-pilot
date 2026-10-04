"""샘플 입력으로 파이프라인을 돌려 DOCX 초안을 만든다.

기본은 LLM을 mock으로 강제한다(키가 있어도 외부 호출·과금 없음).
실제 LLM으로 문장을 쓰려면 --live (LLM 호출 5회 이상, 비용 발생).

  python scripts/export_docx.py                 # mock, output/교통영향평가서_초안.docx
  python scripts/export_docx.py --live --out 내문서.docx
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ap = argparse.ArgumentParser()
ap.add_argument("--live", action="store_true", help="설정된 실제 LLM 사용(과금)")
ap.add_argument("--out", default="output/교통영향평가서_초안.docx")
args = ap.parse_args()

if not args.live:  # 환경변수가 .env보다 우선하므로 빈 값으로 덮어써 mock을 강제
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["ANTHROPIC_API_KEY"] = ""

from app.docx_export import export_docx  # noqa: E402
from app.pipeline import TIAPipeline  # noqa: E402
from app.schemas import Approach, ProjectInput  # noqa: E402
from app.state import IntersectionInput, ReportState  # noqa: E402


async def main() -> None:
    pipe = TIAPipeline()
    print(f"LLM: {'mock' if pipe.llm.mock_mode else pipe.llm.provider + ' (live)'}")
    state = ReportState(
        project=ProjectInput(name="샘플 단지", address="서울특별시 OO구 OO동", households=1500,
                             gross_floor_area_m2=180_000),
        background_growth_rate=0.02,
        intersections=[IntersectionInput(
            name="A교차로", cycle=120, peak="pm",
            approaches=[Approach(name="N", volume=400, saturation_flow=1800, green_time=40, project_share=0.4),
                        Approach(name="E", volume=500, saturation_flow=1800, green_time=40, project_share=0.1)])],
    )
    state = await pipe.run(state)
    out = export_docx(state, args.out)
    print("저장:", out.resolve())


asyncio.run(main())
