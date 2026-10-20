"""ONS：伦敦 GDP 与人口。

数据页：https://www.ons.gov.uk/economy/grossdomesticproductgdp/datasets/regionalgrossdomesticproductallnutslevelregions

同一份工作簿中含：
  Table 5  GDP at current market prices, pounds million
  Table 6  Total resident population numbers, persons

因此 GDP 与人口同源同版本，口径天然一致。版本取文件名中的年份区间（如 1998to2024）。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import openpyxl

from .base import Fact, Fetched, SourceMeta, commit_raw

NAME = "ons"
PAGE_URL = (
    "https://www.ons.gov.uk/economy/grossdomesticproductgdp/datasets/"
    "regionalgrossdomesticproductallnutslevelregions"
)
SITE = "https://www.ons.gov.uk"

GDP_SHEET = "Table 5"
POP_SHEET = "Table 6"


class OnsAdapter:
    name = NAME
    dataset_keys = ("ONS-RGDP",)

    def fetch(self, client, raw_root: Path) -> list[Fetched]:
        page = client.get(PAGE_URL)
        html = page.content.decode("utf-8", errors="ignore")

        candidates: list[tuple[str, str]] = []
        for href in re.findall(r'href="([^"]+\.xlsx)"', html):
            match = re.search(r"/(\d{4}to\d{4})/", href)
            if match:
                candidates.append((match.group(1), href))
        if not candidates:
            raise ValueError("ONS 页面上未找到区域 GDP 的 xlsx 链接")

        version, href = max(candidates)
        url = href if href.startswith("http") else f"{SITE}{href}"
        response = client.get(url)

        meta = SourceMeta(
            id=f"ONS-RGDP-{version}",
            dataset_key="ONS-RGDP",
            city_code="LDN",
            indicator="gdp+population",
            organization="Office for National Statistics (ONS)",
            dataset_title=(
                "Regional gross domestic product: all ITL regions — "
                "Table 5 (GDP, current prices) & Table 6 (population)"
            ),
            table_id="Table 5 / Table 6",
            url=url,
            vintage=version,
            published_at=None,
            notes="使用 balanced 估计；London 为 ITL1 区域",
        )
        return [commit_raw(raw_root, meta, [("ons_rgdp.xlsx", response)])]

    def parse(self, fetched: Fetched) -> list[Fact]:
        workbook = openpyxl.load_workbook(
            io.BytesIO(fetched.files[0].read_bytes()), read_only=True, data_only=True
        )
        gdp = _london_series(workbook[GDP_SHEET])
        population = _london_series(workbook[POP_SHEET])

        facts: list[Fact] = []
        for year, value in sorted(gdp.items()):
            facts.append(
                Fact("city", "LDN", "gdp_lcu", year, value * 1e6, "GBP",
                     note="现价，百万英镑换算")
            )
        for year, value in sorted(population.items()):
            facts.append(
                Fact("city", "LDN", "population", year, value, "person",
                     note="年中人口，ONS Table 6")
            )
        return facts


def _london_series(worksheet) -> dict[int, float]:
    """从 ONS 表格中取 London 行的年份序列。"""
    header: dict[int, int] | None = None  # 列号 -> 年份
    rows = worksheet.iter_rows(values_only=True)

    for row in rows:
        if header is None:
            if row and str(row[0]).strip() == "ITL":
                header = {}
                for index, cell in enumerate(row):
                    text = str(cell).strip() if cell is not None else ""
                    if len(text) == 4 and text.isdigit():
                        header[index] = int(text)
                continue
        if row and len(row) >= 3 and str(row[0]).strip() == "ITL1" and str(row[2]).strip() == "London":
            assert header is not None
            result: dict[int, float] = {}
            for index, year in header.items():
                if index < len(row) and isinstance(row[index], (int, float)):
                    if 1990 <= year <= 2030:
                        result[year] = float(row[index])
            return result

    raise ValueError("未在 ONS 表格中找到 London（ITL1）行")
