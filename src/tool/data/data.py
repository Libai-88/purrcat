"""Data 工具：导入、检查、查询数据集，并留下查询收据。"""

from __future__ import annotations

from src.data import library, query as query_module
from src.data.inspect import InspectionError, inspect_asset
from src.tool.filesystem.utils import can_read
from src.tool.utils.format import error_response, text_response

# 样本上限：给 Agent 看的部分必须小
SAMPLE_ROWS = 10
SAMPLE_COLUMNS = 8


def _render_datasets(datasets: list[dict]) -> str:
    if not datasets:
        return "数据集库是空的。用 action=import 导入一个 CSV / TSV / JSON 文件。"
    lines = ["# 数据集", ""]
    for item in datasets:
        latest = item.get("latest") or {}
        lines.append(
            f"- `{item['id']}` — {item['name']}"
            f"（{item.get('kind', 'dataset')}，{item.get('version_count', 0)} 个版本"
            f"，最新 {latest.get('format', '?')} / {latest.get('size', 0)} 字节"
            f" / {latest.get('availability', '?')}）"
        )
    return "\n".join(lines)


def _render_report(dataset: dict, asset: dict, inspection: dict) -> str:
    report = inspection["report"]
    lines = [
        f"# {dataset['name']} — {library.version_label(dataset, asset['id'])}",
        "",
        f"- 版本 id：`{asset['id']}`",
        f"- SHA-256：{asset.get('sha256', '')}",
        f"- 可用性：{asset.get('availability', '?')}",
        f"- 解析器：{report['parser_version']}",
        f"- 记录数：{report['row_count']}，字段数：{report['field_count']}",
        "",
        "## 字段",
        "",
        "| 字段 | 观察到的类型 | 缺字段 | 显式 null | 空字符串 | 解释 | 转换失败 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in report["fields"]:
        lines.append(
            f"| {item['name']} | {', '.join(item['kinds']) or '—'} | {item['missing']} | "
            f"{item['nulls']} | {item['empty']} | {item.get('interpretation') or '文本'} | "
            f"{item.get('conversion_failures', 0)} |"
        )
    lines += [
        "",
        "## 质量",
        "",
        f"- 缺字段：{report['missing']}",
        f"- 显式 null：{report['nulls']}",
        f"- 空字符串：{report['empty']}",
        f"- 重复行：{report['duplicate_rows']}",
        f"- 转换失败：{report['conversion_failures']}",
        f"- 跳过的空行：{report['blank_lines']}",
        "",
        "这些检查描述的是文件本身，不构成对数据科学意义的判断。",
    ]
    return "\n".join(lines)


def _render_result(result: dict, receipt: dict, sample_limit: int = SAMPLE_ROWS) -> str:
    lines = [
        "# 查询结果",
        "",
        f"- 问题：{receipt.get('question') or '（未填写）'}",
        f"- 命中 {result.get('total')} 行，返回 {len(result.get('rows') or [])} 行",
    ]
    if receipt.get("unit"):
        lines.append(f"- 单位：{receipt['unit']}")
    if receipt.get("grain"):
        lines.append(f"- 粒度：{receipt['grain']}")
    if receipt.get("denominator"):
        lines.append(f"- 分母：{receipt['denominator']}")
    lines.append(f"- 收据 id：`{receipt['query_id']}`")

    rows = result.get("rows") or []
    if rows:
        columns = [str(item) for item in result["spec"].get("columns") or []]
        if not columns and rows:
            columns = [f"col{i + 1}" for i in range(len(rows[0]["cells"]))]
        lines.append("")
        lines.append("| 行 | " + " | ".join(columns) + " |")
        lines.append("| --- |" + " --- |" * len(columns))
        for row in rows[:sample_limit]:
            cells = []
            for cell in row["cells"]:
                text = cell.get("text", "")
                if cell.get("kind") == "null":
                    text = "NULL"
                elif cell.get("kind") == "missing":
                    text = "（缺字段）"
                cells.append(str(text)[:40])
            lines.append(f"| {row['row']} | " + " | ".join(cells) + " |")
        if len(rows) > sample_limit:
            lines.append("")
            lines.append(f"（只展示前 {sample_limit} 行，其余见收据）")
    lines += [
        "",
        "---",
        "",
        "口径是声明，不是检验。收据只说明这次查询读的是哪个版本、按什么口径算的。",
    ]
    return "\n".join(lines)


def Data(
    action: str,
    path: str = None,
    name: str = None,
    kind: str = "dataset",
    dataset_id: str = None,
    asset_id: str = None,
    interpretations: dict = None,
    filter: dict = None,
    sort: dict = None,
    columns: list = None,
    limit: int = None,
    category: str = None,
    measure: str = None,
    aggregation: str = "count",
    question: str = "",
    unit: str = "",
    grain: str = "",
    denominator: str = "",
    **kwargs,
) -> str:
    """数据集工具。"""
    try:
        if action == "import":
            if not path:
                return error_response(
                    "action=import 需要提供 path（本机数据文件的绝对路径）"
                )
            if not can_read(path):
                return error_response(
                    f"没有读取该文件的权限：{path}。如需授权，先向用户申请。"
                )
            imported = library.import_dataset(
                path,
                name=name or "",
                kind=kind or "dataset",
                source=kwargs.get("source") or "",
                license_name=kwargs.get("license") or "",
                project_ref=kwargs.get("project_ref") or "",
                dataset_id=kwargs.get("add_version_to") or "",
            )
            asset = imported["asset"]
            dataset = imported["dataset"]
            return text_response(
                f"已导入《{dataset['name']}》"
                f"（{asset['format']}，{asset['size']} 字节，"
                f"版本 {library.version_label(dataset, asset['id'])}）。\n"
                f"数据集 id：`{dataset['id']}`\n"
                f"版本 id：`{asset['id']}`\n"
                f"SHA-256：{asset['sha256']}\n"
                + (
                    ""
                    if library.can_inspect(asset)
                    else "这个格式不解析成表格，原件已完整保存。"
                ),
                f"📊 Data [{dataset['id']}]",
            )

        if action == "list":
            datasets = library.list_datasets()
            return text_response(
                _render_datasets(datasets), f"📊 Data | {len(datasets)}个数据集"
            )

        if action == "inspect":
            if not dataset_id:
                return error_response("action=inspect 需要提供 dataset_id")
            resolved = library.resolve_version(dataset_id, asset_id or "")
            asset = resolved["asset"]
            if not library.can_inspect(asset):
                return error_response(
                    f"《{resolved['dataset']['name']}》这一版是 {asset['format']} 格式，"
                    "不解析成表格，只保存了原件。"
                )
            inspection = inspect_asset(asset, interpretations or {})
            if interpretations:
                inspection = apply(inspection, interpretations)
            return text_response(
                _render_report(resolved["dataset"], asset, inspection),
                f"📊 Data [{dataset_id}]",
            )

        if action == "query":
            if not dataset_id:
                return error_response("action=query 需要提供 dataset_id")
            spec = {
                "columns": columns or [],
                "filter": filter,
                "sort": sort,
                "limit": limit or query_module.DEFAULT_LIMIT,
            }
            outcome = query_module.run_query(
                dataset_id,
                asset_id or "",
                question=question,
                spec=spec,
                interpretations=interpretations or {},
                unit=unit,
                grain=grain,
                denominator=denominator,
            )
            return text_response(
                _render_result(outcome["result"], outcome["receipt"]),
                f"📊 Data 查询 [{outcome['receipt']['query_id']}]",
            )

        if action == "receipts":
            receipts = query_module.list_receipts()
            if not receipts:
                return text_response("还没有查询收据。", "📊 Data | 0 条收据")
            lines = ["# 查询收据", ""]
            for item in receipts:
                lines.append(
                    f"- `{item['query_id']}` — {item.get('question') or '（未填写问题）'}"
                    f"（{item.get('row_count')} 行，{item.get('created_at', '')}）"
                )
            return text_response("\n".join(lines), f"📊 Data | {len(receipts)} 条收据")

        return error_response(
            f"未知的 action: {action}。可用：import / list / inspect / query / receipts"
        )
    except (library.DataError, InspectionError) as exc:
        return error_response(str(exc))
    except Exception as exc:
        return error_response(f"数据集操作失败: {exc}")


def apply(inspection: dict, interpretations: dict) -> dict:
    """按显式解释重算（薄封装，便于测试替换）。"""
    from src.data.inspect import apply_interpretations

    return apply_interpretations(inspection, interpretations)
