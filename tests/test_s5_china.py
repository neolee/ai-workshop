"""S5：上海、北京适配器解析测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from citygdp.adapters.base import Fetched, SourceMeta
from citygdp.adapters.beijing import BeijingAdapter
from citygdp.adapters.shanghai import ShanghaiAdapter

FIX = Path(__file__).parent / "fixtures"


def make(directory: Path, key: str, city: str) -> Fetched:
    meta = SourceMeta(
        id=f"{key}-1", dataset_key=key, city_code=city, indicator="gdp+population",
        organization="test", dataset_title="test", table_id=None,
        url="https://example.test", vintage="v1",
    )
    return Fetched(meta=meta, directory=directory, files=[])


def series(facts, indicator):
    return {f.year: f.value for f in facts if f.indicator == indicator}


# ---------------- 上海

def test_shanghai_yearbook():
    facts = ShanghaiAdapter().parse(make(FIX / "shanghai", "SHSI-TJNJ", "SHA"))
    gdp, pop = series(facts, "gdp_lcu"), series(facts, "population")
    assert gdp[2024] == pytest.approx(5_392_671_000_000)
    assert gdp[2000] == pytest.approx(487_997_000_000)
    assert pop[2024] == pytest.approx(24_802_600)
    assert pop[2000] == pytest.approx(16_086_000)


def test_shanghai_bulletin():
    facts = ShanghaiAdapter().parse(make(FIX / "shanghai", "SHSI-GB", "SHA"))
    gdp, pop = series(facts, "gdp_lcu"), series(facts, "population")
    assert gdp[2025] == pytest.approx(5_670_871_000_000)
    assert pop[2025] == pytest.approx(24_854_100)
    assert all(f.status == "preliminary" for f in facts)


# ---------------- 北京

def test_beijing_yearbook():
    facts = BeijingAdapter().parse(make(FIX / "beijing", "BJS-TJNJ", "BJS"))
    gdp, pop = series(facts, "gdp_lcu"), series(facts, "population")
    assert gdp[2024] == pytest.approx(4_984_310_000_000)
    assert gdp[2000] == pytest.approx(332_800_000_000)
    assert pop[2024] == pytest.approx(21_832_000)
    assert pop[2000] == pytest.approx(13_636_000)


def test_beijing_bulletin():
    facts = BeijingAdapter().parse(make(FIX / "beijing", "BJS-GB", "BJS"))
    gdp, pop = series(facts, "gdp_lcu"), series(facts, "population")
    assert gdp[2025] == pytest.approx(5_207_340_000_000)
    assert pop[2025] == pytest.approx(21_800_000)
