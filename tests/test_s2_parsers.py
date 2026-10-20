"""S2 适配器解析测试：用真实响应的裁剪样本做回归。

fixtures 来自 2026-10-20 的实际抓取，只保留少量年份，结构未改动。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from citygdp.adapters.base import Fetched, SourceMeta
from citygdp.adapters.hkcsd import HkCsdAdapter
from citygdp.adapters.singstat import SingStatAdapter
from citygdp.adapters.worldbank import WorldBankAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def make_fetched(path: Path, indicator: str) -> Fetched:
    meta = SourceMeta(
        id="TEST-1",
        dataset_key="TEST",
        city_code=None,
        indicator=indicator,
        organization="test",
        dataset_title="test",
        table_id=None,
        url="https://example.test",
        vintage="v1",
    )
    return Fetched(meta=meta, directory=path.parent, files=[path])


def by_year(facts) -> dict[int, float]:
    return {f.year: f.value for f in facts}


# ---------------------------------------------------------------- World Bank

def test_worldbank_gdp_parse():
    facts = WorldBankAdapter().parse(make_fetched(FIXTURES / "wb" / "CHN.json", "NY.GDP.MKTP.CD"))
    values = by_year(facts)
    assert values[2024] == pytest.approx(18_729_668_435_848)
    assert values[2023] == pytest.approx(18_270_356_654_533.2)
    assert all(f.entity_type == "country" and f.entity_code == "CHN" for f in facts)
    assert all(f.unit == "USD" for f in facts)


def test_worldbank_fx_parse():
    facts = WorldBankAdapter().parse(make_fetched(FIXTURES / "wb_fx" / "CHN.json", "PA.NUS.FCRF"))
    values = by_year(facts)
    assert values[2024] == pytest.approx(7.197491, rel=1e-6)
    assert all(f.entity_type == "currency" and f.entity_code == "CNY" for f in facts)
    assert all(f.unit == "LCU per USD" for f in facts)


def test_worldbank_ignores_unknown_iso(tmp_path):
    unknown = tmp_path / "ZZZ.json"
    unknown.write_text('[{}, []]', encoding="utf-8")
    assert WorldBankAdapter().parse(make_fetched(unknown, "NY.GDP.MKTP.CD")) == []


# ---------------------------------------------------------------- SingStat

def test_singstat_gdp_sums_quarters_and_skips_partial_year():
    facts = SingStatAdapter().parse(make_fetched(FIXTURES / "singstat" / "M014871.json", "gdp"))
    values = by_year(facts)
    assert values[2024] == pytest.approx(765_497_500_000)
    assert values[2023] == pytest.approx(686_398_000_000)
    # fixture 里 2026 年只有 1Q，应被跳过
    assert 2026 not in values
    assert all(f.entity_code == "SGP" and f.unit == "SGD" for f in facts)


def test_singstat_population_and_area():
    pop = by_year(SingStatAdapter().parse(
        make_fetched(FIXTURES / "singstat" / "M810001.json", "population")))
    area = by_year(SingStatAdapter().parse(
        make_fetched(FIXTURES / "singstat" / "M890151.json", "area")))
    assert pop[2024] == pytest.approx(6_036_860)
    assert area[2024] == pytest.approx(735.7)
    assert area[2025] == pytest.approx(744.3)


# ---------------------------------------------------------------- HK C&SD

def test_hk_gdp_ignores_percent_change_rows():
    facts = HkCsdAdapter().parse(make_fetched(FIXTURES / "hkcsd" / "310-31002.json", "gdp"))
    values = by_year(facts)
    assert values[2024] == pytest.approx(3_186_526_000_000)
    assert values[2023] == pytest.approx(2_981_210_000_000)
    assert all(f.unit == "HKD" for f in facts)


def test_hk_population_ignores_share_rows():
    facts = HkCsdAdapter().parse(make_fetched(FIXTURES / "hkcsd" / "110-01001.json", "population"))
    values = by_year(facts)
    assert values[2024] == pytest.approx(7_524_100)
    assert values[2023] == pytest.approx(7_536_100)
    assert all(f.unit == "person" for f in facts)


def test_hk_area_backfills_2000():
    facts = HkCsdAdapter().parse(make_fetched(FIXTURES / "hkcsd" / "110-02001.json", "area"))
    values = by_year(facts)
    assert values[2024] == pytest.approx(1089.72)
    assert values[2000] == pytest.approx(1077.24)
    backfill = next(f for f in facts if f.year == 2000)
    assert backfill.status == "provisional"
    assert "回填" in (backfill.note or "")
