"""检查：把一个版本读成表格，给出字段画像与质量报告。

三条硬规则，都是为了不让数据在转述中失真：

1. CSV / TSV 的值一律当**文本**，不猜类型、不猜单位。`001` 就是 `001`。
   只有用户显式把这个字段「解释为数字」时才转，转的是这一列，不是整表。
2. 转换失败的值**保留原文**，并单独标为转换失败——绝不变成 0、也绝不变 null。
3. **缺字段、显式 null、空字符串、转换失败**是四件不同的事，分开计数。
   混成「没有数据」就等于把问题藏起来了。
"""

from __future__ import annotations

import csv
import io
import json
import re
from decimal import Decimal, InvalidOperation

from src.data import library

PARSER_VERSION = "purrcat-data/1"

# 单元格 kinds
KIND_MISSING = "missing"
KIND_NULL = "null"
KIND_EMPTY = "empty"
KIND_STRING = "string"
KIND_NUMBER = "number"
KIND_BOOLEAN = "boolean"

# 严格的十进制字面量：不认千分位、不认本地化、不剥空白
_NUMBER_RE = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")

# 字段解释的取值
INTERPRETATION_NUMBER = "number"


class Cell:
    """一个单元格：原始文本 + 判定出的 kind + 解释后的数值。"""

    __slots__ = ("kind", "display", "number")

    def __init__(self, kind: str, display: str = "", number: Decimal | None = None):
        self.kind = kind
        self.display = display
        self.number = number

    def to_dict(self) -> dict:
        payload = {"kind": self.kind, "text": self.display}
        if self.number is not None:
            payload["exact"] = str(self.number)
        return payload


class Row:
    """一行：原始序号 + 源文件行号 + 单元格。"""

    __slots__ = ("ordinal", "line", "cells")

    def __init__(self, ordinal: int, line: int, cells: dict[str, Cell]):
        self.ordinal = ordinal
        self.line = line
        self.cells = cells


class InspectionError(Exception):
    """检查失败；``status`` 区分失败类型。"""

    def __init__(self, status: str, message: str):
        self.status = status
        super().__init__(message)


def _parse_csv(
    content: bytes, delimiter: str
) -> tuple[list[str], list[tuple[int, list[str]]], int]:
    """解析 CSV/TSV；返回 (表头, 行, 空行数)。"""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InspectionError("invalid", f"文件不是 UTF-8 文本：{exc}") from exc

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise InspectionError("invalid", "文件是空的") from None
    except csv.Error as exc:
        raise InspectionError("invalid", f"解析失败：{exc}") from exc

    header = [item.strip() for item in header]
    if not header or not any(header):
        raise InspectionError("invalid", "CSV 表头不能为空")
    if len(set(header)) != len(header):
        raise InspectionError("invalid", "CSV 表头必须唯一")
    if any(len(item) > library.MAX_FIELD_NAME for item in header):
        raise InspectionError(
            "invalid", f"表头字段名最长 {library.MAX_FIELD_NAME} 字符"
        )
    if len(header) > library.MAX_FIELDS:
        raise InspectionError("invalid", f"检查最多支持 {library.MAX_FIELDS} 个字段")

    rows: list[tuple[int, list[str]]] = []
    blank_lines = 0
    try:
        for values in reader:
            if not values:
                # 真正空的一行才跳过；`,` 这种全空字段的行是一条记录，不是空行
                blank_lines += 1
                continue
            if len(values) != len(header):
                raise InspectionError(
                    "invalid",
                    f"第 {reader.line_num} 行：期望 {len(header)} 列，实际 {len(values)} 列",
                )
            rows.append((reader.line_num, values))
            if len(rows) > library.MAX_ROWS:
                raise InspectionError(
                    "invalid", f"检查最多支持 {library.MAX_ROWS} 行记录"
                )
    except csv.Error as exc:
        raise InspectionError(
            "invalid", f"第 {reader.line_num} 行解析失败：{exc}"
        ) from exc
    return header, rows, blank_lines


