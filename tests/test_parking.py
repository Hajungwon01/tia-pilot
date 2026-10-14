"""주차수요 예측(원단위법)·법정 주차대수·계획주차대수 상한 규칙."""
import asyncio

import pytest
from docx import Document

from app.docx_export import export_docx
from app.guideline_rules import ATTENTION, OK, UNKNOWN, parking_cap
from app.parking import assess_parking, legal_apartment
from app.pipeline import TIAPipeline
from app.schemas import ProjectInput, UnitType, UseArea
from app.service import ServiceError, validate_project
from app.state import ReportState


def U(area, hh):
    return UnitType(exclusive_area_m2=area, households=hh)


def proj(units=None, hh=None, **kw):
    units = units if units is not None else []
    hh = hh if hh is not None else (sum(u.households for u in units) or 100)
    return ProjectInput(name="t", address="서울", households=hh, unit_types=units, **kw)


# ── 법정 주차대수 (주택건설기준 등에 관한 규정 제27조①1, 특별시) ──

def test_legal_apartment_mixed_unit_types():
    n, area_based, hh_min, total = legal_apartment([U(59, 300), U(84, 900), U(114, 300)])
    assert area_based == pytest.approx(300 * 59 / 75 + 900 * 84 / 75 + 300 * 114 / 65)  # 1770.15
    assert hh_min == pytest.approx(300 * 0.7 + 1200)
    assert n == 1771  # 소수점 이하 끝수는 한 대로 본다(올림)
    assert total == pytest.approx(300 * 59 + 900 * 84 + 300 * 114)


def test_85_square_meter_boundary_uses_each_rate():
    # 85㎡ 이하는 75㎡당 1대, 초과는 65㎡당 1대
    assert legal_apartment([U(85, 750)])[1] == pytest.approx(85 * 750 / 75)
    assert legal_apartment([U(85.01, 750)])[1] == pytest.approx(85.01 * 750 / 65)


def test_household_minimum_binds_for_small_units():
    n, area_based, hh_min, _ = legal_apartment([U(30, 1000)])
    assert area_based == pytest.approx(400) and hh_min == pytest.approx(700) and n == 700  # 60㎡ 이하 세대당 0.7대
    r = assess_parking(proj([U(30, 1000)]))
    assert r.binding == "household_min"
    assert legal_apartment([U(61, 100)])[2] == pytest.approx(100)  # 60㎡ 초과는 세대당 1대


def test_ceiling_applies_to_total():
    assert legal_apartment([U(84, 1)])[0] == 2  # 1.12 → 2


def test_other_uses_use_seoul_parking_ordinance_rates():
    r = assess_parking(proj([U(84, 400)], other_uses=[UseArea(use="retail_mall", area_m2=5000),
                                                      UseArea(use="office_public", area_m2=1000)]))
    assert r.legal_others == {"판매시설 중 할인점·전문점·백화점·쇼핑센터": 50.0, "공공업무시설": 5.0}
    assert r.legal_others_total == 55 and r.legal_total == r.legal_apartment + 55 and r.legal_complete


def test_other_use_half_rounds_up_and_unrated_use_marks_incomplete():
    r = assess_parking(proj([U(84, 100)], other_uses=[UseArea(use="res2", area_m2=70)]))  # 70/134 = 0.5
    assert r.legal_others_total == 1
    r = assess_parking(proj([U(84, 100)], other_uses=[UseArea(use="zoo", area_m2=20000)]))
    assert not r.legal_complete and any("포함하지 못함" in n for n in r.notes)


def test_without_unit_types_legal_is_unknown_not_guessed():
    r = assess_parking(proj(hh=500))
    assert r.legal_apartment is None and r.legal_total is None and not r.legal_complete
    assert any("주택형별" in n for n in r.notes)


# ── 주차수요 (원단위법) ──

def test_demand_uses_provisional_rate_unless_user_gives_one():
    r = assess_parking(proj(hh=1500))
    assert r.rate_status == "PROVISIONAL" and r.demand == pytest.approx(1500 * 1.2)
    r = assess_parking(proj(hh=1500, parking_demand_per_household=1.05, parking_demand_source="유사단지 3곳"))
    assert r.rate_status == "USER" and r.demand == pytest.approx(1575) and r.rate_source == "유사단지 3곳"


def test_planned_vs_legal_and_demand():
    r = assess_parking(proj([U(84, 1000)], planned_parking_spaces=1500, parking_demand_per_household=1.4))
    assert r.legal_total == 1120 and r.planned_vs_legal_pct == pytest.approx(1500 / 1120 * 100)
    assert r.planned_vs_demand == pytest.approx(1500 - 1400) and r.cap == pytest.approx(1120 * 1.3)


# ── 계획주차대수 상한 rule (별표 2 8.가⒁) ──

def state_with(planned, units=None):
    s = ReportState(project=proj(units or [U(84, 1000)], planned_parking_spaces=planned))
    s.parking = assess_parking(s.project).model_dump()
    return s


