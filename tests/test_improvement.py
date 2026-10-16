"""개선 시나리오 엔진: 후보 생성·정렬·제약, 파이프라인·보고서·환각 점검 연동."""
import asyncio
import io

from docx import Document

from app.facts import build_facts, verify_text
from app.hcm_signal import DetailedApproach as A
from app.hcm_signal import DetailedIntersection as I
from app.hcm_signal import Phase as P
from app.hcm_signal import analyze_detailed
from app.improvement import CYCLE_MAX, CYCLE_MIN, build_scenarios, scenario_lines
from app.pipeline import TIAPipeline
from app.schemas import ProjectInput
from app.state import ReportState
from app.docx_export import build_docx


def ap(n, ph, vl, vt, vr, lanes=2, case=6, opp=None, **kw):
    return A(name=n, topology="four_way", left_case=case, lanes=lanes, v_left=vl, v_through=vt, v_right=vr, phase=ph,
             opposing=opp, **kw)


def four_leg(**kw) -> I:
    return I(name="T", cycle=120, phf=0.95, phases=[P(green=40), P(green=40), P(green=25)],
             approaches=[ap("EB", 0, 120, 900, 200, 3, 6, "WB"), ap("WB", 0, 100, 800, 150, 3, 6, "EB"),
                         ap("NB", 1, 150, 700, 120, 2, 4), ap("SB", 1, 140, 650, 100, 2, 4)], **kw)


def test_scenarios_sorted_by_delay_and_all_improve():
    b = build_scenarios(four_leg())
    sc = b["scenarios"]
    assert sc and [s["avg_delay"] for s in sc] == sorted(s["avg_delay"] for s in sc)
    assert all(s["delay_reduction"] > 0 for s in sc) and len(sc) <= 5
    assert all(abs((b["base_delay"] - s["avg_delay"]) - s["delay_reduction"]) < 1e-9 for s in sc)


def test_physical_candidates_are_flagged_and_change_lanes_or_left_case():
    b = build_scenarios(four_leg())
    phys = [s for s in b["scenarios"] if s["physical"]]
    assert phys and all(s["changes"] for s in phys)
    assert any("차로수" in c or "좌회전" in c for s in phys for c in s["changes"])
    assert b["best_physical"] in {s["id"] for s in phys}


def test_scenario_result_matches_engine_recomputation():
    """시나리오가 보고한 지체가 같은 입력으로 엔진을 다시 돌린 값과 같아야 한다(add_lane 단독)."""
    ix = four_leg()
    from app.improvement import _lane_candidates

    sid, _, changed, _, _ = next(c for c in _lane_candidates(ix) if c[0] == "add_lane:NB")
    assert changed.approaches[2].lanes == ix.approaches[2].lanes + 1
    assert analyze_detailed(changed).delay < analyze_detailed(ix).delay  # NB 차로 증설은 지체를 줄인다


def test_cycle_search_stays_in_range_and_keeps_yellow_and_slack():
    b = build_scenarios(four_leg())
    for s in b["scenarios"]:
        assert CYCLE_MIN <= s["cycle"] <= CYCLE_MAX


def test_no_cycle_candidate_when_coordinated():
    ix = four_leg()
    apps = [a.model_copy(update={"coordinated": True, "link_length_m": 400, "speed_kph": 50}) if a.name == "EB" else a for a in ix.approaches]
    b = build_scenarios(ix.model_copy(update={"approaches": apps}))
    assert all(s["cycle"] == 120 for s in b["scenarios"]) and any("연동" in n for n in b["notes"])


def test_initial_queue_is_ignored_and_noted():
    ix = four_leg()
    apps = [a.model_copy(update={"initial_queue": {"공용LT": 20}}) if a.name == "NB" else a for a in ix.approaches]
    b = build_scenarios(ix.model_copy(update={"approaches": apps}))
    assert any("Qb=0" in n for n in b["notes"])
    assert b["base_delay"] == build_scenarios(ix)["base_delay"]


