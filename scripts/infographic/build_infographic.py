#!/usr/bin/env python3
"""Build the city-GDP infographic (HTML -> PNG via headless Chrome).

Reads output/城市GDP分析.xlsx (single source of truth) and writes
.infographic/infographic.html with hand-composed SVG charts.
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
XLSX = ROOT / "output" / "城市GDP分析.xlsx"
WORK = ROOT / ".infographic"
WORK.mkdir(exist_ok=True)

CITIES = ["纽约", "伦敦", "东京", "新加坡", "北京", "上海", "深圳", "香港"]
MAINLAND = ["北京", "上海", "深圳"]
COLOR = {
    "纽约": "#1C2E4A",
    "伦敦": "#46698C",
    "东京": "#8299B2",
    "新加坡": "#2A9D8F",
    "香港": "#D2952C",
    "北京": "#7A1E1E",
    "上海": "#B23A2B",
    "深圳": "#E06A45",
}
CSS_CITY = {c: f"c{ i }" for i, c in enumerate(CITIES)}


# ---------------------------------------------------------------- data
def load() -> dict[str, dict[str, dict[int, float]]]:
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb["城市GDP"]
    data: dict[str, dict[str, dict[int, float]]] = {}
    for row in ws.iter_rows(min_row=4, max_row=39, values_only=True):
        if not row[0] or row[1] is None:
            continue
        metric, year = str(row[0]).strip(), int(row[1])
        for city, value in zip(CITIES, row[2:10]):
            if value is not None:
                data.setdefault(metric, {}).setdefault(city, {})[year] = float(value)
    return data


D = load()
GDP = D["区域GDP（亿美元）"]
PRIMACY = D["经济首位度（%）"]
PERCAP = D["人均GDP（美元/人）"]
DENSITY = D["地均GDP（亿美元/km²）"]


def fmt(x: float, digits: int = 0) -> str:
    return f"{x:,.{digits}f}"


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def spread(labels: list[dict], gap: float, lo: float, hi: float) -> None:
    """Push 1-D label positions apart, keeping order; write back 'ly'."""
    order = sorted(range(len(labels)), key=lambda i: labels[i]["y"])
    ys = [labels[i]["y"] for i in order]
    for k in range(1, len(ys)):
        ys[k] = max(ys[k], ys[k - 1] + gap)
    if ys and ys[-1] > hi:
        ys[-1] = hi
        for k in range(len(ys) - 2, -1, -1):
            ys[k] = min(ys[k], ys[k + 1] - gap)
    for k, i in enumerate(order):
        labels[i]["ly"] = ys[k]


# ---------------------------------------------------------------- chart 1: GDP lines
def line_chart() -> str:
    W, H = 1372, 500
    L, R, T, B = 58, 162, 24, 34
    x0, x1 = L, W - R
    y0, y1 = T, H - B
    ymax = 15000

    def sx(year: float) -> float:
        return x0 + (year - 2000) / 25 * (x1 - x0)

    def sy(v: float) -> float:
        return y1 - v / ymax * (y1 - y0)

    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="八城 GDP 走势">']

    # grid + y axis
    for v in range(0, 15001, 3000):
        yy = sy(v)
        cls = "base" if v == 0 else "grid"
        out.append(f'<line class="{cls}" x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}"/>')
        out.append(f'<text class="tick" x="{x0 - 10}" y="{yy + 3.5:.1f}" text-anchor="end">{fmt(v)}</text>')
    # x axis
    for yr in (2000, 2005, 2010, 2015, 2020, 2025):
        xx = sx(yr)
        out.append(f'<line class="grid" x1="{xx:.1f}" y1="{y0}" x2="{xx:.1f}" y2="{y1}"/>')
        out.append(f'<text class="tick" x="{xx:.1f}" y="{y1 + 18}" text-anchor="middle">{yr}</text>')

    # series
    for city in CITIES:
        pts = sorted(GDP[city].items())
        segments, cur = [], []
        for i, (yr, val) in enumerate(pts):
            if cur and yr - cur[-1][0] > 6:
                segments.append(cur)
                cur = []
            cur.append((yr, val))
        if cur:
            segments.append(cur)
        for seg in segments:
            d = " ".join(("M" if i == 0 else "L") + f"{sx(y):.1f},{sy(v):.1f}" for i, (y, v) in enumerate(seg))
            out.append(f'<path class="line {CSS_CITY[city]}" d="{d}"/>')
        for yr, val in pts:
            out.append(f'<circle class="dot {CSS_CITY[city]}" cx="{sx(yr):.1f}" cy="{sy(val):.1f}" r="2.8"/>')
        yr, val = max(pts)
        out.append(f'<circle class="enddot {CSS_CITY[city]}" cx="{sx(yr):.1f}" cy="{sy(val):.1f}" r="4.6"/>')

    # end labels
    labels = []
    for city in CITIES:
        yr, val = max(GDP[city].items())
        labels.append({"city": city, "y": sy(val), "val": val, "year": yr, "x": sx(yr)})
    spread(labels, 23, y0 + 4, y1 - 2)

    gx = x1 + 10
    for lb in labels:
        col = COLOR[lb["city"]]
        out.append(
            f'<path class="leader" d="M{lb["x"] + 4:.1f},{lb["y"]:.1f} L{x1 + 5:.1f},{lb["ly"]:.1f} L{gx - 4:.1f},{lb["ly"]:.1f}" stroke="{col}"/>'
        )
        out.append(
            f'<text class="end-label" x="{gx}" y="{lb["ly"] - 1:.1f}" fill="{col}">{lb["city"]}'
            f'<tspan class="end-val" fill="#17181C"> {fmt(lb["val"])}</tspan></text>'
        )

    # annotation: 京沪深 sum overtakes NY
    ax = sx(2000.6)
    out.append(f'<line class="accent-rule" x1="{ax:.1f}" y1="{sy(14200):.1f}" x2="{ax + 30:.1f}" y2="{sy(14200):.1f}"/>')
    out.append(f'<text class="anno" x="{ax + 26:.1f}" y="{sy(14150):.1f}">京沪深合计 20,517 亿美元（2025）</text>')
    out.append(
        f'<text class="anno-sub" x="{ax + 26:.1f}" y="{sy(14150) + 18:.1f}">'
        f'是纽约（2024 年 13,778 亿美元）的 <tspan class="accent">1.49 倍</tspan>；2005 年这一比值只有 0.49</text>'
    )

    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- chart 2: growth dumbbell
def dumbbell() -> str:
    W, H = 676, 396
    L, R, T = 64, 490, 30
    rows = [c for c in CITIES if 2005 in GDP[c] and 2024 in GDP[c]]
    rows.sort(key=lambda c: GDP[c][2024], reverse=True)
    vmax = 15000

    def sx(v: float) -> float:
        return L + v / vmax * (R - L)

    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="2005 到 2024 GDP 增长">']
    for v in (0, 5000, 10000, 15000):
        xx = sx(v)
        out.append(f'<line class="grid" x1="{xx:.1f}" y1="{T}" x2="{xx:.1f}" y2="{H - 62}"/>')
        out.append(f'<text class="tick" x="{xx:.1f}" y="{H - 44}" text-anchor="middle">{fmt(v)}</text>')


    step = (H - 100) / max(len(rows), 1)
    for i, city in enumerate(rows):
        y = T + step * (i + 0.55)
        a, b = GDP[city][2005], GDP[city][2024]
        col = COLOR[city]
        out.append(f'<text class="row-name" x="0" y="{y + 4:.1f}" fill="{col}">{city}</text>')
        out.append(f'<line class="track" x1="{sx(a):.1f}" y1="{y:.1f}" x2="{sx(b):.1f}" y2="{y:.1f}" stroke="{col}"/>')
        out.append(f'<circle class="dot-out" cx="{sx(a):.1f}" cy="{y:.1f}" r="4.2"/>')
        out.append(f'<circle cx="{sx(b):.1f}" cy="{y:.1f}" r="5.4" fill="{col}"/>')
        out.append(f'<text class="row-val" x="502" y="{y + 4:.1f}">{fmt(b)}</text>')
        out.append(f'<text class="row-mult" x="594" y="{y + 4:.1f}">×{b / a:.2f}</text>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- chart 3: per-capita vs density
def scatter() -> str:
    W, H = 676, 396
    L, R, T, B = 46, 12, 14, 48
    x0, x1 = L, W - R
    y0, y1 = T, H - B
    xmin, xmax = 24000, 200000
    ymin, ymax = 0.28, 28
    yr = 2023

    def sx(v: float) -> float:
        return x0 + (math.log(v) - math.log(xmin)) / (math.log(xmax) - math.log(xmin)) * (x1 - x0)

    def sy(v: float) -> float:
        return y1 - (math.log(v) - math.log(ymin)) / (math.log(ymax) - math.log(ymin)) * (y1 - y0)

    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="人均 GDP 与地均 GDP">']
    for v, lab in ((0.5, "0.5"), (1, "1"), (2, "2"), (5, "5"), (10, "10"), (20, "20")):
        yy = sy(v)
        out.append(f'<line class="grid" x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}"/>')
        out.append(f'<text class="tick" x="{x0 - 8}" y="{yy + 3.5:.1f}" text-anchor="end">{lab}</text>')
    for v in (30000, 50000, 100000, 150000):
        xx = sx(v)
        out.append(f'<line class="grid" x1="{xx:.1f}" y1="{y0}" x2="{xx:.1f}" y2="{y1}"/>')
        out.append(f'<text class="tick" x="{xx:.1f}" y="{y1 + 17}" text-anchor="middle">{v // 1000},000</text>')
    out.append(f'<text class="axis-title" x="{x1}" y="{H - 16}" text-anchor="end">人均 GDP（美元/人，对数）</text>')
    out.append(f'<text class="axis-title" x="{x0}" y="{y0 - 2}" text-anchor="start">地均 GDP（亿美元/km²，对数）</text>')

    # bubbles, big first
    order = sorted(CITIES, key=lambda c: GDP[c][yr], reverse=True)
    for city in order:
        g = GDP[city][yr]
        r = 4 + 20 * math.sqrt(g / 14000)
        cx, cy = sx(PERCAP[city][yr]), sy(DENSITY[city][yr])
        out.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{COLOR[city]}" fill-opacity="0.82" '
            f'stroke="#F7F4EC" stroke-width="1.5"/>'
        )

    # labels (manual offsets to avoid the cluster)
    lab = {
        "纽约": (-34, 4, "end"),
        "伦敦": (-30, -10, "end"),
        "新加坡": (27, -2, "start"),
        "东京": (0, 36, "middle"),
        "香港": (-20, -16, "end"),
        "上海": (25, 5, "start"),
        "北京": (25, 5, "start"),
        "深圳": (24, 1, "start"),
    }
    for city, (dx, dy, anchor) in lab.items():
        cx, cy = sx(PERCAP[city][yr]), sy(DENSITY[city][yr])
        out.append(
            f'<text class="bubble-label" x="{cx + dx:.1f}" y="{cy + dy:.1f}" text-anchor="{anchor}" fill="{COLOR[city]}">{city}</text>'
        )

    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- chart 4: primacy cards
def spark(city: str, w: int = 144, h: int = 150) -> str:
    series = sorted(PRIMACY[city].items())
    x0, x1, y0, y1 = 2, w - 4, 8, h - 12

    def sx(yr: float) -> float:
        return x0 + (yr - 2000) / 25 * (x1 - x0)

    def sy(v: float) -> float:
        return y1 - v / 25 * (y1 - y0)

    out = [f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}">']
    out.append(f'<line class="grid" x1="{x0}" y1="{sy(0):.1f}" x2="{x1}" y2="{sy(0):.1f}"/>')
    d = " ".join(("M" if i == 0 else "L") + f"{sx(y):.1f},{sy(v):.1f}" for i, (y, v) in enumerate(series))
    area = f"M{sx(series[0][0]):.1f},{sy(0):.1f} " + d[1:] + f" L{sx(series[-1][0]):.1f},{sy(0):.1f} Z"
    out.append(f'<path d="{area}" fill="{COLOR[city]}" fill-opacity="0.09" stroke="none"/>')
    out.append(f'<path class="line" d="{d}" stroke="{COLOR[city]}"/>')
    ly, lv = series[-1]
    out.append(f'<circle cx="{sx(ly):.1f}" cy="{sy(lv):.1f}" r="3.4" fill="{COLOR[city]}"/>')
    out.append("</svg>")
    return "".join(out)


CARDS = [
    ("伦敦", "22.7%", "+2.5pp", "2000 → 2024", ""),
    ("东京", "20.3%", "+0.3pp", "2015 → 2023", ""),
    ("上海", "4.0%", "−0.8pp", "2000 → 2025", ""),
    ("香港", "2.2%", "−84%", "2000 → 2025", "down"),
]


def primacy_cards() -> str:
    parts = ['<div class="cards">']
    for city, val, delta, period, cls in CARDS:
        parts.append(
            f'<div class="card" style="border-top-color:{COLOR[city]}">'
            f'<div class="card-name">{city}</div>'
            f'<div class="card-val">{val}</div>'
            f'<div class="card-delta {cls}">较 {period.split(" → ")[0]} 年 {delta}</div>'
            f'{spark(city)}'
            f'<div class="card-period">{period}</div>'
            f"</div>"
        )
    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------- page
CSS = """
:root {
  --paper:#F7F4EC; --ink:#17181C; --muted:#726C61; --rule:#DCD4C4;
  --sans:"PingFang SC","Hiragino Sans GB","Heiti SC",-apple-system,"Helvetica Neue",sans-serif;
  --serif:"Songti SC","STSong","Hiragino Mincho ProN",serif;
  --num:"Avenir Next","Helvetica Neue",-apple-system,sans-serif;
}
* { box-sizing:border-box; }
html,body { margin:0; padding:0; background:var(--paper); }
body { -webkit-font-smoothing:antialiased; text-rendering:geometricPrecision; }
.page { width:1500px; background:var(--paper); color:var(--ink); padding:54px 64px 46px;
        font-family:var(--sans); position:relative; }
