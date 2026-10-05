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


def chapter_h3(d):
    """본문 1~6장 구간의 Heading 3 (별지·끝문 등 서식 부분 제외)."""
    out, on = [], False
    for p in d.paragraphs:
        if p.style.name == "Heading 1":
            on = p.text.startswith(("1. ", "2. ", "3. ", "4. ", "5. ", "6. "))
        if on and p.style.name == "Heading 3":
            out.append(p.text)
    return out


def test_all_checklist_sections_are_rendered_once(doc):
    h3 = chapter_h3(doc)
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


# ── 지침 제24조 서식 / 별지 제1호 / 목차 ──
from app.state import AgencyInfo, StaffMember  # noqa: E402


def full_agency():
    return AgencyInfo(
        agency_name="OO교통엔지니어링", registration_no="제2020-001호", registration_date="2020-03-02",
        lead_name="홍길동", submission_date="2026-11-20", service_period="2026-09-01 ~ 2026-11-20",
        printer="OO인쇄", concept_design_firm="OO설계", agency_address="서울 OO구", agency_phone="02-000-0000",
        client_name="OO주택(주)", client_address="서울 OO구", client_phone="02-111-1111",
        cost_basis_attached=True, contract_copy_attached=False,
        staff=[StaffMember(name="김등록", affiliation="OO", position="이사", period="3개월", qualification="교통기술사 123",
                           roles=["책임자", "교통수요예측"], registered=True),
               StaffMember(name="이미등록", affiliation="OO", position="사원", period="2개월", qualification="-",
                           roles=["교통환경 현황조사"], registered=False)])


def all_text(d):
    cells = [c.text for t in d.tables for r in t.rows for c in r.cells]
    return "\n".join(texts(d) + cells)


def test_missing_agency_info_is_blank_not_invented(doc):
    t = all_text(doc)
    assert "[기재 필요]" in t
    cover = {r.cells[0].text: r.cells[1].text for r in doc.tables[0].rows[1:]}
    assert cover["평가대행업체"] == "[기재 필요]" and cover["평가대행자(책임자)"] == "[기재 필요]"
    assert "(서명 또는 날인)" in t and "대신하지 않습니다" in t  # 서명·날인은 사람 몫


def test_agency_info_appears_on_cover_submission_and_closing(tmp_path):
    st = make_state()
    st.agency = full_agency()
    d = Document(export_docx(st, tmp_path / "a.docx"))
    cover = {r.cells[0].text: r.cells[1].text for r in d.tables[0].rows[1:]}
    assert cover["평가대행업체"] == "OO교통엔지니어링" and cover["평가대행자(책임자)"] == "홍길동"
    t = all_text(d)
    assert "제2020-001호" in t and "2026-11-20" in t and "OO인쇄" in t and "OO설계" in t
    assert "첨부함" in t and "[첨부 필요]" in t  # 가격 산출근거 첨부 / 용역계약서 사본 미첨부


def test_staff_table_splits_registered_and_unregistered_with_roles(tmp_path):
    st = make_state()
    st.agency = full_agency()
    d = Document(export_docx(st, tmp_path / "s.docx"))
    staff = next(t for t in d.tables if "성명" in [c.text for c in t.rows[0].cells])
    assert [staff.rows[1].cells[0].text, staff.rows[2].cells[0].text] == ["등록", "미등록"]
    hdr = [c.text for c in staff.rows[0].cells]
    assert hdr[6:] == ["책임자", "교통환경 현황조사", "관련자료 수집", "평가지표 설정", "교통수요예측",
                       "문제점 도출·분석", "교통개선대책 수립"]  # 제24조⑧ 참여정도 구분
    assert staff.rows[1].cells[hdr.index("책임자")].text == "○"
    assert staff.rows[1].cells[hdr.index("교통환경 현황조사")].text == ""


def test_byeolji1_form_structure_and_calculated_values(doc):
    h = texts(doc, "Heading 1")
    assert any(x.startswith("별지 제1호 서식") for x in h)
    h3 = texts(doc, "Heading 3")
    for sub in ("① 활동인구 분석", "② 수단분담률 분석", "③ 유발교통량", "④ 주차수요 원단위", "⑤ 주차수요 예측결과 및 확보 내역"):
        assert sub in h3
    t = all_text(doc)
    assert "교차로 신호주기 조정" in t and "1건(검토)" in t  # 계산한 개선 검토 건수
    assert "시간절감 분석" in t and "임시 원단위" in t  # 임시 원단위 표시


def test_byeolji1_trip_numbers_match_calculation(doc):
    import re
    st = make_state()
    t = st.trips
    pk = t.am_peak if t.am_peak.total >= t.pm_peak.total else t.pm_peak
    form = next(tb for tb in doc.tables if [c.text for c in tb.rows[0].cells][:3] == ["구분", "", "계"])
    assert form.rows[1].cells[2].text == f"{pk.in_trips:.0f}"
    assert form.rows[2].cells[2].text == f"{pk.out_trips:.0f}"
    assert form.rows[3].cells[2].text == ""  # 주변가로 값은 계산하지 않으므로 법정 서식처럼 빈 칸


def test_toc_field_and_update_request(tmp_path):
    p = export_docx(make_state(), tmp_path / "t.docx")
    d = Document(p)
    xml = d.element.xml
    assert "TOC" in xml and "1-3" in xml  # 목차 필드 지시문(제목 1~3단계)
    assert "목 차" in texts(d, "Heading 1")
    assert d.settings.element.find(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}updateFields") is not None


def test_closing_pages_come_last(doc):
    h1 = texts(doc, "Heading 1")
    assert h1[-1] == "끝 문"
    assert h1.index("부록: 분석 기준·가정") < next(i for i, x in enumerate(h1) if x.startswith("별지 제1호")) < len(h1) - 1


def test_wide_forms_are_on_landscape_a4_pages(doc):
    from docx.enum.section import WD_ORIENT
    secs = doc.sections
    assert len(secs) == 2
    assert secs[0].orientation == WD_ORIENT.PORTRAIT and secs[1].orientation == WD_ORIENT.LANDSCAPE
    assert secs[1].page_width > secs[1].page_height  # A4 가로(제24조①: A4)
    assert abs(secs[1].page_width.cm - 29.7) < 0.1 and abs(secs[1].page_height.cm - 21.0) < 0.1


def test_dense_form_tables_use_empty_cells_not_repeated_placeholders(doc):
    quant = next(tb for tb in doc.tables if tb.rows[0].cells[1].text == "교통영향평가(안)")
    body = [c.text for r in quant.rows[1:] for c in r.cells[3:9]]
    assert "[기재 필요]" not in body  # 칸마다 [기재 필요]가 줄바꿈되던 문제
    assert body.count("") > len(body) * 0.9
