"""신호교차로 서비스수준(LOS) 분석 (HCM 방식 간이 지체식).

TODO(검증 필요): 한국 도로용량편람의 신호교차로 LOS 기준값/지체식과 대조해 교체.
아래 임계값은 HCM 2000 기준 임시 적용.
"""
import math

from .schemas import Approach, IntersectionResult

# (상한 지체 초/대, 등급) — 임시값
LOS_THRESHOLDS = [(10, "A"), (20, "B"), (35, "C"), (55, "D"), (80, "E")]


def los_from_delay(delay: float) -> str:
    for limit, grade in LOS_THRESHOLDS:
        if delay <= limit:
            return grade
    return "F"


def analyze_approach(
    a: Approach, cycle: float, analysis_period_h: float = 0.25, k: float = 0.5, i: float = 1.0
) -> IntersectionResult:
    if a.green_time >= cycle:
        raise ValueError("녹색시간은 신호주기보다 짧아야 함")
    g_c = a.green_time / cycle
    capacity = a.saturation_flow * g_c
    x = a.volume / capacity

    d1 = 0.5 * cycle * (1 - g_c) ** 2 / (1 - min(1.0, x) * g_c)
    d2 = 900 * analysis_period_h * (
        (x - 1) + math.sqrt((x - 1) ** 2 + 8 * k * i * x / (capacity * analysis_period_h))
    )
    delay = d1 + d2
    return IntersectionResult(
        approach=a.name, capacity=capacity, vc_ratio=x, delay=delay, los=los_from_delay(delay)
    )


def analyze_intersection(
    approaches: list[Approach], cycle: float
) -> tuple[list[IntersectionResult], float, str]:
    """접근로별 결과 + 교차로 전체 가중평균 지체/등급."""
    results = [analyze_approach(a, cycle) for a in approaches]
    total_vol = sum(a.volume for a in approaches)
    if total_vol == 0:
        return results, 0.0, "A"
    avg = sum(r.delay * a.volume for r, a in zip(results, approaches)) / total_vol
    return results, avg, los_from_delay(avg)
