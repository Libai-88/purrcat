"""来源凭据：从哪来、什么时候取的、原始请求是什么、内容哈希是多少。

**凭据只说明出处，不说明可信。** 跟研究记录里的 `acceptance` 是两回事：
凭据里**没有** acceptance / verification 字段——「这批数据是从 arXiv 拉的」
不能推出「这批数据是对的」。

凭据不可篡改：写了就不改；重新拉一次是**新的一条**，不是覆盖旧的。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from src.utils._fs import read_json, write_json_atomic
from src.utils.config import DATA_DIR

PROVENANCE_DIRNAME = "provenance"
PROVENANCE_SCHEMA_VERSION = 1


def provenance_root() -> str:
    """来源凭据目录。"""
    return os.path.join(DATA_DIR, PROVENANCE_DIRNAME)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return "prov-" + uuid.uuid4().hex[:12]


def build(
    connector_id: str,
    request: dict,
    retrieved_at: str = "",
    content_sha256: str = "",
    content_bytes: int = 0,
    landed: str = "",
    landed_id: str = "",
    record_count: int = 0,
    source_refs: list[str] | None = None,
) -> dict:
    """组装一条来源凭据。

    ``request`` 是原始请求（查询词、条数、参数），要能让人重跑一遍。
    ``landed`` / ``landed_id`` 说明这份东西进了本机库的哪里。
    """
    return {
        "provenance_id": _new_id(),
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "connector_id": connector_id,
        "request": dict(request or {}),
        "retrieved_at": retrieved_at or _now(),
        "content_sha256": content_sha256,
        "content_bytes": int(content_bytes or 0),
        "landed": landed,
        "landed_id": landed_id,
        "record_count": int(record_count or 0),
        "source_refs": list(source_refs or []),
    }


def save(provenance: dict) -> dict:
    """落盘一条凭据。同一条不重复写。"""
    root = provenance_root()
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, str(provenance["provenance_id"]) + ".json")
    if not os.path.exists(path):
        write_json_atomic(path, provenance)
    return provenance


def get(provenance_id: str) -> dict | None:
    """读一条凭据。"""
    path = os.path.join(provenance_root(), str(provenance_id) + ".json")
    data = read_json(path, default=None)
    return data if isinstance(data, dict) else None


def list_all(connector_id: str = "", limit: int = 50) -> list[dict]:
    """列凭据，新的在前。"""
    root = provenance_root()
    if not os.path.isdir(root):
        return []
    items = []
    for name in os.listdir(root):
        if not name.endswith(".json"):
            continue
        data = read_json(os.path.join(root, name), default=None)
        if isinstance(data, dict) and data.get("provenance_id"):
            items.append(data)
    if connector_id:
        items = [item for item in items if item.get("connector_id") == connector_id]
    items.sort(key=lambda item: str(item.get("retrieved_at") or ""), reverse=True)
    return items[: max(0, int(limit))]


def for_landed(landed_id: str) -> dict | None:
    """按入库对象找它最近的那条凭据。"""
    for item in list_all(limit=200):
        if item.get("landed_id") == landed_id:
            return item
    return None
