import asyncio

import pytest

from app.agents.planning import PlanningAgent
from app.eligibility import assess_eligibility, load_thresholds, spatial_scope
from app.schemas import ProjectInput
from app.state import ReportState


def test_thresholds_file_has_sources_and_values():
    a = load_thresholds()["apartment"]
    assert a["seoul"]["threshold_m2"] == 50000
    assert a["national_urban_area"]["threshold_m2"] == 60000
    assert a["national_traffic_zone"]["threshold_m2"] == 90000
    assert all(a[k]["source"] for k in ("seoul", "national_urban_area", "national_traffic_zone"))


@pytest.mark.parametrize("area,eligible", [(49_999.9, False), (50_000, True), (80_000, True)])
def test_seoul_boundary(area, eligible):
    assert assess_eligibility(area).eligible is eligible


def test_unknown_area_is_undetermined_not_false():
    e = assess_eligibility(None)
    assert e.eligible is None and e.multiple is None


def test_multiple_and_spatial_tiers():
    assert assess_eligibility(100_000).multiple == 2.0
    assert spatial_scope(3.99) == {"radius_km": 1.0, "min_intersections": 4}
    assert spatial_scope(4) == {"radius_km": 1.5, "min_intersections": 8}
    assert spatial_scope(7.99) == {"radius_km": 1.5, "min_intersections": 8}
    assert spatial_scope(8) == {"radius_km": 2.0, "min_intersections": 12}


def test_committee_review_flag():
    assert assess_eligibility(120_000).committee_review_likely is True
    assert assess_eligibility(60_000, floors=25).committee_review_likely is True
    assert assess_eligibility(60_000, floors=15).committee_review_likely is False


def run_planning(**kw):
    st = ReportState(project=ProjectInput(name="t", address="서울", households=300, **kw))
    return asyncio.run(PlanningAgent().run(st))


def test_planning_below_threshold_warns():
    st = run_planning(gross_floor_area_m2=40_000)
    assert st.scope["eligibility"]["eligible"] is False
    assert any("미만" in w for w in st.warnings)
    assert "미해당" in st.sections["intro.reason_timing"]


def test_planning_large_project_uses_wider_scope():
    st = run_planning(gross_floor_area_m2=250_000)  # 5배
    assert st.scope["radius_km"] == 1.5 and st.scope["min_intersections"] == 8
    assert "spatial_provisional" not in st.scope
    assert "해당" in st.sections["intro.reason_timing"]


def test_planning_without_area_asks_for_input():
    st = run_planning()
    assert "project.gross_floor_area_m2" in st.needs_input
    assert st.scope["spatial_provisional"] is True
    assert "intro.reason_timing" not in st.sections
