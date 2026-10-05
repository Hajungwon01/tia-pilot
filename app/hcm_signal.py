"""도로용량편람(국토교통부, 2013) 제8장 신호교차로 운영분석 — 차로군 분류부터 제어지체·LOS까지.

원문 대조(편람 PDF 발간등록번호 11-B090023-000298-01, 쪽은 책 쪽번호):
- 기본 포화교통류율 S0=2,200 pcphgpl, 우회전 SR0=1,900 (p.222, p.232)
- 유효녹색시간 = 녹색신호시간 − 0.3초 (p.268), 분석기간 T=0.25h (p.260)
- 교통량 보정 PHF(식 8-1), 차로이용률 FU(표 8-5), RTOR FR(표 8-6)
- 좌회전 직진환산 El(표 8-7, 식 8-4·8-5), Ep(표 8-9), Eu(표 8-10·11), EL=El×Ep×Eu(식 8-6)
- 노변마찰 Ldw(8-7), Lbb(8-8, 표 8-12), Lp(8-9), LH(8-10), 우회전 ER1·ER2(8-11·12), fc(표 8-13)
- 차로군 분류(식 8-13~20, 표 8-14), 회전 보정(8-21~32), 세갈래(8-33~37), S=2200·N·f·fw·fg·fHV(8-38), fHV(8-39)
- 지체 d=d1(PF)+d2+d3 (8-43), d1(8-47~49), d2(8-50), d3(8-51~53), PF(표 8-17), 가중평균(8-55·56)
검증: 편람 풀이 예제 EB 접근로(p.261~273)의 중간값·결과를 tests/test_hcm_signal.py로 재현한다.

지원 범위: 네갈래 CASE 1·2·3·4·6, 세갈래(직진·우회전 / 직진·좌회전 / 전용 좌·우).
미지원: CASE 5(맨 왼쪽 전용+공용 좌회전 2차로), 우회전 2차로 이상 공용, 교통량 직접 조사 PHF 이동류별 적용.
"""
import math
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.los import los_from_delay

S0 = 2200.0  # pcphgpl
EFFECTIVE_GREEN_LOSS = 0.3  # 초
T_HOURS = 0.25
FU_THRESHOLD = 800.0

# ── 표 ──────────────────────────────────────────────────────────
P_TABLE = [(100, 14.1), (200, 6.35), (400, 2.57), (600, 1.39), (800, 0.84), (1000, 0.54), (1200, 0.37),
           (1400, 0.25), (1600, 0.18), (1800, 0.13)]  # 표 8-8 (Vo → P), 보간
EU1 = [(0, 1.00), (10, 1.21), (20, 1.39), (30, 1.64), (40, 1.97), (50, 2.55), (60, 3.25)]  # 표 8-10
EU2 = [(0, 1.00), (10, 1.17), (20, 1.30), (30, 1.48)]  # 표 8-11
TB = {"small": 10.8, "medium": 15.3, "large": 22.8, "bay": 1.4}  # 표 8-12 (주택지역/업무·상업지구/이용객 많음/별도 승차대)
PF_GC = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
PF_TABLE = [  # 표 8-17: 행=TVO 0.0~1.0, 열=g/C 0.1~0.9
    [1.04, 0.86, 0.76, 0.71, 0.71, 0.73, 0.78, 0.86, 1.06],
    [0.62, 0.56, 0.54, 0.55, 0.58, 0.64, 0.72, 0.81, 0.92],
    [1.04, 0.81, 0.59, 0.55, 0.58, 0.64, 0.72, 0.81, 0.92],
    [1.04, 1.11, 0.98, 0.77, 0.58, 0.64, 0.72, 0.81, 0.92],
    [1.04, 1.11, 1.20, 1.14, 0.94, 0.73, 0.72, 0.81, 0.92],
    [1.04, 1.11, 1.20, 1.31, 1.30, 1.09, 0.83, 0.81, 0.92],
    [1.04, 1.11, 1.20, 1.31, 1.43, 1.47, 1.22, 0.81, 0.92],
    [1.04, 1.11, 1.20, 1.31, 1.43, 1.56, 1.63, 1.27, 0.92],
    [1.04, 1.11, 1.20, 1.31, 1.43, 1.47, 1.58, 1.76, 1.00],
    [1.04, 1.11, 1.15, 1.08, 1.06, 1.09, 1.17, 1.32, 1.59],
    [1.03, 1.01, 0.89, 0.80, 0.74, 0.71, 0.71, 0.81, 1.08],
]


