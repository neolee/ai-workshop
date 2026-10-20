"""派生指标计算：把 fact 中的原始观测换算成 4 项交付指标。

公式（SPEC §5）：
  gdp_usd        = gdp_lcu / fx_lcu_per_usd
  primacy_pct    = gdp_usd(city) / gdp_usd(country) × 100
  gdp_per_capita = gdp_usd / population
  gdp_per_km2    = gdp_usd / area_km2

任一输入缺失则该指标不写入（导出即为空），不做插值。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from .config import Config, City

METRIC_UNITS = {
    "gdp_usd": "USD",
    "primacy_pct": "%",
    "gdp_per_capita_usd": "USD/person",
    "gdp_per_km2_usd": "USD/km2",
}


@dataclass(frozen=True)
class FactRef:
    id: int
    value: float


@dataclass(frozen=True)
class Derived:
    city_code: str
    year: int
    metric: str
    value: float
    formula: str
    inputs: tuple[int, ...]


def load_facts(conn: sqlite3.Connection) -> dict[tuple[str, str, str, int], FactRef]:
    rows = conn.execute(
        "SELECT id, entity_type, entity_code, indicator, year, value FROM fact"
    ).fetchall()
    return {
        (r["entity_type"], r["entity_code"], r["indicator"], r["year"]): FactRef(r["id"], r["value"])
        for r in rows
    }


def population_ref(
    city: City, year: int, facts: dict[tuple[str, str, str, int], FactRef]
) -> tuple[float, tuple[int, ...]] | None:
    """返回 (人口, 参与计算的 fact id)。

    中国三市存的是年末常住人口，人均口径用年平均 =（上年末 + 本年末）/ 2；
    其余城市存的是年中估计，直接使用。
    """
    if city.population.get("computation") == "year_end_average":
        current = facts.get(("city", city.code, "population", year))
        previous = facts.get(("city", city.code, "population", year - 1))
        if current is None or previous is None:
            return None
        return (previous.value + current.value) / 2, (previous.id, current.id)

    single = facts.get(("city", city.code, "population", year))
    if single is None:
        return None
    return single.value, (single.id,)


def build_city_year(
    city: City, year: int, facts: dict[tuple[str, str, str, int], FactRef]
) -> list[Derived]:
    gdp = facts.get(("city", city.code, "gdp_lcu", year))
    fx = facts.get(("currency", city.currency, "fx_lcu_per_usd", year))
    if gdp is None or fx is None:
        return []

    gdp_usd = gdp.value / fx.value
    out = [
        Derived(
            city.code, year, "gdp_usd", gdp_usd,
            "gdp_lcu / fx_lcu_per_usd", (gdp.id, fx.id),
        )
    ]

    pop = population_ref(city, year, facts)
    if pop is not None:
        value, ids = pop
        out.append(
            Derived(
                city.code, year, "gdp_per_capita_usd", gdp_usd / value,
                "gdp_usd / population", (gdp.id, fx.id, *ids),
            )
        )

    area = facts.get(("city", city.code, "area_km2", year))
    if area is not None:
        out.append(
            Derived(
                city.code, year, "gdp_per_km2_usd", gdp_usd / area.value,
                "gdp_usd / area_km2", (gdp.id, fx.id, area.id),
            )
        )

    country = facts.get(("country", city.country_iso3, "country_gdp_usd", year))
    if country is not None:
        formula = "gdp_usd(city) / gdp_usd(country) × 100"
        if city.code == "SGP":
            formula = "城市国家：分母即本国 GDP，比值恒为 100"
        out.append(
            Derived(
                city.code, year, "primacy_pct", gdp_usd / country.value * 100,
                formula, (gdp.id, fx.id, country.id),
            )
        )
    return out


def build(conn: sqlite3.Connection, cfg: Config) -> dict[str, int]:
    facts = load_facts(conn)
    rows: list[Derived] = []
    for city in cfg.cities:
        for year in cfg.years:
            rows.extend(build_city_year(city, year, facts))

    conn.execute("DELETE FROM derived")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn.executemany(
        """
        INSERT INTO derived (city_code, year, metric, value, unit, formula, inputs_json, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                d.city_code, d.year, d.metric, d.value,
                METRIC_UNITS[d.metric], d.formula, json.dumps(list(d.inputs)), now,
            )
            for d in rows
        ],
    )
    conn.commit()

    counts: dict[str, int] = {}
    for d in rows:
        counts[d.metric] = counts.get(d.metric, 0) + 1
    return counts
