"""S6：派生指标计算逻辑测试。"""

from __future__ import annotations

from pathlib import Path

from citygdp.build import FactRef, build_city_year
from citygdp.config import load_config

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT)


def facts(**entries):
    """entries: 形如 city_gdp=(id, value) 的键值，映射到 (type, code, indicator, year)。"""
    return dict(entries)


def make(**kw):
    return {k: FactRef(*v) for k, v in kw.items()}


def test_gdp_usd_and_primacy():
    city = CFG.city("NYC")
    f = make(
        gdp=(1, 1.0e12),
        fx=(2, 1.0),
        pop=(3, 8.0e6),
        area=(4, 800.0),
        country=(5, 2.0e13),
    )
    rows = build_city_year(city, 2024, {
        ("city", "NYC", "gdp_lcu", 2024): f["gdp"],
        ("currency", "USD", "fx_lcu_per_usd", 2024): f["fx"],
        ("city", "NYC", "population", 2024): f["pop"],
        ("city", "NYC", "area_km2", 2024): f["area"],
        ("country", "USA", "country_gdp_usd", 2024): f["country"],
    })
    by_metric = {d.metric: d for d in rows}
    assert by_metric["gdp_usd"].value == 1.0e12
    assert by_metric["primacy_pct"].value == 5.0
    assert by_metric["gdp_per_capita_usd"].value == 125_000
    assert by_metric["gdp_per_km2_usd"].value == 1.25e9
    # inputs 记录参与计算的 fact id
    assert by_metric["gdp_usd"].inputs == (1, 2)


def test_china_city_uses_average_population():
    city = CFG.city("SHA")
    base = {
        ("currency", "CNY", "fx_lcu_per_usd", 2024): FactRef(2, 7.0),
        ("city", "SHA", "gdp_lcu", 2024): FactRef(1, 7.0e12),
        ("city", "SHA", "area_km2", 2024): FactRef(5, 6340.5),
        ("country", "CHN", "country_gdp_usd", 2024): FactRef(6, 1.8e13),
        ("city", "SHA", "population", 2023): FactRef(3, 24.0e6),
        ("city", "SHA", "population", 2024): FactRef(4, 26.0e6),
    }
    rows = build_city_year(city, 2024, base)
    pc = next(d for d in rows if d.metric == "gdp_per_capita_usd")
    # 年平均 = (2400 + 2600) / 2 = 2500 万
    assert pc.value == 1.0e12 / 25.0e6
    assert set(pc.inputs) == {1, 2, 3, 4}


def test_singapore_primacy_is_100():
    city = CFG.city("SGP")
    rows = build_city_year(city, 2024, {
        ("city", "SGP", "gdp_lcu", 2024): FactRef(1, 1.0e12),
        ("currency", "SGD", "fx_lcu_per_usd", 2024): FactRef(2, 1.0),
        ("country", "SGP", "country_gdp_usd", 2024): FactRef(3, 1.0e12),
    })
    prim = next(d for d in rows if d.metric == "primacy_pct")
    assert prim.value == 100.0


def test_missing_fx_yields_no_metrics():
    city = CFG.city("LDN")
    rows = build_city_year(city, 2024, {
        ("city", "LDN", "gdp_lcu", 2024): FactRef(1, 1.0e12),
    })
    assert rows == []


def test_missing_previous_year_population_skips_per_capita():
    city = CFG.city("BJS")
    rows = build_city_year(city, 2000, {
        ("city", "BJS", "gdp_lcu", 2000): FactRef(1, 3.0e11),
        ("currency", "CNY", "fx_lcu_per_usd", 2000): FactRef(2, 8.2785),
        ("city", "BJS", "population", 2000): FactRef(3, 13.6e6),
    })
    assert {d.metric for d in rows} == {"gdp_usd"}
