"""数据集库：一个逻辑数据集由若干**不可变版本**组成。

版本是原始文件本身，导入后不��改；数据集只是版本的容器。
「可用性」是三态（present / changed / missing），按文件大小判断，不是内容哈希——
内容哈希只在检查时重算，用来确认「拿到的还是当初那一份」。

这里不做任何缓存预览：原文件变了或没了，就明确报错，绝不用旧数据糊弄。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone

from src.utils.config import DATA_ROOT

LIBRARY_DIRNAME = "data"
FILES_DIRNAME = "files"
CATALOG_FILENAME = "catalog.json"

# 可被检查（能当成表格读）的格式
TABULAR_FORMATS = ("csv", "tsv", "json", "jsonl", "ndjson")
# 只存下来不解析的格式（模型权重、二进制等）
OPAQUE_FORMATS = ("xlsx", "xls", "h5ad", "pkl", "pt", "onnx", "joblib", "npy")

# 导入与检查的上限
MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_FIELDS = 256
MAX_ROWS = 100_000
MAX_FIELD_NAME = 300

# 可用性三态
AVAILABLE_PRESENT = "present"
AVAILABLE_CHANGED = "changed"
AVAILABLE_MISSING = "missing"

_DATASET_ID_RE = re.compile(r"^ds-[a-f0-9]{12}$")
_ASSET_ID_RE = re.compile(r"^av-[a-f0-9]{12}$")


class DataError(Exception):
    """数据集操作失败。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def library_root() -> str:
    """数据集库根目录。"""
    return os.path.join(DATA_ROOT, LIBRARY_DIRNAME)


def files_root() -> str:
    """原始文件目录；每个版本一个文件，内容寻址。"""
    return os.path.join(library_root(), FILES_DIRNAME)


def catalog_path() -> str:
    return os.path.join(library_root(), CATALOG_FILENAME)


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_json(path: str, payload) -> None:
    """原子写：先写临时文件再替换，避免读到写一半的目录。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def load_catalog() -> dict:
    """读取目录。坏了就当空目录，不让一次损坏挡住整个功能。"""
    catalog = _read_json(catalog_path())
    if not isinstance(catalog, dict):
        return {"schema_version": 1, "datasets": [], "assets": {}}
    catalog.setdefault("schema_version", 1)
    catalog.setdefault("datasets", [])
    catalog.setdefault("assets", {})
    return catalog


def save_catalog(catalog: dict) -> None:
    _write_json(catalog_path(), catalog)


def asset_format(name: str) -> str:
    """按扩展名判断格式。"""
    suffix = os.path.splitext(name or "")[1].lstrip(".").lower()
    return suffix or "binary"


def can_inspect(asset: dict) -> bool:
    """这个版本能不能当成表格读。"""
    return (
        asset.get("kind") == "dataset"
        and str(asset.get("format", "")).lower() in TABULAR_FORMATS
    )


def availability(asset: dict) -> str:
    """原文件当前的三态可用性；按大小判断，不重算哈希。"""
    path = os.path.join(files_root(), str(asset.get("id", "")))
    if os.path.islink(path) or not os.path.isfile(path):
        return AVAILABLE_MISSING
    try:
        if os.path.getsize(path) != int(asset.get("size") or 0):
            return AVAILABLE_CHANGED
    except OSError:
        return AVAILABLE_MISSING
    return AVAILABLE_PRESENT


def file_digest(path: str) -> str:
    """流式算 sha256，避免大文件占内存。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_dataset(
    source_path: str,
    name: str = "",
    kind: str = "dataset",
    source: str = "",
    license_name: str = "",
    project_ref: str = "",
    dataset_id: str = "",
) -> dict:
    """导入一个文件。

    给了 dataset_id 就是给该数据集**追加一个版本**；不给就是新建数据集。
    同名文件也各自成独立数据集——只有显式「加版本」才会归到一起。
    """
    path = os.path.abspath(os.path.expanduser(source_path))
    if not os.path.isfile(path):
        raise DataError(f"找不到文件: {source_path}")
    if kind not in ("dataset", "model"):
        raise DataError("类型只能是 dataset 或 model")

    size = os.path.getsize(path)
    if size <= 0:
        raise DataError("文件是空的")
    if size > MAX_IMPORT_BYTES:
        raise DataError(f"文件超过导入上限（{MAX_IMPORT_BYTES // (1024 * 1024)} MiB）")

    display_name = (name or os.path.basename(path)).strip()
    if (
        not display_name
        or display_name in (".", "..")
        or "/" in display_name
        or "\\" in display_name
    ):
        raise DataError("请给一个文件名，不要给路径")

    catalog = load_catalog()
    assets = catalog["assets"]

    asset_id = "av-" + uuid.uuid4().hex[:12]
    digest = file_digest(path)
    asset = {
        "id": asset_id,
        "name": display_name,
        "kind": kind,
        "format": asset_format(display_name),
        "size": size,
        "source": source or "本机文件",
        "revision": digest[:12],
        "license": license_name or "未知",
        "sha256": digest,
        "created_at": _now(),
        "checksums": [
            {"algorithm": "sha256", "value": digest, "provenance": "导入时计算"}
        ],
    }

    # 先把文件搬进库里，再更新目录——搬失败不留半个数据集
    os.makedirs(files_root(), exist_ok=True)
    staged = os.path.join(files_root(), asset_id + ".part")
    try:
        shutil.copyfile(path, staged)
        target = os.path.join(files_root(), asset_id)
        os.replace(staged, target)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)

    if dataset_id:
        dataset = _find_dataset(catalog, dataset_id)
        if dataset is None:
            raise DataError(f"没有这个数据集: {dataset_id}")
        if dataset.get("archived"):
            raise DataError("数据集已归档，先恢复再添加版本")
        if dataset.get("kind") != kind:
            raise DataError("新版本必须与数据集同类型")
        dataset["versions"] = list(dataset.get("versions") or []) + [asset_id]
    else:
        dataset = {
            "id": "ds-" + uuid.uuid4().hex[:12],
            "name": display_name,
            "kind": kind,
            "versions": [asset_id],
            "project_ref": project_ref.strip(),
            "archived": False,
        }
        catalog["datasets"].append(dataset)

    assets[asset_id] = asset
    save_catalog(catalog)
    return {"asset": asset, "dataset": dataset}


