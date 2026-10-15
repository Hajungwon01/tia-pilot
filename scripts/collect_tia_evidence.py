"""교통영향평가정보지원시스템 공개 목록·원단위정보 수집(읽기 전용). 진행 상황은 progress.txt, 결과는 JSON 파일로 남긴다."""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUT = Path(__file__).parent / "_tia_raw"  # 수집 원본(list.json·full.json, git 제외)
OUT.mkdir(exist_ok=True)
BASE = "https://tia.molit.go.kr"
HDR = {"User-Agent": "Mozilla/5.0 (research; read-only public data)", "Content-Type": "application/x-www-form-urlencoded"}
TABS = {"sim": "businessSmfcyView", "pop": "businessPopultnView", "ratio": "businessRatioView",
        "mode": "businessTrnsprtView", "park": "businessParkingView"}


def log(msg):
    with open(OUT / "progress.txt", "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def session():
    s = requests.Session()
    s.headers.update(HDR)
    s.get(BASE + "/search/businessSrchList.do", timeout=30)
    return s


def post(s, path, data, tries=4):
    for i in range(tries):
        try:
            r = s.post(BASE + path, data=data, timeout=60)
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(2 * (i + 1))
    return ""


def base_form():
    return {"bsns_id": "", "s_user_id": "", "pageType": "businessSrchList", "s_bsns_ty_detail": "", "s_sel_gb": "regist_dd",
            "s_st_dt": "2022-01-01", "s_ed_dt": time.strftime("%Y-%m-%d"), "s_dlbrt_code": "", "s_bsns_ty": "", "s_bsns_dv": "",
            "s_parent_grc_code": "", "s_grc_code": "", "s_bsns_nm": "", "s_data_ty": "", "s_data_nm": "", "s_comp_ty": "",
            "s_comp_nm": "", "s_bsns_lc": "", "s_bsns_enty_st": "", "s_bsns_enty_ed": "", "pageIndex": "1"}


def list_projects():
    s = session()
    found = {}
    for reg in ("11", "28", "41"):
        for kw in ("아파트", "공동주택", "주상복합", "재건축", "리모델링", "주택"):
            for page in range(1, 60):
                f = base_form()
                f.update({"s_parent_grc_code": reg, "s_bsns_nm": kw, "pageIndex": str(page)})
                html = post(s, "/search/businessSrchList.do", f)
                soup = BeautifulSoup(html, "html.parser")
                tb = next((t for t in soup.find_all("table") if "No." in t.get_text() and "사업명" in t.get_text()), None)
                rows = tb.find_all("tr")[1:] if tb else []
                if not rows:
                    break
                for tr in rows:
                    a = tr.find("a")
                    if not a:
                        continue
                    m = re.search(r"\d{6,}", a.get("href", ""))
                    tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                    if m and m.group(0) not in found:
                        found[m.group(0)] = {"reg": reg, "name": tds[1], "year": tds[2], "auth": tds[5] if len(tds) > 5 else ""}
                if len(rows) < 10:
                    break
            log(f"list {reg} {kw} total={len(found)}")
    (OUT / "list.json").write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    return found


def parse_table(html):
    soup = BeautifulSoup(html, "html.parser")
    tbs = [t for t in soup.find_all("table") if "조사일" in t.get_text()]
    if not tbs:
        return []
    out = []
    for tr in tbs[-1].find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) > 3 and "등록된 데이터가 없습니다" not in "".join(cells):
            out.append(cells)
    return out


def fetch_project(pid):
    s = session()
    rec = {}
    for k, u in TABS.items():
        f = base_form()
        f["bsns_id"] = pid
        rec[k] = parse_table(post(s, f"/search/{u}.do", f))
    return pid, rec


def main():
    found = json.loads((OUT / "list.json").read_text(encoding="utf-8")) if (OUT / "list.json").exists() else list_projects()
    ids = sorted(found, key=lambda k: found[k]["year"], reverse=True)
    full = json.loads((OUT / "full.json").read_text(encoding="utf-8")) if (OUT / "full.json").exists() else {}
    todo = [i for i in ids if i not in full]
    log(f"projects={len(ids)} todo={len(todo)}")
    n = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for pid, rec in ex.map(fetch_project, todo):
            full[pid] = rec
            n += 1
            if n % 20 == 0:
                (OUT / "full.json").write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
                log(f"fetched {n}/{len(todo)}")
    (OUT / "full.json").write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
    log("DONE")


if __name__ == "__main__":
    main()
