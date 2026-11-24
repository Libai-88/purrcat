"""图表：把一份数据视图变成**带出处的图表规格**，不是图片。

规格里带着这次画图的全部依据——数据集、版本、SHA-256、用的哪些行、每行来自原文件第几行、
跳过了几组、丢了几个值。没有这些，一张图就只是一张图。

一条口径声明写在每份规格里：方法是声明，不是科学检查。

三条硬规则：

1. **值必须是有限的数字**，缺值与非数值一律不画——不给读者看一根假的柱子。
2. **标签列与数值列必须不同**，否则图上分不清横轴是什么。
3. **重复坐标点直接拒绝**，让用户先想清楚是要聚合还是要换轴。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone

from src.data import library
from src.data.inspect import (
    INTERPRETATION_NUMBER,
    KIND_EMPTY,
    KIND_MISSING,
    InspectionError,
)

CHARTS_DIRNAME = "charts"
SCHEMA_VERSION = 1

# 图表类型。金融专用（蜡烛图、桑基图）与科研场景无关，不做。
CHART_TYPES = ("bar", "line", "area", "scatter")
# 这几种按「类目 × 数值」聚合；散点按「数值 × 数值」逐行成点
AGGREGATE_TYPES = ("bar", "line", "area")
RECORD_TYPES = ("scatter",)

# 上限
MAX_ROWS = 2000
MAX_GROUPS = 50
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024

# 数值落在可绘制范围之外就被剔除并计数
MAX_PLOT_MAGNITUDE = 4096.0


class ChartError(Exception):
    """绘图失败。"""


def charts_root() -> str:
    return os.path.join(library.library_root(), CHARTS_DIRNAME)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _encode(document: dict) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _interpreted_fields(inspection: dict) -> set[str]:
    return {
        item["name"]
        for item in inspection["report"]["fields"]
        if item.get("interpretation") == INTERPRETATION_NUMBER
    }


def _finite(value) -> float | None:
    """转成有限浮点数；不合法返回 None。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _aggregate(inspection: dict, category: str, measure: str, aggregation: str):
    """按类目分组聚合，返回 (行, 省略组数, 丢值数)。"""
    rows = inspection["rows"]
    groups: dict[str, dict] = {}
    excluded = 0

    for row in rows:
        cell = row.cells.get(category)
        if cell is None or cell.kind in (KIND_MISSING, KIND_EMPTY):
            # 空类目画不出来，跳过并计数——不给读者一个空标签的柱子
            excluded += 1
            continue
        label = cell.display
        group = groups.setdefault(
            label,
            {"label": label, "total": 0.0, "count": 0, "ordinals": [], "lines": []},
        )
        group["count"] += 1
        group["ordinals"].append(row.ordinal)
        group["lines"].append(row.line)
        if aggregation == "sum":
            number = row.cells.get(measure)
            if number is None or number.number is None:
                excluded += 1
                continue
            group["total"] += float(number.number)

    ordered = sorted(groups.values(), key=lambda item: (-item["total"], item["label"]))
    shown = ordered[:MAX_GROUPS]
    omitted = len(ordered) - len(shown)

    chart_rows = []
    for group in shown:
        value = group["total"] if aggregation == "sum" else float(group["count"])
        chart_rows.append(
            {
                "label": group["label"],
                "value": value,
                "count": group["count"],
                "rowProvenance": [
                    {"ordinal": ordinal, "line": line}
                    for ordinal, line in zip(group["ordinals"], group["lines"])
                ],
            }
        )
    return chart_rows, omitted, excluded


def _records(inspection: dict, x_field: str, y_field: str):
    """散点：逐行取 (x, y)，任何一维不合法就不画。"""
    rows = inspection["rows"]
    if len(rows) > MAX_ROWS:
        raise ChartError(f"散点最多 {MAX_ROWS} 行，当前 {len(rows)} 行")

    chart_rows = []
    excluded = 0
    seen: set[tuple[float, float]] = set()
    for row in rows:
        x_cell = row.cells.get(x_field)
        y_cell = row.cells.get(y_field)
        x = _finite(x_cell.number) if x_cell else None
        y = _finite(y_cell.number) if y_cell else None
        if x is None or y is None:
            excluded += 1
            continue
        key = (x, y)
        if key in seen:
            raise ChartError(
                "有重复的坐标点，画出来会互相盖住。请先选好要聚合的类目，或换一组坐标。"
            )
        seen.add(key)
        chart_rows.append(
            {
                "label": f"{x:g}, {y:g}",
                "x": x,
                "y": y,
                "rowProvenance": [{"ordinal": row.ordinal, "line": row.line}],
            }
        )
    if not chart_rows:
        raise ChartError("没有能画的点：两列都得是有限数值，且该列已显式解释为数字")
    return chart_rows, 0, excluded


