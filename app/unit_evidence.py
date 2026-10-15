"""유사시설 조사 자료로 아파트 원단위를 산출한다(지침 제12조·제15조의 '유사 건축물 조사 + 관련 자료 비교').

자료: data/unit_rate_evidence.csv — 국토교통부 교통영향평가정보지원시스템(tia.molit.go.kr)에 사업별로 공개된 '원단위정보(유사시설)'를
수집한 것(수집 방법·시점·범위는 파일 머리말). 한 행 = 평가서가 조사·인용한 유사 아파트 단지 1곳(단지명+조사일 기준 중복 제거).

규칙
- 조사일이 기준일 3년 이내인 자료만 쓴다(지침 제12조: 조사시점 기준 3년 이내).
- 항목마다 사업 지역(서울) 자료가 MIN_N(3)건 미만이면 수도권 전체로 넓히고 그 사실을 기록한다(지역 부족은 숨기지 않는다).
- 대푯값은 중앙값(IQR 1.5배 밖 이상치는 표본이 8건 이상일 때 제외). 평균은 입력 오류 하나로 크게 흔들린다.
- 실측(현장조사·영상촬영)과 문헌 인용을 나눠 세고, 실측 1건 이상 + 관련 자료 3건 이상 또는 실측 3건 이상이면 요건 충족으로 본다.
  (문헌조사는 다른 평가서의 값을 다시 인용한 것이라 독립 근거로 세지 않고, 충족 여부 판단에만 '관련 자료'로 쓴다.)
이 자료에 없는 값(평균 재차인원)은 임시값을 그대로 두고 상태를 PARTIAL_EVIDENCE로 표시한다.
"""
import csv
import statistics
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.trip_generation import load_rates

EVIDENCE_PATH = Path(__file__).resolve().parent.parent / "data" / "unit_rate_evidence.csv"
MIN_N = 3
YEARS = 3
FIELD_METHODS = {"현장조사", "영상촬영"}  # 실측
HOME_REGION = "서울"
METRO = {"서울", "경기", "인천"}

NUMERIC = ("pop_res", "pop_use", "park_wd", "car", "taxi", "bus", "subway", "walk", "am_in", "am_out", "pm_in", "pm_out")
# 항목 → (사용 열들). 한 항목이 여러 열을 함께 쓰면 그 열이 모두 있는 단지만 센다(예: 오전 유입·유출).
METRICS = {
    "person_trips": ("pop_res",),
    "car_share": ("car",),
    "am_peak": ("am_in", "am_out"),
    "pm_peak": ("pm_in", "pm_out"),
    "parking": ("park_wd",),
}
# 입력 단위가 섞이거나 오기된 값을 거르는 상식 범위(이 밖의 값은 자료 오류로 보고 쓰지 않는다). 근거 없는 임의 기준이므로 바꾸면 결과가 달라진다.
PLAUSIBLE = {"pop_res": (1.0, 10.0), "park_wd": (0.3, 3.0), "car": (0.0, 90.0), "am_in": (0.0, 100.0), "am_out": (0.0, 100.0),
             "pm_in": (0.0, 100.0), "pm_out": (0.0, 100.0)}
LABELS = {"person_trips": "세대당 일 발생(인/일, 상주)", "car_share": "승용차 분담률(%)", "am_peak": "오전 첨두 유입·유출(%)",
          "pm_peak": "오후 첨두 유입·유출(%)", "parking": "주차원단위(평일, 대/세대)"}


@dataclass
class Facility:
    name: str
    date: str
    region: str
    district: str
    units: int | None
    method: str
    v: dict[str, float | None]
    n_projects: int

    @property
    def measured(self) -> bool:
        return self.method in FIELD_METHODS


