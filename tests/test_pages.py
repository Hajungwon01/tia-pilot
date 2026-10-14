"""첫 화면·안내·분석 마법사·정적 파일."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.storage import Database, LlmRunLog, SqliteJobStore


@pytest.fixture
def client(monkeypatch, tmp_path):
    db = Database(tmp_path / "t.db")
    monkeypatch.setattr(main, "store", SqliteJobStore(db))
    monkeypatch.setattr(main, "limiter", LlmRunLog(db))
    monkeypatch.setattr(main, "throttle", auth.LoginThrottle())
    return TestClient(main.app)


def test_landing_page_sections(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    for needle in ("숫자부터 문서까지", 'href="/app"', 'href="/guide"', "Planning", "Reflection", "이 도구가 하지 않는 일",
                   "자주 묻는 질문", "제출용 보고서가 아니에요", "교통기술사"):
        assert needle in html, needle
    assert 'rel="stylesheet" href="/static/site.css"' in html and '<script src="/static/site.js">' in html
    assert 'id="form"' not in html  # 입력 폼은 /app에만 있다


def test_landing_claims_match_data():
    """첫 화면의 숫자(점검 항목 수·용도 수)는 실제 데이터와 같아야 한다."""
    from app.eligibility import use_table
    from app.reflection import load_checklist
    html = TestClient(main.app).get("/").text
    items = load_checklist()["items"]
    assert f'data-count="{len(items)}"' in html
    assert f'data-count="{sum(1 for i in items if i["check"] == "key")}"' in html
    assert f'data-count="{len(use_table())}"' in html


def test_guide_page_has_toc_and_every_section(client):
    html = client.get("/guide").text
    ids = ["prep", "steps", "result", "rules", "limits", "sources"]
    for i in ids:
        assert f'href="#{i}"' in html and f'id="{i}"' in html, i
    assert html.count('data-key="') == 6  # 준비물 체크리스트 6개
    for needle in ("50,000㎡", "75㎡당 1대", "65㎡당 1대", "130%", "≤15", "서울특별시고시 제2017-43호", "기재 필요"):
        assert needle in html, needle


def test_guide_rules_agree_with_code():
    """안내의 판정 기준 표 값이 코드·데이터와 같은지."""
    from app.eligibility import SPATIAL_TIERS, load_thresholds
    from app.los import LOS_THRESHOLDS
    from app.parking import load_rules
    html = TestClient(main.app).get("/guide").text
    assert f"{load_thresholds()['apartment']['seoul']['threshold_m2']:,}㎡ 이상" in html
    m = load_rules()["apartment_legal"]["m2_per_space"]
    assert f"{m['le85']}㎡당 1대" in html and f"{m['gt85']}㎡당 1대" in html
    assert f"{load_rules()['planned_cap']['seoul_pct']}%" in html
    for v, g in LOS_THRESHOLDS:
        assert f"≤{v}" in html, g
    assert [t[2] for t in SPATIAL_TIERS] == [4, 8, 12] and "교차로 4개 이상" in html and "12개" in html


def test_app_page_is_a_five_step_wizard_with_all_inputs(client):
    html = client.get("/app").text
    assert html.count('class="panel"') == 5 and html.count('class="st-item') == 5
    for step in range(1, 6):
        assert f'data-step="{step}"' in html
    for fid in ("name", "address", "households", "gfa", "kind", "unitTypes", "planned", "addDix", "ag_receipt", "ov_site", "use_llm",
                "submit", "sampleAll", "resetAll", "result", "wizardView", "resultView"):
        assert f'id="{fid}"' in html, fid
    boot = json.loads(re.search(r'<script type="application/json" id="boot">(.*?)</script>', html, re.S).group(1))
    assert len(boot["roles"]) == 7 and any(u["key"] == "office_general" for u in boot["uses"]) and all(u["key"] != "apartment" for u in boot["uses"])
    assert '<script src="/static/wizard.js">' in html and "{{" not in html


def test_every_form_id_used_by_wizard_js_exists_in_markup(client):
    """wizard.js가 $("id")로 찾는 id가 템플릿에 없으면 화면이 통째로 죽는다."""
    html = client.get("/app").text
    js = client.get("/static/wizard.js").text
    used = set(re.findall(r'\$\("([A-Za-z_]+)"\)', js))
    dynamic = {"access_code", "logout"}  # 조건부로만 있는 요소
    created_in_js = {"uses", "unitTypes", "staff", "intersections", "dintersections"}  # 컨테이너는 마크업에 있다
    missing = {i for i in used - dynamic if f'id="{i}"' not in html}
    assert not missing, missing
    assert created_in_js <= {i for i in created_in_js if f'id="{i}"' in html}


def test_static_assets_served_with_types(client):
    for path, ctype in (("/static/site.css", "text/css"), ("/static/site.js", "javascript"), ("/static/wizard.js", "javascript")):
        r = client.get(path)
        assert r.status_code == 200 and ctype in r.headers["content-type"], path
    assert client.get("/static/nope.js").status_code == 404
    assert client.get("/static/../app/main.py").status_code in (400, 404)  # 경로 탈출 불가


def test_css_has_dark_and_light_tokens_and_no_external_resources(client):
    css = client.get("/static/site.css").text
    assert 'data-theme="dark"' in css and "prefers-color-scheme: dark" in css and 'data-theme="light"' in css
    assert "http://" not in css and "https://" not in css and "@import" not in css  # CSP(self)와 오프라인 동작
    for page in ("/", "/guide", "/app", "/login"):
        html = client.get(page, follow_redirects=False).text
        assert not re.search(r'(?:src|href)="https?://', html), page


def test_pages_have_security_headers(client):
    for page in ("/", "/guide", "/app"):
        r = client.get(page)
        assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"], page


def test_result_dashboard_has_kpis_and_five_tabs(client):
    body = {"project": {"name": "대시", "address": "서울", "households": 1000, "gross_floor_area_m2": 180000, "floors": 25,
                        "unit_types": [{"exclusive_area_m2": 84, "households": 1000}], "planned_parking_spaces": 1500}}
    html = client.post("/ui/analyze", json=body).text
    assert html.count('class="kpi ') == 6 and html.count('role="tab"') == 5 and html.count('class="pane') == 5
    for needle in ("평가 대상", "평가 범위", "서비스수준(최저)", "주차 (법정 대비)", "지침 점검", 'data-action="edit"', "입력 없음"):
        assert needle in html, needle
    assert html.count("<svg") == 1  # 교차로가 없으면 주차 도표만


def test_error_partial_offers_way_back(client):
    html = client.post("/ui/analyze", json={"project": {"name": "x", "address": "y", "households": 0}}).text
    assert 'data-action="edit"' in html and "입력을 확인해 주세요" in html


def test_login_page_matches_site_shell(monkeypatch, tmp_path):
    monkeypatch.setenv("BETA_CODES", "alpha")
    from app.config import get_settings
    get_settings.cache_clear()
    try:
        c = TestClient(main.app)
        r = c.get("/login")
        assert r.status_code == 200 and "초대 코드" in r.text and "/static/site.css" in r.text
        assert 'location.href = "/app"' in r.text
    finally:
        monkeypatch.delenv("BETA_CODES")
        get_settings.cache_clear()
