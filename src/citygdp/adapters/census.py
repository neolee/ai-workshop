"""美国人口普查局：纽约市五县人口估计（2000–2024）。

三个 vintage 覆盖不同区间，按年份分段使用（同年重叠时用较新 vintage）：
  2000–2009  co-est00int-tot.csv    （2000–2010 intercensal）
  2010–2019  co-est2020-alldata.csv （2010–2020 vintage）
  2020–2024  co-est2024-alldata.csv （2020–2024 vintage）

注意：三段的基数不同（2010/2020 普查重订基期），同一序列内不要跨段拼接。
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .base import Fact, Fetched, SourceMeta, commit_raw

NAME = "census"
BASE = "https://www2.census.gov/programs-surveys/popest/datasets"

SOURCES: dict[int, tuple[str, str, int, int]] = {
    2000: (f"{BASE}/2000-2010/intercensal/county/co-est00int-tot.csv", "2000", 2000, 2009),
    2010: (f"{BASE}/2010-2020/counties/totals/co-est2020-alldata.csv", "2010", 2010, 2019),
    2020: (f"{BASE}/2020-2024/counties/totals/co-est2024-alldata.csv", "2020", 2020, 2024),
}

STATE_NY = 36
COUNTY_FIPS = {5, 47, 61, 81, 85}  # Bronx, Kings, New York, Queens, Richmond


class CensusAdapter:
    name = NAME
    dataset_keys = ("CENSUS-PEP",)

    def fetch(self, client, raw_root: Path) -> list[Fetched]:
        items = []
        for _key, (url, _name, _start, _end) in sorted(SOURCES.items()):
            items.append((f"{_key}.csv", client.get(url)))

        meta = SourceMeta(
            id="CENSUS-PEP-2024",
            dataset_key="CENSUS-PEP",
            city_code="NYC",
            indicator="population",
            organization="U.S. Census Bureau",
            dataset_title="County Population Totals and Components of Change (Vintage 2024)",
            table_id="co-estYYYY-alldata",
            url=SOURCES[2020][0],
            vintage="2024",
            published_at=None,
            notes="三段 vintage 分段使用；2010/2020 存在基期断点",
        )
        return [commit_raw(raw_root, meta, items)]

    def parse(self, fetched: Fetched) -> list[Fact]:
        totals: dict[int, int] = {}
        for path in fetched.files:
            start = int(path.stem)
            _url, _name, year_from, year_to = SOURCES[start]
            text = path.read_text(encoding="latin-1")
            for row in csv.DictReader(io.StringIO(text)):
                if not _is_nyc_county(row):
                    continue
                for year in range(year_from, year_to + 1):
                    raw = row.get(f"POPESTIMATE{year}")
                    if raw in (None, ""):
                        continue
                    totals[year] = totals.get(year, 0) + int(raw)

        return [
            Fact(
                entity_type="city",
                entity_code="NYC",
                indicator="population",
                year=year,
                value=float(value),
                unit="person",
                note="5 县合计，7 月 1 日估计",
            )
            for year, value in sorted(totals.items())
        ]


def _is_nyc_county(row: dict) -> bool:
    try:
        return int(row["STATE"]) == STATE_NY and int(row["COUNTY"]) in COUNTY_FIPS
    except (KeyError, TypeError, ValueError):
        return False
