"""결과 도표: 계산 결과에서 차트 명세를 만들고 웹용 SVG와 DOCX용 텍스트 막대로 그린다.

- 명세(dict)는 계산 결과(state)에서만 만들며 새 수치를 만들지 않는다.
- 웹: 인라인 SVG(색은 CSS 변수라 다크 모드 대응). DOCX: 외부 이미지·폰트 의존이 없도록 '█' 텍스트 막대 표.
- 범주 색은 검증된 3색(파랑·주황·청록, 라이트·다크 all-pairs 통과). 청록은 라이트에서 대비 3:1 미만이라 모든 막대에 값 라벨을 붙인다.
"""
import math
from html import escape

from app.los import LOS_THRESHOLDS
from app.state import ReportState

SERIES_COLORS = {  # 슬롯 → (라이트, 다크)
    1: ("#2a78d6", "#3987e5"),
    2: ("#eb6834", "#d95926"),
    3: ("#1baf7a", "#199e70"),
}
STAGE_SERIES = [("without", "사업 미시행", 1), ("with", "사업 시행", 2), ("improved", "개선 후", 3)]


def _nice_scale(v: float, n: int = 5) -> tuple[float, float]:
    """(축 최댓값, 눈금 간격): 간격은 1·2·5×10^k, 최댓값은 v 이상의 간격 배수."""
    if v <= 0:
        return 1.0, 0.25
    raw = v / n
    exp = 10 ** math.floor(math.log10(raw))
    step = next(m * exp for m in (1, 2, 5, 10) if raw <= m * exp)
    return round(math.ceil(v / step - 1e-9) * step, 10), step


def _ticks(vmax: float, step: float) -> list[float]:
    return [round(i * step, 10) for i in range(int(round(vmax / step)) + 1)]


# ── 명세 ──

def _los_bands(ymax: float) -> list[dict]:
    """축 범위 [0, ymax]와 겹치는 LOS 등급 구간: {lo, hi(축 최댓값으로 자름), edge(경계선 위치 또는 None), label}."""
    out, lo = [], 0.0
    for v, g in LOS_THRESHOLDS:
        if lo >= ymax:
            break
        out.append({"lo": lo, "hi": min(v, ymax), "edge": v if v < ymax else None, "label": g})
        lo = v
    return out


def stage_charts(state: ReportState) -> list[dict]:
    """교차로별 3단계(미시행/시행/개선 후) 평균지체 비교. 목표년도가 묶음."""
    out = []
    for name, years in state.stages.items():
        groups = []
        for y, st in years.items():
            groups.append({"label": f"준공 후 {y}년", "bars": [
                {"series": label, "slot": slot, "value": st[k]["avg_delay"], "text": f"{st[k]['avg_delay']:.1f}초 ({st[k]['grade']})"}
                for k, label, slot in STAGE_SERIES]})
        peak = max(b["value"] for g in groups for b in g["bars"])
        ymax, ystep = _nice_scale(peak * 1.12)
        out.append({
            "id": f"stage-{len(out) + 1}", "kind": "grouped", "title": f"{name} — 3단계 평균 제어지체", "unit": "초/대",
            "series": [(label, slot) for _, label, slot in STAGE_SERIES], "groups": groups, "ymax": ymax, "ystep": ystep,
            "bands": _los_bands(ymax),
            "summary": f"{name} 사업 미시행·시행·개선 후 평균 제어지체(초/대) 비교",
            "note": "점선은 LOS 등급 경계, 오른쪽 글자는 그 구간의 등급(도로용량편람 <표 8-2>)",
        })
    return out


def vc_charts(state: ReportState) -> list[dict]:
    """교차로별 현황 접근로(차로군) v/c. 용량 한계 1.0을 기준선으로 둔다."""
    out = []
    for name, v in state.los.items():
        bars = [{"label": r["approach"], "value": r["vc_ratio"], "slot": 1,
                 "text": f"{r['vc_ratio']:.2f}" + (f" ({r['los']})" if r.get("los") else "")} for r in v["results"]]
        if not bars:
            continue
        peak = max(b["value"] for b in bars)
        xmax, xstep = _nice_scale(max(peak, 1.0) * 1.12)
        out.append({"id": f"vc-{len(out) + 1}", "kind": "hbar", "title": f"{name} — 현황 접근로별 v/c", "unit": "v/c",
                    "bars": bars, "xmax": xmax, "xstep": xstep,
                    "ref": {"value": 1.0, "label": "용량 한계 v/c 1.0"},
                    "summary": f"{name} 접근로(차로군)별 v/c 비교", "note": "괄호는 접근로 LOS"})
    return out


