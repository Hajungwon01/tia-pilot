"""결과 도표: 명세는 계산 결과만 사용, SVG·DOCX 렌더링."""
import asyncio
import re
import xml.etree.ElementTree as ET

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app import auth, main
from app.charts import (SERIES_COLORS, build_charts, chart_rows, docx_bar_rows, parking_chart, render_svg,
                        stage_charts, vc_charts)
from app.docx_export import export_docx
from app.pipeline import TIAPipeline
from app.schemas import Approach, ProjectInput, UnitType
from app.state import IntersectionInput, ReportState
from app.storage import Database, LlmRunLog, SqliteJobStore


def full_state(**proj_kw):
    p = ProjectInput(name="도표단지", address="서울", households=1000, gross_floor_area_m2=120000, floors=20,
                     unit_types=[UnitType(exclusive_area_m2=84, households=1000)], planned_parking_spaces=1500, **proj_kw)
    s = ReportState(project=p, background_growth_rate=0.02, intersections=[IntersectionInput(
        name="A교차로", cycle=120, approaches=[
            Approach(name="N", volume=400, saturation_flow=1800, green_time=40, project_share=0.4),
            Approach(name="E", volume=500, saturation_flow=1800, green_time=40, project_share=0.1)])])
    return asyncio.run(TIAPipeline().run(s))


@pytest.fixture(scope="module")
def st():
    return full_state()


def test_stage_chart_values_come_from_stage_results(st):
    spec = stage_charts(st)[0]
    assert [g["label"] for g in spec["groups"]] == ["준공 후 1년", "준공 후 3년"]
    for g, (y, res) in zip(spec["groups"], st.stages["A교차로"].items()):
        assert [b["value"] for b in g["bars"]] == [res["without"]["avg_delay"], res["with"]["avg_delay"], res["improved"]["avg_delay"]]
        assert all(b["text"].startswith(f"{b['value']:.1f}초") for b in g["bars"])
    assert spec["ymax"] >= max(b["value"] for g in spec["groups"] for b in g["bars"])
    bands = spec["bands"]  # LOS 등급 구간: 0에서 축 최댓값까지 빈틈없이 이어지고 등급 순서(A, B, ...)를 따른다
    assert bands[0]["lo"] == 0 and bands[-1]["hi"] == spec["ymax"] and bands[0]["label"] == "A"
    assert all(a["hi"] == b["lo"] or a["edge"] is None for a, b in zip(bands, bands[1:]))
    assert all(b["edge"] is None or b["edge"] < spec["ymax"] for b in bands)


def test_vc_and_parking_specs(st):
    vc = vc_charts(st)[0]
    assert [b["label"] for b in vc["bars"]] == [r["approach"] for r in st.los["A교차로"]["results"]]
    assert vc["ref"]["value"] == 1.0 and vc["xmax"] >= 1.0
    pk = parking_chart(st)[0]
    labels = [b["label"] for b in pk["bars"]]
    assert labels[:3] == ["법정 주차대수", "권장 상한(130%)", "계획 주차대수"] and "임시" in labels[3]
    assert pk["bars"][0]["value"] == 1120 and pk["bars"][1]["value"] == pytest.approx(1456)


def test_no_inputs_means_no_intersection_charts_but_parking_still_charts():
    s = asyncio.run(TIAPipeline().run(ReportState(project=ProjectInput(name="t", address="서울", households=500))))
    c = build_charts(s)
    assert c["vc"] == [] and c["stage"] == []
    assert c["parking"] == []  # 법정·계획이 없으면 수요 막대 하나뿐이라 비교 도표를 그리지 않음
    s = asyncio.run(TIAPipeline().run(ReportState(project=ProjectInput(
        name="t", address="서울", households=500, planned_parking_spaces=700))))
    assert [b["label"] for b in build_charts(s)["parking"][0]["bars"]][0] == "계획 주차대수"  # 법정 없이 계획·수요만 비교


