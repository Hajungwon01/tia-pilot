"""DOCX에 들어가는 법정 서식 부분.

- 지침 제24조: 겉표지(평가대행자·평가대행업체), 제출문, 끝문(참여전문인력·업체 정보), 서명·날인란
- 별지 제1호 서식 '교통영향평가 분석표'(제22조제5항, 2016.1.22 개정): 개요·수요예측·정량분석표
원칙: 이 도구가 계산한 값만 채우고, 사람·업체 정보나 계산하지 않는 칸은 [기재 필요]로 둔다(지어내지 않음).
"""
from docx.document import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from app.state import PARTICIPATION_ROLES, AgencyInfo, ReportState

BLANK = "[기재 필요]"
EMPTY = ""  # 별지 서식의 조밀한 표는 법정 서식처럼 빈 칸으로 둔다(작성자가 기재)


def val(x) -> str:
    return str(x) if x not in (None, "", []) else BLANK


def _table(doc: Document, header: list[str], rows: list[list[str]], font=9):
    from app.docx_export import add_table  # 순환 임포트 방지

    add_table(doc, header, rows)


def _para(doc: Document, text: str, size=10.5, bold=False, align=None, color=None):
    from app.docx_export import _set_font

    p = doc.add_paragraph()
    if align:
        p.alignment = align
    _set_font(p.add_run(text), size=size, bold=bold, color=color)
    return p


# ── 제24조 서식 ───────────────────────────────────────────────

def cover_agency_lines(a: AgencyInfo | None) -> list[list[str]]:
    """겉표지: 평가대행자와 평가대행업체(제24조⑤)."""
    a = a or AgencyInfo()
    return [["평가대행업체", val(a.agency_name)], ["평가대행자(책임자)", val(a.lead_name)]]


def add_submission_page(doc: Document, state: ReportState) -> None:
    """제출문: 평가대행업체(등록번호·등록일·책임자)와 제출일(제24조⑤), 서명·날인(제24조⑩)."""
    a = state.agency or AgencyInfo()
    _para(doc, "제 출 문", size=22, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER).paragraph_format.space_before = Pt(60)
    doc.add_paragraph()
    _para(doc, f"{val(a.client_name)} 귀하", size=12)
    _para(doc, f"「도시교통정비 촉진법」 및 「교통영향평가 지침」에 따라 '{state.project.name}' 교통영향평가서를 제출합니다.", size=12)
    doc.add_paragraph()
    _table(doc, ["항목", "내용"], [
        ["평가대행업체", val(a.agency_name)], ["등록번호", val(a.registration_no)],
        ["등록일", val(a.registration_date)], ["책임자", val(a.lead_name)],
        ["제출일", val(a.submission_date)],
    ])
    doc.add_paragraph()
    _para(doc, "책임자  (서명 또는 날인)  ____________________", size=11, align=WD_ALIGN_PARAGRAPH.RIGHT)
    _para(doc, "평가대행업체 대표자  (서명 또는 날인)  ____________________   (직인)", size=11, align=WD_ALIGN_PARAGRAPH.RIGHT)
    _para(doc, "※ 서명·날인은 사람이 직접 해야 하며 본 도구가 대신하지 않습니다(지침 제24조⑩).", size=8.5,
          color=(0x70, 0x70, 0x70))
    doc.add_page_break()


def add_closing_pages(doc: Document, state: ReportState) -> None:
    """끝문: 용역 정보와 참여전문인력 명단(제24조⑥~⑧)."""
    a = state.agency or AgencyInfo()
    doc.add_heading("끝 문", level=1)
    _table(doc, ["항목", "내용"], [
        ["평가 대행용역 수행기간", val(a.service_period)],
        ["보고서 인쇄업체", val(a.printer)],
        ["구상용역 수행업체", val(a.concept_design_firm)],
        ["평가대행업체 주소·전화", f"{val(a.agency_address)} / {val(a.agency_phone)}"],
        ["사업자 주소·전화", f"{val(a.client_address)} / {val(a.client_phone)}"],
        ["대행비용 산정기준에 따른 가격 산출근거", "첨부함" if a.cost_basis_attached else "[첨부 필요]"],
        ["용역계약서 사본", "첨부함" if a.contract_copy_attached else "[첨부 필요]"],
    ])
    doc.add_heading("평가 대행용역 참여전문인력 명단", level=2)
    _para(doc, "※ 규칙 별표 1에 따라 등록된 기술인력과 등록기준에 미달되어 등록하지 못한 기술인력을 구분하여 작성(제24조⑦). "
               "개인별 작업일정표를 첨부해야 합니다.", size=9, color=(0x70, 0x70, 0x70))
    header = ["구분", "성명", "소속", "직책", "근무기간", "자격명·번호"] + PARTICIPATION_ROLES
    rows = []
    for m in sorted(a.staff, key=lambda x: not x.registered):
        rows.append(["등록" if m.registered else "미등록", m.name, val(m.affiliation), val(m.position),
                     val(m.period), val(m.qualification)] + ["○" if r in m.roles else "" for r in PARTICIPATION_ROLES])
    if not rows:
        rows.append([BLANK, "", "", "", "", ""] + [""] * len(PARTICIPATION_ROLES))
    _table(doc, header, rows)
    doc.add_paragraph("참여정도 구분: " + ", ".join(PARTICIPATION_ROLES) + " (제24조⑧)")


