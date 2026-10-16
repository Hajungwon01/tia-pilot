"""개선 시나리오 엔진: 사업 시행 후 교차로에 적용할 수 있는 개선 후보를 편람 엔진(hcm_signal)으로 재계산해 지체 순으로 비교한다.

후보는 두 부류다.
- 신호 조정(물리적 변경 없음): 현시 녹색시간 재배분, 신호주기 조정(탐색 범위 CYCLE_MIN~CYCLE_MAX, 5초 간격) + 재배분
- 물리적 개선(용지·도로폭·안전 검토 필요): 접근로 차로 1개 증설, 전용 좌회전 차로 신설(공용 → 전용). 각 후보는 녹색시간 재배분을 함께 적용한다.
그리고 가장 좋은 물리적 후보에 주기 조정을 더한 복합안을 하나 만든다.

이 엔진은 "계산상 어느 후보가 지체를 얼마나 줄이는가"만 답한다. 시행 가능성(용지·도로폭·교통안전·예산)은 판단하지 않으므로
물리적 후보는 모두 `physical=True`(검토 후보)로 표시하고, 초기 대기차량은 후보 간 비교의 일관성을 위해 Qb=0으로 둔다.
연동 구간(coordinated) 접근로가 있으면 주기를 바꾸면 연동(옵셋)이 깨지므로 주기 조정 후보를 만들지 않는다.
"""
from dataclasses import dataclass

from app.design_criteria import left_lane_note
from app.hcm_signal import DetailedIntersection, analyze_detailed
from app.hcm_stages import reallocate_phase_greens, summarize
from app.stages import MIN_GREEN

CYCLE_MIN = 60.0  # 초. 탐색 범위(임의 기준 — 현장 신호운영 기준 확인 필요)
CYCLE_MAX = 180.0
CYCLE_STEP = 5.0
MAX_LANES = 8  # service.validate_request의 차로 수 상한과 같다
MAX_LISTED = 5  # 결과에 싣는 후보 수
MIN_GAIN = 0.05  # 초/대. 이보다 작은 차이는 같은 안으로 본다


@dataclass(frozen=True)
class Params:
    """사용자가 입력하는 개선 후보 탐색 조건(비우면 아래 기본값 — 모두 임의 기준이므로 현장 기준으로 입력하는 것이 맞다)."""

    min_green: float = MIN_GREEN  # 현시 최소 녹색시간(초): 보행자 횡단 등 안전 기준으로 정함
    cycle_min: float = CYCLE_MIN
    cycle_max: float = CYCLE_MAX

    @classmethod
    def from_project(cls, p) -> "Params":
        return cls(min_green=p.min_green_s or MIN_GREEN, cycle_min=p.cycle_search_min_s or CYCLE_MIN,
                   cycle_max=p.cycle_search_max_s or CYCLE_MAX)

    @property
    def is_default(self) -> bool:
        return self == Params()


DEFAULT_PARAMS = Params()


def _clear_queues(ix: DetailedIntersection) -> DetailedIntersection:
    return ix.model_copy(update={"approaches": [a.model_copy(update={"initial_queue": {}}) for a in ix.approaches]})


def _regreen(ix: DetailedIntersection, p: Params = DEFAULT_PARAMS) -> DetailedIntersection:
    """V/S에 비례해 녹색시간을 재배분. 재배분 대상이 2개 미만이거나 최소 녹색을 못 지키거나 지체가 오히려 늘면 그대로 둔다
    (V/S 비례 배분은 지체 최소를 보장하지 않으므로 원안보다 나빠질 수 있다)."""
    res = analyze_detailed(ix)
    try:
        cand = reallocate_phase_greens(ix, res.phase_y, p.min_green)
    except ValueError:
        return ix
    return cand if analyze_detailed(cand).delay < res.delay - 1e-9 else ix


