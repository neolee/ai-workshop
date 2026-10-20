"""S4：东京都适配器解析测试（年度制、日文表结构）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from citygdp.adapters.base import Fetched, SourceMeta
from citygdp.adapters.tokyo import TokyoAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "tokyo"


def parse():
    meta = SourceMeta(
        id="TOKYO-KEIZAI-2023",
        dataset_key="TOKYO-KEIZAI",
        city_code="TYO",
        indicator="gdp+population",
        organization="test",
        dataset_title="test",
        table_id=None,
        url="https://example.test",
        vintage="2023",
    )
    return TokyoAdapter().parse(Fetched(meta=meta, directory=FIXTURES, files=[]))


def test_gdp_in_yen_from_million_yen():
    gdp = {f.year: f.value for f in parse() if f.indicator == "gdp_lcu"}
    assert gdp[2023] == pytest.approx(125_018_533_000_000)
    assert gdp[2015] == pytest.approx(110_011_424_000_000)


def test_population_in_persons_from_thousands():
    pop = {f.year: f.value for f in parse() if f.indicator == "population"}
    assert pop[2023] == pytest.approx(14_096_000)
    assert pop[2015] == pytest.approx(13_511_000)


def test_only_recent_window_present():
    years = {f.year for f in parse() if f.indicator == "gdp_lcu"}
    assert min(years) == 2011
    assert max(years) == 2023
    assert 2000 not in years and 2010 not in years


def test_fiscal_year_label_is_start_year():
    # 令和5年度 -> 2023；若按结束年映射会得到 2024
    gdp = {f.year: f.value for f in parse() if f.indicator == "gdp_lcu"}
    assert 2023 in gdp and 2024 not in gdp
