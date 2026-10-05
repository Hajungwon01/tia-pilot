from app.reflection import check_report, load_checklist


def test_checklist_loads_and_ids_unique():
    items = load_checklist()["items"]
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))
    assert all(i["check"] in ("key", "manual", "rule") for i in items)
    assert all("key" in i for i in items if i["check"] == "key")
    assert all("rule" in i for i in items if i["check"] == "rule")


def test_empty_report_misses_everything():
    r = check_report(set())
    assert r["passed"] == 0
    assert len(r["missing"]) == r["auto_total"]


def test_full_report_has_no_missing():
    cl = load_checklist()
    keys = {i["key"] for i in cl["items"] if i["check"] == "key"}
    r = check_report(keys, cl)
    assert r["missing"] == []
    assert r["passed"] == r["auto_total"]
    assert r["manual"]  # 수동 항목은 항상 남음


# ── v0.2: 별표 2·3·7·8 ──
import asyncio  # noqa: E402

from app.guideline_rules import ATTENTION, OK, UNKNOWN, entrance_400, evaluate_rules  # noqa: E402
from app.pipeline import TIAPipeline  # noqa: E402
from app.schemas import PeakTrips, ProjectInput, TripGenerationResult  # noqa: E402
from app.state import ReportState  # noqa: E402


def _state(am=(100, 200), pm=(150, 120), status="OFFICIAL"):
    s = ReportState(project=ProjectInput(name="t", address="서울", households=100))
    s.trips = TripGenerationResult(
        daily_person_trips=0, daily_vehicle_trips=0, rates_status=status,
        am_peak=PeakTrips(in_trips=am[0], out_trips=am[1]), pm_peak=PeakTrips(in_trips=pm[0], out_trips=pm[1]))
    return s


def test_checklist_v02_covers_annexes():
    cl = load_checklist()
    assert cl["version"] == "0.2"
    refs = " ".join(i["ref"] for i in cl["items"])
    for annex in ("별표2", "별표3", "별표7", "별표8"):
        assert annex in refs
    assert len([i for i in cl["items"] if i.get("group") == "annex3"]) == 9  # 별표 3 6.가~자
    assert len([i for i in cl["items"] if i.get("group") == "annex8"]) == 4  # 별표 8 대분류 4개
    assert not any("별표 2" in x and "별표 3" in x for x in cl["not_yet_reviewed"])  # 읽은 별표는 미검토 목록에서 제외


def test_new_items_do_not_change_report_structure():
    """별표 1 구조(key 항목) 수는 그대로: 새 항목은 manual/rule이라 보고서 섹션을 늘리지 않는다."""
    cl = load_checklist()
    assert sum(1 for i in cl["items"] if i["check"] == "key") == 52
    r = check_report(set(), cl)
    assert r["auto_total"] == 52
    assert len(r["manual"]) > 5  # 별표 2·3·7·8 항목이 사람 확인 목록에 들어옴
    assert not any(i["check"] == "rule" for i in r["manual"])


def test_entrance_rule_thresholds():
    assert entrance_400(_state(am=(100, 399)))[0] == OK
    status, msg = entrance_400(_state(am=(100, 400)))
    assert status == ATTENTION and "AM" in msg and "400" in msg
    assert entrance_400(_state(am=(10, 10), pm=(450, 100)))[0] == ATTENTION  # PM 유입이 중방향
    assert entrance_400(_state(pm=(100, 500)))[0] == ATTENTION  # 유출이 중방향


def test_entrance_rule_without_trips_is_unknown_and_provisional_noted():
    s = ReportState(project=ProjectInput(name="t", address="서울", households=100))
    assert entrance_400(s)[0] == UNKNOWN
    assert "임시값" in entrance_400(_state(status="PROVISIONAL"))[1]


def test_unknown_rule_name_is_not_silently_passed():
    cl = {"items": [{"id": "X", "ref": "r", "text": "t", "check": "rule", "rule": "nope"}]}
    out = evaluate_rules(_state(), cl)
    assert out[0]["status"] == UNKNOWN


def test_pipeline_reports_rules_and_scope_lists_annex3_focus_items():
    st = asyncio.run(TIAPipeline().run(ReportState(
        project=ProjectInput(name="t", address="서울 OO동", households=300, gross_floor_area_m2=60000))))
    assert [r["id"] for r in st.reflection["rules"]] == ["A2-2.3"]
    scope = st.sections["intro.scope"]
    assert "별표 3 6. 개별 건축물 준용" in scope
    assert "- 가. " in scope and "- 자. 이용자(인구)의 교통이용 유형 및 행태 분석" in scope
