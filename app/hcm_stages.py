"""편람 운영분석 엔진(hcm_signal) 위의 3단계 분석: 사업 미시행 / 시행 / 교통개선대책(현시 녹색시간 재배분).

- 미시행: 이동류 교통량 × (1+연 증가율)^목표년도 (U턴·대향직진 포함)
- 시행: 미시행 + 사업 유발 첨두교통량(합계) × 이동류별 배분율
- 개선: 신호주기·황색 고정, 현시별 녹색신호시간 합을 임계 차로군 V/S에 비례해 재배분(최소 녹색 MIN_GREEN)
"""
from app.hcm_signal import DetailedIntersection, IntersectionAnalysis, analyze_detailed
from app.stages import MIN_GREEN


def scale_intersection(ix: DetailedIntersection, factor: float) -> DetailedIntersection:
    apps = [a.model_copy(update={
        "v_left": a.v_left * factor, "v_through": a.v_through * factor, "v_right": a.v_right * factor,
        "u_turn": a.u_turn * factor, "opposing_through": a.opposing_through * factor}) for a in ix.approaches]
    return ix.model_copy(update={"approaches": apps})


def add_project_volume(ix: DetailedIntersection, project_peak_total: float) -> DetailedIntersection:
    apps = [a.model_copy(update={
        "v_left": a.v_left + project_peak_total * a.project_share_left,
        "v_through": a.v_through + project_peak_total * a.project_share_through,
        "v_right": a.v_right + project_peak_total * a.project_share_right}) for a in ix.approaches]
    return ix.model_copy(update={"approaches": apps})


def reallocate_phase_greens(ix: DetailedIntersection, phase_y: dict[int, float],
                            min_green: float = MIN_GREEN) -> DetailedIntersection:
    """현시 녹색신호시간을 임계 V/S에 비례해 재배분(최소 녹색 미만이면 최소값으로 고정).

    **교통량이 입력된 현시(임계 차로군이 있는 현시)끼리만** 합을 유지하며 재배분한다. 입력된 접근로가 없는 현시는
    실제 교통량을 알 수 없으므로 녹색시간을 그대로 둔다(그렇지 않으면 입력하지 않은 접근로의 녹색을 빼앗아
    근거 없는 '개선'이 나온다). 재배분 대상이 2개 미만이면 변경하지 않는다.
    """
    n = len(ix.phases)
    active = [i for i in range(n) if phase_y.get(i, 0.0) > 0]
    if len(active) < 2:
        return ix
    total = sum(ix.phases[i].green for i in active)
    if len(active) * min_green > total:
        raise ValueError("재배분 대상 현시의 녹색시간 합이 현시 수 × 최소 녹색시간보다 작아 재배분할 수 없음")
    greens: dict[int, float] = {}
    free, remaining = list(active), total
    while True:
        ysum = sum(phase_y[i] for i in free)
        alloc = {i: remaining * phase_y[i] / ysum for i in free}
        low = [i for i in free if alloc[i] < min_green]
        if not low:
            greens.update(alloc)
            break
        for i in low:
            greens[i] = min_green
            free.remove(i)
            remaining -= min_green
        if not free:
            break
    phases = [p.model_copy(update={"green": greens.get(i, p.green)}) for i, p in enumerate(ix.phases)]
    return ix.model_copy(update={"phases": phases})


def summarize(ix: DetailedIntersection, res: IntersectionAnalysis) -> dict:
    """simple 분석의 _summary와 같은 형태(보고서·화면·환각 점검에서 공통 사용)."""
    results = []
    for g in res.groups:
        results.append({"approach": f"{g.approach} {g.label}", "capacity": g.capacity, "vc_ratio": g.x,
                        "delay": g.delay, "los": g.los, "volume": g.volume, "saturation": g.saturation,
                        "y": g.y, "phase": g.phase + 1, "lanes": g.lanes})
    volumes = {}
    for a in ix.approaches:
        for label, v in (("좌", a.v_left), ("직", a.v_through), ("우", a.v_right)):
            if v > 0:
                volumes[f"{a.name} {label}"] = v
    return {
        "avg_delay": res.delay, "grade": res.los,
        "max_vc": max((g.x for g in res.groups), default=0.0),
        "results": results,
        "greens": {f"현시{i + 1}": p.green for i, p in enumerate(ix.phases)},
        "volumes": volumes,
        "critical_vc": res.critical_vc,
        "engine": "hcm_detailed",
    }


