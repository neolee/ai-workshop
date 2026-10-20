"""配置加载与结构校验测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from citygdp.config import EXPECTED_CITY_CODES, METRICS, ConfigError, load_config

ROOT = Path(__file__).resolve().parents[1]


def test_loads_expected_shape():
    cfg = load_config(ROOT)
    assert tuple(c.code for c in cfg.cities) == EXPECTED_CITY_CODES
    assert len(cfg.cities) == 8
    assert cfg.years == (2000, 2005, 2010, 2015, 2020, 2022, 2023, 2024, 2025)
    assert tuple(i["key"] for i in cfg.indicators) == METRICS
    assert len(cfg.anchors) >= 5


def test_every_city_has_currency_and_basis():
    cfg = load_config(ROOT)
    for city in cfg.cities:
        assert len(city.currency) == 3
        assert city.pop_basis, f"{city.code} 缺少人口口径"
        assert city.area_basis, f"{city.code} 缺少面积口径"


def test_paths_resolve_under_root():
    cfg = load_config(ROOT)
    for key in ("db", "raw", "manual"):
        assert cfg.paths[key].is_absolute()
        assert cfg.paths[key].is_relative_to(cfg.root)


def test_shenzhen_break_recorded():
    cfg = load_config(ROOT)
    szx = cfg.city("SZX")
    assert any(b["from_year"] == 2024 for b in szx.breaks)


def test_missing_config_dir_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path)