def _parse_json(content: bytes) -> tuple[list[str], list[tuple[int, dict]], int]:
    """解析 JSON / JSONL；返回 (字段, 行, 空行数)。"""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InspectionError("invalid", f"文件不是 UTF-8 文本：{exc}") from exc

    text_stripped = text.strip()
    if not text_stripped:
        raise InspectionError("invalid", "文件是空的")

    records: list[tuple[int, object]] = []
    blank_lines = 0
    if text_stripped[0] in "[{":
        try:
            document = json.loads(text_stripped)
        except ValueError as exc:
            raise InspectionError("invalid", f"JSON 解析失败：{exc}") from exc
        if isinstance(document, dict):
            # 取第一个值为数组的字段
            for key, value in document.items():
                if isinstance(value, list):
                    records = [(index + 1, item) for index, item in enumerate(value)]
                    break
            else:
                raise InspectionError("invalid", "这个 JSON 里没有记录数组")
        elif isinstance(document, list):
            records = list(enumerate(document, start=1))
        else:
            raise InspectionError("invalid", "这个 JSON 顶层既不是数组也不是对象")
    else:
        # 一行一个 JSON 对象
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                blank_lines += 1
                continue
            try:
                records.append((number, json.loads(line)))
            except ValueError as exc:
                raise InspectionError(
                    "invalid", f"第 {number} 行不是合法 JSON：{exc}"
                ) from exc
            if len(records) > library.MAX_ROWS:
                raise InspectionError(
                    "invalid", f"检查最多支持 {library.MAX_ROWS} 行记录"
                )

    fields: list[str] = []
    for _, record in records:
        if not isinstance(record, dict):
            raise InspectionError("invalid", "每一条记录都必须是对象")
        for key in record:
            if key not in fields:
                fields.append(key)
    if not fields:
        raise InspectionError("invalid", "记录里没有任何字段")
    if len(fields) > library.MAX_FIELDS:
        raise InspectionError("invalid", f"检查最多支持 {library.MAX_FIELDS} 个字段")

    rows = [(number, record) for number, record in records]
    return fields, rows, blank_lines


def _cell_from_json(value, interpreted: bool) -> Cell:
    """JSON 的值自带类型；只有显式解释为数字的字段才尝试转换。"""
    if value is None:
        return Cell(KIND_NULL, "")
    if isinstance(value, bool):
        return Cell(KIND_BOOLEAN, "true" if value else "false")
    if isinstance(value, (int, float)):
        return Cell(KIND_NUMBER, repr(value))
    if isinstance(value, str):
        if value == "":
            return Cell(KIND_EMPTY, "")
        if interpreted:
            return _number_cell(value)
        return Cell(KIND_STRING, value)
    if isinstance(value, (list, dict)):
        return Cell(KIND_STRING, json.dumps(value, ensure_ascii=False))
    return Cell(KIND_STRING, str(value))


def _number_cell(text: str) -> Cell:
    """按严格十进制字面量解释；不成功就保留原文。"""
    if not _NUMBER_RE.match(text):
        return Cell(KIND_STRING, text)
    try:
        number = Decimal(text)
    except InvalidOperation:
        return Cell(KIND_STRING, text)
    if not number.is_finite():
        return Cell(KIND_STRING, text)
    return Cell(KIND_NUMBER, text, number)


def _cell_from_text(value: str, interpreted: bool) -> Cell:
    """CSV/TSV 的值一律先当文本；只有显式解释的字段才尝试转数字。"""
    if value == "":
        return Cell(KIND_EMPTY, "")
    if interpreted:
        return _number_cell(value)
    return Cell(KIND_STRING, value)


def inspect_asset(
    asset: dict, interpretations: dict[str, str] | None = None, limit: int = 0
) -> dict:
    """检查一个版本，返回质量报告与行。

    interpretations 是「显式解释」的字段映射：{"列名": "number"}。
    未列出的列保持文本。limit 大于 0 时只解析这么多行（用于「预览数字」的试算）。
    """
    interpretations = interpretations or {}
    fmt = str(asset.get("format", "")).lower()
    if fmt not in library.TABULAR_FORMATS:
        raise InspectionError(
            "unsupported", f"这种文件不解析成表格（{fmt}），原文件仍完整保存"
        )

    try:
        content = library.read_asset_bytes(asset)
    except library.DataError as exc:
        status = (
            library.AVAILABLE_MISSING
            if "丢失" in str(exc)
            else library.AVAILABLE_CHANGED
        )
        raise InspectionError(status, str(exc)) from exc

    if fmt in ("csv", "tsv"):
        delimiter = "\t" if fmt == "tsv" else ","
        fields, raw_rows, blank_lines = _parse_csv(content, delimiter)
        rows = [
            Row(
                index,
                line,
                {
                    name: _cell_from_text(
                        values[position],
                        interpretations.get(name) == INTERPRETATION_NUMBER,
                    )
                    for position, name in enumerate(fields)
                },
            )
            for index, (line, values) in enumerate(raw_rows, start=1)
        ]
    else:
        fields, raw_rows, blank_lines = _parse_json(content)
        rows = [
            Row(
                index,
                line,
                {
                    # 键不存在是「缺字段」，键存在但值为 null 是「显式 null」，两回事
                    name: (
                        _cell_from_json(
                            record[name],
                            interpretations.get(name) == INTERPRETATION_NUMBER,
                        )
                        if name in record
                        else Cell(KIND_MISSING, "")
                    )
                    for name in fields
                },
            )
            for index, (line, record) in enumerate(raw_rows, start=1)
        ]

    if limit and len(rows) > limit:
        rows = rows[:limit]

    report = _quality_report(fields, rows, blank_lines, interpretations)
    inspection = {
        "asset_id": asset["id"],
        "sha256": asset.get("sha256"),
        "parser_version": PARSER_VERSION,
        "scope": "full" if not limit else f"preview:{limit}",
        "report": report,
        "fields": fields,
        "rows": rows,
    }
    if interpretations:
        inspection = apply_interpretations(inspection, interpretations)
    return inspection


