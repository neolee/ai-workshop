"""ingest 逻辑测试：来源登记、旧版本替换、单值约束。"""

from __future__ import annotations

from pathlib import Path

import pytest

from citygdp.adapters.base import Fact, Fetched, SourceMeta
from citygdp.config import load_config
from citygdp.db import connect, init_db
from citygdp.ingest import ingest_constant_areas, ingest_fetched, register_cities

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def conn(tmp_path):
    path = init_db(tmp_path / "t.sqlite")
    connection = connect(path)
    register_cities(connection, load_config(ROOT))
    yield connection
    connection.close()


def make(source_id: str, facts: list[Fact], dataset_key: str = "HKCSD-310-31002") -> Fetched:
    meta = SourceMeta(
        id=source_id,
        dataset_key=dataset_key,
        city_code="HKG",
        indicator="gdp",
        organization="C&SD",
        dataset_title="GDP",
        table_id="310-31002",
        url="https://example.test",
        vintage=source_id.rsplit("-", 1)[-1],
    )
    return Fetched(
        meta=meta,
        directory=Path("/tmp/does-not-matter"),
        files=[],
        manifest={"fetched_at": "2026-10-20T21:00:00+08:00", "files": []},
    )


def test_cities_registered(conn):
    rows = conn.execute("SELECT code FROM city ORDER BY code").fetchall()
    assert [r["code"] for r in rows] == ["BJS", "HKG", "LDN", "NYC", "SGP", "SHA", "SZX", "TYO"]


def test_new_vintage_replaces_old_facts(conn):
    old = make(
        "HKCSD-310-31002-2024",
        [Fact("city", "HKG", "gdp_lcu", 2024, 3.0e12, "HKD")],
    )
    assert ingest_fetched(conn, old, [Fact("city", "HKG", "gdp_lcu", 2024, 3.0e12, "HKD")]) == 1

    new = make(
        "HKCSD-310-31002-2025",
        [Fact("city", "HKG", "gdp_lcu", 2024, 3.186526e12, "HKD")],
    )
    assert ingest_fetched(
        conn,
        new,
        [
            Fact("city", "HKG", "gdp_lcu", 2024, 3.186526e12, "HKD"),
            Fact("city", "HKG", "gdp_lcu", 2025, 3.329843e12, "HKD"),
        ],
    ) == 2

    rows = conn.execute(
        "SELECT year, value, source_id FROM fact WHERE entity_code='HKG' ORDER BY year"
    ).fetchall()
    assert len(rows) == 2  # 旧版本的 2024 已被替换，不是新增
    assert rows[0]["source_id"] == "HKCSD-310-31002-2025"
    assert rows[0]["value"] == pytest.approx(3.186526e12)
    assert rows[1]["year"] == 2025


def test_duplicate_fact_in_one_batch_is_deduped(conn):
    fetched = make("HKCSD-310-31002-2025", [])
    facts = [
        Fact("city", "HKG", "population", 2024, 7_500_000, "person"),
        Fact("city", "HKG", "population", 2024, 7_524_100, "person"),
    ]
    assert ingest_fetched(conn, fetched, facts) == 1
    value = conn.execute(
        "SELECT value FROM fact WHERE indicator='population' AND year=2024"
    ).fetchone()["value"]
    assert value == pytest.approx(7_524_100)  # 后者覆盖前者


def test_constant_areas_written(conn):
    cfg = load_config(ROOT)
    count = ingest_constant_areas(conn, cfg)
    assert count == 18  # NYC + LDN，各 9 个年份
    rows = conn.execute(
        "SELECT entity_code, year, value FROM fact WHERE indicator='area_km2'"
    ).fetchall()
    assert {r["value"] for r in rows if r["entity_code"] == "NYC"} == {778.2}
    assert {r["value"] for r in rows if r["entity_code"] == "LDN"} == {1572.0}
