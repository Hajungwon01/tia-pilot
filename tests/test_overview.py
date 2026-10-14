"""사업의 개요 필수 기재 항목(서울 지침 제24조③)과 표지 양식(별표 11)."""
import asyncio

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app import auth, main
from app.docx_export import export_docx
from app.docx_forms import cover_agency_lines, cover_color
from app.guideline_rules import ATTENTION, OK, overview_required
from app.overview import NEED, missing_overview, overview_rows
from app.pipeline import TIAPipeline
from app.schemas import ProjectInput, ProjectOverview, UnitType
from app.state import AgencyInfo, ReportState
from app.storage import Database, LlmRunLog, SqliteJobStore

FULL_OV = ProjectOverview(
    permit_laws="건축법 제11조", project_period="2027.1~2029.12", urban_planning="제3종일반주거지역", actual_use="공동주택(아파트)",
    site_area_m2=30000, building_coverage_pct=22, floor_area_ratio_pct=250, basement_floors=3, entrances=2,
    parking_self=1400, parking_mechanical=100, parking_accessible=30, parking_women=40, parking_compact=50, parking_tour_bus=0)


def run(ov=None, agency=None, **kw):
    p = ProjectInput(name="개요단지", address="서울 OO동", households=1000, gross_floor_area_m2=120000, floors=25,
                     unit_types=[UnitType(exclusive_area_m2=84, households=1000)], planned_parking_spaces=1500,
                     overview=ov or ProjectOverview(), **kw)
    return asyncio.run(TIAPipeline().run(ReportState(project=p, agency=agency)))


def by_label(rows):
    return {r["label"]: r for r in rows}


def test_empty_inputs_leave_user_facts_missing_but_fill_computed_ones():
    st = run()
    rows = by_label(overview_rows(st))
    for must_input in ("인·허가 관련 법규", "사업기간", "도시계획사항", "대지면적", "건폐율", "용적률", "사업지 진출입구 수",
                       "사업시행자(연락처)", "주차시설 — 자주식·기계식 구분", "발생교통량 — 주변가로 첨두시·1일(목표년도별)"):
        assert rows[must_input]["source"] == "missing" and rows[must_input]["value"] is None, must_input
    assert rows["사업명"]["value"] == "개요단지" and rows["위치"]["value"] == "서울 OO동"
    assert rows["건축연면적"]["value"] == "120,000㎡"
    assert "1,120대" in rows["주차시설 — 법정·수요·계획 대수와 비율"]["value"] and "법정 대비 134%" in rows["주차시설 — 법정·수요·계획 대수와 비율"]["value"]
    assert rows["규모"]["value"] == "지상 25층, 1,000세대" and "지하 층수 미입력" in rows["규모"]["note"]
    assert rows["Swa값(복합용도)"]["value"].startswith("해당 없음")
    assert rows["실제 용도"]["value"] == "공동주택(아파트)" and rows["실제 용도"]["source"] == "auto"
    assert "일 " in rows["발생교통량 — 사업지(승용차)"]["value"] and "임시 원단위" in rows["발생교통량 — 사업지(승용차)"]["value"]


def test_filled_inputs_appear_and_only_peripheral_traffic_stays_missing():
    ag = AgencyInfo(client_name="OO주택", client_phone="02-111-1111")
    st = run(FULL_OV, ag)
    rows = by_label(overview_rows(st))
    assert rows["사업시행자(연락처)"]["value"] == "OO주택 / 02-111-1111"
    assert rows["규모"]["value"] == "지하 3층, 지상 25층, 1,000세대"
    assert rows["주차시설 — 자주식·기계식 구분"]["value"] == "자주식 1,400대, 기계식 100대"
    assert rows["주차시설 — 장애인·여성·경차·관광버스"]["value"] == "장애인 30대, 여성 40대, 경차 50대, 관광버스 0대"  # 0은 입력한 값
    assert missing_overview(st) == ["발생교통량 — 주변가로 첨두시·1일(목표년도별)"]
    assert rows["사업시행자(연락처)"]["note"] == "" and rows["주차시설 — 자주식·기계식 구분"]["note"] == ""  # 안내는 비었을 때만


def test_zero_is_a_value_not_missing():
    ov = ProjectOverview(parking_accessible=0, parking_women=0, parking_compact=0, parking_tour_bus=0, entrances=0)
    rows = by_label(overview_rows(run(ov)))
    assert rows["주차시설 — 장애인·여성·경차·관광버스"]["source"] == "input"
    assert rows["사업지 진출입구 수"]["value"] == "0개소"


def test_mixed_use_shows_swa_and_other_uses():
    from app.schemas import UseArea
    st = run(other_uses=[UseArea(use="retail_mall", area_m2=3000)])
    rows = by_label(overview_rows(st))
    assert "판매시설 중 할인점·전문점·백화점·쇼핑센터 3,000㎡" in rows["실제 용도"]["value"]
    assert rows["Swa값(복합용도)"]["value"].endswith("(10,000 이상이면 대상)")


def test_rule_flags_missing_then_passes_when_complete():
    st = run()
    status, msg = overview_required(st)
    assert status == ATTENTION and "미기재" in msg and "건폐율" in msg
    rule = next(r for r in st.reflection["rules"] if r["id"] == "SE-9")
    assert rule["status"] == "attention"


