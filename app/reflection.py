"""Reflection 에이전트: 지침 기반 체크리스트(v0.2) 누락 검사."""
import json
from pathlib import Path

CHECKLIST_PATH = Path(__file__).resolve().parent.parent / "data" / "reflection_checklist.json"


def load_checklist(path: Path = CHECKLIST_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_report(present_keys: set[str], checklist: dict | None = None) -> dict:
    """보고서에 포함된 key 집합을 받아 누락/수동확인 항목을 분류. rule 항목은 evaluate_rules가 따로 판정한다."""
    items = (checklist or load_checklist())["items"]
    missing = [i for i in items if i["check"] == "key" and i["key"] not in present_keys]
    manual = [i for i in items if i["check"] == "manual"]
    auto_total = sum(1 for i in items if i["check"] == "key")
    return {
        "passed": auto_total - len(missing),
        "auto_total": auto_total,
        "missing": missing,
        "manual": manual,
    }
