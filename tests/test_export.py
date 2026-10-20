"""S7：导出配置的一致性检查。"""

from __future__ import annotations

from pathlib import Path

from citygdp.config import load_config
from citygdp.export import MISSING_REASONS, metric_specs

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT)


def test_missing_reasons_cover_whitelist():
    assert set(MISSING_REASONS) == set(CFG.known_missing)


def test_metric_specs_match_config_order():
    assert tuple(m.key for m in metric_specs(CFG)) == tuple(i["key"] for i in CFG.indicators)


def test_metric_labels_and_units_match_config():
    specs = metric_specs(CFG)
    assert tuple(m.label for m in specs) == tuple(i["label"] for i in CFG.indicators)
    assert tuple(m.unit for m in specs) == tuple(i["unit"] for i in CFG.indicators)


def test_density_uses_hundred_million_usd():
    spec = next(m for m in metric_specs(CFG) if m.key == "gdp_per_km2_usd")
    assert spec.unit == "亿美元/km²"
    assert spec.scale == 1e-8