# ── 별지 제1호 서식 ───────────────────────────────────────────

def _peak_for_form(state: ReportState):
    """유발교통량 칸에 쓸 첨두: 총량이 큰 쪽. 반환 (이름, PeakTrips)."""
    t = state.trips
    return ("AM", t.am_peak) if t.am_peak.total >= t.pm_peak.total else ("PM", t.pm_peak)


def add_byeolji1(doc: Document, state: ReportState) -> None:
    """별지 제1호 서식 교통영향평가 분석표. 계산한 칸만 채우고 나머지는 빈 서식으로 남긴다."""
    from app.trip_generation import load_rates

    p = state.project
    a = state.agency or AgencyInfo()
    doc.add_heading("별지 제1호 서식 교통영향평가 분석표 (제22조제5항 관련)", level=1)
    _para(doc, "※ 이 도구가 계산한 칸만 채웠습니다. **빈 칸과 [기재 필요] 칸은 현장조사·사업계획 자료가 필요하며 작성자가 채워야 합니다.** "
               "단기=준공 후 1년, 장기=준공 후 3년으로 대응했습니다(지침 제5조①1, 대응은 본 도구의 해석).",
          size=9, color=(0x80, 0x00, 0x00))

    doc.add_heading("1) 개요", level=2)
    _table(doc, ["항목", "내용"], [
        ["연도", val(a.submission_date[:4] if a.submission_date else "")],
        ["평가업체 및 책임자", f"{val(a.agency_name)} / {val(a.lead_name)}"],
        ["사업명", p.name],
        ["분석년도 — 기준", BLANK], ["분석년도 — 단기", "준공 후 1년"], ["분석년도 — 장기", "준공 후 3년"],
    ])

    doc.add_heading("2) 교통수요예측", level=2)
    if not state.trips:
        _para(doc, BLANK, color=(0xC0, 0, 0))
    else:
        t = state.trips
        r = load_rates()[p.land_use.value]
        prov = "" if t.rates_status != "PROVISIONAL" else " (임시 원단위)"
        sh = r["mode_share"]
        pk_name, pk = _peak_for_form(state)

        doc.add_heading("① 활동인구 분석", level=3)
        _para(doc, "※ 본 도구의 원단위는 세대당 일 사람통행(인통행/일)이며 상근·방문 구분은 제공하지 않아 방문 칸에 기재했습니다.",
              size=8.5, color=(0x70, 0x70, 0x70))
        per_hh = r["daily_person_trips_per_household"]
        _table(doc, ["용도구분", "면적(㎡, 세대)", "발생원단위(인/세대) 방문", "총 활동인구(인) 방문", "상근", "비고"], [
            [BLANK + " (전용면적 구간)", f"{p.households:,}세대", f"{per_hh:g}{prov}", f"{t.daily_person_trips:,.0f}", "-",
             "단기·장기 동일 원단위 적용"],
        ])

        doc.add_heading("② 수단분담률 분석", level=3)
        _table(doc, ["용도구분", "승용차", "택시", "버스", "전철", "기타", "평균재차인원"], [
            [BLANK + " (전용면적 구간)", f"{sh['car'] * 100:.0f}%{prov}", BLANK + " (미구분)", f"{sh['bus'] * 100:.0f}%",
             f"{sh['subway'] * 100:.0f}%", f"{sh['walk_other'] * 100:.0f}%", f"{r['car_occupancy']:g}명/대"],
        ])
        _para(doc, "※ 단기·장기 동일 분담률 적용(기준년도 값은 제공하지 않음).", size=8.5, color=(0x70, 0x70, 0x70))

        doc.add_heading("③ 유발교통량", level=3)
        _para(doc, f"첨두시간대 기준: {pk_name} 첨두(유발 총량이 큰 쪽). 승용차 통행만 계산하며 택시·버스·기타는 제공하지 않습니다.",
              size=8.5, color=(0x70, 0x70, 0x70))
        _table(doc, ["구분", "", "계", "승용차", "택시", "버스", "기타"], [
            ["첨두교통량(대/시) 사업지구", "유입", f"{pk.in_trips:.0f}", f"{pk.in_trips:.0f}", "-", "-", "-"],
            ["첨두교통량(대/시) 사업지구", "유출", f"{pk.out_trips:.0f}", f"{pk.out_trips:.0f}", "-", "-", "-"],
            ["첨두교통량(대/시) 주변가로", "유입", EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
            ["첨두교통량(대/시) 주변가로", "유출", EMPTY, EMPTY, EMPTY, EMPTY, EMPTY],
            ["첨두시간대", "", f"사업지구: {pk_name}", "", "주변가로:", EMPTY, ""],
        ])

        pk = state.parking
        doc.add_heading("④ 주차수요 원단위", level=3)
        if pk:
            prov = pk["rate_status"] == "PROVISIONAL"
            area = pk["total_exclusive_area_m2"]
            per_m2 = (f"{pk['demand_per_household'] * pk['utilization'] / (area / p.households):.4f}" if area else
                      f"세대당 {pk['demand_per_household']:g}대")
            src = "임시값(근거 자료 없음)" if prov else (pk["rate_source"] or BLANK)
            _para(doc, "※ 면적은 주택 전용면적 합계(㎡)이며, 세대당 원단위에 이용효율을 곱해 대/㎡로 환산했습니다. 복합용도의 다른 용도 주차수요는 포함하지 않았습니다.",
                  size=8.5, color=(0x70, 0x70, 0x70))
            _table(doc, ["용도구분", "면적(㎡)", "주차원단위(대/㎡)", "이용효율", "주차수요(대)", "원단위 자료출처"], [[
                BLANK + " (전용면적 구간)", f"{area:,.0f}" if area else f"{p.households:,}세대", per_m2 + (" (임시)" if prov else ""),
                f"{pk['utilization']:g}", f"{pk['demand']:,.0f}", src]])
        else:
            _table(doc, ["용도구분", "면적(㎡)", "주차원단위(대/㎡)", "이용효율", "주차수요(대)", "원단위 자료출처"], [[EMPTY] * 6])
        doc.add_heading("⑤ 주차수요 예측결과 및 확보 내역", level=3)
        demand = f"{pk['demand']:,.0f}" if pk else EMPTY
        legal = f"{pk['legal_total']:,}" if pk and pk["legal_total"] is not None else EMPTY
        planned = f"{pk['planned']:,}" if pk and pk["planned"] is not None else EMPTY
        _para(doc, "※ 단기·장기 동일 원단위를 적용해 같은 값입니다. P 요소법·누적 주차법은 계산하지 않았습니다.", size=8.5, color=(0x70, 0x70, 0x70))
        _table(doc, ["분석방법", "단기", "장기", "구분", "주차대수"], [
            ["원단위법", demand, demand, "법적대수", legal], ["P 요소법", EMPTY, EMPTY, "건축계획", planned],
            ["누적 주차법", EMPTY, EMPTY, "분석대수", demand], ["기타", EMPTY, EMPTY, "적용방법", "원단위법(지침 제15조②)" if pk else EMPTY],
        ])

    doc.add_heading("3) 교통영향평가 내용 (정량분석표)", level=2)
    n_ix = len(state.stages)
    items = [
        ("가로 및 교차로", ["도로신설", "도로확폭", "기하구조 개선", "좌회전포켓, 차선 수 조정, U턴", "교차로 신호등 설치", "교차로 신호주기 조정"]),
        ("진출입 동선", ["신설", "확폭, Set-back", "완화차선", "위치조정", "운영개선(일방통행 등)", "가각정리"]),
        ("주차", ["주차면수 추가", "주차면수 제거", "진출입구 신설, 위치·구조조정"]),
        ("대중교통", ["버스정류장 신설", "택시정류장 신설", "정류장 위치조정", "대중교통노선조정, 추가"]),
        ("보행", ["보도신설", "보도확폭, Set-back", "보행동선조정, 보행전용", "횡단보도 신설, 위치조정", "횡단보도 신호등 설치"]),
        ("안전", ["과속방지턱 시설", "미끄럼방지시설", "각종 안내판 시설", "각종 경고등 시설", "노면마킹, 표지병", "자전거 관련시설", "기타, 방음벽 등"]),
    ]
    rows = []
    for grp, names in items:
        for nm in names:
            cnt = EMPTY
            note = ""
            if nm == "교차로 신호주기 조정" and n_ix:
                cnt = f"{n_ix}건(검토)"
                note = "녹색시간 재배분 간이 검토(효과는 3단계 비교표 참조)"
            rows.append([grp, nm, cnt, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, note])
    _table(doc, ["항목", "교통영향평가(안)", "건수", "연장(m)", "폭원(m)", "면적(㎡)", "시행주체", "완공년도", "개선비용(백만원)", "비고"], rows)
    _table(doc, ["시간절감 분석", "인접 4개 교차로 개선 전후 시간절감(시간/년, 백만원/년)"], [
        ["1번 교차로", EMPTY], ["2번 교차로", EMPTY], ["3번 교차로", EMPTY], ["4번 교차로", EMPTY],
        ["소계(백만원)", EMPTY], ["합계(백만원)", EMPTY]])
    _para(doc, "주) 교통영향평가에 기여한 부지는 표준지 공시지가를 기준으로 적용하고 기타 교통영향평가 비용은 실제로 투입한 비용을 적용한다. "
               "시간가치의 적용은 버스 및 승용차로 구분하고 수단별 표준시간 가치를 적용한다.", size=8.5)
    _para(doc, "비고) 활동인구, 수단분담률 및 주차수요, 원단위상의 용도구분은 별지 제1호 서식 비고의 용도구분(주거 1~8 등, 전용면적 기준)에 따른다.",
          size=8.5)
