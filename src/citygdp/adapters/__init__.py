"""数据源适配器注册表。"""

from __future__ import annotations

from .base import Adapter, Fact, Fetched, SourceMeta
from .hkcsd import HkCsdAdapter
from .singstat import SingStatAdapter
from .worldbank import WorldBankAdapter

ADAPTERS: dict[str, type] = {
    "worldbank": WorldBankAdapter,
    "singstat": SingStatAdapter,
    "hkcsd": HkCsdAdapter,
}

__all__ = ["ADAPTERS", "Adapter", "Fact", "Fetched", "SourceMeta"]
