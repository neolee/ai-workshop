"""适配器公共类型与原始数据落盘。

每个数据源一个 adapter，实现 fetch() 与 parse()：
  fetch  — 联网下载，写入 data/raw/<source_id>/，同时写 manifest.json
  parse  — 只读原始文件，产出一组规范化的 Fact（不联网）

manifest.json 保存了完整的 SourceMeta，因此 ingest 可以完全离线重跑。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Protocol

from ..http import Response


# ---------------------------------------------------------------- 数据类型

@dataclass(frozen=True)
class Fact:
    """一条规范化后的观测值（基本单位：本币元 / 人 / km² / 美元）。"""

    entity_type: str  # city | country | currency
    entity_code: str
    indicator: str
    year: int
    value: float
    unit: str
    status: str = "final"  # final | preliminary | provisional
    note: str | None = None


@dataclass(frozen=True)
class SourceMeta:
    """来源登记表所需的元数据（写入 source 表与 manifest）。"""

    id: str
    dataset_key: str  # 去掉版本号的前缀，用于清理旧版本 fact
    city_code: str | None
    indicator: str
    organization: str
    dataset_title: str
    table_id: str | None
    url: str
    vintage: str
    published_at: str | None = None
    acquisition: str = "auto"  # auto | manual
    notes: str | None = None


@dataclass
class Fetched:
    """一次抓取的产物：一个 source 目录 + 若干原始文件。"""

    meta: SourceMeta
    directory: Path
    files: list[Path] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)


# ---------------------------------------------------------------- 落盘

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def commit_raw(
    raw_root: Path,
    meta: SourceMeta,
    items: Iterable[tuple[str, Response]],
) -> Fetched:
    """把一次抓取的所有响应写成不可变原始数据 + manifest。

    同一 source_id 重复抓取会整体覆盖（幂等）；新版本请使用新的 source_id。
    """
    directory = raw_root / meta.id
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)

    files: list[Path] = []
    manifest_files: list[dict] = []
    responses: list[Response] = []
    for name, response in items:
        path = directory / name
        path.write_bytes(response.content)
        files.append(path)
        manifest_files.append(
            {"name": name, "sha256": _sha256(response.content), "bytes": len(response.content)}
        )
        responses.append(response)

    first = responses[0]
    manifest = {
        "source_id": meta.id,
        "dataset_key": meta.dataset_key,
        "meta": asdict(meta),
        "urls": [r.url for r in responses],
        "http_status": first.status,
        "etag": first.headers.get("etag"),
        "last_modified": first.headers.get("last-modified"),
        "fetched_at": first.fetched_at,
        "acquisition": meta.acquisition,
        "files": manifest_files,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return Fetched(meta=meta, directory=directory, files=files, manifest=manifest)


def load_manifest(directory: Path) -> dict:
    path = directory / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"缺少 manifest.json：{directory}")
    return json.loads(path.read_text(encoding="utf-8"))


def fetched_from_directory(directory: Path) -> Fetched:
    """从磁盘还原 Fetched，供离线 ingest 使用。"""
    manifest = load_manifest(directory)
    meta = SourceMeta(**manifest["meta"])
    files = [directory / f["name"] for f in manifest["files"]]
    missing = [p.name for p in files if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"{directory} 缺少原始文件：{missing}")
    return Fetched(meta=meta, directory=directory, files=files, manifest=manifest)


def latest_fetch(raw_root: Path, dataset_key: str) -> Fetched | None:
    """在 raw 下找某数据集的最新版本目录。"""
    if not raw_root.is_dir():
        return None
    candidates: list[tuple[str, Path]] = []
    for child in raw_root.iterdir():
        manifest_path = child / "manifest.json"
        if not child.is_dir() or not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("dataset_key") != dataset_key:
            continue
        candidates.append((manifest.get("fetched_at", ""), child))
    if not candidates:
        return None
    candidates.sort()
    return fetched_from_directory(candidates[-1][1])


# ---------------------------------------------------------------- 协议

class Adapter(Protocol):
    name: str
    dataset_keys: tuple[str, ...]

    def fetch(self, client, raw_root: Path) -> list[Fetched]: ...

    def parse(self, fetched: Fetched) -> list[Fact]: ...