def parking_chart(state: ReportState) -> list[dict]:
    pk = state.parking
    if not pk:
        return []
    bars = []
    if pk.get("legal_total") is not None:
        bars.append({"label": "법정 주차대수", "value": pk["legal_total"], "slot": 1, "text": f"{pk['legal_total']:,}대"})
        bars.append({"label": f"권장 상한({pk['cap_pct']:g}%)", "value": pk["cap"], "slot": 1, "text": f"{pk['cap']:,.0f}대"})
    if pk.get("planned") is not None:
        bars.append({"label": "계획 주차대수", "value": pk["planned"], "slot": 1, "text": f"{pk['planned']:,}대"})
    bars.append({"label": "원단위법 수요" + (" (임시)" if pk["rate_status"] == "PROVISIONAL" else ""), "value": pk["demand"],
                 "slot": 1, "text": f"{pk['demand']:,.0f}대"})
    if len(bars) < 2:
        return []
    pmax, pstep = _nice_scale(max(b["value"] for b in bars) * 1.15)
    return [{"id": "parking-1", "kind": "hbar", "title": "주차대수 비교", "unit": "대", "bars": bars,
             "xmax": pmax, "xstep": pstep, "ref": None,
             "summary": "법정·권장 상한·계획 주차대수와 원단위법 수요 비교",
             "note": "수요는 임시 원단위 기준이면 잠정값" if pk["rate_status"] == "PROVISIONAL" else ""}]


def build_charts(state: ReportState) -> dict[str, list[dict]]:
    return {"vc": vc_charts(state), "stage": stage_charts(state), "parking": parking_chart(state)}


def chart_rows(spec: dict) -> tuple[list[str], list[list[str]]]:
    """표 보기(접근성): 명세와 같은 값을 표로."""
    if spec["kind"] == "grouped":
        header = ["구분"] + [s for s, _ in spec["series"]]
        return header, [[g["label"]] + [b["text"] for b in g["bars"]] for g in spec["groups"]]
    return ["항목", spec["unit"]], [[b["label"], b["text"]] for b in spec["bars"]]


# ── 웹: SVG ──

W = 640


def _legend(series, x0: int, y: int) -> str:
    out, x = [], x0
    for name, slot in series:
        out.append(f'<rect x="{x}" y="{y - 9}" width="10" height="10" rx="2" class="s{slot}"/>'
                   f'<text x="{x + 15}" y="{y}" class="vt">{escape(name)}</text>')
        x += 24 + 13 * len(name)
    return "".join(out)


def svg_grouped(spec: dict) -> str:
    left, right, top, bottom = 48, 40, 34, 34
    H = 270
    pw, ph = W - left - right, H - top - bottom
    ymax = spec["ymax"]
    y = lambda v: top + ph - ph * v / ymax  # noqa: E731
    parts = [f'<svg viewBox="0 0 {W} {H}" class="viz-svg" role="img" aria-label="{escape(spec["summary"])}">',
             f"<title>{escape(spec['title'])}</title>", _legend(spec["series"], left, 16)]
    for b in spec["bands"]:  # LOS 경계(점선) + 구간 가운데 오른쪽에 등급 글자
        if b["edge"] is not None:
            parts.append(f'<line x1="{left}" x2="{left + pw}" y1="{y(b["edge"]):.1f}" y2="{y(b["edge"]):.1f}" class="vgrid dash"/>')
        parts.append(f'<text x="{left + pw + 8}" y="{y((b["lo"] + b["hi"]) / 2) + 4:.1f}" class="vt muted">{escape(b["label"])}</text>')
    parts.append(f'<line x1="{left}" x2="{left + pw}" y1="{y(0):.1f}" y2="{y(0):.1f}" class="vaxis"/>')
    for v in _ticks(ymax, spec["ystep"]):
        parts.append(f'<text x="{left - 6}" y="{y(v) + 4:.1f}" class="vt muted" text-anchor="end">{v:g}</text>')
    ng = len(spec["groups"])
    gw = pw / ng
    for gi, g in enumerate(spec["groups"]):
        nb = len(g["bars"])
        bw = min(46, gw * 0.7 / nb - 2)
        x0 = left + gi * gw + (gw - nb * (bw + 2)) / 2
        for bi, b in enumerate(g["bars"]):
            x = x0 + bi * (bw + 2)
            h = max(ph * b["value"] / ymax, 1)
            parts.append(f'<rect x="{x:.1f}" y="{y(b["value"]):.1f}" width="{bw:.1f}" height="{h:.1f}" rx="3" class="s{b["slot"]} vbar">'
                         f"<title>{escape(g['label'])} {escape(b['series'])}: {escape(b['text'])}</title></rect>"
                         f'<text x="{x + bw / 2:.1f}" y="{y(b["value"]) - 5:.1f}" class="vt" text-anchor="middle">{b["value"]:.1f}</text>')
        parts.append(f'<text x="{left + gi * gw + gw / 2:.1f}" y="{H - 12}" class="vt" text-anchor="middle">{escape(g["label"])}</text>')
    parts.append(f'<text x="{left - 40}" y="{top - 6}" class="vt muted">{escape(spec["unit"])}</text></svg>')
    return "".join(parts)


