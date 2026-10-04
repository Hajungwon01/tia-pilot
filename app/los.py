"""신호교차로 서비스수준(LOS) 분석 — 도로용량편람(국토교통부, 2013) 제8장 기준.

원문 대조 완료(2026-10-05, 편람 PDF 발간등록번호 11-B090023-000298-01):
- 등급 기준 <표 8-2>(편람 p.218): 평균 제어지체(초/대) A ≤15, B ≤30, C ≤50, D ≤70, E ≤100, F ≤220, FF ≤340, FFF >340
- 균일지체 d1 (식 8-47), 증분지체 d2 (식 8-50, T=0.25h 기본, 편람 p.260) — 아래 구현과 동일
- 교차로 평균지체 = 접근로 지체의 교통량 가중평균 (식 8-55, 8-56)
의도적으로 반영하지 않은 항목(계획분석 가정):
- 추가지체 d3: 초기 대기차량 Qb=0 (편람 p.256: 계획분석에서는 0으로 간주)
- 연동계수 PF: 1.0 (비연동). 연동 교차로는 옵셋편의율·<표 8-17>로 d1에 곱해야 함 (TODO)
- 차로군 분류·직진환산·보정계수(식 8-39 등): 사용자가 포화교통류율을 직접 입력한다고 가정
"""
import math

from .schemas import Approach, IntersectionResult

# (상한 지체 초/대, 등급) — 도로용량편람 2013 <표 8-2> (원문 확인)
LOS_THRESHOLDS = [(15, "A"), (30, "B"), (50, "C"), (70, "D"), (100, "E"), (220, "F"), (340, "FF")]
LOS_CRITERIA_NOTE = "도로용량편람(2013) <표 8-2> 기준(원문 확인)"


def los_from_delay(delay: float) -> str:
    for limit, grade in LOS_THRESHOLDS:
        if delay <= limit:
            return grade
    return "FFF"


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
