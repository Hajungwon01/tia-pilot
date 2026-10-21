"""포트폴리오·문서용 화면 캡처(Playwright + 설치된 Chrome). 서버는 미리 띄워 둔다(예: mock 모드, 임시 DB).

    python scripts/capture_screens.py --url http://127.0.0.1:8011 --out docs/screenshots

필요: pip install playwright (브라우저 다운로드 없이 시스템 Chrome을 쓴다). 인증이 켜진 서버면 --code 초대코드.
캡처하는 화면: 첫 화면, 사용 안내, 마법사 단계(입력된 샘플), 결과 대시보드(요약·도표·수치표·점검). 라이트·다크 각각.
결과 화면의 숫자는 '4방향 샘플 채우기'로 만든 예시이고 실제 사업 값이 아니다.
"""
import argparse
import sys
from pathlib import Path

SCALE = 2
VIEW = {"width": 1440, "height": 900}


def shot(page, path: Path, full: bool = False, clip_h: int | None = None):
    kw = {"path": str(path), "full_page": full, "type": "jpeg", "quality": 90}  # PNG는 장당 1MB가 넘어 저장소에 올리기 무겁다
    if clip_h:
        kw["clip"] = {"x": 0, "y": 0, "width": VIEW["width"], "height": clip_h}
    page.screenshot(**kw)
    print("saved", path.name)


def run(url: str, out: Path, code: str | None) -> None:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for theme in ("light", "dark"):
            ctx = browser.new_context(viewport=VIEW, device_scale_factor=SCALE, color_scheme=theme, locale="ko-KR")
            page = ctx.new_page()
            page.on("dialog", lambda d: d.accept())
            if code:
                page.goto(f"{url}/login")
                page.fill("input", code)
                page.click("button")
                page.wait_for_load_state("networkidle")

            # 첫 화면(히어로만): 애니메이션이 끝나길 기다린 뒤 위쪽만 자른다
            page.goto(f"{url}/?theme={theme}")
            page.wait_for_timeout(1800)
            shot(page, out / f"landing-hero-{theme}.jpg", clip_h=700)

            # 사용 안내
            page.goto(f"{url}/guide?theme={theme}")
            page.wait_for_timeout(1200)
            shot(page, out / f"guide-{theme}.jpg", clip_h=900)

            # 마법사: 샘플 불러오기 → 단계별 화면
            page.goto(f"{url}/app?theme={theme}")
            page.wait_for_selector("#sampleAll")
            page.click("#sampleAll")
            page.wait_for_timeout(500)
            shot(page, out / f"wizard-step1-{theme}.jpg", clip_h=900)
            page.click('.st-item[data-step="2"]')
            page.wait_for_timeout(400)
            shot(page, out / f"wizard-step2-{theme}.jpg", clip_h=900)
            page.click('.st-item[data-step="3"]')
            page.check('input[name="mode"][value="detail"]')
            page.click("#sampleFour")
            page.wait_for_timeout(500)
            shot(page, out / f"wizard-step3-{theme}.jpg", clip_h=900)

            # 분석 실행 → 결과 대시보드
            page.click('.st-item[data-step="5"]')
            page.click("#submit")
            page.wait_for_selector("#resultView:not([hidden]) .kpi", timeout=60000)
            page.wait_for_timeout(1500)
            page.evaluate("window.scrollTo(0,0)")
            shot(page, out / f"result-summary-{theme}.jpg", clip_h=900)
            for tab, name in (("charts", "result-charts"), ("tables", "result-tables"), ("checks", "result-checks")):
                page.click(f'.tab[data-tab="{tab}"]')
                page.wait_for_timeout(500)
                page.evaluate("window.scrollTo(0,0)")
                shot(page, out / f"{name}-{theme}.jpg", clip_h=900)
            ctx.close()
        browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8011")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "docs" / "screenshots"))
    ap.add_argument("--code")
    a = ap.parse_args()
    run(a.url.rstrip("/"), Path(a.out), a.code)
    sys.exit(0)