def svg_hbar(spec: dict) -> str:
    bars = spec["bars"]
    left, right, top = 170, 70, 12
    row = 30
    H = top + row * len(bars) + 28
    pw = W - left - right
    xmax = spec["xmax"]
    x = lambda v: left + pw * v / xmax  # noqa: E731
    parts = [f'<svg viewBox="0 0 {W} {H}" class="viz-svg" role="img" aria-label="{escape(spec["summary"])}">',
             f"<title>{escape(spec['title'])}</title>"]
    for v in _ticks(xmax, spec["xstep"]):
        parts.append(f'<line x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{top}" y2="{H - 24}" class="vgrid"/>'
                     f'<text x="{x(v):.1f}" y="{H - 8}" class="vt muted" text-anchor="middle">{v:g}</text>')
    for i, b in enumerate(bars):
        yy = top + i * row
        w = max(pw * b["value"] / xmax, 1)
        parts.append(f'<text x="{left - 8}" y="{yy + 17}" class="vt" text-anchor="end">{escape(b["label"])}</text>'
                     f'<rect x="{left}" y="{yy + 4}" width="{w:.1f}" height="18" rx="3" class="s{b["slot"]} vbar">'
                     f"<title>{escape(b['label'])}: {escape(b['text'])}</title></rect>"
                     f'<text x="{left + w + 6:.1f}" y="{yy + 17}" class="vt">{escape(b["text"])}</text>')
    if spec.get("ref"):
        rx = x(spec["ref"]["value"])
        parts.append(f'<line x1="{rx:.1f}" x2="{rx:.1f}" y1="{top - 4}" y2="{H - 24}" class="vref"/>'
                     f'<text x="{rx + 4:.1f}" y="{top + 6}" class="vt muted">{escape(spec["ref"]["label"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def render_svg(spec: dict) -> str:
    return svg_grouped(spec) if spec["kind"] == "grouped" else svg_hbar(spec)


# ── DOCX: 텍스트 막대 ──

def docx_bar_rows(spec: dict, width: int = 36) -> tuple[list[str], list[list[tuple[str, int | None]]]]:
    """(표 머리글, 행들). 셀은 (텍스트, 색 슬롯) — 슬롯이 있으면 '█' 막대로 그린다."""
    rows = []
    if spec["kind"] == "grouped":
        top = spec["ymax"]
        for g in spec["groups"]:
            for b in g["bars"]:
                n = max(1, round(width * b["value"] / top))
                rows.append([(g["label"], None), (b["series"], None), ("█" * n, b["slot"]), (b["text"], None)])
        return ["구분", "단계", f"평균 제어지체({spec['unit']})", "값(LOS)"], rows
    top = spec["xmax"]
    for b in spec["bars"]:
        n = max(1, round(width * b["value"] / top))
        rows.append([(b["label"], None), ("█" * n, b["slot"]), (b["text"], None)])
    return ["항목", f"{spec['unit']}", "값"], rows
