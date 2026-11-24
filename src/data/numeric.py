"""数字比对：把论文原文里的数字与数据查询收据里的数字对上。

只做**字面比对**，不做科学判断：
两个数字相等，只说明「论文里写的那个数和这张表算出来的一样」，
不说明这个数在科学上是对的，也不说明口径没有偷换。

单位与口径仍然是**声明**。比对结果只回答「字面上对不对得上」。
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# 数值：可选负号、小数、指数
_NUMERIC = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
# 后面跟的百分号与单位（cm2、mg/dL、µg…）
_SUFFIX = r"(?:\s*(?:%|[a-zA-Zµμ°][a-zA-Z0-9²³²/^·\-]{0,7}))?"

_NUMBER_RE = re.compile(
    r"(?<![\w.])(" + _NUMERIC + r")(" + _SUFFIX + r")",
)

# 绝对容差，与查询复算用的容差一致
ABSOLUTE_TOLERANCE = Decimal("0.000001")
# 相对容差：数值大时按比例比
RELATIVE_TOLERANCE = Decimal("0.000001")

# 比对状态
MATCHED = "matched"
MISMATCHED = "mismatch"
UNRESOLVED = "unresolved"
NOT_APPLICABLE = "not_applicable"


def _to_decimal(text: str) -> Decimal | None:
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def extract_numbers(text: str) -> list[dict]:
    """从文本里抽出数字。

    每个数字带原始写法、是否百分号，以及一个归一化后的值：
    百分号会被换算成比例（12% → 0.12），这样 12% 和 0.12 能对上。
    """
    found: list[dict] = []
    for match in _NUMBER_RE.finditer(text or ""):
        raw = match.group(1)
        suffix = (match.group(2) or "").strip()
        value = _to_decimal(raw)
        if value is None:
            continue
        is_percent = suffix == "%"
        normalized = value / Decimal(100) if is_percent else value
        found.append(
            {
                "raw": raw,
                "suffix": suffix,
                "percent": is_percent,
                "value": value,
                "normalized": normalized,
            }
        )
    return found


def _close(left: Decimal, right: Decimal) -> bool:
    """两个数是否在容差内相等。"""
    if left == right:
        return True
    if abs(left - right) <= ABSOLUTE_TOLERANCE:
        return True
    scale = max(abs(left), abs(right))
    return scale > 0 and abs(left - right) / scale <= RELATIVE_TOLERANCE


def _same_number(left: dict, right: dict) -> tuple[bool, str]:
    """判断两个数字是否指同一个量，返回 (是否相同, 说明)。"""
    if _close(left["normalized"], right["normalized"]):
        note = ""
        if left["percent"] != right["percent"]:
            note = "比例写法不同"
        return True, note
    # 12% 与 12 指向不同的量——一个比例一个原值，不算对得上
    if left["percent"] != right["percent"]:
        return False, "一个写成百分比、一个是原值，比例不同"
    return False, ""


def compare_with_summary(paper_text: str, summary: dict | None) -> dict:
    """把论文原文里的数字与查询收据的摘要做字面比对。

    summary 是收据里的数字集合，形如：
        {"kind": "aggregate", "values": {"A": 90, "B": 75}}
        {"kind": "rows", "row_count": 128}
    """
    paper_numbers = extract_numbers(paper_text)
    if not paper_numbers:
        return {
            "status": NOT_APPLICABLE,
            "matched": [],
            "unmatched_paper": [],
            "notes": ["原文里没有可比的数字"],
            "method": "字面数值比对；单位与口径是声明，不是验证。",
        }

    values: list[dict] = []
    if summary and summary.get("kind") == "aggregate":
        for label, value in (summary.get("values") or {}).items():
            decimal = _to_decimal(str(value))
            if decimal is None:
                continue
            values.append(
                {
                    "label": label,
                    "raw": str(value),
                    "percent": False,
                    "value": decimal,
                    "normalized": decimal,
                }
            )
    elif summary and summary.get("kind") == "rows":
        count = _to_decimal(str(summary.get("row_count") or 0))
        if count is not None:
            values.append(
                {
                    "label": "行数",
                    "raw": str(count),
                    "percent": False,
                    "value": count,
                    "normalized": count,
                }
            )

    if not values:
        return {
            "status": NOT_APPLICABLE,
            "matched": [],
            "unmatched_paper": [item["raw"] for item in paper_numbers],
            "notes": ["这条数据收据里没有可比的数值"],
            "method": "字面数值比对；单位与口径是声明，不是验证。",
        }

    matched = []
    unmatched_paper = []
    notes: list[str] = []
    used = set()

    for paper in paper_numbers:
        found = False
        for index, value in enumerate(values):
            if index in used:
                continue
            same, note = _same_number(paper, value)
            if same:
                used.add(index)
                matched.append(
                    {
                        "paper": paper["raw"],
                        "paper_suffix": paper["suffix"],
                        "data": value["raw"],
                        "data_label": value["label"],
                        "note": note,
                    }
                )
                if note:
                    notes.append(f"{paper['raw']} 与 {value['raw']}：{note}")
                found = True
                break
        if not found:
            unmatched_paper.append(paper["raw"])

    unmatched_data = [
        value["label"] for index, value in enumerate(values) if index not in used
    ]

    if matched and not unmatched_paper and not unmatched_data:
        status = MATCHED
    elif matched:
        status = UNRESOLVED
    else:
        status = MISMATCHED

    if status == MISMATCHED:
        notes.append("原文里的数字与这次查询的结果对不上")
    elif status == UNRESOLVED:
        notes.append("部分数字对得上，其余没有对应")

    return {
        "status": status,
        "matched": matched,
        "unmatched_paper": unmatched_paper,
        "unmatched_data": unmatched_data,
        "notes": notes,
        "method": "字面数值比对；单位与口径是声明，不是验证。",
    }
