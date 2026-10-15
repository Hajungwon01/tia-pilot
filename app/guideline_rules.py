"""지침 별표의 정량 기준을 계산 결과로 판정하는 규칙 (체크리스트 check == "rule").

규칙 함수는 (상태, 메시지)를 돌려준다. 입력이 없어 판정할 수 없으면 추측하지 않고 UNKNOWN으로 둔다.
"""
from collections.abc import Callable

from app.reflection import load_checklist
from app.state import ReportState

OK = "ok"  # 기준 충족 또는 해당 없음
ATTENTION = "attention"  # 지침이 검토를 요구하는 조건에 해당
UNKNOWN = "unknown"  # 판정에 필요한 입력·계산이 없음

STATUS_LABELS = {OK: "이상 없음", ATTENTION: "검토 필요", UNKNOWN: "입력 필요"}

ENTRANCE_HEAVY_DIRECTION = 400  # 별표 2 3.가(31)㈏, 8.가⑾: 첨두시 중방향 교통량(대/시)


def entrance_400(state: ReportState) -> tuple[str, str]:
    """첨두시 중방향 발생교통량 ≥ 400대/시이면 진·출입구 2개 차로 이상 또는 2개소 이상을 검토해야 한다.

    사업지 발생교통량은 유발교통량 계산의 AM·PM 첨두 승용차 통행(유입·유출 중 큰 쪽)으로 본다.
    """
    t = state.trips
    if t is None:
        return UNKNOWN, "유발교통량이 계산되지 않아 판정할 수 없음"
    heavy = {"AM": max(t.am_peak.in_trips, t.am_peak.out_trips),
             "PM": max(t.pm_peak.in_trips, t.pm_peak.out_trips)}
    peak = max(heavy, key=heavy.get)
    v = heavy[peak]
    note = {"PROVISIONAL": " (유발 원단위가 임시값이라 확정 판정이 아님)",
            "PARTIAL_EVIDENCE": " (평균 재차인원이 임시값이라 확정 판정이 아님)"}.get(t.rates_status, "")
    if v >= ENTRANCE_HEAVY_DIRECTION:
        return ATTENTION, (f"{peak} 첨두시 중방향 발생교통량 {v:.0f}대/시 ≥ {ENTRANCE_HEAVY_DIRECTION}대/시: "
                           f"진·출입구를 편도 2개 차로 이상 또는 2개소 이상으로 하는 방안 검토 필요{note}")
    return OK, (f"{peak} 첨두시 중방향 발생교통량 {v:.0f}대/시 < {ENTRANCE_HEAVY_DIRECTION}대/시: "
                f"별표 2의 2개소·2개 차로 검토 조건에 해당하지 않음{note}")


def parking_cap(state: ReportState) -> tuple[str, str]:
    """계획주차대수가 법정주차대수의 130%(대도시권역)를 넘지 않는지, 법정에 미달하지 않는지(별표 2 8.가⒁)."""
    r = state.parking or {}
    legal, planned = r.get("legal_total"), r.get("planned")
    if legal is None or planned is None:
        missing = [n for n, v in (("주택형별 전용면적·세대수(법정 대수 산정)", legal), ("계획 주차대수", planned)) if v is None]
        return UNKNOWN, "판정에 필요한 입력 없음: " + ", ".join(missing)
    cap, pct = r["cap"], r["cap_pct"]
    note = "" if r.get("legal_complete") else " (일부 용도 법정 대수 미산정)"
    if planned < legal:
        return ATTENTION, f"계획 {planned:,}대가 법정 {legal:,}대에 미달{note}"
    if planned > cap:
        return ATTENTION, (f"계획 {planned:,}대가 법정 {legal:,}대의 {planned / legal * 100:.0f}%로 권장 상한 {pct:g}%({cap:,.0f}대) 초과: "
                           f"초과 사유 명시 필요{note}")
    return OK, f"계획 {planned:,}대는 법정 {legal:,}대의 {planned / legal * 100:.0f}%로 권장 상한 {pct:g}% 이내{note}"


def overview_required(state: ReportState) -> tuple[str, str]:
    """서울 지침 제24조③ 사업의 개요 필수 기재 항목이 모두 채워졌는지."""
    from app.overview import missing_overview
    miss = missing_overview(state)
    if miss:
        return ATTENTION, f"필수 기재 {len(miss)}개 미기재: " + ", ".join(miss)
    return OK, "제24조③ 필수 기재 항목이 모두 채워짐"


def external_improvement(state: ReportState) -> tuple[str, str]:
    """서울 별표 1 4.아: 사업지구 외부 교통개선은 수립 대상사업 범위의 10배 이상 건축물만 작성한다."""
    mult = ((state.scope or {}).get("eligibility") or {}).get("multiple")
    if mult is None:
        return UNKNOWN, "대상 규모 배수를 판정할 수 없어(면적 미입력) 판단할 수 없음"
    if mult >= 10:
        return ATTENTION, f"대상 기준의 {mult:.1f}배(10배 이상): 사업지구 외부 교통개선 항목을 작성해야 함"
    return OK, f"대상 기준의 {mult:.1f}배(10배 미만): 사업지구 외부 교통개선 항목은 작성 대상이 아님"


RULES: dict[str, Callable[[ReportState], tuple[str, str]]] = {
    "entrance_400": entrance_400,
    "parking_cap": parking_cap,
    "external_improvement": external_improvement,
    "overview_required": overview_required,
}


def evaluate_rules(state: ReportState, checklist: dict | None = None) -> list[dict]:
    """체크리스트의 rule 항목을 모두 판정한다. 규칙 이름을 모르면 UNKNOWN(조용히 통과시키지 않는다)."""
    out = []
    for item in (checklist or load_checklist())["items"]:
        if item["check"] != "rule":
            continue
        fn = RULES.get(item["rule"])
        status, message = fn(state) if fn else (UNKNOWN, f"규칙 {item['rule']} 미구현")
        out.append({"id": item["id"], "ref": item["ref"], "text": item["text"],
                    "status": status, "label": STATUS_LABELS[status], "message": message})
    return out
