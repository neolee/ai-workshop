"""命令行入口。

S1 只实现 `doctor`；其余命令保留骨架，在后续步骤逐个落地。
"""

from __future__ import annotations

import argparse
import sys
import unicodedata

from . import __version__, db
from .config import ConfigError, load_config


# ---------------------------------------------------------------- 显示辅助

def _display_width(text: str) -> int:
    """按终端显示宽度计算长度（中文按 2 计）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int, align: str = "left") -> str:
    gap = max(0, width - _display_width(text))
    return (" " * gap + text) if align == "right" else (text + " " * gap)


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
        fk_ok = db.foreign_key_ok(conn)
        print(f"       外键   {'通过' if fk_ok else '存在违规'}")
        ok = ok and fk_ok

        filled = sum(1 for c in cfg.cities for y in cfg.years if (c.code, y) in coverage)
        expected = sum(
            1
            for c in cfg.cities
            for y in cfg.years
            if not _known_missing(c.code, y)
        )
        print(f"       覆盖   {filled}/{expected}（按 SPEC §4.3 的可得性基线）")
    finally:
        conn.close()

    print("-" * 64)
    print("结论：OK" if ok else "结论：存在失败项")
    return 0 if ok else 1


# SPEC §4.3 明确的不可得组合；S2–S5 完成后应与此完全一致
_KNOWN_MISSING: frozenset[tuple[str, int]] = frozenset(
    {
        ("NYC", 2000),
        ("NYC", 2025),
        ("LDN", 2025),
        ("TYO", 2024),
        ("TYO", 2025),
    }
)


def _known_missing(city_code: str, year: int) -> bool:
    return (city_code, year) in _KNOWN_MISSING


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

    for name, help_text in (
        ("fetch", "下载原始数据到 data/raw"),
        ("ingest", "解析原始数据写入 fact 表"),
        ("build", "计算派生指标"),
        ("validate", "规则校验"),
        ("export", "导出交付物"),
        ("all", "全流程（fetch → export）"),
    ):
        p = sub.add_parser(name, help=help_text)
        if name in ("fetch", "ingest"):
            p.add_argument("--source", default="all", help="来源 ID 或 all")
        if name == "validate":
            p.add_argument("--rule", default=None, help="逗号分隔的规则编号，如 R2,R3")
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


if __name__ == "__main__":
    raise SystemExit(main())