def interp(table: list[tuple[float, float]], x: float) -> float:
    """선형 보간(범위 밖은 양 끝 값). 표의 '사이 값은 보간법' 지침."""
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def fu_factor(through_only_lanes: int, per_lane_vph: float) -> float:
    """차로이용률계수 FU (표 8-5). 직진 전용 차로 수와 차로당 평균 교통량(800 기준)."""
    low = [1.00, 1.02, 1.10, 1.15]
    high = [1.00, 1.00, 1.05, 1.08]
    i = min(max(through_only_lanes, 1), 4) - 1
    return (low if per_lane_vph <= FU_THRESHOLD else high)[i]


def ep_factor(radius_m: float) -> float:  # 표 8-9
    for limit, v in ((9, 1.14), (12, 1.11), (15, 1.09), (18, 1.06), (20, 1.05)):
        if radius_m <= limit:
            return v
    return 1.00


def fc_factor(ped_per_hour: float) -> float:  # 표 8-13
    for limit, v in ((500, 0.3), (1000, 0.6), (2000, 0.8), (3000, 0.9)):
        if ped_per_hour <= limit:
            return v
    return 1.0


def fw_factor(width_m: float) -> float:  # 표 8-15
    if width_m >= 3.0:
        return 1.00
    return 0.94 if width_m > 2.6 else 0.88


def fg_factor(grade_pct: float) -> float:  # 표 8-16 (0→1.00, +3→0.96, +6→0.93, 보간)
    return interp([(0, 1.00), (3, 0.96), (6, 0.93)], max(grade_pct, 0.0))


def fhv_factor(heavy_fraction: float) -> float:  # 식 8-39, E_HV=1.8
    return 1.0 / (1.0 + heavy_fraction * (1.8 - 1.0))


def pf_factor(tvo: float, g_over_c: float) -> float:
    """연동계수 PF (표 8-17 이중 선형 보간). TVO는 0~1로 정규화, g/C는 0.1~0.9로 제한."""
    tvo = tvo % 1.0 if tvo not in (0.0, 1.0) else tvo
    gc = min(max(g_over_c, PF_GC[0]), PF_GC[-1])
    r = min(int(tvo * 10), 9)
    r_frac = tvo * 10 - r
    k = min(max(int((gc - 0.1) * 10 + 1e-9), 0), 7)
    k_frac = (gc - PF_GC[k]) / 0.1

    def row(i):
        return PF_TABLE[i][k] + (PF_TABLE[i][k + 1] - PF_TABLE[i][k]) * k_frac

    return row(r) + (row(r + 1) - row(r)) * r_frac


# ── 입력 모델 ───────────────────────────────────────────────────

class Phase(BaseModel):
    green: float = Field(gt=0)  # 녹색신호시간 G(초). 유효녹색시간은 G−0.3
    yellow: float = Field(default=3.0, ge=0)


