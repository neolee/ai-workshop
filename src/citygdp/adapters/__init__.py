"""数据源适配器注册表。"""

from __future__ import annotations

from .bea import BeaAdapter
from .base import Adapter, Fact, Fetched, SourceMeta
from .census import CensusAdapter
from .hkcsd import HkCsdAdapter
from .ons import OnsAdapter
from .singstat import SingStatAdapter
from .tokyo import TokyoAdapter
from .worldbank import WorldBankAdapter

ADAPTERS: dict[str, type] = {
    "worldbank": WorldBankAdapter,
    "singstat": SingStatAdapter,
    "hkcsd": HkCsdAdapter,
    "bea": BeaAdapter,
    "census": CensusAdapter,
    "ons": OnsAdapter,
    "tokyo": TokyoAdapter,
}

__all__ = ["ADAPTERS", "Adapter", "Fact", "Fetched", "SourceMeta"]