def _best_cycle(ix: DetailedIntersection, p: Params = DEFAULT_PARAMS) -> DetailedIntersection | None:
    """주기를 p.cycle_min~p.cycle_max에서 탐색해 평균지체가 가장 작은 안을 돌려준다(현재 주기와 같거나 연동이면 None)."""
    if any(a.coordinated for a in ix.approaches):
        return None
    y = analyze_detailed(ix).phase_y
    active = [i for i in range(len(ix.phases)) if y.get(i, 0.0) > 0]
    if len(active) < 2:
        return None
    slack = ix.cycle - sum(p.green + p.yellow for p in ix.phases)  # 전적색 등 주기 내 여유(후보에서도 유지)
    fixed = sum(p.yellow for p in ix.phases) + sum(p.green for i, p in enumerate(ix.phases) if i not in active) + slack
    best, best_delay = None, float("inf")
    c = p.cycle_min
    while c <= p.cycle_max + 1e-9:
        total = c - fixed
        if total >= len(active) * p.min_green:
            cur = sum(ix.phases[i].green for i in active)
            phases = [p.model_copy(update={"green": p.green * total / cur}) if i in active else p for i, p in enumerate(ix.phases)]
            cand = ix.model_copy(update={"cycle": c, "phases": phases})
            try:
                cand = reallocate_phase_greens(cand, y, p.min_green)
                d = analyze_detailed(cand).delay
            except ValueError:
                d = float("inf")
            if d < best_delay - 1e-9:
                best, best_delay = cand, d
        c += CYCLE_STEP
    if best is None or abs(best.cycle - ix.cycle) < 1e-9:
        return None
    return best


def _lane_candidates(ix: DetailedIntersection) -> list[tuple[str, str, DetailedIntersection, list[str], dict | None]]:
    """(id, 라벨, 변경된 교차로, 변경 내용, 설계 기준 점검) — 녹색시간 재배분은 아직 적용하지 않은 물리적 변경."""
    out = []
    for i, a in enumerate(ix.approaches):
        if a.v_left + a.v_through + a.v_right <= 0:
            continue
        if a.lanes < MAX_LANES and a.topology != "y_dedicated":
            apps = list(ix.approaches)
            apps[i] = a.model_copy(update={"lanes": a.lanes + 1})
            out.append((f"add_lane:{a.name}", f"{a.name} 접근로 차로 1개 증설", ix.model_copy(update={"approaches": apps}),
                        [f"{a.name} 접근로 차로수 {a.lanes}개 → {a.lanes + 1}개"], None))
        if a.topology in ("four_way", "t_no_right") and a.v_left > 0 and a.left_case in (4, 6):
            upd = {"left_case": 3} if a.left_case == 6 else {"left_case": 1, "left_phase": a.phase}
            apps = list(ix.approaches)
            apps[i] = a.model_copy(update=upd)
            kind = "비보호 전용" if a.left_case == 6 else "직좌동시 전용"
            note, design = left_lane_note(a.v_left, ix.cycle, a.lane_width_m, a.heavy_pct, a.road_class, a.design_speed_kph)
            out.append((f"left_bay:{a.name}", f"{a.name} 접근로 전용 좌회전 차로 신설", ix.model_copy(update={"approaches": apps}),
                        [f"{a.name} 접근로 좌회전 공용 차로 → {kind} 차로(좌회전 CASE {a.left_case} → {upd['left_case']}, 총 차로 1개 추가)", note],
                        design))
    return out


def _scenario(sid: str, kind: str, label: str, physical: bool, ix: DetailedIntersection, base: DetailedIntersection,
              base_delay: float, changes: list[str], design: dict | None = None) -> dict:
    res = analyze_detailed(ix)
    s = summarize(ix, res)
    cyc_note = [f"신호주기 {base.cycle:g}초 → {ix.cycle:g}초"] if abs(ix.cycle - base.cycle) > 1e-9 else []
    return {"id": sid, "kind": kind, "label": label, "physical": physical,
            "avg_delay": res.delay, "grade": res.los, "max_vc": s["max_vc"], "critical_vc": res.critical_vc,
            "delay_reduction": base_delay - res.delay, "cycle": ix.cycle, "greens": s["greens"],
            "changes": cyc_note + changes, "design": design}


