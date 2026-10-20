"""把解析结果写入 SQLite：注册城市、登记来源、写入 fact。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict

from .adapters.base import Fact, Fetched
from .config import Config


def register_cities(conn: sqlite3.Connection, cfg: Config) -> None:
    """把 cities.yaml 的城市主数据同步到 city 表。"""
    for city in cfg.cities:
        conn.execute(
            """
            INSERT INTO city (code, name_cn, name_en, country_iso3, currency,
                              boundary, pop_basis, area_basis, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name_cn=excluded.name_cn,
                name_en=excluded.name_en,
                country_iso3=excluded.country_iso3,
                currency=excluded.currency,
                boundary=excluded.boundary,
                pop_basis=excluded.pop_basis,
                area_basis=excluded.area_basis,
                note=excluded.note
            """,
            (
                city.code,
                city.name_cn,
                city.name_en,
                city.country_iso3,
                city.currency,
                city.boundary,
                city.pop_basis,
                city.area_basis,
                city.note,
            ),
        )
    conn.commit()


def ingest_fetched(conn: sqlite3.Connection, fetched: Fetched, facts: list[Fact]) -> int:
    """写入一条来源及其观测值。

    同一数据集的新版本会替换旧版本的 fact（dataset_key 前缀匹配），
    但 source 表保留历史行，便于追溯。
    """
    meta = fetched.meta
    manifest = fetched.manifest

    conn.execute(
        """
        INSERT OR REPLACE INTO source
            (id, city_code, indicator, organization, dataset_title, table_id, url,
             vintage, published_at, accessed_at, http_etag, http_last_modified,
             sha256, local_path, acquisition, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            meta.id,
            meta.city_code,
            meta.indicator,
            meta.organization,
            meta.dataset_title,
            meta.table_id,
            meta.url,
            meta.vintage,
            meta.published_at,
            manifest.get("fetched_at"),
            manifest.get("etag"),
            manifest.get("last_modified"),
            _aggregate_sha(manifest),
            str(fetched.directory),
            meta.acquisition,
            meta.notes,
        ),
    )

    # 同一数据集的所有旧版本 fact 先清除，避免唯一约束冲突
    conn.execute("DELETE FROM fact WHERE source_id LIKE ?", (f"{meta.dataset_key}-%",))

    unique: dict[tuple[str, str, str, int], Fact] = {}
    for fact in facts:
        key = (fact.entity_type, fact.entity_code, fact.indicator, fact.year)
        unique[key] = fact  # 后出现的覆盖先出现的

    conn.executemany(
        """
        INSERT INTO fact (source_id, entity_type, entity_code, indicator,
                          year, value, unit, status, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                meta.id,
                f.entity_type,
                f.entity_code,
                f.indicator,
                f.year,
                f.value,
                f.unit,
                f.status,
                f.note,
            )
            for f in unique.values()
        ],
    )
    conn.commit()
    return len(unique)


def _aggregate_sha(manifest: dict) -> str | None:
    """单文件取其 SHA256；多文件取「文件名:哈希」拼接后的 SHA256。"""
    files = manifest.get("files") or []
    if not files:
        return None
    if len(files) == 1:
        return files[0]["sha256"]
    joined = "|".join(f'{f["name"]}:{f["sha256"]}' for f in sorted(files, key=lambda x: x["name"]))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def ingest_constant_areas(conn: sqlite3.Connection, cfg) -> int:
    """写入「地理常数」型面积（城市面积各年不变，或按 breaks 跳变）。

    这类数据没有可下载的原始文件，以 source_id = REF-GEO-{CODE} 登记，
    acquisition = manual，并在 notes 中记录所依据的官方出版物。
    """
    total = 0
    for city in cfg.cities:
        area = city.area or {}
        if area.get("kind") != "constant":
            continue
        value = area.get("reference_km2")
        if value is None:
            continue

        source_id = f"REF-GEO-{city.code}"
        conn.execute(
            """
            INSERT OR REPLACE INTO source
                (id, city_code, indicator, organization, dataset_title, table_id, url,
                 vintage, published_at, accessed_at, acquisition, notes)
            VALUES (?, ?, 'area', ?, ?, NULL, ?, ?, NULL, ?, 'manual', ?)
            """,
            (
                source_id,
                city.code,
                area.get("source_name") or "城市统计机构",
                f"{city.name_cn} 面积（{area.get('basis', '')}）",
                area.get("source_url") or "",
                str(area.get("as_of") or ""),
                _now(),
                area.get("note"),
            ),
        )
        conn.execute("DELETE FROM fact WHERE source_id = ?", (source_id,))

        rows = [(year, float(value)) for year in cfg.years]
        conn.executemany(
            "INSERT INTO fact (source_id, entity_type, entity_code, indicator, year, value, unit, status, note) "
            "VALUES (?, 'city', ?, 'area_km2', ?, ?, 'km2', 'final', NULL)",
            [(source_id, city.code, year, v) for year, v in rows],
        )
        total += len(rows)
    conn.commit()
    return total


def _now() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def dump_meta(meta) -> str:
    return json.dumps(asdict(meta), ensure_ascii=False)