def carried_queues(base: DetailedIntersection, stage: DetailedIntersection) -> dict[str, dict[str, float]]:
    """장래 단계에 적용할 초기 대기차량: {접근로: {차로군: Qb}} (편람 p.255 권장 규칙).

    현황(base)에서 관측한 Qb는 **같은 이름의 차로군**에서 장래 V/c가 1.0 이상이거나 현황 V/c보다 클 때만 적용한다.
    (편람에는 차로군 분류가 바뀔 때 대기차량을 다른 차로군으로 옮기는 규칙이 없다 — 옮기면 차로 수가 다른 차로군에
    수십 대가 얹혀 지체가 폭주하므로 옮기지 않는다.)
    """
    base_res = {ap.name: {g.label: g for g in ap.groups} for ap in analyze_detailed(base).approaches}
    cleared = stage.model_copy(update={"approaches": [a.model_copy(update={"initial_queue": {}}) for a in stage.approaches]})
    fut_res = {ap.name: {g.label: g for g in ap.groups} for ap in analyze_detailed(cleared).approaches}
    out: dict[str, dict[str, float]] = {}
    for a in base.approaches:
        q = {}
        for label, qb in a.initial_queue.items():
            src, tgt = base_res.get(a.name, {}).get(label), fut_res.get(a.name, {}).get(label)
            if qb > 0 and src is not None and tgt is not None and (tgt.x >= 1.0 or tgt.x > src.x):
                q[label] = qb
        out[a.name] = q
    return out


def with_queues(stage: DetailedIntersection, queues: dict[str, dict[str, float]]) -> DetailedIntersection:
    return stage.model_copy(update={"approaches": [
        a.model_copy(update={"initial_queue": queues.get(a.name, {})}) for a in stage.approaches]})


QUEUE_NOTE = ("현황의 초기 대기차량을 장래 단계에 적용하지 않음: 사업 교통량 등으로 단계마다 차로군 분류가 달라져 같은 차로군에 "
              "일관되게 적용할 수 없음(편람은 분류 변경 시 대기차량 이전 규칙이 없음). 미시행·시행·개선 후 모두 Qb=0으로 비교")


def analyze_stages_detailed(ix: DetailedIntersection, years: list[int], growth_rate: float,
                            project_peak_total: float) -> dict[int, dict]:
    from app.improvement import build_scenarios  # 지연 import: improvement가 이 모듈의 함수를 쓴다

    out: dict[int, dict] = {}
    for y in years:
        without = scale_intersection(ix, (1 + growth_rate) ** y)
        with_p = add_project_volume(without, project_peak_total)
        improved = reallocate_phase_greens(with_p, analyze_detailed(with_p).phase_y)  # 재배분은 V/S 기준(Qb 무관)
        scenarios = build_scenarios(with_p)
        stages = {"without": without, "with": with_p, "improved": improved}
        notes: list[str] = []
        queues: dict[str, dict[str, float]] = {}
        if any(a.initial_queue for a in ix.approaches):
            carried = {k: carried_queues(ix, s) for k, s in stages.items()}
            # 단계 간 비교가 일관되도록: 세 단계의 적용 결과가 같을 때만 사용하고, 다르면 모두 0으로 둔다
            if carried["without"] == carried["with"] == carried["improved"]:
                queues = carried["without"]
            else:
                notes.append(QUEUE_NOTE)
        without, with_p, improved = (with_queues(s, queues) for s in stages.values())
        res_with = analyze_detailed(with_p)
        res_imp = analyze_detailed(improved)
        st = {
            "without": summarize(without, analyze_detailed(without)),
            "with": summarize(with_p, res_with),
            "improved": summarize(improved, res_imp),
            "notes": notes,
            "scenarios": scenarios,
        }
        st["delay_reduction"] = st["with"]["avg_delay"] - st["improved"]["avg_delay"]
        out[y] = st
    return out
