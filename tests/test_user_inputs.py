"""가정·임시값 대신 사용자가 직접 입력하는 값: 원단위 직접 입력, 개선 후보 탐색 조건, 설계속도."""
import asyncio
import io

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import design_criteria as DC
from app import main
from app.docx_export import build_docx
from app.hcm_signal import DetailedApproach as A
from app.hcm_signal import DetailedIntersection as I
from app.hcm_signal import Phase as P
from app.improvement import Params, build_scenarios
from app.pipeline import TIAPipeline
from app.schemas import ProjectInput, RateOverrides
from app.state import ReportState
from app.trip_generation import estimate_trips


def project(**kw):
    return ProjectInput(name="입력", address="서울", households=1000, gross_floor_area_m2=120_000, **kw)


FULL = dict(person_trips_per_household=4.0, car_share_pct=25, am_in_pct=3, am_out_pct=30, pm_in_pct=15, pm_out_pct=4, source="자체 조사 2026-09")


# ── 원단위 직접 입력 ──
def test_override_replaces_each_item_and_keeps_the_rest():
    base = estimate_trips(project())
    t = estimate_trips(project(rate_overrides=RateOverrides(person_trips_per_household=4.0)))
    assert t.daily_person_trips == 4000 and base.daily_person_trips == 8000
    assert t.rates_status == "PROVISIONAL" and any("세대당 일 발생원단위: 사용자 입력 4인/일" in n for n in t.rate_notes)
    car = estimate_trips(project(rate_overrides=RateOverrides(car_share_pct=20)))
    assert car.daily_vehicle_trips == pytest.approx(8000 * 0.20 / 1.3)


def test_peak_override_changes_peak_trips_and_in_ratio():
    t = estimate_trips(project(rate_overrides=RateOverrides(am_in_pct=3, am_out_pct=30, pm_in_pct=15, pm_out_pct=4)))
    daily = t.daily_vehicle_trips
    assert t.am_peak.in_trips == pytest.approx(daily * 0.5 * 33 / 100 * 3 / 33)
    assert t.am_peak.out_trips == pytest.approx(daily * 0.5 * 30 / 100)
    assert t.pm_peak.in_trips == pytest.approx(daily * 0.5 * 15 / 100)


def test_all_user_values_give_user_status_in_both_modes():
    ov = RateOverrides(**FULL)
    for basis in ("provisional", "evidence"):
        t = estimate_trips(project(rate_basis=basis, rate_overrides=ov, car_occupancy=1.4))
        assert t.rates_status == "USER", basis
    assert estimate_trips(project(rate_basis="evidence", rate_overrides=ov)).rates_status != "USER"  # 재차인원 빠짐


def test_override_beats_evidence_in_evidence_mode():
    t = estimate_trips(project(rate_basis="evidence", rate_overrides=RateOverrides(person_trips_per_household=5.0)))
    assert t.daily_person_trips == 5000 and any("사용자 입력" in n for n in t.rate_notes)


@pytest.mark.parametrize("bad", [dict(am_in_pct=3), dict(pm_out_pct=4), dict(am_in_pct=0, am_out_pct=0), dict(car_share_pct=101),
                                 dict(person_trips_per_household=0), dict(person_trips_per_household=31)])
def test_override_validation(bad):
    with pytest.raises(ValidationError):
        RateOverrides(**bad)


# ── 개선 후보 탐색 조건 ──
def four_leg():
    def ap(n, ph, vl, vt, vr, lanes=2, case=6, opp=None, **kw):
        return A(name=n, topology="four_way", left_case=case, lanes=lanes, v_left=vl, v_through=vt, v_right=vr, phase=ph, opposing=opp,
                 project_share_through=0.1, **kw)
    return I(name="T", cycle=120, phf=0.95, phases=[P(green=40), P(green=40), P(green=25)],
             approaches=[ap("EB", 0, 120, 900, 200, 3, 6, "WB"), ap("WB", 0, 100, 800, 150, 3, 6, "EB"),
                         ap("NB", 1, 150, 700, 120, 2, 4), ap("SB", 1, 140, 650, 100, 2, 4)])


def run(st):
    return asyncio.run(TIAPipeline().run(st))


