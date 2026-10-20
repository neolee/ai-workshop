"""香港政府统计处（C&SD）Web Table API。

三个表，均无需 key，使用 `full_series=1` 取全序列：
  310-31002  本地生产总值（按开支组成部分，当时市价，百万港元）
  110-01001  人口（按性别及年龄，含 6 月与 12 月，千人）
  110-02001  土地面积（按区议会分区，平方公里）

注意：
  * 310-31002 与 110-02001 为年度表；110-01001 为半年表，取每年 6 月值作年中人口。
  * 110-02001 自 2002 年起，2000 年用 2002 年值回填并标注（面积年变化 <1%）。
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Fact, Fetched, SourceMeta, commit_raw

NAME = "hkcsd"
BASE_URL = "https://www.censtatd.gov.hk/api/get.php?id={table}&lang=en&full_series=1"

TABLES: dict[str, dict[str, str]] = {
    "310-31002": {
        "kind": "gdp",
        "title": "Gross Domestic Product (GDP) by major expenditure component at current market prices",
        "unit": "HK$ million",
        "organization": "Census and Statistics Department, Hong Kong SAR",
    },
    "110-01001": {
        "kind": "population",
        "title": "Population by sex and age group",
        "unit": "Number ('000)",
        "organization": "Census and Statistics Department, Hong Kong SAR",
    },
    "110-02001": {
        "kind": "area",
        "title": "Land area, land population and population density by District Council district",
        "unit": "sq. km",
        "organization": "Census and Statistics Department, Hong Kong SAR",
    },
}

# 面积表覆盖不到的最早年份，用最早可得年份回填
AREA_BACKFILL = {2000: 2002}


def _is_hkd_million(row: dict) -> bool:
    return str(row.get("svDesc", "")).strip() == "HK$ million"


def _is_number(row: dict) -> bool:
    return str(row.get("svDesc", "")).strip().startswith("Number")


def _is_land_area(row: dict) -> bool:
    return str(row.get("sv", "")) == "LA" and "sq. km" in str(row.get("svDesc", ""))


def _latest_year(rows: list[dict], kind: str) -> int:
    """数据版本取该表实际可用序列的最新年度，避免被季度/半年行误导。"""
    years: list[int] = []
    for row in rows:
        period = str(row.get("period", ""))
        if kind == "gdp":
            ok = (
                row.get("GDP_COMPONENTDesc") == "Total"
                and row.get("freq") == "Y"
                and _is_hkd_million(row)
            )
        elif kind == "population":
            ok = len(period) == 6 and period[4:] == "06" and _is_number(row)
        else:
            ok = row.get("DCDesc") == "Total" and _is_land_area(row)
        if ok and period[:4].isdigit():
            years.append(int(period[:4]))
    if years:
        return max(years)
    return max(int(str(r.get("period", "0"))[:4]) for r in rows)


def _num(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class HkCsdAdapter:
    name = NAME
    dataset_keys = tuple(f"HKCSD-{t}" for t in TABLES)

    def fetch(self, client, raw_root: Path) -> list[Fetched]:
        results: list[Fetched] = []
        for table_id, spec in TABLES.items():
            response = client.get(BASE_URL.format(table=table_id))
            payload = json.loads(response.content)
            status = payload.get("header", {}).get("status", {})
            if status.get("name") != "Success":
                raise ValueError(f"HK C&SD 表 {table_id} 返回失败：{status}")
            rows = payload.get("dataSet") or []
            if not rows:
                raise ValueError(f"HK C&SD 表 {table_id} 无数据")

            latest = _latest_year(rows, spec["kind"])
            meta = SourceMeta(
                id=f"HKCSD-{table_id}-{latest}",
                dataset_key=f"HKCSD-{table_id}",
                city_code="HKG",
                indicator=spec["kind"],
                organization=spec["organization"],
                dataset_title=spec["title"],
                table_id=table_id,
                url=BASE_URL.format(table=table_id),
                vintage=latest,
                published_at=None,
                notes="数据版本以最新期间年度标识；无独立发布日期字段",
            )
            results.append(commit_raw(raw_root, meta, [(f"{table_id}.json", response)]))
        return results

    def parse(self, fetched: Fetched) -> list[Fact]:
        rows = json.loads(fetched.files[0].read_text(encoding="utf-8"))["dataSet"]
        kind = fetched.meta.indicator
        if kind == "gdp":
            return self._parse_gdp(rows)
        if kind == "population":
            return self._parse_population(rows)
        if kind == "area":
            return self._parse_area(rows)
        raise ValueError(f"未知指标类型：{kind}")

    # -- 解析器 ---------------------------------------------------------
    @staticmethod
    def _parse_gdp(rows: list[dict]) -> list[Fact]:
        facts: list[Fact] = []
        for row in rows:
            if row.get("GDP_COMPONENTDesc") != "Total":
                continue
            if row.get("freq") != "Y" or not _is_hkd_million(row):
                continue
            year = int(str(row["period"])[:4])
            value = _num(row.get("figure"))
            if value is None or not (1990 <= year <= 2030):
                continue
            facts.append(
                Fact(
                    entity_type="city",
                    entity_code="HKG",
                    indicator="gdp_lcu",
                    year=year,
                    value=value * 1e6,  # 百万港元 -> 港元
                    unit="HKD",
                    note="以当时市价计算",
                )
            )
        return facts

    @staticmethod
    def _parse_population(rows: list[dict]) -> list[Fact]:
        facts: list[Fact] = []
        for row in rows:
            if row.get("SEXDesc") != "Total" or row.get("AGEDesc") != "Total":
                continue
            if not _is_number(row):
                continue
            period = str(row.get("period", ""))
            if len(period) != 6 or period[4:] != "06":
                continue  # 只取 6 月（年中）
            year = int(period[:4])
            value = _num(row.get("figure"))
            if value is None or not (1990 <= year <= 2030):
                continue
            facts.append(
                Fact(
                    entity_type="city",
                    entity_code="HKG",
                    indicator="population",
                    year=year,
                    value=value * 1000,  # 千人 -> 人
                    unit="person",
                    note="年中人口（6 月）",
                )
            )
        return facts

    @staticmethod
    def _parse_area(rows: list[dict]) -> list[Fact]:
        by_year: dict[int, float] = {}
        for row in rows:
            if row.get("DCDesc") != "Total" or not _is_land_area(row):
                continue
            year = int(str(row["period"])[:4])
            value = _num(row.get("figure"))
            if value is None or not (1990 <= year <= 2030):
                continue
            by_year[year] = value

        facts = [
            Fact("city", "HKG", "area_km2", year, value, "km2",
                 note="按区议会分区的土地面积（不含水塘等水域）")
            for year, value in sorted(by_year.items())
        ]

        # 2000 年不在原表范围内，用最早可得年份回填
        earliest = min(by_year) if by_year else None
        for target, source_year in AREA_BACKFILL.items():
            if target in by_year or source_year not in by_year:
                continue
            facts.append(
                Fact(
                    "city", "HKG", "area_km2", target, by_year[source_year], "km2",
                    status="provisional",
                    note=f"原表自 {earliest} 年起，{target} 年取 {source_year} 年值回填",
                )
            )
        return facts
