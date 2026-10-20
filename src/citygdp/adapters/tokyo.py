"""东京都：都民経済計算（都内総生産・名目）与都推计人口。

数据页：https://www.toukei.metro.tokyo.lg.jp/keizaik/nenpou/kkne-index.htm
        （都民経済計算年報，最新版）

同一版年報的 CSV：
  kk{版}qv0110.csv  統合勘定(1) 都内総生産勘定（生産側及び支出側） — 百万円
  kk{版}qv0410.csv  関連指標(1) 都民経済計算関連指標 — 其中「3．人口(1) 総人口」千人

**年度**：日本年度（4 月–翌年 3 月），按起始年对齐（令和5年度 → 2023）。
**覆盖**：最新版年報只提供最近 13 个年度（如 FY2011–FY2023）；
        更早年份需另取旧版年報，但跨版本存在约 7% 的修订断点，本适配器不做拼接。
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from .base import Fact, Fetched, SourceMeta, commit_raw

NAME = "tokyo"
INDEX_URL = "https://www.toukei.metro.tokyo.lg.jp/keizaik/nenpou/kkne-index.htm"
BASE = "https://www.toukei.metro.tokyo.lg.jp"

GDP_FILE_SUFFIX = "qv0110.csv"
POP_FILE_SUFFIX = "qv0410.csv"

GDP_ROW_PREFIX = "都内総生産（生産側）"


class TokyoAdapter:
    name = NAME
    dataset_keys = ("TOKYO-KEIZAI",)

    def fetch(self, client, raw_root: Path) -> list[Fetched]:
        page = client.get(INDEX_URL)
        html = page.content.decode("utf-8", errors="ignore")
        matches = re.findall(r"(kk\d{2})qv0110\.csv", html)
        if not matches:
            raise ValueError("年報页面上未找到 kk??qv0110.csv 链接")
        edition = max(matches)  # kk23 等
        fiscal_year = 2000 + int(edition[2:])  # kk23 -> 2023

        gdp_url = f"{BASE}/keizaik/nenpou/{edition}qv0110.csv"
        pop_url = f"{BASE}/keizaik/nenpou/{edition}qv0410.csv"
        items = [
            ("gdp.csv", client.get(gdp_url)),
            ("population.csv", client.get(pop_url)),
        ]

        meta = SourceMeta(
            id=f"TOKYO-KEIZAI-{fiscal_year}",
            dataset_key="TOKYO-KEIZAI",
            city_code="TYO",
            indicator="gdp+population",
            organization="東京都総務局統計部（Tokyo Metropolitan Government）",
            dataset_title="都民経済計算年報 — 統合勘定(1) と 関連指標(1)",
            table_id=f"{edition}qv0110 / {edition}qv0410",
            url=f"{BASE}/keizaik/nenpou/kkne-index.htm",
            vintage=str(fiscal_year),
            published_at=None,
            notes="日本年度（4月-翌年3月），按起始年对齐；最新版年報覆盖最近 13 个年度",
        )
        return [commit_raw(raw_root, meta, items)]

    def parse(self, fetched: Fetched) -> list[Fact]:
        years_gdp = _parse_table(fetched.directory / "gdp.csv", GDP_ROW_PREFIX)
        years_pop = _parse_table(fetched.directory / "population.csv", "総人口")

        facts: list[Fact] = []
        for year, value in sorted(years_gdp.items()):
            facts.append(
                Fact(
                    "city", "TYO", "gdp_lcu", year, value * 1e6, "JPY",
                    note="都内総生産（名目、生産側）、年度按起始年对齐",
                )
            )
        for year, value in sorted(years_pop.items()):
            facts.append(
                Fact(
                    "city", "TYO", "population", year, value * 1000, "person",
                    note="総人口（月初人口の単純平均），千人换算",
                )
            )
        return facts


def _parse_table(path: Path, row_keyword: str) -> dict[int, float]:
    """在年報 CSV 中按行标题关键字取年份序列。"""
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError(f"空文件：{path}")

    header = rows[0]
    year_by_col: dict[int, int] = {}
    for index, cell in enumerate(header):
        match = re.search(r"(\d{4})年度", cell)
        if match:
            year_by_col[index] = int(match.group(1))
    if not year_by_col:
        raise ValueError(f"未识别到年度列：{path}")

    for row in rows[1:]:
        label = " ".join(row[:2])
        if row_keyword not in label or "増加率" in label:
            continue
        values: dict[int, float] = {}
        for index, year in year_by_col.items():
            if index >= len(row):
                continue
            cell = row[index].strip().replace(",", "")
            if cell in ("", "-", "―", "－"):
                continue
            try:
                values[year] = float(cell)
            except ValueError:
                continue
        if values:
            return values

    raise ValueError(f"未找到行「{row_keyword}」：{path}")