def build_scenarios(with_project: DetailedIntersection, params: Params = DEFAULT_PARAMS) -> dict:
    """사업 시행 시 교차로(with_project)에 대한 개선 후보를 지체 순으로 정렬해 돌려준다.

    반환: {"base_delay", "base_grade", "scenarios": [...최대 MAX_LISTED개...], "best_signal", "best_physical", "notes"}
    best_*는 해당 부류의 최선 후보 id(없으면 None). 지체를 줄이지 못하는 후보는 싣지 않는다.
    """
    base = _clear_queues(with_project)
    base_res = analyze_detailed(base)
    base_delay = base_res.delay
    notes: list[str] = []
    if any(a.initial_queue for a in with_project.approaches):
        notes.append("초기 대기차량은 후보 간 비교의 일관성을 위해 적용하지 않음(Qb=0)")
    if any(a.coordinated for a in base.approaches):
        notes.append("연동 구간이 있어 신호주기 조정 후보는 만들지 않음(주기를 바꾸면 연동 옵셋이 달라짐)")
    notes.append(f"탐색 조건: 최소 녹색시간 {params.min_green:g}초, 신호주기 {params.cycle_min:g}~{params.cycle_max:g}초"
                 + ("(기본값 — 현장 기준으로 입력 가능)" if params.is_default else "(입력값)"))

    found: list[dict] = []
    green = _regreen(base, params)
    if green is not base:
        found.append(_scenario("green", "green", "현시 녹색시간 재배분", False, green, base, base_delay, []))
    cyc = _best_cycle(green, params)  # 재배분이 도움이 안 되면 green은 base와 같다
    if cyc is not None:
        found.append(_scenario("cycle", "cycle", "신호주기 조정 + 녹색시간 재배분", False, cyc, base, base_delay, []))

    physical: list[tuple[dict, DetailedIntersection]] = []
    for sid, label, changed, changes, design in _lane_candidates(base):
        ix = _regreen(changed, params)
        sc = _scenario(sid, sid.split(":")[0], label, True, ix, base, base_delay,
                       changes + (["현시 녹색시간 재배분 병행"] if ix is not changed else []), design)
        physical.append((sc, ix))
        found.append(sc)

    if physical:
        top_sc, top_ix = min(physical, key=lambda t: t[0]["avg_delay"])
        if top_sc["delay_reduction"] > MIN_GAIN:
            combo = _best_cycle(top_ix, params)
            if combo is not None:
                found.append(_scenario("combo", "combo", f"{top_sc['label']} + 신호주기 조정", True, combo, base, base_delay,
                                       top_sc["changes"][:1] + [c for c in top_sc["changes"][1:] if "필요 길이" in c], top_sc["design"]))

    found = [s for s in found if s["delay_reduction"] > MIN_GAIN]
    found.sort(key=lambda s: s["avg_delay"])
    listed = found[:MAX_LISTED]
    best_signal = next((s["id"] for s in listed if not s["physical"]), None)
    best_physical = next((s["id"] for s in listed if s["physical"]), None)
    return {"base_delay": base_delay, "base_grade": base_res.los, "scenarios": listed,
            "best_signal": best_signal, "best_physical": best_physical, "notes": notes}


def scenario_lines(name: str, year: int, block: dict) -> list[str]:
    """보고서·LLM 입력용 한국어 요약(숫자는 모두 block에서 온 값)."""
    out = [f"{name} 준공 후 {year}년 개선 후보(사업 시행 시 평균지체 {block['base_delay']:.1f}초/대, LOS {block['base_grade']} 기준):"]
    if not block["scenarios"]:
        out.append("  - 계산상 지체를 줄이는 후보 없음")
    for i, s in enumerate(block["scenarios"], 1):
        tag = "물리적 개선(검토 후보)" if s["physical"] else "신호 조정"
        out.append(f"  {i}. [{tag}] {s['label']}: 평균지체 {s['avg_delay']:.1f}초/대(LOS {s['grade']}), "
                   f"{s['delay_reduction']:.1f}초/대 감소" + (f" (변경: {'; '.join(s['changes'])})" if s["changes"] else ""))
    return out
