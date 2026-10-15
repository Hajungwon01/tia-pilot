"""full.json(수집 원본) → data/unit_rate_evidence.csv. 유사시설(단지명+조사일) 단위로 합치고 아파트·3년+α 이내만 남긴다."""
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent / "_tia_raw"  # collect_tia_evidence.py가 만든 원본
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data" / "unit_rate_evidence.csv"
D = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEEP_FROM = "2023-06-01"  # 기준일(오늘)에서 3년 이내 판정은 모듈이 하고, 시간이 지나도 쓸 수 있게 여유를 둔다


def num(s):
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def rows_with_date(rows):
    out = []
    for r in rows:
        i = next((k for k, c in enumerate(r) if D.match(c)), -1)
        if i >= 0:
            out.append(([c for c in r[:i] if c != ""], r[i], r[i + 1:], r))
    return out


def region(addr):
    return "서울" if "서울" in addr else "인천" if "인천" in addr else "경기" if "경기" in addr else "기타"


full = json.loads((HERE / "full.json").read_text(encoding="utf-8"))
lst = json.loads((HERE / "list.json").read_text(encoding="utf-8"))
fac = {}
sim = {}
for pid, rec in full.items():
    for pre, date, post, raw in rows_with_date(rec.get("sim", [])):
        i = raw.index(date)
        sim[raw[i + 2]] = {"addr": raw[i + 3], "units": num(raw[i + 10]) if len(raw) > i + 10 else None,
                           "method": raw[i + 15] if len(raw) > i + 15 else ""}
    for tab in ("pop", "mode", "ratio", "park"):
        for pre, date, post, raw in rows_with_date(rec.get(tab, [])):
            use, name = (pre + ["", ""])[:2]
            f = fac.setdefault((name, date), {"name": name, "date": date, "use": use, "projs": set()})
            f["projs"].add(pid)
            f["use"] = f["use"] or use
            if tab == "pop":
                f["pop_res"], f["pop_use"] = num(post[2]) if len(post) > 2 else None, num(post[3]) if len(post) > 3 else None
            elif tab == "mode":
                f.setdefault("mode", []).append((post[0], post[1], [num(x) for x in post[2:9]]))
            elif tab == "ratio":
                f.setdefault("ratio", []).append((post[0], [num(x) for x in post[1:5]]))
            elif tab == "park":
                f["park_wd"] = num(post[2]) if len(post) > 2 else None

cols = ["name", "date", "region", "district", "units", "method", "pop_res", "pop_use", "park_wd", "car", "taxi", "bus", "subway",
        "walk", "am_in", "am_out", "pm_in", "pm_out", "n_projects"]
rows = []
for f in fac.values():
    if not re.search("아파트|공동주택", f["use"]) or f["date"] < KEEP_FROM:
        continue
    s = sim.get(f["name"], {})
    addr = s.get("addr", "")
    car = taxi = bus = sub = walk = None
    for pop, day, v in f.get("mode", []):
        if pop in ("상근", "상주") and day != "주말" and len(v) >= 7 and abs(sum(x or 0 for x in v) - 100) < 10:
            car, taxi, bus, sub, walk = v[1], v[2], v[3], v[4], v[6]
            break

    def hour(h):
        for hh, v in f.get("ratio", []):
            if hh.startswith(h) and not all(x in (0, 1) for x in v):
                return v[0], v[1]
        return None, None
    ai, ao = hour("08")
    pi, po = hour("18")
    pr = f.get("pop_res") if (f.get("pop_res") or 0) > 0 else None
    pu = f.get("pop_use") if (f.get("pop_use") or 0) > 0 else None
    pk = f.get("park_wd") if (f.get("park_wd") or 0) > 0 else None
    if all(x is None for x in (pr, pk, car, ai)) or region(addr) == "기타":  # 지역을 확인할 수 없는 단지는 쓰지 않는다
        continue
    gu = " ".join(addr.split()[1:3])
    rows.append([f["name"].replace(",", " "), f["date"], region(addr), gu, "" if not s.get("units") else int(s["units"]), s.get("method", ""),
                 *["" if x is None else round(x, 2) for x in (pr, pu, pk, car, taxi, bus, sub, walk, ai, ao, pi, po)], len(f["projs"])])
rows.sort(key=lambda r: (r[2], r[1], r[0]))
with OUT.open("w", encoding="utf-8", newline="") as fh:
    fh.write("# 국토교통부 교통영향평가정보지원시스템(tia.molit.go.kr) 사업별 '원단위정보(유사시설)' 공개 자료를 수집한 것(수집일 2026-10-15).\n")
    fh.write("# 범위: 서울·경기·인천 승인, 사업신청 2022년 이후, 사업명에 아파트·공동주택·주상복합·재건축·리모델링·주택 포함, 유사시설 용도 아파트·공동주택, 조사일 2023-06-01 이후.\n")
    fh.write("# 한 행 = 유사 아파트 단지 1곳(단지명+조사일 중복 제거). 수치는 평가서가 입력한 값 그대로이며 이 도구는 검증하지 않았다(심의 전 사업 포함).\n")
    fh.write("# 열: pop_res/pop_use=상주·이용 발생원단위(인/일), park_wd=평일 주차원단위(대/세대), car..walk=상주 평일 수단분담률(%), am_*/pm_*=08시·18시 시간대 유입·유출(%).\n")
    w = csv.writer(fh)
    w.writerow(cols)
    w.writerows(rows)
print(len(fac), "facilities total;", len(rows), "kept;", sum(r[2] == "서울" for r in rows), "서울")