def test_rule_ok_when_everything_but_unfillable_is_given():
    """주변가로 교통량은 이 도구가 만들 수 없으므로 마지막 한 칸은 사람이 채워야 한다(규칙은 그 한 칸을 남긴다)."""
    st = run(FULL_OV, AgencyInfo(client_name="OO주택", client_phone="02"))
    status, msg = overview_required(st)
    assert status == ATTENTION and msg.endswith("주변가로 첨두시·1일(목표년도별)")


def test_cover_follows_seoul_form():
    a = AgencyInfo(receipt_no="2026-123", management_no="M-9", agency_name="OO엔지니어링", lead_name="홍길동", client_name="OO주택")
    rows = dict(map(tuple, cover_agency_lines(a, year_month="2026년 11월")))
    assert rows["접수번호"] == "2026-123" and rows["관리번호"] == "M-9" and rows["연도·월"] == "2026년 11월"
    assert rows["평가기관(평가대행업체)"] == "OO엔지니어링" and rows["평가책임자(평가대행자)"] == "홍길동" and rows["사업자명"] == "OO주택"
    assert rows["심의종류"].startswith("신규") and rows["심의진행여부"] == "본보고서(최초 접수)" and rows["표지색(인쇄 시)"] == "파란색"
    empty = dict(map(tuple, cover_agency_lines(None)))
    assert empty["접수번호"] == NEED and empty["사업자명"] == NEED


@pytest.mark.parametrize("rtype,stage,color", [("new", "main", "파란색"), ("change", "main", "녹색"),
                                               ("new", "pre_review", "흰색"), ("change", "re_review", "흰색"),
                                               ("new", "decision", "주황색")])
def test_cover_colors_follow_annex_11(rtype, stage, color):
    assert cover_color(AgencyInfo(review_type=rtype, review_stage=stage)) == color


def test_cover_review_type_labels_counts_and_abbreviated_override():
    r = dict(map(tuple, cover_agency_lines(AgencyInfo(review_type="change", change_count=2))))
    assert r["심의종류"] == "변경(2회)"
    r = dict(map(tuple, cover_agency_lines(AgencyInfo(review_stage="re_review", stage_count=3))))
    assert r["심의진행여부"] == "보완심의 보고서(3회)"
    assert dict(map(tuple, cover_agency_lines(AgencyInfo(), abbreviated=True)))["심의종류"] == "약식"  # 약식 적용 시 자동


def test_docx_has_cover_fields_and_overview_table(tmp_path):
    st = run(FULL_OV, AgencyInfo(client_name="OO주택", client_phone="02-111-1111", receipt_no="R-1"))
    doc = Document(export_docx(st, tmp_path / "o.docx"))
    cover = {r.cells[0].text: r.cells[1].text for r in doc.tables[0].rows[1:]}
    assert cover["접수번호"] == "R-1" and cover["표지색(인쇄 시)"] == "파란색" and cover["연도·월"].endswith("월")
    caps = [p.text for p in doc.paragraphs]
    assert "사업의 개요 필수 기재 항목 (서울시 수립지침 제24조③)" in caps
    tbl = next(t for t in doc.tables if t.rows[0].cells[0].text == "항목" and any(r.cells[0].text == "건폐율" for r in t.rows))
    got = {r.cells[0].text: r.cells[1].text for r in tbl.rows[1:]}
    assert got["건폐율"] == "22%" and got["용적률"] == "250%" and got["대지면적"] == "30,000㎡"
    assert got["발생교통량 — 주변가로 첨두시·1일(목표년도별)"].startswith("[기재 필요]")


def test_api_and_ui_roundtrip(monkeypatch, tmp_path):
    db = Database(tmp_path / "t.db")
    monkeypatch.setattr(main, "store", SqliteJobStore(db))
    monkeypatch.setattr(main, "limiter", LlmRunLog(db))
    monkeypatch.setattr(main, "throttle", auth.LoginThrottle())
    c = TestClient(main.app)
    body = {"project": {"name": "t", "address": "서울", "households": 1000, "gross_floor_area_m2": 120000, "floors": 25,
                        "overview": {"site_area_m2": 30000, "entrances": 2}},
            "agency": {"client_name": "OO주택", "client_phone": "02", "receipt_no": "R-7", "review_type": "change", "change_count": 1}}
    j = c.post("/api/analyze", json=body).json()
    rows = {r["label"]: r for r in j["overview"]}
    assert rows["대지면적"]["value"] == "30,000㎡" and rows["사업지 진출입구 수"]["value"] == "2개소"
    html = c.post("/ui/analyze", json=body).text
    assert "사업의 개요 필수 기재 항목" in html and "기재 필요" in html
    page = c.get("/app").text
    assert "ov_site" in page and "ag_receipt" in page and "별표 11" in page
    bad = c.post("/api/analyze", json={**body, "agency": {"review_type": "weird"}})
    assert bad.status_code == 422
    assert c.post("/api/analyze", json={**body, "project": {**body["project"], "overview": {"building_coverage_pct": 150}}}).status_code == 422


def test_ok_status_constant_reachable():
    """모든 필수 항목이 채워진 상태를 직접 구성하면 규칙은 통과한다."""
    st = run(FULL_OV, AgencyInfo(client_name="OO주택", client_phone="02"))
    import app.overview as ov
    orig = ov.overview_rows
    try:
        ov.overview_rows = lambda s: [{"label": "x", "value": "v", "source": "input", "note": ""}]
        assert overview_required(st)[0] == OK
    finally:
        ov.overview_rows = orig