class DetailedApproach(BaseModel):
    """편람 운영분석표 1의 접근로 입력."""

    name: str
    topology: Literal["four_way", "t_no_left", "t_no_right", "y_dedicated"] = "four_way"
    left_case: Literal[1, 2, 3, 4, 6] = 1  # 표 8-4: 1·2 양방보호(전용 1/2), 3 비보호(전용), 4 직좌동시(공용), 6 비보호(공용)
    lanes: int = Field(default=1, ge=1)  # N: 전용 좌회전 차로를 제외한 접근로 차로수 (공용 좌회전 포함)
    left_lanes: int = Field(default=1, ge=0)  # y_dedicated의 전용 좌회전 차로수 (CASE 1·2·3은 left_case로 결정)
    right_lanes: int = Field(default=1, ge=0)  # y_dedicated의 전용 우회전 차로수
    v_left: float = Field(default=0, ge=0)  # 시간교통량(vph)
    v_through: float = Field(default=0, ge=0)
    v_right: float = Field(default=0, ge=0)
    u_turn: float = Field(default=0, ge=0)  # U턴 교통량(vph)
    opposing_through: float = Field(default=0, ge=0)  # 보정 대향직진 교통량 Vo (비보호 좌회전에만 사용)
    left_radius_m: float = Field(default=25, gt=0)
    right_channelized: bool = False  # 우회전 교통섬(도류화) 유무
    lane_width_m: float = Field(default=3.0, gt=0)
    grade_pct: float = 0.0
    heavy_pct: float = Field(default=0, ge=0, le=100)
    # 노변마찰
    entering_vph: float = Field(default=0, ge=0)  # Ven (정지선 60m 이내 이면도로 진입)
    exiting_vph: float = Field(default=0, ge=0)  # Vex
    bus_stops_vph: float = Field(default=0, ge=0)  # Vb
    bus_distance_m: float = Field(default=75, ge=0)  # 정지선에서 버스정류장까지 거리 l
    bus_class: Literal["small", "medium", "large", "bay"] = "small"
    parking_allowed: bool = False
    parking_vph: float = Field(default=0, ge=0)
    ped_per_hour: float = Field(default=0, ge=0)  # 우회전을 방해하는 교차도로 횡단보행자(양방향)
    ped_green_s: float = Field(default=0, ge=0)  # Gp
    # 신호
    phase: int = Field(default=0, ge=0)  # 직진·우회전(및 비보호·직좌동시 좌회전)이 진행하는 현시 번호
    left_phase: int | None = None  # 양방보호 전용 좌회전(CASE 1·2)의 현시 번호
    # 연동
    coordinated: bool = False
    link_length_m: float = Field(default=0, ge=0)
    speed_kph: float = Field(default=0, ge=0)
    offset_s: float = 0.0
    # 초기 대기차량(차로군 이름 → 대수). 계획분석에서는 비워 둔다(편람: 0으로 간주)
    initial_queue: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self):
        if self.topology == "four_way" and self.left_case in (1, 2) and self.v_left > 0 and self.left_phase is None:
            raise ValueError(f"{self.name}: 양방보호 좌회전(CASE 1·2)은 left_phase(좌회전 현시)가 필요합니다.")
        return self


class DetailedIntersection(BaseModel):
    name: str
    cycle: float = Field(gt=0)
    phases: list[Phase]
    approaches: list[DetailedApproach]
    phf: float = Field(default=1.0, gt=0, le=1.0)  # 첨두시간계수(시간교통량 → 첨두 15분 유율)
    peak: Literal["am", "pm"] = "pm"

    @model_validator(mode="after")
    def _check(self):
        total = sum(p.green + p.yellow for p in self.phases)
        if total > self.cycle + 1e-6:
            raise ValueError(f"{self.name}: 현시 시간 합({total:g}초)이 신호주기({self.cycle:g}초)를 넘습니다.")
        n = len(self.phases)
        for a in self.approaches:
            for p in (a.phase, a.left_phase):
                if p is not None and not 0 <= p < n:
                    raise ValueError(f"{self.name} {a.name}: 현시 번호 {p}가 없습니다(현시 {n}개).")
        names = [a.name for a in self.approaches]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.name}: 접근로 이름이 중복됩니다.")
        return self


# ── 결과 ────────────────────────────────────────────────────────

class GroupResult(BaseModel):
    approach: str
    label: str  # 차로군 이름(예: 공용LT, 실질RT, 통합, 직진, 전용LT)
    phase: int
    lanes: float  # N_i
    volume: float  # 보정된 차로군 교통량 Vi (vph)
    saturation: float  # Si (vphg)
    y: float  # V/S
    g_over_c: float
    capacity: float
    x: float  # V/c
    d1: float
    d2: float
    d3: float
    pf: float
    delay: float
    los: str


