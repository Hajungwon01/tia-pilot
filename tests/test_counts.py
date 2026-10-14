"""교통량 조사 CSV → 첨두시·PHF·접근로 교통량."""
import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.counts import CountsError, parse_counts
from app.storage import Database, LlmRunLog, SqliteJobStore

HEADER = "날짜,시각,접근로,좌회전,직진,우회전,U턴,대형차\n"


def hour_rows(day, start_min, name, per_bin, heavy=0):
    """per_bin: [(좌, 직, 우, U), ...] 4개."""
    out = []
    for i, (l, t, r, u) in enumerate(per_bin):
        m = start_min + 15 * i
        out.append(f"{day},{m // 60:02d}:{m % 60:02d},{name},{l},{t},{r},{u},{heavy}")
    return out


FLAT = [(10, 100, 20, 0)] * 4


def test_peak_hour_volumes_and_phf():
    rows = []
    # EB: 17:00~18:00이 가장 많다(두 번째 구간이 최대 15분)
    rows += hour_rows("2026-03-10", 17 * 60, "EB", [(10, 100, 20, 0), (20, 140, 30, 1), (10, 100, 20, 0), (10, 100, 20, 0)], heavy=4)
    rows += hour_rows("2026-03-10", 16 * 60, "EB", [(1, 10, 2, 0)] * 4)  # 덜 붐비는 시간
    rows += hour_rows("2026-03-10", 17 * 60, "WB", FLAT, heavy=2)
    rows += hour_rows("2026-03-10", 16 * 60, "WB", [(1, 10, 2, 0)] * 4)
    r = parse_counts(HEADER + "\n".join(rows))
    pm = r["peaks"]["pm"]
    assert (pm["start"], pm["end"]) == ("17:00", "18:00") and r["peaks"]["am"] is None
    eb = pm["approaches"]["EB"]
    assert (eb["v_left"], eb["v_through"], eb["v_right"], eb["u_turn"]) == (50, 440, 90, 1)
    assert eb["heavy_pct"] == pytest.approx(100 * 16 / 581, abs=0.05)
    total = 581 + 520
    peak15 = (20 + 140 + 30 + 1) + 130  # 둘째 구간: EB 191 + WB 130
    assert pm["total"] == total and pm["phf"] == pytest.approx(total / (4 * peak15), abs=1e-3)
    assert any("AM" in w for w in r["warnings"])  # AM 자료 없음 알림


def test_am_and_pm_peaks_found_independently():
    rows = []
    for name in ("EB", "WB"):
        rows += hour_rows("d", 8 * 60, name, [(5, 50, 10, 0)] * 4)
        rows += hour_rows("d", 18 * 60, name, [(8, 80, 16, 0)] * 4)
        rows += hour_rows("d", 17 * 60, name, [(1, 10, 2, 0)] * 4)
    r = parse_counts(HEADER + "\n".join(rows))
    assert r["peaks"]["am"]["start"] == "08:00" and r["peaks"]["pm"]["start"] == "18:00"
    assert r["peaks"]["pm"]["phf"] == 1.0  # 평탄한 15분 자료


def test_sliding_window_not_aligned_to_hour():
    names = ("EB",)
    bins = [(1, 10, 2, 0), (1, 10, 2, 0), (9, 90, 18, 0), (9, 90, 18, 0)]
    rows = hour_rows("d", 17 * 60, "EB", bins) + hour_rows("d", 18 * 60, "EB", [(9, 90, 18, 0), (9, 90, 18, 0), (1, 10, 2, 0), (1, 10, 2, 0)])
    pk = parse_counts(HEADER + "\n".join(rows))["peaks"]["pm"]
    assert pk["start"] == "17:30" and pk["approaches"]["EB"]["v_through"] == 360


def test_multiple_days_are_averaged():
    rows = hour_rows("d1", 17 * 60, "EB", [(10, 100, 20, 0)] * 4) + hour_rows("d2", 17 * 60, "EB", [(30, 300, 60, 0)] * 4)
    r = parse_counts(HEADER + "\n".join(rows))
    assert r["days"] == 2 and r["peaks"]["pm"]["approaches"]["EB"]["v_through"] == 800  # (100+300)/2×4
    assert any("평균" in w for w in r["warnings"])


def test_duplicate_rows_sum_for_lanes_or_vehicle_classes():
    rows = hour_rows("d", 17 * 60, "EB", [(10, 100, 20, 0)] * 4) + hour_rows("d", 17 * 60, "EB", [(5, 50, 10, 0)] * 4)
    assert parse_counts(HEADER + "\n".join(rows))["peaks"]["pm"]["approaches"]["EB"]["v_through"] == 600