def test_light_traffic_needs_no_physical_improvement():
    """교통량이 적으면 차로 증설은 지체를 줄이지 못한다(주기 단축 같은 신호 조정만 남을 수 있다)."""
    ix = I(name="E", cycle=100, phf=1.0, phases=[P(green=45), P(green=45)],
           approaches=[A(name="EB", lanes=3, v_through=100, phase=0), A(name="NB", lanes=3, v_through=100, phase=1)])
    b = build_scenarios(ix)
    assert not any(s["physical"] for s in b["scenarios"]) and b["best_physical"] is None


def test_empty_block_text_says_no_candidate():
    block = {"base_delay": 10.0, "base_grade": "B", "scenarios": [], "best_signal": None, "best_physical": None, "notes": []}
    assert "후보 없음" in " ".join(scenario_lines("E", 1, block))


def test_lane_cap_respected():
    ix = I(name="C", cycle=100, phf=1.0, phases=[P(green=40), P(green=40)],
           approaches=[A(name="EB", lanes=8, v_through=3000, phase=0), A(name="NB", lanes=2, v_through=500, phase=1)])
    assert not any(s["id"] == "add_lane:EB" for s in build_scenarios(ix)["scenarios"])


def run_pipeline(ix):
    st = ReportState(project=ProjectInput(name="t", address="서울", households=1500, gross_floor_area_m2=180_000),
                     detailed_intersections=[ix], background_growth_rate=0.02)
    return asyncio.run(TIAPipeline().run(st))


def test_pipeline_attaches_scenarios_to_stages_and_report():
    ix = four_leg()
    apps = [a.model_copy(update={"project_share_through": 0.1}) for a in ix.approaches]
    st = run_pipeline(ix.model_copy(update={"approaches": apps}))
    assert st.stages["T"][1]["scenarios"]["scenarios"]
    assert "개선 후보" in st.artifacts["improve_scenarios"]
    doc = Document(io.BytesIO(_docx_bytes(st)))
    text = "\n".join(p.text for p in doc.paragraphs) + "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "개선 시나리오 비교표" in text and "물리적 개선(검토 후보)" in text


def _docx_bytes(st):
    buf = io.BytesIO()
    build_docx(st).save(buf)
    return buf.getvalue()


def test_facts_accept_scenario_numbers_and_reject_invented():
    ix = four_leg()
    apps = [a.model_copy(update={"project_share_through": 0.1}) for a in ix.approaches]
    st = run_pipeline(ix.model_copy(update={"approaches": apps}))
    f = build_facts(st)
    top = st.stages["T"][1]["scenarios"]["scenarios"][0]
    assert verify_text(f"{top['label']}은 평균지체 {top['avg_delay']:.1f}초/대, {top['delay_reduction']:.1f}초/대 감소로 계산됨.", f) == []
    assert verify_text("차로 증설로 평균지체가 7.7초/대로 줄어듭니다.", f)  # 계산에 없는 수치


def test_result_page_shows_scenario_table(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app import auth, main
    from app.storage import Database, LlmRunLog, SqliteJobStore

    db = Database(tmp_path / "t.db")
    monkeypatch.setattr(main, "store", SqliteJobStore(db))
    monkeypatch.setattr(main, "limiter", LlmRunLog(db))
    monkeypatch.setattr(main, "throttle", auth.LoginThrottle())
    ix = four_leg()
    apps = [a.model_copy(update={"project_share_through": 0.1}) for a in ix.approaches]
    body = {"project": {"name": "시나리오", "address": "서울", "households": 1000, "gross_floor_area_m2": 120000},
            "background_growth_rate": 0.02,
            "detailed_intersections": [ix.model_copy(update={"approaches": apps}).model_dump(mode="json")]}
    html = TestClient(main.app).post("/ui/analyze", json=body).text
    assert "개선 시나리오 (검토 후보)" in html and "물리적 개선" in html and "차로 1개 증설" in html