class ApproachResult(BaseModel):
    name: str
    groups: list[GroupResult]
    delay: float
    los: str
    detail: dict  # 중간 계산값(검증·보고서용)


class IntersectionAnalysis(BaseModel):
    name: str
    approaches: list[ApproachResult]
    delay: float
    los: str
    critical_vc: float | None
    groups: list[GroupResult]
    phase_y: dict[int, float]  # 현시별 임계 차로군 V/S


# ── 계산 ────────────────────────────────────────────────────────

def _left_El(a: DetailedApproach, Vo: float, N: int, VL: float, VTh: float, VLF: float, g_c: float) -> float:
    case = a.left_case
    if case in (1, 4):
        return 1.00
    if case == 2:
        return 1.05
    if Vo <= 0 or VL <= 0:
        return 1.00  # 대향 직진이 없으면 방해 없음
    P = interp(P_TABLE, Vo)
    cap = S0 * N - Vo
    if cap <= 0:
        return 20.0  # 대향 직진이 접근로 용량 이상: 좌회전 불가 수준(상한)
    base = S0 / (Vo * P)
    gap = S0 * (1 - g_c) * Vo / cap
    if case == 3:  # 식 8-4 (VLF=0)
        return base + gap / VL
    return base + (gap - VLF) / VL  # 식 8-5 (CASE 6)


def _delay_components(V: float, S: float, g: float, G: float, C: float, Qb: float, pf: float) -> dict:
    """식 8-40~8-53. g=유효녹색, G=녹색신호시간(초기대기 d1의 적색시간 R=C−G)."""
    gc = g / C
    c = S * gc
    X = V / c if c > 0 else float("inf")
    y = V / S if S > 0 else float("inf")
    T = T_HOURS
    d2 = 900 * T * ((X - 1) + math.sqrt((X - 1) ** 2 + 4 * X / (c * T)))
    d3 = 0.0
    if Qb <= 0:
        d1 = 0.5 * C * (1 - gc) ** 2 / (1 - min(1.0, X) * gc)
    else:
        R = C - G
        crit = (1 - X) * c * T
        if 0 < Qb < crit:  # 유형 I
            d1 = R ** 2 / (2 * C * (1 - y)) + Qb * R / (2 * T * S * (1 - y))
            d3 = 1800 * Qb ** 2 / (c * T * (c - V))
        elif crit > 0:  # 유형 II (0 < (1-X)cT < Qb)
            d1 = R / 2
            d3 = 3600 * Qb / c - 1800 * T * (1 - X)
        else:  # 유형 III
            d1 = R / 2
            d3 = 3600 * Qb / c
    return {"c": c, "x": X, "y": y, "d1": d1, "d2": d2, "d3": d3, "delay": d1 * pf + d2 + d3}


