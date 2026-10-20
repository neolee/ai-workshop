"""BEA：纽约市五县现价 GDP（批量 ZIP，无需 key）。

端点：https://apps.bea.gov/regional/zip/CAGDP1.zip
表 CAGDP1「County GDP summary」，LineCode=3 为现价 GDP（千美元）。
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

from .base import Fact, Fetched, SourceMeta, commit_raw

NAME = "bea"
URL = "https://apps.bea.gov/regional/zip/CAGDP1.zip"

# 纽约市五县 FIPS
COUNTIES: dict[str, str] = {
    "36005": "Bronx",
    "36047": "Kings",
    "36061": "New York",
    "36081": "Queens",
    "36085": "Richmond",
}

LINE_CURRENT_DOLLAR = "3"


class BeaAdapter:
    name = NAME
    dataset_keys = ("BEA-CAGDP1",)

    def fetch(self, client, raw_root: Path) -> list[Fetched]:
        response = client.get(URL)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
        ny_file = next(
            (n for n in names if n.startswith("CAGDP1_NY_") and n.endswith(".csv")), None
        )
        if ny_file is None:
            raise ValueError(f"ZIP 内未找到纽约州文件：{names[:5]}")
        match = re.search(r"_(\d{4})\.csv$", ny_file)
        if match is None:
            raise ValueError(f"无法从文件名解析年份：{ny_file}")
        year = match.group(1)

        meta = SourceMeta(
            id=f"BEA-CAGDP1-{year}",
            dataset_key="BEA-CAGDP1",
            city_code="NYC",
            indicator="gdp",
            organization="U.S. Bureau of Economic Analysis (BEA)",
            dataset_title="County gross domestic product (GDP) summary — CAGDP1",
            table_id="CAGDP1",
            url=URL,
            vintage=year,
            published_at=None,
            notes="纽约市 = Bronx+Kings+New York+Queens+Richmond 五县加总",
        )
        return [commit_raw(raw_root, meta, [("CAGDP1.zip", response)])]

    def parse(self, fetched: Fetched) -> list[Fact]:
        with zipfile.ZipFile(io.BytesIO(fetched.files[0].read_bytes())) as archive:
            name = next(
                n for n in archive.namelist()
                if n.startswith("CAGDP1_NY_") and n.endswith(".csv")
            )
            text = archive.read(name).decode("utf-8-sig")

        totals: dict[int, float] = {}
        for row in csv.DictReader(io.StringIO(text)):
            geo = (row.get("GeoFIPS") or "").strip().strip('"')
            if geo not in COUNTIES:
                continue
            if (row.get("LineCode") or "").strip() != LINE_CURRENT_DOLLAR:
                continue
            for year in range(1990, 2031):
                raw = row.get(str(year))
                if raw is None or raw.strip() in ("", "(NA)"):
                    continue
                totals[year] = totals.get(year, 0.0) + float(raw)

        return [
            Fact(
                entity_type="city",
                entity_code="NYC",
                indicator="gdp_lcu",
                year=year,
                value=value * 1e3,  # 千美元 -> 美元
                unit="USD",
                note="五县现价 GDP 合计",
            )
            for year, value in sorted(totals.items())
        ]