def test_cap_rule_boundaries():
    assert parking_cap(state_with(1456))[0] == OK  # 1120 × 1.3 = 1456 정확히 상한
    status, msg = parking_cap(state_with(1457))
    assert status == ATTENTION and "초과" in msg and "사유" in msg
    status, msg = parking_cap(state_with(1119))
    assert status == ATTENTION and "미달" in msg
    assert parking_cap(state_with(1120))[0] == OK


def test_cap_rule_needs_both_inputs():
    s = ReportState(project=proj(hh=500))
    s.parking = assess_parking(s.project).model_dump()
    status, msg = parking_cap(s)
    assert status == UNKNOWN and "계획 주차대수" in msg and "주택형별" in msg
    assert parking_cap(ReportState(project=proj(hh=500)))[0] == UNKNOWN  # 주차 계산 자체가 없을 때도 추측하지 않음


# ── 서비스·파이프라인·문서 ──

def test_service_rejects_unit_type_household_mismatch():
    with pytest.raises(ServiceError):
        validate_project(ProjectInput(name="t", address="서울", households=1000, unit_types=[U(84, 900)]))
    validate_project(ProjectInput(name="t", address="서울", households=1000, unit_types=[U(84, 1000)]))


def run(**kw):
    p = ProjectInput(name="주차단지", address="서울 OO동", households=1000, gross_floor_area_m2=120000, floors=20, **kw)
    return asyncio.run(TIAPipeline().run(ReportState(project=p)))


def test_pipeline_fills_parking_sections_and_checklist_keys():
    st = run(unit_types=[U(84, 1000)], planned_parking_spaces=1500)
    text = st.sections["demand.parking"]
    assert "1,120대" in text and "1,500대" in text and "법정 대비 134%" in text
    assert "원단위법" in st.sections["parking.method"]
    assert "demand.parking" not in st.reflection["missing"] and "parking.method" not in st.reflection["missing"]
    assert any("권장 상한 130%" in w and "1,456" in w for w in st.warnings)
    rule = next(r for r in st.reflection["rules"] if r["id"] == "A2-8.5")
    assert rule["status"] == "attention"
    assert any("임시" in w and "주차수요 원단위" in w for w in st.warnings)


def test_pipeline_without_parking_inputs_asks_for_them():
    st = run()
    assert {"project.unit_types", "project.planned_parking_spaces"} <= set(st.needs_input)
    assert "주택형별 전용면적·세대수 입력 필요" in st.sections["demand.parking"]
    rule = next(r for r in st.reflection["rules"] if r["id"] == "A2-8.5")
    assert rule["status"] == "unknown"


def test_demand_above_planned_warns():
    st = run(unit_types=[U(84, 1000)], planned_parking_spaces=1100)  # 수요 1,200 > 계획 1,100
    assert any("초과" in w and "계획 주차대수" in w for w in st.warnings)
    assert "부족" in st.sections["demand.parking"]


def test_api_and_ui_show_parking(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app import auth, main
    from app.storage import Database, LlmRunLog, SqliteJobStore
    db = Database(tmp_path / "t.db")
    monkeypatch.setattr(main, "store", SqliteJobStore(db))
    monkeypatch.setattr(main, "limiter", LlmRunLog(db))
    monkeypatch.setattr(main, "throttle", auth.LoginThrottle())
    c = TestClient(main.app)
    body = {"project": {"name": "t", "address": "서울", "households": 1000, "gross_floor_area_m2": 120000, "floors": 20,
                        "unit_types": [{"exclusive_area_m2": 84, "households": 1000}], "planned_parking_spaces": 1500}}
    j = c.post("/api/analyze", json=body).json()
    assert j["parking"]["legal_total"] == 1120 and j["parking"]["planned"] == 1500
    assert any(r["id"] == "A2-8.5" and r["label"] == "검토 필요" for r in j["reflection"]["rules"])
    html = c.post("/ui/analyze", json=body).text
    assert "주차수요 예측" in html and "1,120대" in html and "임시 원단위" in html
    bad = c.post("/api/analyze", json={"project": {**body["project"], "households": 999}})
    assert bad.status_code == 422
    assert "주차" in c.get("/app").text


def test_docx_form_items_4_and_5_are_filled(tmp_path):
    st = run(unit_types=[U(84, 1000)], planned_parking_spaces=1500, parking_demand_per_household=1.3,
             parking_demand_source="유사단지 조사")
    doc = Document(export_docx(st, tmp_path / "o.docx"))
    cells = [c.text for t in doc.tables for r in t.rows for c in r.cells]
    assert "1,300" in cells and "1,120" in cells and "1,500" in cells  # 수요·법정·계획
    assert "유사단지 조사" in cells and "84,000" in cells  # 출처·전용면적 합계
    assert any("0.0155" in c for c in cells)  # 1.3 / 84 대/㎡