def analyze_approach(a: DetailedApproach, ix: DetailedIntersection) -> ApproachResult:
    C, phf = ix.cycle, ix.phf
    main_phase = a.phase
    G_main = ix.phases[main_phase].green
    g_main = G_main - EFFECTIVE_GREEN_LOSS
    gc_main = g_main / C
    detail: dict = {"phase": main_phase, "g_over_c": gc_main}

    topo = a.topology
    # 유효 입력 정리
    case = a.left_case if topo in ("four_way", "t_no_right") else 1
    VL_raw = a.v_left if topo in ("four_way", "t_no_right", "y_dedicated") else 0.0
    VR_raw = a.v_right if topo in ("four_way", "t_no_left", "y_dedicated") else 0.0
    VTh_raw = a.v_through if topo != "y_dedicated" else 0.0
    dedicated_left = (topo == "four_way" and case in (1, 2, 3)) or (topo == "t_no_right" and case in (1, 2, 3))
    shared_left = (topo in ("four_way", "t_no_right")) and case in (4, 6)
    N = a.lanes
    has_left, has_right = VL_raw > 0, VR_raw > 0

    # 교통량 보정 (PHF, 차로이용률, RTOR)
    VL = VL_raw / phf
    if topo == "y_dedicated":
        n_th_only = 1
    else:
        n_th_only = max(1, N - (1 if (shared_left and has_left) else 0) - (1 if has_right else 0))
    VTh_pk = VTh_raw / phf
    FU = fu_factor(n_th_only, VTh_pk / n_th_only) if VTh_raw > 0 else 1.0
    VTh = VTh_pk * FU
    FR = 0.4 if (topo == "four_way" and a.right_channelized) else 0.5
    VR = VR_raw / phf * FR
    detail.update(VL=VL, VTh=VTh, VR=VR, FU=FU, FR=FR)

    # 노변마찰 / 횡단보행자
    Ldw = 0.9 * a.entering_vph + 1.4 * a.exiting_vph
    lb = max(0.0, (75 - a.bus_distance_m) / 75)
    Lbb = TB[a.bus_class] * lb * a.bus_stops_vph if (a.bus_stops_vph > 10 and a.bus_distance_m < 75) else 0.0
    Lp = (360 + 18 * a.parking_vph) if a.parking_allowed else 0.0
    LH = (Ldw + Lbb + Lp) * 0.3
    fcGp = 0.0 if a.right_channelized else fc_factor(a.ped_per_hour) * a.ped_green_s
    detail.update(Ldw=Ldw, lb=lb, Lbb=Lbb, Lp=Lp, LH=LH, fcGp=fcGp)

    # 좌회전 직진환산계수
    EL = 1.0
    VLF = 3600 * VTh / (C * N * VL) if (shared_left and VL > 0 and N > 0) else 0.0
    if VL > 0 and topo != "y_dedicated" or (topo == "y_dedicated" and VL > 0):
        N_for_P = N if topo != "y_dedicated" else max(a.left_lanes, 1)
        El = _left_El(a, a.opposing_through, N_for_P if topo != "y_dedicated" else N_for_P, VL, VTh, VLF, gc_main)
        Ep = ep_factor(a.left_radius_m)
        left_capable = 2 if case == 2 else 1
        upct = 100 * a.u_turn / (VL_raw + a.u_turn) if (VL_raw + a.u_turn) > 0 else 0.0
        Eu = interp(EU2 if left_capable == 2 else EU1, upct)
        EL = El * Ep * Eu
        detail.update(El=El, Ep=Ep, Eu=Eu, EL=EL)
    detail["VLF"] = VLF

    # 우회전 직진환산계수 (공용 우회전)
    ER = 1.0
    NT = N
    VRF = 3600 * VTh / (C * N * VR) if (has_right and VR > 0 and N > 0 and topo != "y_dedicated") else 0.0
    if has_right and topo != "y_dedicated":
        if a.right_channelized:
            ER = 1.16 + LH / (1.63 * VR)  # 식 8-12
        else:
            ER = 1.16 + (S0 / VR) * (fcGp / C + LH / 3600 - 1.63 * VTh / (C * NT * VR))  # 식 8-11
            ER = max(ER, 1.16)
        detail.update(ER=ER)
    detail["VRF"] = VRF

    fw, fg, fhv = fw_factor(a.lane_width_m), fg_factor(a.grade_pct), fhv_factor(a.heavy_pct / 100)
    common = fw * fg * fhv
    detail.update(fw=fw, fg=fg, fHV=fhv)

    # ── 차로군 구성: (label, phase, lanes, volume, f, key) ──
    raw_groups: list[tuple[str, int, float, float, float]] = []

    def left_phase() -> int:
        return a.left_phase if (a.left_phase is not None and case in (1, 2)) else main_phase

    def th_friction(n: float) -> float:  # 식 8-33/8-35: 우회전이 없는 직진 차로군의 노변마찰
        return 1 - LH / (3600 * n) if LH > 0 and n > 0 else 1.0

    if topo == "y_dedicated":
        if has_left:
            raw_groups.append(("전용LT", left_phase() if case in (1, 2) else main_phase, max(a.left_lanes, 1), VL, 1 / EL))
        if has_right:
            NR = max(a.right_lanes, 1)
            f_rt = 0.86 * (1 - LH / (3600 * NR)) if a.right_channelized else 0.86 * (1 - fcGp / (C * NR) - LH / (3600 * NR))
            raw_groups.append(("전용RT", main_phase, NR, VR, f_rt))
    elif dedicated_left:
        n_left = 2 if case == 2 else 1
        if has_left:
            raw_groups.append(("전용LT", left_phase(), n_left, VL, 1 / EL))
        if topo == "t_no_right":
            raw_groups.append(("직진", main_phase, N, VTh, th_friction(N)))
        else:
            _right_groups(raw_groups, N, VTh, VR, VRF, ER, 0.0, EL, main_phase, th_friction, detail, has_right)
    elif shared_left and topo == "t_no_right":
        _t_no_right_shared(raw_groups, N, VTh, VL, VLF, EL, LH, main_phase, detail)
    elif shared_left and has_left:
        _shared_left_groups(raw_groups, N, VTh, VL, VR, VLF, VRF, EL, ER, main_phase, detail, has_right)
    else:  # 좌회전 없음(또는 공용 좌회전 차로가 비어 있음): 직진·우회전만
        _right_groups(raw_groups, N, VTh, VR, VRF, ER, 0.0, EL, main_phase, th_friction, detail, has_right)

    # ── 포화교통류율·용량·지체 ──
    groups: list[GroupResult] = []
    for label, ph, n_i, V, f in raw_groups:
        if V <= 0:
            continue
        S = S0 * n_i * f * common
        G = ix.phases[ph].green
        g = G - EFFECTIVE_GREEN_LOSS
        pf = 1.0
        if a.coordinated and ph == main_phase and a.speed_kph > 0:
            tc = a.link_length_m * 3.6 / a.speed_kph
            pf = pf_factor((tc - a.offset_s) / C, g / C)
        Qb = a.initial_queue.get(label, 0.0)
        d = _delay_components(V, S, g, G, C, Qb, pf)
        groups.append(GroupResult(approach=a.name, label=label, phase=ph, lanes=n_i, volume=V, saturation=S, y=d["y"],
                                  g_over_c=g / C, capacity=d["c"], x=d["x"], d1=d["d1"], d2=d["d2"], d3=d["d3"],
                                  pf=pf, delay=d["delay"], los=los_from_delay(d["delay"])))
    tot = sum(g.volume for g in groups)
    delay = sum(g.volume * g.delay for g in groups) / tot if tot > 0 else 0.0
    detail["factors"] = {g.label: round(g.saturation / (S0 * g.lanes * common), 4) for g in groups}
    return ApproachResult(name=a.name, groups=groups, delay=delay, los=los_from_delay(delay), detail=detail)


