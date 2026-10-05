import asyncio

import pytest

from app.agents.data import DataAgent
from app.agents.planning import PlanningAgent
from app.facts import build_facts, verify_text
from app.pipeline import TIAPipeline
from app.schemas import Approach, ProjectInput
from app.stages import (MEANINGFUL_REDUCTION, add_project_volume, analyze_stages, optimize_green,
                        scale_volumes)
from app.state import IntersectionInput, ReportState


def ap(name, v, g=40, share=0.0, s=1800):
    return Approach(name=name, volume=v, saturation_flow=s, green_time=g, project_share=share)


def test_scale_and_add_volume():
    a = [ap("N", 400, share=0.5), ap("E", 100, share=0.25)]
    s = scale_volumes(a, 1.1)
    assert s[0].volume == pytest.approx(440)
    p = add_project_volume(s, 200)
    assert p[0].volume == pytest.approx(540) and p[1].volume == pytest.approx(160)
    assert a[0].volume == 400  # 원본 불변


def test_optimize_green_keeps_total_and_is_proportional():
    a = [ap("N", 600, g=30), ap("E", 300, g=60)]  # v/s 비 2:1, 총 90초
    o = optimize_green(a)
    assert sum(x.green_time for x in o) == pytest.approx(90)
    assert o[0].green_time == pytest.approx(60) and o[1].green_time == pytest.approx(30)


def test_optimize_green_respects_minimum_and_total():
    a = [ap("N", 900, g=40), ap("E", 10, g=40), ap("S", 10, g=30)]
    o = optimize_green(a, min_green=7)
    assert all(x.green_time >= 7 - 1e-9 for x in o)
    assert sum(x.green_time for x in o) == pytest.approx(110)


def test_optimize_green_zero_volume_and_infeasible():
    a = [ap("N", 0, g=40), ap("E", 0, g=40)]
    assert [x.green_time for x in optimize_green(a)] == [40, 40]
    with pytest.raises(ValueError):
        optimize_green([ap("N", 10, g=5), ap("E", 10, g=5)], min_green=7)


def test_stage_ordering_growth_project_improvement():
    approaches = [ap("N", 500, g=25, share=0.5), ap("E", 300, g=55, share=0.2)]  # 녹색 배분이 어긋남
    res = analyze_stages(approaches, cycle=120, years=[1, 3], growth_rate=0.02, project_peak_total=200)
    for y in (1, 3):
        st = res[y]
        assert st["without"]["avg_delay"] < st["with"]["avg_delay"]  # 사업이 지체를 키움
        assert st["improved"]["avg_delay"] < st["with"]["avg_delay"]  # 재배분이 효과 있음
        assert st["delay_reduction"] >= MEANINGFUL_REDUCTION
    assert res[3]["without"]["avg_delay"] > res[1]["without"]["avg_delay"]  # 증가율 반영


def test_zero_growth_and_zero_share_means_all_stages_equal():
    a = [ap("N", 400), ap("E", 400)]
    res = analyze_stages(a, 120, [1], growth_rate=0.0, project_peak_total=300)
    st = res[1]
    assert st["without"]["avg_delay"] == pytest.approx(st["with"]["avg_delay"])


def make_state(growth=0.02, share=True, peak="pm"):
    ix = IntersectionInput(name="A교차로", cycle=120, peak=peak, approaches=[
        ap("N", 400, g=40, share=0.4 if share else 0), ap("E", 500, g=40, share=0.1 if share else 0)])
    st = ReportState(project=ProjectInput(name="t", address="서울", households=1500, gross_floor_area_m2=180_000),
                     intersections=[ix], background_growth_rate=growth)
    asyncio.run(PlanningAgent().run(st))
    return st


def test_data_agent_fills_three_stage_sections():
    st = make_state()
    asyncio.run(DataAgent().run(st))
    assert set(st.stages["A교차로"]) == {1, 3}
    assert "demand.without_project" in st.sections and "demand.los_three_stage" in st.sections
    assert "미시행" in st.sections["demand.los_three_stage"] and "개선 후" in st.sections["demand.los_three_stage"]
    assert set(st.needs_input) <= {"project.unit_types", "project.planned_parking_spaces"}  # 주차 입력만 남음


def test_missing_growth_and_share_are_flagged_not_silently_assumed():
    st = make_state(growth=None, share=False)
    asyncio.run(DataAgent().run(st))
    assert "demand.background_growth_rate" in st.needs_input
    assert "demand.project_share" in st.needs_input
    assert any("증가율 미입력" in w for w in st.warnings)
    assert any("배분율 미입력" in w for w in st.warnings)


def test_peak_selection_changes_project_load():
    am = make_state(peak="am")
    pm = make_state(peak="pm")
    asyncio.run(DataAgent().run(am))
    asyncio.run(DataAgent().run(pm))
    assert am.stages["A교차로"][1]["with"]["volumes"] != pm.stages["A교차로"][1]["with"]["volumes"]


def test_no_intersections_means_no_stages_and_asks_input():
    st = ReportState(project=ProjectInput(name="t", address="서울", households=100))
    asyncio.run(DataAgent().run(st))
    assert st.stages == {} and "los.intersections" in st.needs_input
    assert "demand.los_three_stage" not in st.sections


def test_facts_accept_stage_numbers_and_reject_invented_greens():
    st = make_state()
    asyncio.run(DataAgent().run(st))
    stage = st.stages["A교차로"][1]
    d = stage["improved"]["avg_delay"]
    green = next(iter(stage["improved"]["greens"].values()))
    f = build_facts(st)
    assert verify_text(f"개선 후 평균지체 {d:.1f}초/대, 녹색시간 {green:.1f}초로 조정", f) == []
    assert verify_text("녹색시간을 77초로 늘립니다.", f) != []


def test_pipeline_document_contains_three_stage_table_and_checklist_keys():
    st = asyncio.run(TIAPipeline().run(make_state()))
    assert "3단계 LOS 비교표" in st.document
    assert "demand.los_three_stage" not in st.reflection["missing"]
    assert "demand.without_project" not in st.reflection["missing"]
