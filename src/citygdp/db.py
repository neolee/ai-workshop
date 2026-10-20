"""SQLite 中间库：连接、建表、健康检查。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# 顺序与 DDL 一致，供 doctor 与测试使用
TABLES: tuple[str, ...] = ("city", "source", "fact", "derived", "issue")


def connect(path: str | Path) -> sqlite3.Connection:
    """打开连接，开启外键约束，返回 Row 工厂。"""
    conn = sqlite3.connect(Path(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | Path) -> Path:
    """执行 schema.sql 建表（幂等）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return path


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def missing_tables(conn: sqlite3.Connection) -> list[str]:
    existing = set(table_names(conn))
    return [t for t in TABLES if t not in existing]


def row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608 - 表名来自常量元组
        for t in TABLES
    }


def foreign_key_ok(conn: sqlite3.Connection) -> bool:
    return not conn.execute("PRAGMA foreign_key_check").fetchall()


def gdp_coverage(conn: sqlite3.Connection) -> set[tuple[str, int]]:
    """已入库的 (城市, 年份) GDP 组合，用于 doctor 的覆盖矩阵。"""
    rows = conn.execute(
        "SELECT entity_code, year FROM fact "
        "WHERE entity_type = 'city' AND indicator = 'gdp_lcu'"
    ).fetchall()
    return {(r["entity_code"], r["year"]) for r in rows}
