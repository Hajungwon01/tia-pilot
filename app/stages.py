"""3단계 교통영향 분석: 사업 미시행 / 사업시행 / 교통개선대책 이행 (지침 제11조④).

- 미시행: 현황 교통량 × (1+연 증가율)^목표년도
- 시행: 미시행 + 사업 유발 첨두교통량 × 접근로별 배분율
- 개선: 신호주기 고정, 녹색시간을 교통류율비(v/s)에 비례해 재배분 (각 접근로가 별도 현시라는 단순 가정)
개선 수치는 LLM이 아니라 이 계산 결과이므로 보고서 문장에서 인용할 수 있다.
"""
from app.los import analyze_intersection
from app.schemas import Approach

GRADE_ORDER = ["A", "B", "C", "D", "E", "F", "FF", "FFF"]
MIN_GREEN = 7.0  # 초. 임시 최소 녹색시간(보행·안전 기준 확인 필요)
MEANINGFUL_REDUCTION = 1.0  # 초/대. 이보다 작은 지체 감소는 "효과 미미"로 표기(임의 기준)


def grade_rank(g: str) -> int:
    return GRADE_ORDER.index(g)


def scale_volumes(approaches: list[Approach], factor: float) -> list[Approach]:
    return [a.model_copy(update={"volume": a.volume * factor}) for a in approaches]


def add_project_volume(approaches: list[Approach], project_peak_total: float) -> list[Approach]:
    return [a.model_copy(update={"volume": a.volume + project_peak_total * a.project_share}) for a in approaches]


def optimize_green(approaches: list[Approach], min_green: float = MIN_GREEN) -> list[Approach]:
    """총 녹색시간을 유지한 채 v/s(교통류율비)에 비례해 재배분. 최소 녹색시간 미만은 최소값으로 고정."""
    total = sum(a.green_time for a in approaches)
    if len(approaches) * min_green > total:
        raise ValueError("총 녹색시간이 접근로 수 × 최소 녹색시간보다 작아 재배분할 수 없음")
    y = [a.volume / a.saturation_flow for a in approaches]
    if sum(y) == 0:
        return list(approaches)
    greens = [None] * len(approaches)
    free = list(range(len(approaches)))
    remaining = total
    while True:  # 최소값 미만이 되는 접근로를 고정하고 나머지를 다시 배분
        ysum = sum(y[i] for i in free)
        alloc = {i: remaining * y[i] / ysum for i in free} if ysum > 0 else {i: remaining / len(free) for i in free}
        low = [i for i in free if alloc[i] < min_green]
        if not low:
            for i in free:
                greens[i] = alloc[i]
            break
        for i in low:
            greens[i] = min_green
            free.remove(i)
            remaining -= min_green
        if not free:
            break
    return [a.model_copy(update={"green_time": g}) for a, g in zip(approaches, greens)]


def _summary(approaches: list[Approach], cycle: float) -> dict:
    results, avg, grade = analyze_intersection(approaches, cycle)
    return {
        "avg_delay": avg,
        "grade": grade,
        "max_vc": max(r.vc_ratio for r in results),
        "results": [r.model_dump() for r in results],
        "greens": {a.name: a.green_time for a in approaches},
        "volumes": {a.name: a.volume for a in approaches},
    }


def analyze_stages(approaches: list[Approach], cycle: float, years: list[int],
                   growth_rate: float, project_peak_total: float) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for y in years:
        without = scale_volumes(approaches, (1 + growth_rate) ** y)
        with_p = add_project_volume(without, project_peak_total)
        improved = optimize_green(with_p)
        st = {
            "without": _summary(without, cycle),
            "with": _summary(with_p, cycle),
            "improved": _summary(improved, cycle),
        }
        st["delay_reduction"] = st["with"]["avg_delay"] - st["improved"]["avg_delay"]
        out[y] = st
    return out
