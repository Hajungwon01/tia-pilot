"""보고서 상태(ReportState) → Word(.docx) 교통영향평가서 초안.

구성: 표지(사업 개요·디스클레이머) → 작성 현황 요약 → 1~6장(별표 1 순서) → 부록 표.
미작성·MOCK 문장은 빨간 [미작성]으로, 환각 점검에 걸린 문장은 노란 강조 + 사유로 표시해
사람이 검토할 곳이 한눈에 보이게 한다.
"""
import re
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from app.core.llm_client import MOCK_PREFIX
from app.overview import overview_rows
from app.docx_forms import add_byeolji1, add_closing_pages, add_submission_page, cover_agency_lines
from app.facts import review_sections
from app.charts import SERIES_COLORS, build_charts, docx_bar_rows
from app.reflection import load_checklist
from app.state import ReportState

DISCLAIMER = "본 문서는 초안 작성 지원 도구가 생성한 초안이며, 최종 검토·날인은 교통기술사 등 전문가가 수행해야 합니다."
FONT = "맑은 고딕"

# 체크리스트 key 접두어 → (장 번호, 장 제목)  — 지침 별표 1 순서
CHAPTERS = [
    ("1", "서 론", ("intro", "scope")),
    ("2", "교통환경조사 분석", ("survey", "los")),
    ("3", "사업지구 및 주변지역의 장래 교통수요", ("demand", "unitrate", "modeshare", "parking")),
    ("4", "사업의 시행에 따른 문제점 및 개선대책", ("improve", "effect")),
    ("5", "교통개선대책안의 시행계획", ("plan",)),
    ("6", "참고자료", ("appendix",)),
]

# 체크리스트 key → 보고서 소제목(체크리스트의 규칙 설명문은 제목으로 쓰기엔 길어서 별도 지정)
KEY_TITLES = {
    "intro.overview": "사업의 개요", "intro.reason_timing": "교통영향평가 사유 및 시기의 적정성",
    "intro.scope": "교통영향평가 범위", "intro.summary": "결과 요약",
    "scope.target_years": "시간적 범위", "scope.spatial": "공간적 범위",
    "survey.facilities_traffic": "교통시설 및 교통소통 현황", "survey.landuse": "토지이용현황·계획 및 주변지역 개발계획",
    "survey.facility_plans": "교통시설 설치계획 및 교통관련 계획", "survey.signal_geometry": "교차로 차로운영·기하구조·신호",
    "survey.similar_parking": "유사 건축물 주차시설 현황", "survey.vehicle_classes": "차종별 교통량",
    "survey.delay_speed": "교차로 평균지체도 및 가로 평균통행속도", "survey.transit": "대중교통 운영현황",
    "survey.accidents": "교통사고 현황", "survey.ped_bike": "보행자·자전거 통행 실태",
    "survey.count_days": "교통량 조사 개요", "survey.block_analysis": "블록 내 이면도로·교차로 분석",
    "los.handbook_basis": "서비스수준 분석 기준", "los.links": "가로구간 분석", "los.intersections": "교차로 분석",
    "los.transit": "대중교통 분석", "los.pedestrian": "보행 분석", "los.bicycle": "자전거통행 분석",
    "demand.without_project": "사업 미시행 시 수요예측", "demand.with_project": "사업시행 시 수요예측",
    "demand.parking": "주차수요 예측", "demand.indicator_adjust": "교통지표 보정", "demand.method": "수요예측 방법",
    "demand.los_three_stage": "3단계 서비스수준 분석", "demand.peak_decision": "첨두일·첨두시 결정",
    "unitrate.basis": "교통유발 원단위 근거", "unitrate.peak_split": "원단위의 첨두시 구분",
    "unitrate.source_recency": "원단위 출처 및 조사시점", "unitrate.year_adjust": "기준년도 보정",
    "unitrate.occupancy": "평균 재차인원", "modeshare.basis": "교통수단 분담률", "parking.method": "주차수요 예측방법",
    "improve.roads_intersections": "주변가로 및 교차로", "improve.access": "진·출입 동선",
    "improve.transit": "대중교통", "improve.walk": "보행", "improve.bike": "자전거", "improve.parking": "주차",
    "improve.safety": "교통안전 및 기타",
    "effect.quantitative": "개선효과 분석(계량)", "effect.qualitative": "개선효과 분석(비계량)",
    "plan.actors_timing": "사업시행주체 및 시행시기", "plan.construction": "공사 중 교통처리대책",
    "plan.external_measures": "사업지구 외부 개선대책 시행계획",
    "appendix.traffic_counts": "교통량 조사자료", "appendix.unit_rates": "원단위 등 조사자료",
    "appendix.analysis_table": "교통영향평가 분석표(별지 제1호)", "appendix.citations": "인용자료",
}

