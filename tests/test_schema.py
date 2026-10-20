"""schema 约束测试：确保数据库层能拦住错误写入。

对应 PLAN.md S1 的门禁：UNIQUE 拦截重复单元格、CHECK 拦截非法指标、
外键拦截悬空的 source_id。
"""

from __future__ import annotations

import sqlite3

import pytest

from citygdp import db


@pytest.fixture()
def conn(tmp_path):
    path = db.init_db(tmp_path / "test.sqlite")
    connection = db.connect(path)
    seed(connection)
    yield connection
    connection.close()


def seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO city (code, name_cn, name_en, country_iso3, currency, "
        "boundary, pop_basis, area_basis, note) "
        "VALUES ('NYC','纽约','New York City','USA','USD','5 county','Jul 1','land',NULL)"
    )
    conn.execute(
        "INSERT INTO source (id, city_code, indicator, organization, dataset_title, "
        "url, accessed_at, acquisition) "
        "VALUES ('BEA-CAGDP1-TEST','NYC','gdp_lcu','BEA','GDP by County',"
        "'https://example.test/CAGDP1.zip','2026-10-20T00:00:00+08:00','auto')"
    )
    conn.commit()


def add_fact(conn: sqlite3.Connection, **overrides) -> None:
    row = {
        "source_id": "BEA-CAGDP1-TEST",
        "entity_type": "city",
        "entity_code": "NYC",
        "indicator": "gdp_lcu",
        "year": 2024,
        "value": 1.37778e12,
        "unit": "USD",
    }
    row.update(overrides)
    conn.execute(
        "INSERT INTO fact (source_id, entity_type, entity_code, indicator, year, value, unit) "
        "VALUES (:source_id, :entity_type, :entity_code, :indicator, :year, :value, :unit)",
        row,
    )
    conn.commit()


def test_all_tables_created(tmp_path):
    path = db.init_db(tmp_path / "fresh.sqlite")
    conn = db.connect(path)
    try:
        assert set(db.table_names(conn)) == {"city", "source", "fact", "derived", "issue"}
    finally:
        conn.close()


def test_duplicate_cell_rejected(conn):
    add_fact(conn)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        add_fact(conn, value=1.0)


def test_invalid_indicator_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_fact(conn, indicator="gdp_bogus")


def test_invalid_entity_type_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_fact(conn, entity_type="planet")


def test_dangling_source_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        add_fact(conn, source_id="NO-SUCH-SOURCE")


def test_invalid_status_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO fact (source_id, entity_type, entity_code, indicator, year, value, unit, status) "
            "VALUES ('BEA-CAGDP1-TEST','city','NYC','population',2024,8480000,'person','draft')"
        )


def test_valid_rows_accepted(conn):
    add_fact(conn)
    add_fact(conn, indicator="population", value=8_478_072, unit="person")
    add_fact(conn, indicator="area_km2", value=778.2, unit="km2")
    count = conn.execute("SELECT COUNT(*) FROM fact").fetchone()[0]
    assert count == 3
    assert db.foreign_key_ok(conn)
