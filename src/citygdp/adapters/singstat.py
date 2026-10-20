"""新加坡统计局（SingStat）TableBuilder API。

三张表，均无需 key：
  M014871  GDP at Current Market Prices, Quarterly（百万新元）
  M810001  Indicators on Population, Annual（总人口）
  M890151  Land Area (As at December), Annual（平方公里）

注意：M014871 是季度表，年度值由四个季度加总得到（现价加总成立）。
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Fact, Fetched, SourceMeta, commit_raw

NAME = "singstat"
BASE_URL = "https://tablebuilder.singstat.gov.sg/api/table/tabledata/{table}"

TABLES: dict[str, dict[str, str]] = {
    "M014871": {
        "kind": "gdp",
        "title": "Expenditure on Gross Domestic Product at Current Prices, Quarterly",
        "unit": "Million Dollars",
    },
    "M810001": {
        "kind": "population",
        "title": "Indicators on Population, Annual",
        "unit": "Number",
    },
    "M890151": {
        "kind": "area",
        "title": "Land Area (As at December), Annual",
        "unit": "Square Kilometre",
    },
}

# 从表中取哪个 row（按 rowText 精确匹配）
GDP_ROW = "GDP At Current Market Prices"
POP_ROW = "Total Population"
AREA_ROW = "Total Land Area"


def _ddmmyyyy_to_iso(text: str) -> str:
    day, month, year = text.strip().split("/")
    return f"{year}-{month}-{day}"


def _num(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = value.strip().replace(",", "")
    if text in ("", "-", "na", "N.A."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _find_row(data: dict, row_text: str) -> dict | None:
    for row in data.get("row", []):
        if str(row.get("rowText", "")).strip() == row_text:
            return row
    return None


class SingStatAdapter:
    name = NAME
    dataset_keys = tuple(f"SINGSTAT-{t}" for t in TABLES)

    def fetch(self, client, raw_root: Path) -> list[Fetched]:
        results: list[Fetched] = []
        for table_id, spec in TABLES.items():
            response = client.get(BASE_URL.format(table=table_id))
            payload = json.loads(response.content)
            data = payload.get("Data") or {}
            if not data.get("row"):
                raise ValueError(f"SingStat 表 {table_id} 返回空数据")

            version = _ddmmyyyy_to_iso(str(data.get("dataLastUpdated", "")))
            meta = SourceMeta(
                id=f"SINGSTAT-{table_id}-{version}",
                dataset_key=f"SINGSTAT-{table_id}",
                city_code="SGP",
                indicator=spec["kind"],
                organization="Singapore Department of Statistics (SingStat)",
                dataset_title=spec["title"],
                table_id=table_id,
                url=BASE_URL.format(table=table_id),
                vintage=version,
                published_at=version,
            )
            results.append(commit_raw(raw_root, meta, [(f"{table_id}.json", response)]))
        return results

    def parse(self, fetched: Fetched) -> list[Fact]:
        path = fetched.files[0]
        data = json.loads(path.read_text(encoding="utf-8"))["Data"]
        kind = fetched.meta.indicator

        if kind == "gdp":
            return self._parse_gdp(data)
        if kind == "population":
            return self._parse_annual(data, POP_ROW, "population", "person")
        if kind == "area":
            return self._parse_annual(data, AREA_ROW, "area_km2", "km2")
        raise ValueError(f"未知指标类型：{kind}")

    # -- 解析器 ---------------------------------------------------------
    @staticmethod
    def _parse_gdp(data: dict) -> list[Fact]:
        row = _find_row(data, GDP_ROW)
        if row is None:
            raise ValueError(f"未找到行：{GDP_ROW}")
        quarters: dict[int, dict[int, float]] = {}
        for column in row.get("columns", []):
            key = str(column.get("key", ""))
            parts = key.split()
            if len(parts) != 2:
                continue
            year = int(parts[0])
            quarter = int(parts[1].replace("Q", ""))
            value = _num(column.get("value"))
            if value is None:
                continue
            quarters.setdefault(year, {})[quarter] = value

        facts: list[Fact] = []
        for year, qs in sorted(quarters.items()):
            if len(qs) < 4 or not (1990 <= year <= 2030):
                continue  # 不完整的年份（如当年只到 Q2）不输出
            facts.append(
                Fact(
                    entity_type="city",
                    entity_code="SGP",
                    indicator="gdp_lcu",
                    year=year,
                    value=sum(qs.values()) * 1e6,  # 百万新元 -> 新元
                    unit="SGD",
                )
            )
        return facts

    @staticmethod
    def _parse_annual(data: dict, row_text: str, indicator: str, unit: str) -> list[Fact]:
        row = _find_row(data, row_text)
        if row is None:
            raise ValueError(f"未找到行：{row_text}")
        facts: list[Fact] = []
        for column in row.get("columns", []):
            key = str(column.get("key", "")).strip()
            if len(key) != 4 or not key.isdigit():
                continue
            year = int(key)
            if not (1990 <= year <= 2030):
                continue
            value = _num(column.get("value"))
            if value is None:
                continue
            facts.append(
                Fact(
                    entity_type="city",
                    entity_code="SGP",
                    indicator=indicator,
                    year=year,
                    value=value,
                    unit=unit,
                )
            )
        return facts
