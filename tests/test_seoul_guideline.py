"""서울특별시 교통영향평가 수립지침(고시 제2017-43호) 반영분."""
import asyncio

from docx import Document

from app.agents.ai import AI_SECTIONS
from app.docx_export import KEY_TITLES, export_docx
from app.guideline_rules import ATTENTION, OK, UNKNOWN, external_improvement
from app.pipeline import TIAPipeline
from app.reflection import load_checklist
from app.schemas import ProjectInput
from app.state import ReportState


def run(**kw):
    p = ProjectInput(name="t", address="서울", households=500, **kw)
    return asyncio.run(TIAPipeline().run(ReportState(project=p)))


def test_transit_walk_bike_are_separate_sections_like_seoul_annex1():
    keys = {i["key"] for i in load_checklist()["items"] if i["check"] == "key"}
    assert {"improve.transit", "improve.walk", "improve.bike"} <= keys and "improve.transit_walk_bike" not in keys
    assert {"improve.transit", "improve.walk", "improve.bike"} <= set(AI_SECTIONS)
    assert {KEY_TITLES[k] for k in ("improve.transit", "improve.walk", "improve.bike")} == {"대중교통", "보행", "자전거"}


def test_checklist_cites_seoul_guideline():
    cl = load_checklist()
    assert "제2017-43호" in cl["basis"] and cl["version"] == "0.3"
    refs = " ".join(i["ref"] for i in cl["items"])
    for must in ("서울 별표1 4.라", "서울 별표1 4.마", "서울 별표3 6.타", "서울 지침 제12조⑨", "서울 지침 제18조"):
        assert must in refs, must
    assert any("비용부담주체" in i["text"] for i in cl["items"] if i["id"] == "S5-1")


def test_scope_text_lists_seoul_only_focus_items():
    st = run(gross_floor_area_m2=60000)
    scope = st.sections["intro.scope"]
    assert "서울시 수립지침" in scope
    assert "- 차. 차량과 보행자, 자전거의 상충분석" in scope and "- 타. 자전거도로의 설치 가능여부 검토" in scope


def test_ai_writes_three_separate_sections_when_llm_runs():
    from tests.test_pipeline import FakeLLM
    s = ReportState(project=ProjectInput(name="t", address="서울", households=500, gross_floor_area_m2=60000))
    st = asyncio.run(TIAPipeline(llm=FakeLLM(fail_first=False)).run(s))
    for k in ("improve.transit", "improve.walk", "improve.bike"):
        assert st.sections.get(k) and k not in st.reflection["missing"]


def test_external_improvement_rule_needs_ten_times():
    def st(mult):
        s = ReportState(project=ProjectInput(name="t", address="서울", households=500))
        s.scope = {"eligibility": {"multiple": mult}}
        return s
    assert external_improvement(st(9.99))[0] == OK
    status, msg = external_improvement(st(10))
    assert status == ATTENTION and "10배 이상" in msg
    assert external_improvement(ReportState(project=ProjectInput(name="t", address="서울", households=5)))[0] == UNKNOWN


def test_pipeline_reports_external_rule_for_large_project():
    st = run(gross_floor_area_m2=520000)  # 10.4배
    rule = next(r for r in st.reflection["rules"] if r["id"] == "SE-7")
    assert rule["status"] == "attention"
    assert next(r for r in run(gross_floor_area_m2=60000).reflection["rules"] if r["id"] == "SE-7")["status"] == "ok"


def test_docx_has_three_separate_improvement_headings(tmp_path):
    doc = Document(export_docx(run(gross_floor_area_m2=60000), tmp_path / "o.docx"))
    h3 = [p.text for p in doc.paragraphs if p.style.name == "Heading 3"]
    assert {"대중교통", "보행", "자전거"} <= set(h3) and "대중교통, 자전거 및 보행" not in h3