.page::after { content:""; position:absolute; inset:20px; border:1px solid rgba(23,24,28,.10); pointer-events:none; }
header { position:relative; }
.kicker { font-family:var(--num); font-size:12px; letter-spacing:.22em; text-transform:uppercase;
          color:var(--muted); display:flex; gap:14px; align-items:center; }
.kicker .dot { width:6px; height:6px; border-radius:50%; background:#B23A2B; display:inline-block; }
.masthead { display:flex; justify-content:space-between; align-items:flex-end; gap:40px; }
h1 { font-family:var(--serif); font-weight:700; font-size:88px; line-height:1.0; margin:16px 0 0;
     letter-spacing:-.02em; }
h1 em { font-style:normal; color:#B23A2B; }
.deck { font-size:18px; line-height:1.66; margin:20px 0 0; max-width:1120px; color:#33322E; }
.deck b { font-weight:600; }
.meta { text-align:right; font-family:var(--num); font-size:11.5px; line-height:1.75; color:var(--muted);
        letter-spacing:.06em; white-space:nowrap; padding-bottom:6px; }
.meta strong { color:var(--ink); font-weight:600; letter-spacing:.12em; font-size:12.5px; }

.kpis { display:flex; gap:26px; margin-top:38px; }
.kpi { flex:1; border-top:2px solid var(--ink); padding-top:14px; }
.kpi .lab { font-size:12px; color:var(--muted); letter-spacing:.04em; }
.kpi .val { font-family:var(--num); font-size:44px; font-weight:600; line-height:1.12; margin-top:6px;
            letter-spacing:-.015em; font-variant-numeric:tabular-nums; }
.kpi .val small { font-size:20px; font-weight:500; letter-spacing:0; margin-left:2px; }
.kpi .sub { font-size:11.5px; color:#4A463E; line-height:1.55; margin-top:7px; }

section { margin-top:42px; }
.sec-head { display:flex; align-items:baseline; gap:14px; border-bottom:1px solid var(--rule);
            padding-bottom:9px; margin-bottom:16px; }
.sec-no { font-family:var(--num); font-size:11.5px; letter-spacing:.16em; color:#B23A2B; font-weight:600; }
.sec-head h2 { font-size:19px; font-weight:600; margin:0; letter-spacing:.01em; }
.sec-head .aside { margin-left:auto; font-size:11.5px; color:var(--muted); font-family:var(--num); letter-spacing:.08em; }
.split { display:flex; gap:24px; align-items:stretch; }
.split > .panel { flex:1; min-width:0; display:flex; flex-direction:column; }
.split > .panel > .note:last-child { margin-top:auto; padding-top:10px; }
.panel h3 { font-size:14px; font-weight:600; margin:0 0 2px; }
.panel .hint { font-size:11px; color:var(--muted); margin:0 0 4px; }
.note { font-size:11.5px; line-height:1.65; color:var(--muted); margin:8px 0 0; }
.note b { color:#3A362F; font-weight:600; }

.chart { display:block; overflow:visible; }
.chart text { font-family:var(--sans); }
.grid { stroke:#E4DCCB; stroke-width:.8; }
.grid.faint { stroke:#EDE7DA; stroke-dasharray:2 4; }
.base { stroke:#B9AF9C; stroke-width:1; }
.tick { font-size:10.5px; fill:#8C8577; font-variant-numeric:tabular-nums; }
.axis-title { font-size:10.5px; fill:#8C8577; letter-spacing:.04em; }
.mark { stroke:#B9AF9C; stroke-width:1; stroke-dasharray:3 5; }
.mark-label { font-size:9.5px; fill:#8C8577; font-family:var(--num); }
.leader { fill:none; stroke-width:.9; stroke-opacity:.45; }
.end-label { font-size:13px; font-weight:600; letter-spacing:.01em; }
.end-val { font-family:var(--num); font-size:12.5px; font-weight:600; font-variant-numeric:tabular-nums; }
.anno { font-size:12.5px; fill:#4A463E; font-weight:600; }
.anno-sub { font-size:11px; fill:#8C8577; }
.line { fill:none; stroke-width:3; stroke-linecap:round; stroke-linejoin:round; }
svg .line { stroke-width:3; }
.dot { stroke:var(--paper); stroke-width:1; }
.row-name { font-size:12.5px; font-weight:600; }
.row-val { font-family:var(--num); font-size:13px; font-weight:600; fill:var(--ink); font-variant-numeric:tabular-nums; }
.row-mult { font-family:var(--num); font-size:11.5px; fill:#726C61; font-variant-numeric:tabular-nums; }
.track { stroke-width:2.6; stroke-opacity:.30; stroke-linecap:round; }
.dot-out { fill:var(--paper); stroke:#9C9382; stroke-width:1.2; }
.bubble-label { font-size:11.5px; font-weight:600; letter-spacing:.01em; }
.enddot { stroke:var(--paper); stroke-width:1.4; }
.accent-rule { stroke:#B23A2B; stroke-width:2.5; }
.accent { fill:#B23A2B; font-weight:600; }
.panel .sec-head h2 { font-size:15.5px; }
.panel .sec-head .sec-no { font-size:10.5px; }
.panel .sec-head .aside { font-size:10.5px; letter-spacing:.06em; }

.cards { display:flex; gap:12px; }
.card { flex:1; border-top:3px solid; padding-top:10px; }
.card-name { font-size:12px; color:var(--muted); letter-spacing:.06em; }
.card-val { font-family:var(--num); font-size:34px; font-weight:600; line-height:1.15; letter-spacing:-.01em;
            font-variant-numeric:tabular-nums; }
.card-delta { font-family:var(--num); font-size:11.5px; color:#6C675D; margin-top:1px; }
.card-delta span { font-family:var(--sans); color:#9A9386; margin-left:4px; letter-spacing:.02em; }
.card-delta.down { color:#B23A2B; font-weight:600; }
.spark { display:block; margin-top:8px; overflow:visible; }
.spark-tick { font-family:var(--num); font-size:8px; fill:#A9A193; }
.spark-year { font-family:var(--num); font-size:8.5px; fill:#A9A193; }
.card-period { font-size:10px; color:#9A9386; margin-top:2px; font-family:var(--num); letter-spacing:.04em; }

.findings { border-top:1px solid var(--rule); }
.find { display:flex; gap:14px; padding:12px 0 11px; border-bottom:1px solid var(--rule); }
.find:last-child { border-bottom:none; }
.find .fn { font-family:var(--num); font-size:11px; color:#B23A2B; font-weight:600; padding-top:4px; letter-spacing:.08em; }
.find h4 { margin:0 0 4px; font-size:14.5px; font-weight:600; letter-spacing:.01em; }
.find p { margin:0; font-size:12.5px; line-height:1.72; color:#3E3A33; }
.find p b { font-weight:600; color:var(--ink); font-family:var(--num); font-size:12.5px; }

footer { margin-top:38px; border-top:2px solid var(--ink); padding-top:12px;
         display:flex; gap:40px; align-items:flex-start; }
.src { flex:1; font-size:10px; line-height:1.72; color:#7E776A; }
.src b { color:#3A362F; font-weight:600; }
.stamp { font-family:var(--num); font-size:10px; color:#9A9386; text-align:right; letter-spacing:.08em; line-height:1.8; white-space:nowrap; }
"""


def city_css() -> str:
    return "\n".join(
        f'.line.{CSS_CITY[c]}{{stroke:{COLOR[c]}}} .dot.{CSS_CITY[c]}{{fill:{COLOR[c]}}}' for c in CITIES
    )


def build() -> str:
    total_25 = sum(GDP[c][2025] for c in MAINLAND)
    ratio = total_25 / GDP["纽约"][2024]
    sz = GDP["深圳"][2025] / GDP["深圳"][2000]
    cagr = (sz ** (1 / 25) - 1) * 100

    body = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>八座城市，一场重排｜城市 GDP 2000–2025</title>
<style>{CSS}{city_css()}</style></head>
<body><div class="page">

<header>
  <div class="masthead">
    <div>
      <div class="kicker"><span class="dot"></span>CITY GDP OBSERVATORY · 2000—2025</div>
      <h1>八座城市，<em>一场重排</em></h1>
    </div>
    <div class="meta"><strong>8 CITIES / 9 SNAPSHOTS</strong><br>现价美元 · 世界银行年均汇率<br>区域 GDP / 首位度 / 人均 / 地均</div>
  </div>
  <p class="deck">京沪深合计 25 年把总量追到<b>纽约的 1.49 倍</b>；但人均仍只有纽约的 <b>1/5 上下</b>，北京地均更只有 <b>1/40</b>。<br>规模的重排已经发生，效率的重排还没有。</p>
</header>

<div class="kpis">
  <div class="kpi"><div class="lab">京沪深合计 ÷ 纽约</div><div class="val">1.49<small>×</small></div>
    <div class="sub">20,517 亿美元 vs 13,778 亿美元（2025 / 2024）</div></div>
  <div class="kpi"><div class="lab">深圳 GDP · 2000→2025</div><div class="val">×19.9</div>
    <div class="sub">年均复合 {cagr:.1f}%，八城最快</div></div>
  <div class="kpi"><div class="lab">纽约人均 GDP（2024）</div><div class="val">16.3<small> 万美元</small></div>
    <div class="sub">深圳的 5.7 倍；是香港的 3.0 倍</div></div>
  <div class="kpi"><div class="lab">香港经济首位度</div><div class="val">2.2<small>%</small></div>
    <div class="sub">2000 年为 14.0%，25 年下降 84%</div></div>
</div>

<section>
  <div class="sec-head"><span class="sec-no">01</span><h2>总量：京沪深 25 年增长 13–20 倍，纽约、伦敦、香港约 2.5 倍</h2>
    <span class="aside">区域 GDP · 亿美元</span></div>
  {line_chart()}
  <p class="note">按实际数据点连线，缺失年份不插补。纽约、伦敦最新为 2024 年，东京为 2023 年（日本财年），其余为 2025 年初步核算数；东京美元值 2020→2023 下降 12.8%，主要来自日元贬值。</p>
</section>

<section>
  <div class="split">
    <div class="panel">
      <div class="sec-head"><span class="sec-no">02</span><h2>增长：19 年里深圳 ×8.2，伦敦 ×1.6</h2>
        <span class="aside">○2005　●2024</span></div>
      {dumbbell()}
      <p class="note"><b>绝对增量仍是纽约最大</b>（+8,325 亿美元）。京沪深的高倍数来自低起点：2005 年三市合计仅为纽约的 49%。东京缺 2005 年数据，未列入。</p>
    </div>
    <div class="panel">
      <div class="sec-head"><span class="sec-no">03</span><h2>效率：人均差 5.5 倍，地均差 41 倍</h2>
        <span class="aside">2023 · 八城可比</span></div>
      {scatter()}
      <p class="note">气泡面积代表区域 GDP。京沪深挤在左下角：人均 3 万美元上下，地均全部低于香港；<b>纽约是唯一「人均 >15 万且地均 >15 亿美元/km²」的城市</b>。</p>
    </div>
  </div>
</section>

<section>
  <div class="sec-head"><span class="sec-no">04</span><h2>首位度：只有香港在坠落，伦敦、东京稳在 20% 以上</h2>
    <span class="aside">占本国 GDP · 0–25%</span></div>
  <div class="split">
    <div class="panel">
      {primacy_cards()}
      <p class="note">新加坡为城市国家，首位度恒为 100%。北京 3.7%、深圳 2.8%；京沪深合计仅占中国 GDP 的 10.5%。</p>
    </div>
    <div class="panel">
      <div class="findings">
        <div class="find"><span class="fn">01</span><div><h4>总量超车靠速度，不靠体量</h4>
          <p>2025 年上海 7,887 亿美元，已达伦敦（2024）的 <b>94%</b>；深圳 <b>5,387</b> 亿美元，比香港高 26%。而 2000 年，香港还是上海的 2.9 倍、深圳的 6.3 倍。</p></div></div>
        <div class="find"><span class="fn">02</span><div><h4>人均在收敛，地均没有</h4>
          <p>深圳人均从 2000 年仅香港的 <b>16%</b> 追到 2025 年的 <b>52%</b>；但纽约地均产出仍是北京的 <b>41 倍</b>（2023）——北京的「低密度」是面积口径的结果，不等于土地效率高。</p></div></div>
        <div class="find"><span class="fn">03</span><div><h4>首位度是一道分母题</h4>
          <p>香港占比从 14.0% 跌到 2.2%，但同期香港 GDP 仍增长 <b>2.5 倍</b>；变化来自中国 GDP 增长约 16 倍。上海占全国的比重也从 4.8% 降到 4.0%：城市跑得快，国家跑得更快。</p></div></div>
      </div>
    </div>
  </div>
</section>

<footer>
  <div class="src"><b>口径</b> 现价美元，按世界银行年度平均官方汇率折算；城市边界：纽约=五县合计，伦敦=ITL1，东京=都全域，新加坡=全国，京沪深=全市，香港=全境。东京为日本财年（按起始年对齐）。
    <br><b>缺失</b> 纽约 2000、2025 年，东京 2000/2005/2010/2024/2025 年无数据，图中不插补。<b>来源</b> 世界银行 WDI · 美国 BEA · 英国 ONS · 东京都《都民経済計算》· 新加坡 SingStat · 香港政府统计处 · 北京/上海/深圳统计局。</div>
  <div class="stamp">制图 2026-10<br>数据版本 2026-10-20</div>
</footer>

</div></body></html>"""
    return body


def main() -> None:
    html_text = build()
    (WORK / "infographic.html").write_text(html_text, encoding="utf-8")
    print("wrote", WORK / "infographic.html", len(html_text), "bytes")


if __name__ == "__main__":
    main()
