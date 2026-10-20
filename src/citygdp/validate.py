"""规则校验 R1–R11（DESIGN §9）。

校验结果写入 issue 表；有 error 级问题时命令退出码为 1。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Config

ALL_RULES = tuple(f"R{i}" for i in range(1, 12))

# 中国三市与东京的量级哨兵按币种给出（见 params.yaml validation.magnitude）
CHINA_CITIES = {"BJS", "SHA", "SZX"}


@dataclass(frozen=True)
class Issue:
    rule: str
    severity: str  # info | warn | error
    message: str
    city_code: str | None = None
    year: int | None = None
    metric: str | None = None


def _years_clause(cfg: Config) -> tuple[str, tuple[int, ...]]:
    """只校验交付年份；fact 中保留的历史年份不参与规则检查。"""
    years = tuple(cfg.years)
    return "(" + ", ".join("?" for _ in years) + ")", years


def _rel(a: float, b: float) -> float:
    return abs(a - b) / abs(b) if b else float("inf")


def validate(
    conn: sqlite3.Connection, cfg: Config, rules: set[str] | None = None
) -> list[Issue]:
    selected = set(ALL_RULES) if not rules else {r.upper() for r in rules}
    unknown = selected - set(ALL_RULES)
    if unknown:
        raise ValueError(f"未知规则：{sorted(unknown)}")

    issues: list[Issue] = []
    checks = {
        "R1": _r1_uniqueness,
        "R2": _r2_fx_bounds,
        "R3": _r3_primacy,
        "R4": _r4_yoy,
        "R5": _r5_per_capita,
        "R6": _r6_density,
        "R7": _r7_magnitude,
        "R8": _r8_anchors,
        "R9": _r9_missing_whitelist,
        "R10": _r10_registry,
        "R11": _r11_completeness,
    }
    for rule in sorted(selected, key=lambda r: int(r[1:])):
        issues.extend(checks[rule](conn, cfg))

    conn.execute("DELETE FROM issue")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn.executemany(
        """
        INSERT INTO issue (step, city_code, year, metric, severity, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (i.rule, i.city_code, i.year, i.metric, i.severity, i.message, now)
            for i in issues
        ],
    )
    conn.commit()
    return issues


# ---------------------------------------------------------------- R1