def _f(P: float, E: float) -> float:
    return 1 / (1 + P * (E - 1))


def _right_groups(out, N, VTh, VR, VRF, ER, VLF, EL, ph, th_friction, detail, has_right):
    """전용 좌회전이 있거나 좌회전이 없는 접근로의 직진·우회전 차로군 분류(식 8-15, 8-19, 표 8-14)."""
    if not has_right:
        out.append(("직진", ph, N, VTh, th_friction(N)))
        return
    if N == 1:
        VT = VTh + VR
        out.append(("통합", ph, 1, VT, _f(VR / VT, ER)))
        return
    VSTR = (VTh - ER * VR * (N - 1)) / N  # 식 8-19
    detail["VSTR"] = VSTR
    if VSTR < VRF:  # 실질적 전용 우회전
        out.append(("실질RT", ph, 1, VRF + VR, _f(VR / (VRF + VR), ER)))
        out.append(("직진", ph, N - 1, VTh - VRF, 1.0))
    else:  # 직진·우회전 공용
        VT = VTh - VLF + VR
        out.append(("공용RT", ph, N, VT, _f(VR / VT, ER)))


def _shared_left_groups(out, N, VTh, VL, VR, VLF, VRF, EL, ER, ph, detail, has_right):
    """공용 좌회전 차로(CASE 4·6): 식 8-17, 8-20, 표 8-14, 식 8-21~25·8-28~32."""
    if not has_right:
        ER_VR = 0.0
    else:
        ER_VR = ER * VR
    if N == 1:  # 통합 차로군(식 8-32)
        VT = VTh + VL + VR
        out.append(("통합", ph, 1, VT, 1 / (1 + (VL / VT) * (EL - 1) + (VR / VT) * (ER - 1 if has_right else 0))))
        return
    VSTL = (VTh + ER_VR - EL * VL * (N - 1)) / N  # 식 8-17
    VSTR = (VTh + EL * VL - ER_VR * (N - 1)) / N if has_right else float("inf")  # 식 8-20
    detail.update(VSTL=VSTL, VSTR=VSTR)
    left_de_facto = VSTL < VLF
    right_de_facto = has_right and VSTR < VRF
    if left_de_facto and right_de_facto and N >= 3:  # 실질 전용 좌·우 + 직진
        out.append(("실질LT", ph, 1, VLF + VL, _f(VL / (VLF + VL), EL)))
        out.append(("실질RT", ph, 1, VRF + VR, _f(VR / (VRF + VR), ER)))
        out.append(("직진", ph, N - 2, VTh - VLF - VRF, 1.0))
    elif left_de_facto and not right_de_facto:
        out.append(("실질LT", ph, 1, VLF + VL, _f(VL / (VLF + VL), EL)))
        if has_right:
            VT = VTh - VLF + VR
            out.append(("공용RT", ph, N - 1, VT, _f(VR / VT, ER)))
        else:
            out.append(("직진", ph, N - 1, VTh - VLF, 1.0))
    elif right_de_facto and not left_de_facto:  # 편람 예제의 경우
        VT = VTh - VRF + VL
        out.append(("공용LT", ph, N - 1, VT, _f(VL / VT, EL)))
        out.append(("실질RT", ph, 1, VRF + VR, _f(VR / (VRF + VR), ER)))
    else:  # 전체 통합(식 8-32)
        VT = VTh + VL + VR
        out.append(("통합", ph, N, VT, 1 / (1 + (VL / VT) * (EL - 1) + (VR / VT) * (ER - 1 if has_right else 0))))


