import asyncio
import copy
import io

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app import hcm_stages as HS
from app import main
from app.facts import build_facts, verify_text
from app.hcm_signal import DetailedApproach, DetailedIntersection, Phase, analyze_detailed
from app.pipeline import TIAPipeline
from app.schemas import ProjectInput
from app.state import ReportState
from app.storage import Database, LlmRunLog, SqliteJobStore
from test_hcm_signal import example_intersection


def make_detailed(share=True) -> DetailedIntersection:
    """편람 예제 EB 접근로 + 사업 교통량 배분."""
    ix = example_intersection(initial_queue={}, coordinated=False)
    if share:
        a = ix.approaches[0].model_copy(update={"project_share_left": 0.2, "project_share_through": 0.3,
                                                "project_share_right": 0.1})
        ix = ix.model_copy(update={"approaches": [a]})
    return ix


def run(state: ReportState) -> ReportState:
    return asyncio.run(TIAPipeline().run(state))


def state_with(ix, growth=0.02) -> ReportState:
    return ReportState(project=ProjectInput(name="t", address="서울", households=1500, gross_floor_area_m2=180_000),
                       detailed_intersections=[ix], background_growth_rate=growth)


# ── 파이프라인 ──
def test_detailed_intersection_flows_through_pipeline():
    st = run(state_with(make_detailed()))
    name = "A도로×B도로"
    v = st.los[name]
    assert v["engine"] == "hcm_detailed" and v["critical_vc"] > 0
    assert {r["approach"] for r in v["results"]} == {"EB 공용LT", "EB 실질RT"}
    assert set(st.stages[name]) == {1, 3}
    s1 = st.stages[name][1]
    assert set(s1) == {"without", "with", "improved", "delay_reduction", "notes", "scenarios"}
    assert "los.intersections" in st.sections and "demand.los_three_stage" in st.sections
    assert any("운영분석 절차" in w for w in st.warnings) and set(st.needs_input) <= {"project.unit_types", "project.planned_parking_spaces"}  # 주차 입력만 남음


def test_stage_ordering_with_project_and_growth():
    st = run(state_with(make_detailed()))
    s = st.stages["A도로×B도로"]
    assert s[3]["without"]["avg_delay"] > s[1]["without"]["avg_delay"] > 0  # 증가율 반영
    assert s[1]["with"]["avg_delay"] > s[1]["without"]["avg_delay"]  # 사업 교통량이 지체를 키움
    assert s[1]["improved"]["avg_delay"] <= s[1]["with"]["avg_delay"] + 1e-9


def test_missing_growth_and_shares_are_flagged():
    st = run(state_with(make_detailed(share=False), growth=None))
    assert {"demand.background_growth_rate", "demand.project_share"} <= set(st.needs_input)
    assert any("이동류별 사업 교통량 배분율 미입력" in w for w in st.warnings)


def test_simple_and_detailed_can_coexist_but_names_must_differ():
    from app.schemas import Approach
    from app.state import IntersectionInput
    simple = IntersectionInput(name="B교차로", cycle=100, approaches=[
        Approach(name="N", volume=300, saturation_flow=1800, green_time=40)])
    st = state_with(make_detailed())
    st.intersections = [simple]
    out = run(st)
    assert {"A도로×B도로", "B교차로"} <= set(out.los) and out.los["B교차로"].get("engine") is None
    assert any("간이 분석" in w for w in out.warnings) and any("운영분석 절차" in w for w in out.warnings)
    st2 = state_with(make_detailed())
    st2.intersections = [simple.model_copy(update={"name": "A도로×B도로"})]
    with pytest.raises(ValueError, match="중복"):
        run(st2)


# ── 3단계 구성요소 ──
def test_scale_and_add_project_volume():
    ix = make_detailed()
    s = HS.scale_intersection(ix, 1.1)
    assert s.approaches[0].v_through == pytest.approx(660) and s.approaches[0].opposing_through == pytest.approx(660)
    w = HS.add_project_volume(s, 100)
    a = w.approaches[0]
    assert a.v_left == pytest.approx(99 + 20) and a.v_through == pytest.approx(660 + 30) and a.v_right == pytest.approx(352 + 10)
    assert ix.approaches[0].v_through == 600  # 원본 불변


