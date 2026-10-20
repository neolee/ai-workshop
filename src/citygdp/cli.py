"""命令行入口。

已实现：doctor、fetch、ingest。
待实现：build、validate、export（S6–S7）。
"""

from __future__ import annotations

import argparse
import sys
import unicodedata

from . import __version__, db
from .adapters import ADAPTERS
from .adapters.base import latest_fetch
from .build import build
from .validate import validate
from .config import Config, ConfigError, load_config
from .http import FetchError, HttpClient
from .ingest import ingest_constant_areas, ingest_fetched, register_cities

# ---------------------------------------------------------------- 显示辅助

def _display_width(text: str) -> int:
    """按终端显示宽度计算长度（中文按 2 计）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int, align: str = "left") -> str:
    gap = max(0, width - _display_width(text))
    return (" " * gap + text) if align == "right" else (text + " " * gap)


def _resolve_sources(value: str) -> list[str]:
    if value.strip() == "all":
        return list(ADAPTERS)
    names = [x.strip() for x in value.split(",") if x.strip()]
    unknown = [n for n in names if n not in ADAPTERS]
    if unknown:
        raise SystemExit(f"未知数据源：{unknown}；可选 {sorted(ADAPTERS)} 或 all")
    if not names:
        raise SystemExit("--source 不能为空")
    return names


# ---------------------------------------------------------------- doctor

def cmd_doctor(_args: argparse.Namespace) -> int:
    print(f"citygdp {__version__} — 环境自检")
    print("=" * 64)

    try:
        cfg = load_config()
    except ConfigError as exc:
        print("[配置] 失败")
        print(str(exc))
        return 1

    print("[配置] 通过")
    print(f"       根目录  {cfg.root}")
    print(f"       城市    {len(cfg.cities)} 个：{'、'.join(c.name_cn for c in cfg.cities)}")
    print(f"       年份    {len(cfg.years)} 个：{', '.join(map(str, cfg.years))}")
    print(f"       指标    {len(cfg.indicators)} 项：{'、'.join(str(i['label']) for i in cfg.indicators)}")
    print(f"       锚点    {len(cfg.anchors)} 条（容差 {cfg.anchor_tolerance:.2%}）")

    db_path = cfg.paths["db"]
    created = not db_path.exists()
    if created:
        db.init_db(db_path)

    conn = db.connect(db_path)
    ok = True
    try:
        missing = db.missing_tables(conn)
        if missing:  # 文件存在但 schema 不全，补建
            db.init_db(db_path)
            missing = db.missing_tables(conn)
        if missing:
            print(f"[数据库] 失败：缺少表 {missing}")
            return 1

        coverage = db.gdp_coverage(conn)
        print()
        print("[覆盖] 行 = 城市，列 = 年份（✓ 已入库，· 暂无）")
        label_w = max(_display_width(c.name_cn) for c in cfg.cities) + 2
        cell_w = 5
        print(" " * label_w + "".join(_pad(str(y), cell_w, "right") for y in cfg.years))
        for c in cfg.cities:
            row = _pad(c.name_cn, label_w)
            for y in cfg.years:
                mark = "✓" if (c.code, y) in coverage else "·"
                row += _pad(mark, cell_w, "right")
            print(row)

        counts = db.row_counts(conn)
        print()
        rel = db_path.relative_to(cfg.root)
        print(f"[数据库] {rel} （{'新建' if created else '已存在'}）")
        print(f"       表     {', '.join(db.table_names(conn))}")
        print(f"       行数   " + "  ".join(f"{k}={v}" for k, v in counts.items()))
        by_ind = _fact_breakdown(conn)
        if by_ind:
            print(f"       明细   " + "  ".join(f"{k}={v}" for k, v in by_ind))
        fk_ok = db.foreign_key_ok(conn)
        print(f"       外键   {'通过' if fk_ok else '存在违规'}")
        ok = ok and fk_ok

        filled = sum(1 for c in cfg.cities for y in cfg.years if (c.code, y) in coverage)
        expected = sum(
            1 for c in cfg.cities for y in cfg.years if (c.code, y) not in cfg.known_missing
        )
        print(f"       覆盖   {filled}/{expected}（按 SPEC §4.3 的可得性基线）")
    finally:
        conn.close()

    print("-" * 64)
    print("结论：OK" if ok else "结论：存在失败项")
    return 0 if ok else 1


def _fact_breakdown(conn) -> list[tuple[str, int]]:
    try:
        rows = conn.execute(
            "SELECT indicator, COUNT(*) AS n FROM fact GROUP BY indicator ORDER BY indicator"
        ).fetchall()
    except Exception:  # noqa: BLE001 - 诊断信息，失败不应影响主流程
        return []
    return [(r["indicator"], r["n"]) for r in rows]


# ---------------------------------------------------------------- fetch

def cmd_fetch(args: argparse.Namespace) -> int:
    cfg = load_config()
    raw_root = cfg.paths["raw"]
    raw_root.mkdir(parents=True, exist_ok=True)
    names = _resolve_sources(args.source)

    print(f"抓取 {len(names)} 个数据源 → {raw_root.relative_to(cfg.root)}")
    with HttpClient() as client:
        for name in names:
            adapter = ADAPTERS[name]()
            fetched_list = adapter.fetch(client, raw_root)
            for fetched in fetched_list:
                print(f"  [{name}] {fetched.meta.id}  {len(fetched.files)} 文件")
    print("完成。")
    return 0


# ---------------------------------------------------------------- ingest

def cmd_ingest(args: argparse.Namespace) -> int:
    cfg = load_config()
    db_path = cfg.paths["db"]
    db.init_db(db_path)
    conn = db.connect(db_path)
    names = _resolve_sources(args.source)
    total = 0
    try:
        register_cities(conn, cfg)
        for name in names:
            adapter = ADAPTERS[name]()
            for key in adapter.dataset_keys:
                fetched = latest_fetch(cfg.paths["raw"], key)
                if fetched is None:
                    print(f"  [{name}] {key}: 无原始数据，跳过（先执行 fetch）")
                    continue
                facts = adapter.parse(fetched)
                count = ingest_fetched(conn, fetched, facts)
                total += count
                print(f"  [{name}] {fetched.meta.id}  fact={count}")
        area_count = ingest_constant_areas(conn, cfg)
        if area_count:
            print(f"  [geo] 常数面积  fact={area_count}")
        counts = db.row_counts(conn)
        print("入库完成：" + "  ".join(f"{k}={v}" for k, v in counts.items()))
    finally:
        conn.close()
    return 0 if total else 1


# ---------------------------------------------------------------- build

def cmd_build(_args: argparse.Namespace) -> int:
    cfg = load_config()
    conn = db.connect(cfg.paths["db"])
    try:
        counts = build(conn, cfg)
    finally:
        conn.close()
    order = ["gdp_usd", "primacy_pct", "gdp_per_capita_usd", "gdp_per_km2_usd"]
    print("派生指标：" + "  ".join(f"{k}={counts.get(k, 0)}" for k in order))
    return 0


# ---------------------------------------------------------------- validate

def cmd_validate(args: argparse.Namespace) -> int:
    cfg = load_config()
    conn = db.connect(cfg.paths["db"])
    rules = {r.strip() for r in args.rule.split(",")} if args.rule else None
    try:
        issues = validate(conn, cfg, rules)
    finally:
        conn.close()

    errors = [i for i in issues if i.severity == "error"]
    warns = [i for i in issues if i.severity == "warn"]
    print(f"校验完成：error={len(errors)}  warn={len(warns)}")
    for issue in errors + warns:
        print(f"  [{issue.rule}][{issue.severity}] {issue.message}")
    if not issues:
        print("  全部规则通过")
    return 1 if errors else 0


# ---------------------------------------------------------------- 骨架命令

def _make_stub(name: str):
    def _stub(_args: argparse.Namespace) -> int:
        raise NotImplementedError(f"`{name}` 将在后续步骤实现（见 PLAN.md）")

    return _stub


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="citygdp",
        description="城市 GDP 数据采集与统计（8 城 × 9 年 × 4 指标）",
    )
    parser.add_argument("--version", action="version", version=f"citygdp {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="环境、配置、数据库自检")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("fetch", help="下载原始数据到 data/raw")
    p.add_argument("--source", default="all", help="数据源名或逗号分隔列表，默认 all")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("ingest", help="解析原始数据写入 fact 表")
    p.add_argument("--source", default="all", help="数据源名或逗号分隔列表，默认 all")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("build", help="计算派生指标")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("validate", help="规则校验")
    p.add_argument("--rule", default=None, help="逗号分隔的规则编号，如 R2,R3")
    p.set_defaults(func=cmd_validate)

    for name, help_text in (
        ("export", "导出交付物"),
        ("all", "全流程（fetch → export）"),
    ):
        p = sub.add_parser(name, help=help_text)
        if name == "all":
            p.add_argument("--skip-fetch", action="store_true", help="跳过联网抓取，仅重建")
        p.set_defaults(func=_make_stub(name))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except NotImplementedError as exc:
        print(f"[未实现] {exc}", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return 1
    except FetchError as exc:
        print(f"[抓取失败] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