NEEDS_INPUT_LABELS = {
    "project.gross_floor_area_m2": "건축 연면적(㎡) — 평가 대상 여부·범위 판정",
    "project.unit_types": "주택형별 전용면적·세대수 — 법정 주차대수 산정",
    "project.planned_parking_spaces": "계획 주차대수(건축계획) — 법정 대비 비교·원단위 수요 대비 점검",
    "project.expansion_areas": "증축: 기존 준공 연면적·증축 연면적(㎡) — 평가 대상 여부 판정",
    "demand.background_growth_rate": "배경교통량 연 증가율",
    "demand.project_share": "방면별 사업 교통량 배분율",
    "survey.signal_geometry": "교차로 차로운영·기하구조·신호주기·현시(현장 조사)",
    "survey.count_days": "첨두시 교통량 조사 결과(평일·토·일)",
    "los.intersections": "교차로 접근로별 교통량·포화교통류율·녹색시간",
}


def _set_font(run, size=None, bold=None, color=None, italic=None) -> None:
    run.font.name = FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color:
        run.font.color.rgb = RGBColor(*color)


def _style_base(doc: Document) -> None:
    st = doc.styles["Normal"]
    st.font.name = FONT
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    for name, size in (("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11.5)):
        h = doc.styles[name]
        h.font.name = FONT
        h.font.size = Pt(size)
        h.font.bold = True
        h.font.color.rgb = RGBColor(0x1F, 0x2D, 0x4D)
        h.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)


def _add_page_number(paragraph) -> None:
    run = paragraph.add_run()
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)
    _set_font(run, 9)


