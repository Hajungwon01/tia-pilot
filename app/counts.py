"""교통량 조사 CSV(15분 단위, 이동류별)에서 첨두시와 첨두시간계수(PHF)를 뽑아 교차로 입력을 채운다.

입력 형식(긴 형식, 한 행 = 한 접근로의 15분 구간):
    날짜(선택), 시각, 접근로, 좌회전, 직진, 우회전, U턴(선택), 대형차(선택: 위 교통량 중 대형차 대수)

계산 규칙
- 15분 구간의 시작 시각을 쓴다(07:00 = 07:00~07:15). 한 행 이상이 같은 (날짜, 시각, 접근로)이면 더한다(차로·차종별 행 지원).
- 날짜가 여러 개면 같은 (시각, 접근로)끼리 평균한다(지침이 요구하는 복수 일 조사 평균).
- 첨두시는 연속한 4개 구간(1시간) 중 교차로 전체 교통량이 최대인 구간이며, AM은 06~10시, PM은 16~20시 안에서 찾는다.
  구간 안에 한 접근로라도 빠진 15분이 있으면 그 시간대는 후보에서 제외한다(빠진 값을 0으로 보면 첨두가 왜곡된다).
- PHF = 첨두 1시간 교통량 ÷ (4 × 첨두 1시간 안 최대 15분 교통량), 교차로 전체 기준(편람 식 8-1의 시간교통량 보정에 사용).
이 모듈은 값을 추정하지 않는다. 읽을 수 없는 행이 있으면 어느 행인지 알려 주며 전체를 거부한다.
"""
import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass

MAX_ROWS = 20_000
MAX_APPROACHES = 8
PEAK_WINDOWS = {"am": (6 * 60, 10 * 60), "pm": (16 * 60, 20 * 60)}  # 분 단위 [시작, 끝)
PHF_WARN_BELOW = 0.8  # 임의 기준: 이보다 낮으면 15분 변동이 매우 큰 것이므로 자료 입력 오류인지 확인하라고 알린다

ALIASES = {
    "date": ("날짜", "일자", "조사일", "date"),
    "time": ("시각", "시간", "시작시각", "time"),
    "approach": ("접근로", "방향", "방면", "approach"),
    "left": ("좌회전", "좌", "left", "lt"),
    "through": ("직진", "직", "through", "th"),
    "right": ("우회전", "우", "right", "rt"),
    "uturn": ("u턴", "유턴", "uturn", "u-turn"),
    "heavy": ("대형차", "중차량", "heavy"),
}
REQUIRED = ("time", "approach", "left", "through", "right")
MOVES = ("left", "through", "right", "uturn")
LABELS = {"time": "시각", "approach": "접근로", "left": "좌회전", "through": "직진", "right": "우회전"}