def test_reallocate_phase_greens_keeps_total_and_minimum():
    ix = DetailedIntersection(name="t", cycle=100, phf=1.0, phases=[Phase(green=20), Phase(green=60)],
                              approaches=[DetailedApproach(name="N", lanes=2, v_through=1500, phase=0),
                                          DetailedApproach(name="E", lanes=2, v_through=300, phase=1)])
    res = analyze_detailed(ix)
    new = HS.reallocate_phase_greens(ix, res.phase_y)
    assert sum(p.green for p in new.phases) == pytest.approx(80)
    assert new.phases[0].green > 20 and new.phases[1].green < 60  # 혼잡한 현시에 녹색 이동
    assert new.phases[0].yellow == 3 and new.cycle == 100  # 주기·황색 고정
    assert analyze_detailed(new).delay < res.delay  # 실제로 지체 감소
    squeezed = HS.reallocate_phase_greens(ix, {0: 1.0, 1: 0.001}, min_green=7)  # 극단적 비율 → 최소 녹색 보장
    assert squeezed.phases[1].green == pytest.approx(7) and squeezed.phases[0].green == pytest.approx(73)
    with pytest.raises(ValueError, match="최소 녹색"):
        HS.reallocate_phase_greens(ix, {0: 1, 1: 1}, min_green=50)


def test_phases_without_input_traffic_keep_their_green():
    """입력 없는 현시의 녹색을 빼앗아 '개선'을 만들어 내지 않는다(회귀: 접근로 1개만 입력했을 때 33초 감소로 표시됨)."""
    ix = DetailedIntersection(name="t", cycle=120, phf=1.0,
                              phases=[Phase(green=45), Phase(green=20), Phase(green=46)],
                              approaches=[DetailedApproach(name="EB", lanes=2, v_through=900, phase=0)])
    res = analyze_detailed(ix)
    assert set(res.phase_y) == {0}
    assert HS.reallocate_phase_greens(ix, res.phase_y) == ix  # 변경 없음
    two = {0: 0.4, 1: 0.2}  # 현시 2(인덱스 2)는 입력 없음 → 현시 0·1끼리만 재배분, 합 65 유지
    new = HS.reallocate_phase_greens(ix, two)
    assert new.phases[2].green == 46 and new.phases[0].green + new.phases[1].green == pytest.approx(65)


def test_partial_input_gives_no_fake_improvement_and_warns():
    st = run(state_with(make_detailed()))  # 3현시 중 EB(현시 1)만 입력
    s = st.stages["A도로×B도로"]
    for y in (1, 3):
        assert s[y]["delay_reduction"] == pytest.approx(0.0)
        assert s[y]["improved"]["avg_delay"] == pytest.approx(s[y]["with"]["avg_delay"])
    assert any("현시 2, 3에는 입력된 접근로가 없어" in w for w in st.warnings)


def test_summary_has_same_shape_as_simple_summary():
    ix = make_detailed()
    s = HS.summarize(ix, analyze_detailed(ix))
    assert {"avg_delay", "grade", "max_vc", "results", "greens", "volumes"} <= set(s)
    assert s["greens"] == {"현시1": 45.0, "현시2": 20.0, "현시3": 46.0}
    assert s["volumes"] == {"EB 좌": 90, "EB 직": 600, "EB 우": 320}


# ── 환각 점검: 편람 엔진 수치는 인용 가능, 지어낸 수치는 거부 ──
def test_facts_accept_engine_numbers_and_reject_invented():
    st = run(state_with(make_detailed()))
    f = build_facts(st)
    g = st.los["A도로×B도로"]["results"][0]
    ok = f"EB 공용LT 차로군은 포화교통류율 {g['saturation']:.0f}대/시, 교통량 {g['volume']:.0f}대/시, 지체 {g['delay']:.1f}초/대입니다."
    assert verify_text(ok, f) == []
    assert verify_text("포화교통류율은 9999대/시입니다.", f) != []


# ── 문서 ──
def test_docx_lists_lane_groups_and_detailed_basis(tmp_path):
    from app.docx_export import export_docx
    st = run(state_with(make_detailed()))
    d = Document(export_docx(st, tmp_path / "d.docx"))
    cells = [c.text for t in d.tables for r in t.rows for c in r.cells]
    assert "EB 공용LT" in cells and "EB 실질RT" in cells and "교차로 전체" in cells
    body = "\n".join(p.text for p in d.paragraphs)
    assert "편람 제8장 운영분석 절차" in body and "간이 입력 교차로" not in body


