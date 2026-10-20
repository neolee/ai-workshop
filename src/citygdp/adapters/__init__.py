"""数据源适配器注册表。"""

from __future__ import annotations

from .bea import BeaAdapter
from .beijing import BeijingAdapter
from .base import Adapter, Fact, Fetched, SourceMeta
from .census import CensusAdapter
from .hkcsd import HkCsdAdapter
from .ons import OnsAdapter
from .shanghai import ShanghaiAdapter
from .shenzhen import ShenzhenAdapter
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
    "shanghai": ShanghaiAdapter,
    "beijing": BeijingAdapter,
    "shenzhen": ShenzhenAdapter,
}

__all__ = ["ADAPTERS", "Adapter", "Fact", "Fetched", "SourceMeta"]