@lru_cache
def load_facilities(path: Path = EVIDENCE_PATH) -> tuple[Facility, ...]:
    out: list[Facility] = []
    with path.open(encoding="utf-8", newline="") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        for r in rows:
            def num(k):
                s = (r.get(k) or "").strip()
                return float(s) if s else None
            out.append(Facility(name=r["name"], date=r["date"], region=r["region"], district=r["district"],
                                units=int(float(r["units"])) if (r.get("units") or "").strip() else None,
                                method=(r.get("method") or "").strip(), v={k: num(k) for k in NUMERIC},
                                n_projects=int(float(r.get("n_projects") or 1))))
    return tuple(out)


def cutoff(today: date, years: int = YEARS) -> str:
    try:
        return today.replace(year=today.year - years).isoformat()
    except ValueError:  # 2월 29일
        return today.replace(year=today.year - years, day=28).isoformat()


def _trim(vals: list[float]) -> list[float]:
    if len(vals) < 8:
        return vals
    s = sorted(vals)
    q1, q3 = statistics.quantiles(s, n=4)[0], statistics.quantiles(s, n=4)[2]
    lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
    return [x for x in vals if lo <= x <= hi]


@dataclass
class MetricResult:
    key: str
    value: float | None = None  # 대푯값(중앙값). 열이 둘이면 values에 열별 중앙값
    values: dict[str, float] = field(default_factory=dict)
    n: int = 0
    n_measured: int = 0
    n_document: int = 0
    p25: float | None = None
    p75: float | None = None
    scope: str = ""  # 서울 | 수도권
    guideline_ok: bool = False
    facilities: list[Facility] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _usable(f: Facility, cols: tuple[str, ...]) -> bool:
    if any(f.v.get(c) is None for c in cols):
        return False
    if any(not PLAUSIBLE[c][0] <= f.v[c] <= PLAUSIBLE[c][1] for c in cols):
        return False
    return not (len(cols) == 2 and all(f.v[c] == 0 for c in cols))


def metric(key: str, facilities: list[Facility], today: date, region: str = HOME_REGION) -> MetricResult:
    cols = METRICS[key]
    cut = cutoff(today)
    recent = [f for f in facilities if f.date >= cut and f.date <= today.isoformat() and _usable(f, cols)]
    mine = [f for f in recent if f.region == region]
    res = MetricResult(key=key)
    if len(mine) >= MIN_N:
        use, res.scope = mine, region
    else:
        use, res.scope = [f for f in recent if f.region in METRO], "수도권"
        res.notes.append(f"{region} 자료가 {len(mine)}건(<{MIN_N})이라 수도권(서울·경기·인천)으로 넓힘")
    if len(use) < MIN_N:
        res.notes.append(f"조사일 {cut} 이후 자료가 {len(use)}건뿐이라 산출하지 않음")
        res.facilities = use
        return res
    res.facilities = use
    for c in cols:
        vals = _trim([f.v[c] for f in use])
        res.values[c] = statistics.median(vals)
    res.value = res.values[cols[0]]
    first = _trim([f.v[cols[0]] for f in use])
    q = statistics.quantiles(sorted(first), n=4) if len(first) >= 2 else [first[0]] * 3
    res.p25, res.p75 = q[0], q[2]
    res.n = len(use)
    res.n_measured = sum(f.measured for f in use)
    res.n_document = res.n - res.n_measured
    res.guideline_ok = res.n_measured >= MIN_N or (res.n_measured >= 1 and res.n_document >= MIN_N)
    if not res.guideline_ok:
        res.notes.append(f"실측 {res.n_measured}건·문헌 {res.n_document}건으로 지침 요건(실측 1+관련 자료 3, 또는 실측 3) 미충족")
    if res.n_measured < MIN_N:
        res.notes.append("문헌조사는 다른 평가서 값을 다시 인용한 것이라 독립 근거가 아님")
    return res


