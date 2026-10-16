"""유사시설 조사 자료 기반 원단위(app/unit_evidence.py) — 선택 규칙·지침 요건·파이프라인 연동."""
import asyncio
import io
from datetime import date

import pytest
from docx import Document

from app import unit_evidence as UE
from app.docx_export import build_docx
from app.parking import assess_parking
from app.pipeline import TIAPipeline
from app.schemas import ProjectInput
from app.state import ReportState
from app.trip_generation import estimate_trips, load_rates

TODAY = date(2026, 10, 14)


def fac(name, d, region="서울", method="현장조사", **v):
    base = {k: None for k in UE.NUMERIC}
    base.update(v)
    return UE.Facility(name=name, date=d, region=region, district="", units=500, method=method, v=base, n_projects=1)


def full(name, d, region="서울", method="현장조사", pop=3.5, car=26.0, park=1.2):
    return fac(name, d, region, method, pop_res=pop, car=car, park_wd=park, am_in=2.0, am_out=30.0, pm_in=14.0, pm_out=5.0)


def test_cutoff_is_three_years_back():
    assert UE.cutoff(TODAY) == "2023-10-14" and UE.cutoff(date(2028, 2, 29)) == "2025-02-28"


def test_old_and_future_records_are_excluded():
    fs = [full("a", "2023-10-13"), full("b", "2023-10-14"), full("c", "2024-01-01"), full("d", "2025-01-01"), full("e", "2027-01-01")]
    m = UE.metric("person_trips", fs, TODAY)
    assert m.n == 3 and {f.name for f in m.facilities} == {"b", "c", "d"}


def test_outlier_is_trimmed_before_median_when_enough_samples():
    vals = [3.0, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 9.0]
    fs = [full(f"f{i}", "2025-01-01", pop=v) for i, v in enumerate(vals)]
    m = UE.metric("person_trips", fs, TODAY)
    assert m.n == 9 and m.value == pytest.approx(3.35)  # 9.0을 뺀 8개의 중앙값(3.3, 3.4의 가운데)
    assert UE._trim(vals) == vals[:-1]


def test_small_samples_are_not_trimmed():
    fs = [full(f"f{i}", "2025-01-01", pop=v) for i, v in enumerate([3.0, 3.5, 9.0])]
    assert UE.metric("person_trips", fs, TODAY).value == 3.5  # 중앙값이라 9.0이 있어도 흔들리지 않는다


def test_falls_back_to_metro_when_seoul_has_fewer_than_three_and_says_so():
    fs = [full("s1", "2025-01-01"), full("s2", "2025-01-02"), full("g1", "2025-01-01", "경기"), full("g2", "2025-02-01", "경기"),
          full("x", "2025-02-01", "부산")]
    m = UE.metric("car_share", fs, TODAY)
    assert m.scope == "수도권" and m.n == 4 and any("수도권" in n for n in m.notes)  # 부산 제외
    m2 = UE.metric("car_share", fs + [full("s3", "2025-03-01")], TODAY)
    assert m2.scope == "서울" and m2.n == 3 and not m2.notes[:1] == ["수도권"]


def test_too_few_records_gives_no_value():
    m = UE.metric("parking", [full("a", "2025-01-01"), full("b", "2025-01-02")], TODAY)
    assert m.value is None and any("산출하지 않음" in n for n in m.notes)


def test_two_column_metric_needs_both_columns_and_drops_zero_pairs():
    fs = [fac("a", "2025-01-01", am_in=2.0, am_out=None), fac("b", "2025-01-01", am_in=0, am_out=0),
          full("c", "2025-01-01"), full("d", "2025-01-02"), full("e", "2025-01-03")]
    m = UE.metric("am_peak", fs, TODAY)
    assert m.n == 3 and m.values == {"am_in": 2.0, "am_out": 30.0}


