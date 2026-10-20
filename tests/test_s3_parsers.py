"""S3 适配器解析测试：BEA（纽约）、Census（人口）、ONS（伦敦）。

fixtures 来自 2026-10-20 实际抓取的裁剪样本，结构未改。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from citygdp.adapters.base import Fetched, SourceMeta
from citygdp.adapters.bea import BeaAdapter
from citygdp.adapters.census import CensusAdapter
from citygdp.adapters.ons import OnsAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def make(paths: list[Path], indicator: str, key: str) -> Fetched:
    meta = SourceMeta(
        id=f"{key}-1",
        dataset_key=key,
        city_code=None,
        indicator=indicator,
        organization="test",
        dataset_title="test",
        table_id=None,
        url="https://example.test",
        vintage="v1",
    )
    return Fetched(meta=meta, directory=FIXTURES, files=paths)


def by_year(facts) -> dict[int, float]:
    return {f.year: f.value for f in facts}


# ---------------------------------------------------------------- BEA

def test_bea_sums_five_counties_in_current_dollars():
    facts = BeaAdapter().parse(make([FIXTURES / "bea" / "CAGDP1.zip"], "gdp", "BEA"))
    values = by_year(facts)
    assert values[2024] == pytest.approx(1_377_841_498_000)
    assert values[2001] == pytest.approx(482_656_392_000)
    assert all(f.entity_code == "NYC" and f.unit == "USD" for f in facts)


# ---------------------------------------------------------------- Census

def test_census_covers_2000_to_2024_across_three_vintages():
    facts = CensusAdapter().parse(
        make(
            [FIXTURES / "census" / f"{y}.csv" for y in (2000, 2010, 2020)],
            "population",
            "CENSUS",
        )
    )
    values = by_year(facts)
    assert len(facts) == 25
    assert values[2000] == pytest.approx(8_017_608)
    assert values[2010] == pytest.approx(8_190_105)   # 2010–2020 vintage
    assert values[2020] == pytest.approx(8_740_306)   # 2020–2024 vintage 的 blended base
    assert values[2024] == pytest.approx(8_478_072)
    assert all(f.entity_code == "NYC" and f.unit == "person" for f in facts)


# ---------------------------------------------------------------- ONS

def test_ons_parses_gdp_and_population_from_same_workbook():
    facts = OnsAdapter().parse(make([FIXTURES / "ons" / "ons_rgdp.xlsx"], "gdp+population", "ONS"))
    gdp = by_year([f for f in facts if f.indicator == "gdp_lcu"])
    pop = by_year([f for f in facts if f.indicator == "population"])

    assert gdp[2000] == pytest.approx(223_282_000_000)
    assert gdp[2024] == pytest.approx(656_291_000_000)
    assert pop[2000] == pytest.approx(7_236_712)
    assert pop[2024] == pytest.approx(9_089_736)
    assert all(f.entity_code == "LDN" for f in facts)


def test_ons_picks_london_not_uk():
    facts = OnsAdapter().parse(make([FIXTURES / "ons" / "ons_rgdp.xlsx"], "gdp+population", "ONS"))
    gdp = by_year([f for f in facts if f.indicator == "gdp_lcu"])
    assert gdp[2024] != pytest.approx(2_900_000_000_000)  # UK 行不应被取到