# ── API ──
DETAIL_PAYLOAD = {
    "project": {"name": "T", "address": "서울", "households": 1500, "gross_floor_area_m2": 180000},
    "background_growth_rate": 0.02,
    "detailed_intersections": [{
        "name": "A", "cycle": 120, "phf": 0.95, "peak": "pm",
        "phases": [{"green": 45, "yellow": 3}, {"green": 20, "yellow": 3}, {"green": 46, "yellow": 3}],
        "approaches": [{
            "name": "EB", "topology": "four_way", "left_case": 6, "lanes": 3, "v_left": 90, "v_through": 600,
            "v_right": 320, "opposing_through": 600, "left_radius_m": 12, "lane_width_m": 3.3, "heavy_pct": 5,
            "entering_vph": 23, "exiting_vph": 20, "bus_stops_vph": 11, "bus_distance_m": 30, "bus_class": "medium",
            "parking_allowed": True, "parking_vph": 10, "ped_per_hour": 400, "ped_green_s": 40, "phase": 0,
            "project_share_left": 0.2, "project_share_through": 0.3, "project_share_right": 0.1}]}],
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    db = Database(tmp_path / "h.db")
    monkeypatch.setattr(main, "store", SqliteJobStore(db))
    monkeypatch.setattr(main, "limiter", LlmRunLog(db))
    return TestClient(main.app)


def test_api_accepts_detailed_intersections(client):
    r = client.post("/api/analyze", json=DETAIL_PAYLOAD)
    assert r.status_code == 200
    j = r.json()
    assert j["los"]["A"]["engine"] == "hcm_detailed" and set(j["stages"]["A"]) == {"1", "3"}
    assert client.get(j["download_url"]).status_code == 200
    doc = Document(io.BytesIO(client.get(j["download_url"]).content))
    assert any("편람 제8장 운영분석 절차" in p.text for p in doc.paragraphs)


@pytest.mark.parametrize("mutate,expect", [
    (lambda p: p["detailed_intersections"][0]["approaches"][0].update(project_share_left=0.9, project_share_through=0.5), "100%"),
    (lambda p: p["detailed_intersections"][0]["approaches"][0].update(lanes=9), "차로 수"),
    (lambda p: p["detailed_intersections"][0].update(phases=[{"green": 45, "yellow": 3}] * 9, cycle=500), "현시는 최대 8개"),
])
def test_api_semantic_validation_for_detailed(client, mutate, expect):
    p = copy.deepcopy(DETAIL_PAYLOAD)
    mutate(p)
    r = client.post("/api/analyze", json=p)
    assert r.status_code == 422 and expect in r.json()["detail"]


@pytest.mark.parametrize("mutate,expect", [
    (lambda p: p["detailed_intersections"][0].update(cycle=60), "신호주기"),
    (lambda p: p["detailed_intersections"][0]["approaches"][0].update(phase=7), "현시 번호"),
    (lambda p: p["detailed_intersections"][0]["approaches"][0].update(opposing="ZZ"), "맞은편 접근로"),
    (lambda p: p["detailed_intersections"][0]["approaches"][0].update(left_case=1, left_phase=None), "left_phase"),
])
def test_ui_reports_model_validation_errors_readably(client, mutate, expect):
    p = copy.deepcopy(DETAIL_PAYLOAD)
    mutate(p)
    r = client.post("/ui/analyze", json=p)
    assert r.status_code == 422 and "입력을 확인해 주세요" in r.text and expect in r.text


def test_duplicate_names_across_modes_rejected_by_api(client):
    p = copy.deepcopy(DETAIL_PAYLOAD)
    p["intersections"] = [{"name": "A", "cycle": 100, "approaches": [
        {"name": "N", "volume": 100, "saturation_flow": 1800, "green_time": 40}]}]
    r = client.post("/api/analyze", json=p)
    assert r.status_code == 422 and "중복" in r.json()["detail"]


def test_misspelled_initial_queue_key_is_reported_not_silently_ignored():
    ix = example_intersection(initial_queue={"공용LT": 40, "공용TL": 10})  # 오타
    st = run(state_with(ix.model_copy(update={"approaches": [ix.approaches[0]]})))
    assert any("공용TL" in w and "적용되지 않음" in w for w in st.warnings)
    assert not any("'공용LT'" in w and "적용되지 않음" in w for w in st.warnings)


def test_api_accepts_initial_queue_and_coordination_matching_manual(client):
    p = copy.deepcopy(DETAIL_PAYLOAD)
    a = p["detailed_intersections"][0]["approaches"][0]
    a.update(coordinated=True, link_length_m=400, speed_kph=50, offset_s=10, initial_queue={"공용LT": 40},
             project_share_left=0, project_share_through=0, project_share_right=0)
    p["background_growth_rate"] = 0.0
    j = client.post("/api/analyze", json=p).json()
    by = {r["approach"]: r for r in j["los"]["A"]["results"]}
    assert by["EB 공용LT"]["delay"] == pytest.approx(43.5, abs=0.8) and by["EB 실질RT"]["delay"] == pytest.approx(30.2, abs=0.5)
    assert j["los"]["A"]["avg_delay"] == pytest.approx(40.4, abs=0.7)  # 편람 예제 접근로 지체


# ── 장래 단계의 초기 대기차량 (편람 p.255 권장 규칙 + 단계 간 일관성) ──
def example_with_queue(shares=True):
    ix = example_intersection()  # 공용LT Qb=40, 연동
    if shares:
        a = ix.approaches[0].model_copy(update={"project_share_left": 0.2, "project_share_through": 0.3,
                                                "project_share_right": 0.1})
        ix = ix.model_copy(update={"approaches": [a]})
    return ix


def test_queue_carried_only_to_same_group_when_future_vc_is_higher():
    base = example_with_queue(shares=False)
    up = HS.scale_intersection(base, 1.05)  # 교통량 증가 → V/c가 현황보다 큼 → 적용
    down = HS.scale_intersection(base, 0.5)  # V/c가 낮아짐 → 0으로 간주
    assert HS.carried_queues(base, up)["EB"] == {"공용LT": 40}
    assert HS.carried_queues(base, down)["EB"] == {}
    # 현황 자체(같은 교통량)는 'V/c가 더 크지 않으므로' 적용하지 않는다(현황 분석은 별도로 Qb 반영)
    assert HS.carried_queues(base, base)["EB"] == {}


def test_queue_not_transferred_when_group_classification_changes():
    base = example_with_queue()
    heavy = HS.add_project_volume(HS.scale_intersection(base, 1.06), 260)  # 분류가 '통합'/'실질LT' 등으로 바뀜
    labels = {g.label for g in analyze_detailed(heavy).groups}
    assert "공용LT" not in labels
    assert HS.carried_queues(base, heavy)["EB"] == {}  # 이전 규칙 없이 옮기지 않음 (옮기면 d3가 수백 초로 폭주)


def test_inconsistent_stage_classification_zeroes_queue_in_all_stages_and_notes_it():
    base = example_with_queue()
    res = HS.analyze_stages_detailed(base, [1, 3], 0.02, 260)
    for y, s in res.items():
        assert s["notes"] and "Qb=0" in s["notes"][0]
        # 아무 단계에도 폭주한 지체가 없고, 사업 교통량 추가로 지체가 줄지 않는다(회귀: 40.8 → 22.2로 줄어 보이던 문제)
        assert s["with"]["avg_delay"] >= s["without"]["avg_delay"] - 1e-9
        assert max(r["delay"] for r in s["with"]["results"]) < 200


def test_growth_only_keeps_group_names_so_queue_applies_to_every_stage():
    base = example_with_queue(shares=False)
    res = HS.analyze_stages_detailed(base, [1], 0.05, 0)  # 사업 교통량 없음 → 분류 유지
    s = res[1]
    assert s["notes"] == []
    base_lt = next(r for r in summarize_base(base) if r["approach"] == "EB 공용LT")["delay"]
    lt = next(r for r in s["without"]["results"] if r["approach"] == "EB 공용LT")
    assert lt["delay"] > base_lt  # 성장 + Qb(d3) 반영으로 현황보다 큼


def summarize_base(ix):
    return HS.summarize(ix, analyze_detailed(ix))["results"]


def test_pipeline_warns_about_dropped_queue():
    st = run(state_with(example_with_queue()))
    assert any("초기 대기차량을 장래 단계에 적용하지 않음" in w and "준공 후 1년" in w for w in st.warnings)
    base_lt = st.los["A도로×B도로"]["results"][0]["delay"]
    assert base_lt == pytest.approx(42.8, abs=0.6)  # 현황 분석에는 Qb가 그대로 반영된다(편람 예제 43.5)