def test_window_with_missing_approach_bin_is_skipped():
    rows = hour_rows("d", 17 * 60, "EB", FLAT) + hour_rows("d", 17 * 60, "WB", FLAT)[:3]  # WB 17:45 빠짐
    rows += hour_rows("d", 18 * 60, "EB", [(1, 10, 2, 0)] * 4) + hour_rows("d", 18 * 60, "WB", [(1, 10, 2, 0)] * 4)
    r = parse_counts(HEADER + "\n".join(rows))
    assert r["peaks"]["pm"]["start"] == "18:00"  # 빠진 시간대(17:00)는 후보에서 제외
    assert any("제외" in w for w in r["warnings"])


def test_optional_columns_and_alias_headers_and_tab_delimiter():
    text = "시간\t방향\t좌\t직\t우\n17:00\tEB\t1\t10\t2\n17:15\tEB\t1\t10\t2\n17:30\tEB\t1\t10\t2\n17:45\tEB\t1\t10\t2\n"
    r = parse_counts(text)
    eb = r["peaks"]["pm"]["approaches"]["EB"]
    assert eb["v_through"] == 40 and "heavy_pct" not in eb and eb["u_turn"] == 0
    assert any("대형차 열이 없어" in w for w in r["warnings"])


def test_bom_and_thousand_separators():
    rows = ['2026-01-01,17:00,EB,"1,000",2,3,0,0', "2026-01-01,17:15,EB,0,0,0,0,0", "2026-01-01,17:30,EB,0,0,0,0,0", "2026-01-01,17:45,EB,0,0,0,0,0"]
    r = parse_counts("﻿" + HEADER + "\n".join(rows))
    assert r["peaks"]["pm"]["approaches"]["EB"]["v_left"] == 1000


@pytest.mark.parametrize("text,expect", [
    ("", "자료가 없습니다"),
    ("시각,접근로,좌회전\n17:00,EB,1\n", "필수 열이 없습니다"),
    (HEADER + "d,17:07,EB,1,1,1,0,0\n", "15분 단위"),
    (HEADER + "d,25:00,EB,1,1,1,0,0\n", "올바르지 않습니다"),
    (HEADER + "d,abc,EB,1,1,1,0,0\n", "읽을 수 없습니다"),
    (HEADER + "d,17:00,EB,x,1,1,0,0\n", "숫자가 아닙니다"),
    (HEADER + "d,17:00,EB,-5,1,1,0,0\n", "0 이상"),
    (HEADER + "d,17:00,,1,1,1,0,0\n", "접근로 이름이 비어"),
    (HEADER + "d,17:00,EB,1,1,1,0,9\n", "대형차"),
    (HEADER + "d,17:00,EB,1,1,1,0,0\n", "첨두 1시간을 찾지 못했습니다"),  # 구간이 1개뿐
])
def test_bad_input_is_rejected_with_reason(text, expect):
    with pytest.raises(CountsError, match=expect):
        parse_counts(text)


def test_row_number_in_error_message():
    with pytest.raises(CountsError, match="3행"):
        parse_counts(HEADER + "d,17:00,EB,1,1,1,0,0\nd,17:15,EB,a,1,1,0,0\n")


def test_too_many_approaches_rejected():
    rows = []
    for i in range(9):
        rows += hour_rows("d", 17 * 60, f"A{i}", FLAT)
    with pytest.raises(CountsError, match="접근로가 9개"):
        parse_counts(HEADER + "\n".join(rows))


# ── API ──
@pytest.fixture
def client(monkeypatch, tmp_path):
    db = Database(tmp_path / "t.db")
    monkeypatch.setattr(main, "store", SqliteJobStore(db))
    monkeypatch.setattr(main, "limiter", LlmRunLog(db))
    monkeypatch.setattr(main, "throttle", auth.LoginThrottle())
    return TestClient(main.app)


def test_api_parses_template_file_shipped_with_the_app(client):
    text = client.get("/static/count_template.csv").content.decode("utf-8-sig")
    j = client.post("/api/counts/parse", json={"text": text}).json()
    assert j["peaks"]["pm"]["start"] == "17:00" and set(j["approaches"]) == {"EB", "WB"}


def test_api_errors(client):
    r = client.post("/api/counts/parse", json={"text": HEADER + "d,17:07,EB,1,1,1,0,0\n"})
    assert r.status_code == 422 and "15분 단위" in r.json()["detail"]
    assert client.post("/api/counts/parse", json={"text": "  "}).status_code == 400
    assert client.post("/api/counts/parse", content=b"not json").status_code == 400
    assert client.post("/api/counts/parse", json={"text": "x" * 2_100_000}).status_code == 413


def test_api_requires_login_when_auth_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("BETA_CODES", "alpha")
    from app.config import get_settings
    get_settings.cache_clear()
    try:
        c = TestClient(main.app)
        assert c.post("/api/counts/parse", json={"text": "x"}).status_code == 401
    finally:
        monkeypatch.delenv("BETA_CODES")
        get_settings.cache_clear()


def test_wizard_has_csv_import_wired(client):
    js = client.get("/static/wizard.js").text
    assert "/api/counts/parse" in js and "count_template.csv" in js and 'class="csv-file"' in js
    assert 'euc-kr' in js  # 엑셀 한국어 CSV
