"""Planning 정확도: 복합용도(Swa)·증축·용도변경·약식 평가(지침 제23조)."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.agents.planning import PlanningAgent
from app.eligibility import assess_project, use_table
from app.pipeline import TIAPipeline
from app.schemas import Approach, ProjectInput, UseArea
from app.service import ServiceError, validate_project
from app.state import IntersectionInput, ReportState
from app.storage import Database, LlmRunLog, SqliteJobStore


def proj(**kw):
    base = dict(name="t", address="서울", households=500)
    base.update(kw)
    return ProjectInput(**base)


def run_planning(**kw):
    return asyncio.run(PlanningAgent().run(ReportState(project=proj(**kw))))


def exp(added, existing=40000, **kw):
    return proj(project_kind="expansion", existing_gfa_m2=existing, expansion_gfa_m2=added, existing_evaluated=True, **kw)


# ── 복합용도 ──

def test_seoul_use_table_matches_ordinance():
    t = use_table()
    assert t["apartment"]["threshold_m2"] == 50000
    assert t["office_general"]["threshold_m2"] == 20000 and t["retail_mall"]["threshold_m2"] == 3000
    assert t["zoo"]["metric"] == "site"


def test_mixed_use_swa_boundary():
    # 30,000/50,000 = 0.6, 일반업무 8,000/20,000 = 0.4 → Swa 정확히 10,000 → 대상
    e = assess_project(proj(gross_floor_area_m2=30000, other_uses=[UseArea(use="office_general", area_m2=8000)]))
    assert e.eligible is True and e.mixed_use and e.swa == pytest.approx(10000)
    assert e.multiple == pytest.approx(1.0)
    e = assess_project(proj(gross_floor_area_m2=30000, other_uses=[UseArea(use="office_general", area_m2=7900)]))
    assert e.eligible is False and e.swa < 10000


def test_mixed_use_makes_uses_below_their_own_thresholds_eligible_together():
    e = assess_project(proj(gross_floor_area_m2=40000, other_uses=[UseArea(use="retail_mall", area_m2=700)]))
    assert e.eligible is True  # 0.8 + 0.2333 = 1.033, 각각은 기준 미만


def test_single_apartment_swa_equals_area_over_threshold():
    e = assess_project(proj(gross_floor_area_m2=100000))
    assert e.swa == pytest.approx(20000) and e.multiple == pytest.approx(2.0) and not e.mixed_use


def test_unknown_use_rejected():
    with pytest.raises(ValueError):
        assess_project(proj(gross_floor_area_m2=30000, other_uses=[UseArea(use="nope", area_m2=10)]))
    with pytest.raises(ServiceError):
        validate_project(proj(other_uses=[UseArea(use="nope", area_m2=10)]))
    with pytest.raises(ServiceError):
        validate_project(proj(other_uses=[UseArea(use="apartment", area_m2=10)]))
    with pytest.raises(ServiceError):
        validate_project(proj(other_uses=[UseArea(use="res2", area_m2=10), UseArea(use="res2", area_m2=20)]))


# ── 증축·용도변경 ──

def test_expansion_thirty_percent_rule():
    e = assess_project(exp(12000))  # 정확히 30%는 '초과'가 아님
    assert e.eligible is False and any("30% 이하" in n for n in e.notes)
    e = assess_project(exp(12001))
    assert e.eligible is True and e.gross_floor_area_m2 == pytest.approx(52001)  # 준공 면적 + 증축 부분 합산
    assert e.multiple == pytest.approx(52001 / 50000)


def test_expansion_sums_prior_expansions_and_threshold_trigger():
    assert assess_project(exp(6000, prior_expansion_gfa_m2=6001)).eligible is True  # 합산 12,001 > 30%
    assert assess_project(exp(50000, existing=400000)).eligible is True  # 12.5%지만 증축 규모가 대상규모 이상


def test_expansion_missing_inputs_is_undetermined():
    e = assess_project(proj(project_kind="expansion", existing_gfa_m2=40000))
    assert e.eligible is None and e.multiple is None


def test_expansion_of_never_evaluated_building_compares_total_with_threshold():
    base = dict(project_kind="expansion", existing_gfa_m2=45000, existing_evaluated=False)
    assert assess_project(proj(expansion_gfa_m2=4000, **base)).eligible is False
    e = assess_project(proj(expansion_gfa_m2=5000, **base))
    assert e.eligible is True and any("5.바" in n for n in e.notes)


def test_use_change_uses_converted_area():
    e = assess_project(proj(project_kind="use_change", gross_floor_area_m2=55000))
    assert e.eligible is True and any("용도변경" in n for n in e.notes)


# ── 약식 평가 (지침 제23조) ──

def test_abbreviated_district_case():
    ab = assess_project(proj(gross_floor_area_m2=60000, floors=15, in_evaluated_district=True,
                             request_abbreviated=True)).abbreviated
    assert ab.possible and ab.cases == ["district"] and ab.complex_only and ab.applied
    ab = assess_project(proj(gross_floor_area_m2=60000, floors=15, in_evaluated_district=True)).abbreviated
    assert ab.possible and not ab.applied  # 지침상 '할 수 있다' — 선택하지 않으면 적용하지 않음


def test_abbreviated_blocked_by_committee_conditions():
    common = dict(in_evaluated_district=True, request_abbreviated=True)
    for floors, gfa in ((21, 60000), (10, 100000)):
        ab = assess_project(proj(gross_floor_area_m2=gfa, floors=floors, **common)).abbreviated
        assert ab.possible is False and not ab.applied and "제13조의4" in " ".join(ab.reasons)
    mixed = proj(gross_floor_area_m2=60000, floors=10, in_evaluated_district=True,
                 other_uses=[UseArea(use="retail_shop", area_m2=500)])
    assert assess_project(mixed).abbreviated.possible is False  # 판매시설 포함


def test_abbreviated_needs_inputs_instead_of_guessing():
    assert assess_project(proj(gross_floor_area_m2=60000, in_evaluated_district=True)).abbreviated.possible is None  # 층수 없음
    assert assess_project(proj(gross_floor_area_m2=60000, floors=10)).abbreviated.possible is None  # 사업지구 여부 없음
    assert assess_project(proj(gross_floor_area_m2=60000, floors=10, in_evaluated_district=False)).abbreviated.possible is False


def test_abbreviated_not_considered_when_not_eligible():
    e = assess_project(proj(gross_floor_area_m2=30000, floors=10, in_evaluated_district=True, request_abbreviated=True))
    assert e.eligible is False and not e.abbreviated.applied


def test_abbreviated_change_case_seven_years_and_range():
    # 증축 40%(변경심의 대상), 대상규모 미만 → 7년이 지나도 가능(나목)
    e = assess_project(exp(16000, years_since_completion=9, in_evaluated_district=False))
    assert e.eligible is True and e.abbreviated.possible
    assert e.abbreviated.cases == ["change"] and not e.abbreviated.complex_only
    # 증축이 대상규모 이상: 7년 경과면 불가, 미경과면 가능(주의 문구), 연수 미입력이면 판정 불가
    big = dict(existing=400000, in_evaluated_district=False)
    assert assess_project(exp(50000, years_since_completion=8, **big)).abbreviated.possible is False
    ok = assess_project(exp(50000, years_since_completion=6.9, **big)).abbreviated
    assert ok.possible and any("주의" in r for r in ok.reasons)
    assert assess_project(exp(50000, **big)).abbreviated.possible is None
    # 기존 사업이 평가를 받지 않았다면 제4호 불가
    e = assess_project(proj(project_kind="expansion", existing_gfa_m2=40000, expansion_gfa_m2=16000, existing_evaluated=False,
                            years_since_completion=2, in_evaluated_district=False))
    assert e.abbreviated.possible is False


# ── Planning·파이프라인·API ──

def test_planning_applies_abbreviated_scope_and_texts():
    st = run_planning(gross_floor_area_m2=60000, floors=15, in_evaluated_district=True, request_abbreviated=True)
    assert st.scope["target_years"] == [1] and st.scope["spatial_mode"] == "site_adjacent" and st.scope["abbreviated"]
    assert "대지와 직접 접하거나 연결되는 도로의 교차로" in st.sections["scope.spatial"] and "약식" in st.sections["scope.target_years"]
    assert any("약식 교통영향평가(지침 제23조)" in w for w in st.warnings)


def test_planning_offers_but_does_not_apply_abbreviated_by_default():
    st = run_planning(gross_floor_area_m2=60000, floors=15, in_evaluated_district=True)
    assert st.scope["target_years"] == [1, 3] and "abbreviated" not in st.scope
    assert any("적용 가능" in w for w in st.warnings)
    st = run_planning(gross_floor_area_m2=60000, floors=30, in_evaluated_district=True, request_abbreviated=True)
    assert st.scope["target_years"] == [1, 3] and any("적용하지 않음" in w for w in st.warnings)


def test_planning_expansion_missing_areas_needs_input():
    assert "project.expansion_areas" in run_planning(project_kind="expansion").needs_input


def test_planning_expansion_warns_households_basis():
    st = run_planning(project_kind="expansion", existing_gfa_m2=40000, expansion_gfa_m2=16000, existing_evaluated=True)
    assert any("증축으로 늘어나는 세대수" in w for w in st.warnings)
    assert "증축" in st.sections["intro.overview"] and "56,000" not in st.sections["intro.overview"]


def test_abbreviated_pipeline_analyzes_only_one_target_year():
    s = ReportState(
        project=ProjectInput(name="t", address="서울", households=300, gross_floor_area_m2=60000, floors=15,
                             in_evaluated_district=True, request_abbreviated=True),
        intersections=[IntersectionInput(name="A", cycle=120, approaches=[
            Approach(name="N", volume=400, saturation_flow=1800, green_time=40),
            Approach(name="E", volume=500, saturation_flow=1800, green_time=40)])])
    st = asyncio.run(TIAPipeline().run(s))
    assert list(st.stages["A"].keys()) == [1]


def test_api_accepts_mixed_use_and_form_lists_uses(monkeypatch, tmp_path):
    db = Database(tmp_path / "t.db")
    monkeypatch.setattr(main, "store", SqliteJobStore(db))
    monkeypatch.setattr(main, "limiter", LlmRunLog(db))
    monkeypatch.setattr(main, "throttle", auth.LoginThrottle())
    c = TestClient(main.app)
    page = c.get("/").text
    assert "복합용도" in page and "office_general" in page and "retail_mall" in page  # 용도 목록은 JSON으로 내려감
    body = {"project": {"name": "복합", "address": "서울", "households": 400, "gross_floor_area_m2": 30000, "floors": 12,
                        "other_uses": [{"use": "office_general", "area_m2": 8000}]}}
    r = c.post("/api/analyze", json=body)
    assert r.status_code == 200
    e = r.json()["eligibility"]
    assert e["mixed_use"] and e["eligible"] and e["swa"] == pytest.approx(10000)
    bad = c.post("/api/analyze", json={"project": {**body["project"], "other_uses": [{"use": "nope", "area_m2": 5}]}})
    assert bad.status_code == 422
    ui = c.post("/ui/analyze", json=body)
    assert ui.status_code == 200 and "복합용도" in ui.text and "Swa" in ui.text
