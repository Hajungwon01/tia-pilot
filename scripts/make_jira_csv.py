"""BACKLOG.md -> jira_import.csv (Jira CSV Import용). 실행: python scripts/make_jira_csv.py"""
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "BACKLOG.md"
OUT = ROOT / "jira_import.csv"

EPICS = {
    "EP-0": ("기반·문서화", "infra"),
    "EP-PLAN": ("Planning 에이전트 (규모·범위 판정)", "agent-planning"),
    "EP-DATA": ("Data 에이전트 (수요 추정·LOS·공공데이터)", "agent-data"),
    "EP-ENG": ("Engineering 에이전트 (파이프라인·문서 조립)", "agent-eng"),
    "EP-CRE": ("Creative 에이전트 (시각화)", "agent-creative"),
    "EP-AI": ("AI 에이전트 (해석·개선대책 문구)", "agent-ai"),
    "EP-REF": ("Reflection 에이전트 (지침 준수 점검)", "agent-reflection"),
    "EP-UI": ("프론트엔드·배포", "ui"),
    "EP-QA": ("검증", "qa"),
}
PRIORITY = {"P0": "Highest", "P1": "Medium", "P2": "Low"}
STATUS = {"완료": "Done"}  # 나머지는 To Do
SPRINT_NAME = "TIA Sprint {}"

HEADER = ["Issue Id", "Issue Type", "Summary", "Parent", "Priority", "Status",
          "Sprint", "Labels", "Labels", "Description"]


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def main() -> None:
    rows: list[list[str]] = []
    issue_id = 0

    def add(kind, summary, parent="", prio="", status="To Do", sprint="", labels=("", ""), desc=""):
        nonlocal issue_id
        issue_id += 1
        rows.append([str(issue_id), kind, summary, parent, prio, status, sprint, labels[0], labels[1], desc])
        return str(issue_id)

    epic_ids = {}
    for code, (name, _label) in EPICS.items():
        epic_ids[code] = add("Epic", name, labels=(_label, ""))

    section = None
    in_blockers = False
    for line in SRC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (EP-[A-Z0-9]+)", line)
        if m:
            section, in_blockers = m.group(1), False
            continue
        if line.startswith("## 외부 의존"):
            section, in_blockers = None, True
            continue
        if not line.startswith("|") or line.startswith("|---") or "Story" in line.split("|")[2:3] or line.startswith("| ID"):
            continue
        c = cells(line)
        if in_blockers and c[0].startswith("BLK-"):
            add("Task", f"[{c[0]}] {c[1]}", prio="Highest", status="To Do",
                labels=("blocker", "external"), desc=f"상태: {c[2]}\n{c[3] if len(c) > 3 else ''}")
        elif section and c[0].startswith("TIA-") and len(c) >= 5:
            tid, story, prio, sprint, status = c[0], c[1], c[2], c[3], c[4]
            labels = [EPICS[section][1], ""]
            if status.startswith("차단됨"):
                labels[1] = "blocked"
            sp = re.fullmatch(r"S(\d+)", sprint)
            add("Story", f"[{tid}] {story}", parent=epic_ids[section], prio=PRIORITY.get(prio, "Medium"),
                status=STATUS.get(status.split("(")[0], "To Do"),
                sprint=SPRINT_NAME.format(sp.group(1)) if sp else "",
                labels=tuple(labels), desc=f"백로그 ID: {tid}\n원본 상태: {status}")

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    kinds = {}
    for r in rows:
        kinds[r[1]] = kinds.get(r[1], 0) + 1
    print(OUT.name, kinds)


if __name__ == "__main__":
    main()
