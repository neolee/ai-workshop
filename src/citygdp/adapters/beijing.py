"""北京市统计局：统计年鉴在线版（Excel 表）+ 年度统计公报。

年鉴入口页返回一段 JS 跳转，指向 `nj.tjj.beijing.gov.cn/nj/main/{YYYY}-tjnj/zk/`。
表页在 `e/html/` 下同时提供 JPG（展示）与 XLS（数据），本适配器取 XLS：
  C0201.xls  表2-1 地区生产总值(1978-2024年)  亿元
  C0302.xls  表3-2 常住人口(1978-2024年)      万人

最新一年（2025）从统计公报取。
"""

from __future__ import annotations

import re
from pathlib import Path

import xlrd

from ._html import decode_page
from .base import Fact, Fetched, SourceMeta, commit_raw

NAME = "beijing"
ENTRY_URL = "https://tjj.beijing.gov.cn/tjsj_31433/tjnj_31441/bjtjnj_31442/"
BULLETIN_URL = "https://tjj.beijing.gov.cn/tjsj_31433/tjgb_31445/ndgb_31446/202603/t20260326_4566469.html"

GDP_TABLE = "C0201.xls"      # 表2-1 地区生产总值
POP_TABLE = "C0302.xls"      # 表3-2 常住人口


class BeijingAdapter:
    name = NAME
    dataset_keys = ("BJS-TJNJ", "BJS-GB")

    def fetch(self, client, raw_root: Path) -> list[Fetched]:
        entry = client.get(ENTRY_URL)
        html = decode_page(entry.content)
        match = re.search(r"location\.replace\('([^']*?/(\d{4})-tjnj/zk/)indexch\.htm'\)", html)
        if match is None:
            raise ValueError("北京年鉴入口未找到年份跳转")
        base, year = match.group(1), match.group(2)

        items = [
            ("gdp.xls", client.get(f"{base}e/html/{GDP_TABLE}")),
            ("population.xls", client.get(f"{base}e/html/{POP_TABLE}")),
        ]
        meta = SourceMeta(
            id=f"BJS-TJNJ-{year}",
            dataset_key="BJS-TJNJ",
            city_code="BJS",
            indicator="gdp+population",
            organization="北京市统计局",
            dataset_title=f"北京统计年鉴{year} — 表2-1 地区生产总值、表3-2 常住人口",
            table_id=f"{GDP_TABLE} / {POP_TABLE}",
            url=f"{base}e/html/{GDP_TABLE}",
            vintage=str(year),
            published_at=None,
            notes="生产总值 1978–上年；人口为年末常住人口",
        )
        results = [commit_raw(raw_root, meta, items)]

        bulletin = client.get(BULLETIN_URL)
        results.append(
            commit_raw(
                raw_root,
                SourceMeta(
                    id="BJS-GB-2025",
                    dataset_key="BJS-GB",
                    city_code="BJS",
                    indicator="gdp+population",
                    organization="北京市统计局",
                    dataset_title="北京市2025年国民经济和社会发展统计公报",
                    table_id=None,
                    url=BULLETIN_URL,
                    vintage="2025",
                    published_at="2026-03-26",
                    notes="初步核算数；年末常住人口",
                ),
                [("bulletin.html", bulletin)],
            )
        )
        return results

    def parse(self, fetched: Fetched) -> list[Fact]:
        if fetched.meta.dataset_key == "BJS-GB":
            return _parse_bulletin(fetched.directory / "bulletin.html")

        gdp = _xls_series(fetched.directory / "gdp.xls")
        pop = _xls_series(fetched.directory / "population.xls")

        facts = [
            Fact("city", "BJS", "gdp_lcu", y, v * 1e8, "CNY", note="现价，亿元换算")
            for y, v in sorted(gdp.items())
        ]
        facts += [
            Fact("city", "BJS", "population", y, v * 1e4, "person", note="年末常住人口，万人换算")
            for y, v in sorted(pop.items())
        ]
        return facts


def _xls_series(path: Path) -> dict[int, float]:
    """读取年鉴 Excel：首列为年份、第二列为数值。"""
    book = xlrd.open_workbook(str(path))
    sheet = book.sheet_by_index(0)
    series: dict[int, float] = {}
    for r in range(sheet.nrows):
        year_cell = sheet.cell_value(r, 0)
        try:
            year = int(float(str(year_cell).strip()))
        except (TypeError, ValueError):
            continue
        if not (1900 <= year <= 2030) or sheet.ncols < 2:
            continue
        raw = str(sheet.cell_value(r, 1)).strip().replace(",", "")
        if not raw:
            continue
        try:
            series[year] = float(raw)
        except ValueError:
            continue
    return series


def _parse_bulletin(path: Path) -> list[Fact]:
    html = decode_page(path.read_bytes())
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    gdp = re.search(r"全年实现地区生产总值\s*([\d,]+\.?\d*)\s*亿元", text)
    pop = re.search(r"全市常住人口(?:\[\d+\])?\s*([\d,]+\.?\d*)\s*万人", text)
    if not gdp or not pop:
        raise ValueError("公报中未找到生产总值或常住人口")

    return [
        Fact("city", "BJS", "gdp_lcu", 2025, float(gdp.group(1).replace(",", "")) * 1e8,
             "CNY", status="preliminary", note="初步核算"),
        Fact("city", "BJS", "population", 2025, float(pop.group(1).replace(",", "")) * 1e4,
             "person", status="preliminary", note="年末常住人口"),
    ]
