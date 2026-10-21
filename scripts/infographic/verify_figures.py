#!/usr/bin/env python3
"""Verify every figure printed on the infographic against the source workbook."""
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
wb = openpyxl.load_workbook(ROOT / "output" / "城市GDP分析.xlsx", data_only=True)
ws = wb["城市GDP"]
CITIES = ["纽约", "伦敦", "东京", "新加坡", "北京", "上海", "深圳", "香港"]
D: dict[str, dict[str, dict[int, float]]] = {}
for row in ws.iter_rows(min_row=4, max_row=39, values_only=True):
    if not row[0] or row[1] is None:
        continue
    metric, year = str(row[0]).strip(), int(row[1])
    for city, v in zip(CITIES, row[2:10]):
        if v is not None:
            D.setdefault(metric, {}).setdefault(city, {})[year] = float(v)

G = D["区域GDP（亿美元）"]
P = D["经济首位度（%）"]
PC = D["人均GDP（美元/人）"]
DN = D["地均GDP（亿美元/km²）"]

checks: list[tuple[str, float, float, float]] = []


def chk(label: str, actual: float, printed: float, tol: float = 0.006) -> None:
    checks.append((label, actual, printed, tol))


total = sum(G[c][2025] for c in ["北京", "上海", "深圳"])
chk("京沪深 2025 合计（亿美元）", total, 20517, 0.0005)
chk("纽约 2024（亿美元）", G["纽约"][2024], 13778, 0.0005)
chk("1.49 倍", total / G["纽约"][2024], 1.49)
chk("2005 比值 0.49", sum(G[c][2005] for c in ["北京", "上海", "深圳"]) / G["纽约"][2005], 0.49)
chk("深圳 2000→2025 倍数", G["深圳"][2025] / G["深圳"][2000], 19.9, 0.001)
chk("深圳 CAGR %", ((G["深圳"][2025] / G["深圳"][2000]) ** (1 / 25) - 1) * 100, 12.7, 0.001)
chk("纽约人均 2024（万）", PC["纽约"][2024] / 1e4, 16.3, 0.01)
chk("纽约/深圳 人均 2024", PC["纽约"][2024] / PC["深圳"][2024], 5.7, 0.05)
chk("纽约/香港 人均 2024", PC["纽约"][2024] / PC["香港"][2024], 3.0, 0.01)
chk("香港首位度 2025", P["香港"][2025], 2.2, 0.02)
chk("香港首位度 2000", P["香港"][2000], 14.0, 0.02)
chk("香港首位度降幅 %", (P["香港"][2025] / P["香港"][2000] - 1) * -100, 84, 0.01)
chk("深圳 2005→2024 倍数", G["深圳"][2024] / G["深圳"][2005], 8.20, 0.001)
chk("伦敦 2005→2024 倍数", G["伦敦"][2024] / G["伦敦"][2005], 1.62, 0.001)
chk("纽约绝对增量（亿美元）", G["纽约"][2024] - G["纽约"][2005], 8325, 0.001)
chk("2005 京沪深/纽约 %", sum(G[c][2005] for c in ["北京", "上海", "深圳"]) / G["纽约"][2005] * 100, 49, 0.02)
chk("纽约/深圳 人均 2023", PC["纽约"][2023] / PC["深圳"][2023], 5.5, 0.05)
chk("纽约/北京 地均 2023", DN["纽约"][2023] / DN["北京"][2023], 41, 0.02)
chk("上海/伦敦 2025-2024 %", G["上海"][2025] / G["伦敦"][2024] * 100, 94, 0.001)
chk("深圳 2025（亿美元）", G["深圳"][2025], 5387, 0.0005)
chk("深圳/香港 2025 %", (G["深圳"][2025] / G["香港"][2025] - 1) * 100, 26, 0.01)
chk("香港/上海 2000", G["香港"][2000] / G["上海"][2000], 2.9, 0.01)
chk("香港/深圳 2000", G["香港"][2000] / G["深圳"][2000], 6.3, 0.01)
chk("深圳/香港 人均 2000 %", PC["深圳"][2000] / PC["香港"][2000] * 100, 16, 0.03)
chk("深圳/香港 人均 2025 %", PC["深圳"][2025] / PC["香港"][2025] * 100, 52, 0.01)
chk("香港 GDP 2000→2025 倍数", G["香港"][2025] / G["香港"][2000], 2.5, 0.02)
chk("中国 GDP 增长倍数", (G["香港"][2025] / G["香港"][2000]) / (P["香港"][2025] / P["香港"][2000]), 16, 0.02)
chk("上海首位度 2000", P["上海"][2000], 4.8, 0.02)
chk("上海首位度 2025", P["上海"][2025], 4.0, 0.02)
chk("伦敦首位度 2024", P["伦敦"][2024], 22.7, 0.02)
chk("伦敦首位度 2000", P["伦敦"][2000], 20.2, 0.02)
chk("东京首位度 2023", P["东京"][2023], 20.3, 0.02)
chk("伦敦 pp 变化", P["伦敦"][2024] - P["伦敦"][2000], 2.5, 0.05)
chk("东京 pp 变化", P["东京"][2023] - P["东京"][2015], 0.3, 0.1)
chk("上海 pp 变化", P["上海"][2025] - P["上海"][2000], -0.8, 0.05)
chk("京沪深首位度合计", sum(P[c][2025] for c in ["北京", "上海", "深圳"]), 10.5, 0.01)
chk("北京首位度 2025", P["北京"][2025], 3.7, 0.02)
chk("深圳首位度 2025", P["深圳"][2025], 2.8, 0.02)

bad = 0
for label, actual, printed, tol in checks:
    ok = abs(actual - printed) <= tol * max(1.0, abs(printed))
    bad += not ok
    print(f"{'OK ' if ok else 'BAD'}  {label:28s} computed={actual:12.4f}  printed={printed:10.2f}")
print(f"\n{len(checks) - bad}/{len(checks)} checks passed")
raise SystemExit(1 if bad else 0)