def test_params_from_project_and_defaults():
    assert Params.from_project(project()).is_default
    p = Params.from_project(project(min_green_s=12, cycle_search_min_s=80, cycle_search_max_s=140))
    assert (p.min_green, p.cycle_min, p.cycle_max) == (12, 80, 140) and not p.is_default


def test_cycle_search_range_is_respected_and_reported():
    b = build_scenarios(four_leg(), Params(cycle_min=100, cycle_max=130))
    assert all(100 <= s["cycle"] <= 130 for s in b["scenarios"])
    assert any("신호주기 100~130초(입력값)" in n for n in b["notes"])
    assert any("기본값" in n for n in build_scenarios(four_leg())["notes"])


def test_larger_minimum_green_blocks_candidates_that_need_shorter_greens():
    ix = four_leg()
    huge = build_scenarios(ix, Params(min_green=45))  # 현시 3개가 모두 45초 이상이어야 해서 재배분·주기 조정 불가(최대 주기 180초 기준)
    assert not any(s["kind"] in ("green", "cycle") for s in huge["scenarios"])


def test_project_validation_of_cycle_range_and_min_green():
    with pytest.raises(ValidationError):
        project(cycle_search_min_s=150, cycle_search_max_s=100)
    with pytest.raises(ValidationError):
        project(min_green_s=0)
    with pytest.raises(ValidationError):
        project(min_green_s=61)


def test_pipeline_uses_entered_min_green_and_warns_about_defaults():
    ix = four_leg()
    st = run(ReportState(project=project(), detailed_intersections=[ix], background_growth_rate=0.02))
    assert any("탐색 조건이 기본값" in w for w in st.warnings)
    st2 = run(ReportState(project=project(min_green_s=15, cycle_search_min_s=90, cycle_search_max_s=150), detailed_intersections=[ix],
                          background_growth_rate=0.02))
    assert any("탐색 조건(입력값): 최소 녹색시간 15초" in w for w in st2.warnings)


# ── 설계속도 직접 입력 ──
def test_entered_design_speed_beats_road_class():
    assert DC.design_speed_for("arterial", 40) == (40, "설계속도 40km/h(입력값)")
    text, d = DC.left_lane_note(150, 120, 3.0, 5, "arterial", 60)
    assert d["design_speed"] == 60 and d["speed_assumed"] is False and "60km/h(입력값)" in text


def test_design_speed_value_must_be_a_table_speed():
    with pytest.raises(ValidationError):
        A(name="x", design_speed_kph=45)


# ── 보고서·화면 ──
def test_report_appendix_lists_rate_basis_and_facilities():
    st = run(ReportState(project=project(rate_basis="evidence", rate_overrides=RateOverrides(person_trips_per_household=4.0, source="자체 조사")),
                         detailed_intersections=[four_leg()], background_growth_rate=0.01))
    buf = io.BytesIO()
    build_docx(st).save(buf)
    doc = Document(io.BytesIO(buf.getvalue()))
    text = "\n".join(p.text for p in doc.paragraphs)
    cells = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "원단위 근거" in text and "tia.molit.go.kr" in text and "직접 입력한 원단위 출처: 자체 조사" in text
    assert "세대당 일 발생" in cells and "조사방법" in cells


def test_provisional_report_says_so_in_appendix():
    st = run(ReportState(project=project()))
    buf = io.BytesIO()
    build_docx(st).save(buf)
    text = "\n".join(p.text for p in Document(io.BytesIO(buf.getvalue())).paragraphs)
    assert "원단위 근거: 임시값(근거 자료 없음)" in text


def test_wizard_has_input_fields_and_sends_them():
    c = TestClient(main.app)
    html, js = c.get("/app").text, c.get("/static/wizard.js").text
    for fid in ("ro_trips", "ro_car", "ro_ami", "ro_amo", "ro_pmi", "ro_pmo", "ro_src", "mingreen", "cmin", "cmax"):
        assert f'id="{fid}"' in html, fid
    for key in ("rate_overrides", "min_green_s", "cycle_search_min_s", "cycle_search_max_s", "design_speed_kph", "dp-dspd"):
        assert key in js, key