def _t_no_right_shared(out, N, VTh, VL, VLF, EL, LH, ph, detail):
    """세갈래 직진·좌회전만 + 공용 좌회전(식 8-33~36)."""
    if VL <= 0:
        out.append(("직진", ph, N, VTh, 1 - LH / (3600 * N) if LH > 0 else 1.0))
        return
    VSTL = (VTh - EL * VL * (N - 1) + LH / 1.63) / N if N > 1 else float("inf")  # 식 8-34
    detail["VSTL"] = VSTL
    if N > 1 and VSTL < VLF:  # 실질적 전용 좌회전
        out.append(("실질LT", ph, 1, VLF + VL, _f(VL / (VLF + VL), EL)))
        nth = N - 1
        out.append(("직진", ph, nth, VTh - VLF, 1 - LH / (3600 * nth) if LH > 0 else 1.0))
    else:  # 직·좌 공용(식 8-36)
        PLT = VL / (VTh + VL)
        f = 1 / (1 + PLT * (EL - 1 + LH / (1.63 * VL)))
        out.append(("공용LT", ph, N, VTh + VL, f))


def analyze_detailed(ix: DetailedIntersection) -> IntersectionAnalysis:
    approaches = [analyze_approach(a, ix) for a in ix.approaches]
    groups = [g for ap in approaches for g in ap.groups]
    tot = sum(g.volume for g in groups)
    delay = sum(g.volume * g.delay for g in groups) / tot if tot > 0 else 0.0
    phase_y: dict[int, float] = {}
    for g in groups:
        phase_y[g.phase] = max(phase_y.get(g.phase, 0.0), g.y)
    L = sum(p.yellow + EFFECTIVE_GREEN_LOSS for p in ix.phases)
    crit = sum(phase_y.values()) * ix.cycle / (ix.cycle - L) if ix.cycle > L else None  # 식 8-42
    return IntersectionAnalysis(name=ix.name, approaches=approaches, delay=delay, los=los_from_delay(delay),
                                critical_vc=crit, groups=groups, phase_y=phase_y)