@pytest.mark.parametrize("methods,ok", [
    (["현장조사"] * 3, True),  # 실측 3
    (["현장조사", "문헌조사", "문헌조사", "문헌조사"], True),  # 실측 1 + 문헌 3
    (["현장조사", "문헌조사", "문헌조사"], False),  # 문헌 2
    (["문헌조사"] * 6, False),  # 실측 0
    (["영상촬영", "현장조사"] + ["문헌조사"] * 3, True),
])
def test_guideline_requirement(methods, ok):
    fs = [full(f"f{i}", "2025-01-01", method=m) for i, m in enumerate(methods)]
    assert UE.metric("person_trips", fs, TODAY).guideline_ok is ok


def test_derive_rates_shape_and_math():
    fs = [full(f"f{i}", "2025-01-0%d" % (i + 1)) for i in range(4)]
    ev = UE.derive_rates(TODAY, facilities=fs)
    a = ev.rates["apartment"]
    assert ev.status == "PARTIAL_EVIDENCE" and a["daily_person_trips_per_household"] == 3.5
    assert a["mode_share"]["car"] == pytest.approx(0.26) and sum(a["mode_share"].values()) == pytest.approx(1.0)
    assert a["peak_hour"]["am"]["ratio_of_daily"] == pytest.approx(0.5 * 32 / 100)
    assert a["peak_hour"]["am"]["in_ratio"] == pytest.approx(2 / 32)
    assert a["peak_hour"]["pm"]["in_ratio"] == pytest.approx(14 / 19)
    assert a["parking"]["demand_per_household"] == 1.2 and a["car_occupancy"] == load_rates()["apartment"]["car_occupancy"]
    assert any("재차인원" in n for n in ev.notes)
    assert estimate_trips(ProjectInput(name="t", address="x", households=1000), ev.rates).rates_status == "PARTIAL_EVIDENCE"


def test_missing_metric_keeps_provisional_value_and_notes_it():
    ev = UE.derive_rates(TODAY, facilities=[full("a", "2025-01-01")])
    base = load_rates()["apartment"]
    assert ev.rates["apartment"]["daily_person_trips_per_household"] == base["daily_person_trips_per_household"]
    assert any("임시값 유지" in n for n in ev.notes)


# ── 실제 수집 자료 ──
def test_collected_data_is_usable_for_seoul_apartments():
    facs = UE.load_facilities()
    assert len(facs) >= 50 and all(f.region in {"서울", "경기", "인천"} for f in facs)
    assert len({(f.name, f.date) for f in facs}) == len(facs)  # 단지+조사일 중복 없음
    ev = UE.derive_rates(TODAY)
    for k in ("person_trips", "car_share", "parking"):
        assert ev.metrics[k].value is not None and ev.metrics[k].n >= UE.MIN_N, k
    a = ev.rates["apartment"]
    assert 1.5 < a["daily_person_trips_per_household"] < 8 and 0.05 < a["mode_share"]["car"] < 0.7 and 0.3 < a["parking"]["demand_per_household"] < 2.5


def test_basis_rows_list_every_metric():
    rows = UE.derive_rates(TODAY).basis_rows()
    assert len(rows) == len(UE.METRICS) and all(len(r) == 6 for r in rows)


# ── 파이프라인·보고서 연동 ──
def project(**kw):
    return ProjectInput(name="근거", address="서울", households=1000, gross_floor_area_m2=120_000, **kw)


def test_default_is_provisional_and_evidence_is_opt_in():
    assert estimate_trips(project()).rates_status == "PROVISIONAL"
    t = estimate_trips(project(rate_basis="evidence"))
    assert t.rates_status == "PARTIAL_EVIDENCE" and any("재차인원" in n for n in t.rate_notes)


def test_evidence_changes_numbers_and_parking_uses_evidence_rate_unless_user_overrides():
    prov, evid = estimate_trips(project()), estimate_trips(project(rate_basis="evidence"))
    assert prov.daily_vehicle_trips != evid.daily_vehicle_trips
    p = assess_parking(project(rate_basis="evidence"))
    assert p.rate_status == "EVIDENCE" and "유사시설" in p.rate_source
    u = assess_parking(project(rate_basis="evidence", parking_demand_per_household=0.9, parking_demand_source="자체 조사"))
    assert u.rate_status == "USER" and u.demand_per_household == 0.9


def run(state):
    return asyncio.run(TIAPipeline().run(state))


