"""世界银行 WDI：国家 GDP（现价美元）与官方汇率（本币/美元）。

端点无需 key：
  https://api.worldbank.org/v2/country/{ISO3}/indicator/{IND}?format=json&per_page=1000&date=1990:2030
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import Adapter, Fact, Fetched, SourceMeta, commit_raw

NAME = "worldbank"

GDP_IND = "NY.GDP.MKTP.CD"
FX_IND = "PA.NUS.FCRF"

# 需要取数的经济体：ISO3 -> 本币
ECONOMIES: dict[str, str] = {
    "USA": "USD",
    "GBR": "GBP",
    "JPN": "JPY",
    "SGP": "SGD",
    "CHN": "CNY",
    "HKG": "HKD",
}

YEAR_RANGE = "1990:2030"
BASE_URL = "https://api.worldbank.org/v2/country/{iso}/indicator/{ind}"
API_ROOT = "https://api.worldbank.org/v2/"


def _url(iso: str, indicator: str) -> str:
    return f"{BASE_URL.format(iso=iso, ind=indicator)}?format=json&per_page=1000&date={YEAR_RANGE}"


class WorldBankAdapter:
    name = NAME
    dataset_keys = (f"WB-{GDP_IND}", f"WB-{FX_IND}")

    def fetch(self, client, raw_root: Path) -> list[Fetched]:
        results: list[Fetched] = []
        for indicator, label in (
            (GDP_IND, "GDP (current US$)"),
            (FX_IND, "Official exchange rate (LCU per US$, period average)"),
        ):
            items = []
            versions: set[str] = set()
            for iso in ECONOMIES:
                response = client.get(_url(iso, indicator))
                payload = json.loads(response.content)
                if not isinstance(payload, list) or len(payload) < 2:
                    raise ValueError(f"世界银行返回结构异常：{iso} / {indicator}")
                versions.add(str(payload[0].get("lastupdated", "unknown")))
                items.append((f"{iso}.json", response))

            version = max(versions)
            if len(versions) > 1:
                version = f"{max(versions)}"

            meta = SourceMeta(
                id=f"WB-{indicator}-{version}",
                dataset_key=f"WB-{indicator}",
                city_code=None,
                indicator=indicator,
                organization="World Bank",
                dataset_title=f"World Development Indicators — {label}",
                table_id=indicator,
                url=_url("CHN", indicator),
                vintage=version,
                published_at=version,
                notes=(
                    None
                    if len(versions) == 1
                    else f"各经济体 lastupdated 不一致：{sorted(versions)}，取最大"
                ),
            )
            results.append(commit_raw(raw_root, meta, items))
        return results

    def parse(self, fetched: Fetched) -> list[Fact]:
        indicator = fetched.meta.indicator
        facts: list[Fact] = []
        for path in fetched.files:
            iso = path.stem
            if iso not in ECONOMIES:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload[1] or []
            for row in rows:
                year = int(row["date"])
                value = row.get("value")
                if value is None or not (1990 <= year <= 2030):
                    continue
                if indicator == GDP_IND:
                    facts.append(
                        Fact(
                            entity_type="country",
                            entity_code=iso,
                            indicator="country_gdp_usd",
                            year=year,
                            value=float(value),
                            unit="USD",
                        )
                    )
                elif indicator == FX_IND:
                    facts.append(
                        Fact(
                            entity_type="currency",
                            entity_code=ECONOMIES[iso],
                            indicator="fx_lcu_per_usd",
                            year=year,
                            value=float(value),
                            unit="LCU per USD",
                        )
                    )
        return facts
