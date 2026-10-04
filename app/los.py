"""신호교차로 서비스수준(LOS) 분석.

등급 기준: 도로용량편람(국토교통부, 2013) 신호교차로 — 평균 제어지체(초/대) A ≤15, B ≤30, C ≤50, D ≤70, E ≤100.
  ※ 값은 편람을 인용한 2차 출처(2026-10-05 확인)로 반영했고 원문 PDF와는 대조하지 못했다(TODO: 원문 대조).
  ※ 편람은 100초 초과를 F(≤220초)·FF·FFF로 더 세분하지만 세부 경계를 확인하지 못해 100초 초과는 F로 묶는다.
지체식: HCM 형태의 간이식(d1+d2). 편람의 진행보정계수(PF)·초기대기지체(d3)는 미반영(TODO).
"""
import math

from .schemas import Approach, IntersectionResult

# (상한 지체 초/대, 등급) — 도로용량편람 2013 (2차 출처 확인, 원문 대조 필요)
LOS_THRESHOLDS = [(15, "A"), (30, "B"), (50, "C"), (70, "D"), (100, "E")]
LOS_CRITERIA_NOTE = "도로용량편람(2013) 기준, 2차 출처로 확인(원문 미대조)"


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