def test_pipeline_warns_about_remaining_provisional_occupancy_and_report_marks_it():
    st = run(ReportState(project=project(rate_basis="evidence")))
    assert any("재차인원" in w for w in st.warnings) and not any("임시값(KTDB 승인 전)" in w for w in st.warnings)
    buf = io.BytesIO()
    build_docx(st).save(buf)
    text = "\n".join(c.text for t in Document(io.BytesIO(buf.getvalue())).tables for r in t.rows for c in r.cells)
    assert "명/대 (임시)" in text and "(임시 배분)" in text


def test_implausible_values_are_ignored():
    fs = [full("a", "2025-01-01", park=7.0), full("b", "2025-01-02", park=0.1), full("c", "2025-01-03", park=1.2),
          full("d", "2025-01-04", park=1.3), full("e", "2025-01-05", park=1.1)]
    m = UE.metric("parking", fs, TODAY)
    assert m.n == 3 and m.value == 1.2  # 7.0(단위 혼입 의심)·0.1은 제외


# ── 평균 재차인원 입력 ──
def test_entered_occupancy_replaces_provisional_and_upgrades_status():
    fs = [full(f"f{i}", "2025-01-0%d" % (i + 1)) for i in range(4)]
    ev = UE.derive_rates(TODAY, facilities=fs, car_occupancy=1.5)
    assert ev.status == "EVIDENCE" and ev.rates["apartment"]["car_occupancy"] == 1.5
    assert not any("재차인원" in n for n in ev.notes)
    partial = UE.derive_rates(TODAY, facilities=fs)
    assert partial.status == "PARTIAL_EVIDENCE"


def test_occupancy_with_missing_metric_stays_partial():
    ev = UE.derive_rates(TODAY, facilities=[full("a", "2025-01-01")], car_occupancy=1.5)
    assert ev.status == "PROVISIONAL" and ev.rates["apartment"]["car_occupancy"] == 1.5  # 유사시설 자료가 하나도 없으면 근거 상태가 아니다
    mixed = [full(f"f{i}", "2025-01-0%d" % (i + 1), pop=3.5) for i in range(4)]
    for f in mixed:
        f.v["car"] = None  # 분담률만 비는 경우
    assert UE.derive_rates(TODAY, facilities=mixed, car_occupancy=1.5).status == "PARTIAL_EVIDENCE"


def test_project_occupancy_changes_vehicle_trips_in_both_modes():
    base = estimate_trips(project(rate_basis="evidence"))
    occ = estimate_trips(project(rate_basis="evidence", car_occupancy=2.0))
    assert occ.rates_status == "EVIDENCE" and base.rates_status == "PARTIAL_EVIDENCE"
    assert occ.daily_vehicle_trips == pytest.approx(base.daily_vehicle_trips * 1.3 / 2.0)
    prov = estimate_trips(project(car_occupancy=2.0))
    assert prov.rates_status == "PROVISIONAL" and prov.daily_vehicle_trips == pytest.approx(estimate_trips(project()).daily_vehicle_trips * 1.3 / 2.0)


@pytest.mark.parametrize("v", [0.5, 0, 9, -1])
def test_occupancy_range_is_validated(v):
    with pytest.raises(ValueError):
        project(car_occupancy=v)


def test_pipeline_report_and_ui_for_entered_occupancy():
    st = run(ReportState(project=project(rate_basis="evidence", car_occupancy=1.4, car_occupancy_source="단지 현장조사")))
    assert st.trips.rates_status == "EVIDENCE" and any("재차인원은 입력값(출처: 단지 현장조사)" in w for w in st.warnings)
    buf = io.BytesIO()
    build_docx(st).save(buf)
    text = "\n".join(c.text for t in Document(io.BytesIO(buf.getvalue())).tables for r in t.rows for c in r.cells)
    assert "1.4명/대 (입력)" in text


def test_wizard_sends_occupancy_fields():
    from fastapi.testclient import TestClient

    from app import main
    c = TestClient(main.app)
    html, js = c.get("/app").text, c.get("/static/wizard.js").text
    assert 'id="occ"' in html and 'id="occsrc"' in html and "car_occupancy" in js and "car_occupancy_source" in js
