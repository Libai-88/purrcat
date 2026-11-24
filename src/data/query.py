"""查询：过滤、排序、聚合，以及一条可引用的**查询收据**。

收据记录的是「这次查询读的是哪个数据集的哪一版、用的什么口径、得到多少行」，
并明确声明「单位与口径是声明，不是验证」。收据可以写进研究记录当作证据，
这样论文里的数字就能回指到具体的数据版本与查询口径上。

一条硬规则：**数字比较要求该字段已被显式解释为数字**。
在文本列上做 >= / <= 是口径错误，直接报错，不返回一个空结果。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone

from src.data import library
from src.data.inspect import (
    INTERPRETATION_NUMBER,
    KIND_EMPTY,
    KIND_MISSING,
    KIND_NULL,
    InspectionError,
)

RECEIPTS_DIRNAME = "receipts"

# 过滤算子
OPERATORS = ("contains", "eq", "gte", "lte", "missing", "null", "empty")
# 数值比较用的算子——要求字段已显式解释为数字
NUMERIC_OPERATORS = ("gte", "lte")

# 展示上限
MAX_COLUMNS = 32
MAX_ROWS = 100_000
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
# 聚合最多画几组
MAX_GROUPS = 50

# 收据的可信度状态——与研究记录同一套词表
ACCEPTANCE_NEEDS_REVIEW = "needs_review"


def receipts_root() -> str:
    return os.path.join(library.library_root(), RECEIPTS_DIRNAME)


def _now() -> str:
    # 微秒精度：同一秒内产生的多条收据也要能稳定排序
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _normalize_spec(spec: dict | None) -> dict:
    """整理查询口径；未知算子与非法列数直接拒收。"""
    spec = dict(spec or {})
    columns = spec.get("columns") or []
    if not isinstance(columns, list) or len(columns) > MAX_COLUMNS:
        raise InspectionError("invalid", f"一次最多选 {MAX_COLUMNS} 列")

    where = spec.get("filter") or None
    if where is not None:
        if not isinstance(where, dict):
            raise InspectionError("invalid", "过滤条件格式不对")
        operator = str(where.get("operator") or "")
        if operator not in OPERATORS:
            raise InspectionError("invalid", f"过滤算子只能是：{', '.join(OPERATORS)}")
        if operator not in ("missing", "null", "empty") and not where.get("field"):
            raise InspectionError("invalid", "这个过滤条件需要指定字段")

    order = spec.get("sort") or None
    if order is not None:
        if not isinstance(order, dict) or not order.get("field"):
            raise InspectionError("invalid", "排序需要指定字段")

    limit = spec.get("limit", DEFAULT_LIMIT)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise InspectionError("invalid", "limit 必须是整数") from None
    limit = max(1, min(limit, MAX_LIMIT))

    offset = int(spec.get("offset", 0) or 0)
    if offset < 0:
        raise InspectionError("invalid", "offset 不能为负")

    return {
        "columns": [str(item) for item in columns],
        "filter": where,
        "sort": order,
        "limit": limit,
        "offset": max(0, offset),
    }


def _matches(cell, operator: str, value) -> bool:
    """单格过滤。文本列上的数值比较在别处已拦掉。"""
    if operator == "missing":
        return cell is None
    if cell is None:
        return False
    if operator == "null":
        return cell.kind == KIND_NULL
    if operator == "empty":
        return cell.kind == KIND_EMPTY
    if operator == "contains":
        return str(value) in cell.display
    if operator == "eq":
        return cell.display == str(value)
    if operator in NUMERIC_OPERATORS:
        if cell.number is None:
            return False
        try:
            target = float(value)
        except (TypeError, ValueError):
            raise InspectionError("invalid", f"比较值不是数字：{value!r}") from None
        return cell.number >= target if operator == "gte" else cell.number <= target
    return False


def query_rows(inspection: dict, spec: dict | None = None) -> dict:
    """按口径过滤、排序、分页，返回命中的行与总数。"""
    spec = _normalize_spec(spec)
    rows = inspection["rows"]
    fields = inspection["fields"]
    interpretations = {
        item["name"]: item["interpretation"]
        for item in inspection["report"]["fields"]
        if item.get("interpretation")
    }

    where = spec["filter"]
    if where:
        field = str(where.get("field") or "")
        operator = str(where.get("operator"))
        if field and field not in fields:
            raise InspectionError("invalid", f"没有这个字段: {field}")
        if operator in NUMERIC_OPERATORS:
            if interpretations.get(field) != INTERPRETATION_NUMBER:
                raise InspectionError(
                    "invalid",
                    f"字段「{field}」是文本，不能做数值比较。"
                    "请先把这个字段显式解释为数字。",
                )
        rows = [
            row
            for row in rows
            if _matches(row.cells.get(field), operator, where.get("value"))
        ]

    order = spec["sort"]
    if order:
        field = str(order["field"])
        if field not in fields:
            raise InspectionError("invalid", f"没有这个字段: {field}")
        descending = bool(order.get("descending"))
        numeric = interpretations.get(field) == INTERPRETATION_NUMBER

        def _sort_key(row):
            cell = row.cells.get(field)
            if cell is None or cell.kind == KIND_MISSING:
                # 缺值一律排在最后，两种排序方向都一样
                return (1, "" if not numeric else 0.0)
            if numeric:
                return (0, cell.number if cell.number is not None else 0.0)
            return (0, cell.display)

        # 缺值永远排在最后，不随排序方向翻转
        present = [row for row in rows if _sort_key(row)[0] == 0]
        absent = [row for row in rows if _sort_key(row)[0] == 1]
        present.sort(key=lambda row: _sort_key(row)[1], reverse=descending)
        rows = present + absent

    total = len(rows)
    window = rows[spec["offset"] : spec["offset"] + spec["limit"]]
    columns = spec["columns"] or fields

    return {
        "spec": spec,
        "total": total,
        "matched": total,
        "offset": spec["offset"],
        "rows": [
            {
                "row": row.ordinal,
                "source_line": row.line,
                "cells": [
                    row.cells[name].to_dict()
                    if name in row.cells
                    else {"kind": KIND_MISSING, "text": ""}
                    for name in columns
                ],
            }
            for row in window
        ],
    }


def aggregate(
    inspection: dict, category: str, measure: str = "", aggregation: str = "count"
) -> dict:
    """按类目分组聚合；最多给出 50 组，其余计入 omitted。

    聚合口径是**声明**，不是检验——它不说明这个数字在科学上意味着什么。
    """
    fields = inspection["fields"]
    if category not in fields:
        raise InspectionError("invalid", f"没有这个字段: {category}")
    if aggregation not in ("sum", "count"):
        raise InspectionError("invalid", "聚合方式只能是 sum 或 count")
    if aggregation == "sum":
        if measure not in fields:
            raise InspectionError("invalid", f"没有这个字段: {measure}")
        interpreted = {
            item["name"]: item["interpretation"]
            for item in inspection["report"]["fields"]
            if item.get("interpretation")
        }
        if interpreted.get(measure) != INTERPRETATION_NUMBER:
            raise InspectionError(
                "invalid",
                f"字段「{measure}」是文本，不能求和。请先显式解释为数字。",
            )

    groups: dict[str, dict] = {}
    for row in inspection["rows"]:
        cell = row.cells.get(category)
        key = cell.display if cell is not None and cell.kind != KIND_MISSING else ""
        group = groups.setdefault(key, {"label": key, "value": 0, "count": 0})
        group["count"] += 1
        if aggregation == "sum":
            number_cell = row.cells.get(measure)
            if number_cell is not None and number_cell.number is not None:
                group["value"] += number_cell.number

    ordered = sorted(groups.values(), key=lambda item: (-item["value"], item["label"]))
    shown = ordered[:MAX_GROUPS]
    omitted = len(ordered) - len(shown)
    for group in shown:
        if aggregation == "count":
            group["value"] = group["count"]
        group["value"] = float(group["value"])
    return {
        "category": category,
        "measure": measure,
        "aggregation": aggregation,
        "groups": shown,
        "omitted_groups": omitted,
        "group_count": len(groups),
    }


def build_receipt(
    dataset: dict,
    asset: dict,
    question: str,
    spec: dict,
    result: dict,
    unit: str = "",
    grain: str = "",
    denominator: str = "",
    elapsed_seconds: float = 0.0,
) -> dict:
    """组装一条查询收据。"""
    return {
        "query_id": "q-" + uuid.uuid4().hex[:12],
        "dataset_id": dataset["id"],
        "asset_id": asset["id"],
        "sha256": asset.get("sha256"),
        "question": question.strip(),
        "spec": spec,
        "unit": unit.strip(),
        "grain": grain.strip(),
        "denominator": denominator.strip(),
        "status": "completed",
        "row_count": result.get("total"),
        "row_count_returned": len(result.get("rows") or []),
        "elapsed_seconds": round(elapsed_seconds, 4),
        "acceptance": ACCEPTANCE_NEEDS_REVIEW,
        "created_at": _now(),
    }


def save_receipt(receipt: dict) -> dict:
    """落盘收据；同名收据不重复写。"""
    root = receipts_root()
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, str(receipt["query_id"]) + ".json")
    if not os.path.exists(path):
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    return receipt


def get_receipt(query_id: str) -> dict | None:
    path = os.path.join(receipts_root(), str(query_id) + ".json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def list_receipts() -> list[dict]:
    """列出查询收据，按时间倒序。"""
    root = receipts_root()
    if not os.path.isdir(root):
        return []
    receipts = []
    for name in sorted(os.listdir(root)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(root, name), "r", encoding="utf-8") as handle:
                receipts.append(json.load(handle))
        except (OSError, ValueError):
            continue
    receipts.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return receipts


def run_query(
    dataset_id: str,
    asset_id: str = "",
    question: str = "",
    spec: dict | None = None,
    interpretations: dict[str, str] | None = None,
    unit: str = "",
    grain: str = "",
    denominator: str = "",
) -> dict:
    """跑一次查询并留下收据。"""
    from src.data import inspect as inspect_module

    resolved = library.resolve_version(dataset_id, asset_id)
    asset = resolved["asset"]
    if not library.can_inspect(asset):
        raise InspectionError("unsupported", "这个文件不是表格，只保存了原件，无法查询")

    started = time.time()
    inspection = inspect_module.inspect_asset(asset, interpretations or {})
    if interpretations:
        inspection = inspect_module.apply_interpretations(inspection, interpretations)
    result = query_rows(inspection, spec)
    elapsed = time.time() - started

    receipt = build_receipt(
        resolved["dataset"],
        asset,
        question,
        result["spec"],
        result,
        unit=unit,
        grain=grain,
        denominator=denominator,
        elapsed_seconds=elapsed,
    )
    save_receipt(receipt)
    return {"receipt": receipt, "result": result}
