"""평면교차로 설계 지침(건설교통부, 2004.12) 기하구조 기준 — 개선 후보의 '물리적 시행 가능성'을 점검하는 근거.

원문 대조(PDF 파일 쪽 − 12 = 책 쪽번호; 아래 `page`는 책 쪽번호):
- 좌회전 차로 길이(3.3.1 (4)·(5), 51~54쪽): L = Ls + Ld = 1.5·N·S + (l − T), 단 L ≥ 2.0·N·S.
  Ls 대기길이, Ld 감속길이(= l − T), l 감속길이 <표 3.6>(a=2.0 기준치 / a=3.0 최소치), T 차로 테이퍼, N 신호 1주기당 좌회전 도착대수,
  S 대기 자동차 길이 <표 3.7>(대형차 혼입률을 알기 어려우면 7.0m). 예시(53~54쪽 6가지)를 tests/test_design_criteria.py로 재현한다.
- 차로 테이퍼(50쪽): 폭:길이 = 1:8(설계속도 50km/h 이하), 1:15(60km/h 이상), 시가지 용지 제약이 심하면 1:4까지.
- 교통섬 최소 크기(70쪽): 9㎡ 이상, 용지 제약 시 도시지역 5㎡·지방지역 7㎡ 이상.
- 회전반경 최소(61쪽): 주간선 15m, 보조간선 12m, 집산 10m, 국지 6m 이상.
설계속도는 이 도구가 입력받지 않으므로 호출하는 쪽이 가정값(DEFAULT_DESIGN_SPEED)을 명시해야 한다. 길이는 5m 단위로 올림한다(예시의 '≒').
이 지침은 계산식이 아니라 치수 기준이므로, 결과는 '필요 길이 점검'이지 시행 가능성 판정이 아니다(용지 여유는 사람이 확인).
"""
import math
from dataclasses import dataclass

REF = "평면교차로 설계 지침(건설교통부, 2004)"
LAW_REF = "도로의 구조·시설 기준에 관한 규칙 제8조①"
DEFAULT_DESIGN_SPEED = 50  # km/h. 도로 기능을 모르면 도시지역 집산도로 값으로 가정한다
# 도로의 구조·시설 기준에 관한 규칙(국토교통부령) 제8조① 표 — 도시지역 설계속도(km/h). 이 속도 '이상'이며, 지형·경제성에 따라 20km/h 이내로 낮출 수 있다.
# (2020.3.6 개정 이후 표 변경 없음: 2026.6.3 시행본까지 같은 표를 확인. 지방지역은 이 도구의 서울 대상에 해당 없음.)
URBAN_DESIGN_SPEED = {"arterial": 80, "sub_arterial": 60, "collector": 50, "local": 40}
ROAD_CLASS_LABELS = {"arterial": "주간선도로", "sub_arterial": "보조간선도로", "collector": "집산도로", "local": "국지도로"}
SPEEDS = (30, 40, 50, 60, 70, 80)
DECEL_STANDARD = {30: 20, 40: 30, 50: 50, 60: 70, 70: 95, 80: 125}  # <표 3.6> a=2.0m/초² 기준치(m)
DECEL_MIN = {30: 15, 40: 20, 50: 35, 60: 45, 70: 65, 80: 80}  # a=3.0m/초² 최소치(m)
VEHICLE_LENGTH = [(5, 6.0), (15, 7.0), (30, 7.8), (50, 9.0)]  # <표 3.7> (대형차 혼입률 %, 평균 자동차 길이 m)
DEFAULT_VEHICLE_LENGTH = 7.0  # 혼입률을 정확히 알기 어려울 때(15% 가정)
ISLAND_MIN_M2 = {"일반": 9, "도시지역(부득이)": 5, "지방지역(부득이)": 7}
TURN_RADIUS_MIN_M = {"주간선도로": 15, "보조간선도로": 12, "집산도로": 10, "국지도로": 6}

CITED_CRITERIA = [  # AI 문장·보고서에서 인용할 수 있는 원문 확인 기준(쪽은 책 쪽번호)
    {"id": "left_lane_length", "page": "51~52", "text": "좌회전 차로 길이 L=1.5·N·S+(l−T), L≥2.0·N·S (N: 신호 1주기당 좌회전 도착대수, S: 7.0m)"},
    {"id": "lane_taper", "page": "50", "text": "차로 테이퍼 폭:길이 1:8(설계속도 50km/h 이하)·1:15(60km/h 이상), 시가지 용지 제약 시 1:4까지"},
    {"id": "design_speed", "page": "", "src": LAW_REF, "text": "도시지역 설계속도 주간선도로 80·보조간선도로 60·집산도로 50·국지도로 40km/h 이상(지형·경제성에 따라 20km/h 이내 감속 가능)"},
    {"id": "island_min", "page": "70", "text": "교통섬 최소 면적 9㎡, 용지 제약 시 도시지역 5㎡·지방지역 7㎡"},
    {"id": "turn_radius", "page": "61", "text": "회전반경 최소 주간선 15m·보조간선 12m·집산 10m·국지 6m"},
]


