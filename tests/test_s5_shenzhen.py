"""S5：深圳 PDF 文本层解析测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from citygdp.adapters.base import Fetched, SourceMeta
from citygdp.adapters.shenzhen import ShenzhenAdapter

FIX = Path(__file__).parent / "fixtures" / "shenzhen"


def make(key: str) -> Fetched:
    meta = SourceMeta(
        id=f"{key}-1", dataset_key=key, city_code="SZX", indicator="gdp+population",
        organization="test", dataset_title="test", table_id=None,
        url="https://example.test", vintage="2025",
    )
    return Fetched(meta=meta, directory=FIX, files=[])


def series(facts, indicator):
    return {f.year: f.value for f in facts if f.indicator == indicator}


def test_shenzhen_gdp_from_pdf():
    facts = ShenzhenAdapter().parse(make("SZX-TJNJ"))
    gdp = series(facts, "gdp_lcu")
    assert gdp[2024] == pytest.approx(3_680_187_000_000)
    assert gdp[2000] == pytest.approx(224_011_600_000)
    assert gdp[1979] == pytest.approx(196_380_000)


def test_shenzhen_population_from_pdf():
    facts = ShenzhenAdapter().parse(make("SZX-TJNJ"))
    pop = series(facts, "population")
    assert pop[2024] == pytest.approx(17_989_500)
    assert pop[2000] == pytest.approx(7_012_400)


def test_shenzhen_area_break():
    facts = ShenzhenAdapter().parse(make("SZX-TJNJ"))
    area = series(facts, "area_km2")
    assert area[2023] == pytest.approx(1997.47)
    assert area[2024] == pytest.approx(2465.77)
    assert area[2025] == pytest.approx(2465.77)


def test_shenzhen_bulletin():
    facts = ShenzhenAdapter().parse(make("SZX-GB"))
    gdp, pop = series(facts, "gdp_lcu"), series(facts, "population")
    assert gdp[2025] == pytest.approx(3_873_180_000_000)
    assert pop[2025] == pytest.approx(18_248_500)
