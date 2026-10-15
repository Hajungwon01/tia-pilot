"""사업의 개요 필수 기재 항목 표(서울특별시 교통영향평가 수립지침 제24조③).

계산된 값(법정·수요 주차대수, 발생교통량, Swa 등)은 자동으로 채우고, 사람이 알려줘야 하는 값은 비어 있으면
'기재 필요'로 표시한다. 새 수치를 만들지 않는다.
"""
from app.eligibility import use_table
from app.state import ReportState

NEED = "[기재 필요]"
KIND_LABELS = {"new": "신축", "expansion": "증축", "use_change": "용도변경"}


def _area(v: float | None) -> str | None:
    return None if v is None else f"{v:,.0f}㎡"


def _count(v: int | None) -> str | None:
    return None if v is None else f"{v:,}대"


def overview_rows(state: ReportState) -> list[dict]:
    """[{label, value, source: auto|input|missing, note}] — value는 missing이면 None."""
    p, ov = state.project, state.project.overview
    ag = state.agency
    rows: list[dict] = []

    def add(label, value, source="input", note="", keep_note=False):
        """note는 비었을 때의 안내. keep_note=True면 값이 있어도 단서로 함께 보여준다(증축 합산·지하 미입력·자동 표기 등)."""
        value = value if value not in ("", None) else None
        rows.append({"label": label, "value": value, "source": "missing" if value is None else source,
                     "note": note if value is None or keep_note else ""})

    add("인·허가 관련 법규", ov.permit_laws)
    add("사업명", p.name, "auto")
    add("위치", p.address, "auto")
    contact = " / ".join(x for x in ((ag.client_name if ag else ""), (ag.client_phone if ag else "")) if x)
    add("사업시행자(연락처)", contact if ag and ag.client_name and ag.client_phone else None, "input",
        "사업자명과 연락처가 모두 필요")
    add("사업기간", ov.project_period)
    add("도시계획사항", ov.urban_planning)
    uses = [ov.actual_use or "공동주택(아파트)"] + [f"{use_table()[u.use]['label']} {u.area_m2:,.0f}㎡" for u in p.other_uses]
    add("실제 용도", ", ".join(uses), "input" if ov.actual_use else "auto",
        "" if ov.actual_use else "입력이 없어 공동주택(아파트)으로 표기", keep_note=True)

    elig = (state.scope or {}).get("eligibility") or {}
    area = elig.get("gross_floor_area_m2")
    add("대지면적", _area(ov.site_area_m2))
    add("건축연면적", _area(area) if area else None, "auto",
        "증축은 준공 면적 + 증축 면적 합산" if p.project_kind == "expansion" else "", keep_note=p.project_kind == "expansion")
    add("건폐율", None if ov.building_coverage_pct is None else f"{ov.building_coverage_pct:g}%")
    add("용적률", None if ov.floor_area_ratio_pct is None else f"{ov.floor_area_ratio_pct:g}%")
    scale = None
    if p.floors is not None:
        scale = (f"지하 {ov.basement_floors}층, " if ov.basement_floors is not None else "") + f"지상 {p.floors}층, {p.households:,}세대"
    add("규모", scale, "input", "지하 층수 미입력(지상 층수·세대수만 표기)" if scale and ov.basement_floors is None else
        "" if scale else "지상·지하 층수와 세대수가 필요", keep_note=True)
    swa = elig.get("swa")
    add("Swa값(복합용도)", (f"{swa:,.0f} (10,000 이상이면 대상)" if elig.get("mixed_use") and swa is not None else
                          "해당 없음(공동주택 단일 용도)" if swa is not None else None), "auto")

    pk = state.parking or {}
    if pk:
        legal = f"법정 {pk['legal_total']:,}대" if pk.get("legal_total") is not None else None
        parts = [legal, f"수요 {pk['demand']:,.0f}대" + (" (임시 원단위)" if pk["rate_status"] == "PROVISIONAL" else "")]
        if pk.get("planned") is not None:
            parts.append(f"계획 {pk['planned']:,}대")
            if pk.get("planned_vs_legal_pct") is not None:
                parts.append(f"법정 대비 {pk['planned_vs_legal_pct']:.0f}%")
        add("주차시설 — 법정·수요·계획 대수와 비율", ", ".join(x for x in parts if x) if legal and pk.get("planned") is not None else None,
            "auto", "법정 대수(주택형별 입력)와 계획 대수가 모두 있어야 비율을 적을 수 있음")
    else:
        add("주차시설 — 법정·수요·계획 대수와 비율", None, "auto")
    mech = ", ".join(x for x in (f"자주식 {ov.parking_self:,}대" if ov.parking_self is not None else "",
                                 f"기계식 {ov.parking_mechanical:,}대" if ov.parking_mechanical is not None else "") if x)
    add("주차시설 — 자주식·기계식 구분", mech if ov.parking_self is not None and ov.parking_mechanical is not None else None,
        "input", "자주식과 기계식 대수를 모두 입력(없으면 0)")
    special = [(n, v) for n, v in (("장애인", ov.parking_accessible), ("여성", ov.parking_women), ("경차", ov.parking_compact),
                                  ("관광버스", ov.parking_tour_bus)) if v is not None]
    add("주차시설 — 장애인·여성·경차·관광버스",
        ", ".join(f"{n} {v:,}대" for n, v in special) if len(special) == 4 else None, "input", "네 가지를 모두 입력(없으면 0)")

    t = state.trips
    years = (state.scope or {}).get("target_years", [1, 3])
    if t:
        add("발생교통량 — 사업지(승용차)",
            f"준공 후 {'·'.join(str(y) for y in years)}년 동일 원단위 적용: 일 {t.daily_vehicle_trips:,.0f}대/일, "
            f"AM 첨두 {t.am_peak.total:,.0f}대/시, PM 첨두 {t.pm_peak.total:,.0f}대/시"
            + {"PROVISIONAL": " (임시 원단위)", "PARTIAL_EVIDENCE": " (유사시설 조사 원단위, 재차인원 임시)", "EVIDENCE": " (유사시설 조사 원단위)"}.get(t.rates_status, ""), "auto")
    else:
        add("발생교통량 — 사업지(승용차)", None, "auto")
    add("발생교통량 — 주변가로 첨두시·1일(목표년도별)", None, "input", "주변가로 교통량 조사 결과가 필요(이 도구는 사업지 발생교통량만 계산)")
    add("사업지 진출입구 수", None if ov.entrances is None else f"{ov.entrances}개소")
    return rows


def missing_overview(state: ReportState) -> list[str]:
    return [r["label"] for r in overview_rows(state) if r["source"] == "missing"]