@dataclass
class EvidenceRates:
    rates: dict  # trip_generation.estimate_trips가 쓰는 형식
    metrics: dict[str, MetricResult]
    status: str  # EVIDENCE | PARTIAL_EVIDENCE
    notes: list[str]
    today: date

    def basis_rows(self) -> list[list[str]]:
        """보고서 부록·화면용: 항목별 근거 요약."""
        rows = []
        for k, m in self.metrics.items():
            val = "—" if m.value is None else " / ".join(f"{m.values[c]:g}" for c in METRICS[k])
            rng = "" if m.p25 is None else f"{m.p25:g}~{m.p75:g}"
            rows.append([LABELS[k], val, rng, f"{m.n}건(실측 {m.n_measured}·문헌 {m.n_document})", m.scope or "—",
                         "충족" if m.guideline_ok else "미충족"])
        return rows


def derive_rates(today: date | None = None, region: str = HOME_REGION, facilities=None,
                 car_occupancy: float | None = None) -> EvidenceRates:
    """유사시설 자료로 trip_generation 형식의 원단위를 만든다. 필수 항목이 비면 임시값 항목을 유지하고 상태를 낮춘다.

    car_occupancy(사용자 입력 평균 재차인원)를 주면 임시값 대신 쓴다. 유사시설 항목이 모두 산출된 경우에만 상태가 EVIDENCE가 된다."""
    today = today or date.today()
    facs = list(facilities if facilities is not None else load_facilities())
    ms = {k: metric(k, facs, today, region) for k in METRICS}
    base = load_rates()["apartment"]
    notes: list[str] = []
    apt = {
        "daily_person_trips_per_household": base["daily_person_trips_per_household"],
        "mode_share": dict(base["mode_share"]),
        "car_occupancy": base["car_occupancy"],
        "peak_hour": {k: dict(v) for k, v in base["peak_hour"].items()},
        "parking": dict(base["parking"]),
    }
    missing: list[str] = []
    m = ms["person_trips"]
    if m.value:
        apt["daily_person_trips_per_household"] = m.value
    else:
        missing.append(LABELS["person_trips"])
    m = ms["car_share"]
    if m.value is not None:
        car = m.value / 100
        rest = (1 - car) / (1 - base["mode_share"]["car"])  # 나머지 수단은 임시 비율을 유지한 채 합이 1이 되도록 스케일
        apt["mode_share"] = {k: (car if k == "car" else v * rest) for k, v in base["mode_share"].items()}
    else:
        missing.append(LABELS["car_share"])
    for key, hour in (("am_peak", "am"), ("pm_peak", "pm")):
        m = ms[key]
        if m.value is not None:
            i, o = m.values[METRICS[key][0]], m.values[METRICS[key][1]]
            # 일 유입·유출을 각각 하루의 절반으로 보고, 첨두시 비율(%)을 곱해 일 차량대비 첨두 비율과 유입 비율을 만든다
            apt["peak_hour"][hour] = {"ratio_of_daily": 0.5 * (i + o) / 100, "in_ratio": i / (i + o)}
        else:
            missing.append(LABELS[key])
    m = ms["parking"]
    if m.value is not None:
        apt["parking"]["demand_per_household"] = m.value
    else:
        missing.append(LABELS["parking"])
    for k in missing:
        notes.append(f"{k}: 근거 자료 부족 — 임시값 유지")
    if car_occupancy is not None:
        apt["car_occupancy"] = car_occupancy
    else:
        notes.append("평균 재차인원은 이 자료에 없어 임시값(%g명) 유지" % base["car_occupancy"])
    for k, m in ms.items():
        notes += [f"{LABELS[k]}: {n}" for n in m.notes if "독립 근거" not in n]
    status = "EVIDENCE" if car_occupancy is not None and not missing else "PARTIAL_EVIDENCE"
    rates = {"_status": status, "_note": "유사시설 조사(교통영향평가정보지원시스템) 중앙값" + (" + 입력 재차인원" if car_occupancy is not None else " + 임시 재차인원"),
             "apartment": apt}
    return EvidenceRates(rates=rates, metrics=ms, status=status, notes=notes, today=today)
