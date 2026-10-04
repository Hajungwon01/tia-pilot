import asyncio
from datetime import date

import pytest
from docx import Document

from app.docx_export import CHAPTERS, KEY_TITLES, add_text_block, export_docx
from app.pipeline import TIAPipeline
from app.reflection import load_checklist
from app.schemas import Approach, ProjectInput
from app.state import IntersectionInput, ReportState


def make_state(full=True):
    st = ReportState(
        project=ProjectInput(name="테스트 단지", address="서울 OO동", households=1500, gross_floor_area_m2=180_000),
        background_growth_rate=0.02 if full else None,
        intersections=[IntersectionInput(name="A교차로", cycle=120, approaches=[
            Approach(name="N", volume=400, saturation_flow=1800, green_time=40, project_share=0.4),
            Approach(name="E", volume=500, saturation_flow=1800, green_time=40, project_share=0.1)])] if full else [])
    return asyncio.run(TIAPipeline().run(st))


@pytest.fixture
def doc(tmp_path):
    p = export_docx(make_state(), tmp_path / "out.docx", today=date(2026, 10, 5))
    return Document(p)


def texts(d, style=None):
    return [p.text for p in d.paragraphs if style is None or p.style.name == style]


def test_every_checklist_key_has_a_title_and_a_chapter():
    keys = {i["key"] for i in load_checklist()["items"] if i["check"] == "key"}
    assert keys == set(KEY_TITLES)
    prefixes = {p for _, _, ps in CHAPTERS for p in ps}
    assert {k.split(".")[0] for k in keys} <= prefixes  # 어떤 장에도 안 들어가 누락되는 항목이 없어야 함


def test_chapters_in_guideline_order(doc):
    h1 = [t for t in texts(doc, "Heading 1") if t[:2] in {f"{n}." for n, _, _ in CHAPTERS}]
    assert h1 == [f"{n}. {title}" for n, title, _ in CHAPTERS]


def test_all_checklist_sections_are_rendered_once(doc):
    h3 = texts(doc, "Heading 3")
    for key, title in KEY_TITLES.items():
        assert title in h3, key
    # 항목 수 + 표 소제목 2개(현황 LOS, 3단계 비교)
    assert len(h3) == len(KEY_TITLES) + 2


def test_disclaimer_in_header_and_cover(doc):
    assert "초안 작성 지원 도구" in doc.sections[0].header.paragraphs[0].text
    assert any("최종 검토·날인" in t for t in texts(doc))


def test_cover_has_project_info_and_date(doc):
    cover = {r.cells[0].text: r.cells[1].text for r in doc.tables[0].rows[1:]}
    assert cover["사업명"] == "테스트 단지" and cover["작성일"] == "2026-10-05"
    assert cover["건축 연면적"] == "180,000㎡"


def test_tables_present_with_numbers(doc):
    heads = [[c.text for c in t.rows[0].cells] for t in doc.tables]
    assert ["교차로", "접근로", "용량(대/시)", "v/c", "지체(초/대)", "LOS"] in heads
    stage = next(t for t in doc.tables if len(t.columns) > 2 and t.rows[0].cells[2].text == "미시행")
    assert len(stage.rows) == 1 + 2  # 목표년도 1년·3년
    assert "(" in stage.rows[1].cells[2].text  # 지체(LOS) 표기


def test_missing_and_mock_sections_are_marked_not_silently_filled(doc):
    marked = [t for t in texts(doc) if t.startswith("[미작성]")]
    assert len(marked) >= 5
    assert any("LLM 미연결" in t for t in marked)  # mock으로 쓴 AI 섹션은 자리표시로 표시


def test_needs_input_listed_when_inputs_missing(tmp_path):
    d = Document(export_docx(make_state(full=False), tmp_path / "o.docx"))
    t = texts(d)
    assert "입력이 더 필요한 항목" in texts(d, "Heading 2")
    assert any("배경교통량 연 증가율" in x or "교차로 접근로별" in x for x in t)


def test_flagged_text_is_marked_with_reason(tmp_path):
    st = make_state()
    st.put("improve.access", "교통량이 용량을 초과하고 녹색시간 99초가 필요합니다.", "ai")
    d = Document(export_docx(st, tmp_path / "f.docx"))
    t = texts(d)
    assert any("검토 필요(계산 결과와 불일치 가능)" in x and "99초" in x for x in t)
    assert "계산 결과와 불일치 가능 — 검토 필요" in texts(d, "Heading 2")


def test_markdown_in_llm_text_is_converted(tmp_path):
    from docx import Document as D
    d = D()
    add_text_block(d, "### 소제목\n**굵게** 본문\n- 항목1\n| a | b |\n|---|---|\n| 1 | 2 |")
    body = "\n".join(p.text for p in d.paragraphs)
    assert "###" not in body and "**" not in body and "소제목" in body and "굵게 본문" in body
    assert d.tables and d.tables[0].rows[1].cells[0].text == "1"
    assert any(r.bold for p in d.paragraphs for r in p.runs if r.text == "굵게")


def test_show_refs_toggle(tmp_path):
    st = make_state()
    with_refs = Document(export_docx(st, tmp_path / "a.docx", show_refs=True))
    without = Document(export_docx(st, tmp_path / "b.docx", show_refs=False))
    assert any(t.startswith("근거:") for t in texts(with_refs))
    assert not any(t.startswith("근거:") for t in texts(without))