def _quality_report(
    fields: list[str],
    rows: list[Row],
    blank_lines: int,
    interpretations: dict | None = None,
) -> dict:
    """汇总字段画像与整体质量。

    interpretations 是被显式解释为数字的列；这些列里转不动的值单独计数，
    原文照旧保留。
    """
    interpretations = interpretations or {}
    profiles = []
    for name in fields:
        kinds: set[str] = set()
        missing = nulls = empty = 0
        for row in rows:
            cell = row.cells.get(name)
            if cell is None or cell.kind == KIND_MISSING:
                missing += 1
                continue
            kinds.add(cell.kind)
            if cell.kind == KIND_NULL:
                nulls += 1
            elif cell.kind == KIND_EMPTY:
                empty += 1
        interpreted = interpretations.get(name) == INTERPRETATION_NUMBER
        failures = []
        if interpreted:
            for row in rows:
                cell = row.cells.get(name)
                if (
                    cell is not None
                    and cell.kind == KIND_STRING
                    and cell.display.strip() != ""
                ):
                    failures.append(
                        {"row": row.ordinal, "line": row.line, "text": cell.display}
                    )
        profiles.append(
            {
                "name": name,
                "kinds": sorted(kinds),
                "missing": missing,
                "nulls": nulls,
                "empty": empty,
                "interpretation": INTERPRETATION_NUMBER if interpreted else None,
                "conversion_failures": len(failures),
                "conversion_examples": failures[:5],
            }
        )

    # 重复行：整行内容相同算重复
    seen: dict[str, int] = {}
    duplicates = []
    for row in rows:
        key = json.dumps(
            {name: row.cells[name].display for name in fields if name in row.cells},
            ensure_ascii=False,
            sort_keys=True,
        )
        if key in seen:
            duplicates.append(
                {"row": row.ordinal, "duplicate_of": seen[key], "line": row.line}
            )
        else:
            seen[key] = row.ordinal

    return {
        "parser_version": PARSER_VERSION,
        "scope": "full",
        "row_count": len(rows),
        "field_count": len(fields),
        "fields": profiles,
        "missing": sum(item["missing"] for item in profiles),
        "nulls": sum(item["nulls"] for item in profiles),
        "empty": sum(item["empty"] for item in profiles),
        "duplicate_rows": len(duplicates),
        "duplicates": duplicates[:10],
        "blank_lines": blank_lines,
        "conversion_failures": 0,
    }


def apply_interpretations(inspection: dict, interpretations: dict[str, str]) -> dict:
    """按显式解释重算字段画像。

    只改被点名的字段；解释为数字的字段转不动的值，保留原文并计入转换失败。
    """
    fields = inspection["fields"]
    rows = inspection["rows"]
    rebuilt_rows = []
    for row in rows:
        cells = {}
        for name in fields:
            cell = row.cells.get(name)
            if cell is None:
                cells[name] = Cell(KIND_MISSING, "")
                continue
            if interpretations.get(name) == INTERPRETATION_NUMBER and cell.kind in (
                KIND_STRING,
                KIND_EMPTY,
            ):
                cells[name] = (
                    _number_cell(cell.display) if cell.kind == KIND_STRING else cell
                )
            else:
                cells[name] = cell
        rebuilt_rows.append(Row(row.ordinal, row.line, cells))

    report = _quality_report(
        fields, rebuilt_rows, inspection["report"]["blank_lines"], interpretations
    )
    report["conversion_failures"] = sum(
        item["conversion_failures"] for item in report["fields"]
    )
    return {**inspection, "rows": rebuilt_rows, "report": report}


def preview_interpretation(asset: dict, field: str, sample: int = 5) -> dict:
    """「预览数字」的试算：只看前几行，转不动的给出样例。

    这是试算，不改任何东西；用户确认后才应用。
    """
    interpretation = {field: INTERPRETATION_NUMBER}
    inspection = inspect_asset(asset, interpretation, limit=sample)
    profile = next(
        (item for item in inspection["report"]["fields"] if item["name"] == field), None
    )
    failures = profile["conversion_failures"] if profile else 0
    samples = []
    for row in inspection["rows"]:
        cell = row.cells.get(field)
        if cell is None:
            continue
        samples.append(
            {
                "row": row.ordinal,
                "source_line": row.line,
                "original": cell.display,
                "interpreted": str(cell.number) if cell.number is not None else None,
            }
        )
    return {
        "field": field,
        "checked": inspection["report"]["row_count"],
        "conversion_failures": failures,
        "samples": samples[:sample],
        "failure_examples": (profile or {}).get("conversion_examples", []),
    }