class CountsError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 입력 오류."""


@dataclass
class _Row:
    day: str
    minute: int
    approach: str
    mv: dict[str, float]
    heavy: float | None


def _norm(h: str) -> str:
    return re.sub(r"[\s_()（）]", "", h.strip().lower().lstrip("﻿"))


def _column_map(header: list[str]) -> dict[str, int]:
    norm = [_norm(h) for h in header]
    out: dict[str, int] = {}
    for key, names in ALIASES.items():
        for n in names:
            if _norm(n) in norm:
                out[key] = norm.index(_norm(n))
                break
    missing = [LABELS[k] for k in REQUIRED if k not in out]
    if missing:
        raise CountsError(f"필수 열이 없습니다: {', '.join(missing)}. 첫 행에 열 이름(시각, 접근로, 좌회전, 직진, 우회전)이 있어야 합니다.")
    return out


def _parse_minute(raw: str, line: int) -> int:
    m = re.fullmatch(r"\s*(\d{1,2})\s*[:시]\s*(\d{1,2})\s*(?:분)?(?::\d{1,2})?\s*", raw) or re.fullmatch(r"\s*(\d{2})(\d{2})\s*", raw)
    if not m:
        raise CountsError(f"{line}행: 시각 '{raw}'을(를) 읽을 수 없습니다(예: 07:00).")
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        raise CountsError(f"{line}행: 시각 '{raw}'이(가) 올바르지 않습니다.")
    if mi % 15:
        raise CountsError(f"{line}행: 시각 '{raw}'이(가) 15분 단위가 아닙니다(00·15·30·45분만 가능).")
    return h * 60 + mi


def _parse_num(raw: str, what: str, line: int) -> float:
    s = raw.strip().replace(",", "")
    if s in ("", "-"):
        return 0.0
    try:
        v = float(s)
    except ValueError:
        raise CountsError(f"{line}행: {what} '{raw}'은(는) 숫자가 아닙니다.") from None
    if v < 0 or v != v or v == float("inf"):
        raise CountsError(f"{line}행: {what} '{raw}'은(는) 0 이상의 수여야 합니다.")
    return v


def _read_rows(text: str) -> list[_Row]:
    text = text.lstrip("﻿")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise CountsError("자료가 없습니다. 첫 행은 열 이름, 둘째 행부터 15분 단위 교통량이어야 합니다.")
    if len(lines) - 1 > MAX_ROWS:
        raise CountsError(f"행이 너무 많습니다(최대 {MAX_ROWS:,}행).")
    delim = max((",", "\t", ";"), key=lambda d: lines[0].count(d))
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)
    header = next(reader)
    cols = _column_map(header)
    rows: list[_Row] = []
    for i, rec in enumerate(reader, start=2):
        if not any(c.strip() for c in rec):
            continue

        def cell(key: str) -> str:
            j = cols.get(key)
            return rec[j] if j is not None and j < len(rec) else ""

        name = cell("approach").strip()
        if not name:
            raise CountsError(f"{i}행: 접근로 이름이 비어 있습니다.")
        mv = {k: _parse_num(cell(k), LABELS.get(k, k), i) if k in cols else 0.0 for k in MOVES}
        heavy = _parse_num(cell("heavy"), "대형차", i) if "heavy" in cols else None
        total = sum(mv.values())
        if heavy is not None and heavy > total + 1e-9:
            raise CountsError(f"{i}행: 대형차({heavy:g})가 해당 행 전체 교통량({total:g})보다 많습니다.")
        rows.append(_Row(cell("date").strip(), _parse_minute(cell("time"), i), name, mv, heavy))
    return rows


def _aggregate(rows: list[_Row]):
    """(날짜, 분, 접근로)로 합산 → (분, 접근로)별 날짜 평균. 반환: {(분, 접근로): {move: 평균, 'heavy': 평균|None}}, 날짜 수."""
    per_day: dict[tuple[str, int, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    has_heavy = any(r.heavy is not None for r in rows)
    for r in rows:
        d = per_day[(r.day, r.minute, r.approach)]
        for k in MOVES:
            d[k] += r.mv[k]
        if has_heavy:
            d["heavy"] += r.heavy or 0.0
    days = {k[0] for k in per_day}
    by_bin: dict[tuple[int, str], list[dict[str, float]]] = defaultdict(list)
    for (_, minute, name), d in per_day.items():
        by_bin[(minute, name)].append(d)
    avg = {}
    for key, ds in by_bin.items():
        avg[key] = {k: sum(d[k] for d in ds) / len(ds) for k in (*MOVES, *(("heavy",) if has_heavy else ()))}
    return avg, len(days), has_heavy


def _fmt(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _peak(avg: dict, names: list[str], lo: int, hi: int, has_heavy: bool):
    best = None
    skipped = 0
    for start in range(lo, hi - 45, 15):
        bins = [start + 15 * i for i in range(4)]
        if any((b, n) not in avg for b in bins for n in names):
            skipped += 1
            continue
        per_bin = [sum(sum(avg[(b, n)][k] for k in MOVES) for n in names) for b in bins]
        total = sum(per_bin)
        if best is None or total > best[0]:
            best = (total, start, max(per_bin))
    if best is None:
        return None, skipped
    total, start, peak15 = best
    bins = [start + 15 * i for i in range(4)]
    appr = {}
    for n in names:
        vol = {k: sum(avg[(b, n)][k] for b in bins) for k in MOVES}
        entry = {"v_left": round(vol["left"]), "v_through": round(vol["through"]), "v_right": round(vol["right"]),
                 "u_turn": round(vol["uturn"])}
        tot_n = sum(vol.values())
        if has_heavy and tot_n > 0:
            entry["heavy_pct"] = round(100 * sum(avg[(b, n)]["heavy"] for b in bins) / tot_n, 1)
        appr[n] = entry
    phf = min(1.0, total / (4 * peak15)) if peak15 > 0 else 1.0
    return {"start": _fmt(start), "end": _fmt(start + 60), "total": round(total), "phf": round(phf, 3), "approaches": appr}, skipped


def parse_counts(text: str) -> dict:
    """CSV 본문 → {"peaks": {"am": {...}|None, "pm": {...}|None}, "approaches": [...], "days": n, "rows": n, "warnings": [...]}."""
    rows = _read_rows(text)
    names = list(dict.fromkeys(r.approach for r in rows))  # 입력 순서 유지
    if len(names) > MAX_APPROACHES:
        raise CountsError(f"접근로가 {len(names)}개입니다(최대 {MAX_APPROACHES}개).")
    avg, days, has_heavy = _aggregate(rows)
    warnings: list[str] = []
    peaks = {}
    for key, (lo, hi) in PEAK_WINDOWS.items():
        peaks[key], skipped = _peak(avg, names, lo, hi, has_heavy)
        label = key.upper()
        if peaks[key] is None:
            warnings.append(f"{label} 첨두({_fmt(lo)}~{_fmt(hi)}): 모든 접근로의 15분 자료가 연속 1시간 이상 있는 시간대가 없어 계산하지 못했습니다.")
        else:
            if skipped:
                warnings.append(f"{label} 첨두: 접근로 자료가 빠진 시간대 {skipped}곳은 후보에서 제외했습니다.")
            if peaks[key]["phf"] < PHF_WARN_BELOW:
                warnings.append(f"{label} 첨두 PHF가 {peaks[key]['phf']:.2f}로 낮습니다. 15분 자료가 맞는지 확인하세요.")
    if not any(peaks.values()):
        raise CountsError("AM(06~10시)·PM(16~20시) 어느 쪽에서도 첨두 1시간을 찾지 못했습니다. 15분 단위로 모든 접근로의 자료가 연속되어야 합니다.")
    if days > 1:
        warnings.append(f"조사일 {days}일의 같은 시각·접근로를 평균했습니다.")
    if not has_heavy:
        warnings.append("대형차 열이 없어 중차량 비율은 채우지 않았습니다.")
    return {"peaks": peaks, "approaches": names, "days": days, "rows": len(rows), "warnings": warnings}