def _find_dataset(catalog: dict, dataset_id: str):
    for dataset in catalog.get("datasets") or []:
        if dataset.get("id") == dataset_id:
            return dataset
    return None


def list_datasets(include_archived: bool | None = False) -> list[dict]:
    """列出数据集，带上每个版本的可用性。

    include_archived 为 None 表示不按归档状态过滤。
    """
    catalog = load_catalog()
    assets = catalog["assets"]
    result = []
    for dataset in catalog.get("datasets") or []:
        if (
            include_archived is not None
            and bool(dataset.get("archived")) != include_archived
        ):
            continue
        versions = []
        for asset_id in dataset.get("versions") or []:
            asset = assets.get(asset_id)
            if not asset:
                continue
            versions.append({**asset, "availability": availability(asset)})
        result.append(
            {
                **dataset,
                "version_count": len(versions),
                # versions 保持 id 列表；富化后的明细另放在 version_details，
                # 免得把「这个数据集有哪些版本」这个信息本身覆盖掉
                "version_details": versions,
                "latest": versions[-1] if versions else None,
            }
        )
    return result


def get_dataset(dataset_id: str) -> dict | None:
    """取一个数据集及其版本。"""
    for dataset in list_datasets(include_archived=None):
        if dataset["id"] == dataset_id:
            return dataset
    return None


def get_asset(asset_id: str) -> dict | None:
    """取一个版本；带上可用性。"""
    asset = load_catalog()["assets"].get(asset_id)
    if not asset:
        return None
    return {**asset, "availability": availability(asset)}


def resolve_version(dataset_id: str, asset_id: str = "") -> dict:
    """解析要读的那一版；不给 asset_id 就取最新版。"""
    dataset = get_dataset(dataset_id)
    if dataset is None:
        raise DataError(f"没有这个数据集: {dataset_id}")
    versions = dataset.get("versions") or []
    if not versions:
        raise DataError("这个数据集还没有任何版本")
    target = asset_id or versions[-1]
    if target not in versions:
        raise DataError(f"这个数据集没有版本 {target}")
    asset = get_asset(target)
    if asset is None:
        raise DataError(f"版本记录缺失: {target}")
    return {"dataset": dataset, "asset": asset}


def read_asset_bytes(asset: dict) -> bytes:
    """读原文件字节；只在检查时读，并核对哈希。"""
    state = asset.get("availability")
    if state == AVAILABLE_MISSING:
        raise DataError("原文件已丢失，无法读取，也不会用旧数据代替")
    if state == AVAILABLE_CHANGED:
        raise DataError("原文件大小已变，无法读取，也不会用旧数据代替")
    path = os.path.join(files_root(), str(asset["id"]))
    try:
        with open(path, "rb") as handle:
            content = handle.read(MAX_IMPORT_BYTES + 1)
    except OSError as exc:
        raise DataError(f"读取原文件失败: {exc}") from exc
    if len(content) != int(asset.get("size") or 0):
        raise DataError("原文件大小与登记的不一致")
    if hashlib.sha256(content).hexdigest() != asset.get("sha256"):
        raise DataError("原文件内容与登记的 SHA-256 不一致")
    return content


def set_archived(dataset_id: str, archived: bool) -> dict:
    """归档或恢复一个数据集。"""
    catalog = load_catalog()
    dataset = _find_dataset(catalog, dataset_id)
    if dataset is None:
        raise DataError(f"没有这个数据集: {dataset_id}")
    dataset["archived"] = bool(archived)
    save_catalog(catalog)
    return dataset


def version_label(dataset: dict, asset_id: str) -> str:
    """版本号由位置推导：第一个版本是 v1。"""
    versions = dataset.get("versions") or []
    if asset_id in versions:
        return f"v{versions.index(asset_id) + 1}"
    return "—"