def test_svg_is_well_formed_labeled_and_escaped(st):
    for spec in stage_charts(st) + vc_charts(st) + parking_chart(st):
        svg = render_svg(spec)
        root = ET.fromstring(svg)  # 유효한 XML
        assert root.tag.endswith("svg") and root.attrib["role"] == "img" and root.attrib["aria-label"]
        assert "<title>" in svg
        assert "<script" not in svg
    spec = {**vc_charts(st)[0]}
    spec["bars"] = [{"label": "<img onerror=x>", "value": 0.5, "slot": 1, "text": "0.50"}]
    assert "<img" not in render_svg(spec) and "&lt;img" in render_svg(spec)


def test_every_bar_has_a_visible_value_label(st):
    """청록 계열은 라이트 모드 대비가 3:1 미만이라 모든 막대에 값 라벨이 있어야 한다."""
    spec = stage_charts(st)[0]
    svg = render_svg(spec)
    n_bars = sum(len(g["bars"]) for g in spec["groups"])
    assert len(re.findall(r'class="vbar"|class="s\d vbar"', svg)) == n_bars
    for g in spec["groups"]:
        for b in g["bars"]:
            assert f">{b['value']:.1f}</text>" in svg


def test_palette_uses_validated_slots_only():
    assert SERIES_COLORS == {1: ("#2a78d6", "#3987e5"), 2: ("#eb6834", "#d95926"), 3: ("#1baf7a", "#199e70")}


def test_table_view_matches_chart_values(st):
    header, rows = chart_rows(stage_charts(st)[0])
    assert header == ["구분", "사업 미시행", "사업 시행", "개선 후"] and len(rows) == 2
    header, rows = chart_rows(vc_charts(st)[0])
    assert header == ["항목", "v/c"] and rows[0][0] == vc_charts(st)[0]["bars"][0]["label"]


def test_docx_bars_scale_with_value(st):
    spec = parking_chart(st)[0]
    header, rows = docx_bar_rows(spec, width=40)
    lengths = [len(r[1][0]) for r in rows]
    assert lengths[0] < lengths[1] < lengths[2]  # 법정 1,120 < 상한 1,456 < 계획 1,500
    assert max(lengths) <= 40 and all(n >= 1 for n in lengths)
    assert rows[0][2][0] == "1,120대"


def test_docx_contains_figures_with_values(tmp_path, st):
    doc = Document(export_docx(st, tmp_path / "o.docx"))
    caps = [p.text for p in doc.paragraphs if p.text.startswith("그림 ")]
    assert caps == ["그림 1. A교차로 — 현황 접근로별 v/c", "그림 2. A교차로 — 3단계 평균 제어지체", "그림 3. 주차대수 비교"]
    cells = [c.text for t in doc.tables for r in t.rows for c in r.cells]
    assert any(c.startswith("█") for c in cells) and "1,120대" in cells
    h3 = [p.text for p in doc.paragraphs if p.style.name == "Heading 3"]
    assert not any(t.startswith("그림") for t in h3)  # 그림 캡션은 목차 제목이 아니다


def test_result_page_shows_charts_and_table_view(monkeypatch, tmp_path):
    db = Database(tmp_path / "t.db")
    monkeypatch.setattr(main, "store", SqliteJobStore(db))
    monkeypatch.setattr(main, "limiter", LlmRunLog(db))
    monkeypatch.setattr(main, "throttle", auth.LoginThrottle())
    c = TestClient(main.app)
    body = {"project": {"name": "t", "address": "서울", "households": 1000, "gross_floor_area_m2": 120000, "floors": 20,
                        "unit_types": [{"exclusive_area_m2": 84, "households": 1000}], "planned_parking_spaces": 1500},
            "background_growth_rate": 0.02,
            "intersections": [{"name": "A교차로", "cycle": 120, "approaches": [
                {"name": "N", "volume": 400, "saturation_flow": 1800, "green_time": 40, "project_share": 0.4},
                {"name": "E", "volume": 500, "saturation_flow": 1800, "green_time": 40, "project_share": 0.1}]}]}
    j = c.post("/api/analyze", json=body).json()
    assert [k for k, v in j["charts"].items() if v] == ["vc", "stage", "parking"]
    html = c.post("/ui/analyze", json=body).text
    assert html.count("<svg") == 3 and html.count("표로 보기") == 3 and "A교차로 — 3단계 평균 제어지체" in html
    assert "법정 주차대수" in html
