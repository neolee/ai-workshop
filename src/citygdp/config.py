"""配置加载与校验。

配置文件是口径的唯一定义处：config/cities.yaml、config/params.yaml、
config/anchors.yaml。本模块负责把三者读入并做结构校验，任何不一致都在
这里以 ConfigError 报出，避免带着错误口径进入取数阶段。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# 交付指标的顺序即交付表中指标块的顺序（SPEC.md §8.1）
METRICS: tuple[str, ...] = (
    "gdp_usd",
    "primacy_pct",
    "gdp_per_capita_usd",
    "gdp_per_km2_usd",
)

EXPECTED_CITY_CODES: tuple[str, ...] = (
    "NYC", "LDN", "TYO", "SGP", "BJS", "SHA", "SZX", "HKG",
)

REQUIRED_CITY_FIELDS: tuple[str, ...] = (
    "code", "name_cn", "name_en", "country_iso3", "currency",
    "boundary", "population", "area",
)


class ConfigError(Exception):
    """配置缺失或结构不合法。"""


@dataclass(frozen=True)
class City:
    code: str
    name_cn: str
    name_en: str
    country_iso3: str
    currency: str
    boundary: str
    population: dict[str, Any]
    area: dict[str, Any]
    note: str | None = None
    breaks: tuple[dict[str, Any], ...] = ()

    @property
    def pop_basis(self) -> str:
        return str(self.population.get("basis", ""))

    @property
    def area_basis(self) -> str:
        return str(self.area.get("basis", ""))


@dataclass(frozen=True)
class Config:
    root: Path
    cities: tuple[City, ...]
    years: tuple[int, ...]
    indicators: tuple[dict[str, Any], ...]
    fx_indicator: str
    country_gdp_indicator: str
    paths: dict[str, Path]
    output: dict[str, Path]
    adopted_source: dict[str, dict[str, str]]
    validation: dict[str, Any]
    anchors: tuple[dict[str, Any], ...]
    anchor_tolerance: float

    @property
    def city_codes(self) -> tuple[str, ...]:
        return tuple(c.code for c in self.cities)

    def city(self, code: str) -> City:
        for c in self.cities:
            if c.code == code:
                return c
        raise KeyError(code)


def find_root(explicit: str | Path | None = None) -> Path:
    """定位项目根目录：显式参数 > 环境变量 > 自 __file__ 向上查找。"""
    if explicit is not None:
        root = Path(explicit).resolve()
        if not (root / "config" / "cities.yaml").is_file():
            raise ConfigError(f"{root} 下找不到 config/cities.yaml")
        return root

    env = os.environ.get("CITYGDP_ROOT")
    if env:
        return find_root(env)

    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config" / "cities.yaml").is_file():
            return parent
    raise ConfigError("找不到项目根目录（需包含 pyproject.toml 与 config/cities.yaml）")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"缺少配置文件：{path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} 顶层必须是映射（mapping）")
    return data


def load_config(root: str | Path | None = None) -> Config:
    base = find_root(root)
    raw_cities = _load_yaml(base / "config" / "cities.yaml")
    params = _load_yaml(base / "config" / "params.yaml")
    raw_anchors = _load_yaml(base / "config" / "anchors.yaml")

    errors: list[str] = []

    # ---- 城市 ----
    cities_raw = raw_cities.get("cities")
    if not isinstance(cities_raw, list) or not cities_raw:
        raise ConfigError("cities.yaml: 缺少非空的 cities 列表")

    cities: list[City] = []
    for i, item in enumerate(cities_raw):
        if not isinstance(item, dict):
            errors.append(f"cities[{i}] 不是映射")
            continue
        for key in REQUIRED_CITY_FIELDS:
            if key not in item:
                errors.append(f"cities[{i}] 缺少字段 {key}")
        for key in ("code", "name_cn", "name_en", "country_iso3", "currency"):
            if key in item and not isinstance(item[key], str):
                errors.append(f"cities[{i}].{key} 必须是字符串")
        if "country_iso3" in item and len(str(item["country_iso3"])) != 3:
            errors.append(f"cities[{i}].country_iso3 必须是 3 位 ISO 代码")
        if "currency" in item and len(str(item["currency"])) != 3:
            errors.append(f"cities[{i}].currency 必须是 3 位币种代码")
        for key in ("population", "area"):
            if key in item and not isinstance(item[key], dict):
                errors.append(f"cities[{i}].{key} 必须是映射")
        try:
            cities.append(
                City(
                    code=item["code"],
                    name_cn=item["name_cn"],
                    name_en=item["name_en"],
                    country_iso3=item["country_iso3"],
                    currency=item["currency"],
                    boundary=item["boundary"],
                    population=item["population"],
                    area=item["area"],
                    note=item.get("note"),
                    breaks=tuple(item.get("breaks") or ()),
                )
            )
        except KeyError as exc:  # 已在上面记录，这里只避免二次崩溃
            errors.append(f"cities[{i}] 解析失败：{exc}")

    codes = [c.code for c in cities]
    if len(set(codes)) != len(codes):
        errors.append(f"城市代码重复：{codes}")
    if set(codes) != set(EXPECTED_CITY_CODES):
        errors.append(
            f"城市集合不符：期望 {sorted(EXPECTED_CITY_CODES)}，实际 {sorted(codes)}"
        )
    # 顺序即交付表行序，必须与 SPEC 一致
    if codes != list(EXPECTED_CITY_CODES):
        errors.append(f"城市顺序不符：期望 {list(EXPECTED_CITY_CODES)}，实际 {codes}")

    # ---- 年份 ----
    years_raw = params.get("years")
    if not isinstance(years_raw, list) or not years_raw:
        errors.append("params.yaml: years 必须是非空列表")
        years: tuple[int, ...] = ()
    else:
        if not all(isinstance(y, int) for y in years_raw):
            errors.append("params.yaml: years 必须全为整数")
        if years_raw != sorted(years_raw):
            errors.append("params.yaml: years 必须升序")
        if len(set(years_raw)) != len(years_raw):
            errors.append("params.yaml: years 有重复")
        for y in years_raw:
            if isinstance(y, int) and not (1990 <= y <= 2030):
                errors.append(f"params.yaml: 年份 {y} 超出合理区间 1990–2030")
        years = tuple(years_raw)

    # ---- 指标 ----
    indicators_raw = params.get("indicators")
    if not isinstance(indicators_raw, list) or len(indicators_raw) != len(METRICS):
        errors.append(f"params.yaml: indicators 必须是 {len(METRICS)} 项")
        indicators: tuple[dict[str, Any], ...] = ()
    else:
        keys = [str(i.get("key")) for i in indicators_raw if isinstance(i, dict)]
        if tuple(keys) != METRICS:
            errors.append(f"params.yaml: indicators 顺序应为 {METRICS}，实际 {tuple(keys)}")
        for i in indicators_raw:
            if not isinstance(i, dict):
                continue
            for key in ("key", "label", "unit", "decimals"):
                if key not in i:
                    errors.append(f"params.yaml: indicator 缺少 {key}")
        indicators = tuple(indicators_raw)

    # ---- 路径 ----
    paths_raw = params.get("paths") or {}
    output_raw = params.get("output") or {}
    paths = {k: (base / str(v)) for k, v in paths_raw.items()}
    output = {k: (base / str(v)) for k, v in output_raw.items()}
    for required in ("db", "raw", "manual"):
        if required not in paths:
            errors.append(f"params.yaml: paths 缺少 {required}")
    for required in ("workbook", "registry", "notes"):
        if required not in output:
            errors.append(f"params.yaml: output 缺少 {required}")

    # ---- 锚点 ----
    anchors_raw = raw_anchors.get("anchors") or []
    anchors: list[dict[str, Any]] = []
    if not isinstance(anchors_raw, list):
        errors.append("anchors.yaml: anchors 必须是列表")
        anchors_raw = []
    for i, a in enumerate(anchors_raw):
        if not isinstance(a, dict):
            errors.append(f"anchors[{i}] 不是映射")
            continue
        if a.get("city") not in set(codes):
            errors.append(f"anchors[{i}]: 未知城市 {a.get('city')}")
        if years and a.get("year") not in set(years):
            errors.append(f"anchors[{i}]: 年份 {a.get('year')} 不在 years 中")
        if not isinstance(a.get("value"), (int, float)) or a.get("value", 0) <= 0:
            errors.append(f"anchors[{i}]: value 必须是正数")
        anchors.append(a)

    tolerance = raw_anchors.get("tolerance", 0.005)
    if not isinstance(tolerance, (int, float)) or not (0 < tolerance < 1):
        errors.append("anchors.yaml: tolerance 必须在 (0,1) 内")
        tolerance = 0.005

    # ---- 采纳源 ----
    adopted = params.get("adopted_source") or {}
    if not isinstance(adopted, dict):
        errors.append("params.yaml: adopted_source 必须是映射")
        adopted = {}
    for city_code, mapping in adopted.items():
        if city_code not in set(codes):
            errors.append(f"adopted_source: 未知城市 {city_code}")
            continue
        if not isinstance(mapping, dict):
            errors.append(f"adopted_source.{city_code} 必须是映射")
            continue
        for ind in mapping:
            if ind not in set(METRICS) | {"gdp_lcu", "population", "area_km2"}:
                errors.append(f"adopted_source.{city_code}: 未知指标 {ind}")

    if errors:
        raise ConfigError("配置校验失败：\n  - " + "\n  - ".join(errors))

    return Config(
        root=base,
        cities=tuple(cities),
        years=years,
        indicators=indicators,
        fx_indicator=str(params["fx_indicator"]),
        country_gdp_indicator=str(params["country_gdp_indicator"]),
        paths=paths,
        output=output,
        adopted_source=adopted,
        validation=params.get("validation") or {},
        anchors=tuple(anchors),
        anchor_tolerance=float(tolerance),
    )