def build_chart(inspection: dict, spec: dict, dataset: dict, asset: dict) -> dict:
    """按口径生成一份图表规格。"""
    chart_type = str(spec.get("type") or "bar")
    if chart_type not in CHART_TYPES:
        raise ChartError(f"图表类型只能是：{', '.join(CHART_TYPES)}")

    fields = inspection["fields"]
    interpreted = _interpreted_fields(inspection)
    x_field = str(spec.get("x") or "")
    y_field = str(spec.get("y") or "")

    if not x_field or x_field not in fields:
        raise ChartError(f"没有这个字段: {x_field}")
    if not y_field or y_field not in fields:
        raise ChartError(f"没有这个字段: {y_field}")
    if x_field == y_field:
        raise ChartError("标签列与数值列必须不同，否则图上分不清横轴是什么")

    if chart_type in AGGREGATE_TYPES:
        aggregation = str(spec.get("aggregation") or "sum")
        if aggregation not in ("sum", "count"):
            raise ChartError("聚合方式只能是 sum 或 count")
        if aggregation == "sum":
            if y_field not in interpreted:
                raise ChartError(
                    f"字段「{y_field}」还是文本，不能求和。"
                    "请先在字段表里把它显式解释为数字。"
                )
        rows, omitted, excluded = _aggregate(inspection, x_field, y_field, aggregation)
        if not rows:
            raise ChartError("没有能画的分组：类目列全是空值")
        chart = {
            "type": chart_type,
            "x": x_field,
            "y": y_field,
            "aggregation": aggregation,
        }
    else:
        for name in (x_field, y_field):
            if name not in interpreted:
                raise ChartError(
                    f"字段「{name}」还是文本，散点图需要两个数值列。"
                    "请先在字段表里把它显式解释为数字。"
                )
        rows, omitted, excluded = _records(inspection, x_field, y_field)
        chart = {"type": chart_type, "x": x_field, "y": y_field}

    if len(rows) > MAX_ROWS:
        raise ChartError(f"图表最多 {MAX_ROWS} 行，当前 {len(rows)} 行")

    source = {
        "label": str(spec.get("source_label") or dataset.get("name") or ""),
        "datasetId": dataset["id"],
        "assetId": asset["id"],
        "sha256": asset.get("sha256", ""),
        "versionLabel": library.version_label(dataset, asset["id"]),
        "dataView": {
            "x": x_field,
            "y": y_field,
            "aggregation": chart.get("aggregation", ""),
            "interpretations": sorted(interpreted),
        },
        "parserVersion": inspection["parser_version"],
        "report": inspection["report"],
        "omittedGroups": omitted,
        "excludedValues": excluded,
        "caveats": [],
    }

    unit = str(spec.get("unit") or "").strip()
    grain = str(spec.get("grain") or "").strip()
    denominator = str(spec.get("denominator") or "").strip()
    caveats = []
    if unit:
        caveats.append(f"单位：{unit}（声明，未经校验）")
    if grain:
        caveats.append(f"粒度：{grain}")
    if denominator:
        caveats.append(f"分母：{denominator}")
    if omitted:
        caveats.append(f"只画了前 {MAX_GROUPS} 组，另有 {omitted} 组未画")
    if excluded:
        caveats.append(f"有 {excluded} 个值缺数据或不是数字，未画")
    source["caveats"] = caveats

    document = {
        "schemaVersion": SCHEMA_VERSION,
        "title": str(spec.get("title") or f"{y_field} by {x_field}"),
        "description": str(spec.get("description") or ""),
        "chart": chart,
        "rows": rows,
        "source": source,
        "acceptance": "needs_review",
        "generatedAt": _now(),
        "method": "方法是声明，不是科学检查。图表只说明这些数字是怎么从这一版数据算出来的。",
    }
    # 被哈希的就是存盘的字节：读回时重算哈希才能确认没被改动
    content = _encode(document)
    return {**document, "id": hashlib.sha256(content).hexdigest()}


def save_chart(document: dict) -> dict:
    """按内容哈希落盘；同样的图不会存两份。

    落盘的字节不含 id 字段——id 就是这些字节的哈希，自证不自指。
    """
    digest = str(document["id"])
    root = charts_root()
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, digest + ".chart.json")
    if not os.path.exists(path):
        stored = {key: value for key, value in document.items() if key != "id"}
        temporary = path + ".tmp"
        with open(temporary, "wb") as handle:
            handle.write(_encode(stored))
        os.replace(temporary, path)
    return document


def read_chart(digest: str) -> dict:
    """读一份图表规格；哈希对不上就拒绝。"""
    path = os.path.join(charts_root(), str(digest) + ".chart.json")
    try:
        with open(path, "rb") as handle:
            content = handle.read()
    except OSError as exc:
        raise ChartError(f"读不到这份图表：{digest}") from exc
    if hashlib.sha256(content).hexdigest() != str(digest):
        raise ChartError("这份图表的哈希与记录不符，可能已被改动")
    document = json.loads(content.decode("utf-8"))
    return {**document, "id": str(digest)}


def list_charts() -> list[dict]:
    """列出已保存的图表规格。"""
    root = charts_root()
    if not os.path.isdir(root):
        return []
    charts = []
    for name in sorted(os.listdir(root)):
        if not name.endswith(".chart.json"):
            continue
        try:
            document = read_chart(name[: -len(".chart.json")])
        except (ChartError, ValueError):
            continue
        charts.append(document)
    charts.sort(key=lambda item: item.get("generatedAt") or "", reverse=True)
    return charts


def make_chart(
    dataset_id: str,
    asset_id: str = "",
    chart_type: str = "bar",
    x_field: str = "",
    y_field: str = "",
    aggregation: str = "sum",
    interpretations: dict | None = None,
    title: str = "",
    unit: str = "",
    grain: str = "",
    denominator: str = "",
) -> dict:
    """跑一次绘图并把规格落盘。"""
    from src.data import inspect as inspect_module

    resolved = library.resolve_version(dataset_id, asset_id)
    asset = resolved["asset"]
    if not library.can_inspect(asset):
        raise InspectionError("unsupported", "这个文件不是表格，无法绘图")

    inspection = inspect_module.inspect_asset(asset, interpretations or {})
    if interpretations:
        inspection = inspect_module.apply_interpretations(inspection, interpretations)

    document = build_chart(
        inspection,
        {
            "type": chart_type,
            "x": x_field,
            "y": y_field,
            "aggregation": aggregation,
            "title": title,
            "unit": unit,
            "grain": grain,
            "denominator": denominator,
        },
        resolved["dataset"],
        asset,
    )
    save_chart(document)
    return document
