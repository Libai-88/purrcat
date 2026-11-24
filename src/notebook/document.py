"""研究文档模型：一份规范树，块承载证据。

设计取自 Pero 的不变量，但按 PurrCat 的形态落地：

* **一份规范树**——文档是块的有序列表，Markdown / HTML 都是投影，不单独存储。
* **证据是块的一等公民**——`evidence` 块引用论文原文（逐字校验），
  `data` 块引用一条查询收据，`finding` 块引用本文件里的证据块。
* **三层身份**——块 id（文档内）、属主对象 id（论文 / 收据）、版本（commit / 收据本身）分开记。
* **钉住 ≠ 验证**——每份文档带 acceptance，取值封闭。
* **未知 ≠ 可删**——不认识的结构要么包进保留信封，要么整篇只读并挂横幅。

模型只在这里实现一份。面板是投影，后端是权威。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid

from src.papers import library as paper_library
from src.papers import records as paper_records

SCHEMA_VERSION = 1

# 上限（与 Pero 的量级相当，但按 PurrCat 的实际需要收窄）
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_TITLE = 200
MAX_TEXT = 32_768
MAX_BLOCKS = 400
MAX_TABLE_ROWS = 200
MAX_TABLE_COLUMNS = 50
MAX_CELL_LENGTH = 4096
MAX_EVIDENCE_PER_FINDING = 100

BLOCK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CELL_ADDRESS_RE = re.compile(r"^([A-Z]{1,2})([1-9][0-9]{0,2})$")

# 块种类
BLOCK_TEXT = "text"
BLOCK_HEADING = "heading"
BLOCK_EVIDENCE = "evidence"
BLOCK_DATA = "data"
BLOCK_TABLE = "table"
BLOCK_FINDING = "finding"

BLOCK_KINDS = (
    BLOCK_TEXT,
    BLOCK_HEADING,
    BLOCK_EVIDENCE,
    BLOCK_DATA,
    BLOCK_TABLE,
    BLOCK_FINDING,
)

# 需要块 id 的种类（身份三层里第一层）
_BLOCKS_WITH_ID = (BLOCK_EVIDENCE, BLOCK_DATA, BLOCK_TABLE, BLOCK_FINDING)

# 文档可信度（封闭词表，与研究记录同一套）
ACCEPTANCE_UNVERIFIED = "unverified"
ACCEPTANCE_NEEDS_REVIEW = "needs_review"
ACCEPTANCE_ACCEPTED = "accepted"
ACCEPTANCE_REJECTED = "rejected"

ACCEPTANCE_VALUES = (
    ACCEPTANCE_UNVERIFIED,
    ACCEPTANCE_NEEDS_REVIEW,
    ACCEPTANCE_ACCEPTED,
    ACCEPTANCE_REJECTED,
)

# 结论相对证据的立场
STANCE_SUPPORT = "support"
STANCE_COUNTEREVIDENCE = "counterevidence"
STANCE_GAP = "gap"

STANCE_VALUES = (STANCE_SUPPORT, STANCE_COUNTEREVIDENCE, STANCE_GAP)


class DocumentError(Exception):
    """文档不合法。"""


def _text(value, field: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise DocumentError(f"{field} 必须是字符串")
    if len(value) > limit:
        raise DocumentError(f"{field} 超过 {limit} 字符上限")
    return value


def _id_list(value, field: str, limit: int = MAX_EVIDENCE_PER_FINDING) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DocumentError(f"{field} 必须是列表")
    if len(value) > limit:
        raise DocumentError(f"{field} 超过 {limit} 条上限")
    result = []
    for item in value:
        if not isinstance(item, str) or not BLOCK_ID_RE.match(item):
            raise DocumentError(f"{field} 里的块 id 不合法：{item!r}")
        if item in result:
            raise DocumentError(f"{field} 里有重复的块 id：{item}")
        result.append(item)
    return result


def _validate_evidence(attrs: dict) -> dict:
    """证据块：引文必须逐字出现在论文那一页。"""
    paper_id = str(attrs.get("paper_id") or "").strip()
    if not paper_id:
        raise DocumentError("证据块缺少 paper_id")
    if paper_library.get_paper(paper_id) is None:
        raise DocumentError(f"论文库里没有这篇论文：{paper_id}")
    try:
        page = int(attrs.get("page"))
    except (TypeError, ValueError):
        raise DocumentError("证据块页码不合法") from None
    quote = _text(attrs.get("quote") or "", "证据块引文")
    if not quote.strip():
        raise DocumentError("证据块引文不能为空")
    located = paper_records._check_quote(paper_id, page, quote)
    return {
        "paper_id": paper_id,
        "page": page,
        "quote": quote,
        "verification": located["verification"],
        "candidates": located["candidates"],
        "label": str(attrs.get("label") or ""),
    }


def _validate_data(attrs: dict) -> dict:
    """数据块：引用的查询收据必须存在且跑完了。"""
    from src.data import query as query_module

    receipt_id = str(attrs.get("receipt_id") or "").strip()
    if not receipt_id:
        raise DocumentError("数据块缺少 receipt_id")
    receipt = query_module.get_receipt(receipt_id)
    if receipt is None:
        raise DocumentError(f"没有这条查询收据：{receipt_id}")
    if receipt.get("status") != "completed":
        raise DocumentError(
            f"这条查询收据没有跑完（{receipt.get('status')}），不能当证据：{receipt_id}"
        )
    return {
        "receipt_id": receipt_id,
        "dataset_id": receipt.get("dataset_id", ""),
        "asset_id": receipt.get("asset_id", ""),
        "sha256": receipt.get("sha256", ""),
        "question": receipt.get("question", ""),
        "unit": receipt.get("unit", ""),
        "grain": receipt.get("grain", ""),
        "denominator": receipt.get("denominator", ""),
        "row_count": receipt.get("row_count"),
        "summary": receipt.get("summary") or {},
        "label": str(attrs.get("label") or ""),
    }


def _validate_table(attrs: dict) -> dict:
    """表格块：存的是公式源码，不是算出来的值。"""
    sheet = attrs.get("sheet") or {}
    if not isinstance(sheet, dict):
        raise DocumentError("表格块的 sheet 必须是对象")
    try:
        rows = int(sheet.get("rows") or 0)
        columns = int(sheet.get("columns") or 0)
    except (TypeError, ValueError):
        raise DocumentError("表格块的行列数不合法") from None
    if rows < 0 or columns < 0:
        raise DocumentError("表格块的行列数不能为负")
    if rows > MAX_TABLE_ROWS or columns > MAX_TABLE_COLUMNS:
        raise DocumentError(
            f"表格超过上限（{MAX_TABLE_ROWS} 行 / {MAX_TABLE_COLUMNS} 列）"
        )
    cells = sheet.get("cells") or {}
    if not isinstance(cells, dict):
        raise DocumentError("表格块的 cells 必须是对象")
    clean_cells = {}
    for address, value in cells.items():
        if not CELL_ADDRESS_RE.match(str(address)):
            raise DocumentError(f"单元格地址不合法：{address!r}")
        text = _text(
            value if isinstance(value, str) else str(value), "单元格", MAX_CELL_LENGTH
        )
        clean_cells[str(address)] = text
    return {
        "label": str(attrs.get("label") or ""),
        "sheet": {
            "rows": rows,
            "columns": columns,
            "cells": clean_cells,
        },
        "annotations": attrs.get("annotations") or {},
        "column_names": attrs.get("column_names") or {},
    }


def _validate_finding(attrs: dict) -> dict:
    """结论块：只能引用本文件里的证据块。"""
    claim = _text(attrs.get("claim") or "", "结论正文")
    if not claim.strip():
        raise DocumentError("结论正文不能为空")
    limitations = _text(attrs.get("limitations") or "", "结论的局限说明")
    stance = str(attrs.get("stance") or STANCE_SUPPORT)
    if stance not in STANCE_VALUES:
        raise DocumentError(f"结论立场取值非法：{stance!r}")
    return {
        "claim": claim,
        "limitations": limitations,
        "stance": stance,
        "evidence_ids": _id_list(attrs.get("evidence_ids"), "结论的证据列表"),
    }


_VALIDATORS = {
    BLOCK_TEXT: lambda attrs: {"text": _text(attrs.get("text") or "", "正文")},
    BLOCK_HEADING: lambda attrs: {
        "text": _text(attrs.get("text") or "", "标题"),
        "level": int(attrs.get("level") or 1),
    },
    BLOCK_EVIDENCE: _validate_evidence,
    BLOCK_DATA: _validate_data,
    BLOCK_TABLE: _validate_table,
    BLOCK_FINDING: _validate_finding,
}


def validate_block(raw: dict) -> dict:
    """校验并规范化一个块。"""
    if not isinstance(raw, dict):
        raise DocumentError("块必须是对象")
    kind = str(raw.get("kind") or "").strip()
    if kind not in BLOCK_KINDS:
        raise DocumentError(f"未知的块类型：{kind!r}")
    attrs = raw.get("attrs") or {}
    if not isinstance(attrs, dict):
        raise DocumentError("块的 attrs 必须是对象")
    try:
        clean = _VALIDATORS[kind](attrs)
    except DocumentError:
        raise
    except Exception as exc:
        # 证据校验、数据收据校验住在各自的领域模块里；文档模型统一抛自己的错误，
        # 调用方不必知道是哪一层在拒收。
        raise DocumentError(str(exc)) from exc
    if kind == BLOCK_HEADING:
        level = clean["level"]
        if level < 1 or level > 6:
            raise DocumentError("标题层级必须在 1 到 6 之间")
    block = {"kind": kind, "attrs": clean}
    if kind in _BLOCKS_WITH_ID:
        block_id = str(raw.get("block_id") or "").strip()
        if not BLOCK_ID_RE.match(block_id):
            raise DocumentError(f"块 id 不合法：{block_id!r}")
        block["block_id"] = block_id
    return block


def validate_document(raw: dict) -> dict:
    """校验并规范化一份文档。"""
    if not isinstance(raw, dict):
        raise DocumentError("文档必须是对象")
    version = int(raw.get("schema_version") or 0)
    if version != SCHEMA_VERSION:
        raise DocumentError(f"文档 schema 版本必须是 {SCHEMA_VERSION}")

    title = _text(str(raw.get("title") or ""), "标题", MAX_TITLE)
    blocks_raw = raw.get("blocks") or []
    if not isinstance(blocks_raw, list):
        raise DocumentError("blocks 必须是列表")
    if len(blocks_raw) > MAX_BLOCKS:
        raise DocumentError(f"块数量超过 {MAX_BLOCKS} 上限")

    blocks = []
    seen_ids = set()
    for item in blocks_raw:
        block = validate_block(item)
        block_id = block.get("block_id")
        if block_id:
            if block_id in seen_ids:
                raise DocumentError(f"块 id 重复：{block_id}")
            seen_ids.add(block_id)
        blocks.append(block)

    # 结论只能引用本文件里的证据块
    for block in blocks:
        if block["kind"] != BLOCK_FINDING:
            continue
        for evidence_id in block["attrs"]["evidence_ids"]:
            target = next(
                (item for item in blocks if item.get("block_id") == evidence_id), None
            )
            if target is None:
                raise DocumentError(f"结论引用的证据块不在本文件里：{evidence_id}")
            if target["kind"] not in (BLOCK_EVIDENCE, BLOCK_DATA):
                raise DocumentError(
                    f"结论只能引用证据块或数据块：{evidence_id} 是 {target['kind']} 块"
                )

    acceptance = str(raw.get("acceptance") or ACCEPTANCE_UNVERIFIED)
    if acceptance not in ACCEPTANCE_VALUES:
        raise DocumentError(f"文档可信度取值非法：{acceptance!r}")

    document = {
        "schema_version": SCHEMA_VERSION,
        "title": title,
        "blocks": blocks,
        "acceptance": acceptance,
        "notes": _text(str(raw.get("notes") or ""), "备注"),
    }
    return document


def document_digest(document: dict) -> str:
    """文档内容摘要，作为修订的内容寻址标识。"""
    payload = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def new_block_id() -> str:
    return uuid.uuid4().hex[:16]


def find_block(document: dict, block_id: str) -> dict | None:
    """按 id 找块。"""
    for block in document.get("blocks") or []:
        if block.get("block_id") == block_id:
            return block
    return None


def new_document(title: str = "未命名笔记") -> dict:
    """建一份空文档。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "title": title[:MAX_TITLE],
        "blocks": [],
        "acceptance": ACCEPTANCE_UNVERIFIED,
        "notes": "",
    }
