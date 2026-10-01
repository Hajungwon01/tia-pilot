from app.reflection import check_report, load_checklist


def test_checklist_loads_and_ids_unique():
    items = load_checklist()["items"]
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))
    assert all(i["check"] in ("key", "manual") for i in items)
    assert all("key" in i for i in items if i["check"] == "key")


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
