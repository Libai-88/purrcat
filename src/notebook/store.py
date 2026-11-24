"""研究文档的修订存储。

修订**不可变**，只追加；每次提交带上 `expected_revision`，对不上就报冲突而不是覆盖。
内容寻址：每个修订记着自己的文档摘要，可以回答「这份记录后来被改过吗」。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from src.notebook import document as doc

NOTEBOOKS_DIRNAME = "notebooks"
_REVISIONS_DIRNAME = "revisions"
_META_FILENAME = "meta.json"


class RevisionConflict(Exception):
    """修订号对不上。"""


class NotebookError(Exception):
    """笔记库操作失败。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _root() -> str:
    from src.utils.config import DATA_DIR

    return os.path.join(DATA_DIR, NOTEBOOKS_DIRNAME)


def _doc_dir(doc_id: str) -> str:
    return os.path.join(_root(), doc_id)


def _write_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _validate_doc_id(doc_id: str) -> str:
    if not doc_id or not doc.BLOCK_ID_RE.match(doc_id):
        raise NotebookError(f"笔记 id 不合法：{doc_id!r}")
    return doc_id


def latest_revision(doc_id: str) -> int:
    """当前最新修订号；没有笔记时是 0。"""
    meta = _read_json(os.path.join(_doc_dir(doc_id), _META_FILENAME))
    return int(meta.get("revision") or 0) if meta else 0


def commit(doc_id: str, document: dict, expected_revision: int | None = None) -> dict:
    """提交一次修订。

    expected_revision 与当前修订对不上时抛 RevisionConflict——不覆盖别人的改动。
    """
    doc_id = _validate_doc_id(doc_id)
    current = latest_revision(doc_id)
    if expected_revision is not None and int(expected_revision) != current:
        raise RevisionConflict(
            f"笔记 {doc_id} 已经改到第 {current} 版（你要提交的是第 {expected_revision} 版）"
        )

    validated = doc.validate_document(document)
    revision = current + 1
    record = {
        "doc_id": doc_id,
        "revision": revision,
        "updated_at": _now(),
        "digest": doc.document_digest(validated),
        "document": validated,
    }
    _write_json(
        os.path.join(_doc_dir(doc_id), _REVISIONS_DIRNAME, f"{revision:04d}.json"),
        record,
    )

    previous = _read_json(os.path.join(_doc_dir(doc_id), _META_FILENAME)) or {}
    meta = {
        "doc_id": doc_id,
        "title": validated["title"],
        "revision": revision,
        "digest": record["digest"],
        "updated_at": record["updated_at"],
        "created_at": previous.get("created_at") or record["updated_at"],
        "block_count": len(validated["blocks"]),
    }
    _write_json(os.path.join(_doc_dir(doc_id), _META_FILENAME), meta)
    return record


def read(doc_id: str, revision: int | None = None) -> dict:
    """读某一版修订；不给修订号就读最新版。"""
    doc_id = _validate_doc_id(doc_id)
    target = int(revision) if revision is not None else latest_revision(doc_id)
    if target <= 0:
        raise NotebookError(f"没有这份笔记：{doc_id}")
    record = _read_json(
        os.path.join(_doc_dir(doc_id), _REVISIONS_DIRNAME, f"{target:04d}.json")
    )
    if record is None:
        raise NotebookError(f"没有第 {target} 版修订：{doc_id}")
    return record


def list_documents() -> list[dict]:
    """列出所有笔记（按更新时间倒序）。"""
    root = _root()
    if not os.path.isdir(root):
        return []
    documents = []
    for name in sorted(os.listdir(root)):
        meta = _read_json(os.path.join(root, name, _META_FILENAME))
        if isinstance(meta, dict) and meta.get("doc_id"):
            documents.append(meta)
    documents.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return documents


def revision_history(doc_id: str, limit: int = 50) -> list[dict]:
    """修订历史（只列摘要，不列全文）。"""
    doc_id = _validate_doc_id(doc_id)
    folder = os.path.join(_doc_dir(doc_id), _REVISIONS_DIRNAME)
    if not os.path.isdir(folder):
        return []
    history = []
    for name in sorted(os.listdir(folder), reverse=True):
        if not name.endswith(".json"):
            continue
        record = _read_json(os.path.join(folder, name))
        if isinstance(record, dict):
            history.append(
                {
                    "revision": record.get("revision"),
                    "updated_at": record.get("updated_at"),
                    "digest": record.get("digest"),
                }
            )
        if len(history) >= limit:
            break
    return history