def vehicle_length(heavy_pct: float | None) -> float:
    """<표 3.7> 대형차 혼입률에 따른 평균 자동차 길이(m). 모르면 7.0m. 표의 사이 값은 선형 보간."""
    if heavy_pct is None:
        return DEFAULT_VEHICLE_LENGTH
    pts = VEHICLE_LENGTH
    if heavy_pct <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if heavy_pct <= x1:
            return y0 + (y1 - y0) * (heavy_pct - x0) / (x1 - x0)
    return pts[-1][1]


def _up5(x: float) -> float:
    return math.ceil(x / 5 - 1e-9) * 5


@dataclass
class LeftLaneLength:
    design_speed: int
    constrained: bool
    arrivals_per_cycle: float
    lane_width_m: float
    vehicle_length_m: float
    decel_m: float  # 표 3.6 감속길이 l
    taper_m: float  # 차로 테이퍼 T(5m 올림)
    queue_m: float  # Ls = 1.5·N·S
    l1_m: float  # Ls + (l−T), 5m 올림
    l2_m: float  # 2.0·N·S, 5m 올림
    length_m: float  # max(L1, L2)

    @property
    def ref(self) -> str:
        return f"{REF} 51~52쪽(표 3.6·3.7)"


def left_turn_lane_length(arrivals_per_cycle: float, design_speed: int = DEFAULT_DESIGN_SPEED, lane_width_m: float = 3.0,
                          heavy_pct: float | None = None, constrained: bool = False,
                          vehicle_length_m: float | None = None) -> LeftLaneLength:
    """신호교차로 좌회전 차로 최소 길이. constrained=True면 용지 제약 시의 최소 감속길이(a=3.0) 사용."""
    if design_speed not in SPEEDS:
        raise ValueError(f"설계속도는 {SPEEDS}km/h 중 하나여야 합니다(표 3.6): {design_speed}")
    if arrivals_per_cycle <= 0:
        raise ValueError("신호 1주기당 좌회전 도착대수는 0보다 커야 합니다")
    S = vehicle_length_m if vehicle_length_m is not None else vehicle_length(heavy_pct)
    N = arrivals_per_cycle
    ratio = 8 if design_speed <= 50 else 15
    T = _up5(lane_width_m * ratio)
    l = (DECEL_MIN if constrained else DECEL_STANDARD)[design_speed]
    Ls = 1.5 * N * S
    L1 = _up5(Ls + (l - T))
    L2 = _up5(2.0 * N * S)
    return LeftLaneLength(design_speed, constrained, N, lane_width_m, S, l, T, Ls, L1, L2, max(L1, L2))


def arrivals_per_cycle(v_left_vph: float, cycle_s: float) -> int:
    """신호 1주기당 좌회전 도착대수(올림, 최소 1대)."""
    return max(1, math.ceil(v_left_vph * cycle_s / 3600 - 1e-9))


def design_speed_for(road_class: str | None) -> tuple[int, str]:
    """도로 기능별 구분 → (설계속도 km/h, 근거 설명). 모르면 집산도로 값을 가정하고 그렇다고 적는다."""
    if road_class in URBAN_DESIGN_SPEED:
        v = URBAN_DESIGN_SPEED[road_class]
        return v, f"{ROAD_CLASS_LABELS[road_class]}(도시지역) 설계속도 {v}km/h 이상, {LAW_REF}"
    return DEFAULT_DESIGN_SPEED, f"도로 기능 미입력 — 설계속도 {DEFAULT_DESIGN_SPEED}km/h 가정(도시지역 집산도로 값, {LAW_REF})"


def left_lane_note(v_left_vph: float, cycle_s: float, lane_width_m: float, heavy_pct: float,
                   road_class: str | None = None) -> tuple[str, dict]:
    """개선 후보(전용 좌회전 차로 신설)에 붙이는 설명과 수치. 설계속도는 도로 기능에서 정하고, 모르면 가정이라고 문장에 명시한다."""
    n = arrivals_per_cycle(v_left_vph, cycle_s)
    design_speed, basis = design_speed_for(road_class)
    std = left_turn_lane_length(n, design_speed, lane_width_m, heavy_pct)
    mn = left_turn_lane_length(n, design_speed, lane_width_m, heavy_pct, constrained=True)
    text = (f"전용 좌회전 차로 필요 길이 약 {std.length_m:g}m(기준치) · 용지 제약 시 {mn.length_m:g}m(최소치) "
            f"— 신호 1주기당 좌회전 {n}대, {basis}; {std.ref}")
    return text, {"arrivals": n, "design_speed": design_speed, "standard_m": std.length_m, "minimum_m": mn.length_m,
                  "ref": std.ref, "road_class": road_class, "speed_assumed": road_class not in URBAN_DESIGN_SPEED}


def criteria_lines() -> list[str]:
    """LLM 입력용: 인용 가능한 설계 기준(원문 확인분)."""
    return [f"  - {c['text']} ({c['src']})" if c.get("src") else f"  - {c['text']} ({REF} {c['page']}쪽)" for c in CITED_CRITERIA]