def _r1_uniqueness(conn: sqlite3.Connection, cfg: Config) -> list[Issue]:
    rows = conn.execute(
        """
        SELECT entity_type, entity_code, indicator, year, COUNT(*) AS n
        FROM fact GROUP BY 1, 2, 3, 4 HAVING n > 1
        """
    ).fetchall()
    return [
        Issue(
            "R1", "error", f"{r['entity_code']} {r['indicator']} {r['year']} 有 {r['n']} 条重复记录",
            city_code=r["entity_code"], year=r["year"], metric=r["indicator"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------- R2

def _r2_fx_bounds(conn: sqlite3.Connection, cfg: Config) -> list[Issue]:
    bounds = cfg.validation.get("fx_bounds") or {}
    clause, years = _years_clause(cfg)
    issues = []
    for row in conn.execute(
        f"SELECT entity_code, year, value FROM fact WHERE indicator = 'fx_lcu_per_usd' AND year IN {clause}",
        years,
    ):
        low_high = bounds.get(row["entity_code"])
        if not low_high:
            continue
        low, high = float(low_high[0]), float(low_high[1])
        if not (low <= row["value"] <= high):
            issues.append(
                Issue("R2", "error",
                      f"{row['entity_code']} {row['year']} 汇率 {row['value']:.4f} 超出 [{low}, {high}]",
                      year=row["year"], metric="fx_lcu_per_usd")
            )
    return issues


# ---------------------------------------------------------------- R3

def _r3_primacy(conn: sqlite3.Connection, cfg: Config) -> list[Issue]:
    low, high = (float(x) for x in cfg.validation.get("primacy_bounds", [0.0, 100.0]))
    issues = []
    for row in conn.execute(
        "SELECT city_code, year, value FROM derived WHERE metric = 'primacy_pct'"
    ):
        if row["city_code"] == "SGP":
            if abs(row["value"] - 100.0) > 0.01:
                issues.append(
                    Issue("R3", "error",
                          f"新加坡 {row['year']} 首位度应为 100%，实际 {row['value']:.4f}%",
                          city_code="SGP", year=row["year"], metric="primacy_pct")
                )
            continue
        if not (low < row["value"] <= high * 1.0001):
            issues.append(
                Issue("R3", "error",
                      f"{row['city_code']} {row['year']} 首位度 {row['value']:.2f}% 超出 ({low}, {high}]",
                      city_code=row["city_code"], year=row["year"], metric="primacy_pct")
            )
    return issues


# ---------------------------------------------------------------- R4

def _r4_yoy(conn: sqlite3.Connection, cfg: Config) -> list[Issue]:
    low, high = (float(x) for x in cfg.validation.get("yoy_bounds", [-0.25, 0.45]))
    series: dict[str, list[tuple[int, float]]] = {}
    for row in conn.execute(
        "SELECT city_code, year, value FROM derived WHERE metric = 'gdp_usd' ORDER BY city_code, year"
    ):
        series.setdefault(row["city_code"], []).append((row["year"], row["value"]))

    issues = []
    for city, points in series.items():
        for (y1, v1), (y2, v2) in zip(points, points[1:]):
            if y2 - y1 != 1:
                continue  # 只检查连续年份
            change = v2 / v1 - 1
            if not (low <= change <= high):
                issues.append(
                    Issue("R4", "warn",
                          f"{city} {y1}→{y2} GDP 美元同比 {change:+.1%} 超出 [{low:.0%}, {high:.0%}]",
                          city_code=city, year=y2, metric="gdp_usd")
                )
    return issues


# ---------------------------------------------------------------- R5 / R6

def _r5_per_capita(conn: sqlite3.Connection, cfg: Config) -> list[Issue]:
    low, high = (float(x) for x in cfg.validation.get("per_capita_bounds", [0, 10**9]))
    return [
        Issue("R5", "warn",
              f"{r['city_code']} {r['year']} 人均 GDP {r['value']:,.0f} 超出 [{low:,}, {high:,}]",
              city_code=r["city_code"], year=r["year"], metric="gdp_per_capita_usd")
        for r in conn.execute(
            "SELECT city_code, year, value FROM derived WHERE metric = 'gdp_per_capita_usd'"
        )
        if not (low <= r["value"] <= high)
    ]


def _r6_density(conn: sqlite3.Connection, cfg: Config) -> list[Issue]:
    low, high = (float(x) for x in cfg.validation.get("density_bounds", [0, 10**12]))
    return [
        Issue("R6", "warn",
              f"{r['city_code']} {r['year']} 地均 GDP {r['value']:,.0f} 超出 [{low:,}, {high:,}]",
              city_code=r["city_code"], year=r["year"], metric="gdp_per_km2_usd")
        for r in conn.execute(
            "SELECT city_code, year, value FROM derived WHERE metric = 'gdp_per_km2_usd'"
        )
        if not (low <= r["value"] <= high)
    ]


# ---------------------------------------------------------------- R7

def _r7_magnitude(conn: sqlite3.Connection, cfg: Config) -> list[Issue]:
    magnitude = cfg.validation.get("magnitude") or {}
    clause, years = _years_clause(cfg)
    issues = []
    for row in conn.execute(
        f"SELECT entity_code, year, value, unit FROM fact WHERE indicator = 'gdp_lcu' AND year IN {clause}",
        years,
    ):
        bounds = magnitude.get(row["unit"])
        if not bounds:
            continue
        low, high = float(bounds[0]), float(bounds[1])
        if not (low <= row["value"] <= high):
            issues.append(
                Issue("R7", "error",
                      f"{row['entity_code']} {row['year']} GDP 量级 {row['value']:.3g} {row['unit']} 超出 [{low:.1e}, {high:.1e}]",
                      city_code=row["entity_code"], year=row["year"], metric="gdp_lcu")
            )
    return issues


# ---------------------------------------------------------------- R8

def _r8_anchors(conn: sqlite3.Connection, cfg: Config) -> list[Issue]:
    issues = []
    for anchor in cfg.anchors:
        row = conn.execute(
            "SELECT value FROM fact WHERE entity_code = ? AND indicator = ? AND year = ?",
            (anchor["city"], anchor["indicator"], anchor["year"]),
        ).fetchone()
        if row is None:
            issues.append(
                Issue("R8", "error",
                      f"锚点 {anchor['city']} {anchor['year']} 在 fact 中不存在",
                      city_code=anchor["city"], year=anchor["year"], metric=anchor["indicator"])
            )
            continue
        deviation = _rel(row["value"], anchor["value"])
        if deviation > cfg.anchor_tolerance:
            issues.append(
                Issue("R8", "error",
                      f"锚点 {anchor['city']} {anchor['year']} 偏差 {deviation:.4%} 超过 {cfg.anchor_tolerance:.2%}",
                      city_code=anchor["city"], year=anchor["year"], metric=anchor["indicator"])
            )
    return issues


# ---------------------------------------------------------------- R9

def _r9_missing_whitelist(conn: sqlite3.Connection, cfg: Config) -> list[Issue]:
    present = {
        (r["city_code"], r["year"])
        for r in conn.execute("SELECT city_code, year FROM derived WHERE metric = 'gdp_usd'")
    }
    issues = []
    for city in cfg.cities:
        for year in cfg.years:
            key = (city.code, year)
            if key in present or key in cfg.known_missing:
                continue
            issues.append(
                Issue("R9", "error", f"{city.name_cn} {year} 无数据，且不在 known_missing 白名单中",
                      city_code=city.code, year=year, metric="gdp_usd")
            )
    return issues


# ---------------------------------------------------------------- R10

def _r10_registry(conn: sqlite3.Connection, cfg: Config) -> list[Issue]:
    issues = []
    for row in conn.execute("SELECT * FROM source"):
        sid = row["id"]
        for field in ("url", "organization", "accessed_at"):
            if not row[field]:
                issues.append(
                    Issue("R10", "error", f"{sid} 缺少必填字段 {field}", metric=row["indicator"])
                )
        if row["acquisition"] != "auto":
            continue
        local = row["local_path"]
        if not local:
            issues.append(Issue("R10", "error", f"{sid} 为自动来源但缺少 local_path"))
            continue
        directory = Path(local)
        if not directory.exists():
            issues.append(Issue("R10", "error", f"{sid} 原始目录不存在：{local}"))
            continue
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            issues.append(Issue("R10", "error", f"{sid} 缺少 manifest.json"))
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest.get("files", []):
            path = directory / item["name"]
            if not path.is_file():
                issues.append(Issue("R10", "error", f"{sid} 缺少原始文件 {item['name']}"))
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != item["sha256"]:
                issues.append(Issue("R10", "error", f"{sid} 文件哈希不匹配：{item['name']}"))
    return issues


# ---------------------------------------------------------------- R11

def _r11_completeness(conn: sqlite3.Connection, cfg: Config) -> list[Issue]:
    rows = conn.execute("SELECT city_code, year, COUNT(*) AS n FROM derived GROUP BY 1, 2").fetchall()
    counts = {(r["city_code"], r["year"]): r["n"] for r in rows}
    issues = []
    for city in cfg.cities:
        for year in cfg.years:
            if (city.code, year) in cfg.known_missing:
                continue
            n = counts.get((city.code, year), 0)
            if n != 4:
                issues.append(
                    Issue("R11", "error",
                          f"{city.name_cn} {year} 派生指标应有 4 项，实际 {n} 项",
                          city_code=city.code, year=year)
                )
    return issues