def _shade(cell, hex_fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _add_rich(paragraph, text: str, size=None, color=None, highlight=False) -> None:
    """**굵게** 만 처리한다(LLM이 마크다운을 섞어 쓰는 경우 대비)."""
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if not part:
            continue
        run = paragraph.add_run(part)
        _set_font(run, size=size, bold=(i % 2 == 1) or None, color=color)
        if highlight:
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def add_text_block(doc: Document, text: str, highlight=False) -> None:
    """여러 줄 본문. #/##/### 제목, -/* 목록, 마크다운 표(| 로 시작하는 줄)를 간단히 처리."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip()
        s = raw.strip()
        if not s:
            i += 1
            continue
        if s.startswith("|"):  # 마크다운 표
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i].strip())
                i += 1
            rows = [[c.strip() for c in r.strip("|").split("|")] for r in block if not re.fullmatch(r"\|[\s\-:|]+\|", r)]
            add_table(doc, rows[0], rows[1:])
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            p = doc.add_paragraph()
            _add_rich(p, m.group(2), size=11, highlight=highlight)
            for r in p.runs:
                r.bold = True
        elif re.match(r"^[-*]\s+", s):
            p = doc.add_paragraph(style="List Bullet")
            _add_rich(p, re.sub(r"^[-*]\s+", "", s), highlight=highlight)
        else:
            p = doc.add_paragraph()
            _add_rich(p, s, highlight=highlight)
        p.paragraph_format.space_after = Pt(4)
        i += 1


def add_table(doc: Document, header: list[str], rows: list[list[str]]) -> None:
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for c, h in zip(t.rows[0].cells, header):
        c.text = ""
        _set_font(c.paragraphs[0].add_run(h), size=9.5, bold=True)
        c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        _shade(c, "E8ECF4")
    for r in rows:
        cells = t.add_row().cells
        for c, v in zip(cells, r):
            c.text = ""
            _set_font(c.paragraphs[0].add_run(str(v)), size=9.5)
    doc.add_paragraph()


def add_overview_table(doc: Document, state: ReportState) -> None:
    """서울 수립지침 제24조③ 사업의 개요 필수 기재 항목. 비어 있는 항목은 빨간 [기재 필요]로 남긴다."""
    cap = doc.add_paragraph()
    _set_font(cap.add_run("사업의 개요 필수 기재 항목 (서울시 수립지침 제24조③)"), size=10, bold=True)
    cap.paragraph_format.keep_with_next = True
    t = doc.add_table(rows=1, cols=2)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for c, h in zip(t.rows[0].cells, ["항목", "내용"]):
        c.text = ""
        _set_font(c.paragraphs[0].add_run(h), size=9.5, bold=True)
        _shade(c, "E8ECF4")
    for r in overview_rows(state):
        a, b = t.add_row().cells
        a.text = b.text = ""
        _set_font(a.paragraphs[0].add_run(r["label"]), size=9.5)
        if r["value"] is None:
            _set_font(b.paragraphs[0].add_run("[기재 필요]" + (f" — {r['note']}" if r["note"] else "")), size=9.5, bold=True,
                      color=(0xC0, 0x00, 0x00))
        else:
            _set_font(b.paragraphs[0].add_run(r["value"] + (f" ({r['note']})" if r["note"] else "")), size=9.5)
    doc.add_paragraph()


def add_figure(doc: Document, spec: dict, no: int) -> None:
    """그림: 외부 이미지·폰트 없이 '█' 텍스트 막대 표로 그린다(Word에서 바로 편집 가능, 값은 모든 행에 병기)."""
    header, rows = docx_bar_rows(spec)
    cap = doc.add_paragraph()
    _set_font(cap.add_run(f"그림 {no}. {spec['title']}"), size=10, bold=True)
    cap.paragraph_format.keep_with_next = True
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for c, h in zip(t.rows[0].cells, header):
        c.text = ""
        _set_font(c.paragraphs[0].add_run(h), size=9, bold=True)
        _shade(c, "E8ECF4")
    for r in rows:
        cells = t.add_row().cells
        for c, (text, slot) in zip(cells, r):
            c.text = ""
            color = tuple(int(SERIES_COLORS[slot][0][i:i + 2], 16) for i in (1, 3, 5)) if slot else None
            _set_font(c.paragraphs[0].add_run(text), size=9 if not slot else 8, color=color)
    note = [spec["note"]] if spec.get("note") else []
    if spec.get("ref"):
        note.append(f"기준선: {spec['ref']['label']}")
    if note:
        n = doc.add_paragraph()
        _set_font(n.add_run("※ " + " / ".join(note)), size=8.5, italic=True, color=(0x70, 0x70, 0x70))
    doc.add_paragraph()


def _placeholder(doc: Document, msg: str) -> None:
    p = doc.add_paragraph()
    _set_font(p.add_run(msg), size=10.5, bold=True, color=(0xC0, 0x00, 0x00))


def _chapter_items(chapter_prefixes: tuple[str, ...]) -> list[dict]:
    return [i for i in load_checklist()["items"]
            if i["check"] == "key" and i["key"].split(".")[0] in chapter_prefixes]


def _los_rows(state: ReportState) -> list[list[str]]:
    rows = []
    for name, v in state.los.items():
        for r in v["results"]:
            rows.append([name, r["approach"], f"{r['capacity']:.0f}", f"{r['vc_ratio']:.2f}",
                         f"{r['delay']:.1f}", r["los"]])
        rows.append([name, "교차로 전체", "-", "-", f"{v['avg_delay']:.1f}", v["grade"]])
    return rows


def _stage_rows(state: ReportState) -> list[list[str]]:
    rows = []
    for name, years in state.stages.items():
        for y, st in years.items():
            cell = lambda k: f"{st[k]['avg_delay']:.1f} ({st[k]['grade']})"  # noqa: E731
            rows.append([name, f"준공 후 {y}년", cell("without"), cell("with"), cell("improved"),
                         f"{st['delay_reduction']:.1f}"])
    return rows


def _scenario_rows(state: ReportState) -> list[list[str]]:
    rows = []
    for name, years in state.stages.items():
        for y, st in years.items():
            for s in (st.get("scenarios") or {}).get("scenarios", []):
                rows.append([name, f"준공 후 {y}년", "물리적 개선(검토 후보)" if s["physical"] else "신호 조정", s["label"],
                             f"{s['avg_delay']:.1f}", s["grade"], f"{s['delay_reduction']:.1f}", "; ".join(s["changes"]) or "-"])
    return rows


def _add_rate_basis(doc: Document, state: ReportState) -> None:
    """부록: 유발·주차 원단위의 근거(유사시설 조사 요약표·단지 목록, 직접 입력값). 임시값만 쓴 경우는 그렇다고만 적는다."""
    p = state.project
    t = state.trips
    if p.rate_basis != "evidence" and not p.rate_overrides.given() and p.car_occupancy is None:
        doc.add_paragraph("원단위 근거: 임시값(근거 자료 없음) — 수치는 잠정입니다.", style="List Bullet")
        return
    doc.add_heading("원단위 근거", level=2)
    if t and t.rate_notes:
        for n in t.rate_notes:
            doc.add_paragraph(n, style="List Bullet")
    if p.rate_basis == "evidence":
        from app.unit_evidence import derive_rates, facility_rows

        ev = derive_rates(car_occupancy=p.car_occupancy, overrides=p.rate_overrides)
        doc.add_paragraph("유사시설 조사 자료: 국토교통부 교통영향평가정보지원시스템(tia.molit.go.kr)에 공개된 사업별 원단위정보(유사시설). "
                          "조사일 3년 이내, 서울 우선(3건 미만이면 수도권), 중앙값(이상치 제외). 평가서가 입력한 값을 이 도구가 검증하지는 않았습니다.")
        add_table(doc, ["항목", "중앙값", "25~75%", "사례 수", "범위", "지침 요건(실측 1+자료 3 또는 실측 3)"], ev.basis_rows())
        doc.add_paragraph("'발생원단위(인/일)'는 시스템 설명서로 정의를 확인하지 못해 총 활동인구(양방향 합) ÷ 세대수로 해석했습니다. "
                          "참고로 KTDB 가구통행실태조사(2016) 서울 아파트 거주자 통행은 집 출발 2.37·집 도착 2.36, 합 4.73인/세대·일로(조사 3년 초과, 참고용) "
                          "유사시설 값은 그 약 76% 수준이라 과소할 수 있습니다. 직접 조사한 값이 있으면 '원단위 직접 입력'으로 바꿀 수 있습니다.",
                          style="List Bullet")
        rows = facility_rows(ev)
        if rows:
            doc.add_paragraph("원단위 산출에 쓴 유사시설(조사일 최신순, 최대 40곳):")
            add_table(doc, ["단지", "조사일", "지역", "조사방법", "세대수"], rows)
    if p.rate_overrides.given() and p.rate_overrides.source.strip():
        doc.add_paragraph(f"직접 입력한 원단위 출처: {p.rate_overrides.source.strip()}", style="List Bullet")


def add_toc(doc: Document) -> None:
    """Word 목차 필드(제목 1~3단계). 쪽번호는 Word에서 열어 필드를 갱신해야 채워진다."""
    p = doc.add_paragraph()
    run = p.add_run()
    parts = []
    el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), "begin"); parts.append(el)
    el = OxmlElement("w:instrText"); el.set(qn("xml:space"), "preserve"); el.text = 'TOC \\o "1-3" \\h \\z \\u'; parts.append(el)
    el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), "separate"); parts.append(el)
    for e in parts:
        run._r.append(e)
    hint = p.add_run("(Word에서 이 문서를 열면 '필드를 업데이트하시겠습니까?'라고 묻습니다. '예'를 누르면 목차가 채워집니다. "
                     "수동으로는 이 영역을 우클릭 → '필드 업데이트'.)")
    _set_font(hint, size=9, italic=True, color=(0x70, 0x70, 0x70))
    end = p.add_run()
    el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), "end"); end._r.append(el)


def _new_section(doc: Document, landscape: bool) -> None:
    """새 쪽에서 시작하는 구역. A4 가로/세로로 전환한다(머리글·바닥글은 앞 구역을 이어받음)."""
    from docx.enum.section import WD_ORIENT, WD_SECTION

    sec = doc.add_section(WD_SECTION.NEW_PAGE)
    w, h = Cm(21.0), Cm(29.7)
    sec.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
    sec.page_width, sec.page_height = (h, w) if landscape else (w, h)
    sec.left_margin = sec.right_margin = Cm(2.0 if landscape else 2.5)


def _request_field_update(doc: Document) -> None:
    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is None:
        uf = OxmlElement("w:updateFields")
        uf.set(qn("w:val"), "true")
        settings.append(uf)


def build_docx(state: ReportState, today: date | None = None, show_refs: bool = True) -> Document:
    today = today or date.today()
    flagged = review_sections(state)
    doc = Document()
    _style_base(doc)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)  # A4 (지침 제24조 규격은 별도 확인 필요)
    sec.left_margin = sec.right_margin = Cm(2.5)
    sec.top_margin = sec.bottom_margin = Cm(2.3)

    hp = sec.header.paragraphs[0]
    hp.text = ""
    _set_font(hp.add_run("[초안] " + DISCLAIMER), size=8, color=(0x80, 0x00, 0x00))
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_page_number(fp)

    # ── 표지 ──
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(80)
    _set_font(p.add_run("교통영향평가서 (초안)"), size=26, bold=True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_font(p.add_run(state.project.name), size=16)
    doc.add_paragraph()
    pr = state.project
    add_table(doc, ["항목", "내용"], [
        ["사업명", pr.name], ["위치", pr.address], ["용도", "공동주택(아파트)" if pr.land_use.value == "apartment" else pr.land_use.value],
        ["세대수", f"{pr.households:,}세대"],
        ["건축 연면적", f"{pr.gross_floor_area_m2:,.0f}㎡" if pr.gross_floor_area_m2 else "미입력"],
        ["작성일", today.isoformat()],
        *cover_agency_lines(state.agency, bool((state.scope or {}).get("abbreviated")), f"{today.year}년 {today.month}월"),  # 서울 지침 별표 11 표지양식
    ])
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_font(p.add_run("※ " + DISCLAIMER), size=10, bold=True, color=(0x80, 0x00, 0x00))
    doc.add_page_break()
    add_submission_page(doc, state)  # 제출문(제24조⑤), 서명·날인란(제24조⑩)

    # ── 작성 현황 ──
    doc.add_heading("작성 현황 요약 (검토용)", level=1)
    r = state.reflection
    if r:
        doc.add_paragraph(f"지침 체크리스트(v0.3) 자동 점검: {r['passed']} / {r['auto_total']} 항목 충족. "
                          f"사람이 직접 확인할 항목 {len(r['manual'])}건.")
        for rule in r.get("rules", []):
            doc.add_paragraph(f"[{rule['label']}] {rule['ref']}: {rule['message']}", style="List Bullet")
    if state.needs_input:
        doc.add_heading("입력이 더 필요한 항목", level=2)
        for k in state.needs_input:
            doc.add_paragraph(NEEDS_INPUT_LABELS.get(k, k), style="List Bullet")
    if flagged:
        doc.add_heading("계산 결과와 불일치 가능 — 검토 필요", level=2)
        for k, issues in flagged.items():
            doc.add_paragraph(f"{k}: " + "; ".join(issues), style="List Bullet")
    if state.warnings:
        doc.add_heading("작성 시 주의", level=2)
        for w in state.warnings:
            doc.add_paragraph(w, style="List Bullet")
    doc.add_page_break()

    # ── 목차 ──
    doc.add_heading("목 차", level=1)
    add_toc(doc)
    doc.add_page_break()

    # ── 1~6장 ──
    charts = build_charts(state)
    fig_no = 0
    for num, title, prefixes in CHAPTERS:
        doc.add_heading(f"{num}. {title}", level=1)
        for item in _chapter_items(prefixes):
            key = item["key"]
            doc.add_heading(KEY_TITLES.get(key, item["text"]), level=3)
            if show_refs:  # 검토용: 지침 조문 근거를 소제목 아래에 작게 표시
                note = doc.add_paragraph()
                _set_font(note.add_run(f"근거: {item['ref']}"), size=8.5, italic=True, color=(0x70, 0x70, 0x70))
            body = state.sections.get(key, "")
            if not body.strip() or body.startswith(MOCK_PREFIX):
                _placeholder(doc, "[미작성] 입력 또는 작성 필요" + (" (LLM 미연결 자리표시)" if body.startswith(MOCK_PREFIX) else ""))
            else:
                add_text_block(doc, body, highlight=key in flagged)
                if key in flagged:
                    _placeholder(doc, "⚠ 검토 필요(계산 결과와 불일치 가능): " + "; ".join(flagged[key]))
            if key == "intro.overview":
                add_overview_table(doc, state)
        # 장 끝 표
        if num == "2" and state.los:
            doc.add_heading("현황 LOS 분석표", level=3)
            add_table(doc, ["교차로", "접근로", "용량(대/시)", "v/c", "지체(초/대)", "LOS"], _los_rows(state))
            for spec in charts["vc"]:
                fig_no += 1
                add_figure(doc, spec, fig_no)
        if num == "3" and state.stages:
            doc.add_heading("3단계 LOS 비교표 (사업 미시행 / 시행 / 개선 후)", level=3)
            add_table(doc, ["교차로", "목표년도", "미시행", "시행", "개선 후", "개선 효과(초 감소)"], _stage_rows(state))
            for spec in charts["stage"]:
                fig_no += 1
                add_figure(doc, spec, fig_no)
            sc_rows = _scenario_rows(state)
            if sc_rows:
                doc.add_heading("개선 시나리오 비교표 (검토 후보)", level=3)
                add_table(doc, ["교차로", "목표년도", "구분", "개선안", "평균지체(초/대)", "LOS", "지체 감소(초/대)", "변경 내용"], sc_rows)
                n = doc.add_paragraph()
                _set_font(n.add_run("※ 지체 감소는 사업 시행 시(초기 대기차량 미적용) 대비. 물리적 개선은 용지·도로폭·교통안전 검토 전의 "
                                    "검토 후보이며 시행 가능성은 판단하지 않았습니다."), size=8.5, italic=True, color=(0x70, 0x70, 0x70))
        if num == "3":
            for spec in charts["parking"]:
                fig_no += 1
                add_figure(doc, spec, fig_no)

    doc.add_heading("부록: 분석 기준·가정", level=1)
    basis = ["LOS 등급: 도로용량편람(국토교통부, 2013) <표 8-2> 평균 제어지체 기준, d1(식 8-47)·d2(식 8-50) — 원문 확인."]
    if state.detailed_intersections:
        basis += [
            "상세 입력 교차로: 편람 제8장 운영분석 절차(교통량 보정, 차로군 분류, 좌·우회전 직진환산, 노변마찰, 포화교통류율 "
            "식 8-38, 연동계수 PF·초기대기지체 d3 포함)로 계산했고, 편람 풀이 예제로 검증했습니다.",
            "상세 입력 미지원: 우회전 2차로 이상 공용(편람에 계산식 없음). 좌회전 CASE 5는 식 8-14·8-16·8-18·8-20으로 계산하며 차로수 N은 맨 왼쪽 전용 차로를 포함합니다. 현시별 녹색시간은 녹색신호시간 G이며 유효녹색은 G−0.3초입니다.",
            "상세 입력의 '개선 후'는 신호주기·황색을 고정하고 현시별 녹색시간을 임계 V/S에 비례해 재배분한 계산입니다. "
            "차로 증설·전용 좌회전 차로 신설·신호주기 조정은 '개선 시나리오'로 편람 엔진을 다시 돌려 비교했으며(주기 탐색 60~180초), "
            "시행 가능성(용지·도로폭·안전)은 판단하지 않았으나, 전용 좌회전 차로 후보에는 평면교차로 설계 지침(2004) 3.3.1(4)·(5)의 "
            "필요 길이(5m 단위 올림, 신호 1주기당 좌회전 도착대수 기준; 설계속도는 접근로의 도로 기능별 구분에서 도로의 구조·시설 기준에 관한 규칙 제8조①로 정하고 입력이 없으면 50km/h로 가정)를 병기했습니다.",
        ]
    if state.intersections:
        basis += [
            "간이 입력 교차로: 포화교통류율은 입력값이며 연동계수 PF=1.0, 추가지체 d3=0, 차로군 분류·보정계수는 미반영입니다.",
            "간이 입력의 개선 후 분석은 신호주기 고정·녹색시간 재배분만 반영한 간이 계산입니다.",
        ]
    basis.append("유발교통량: 표준 원단위 기반 직접수요예측. 원단위가 임시값이면 수치는 잠정값입니다.")
    for line in basis:
        doc.add_paragraph(line, style="List Bullet")
    _add_rate_basis(doc, state)

    # 열이 많은 법정 서식(별지 제1호, 참여전문인력 명단)은 가로 방향 쪽에 배치한다.
    _new_section(doc, landscape=True)
    add_byeolji1(doc, state)  # 별지 제1호 서식 교통영향평가 분석표
    add_closing_pages(doc, state)  # 끝문·참여전문인력(제24조⑥~⑧)
    _request_field_update(doc)  # 열 때 목차 필드 갱신 안내
    return doc


def export_docx(state: ReportState, path: str | Path, today: date | None = None, show_refs: bool = True) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    build_docx(state, today, show_refs).save(path)
    return path
