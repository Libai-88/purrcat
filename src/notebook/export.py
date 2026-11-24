"""把研究文档导出成 Markdown。

导出是**有损的**，所以必须把损失说出来：
公式在 Markdown 里不保留、表格只留值、证据快照不随文导出。
导出自带一份损失清单，接收方才知道这份 Markdown 缺了什么。

原则：**不用有损格式悄悄替换一份完整的证据记录。**
"""

from __future__ import annotations

from src.notebook import table

# 损失码
LOSS_FORMULA = "formula-not-exported"
LOSS_TABLE_VALUES = "table-values-only"
LOSS_EVIDENCE_SNAPSHOT = "evidence-snapshot-not-exported"
LOSS_UNIT = "cell-unit-not-exported"

_LOSS_TEXT = {
    LOSS_FORMULA: "表格里的公式在 Markdown 中不保留，只导出计算结果。",
    LOSS_TABLE_VALUES: "表格的格式（合并、颜色、列宽）不在 Markdown 里。",
    LOSS_EVIDENCE_SNAPSHOT: "证据的原文快照不随文档导出，请回到来源查看。",
    LOSS_UNIT: "单元格的单位标注不在 Markdown 里。",
}


def _cell_value_text(sheet: dict, address: str, values: dict) -> str:
    if address in values:
        return table.format_value(values[address])
    return sheet.get("cells", {}).get(address, "")


def _render_table(block: dict, values: dict) -> tuple[str, list[dict]]:
    """渲染一个表格块，返回 (Markdown, 损失)。"""
    attrs = block.get("attrs") or {}
    sheet = attrs.get("sheet") or {}
    rows = int(sheet.get("rows") or 0)
    columns = int(sheet.get("columns") or 0)
    cells = sheet.get("cells") or {}
    annotations = attrs.get("annotations") or {}
    column_names = attrs.get("column_names") or {}

    losses: list[dict] = []
    if any(
        isinstance(source, str) and source.strip().startswith("=")
        for source in cells.values()
    ):
        losses.append({"code": LOSS_FORMULA, "detail": _LOSS_TEXT[LOSS_FORMULA]})
    if rows and columns:
        losses.append(
            {"code": LOSS_TABLE_VALUES, "detail": _LOSS_TEXT[LOSS_TABLE_VALUES]}
        )
    if annotations:
        losses.append(
            {
                "code": LOSS_EVIDENCE_SNAPSHOT,
                "detail": _LOSS_TEXT[LOSS_EVIDENCE_SNAPSHOT],
            }
        )

    headers = []
    for column in range(columns):
        letter = table.column_letters(column)
        headers.append(str(column_names.get(letter) or letter))

    lines = []
    if attrs.get("label"):
        lines.append(f"**{attrs['label']}**")
        lines.append("")
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in range(rows):
        cells_out = []
        for column in range(columns):
            address = table.format_address(row, column)
            text = _cell_value_text(sheet, address, values)
            if address in annotations and annotations[address].get("unit"):
                losses.append({"code": LOSS_UNIT, "detail": _LOSS_TEXT[LOSS_UNIT]})
            cells_out.append(str(text).replace("|", "\\|"))
        lines.append("| " + " | ".join(cells_out) + " |")
    lines.append("")
    return "\n".join(lines), losses


def _render_evidence(block: dict) -> tuple[str, list[dict]]:
    attrs = block.get("attrs") or {}
    lines = [
        f"> **原文证据** · `{attrs.get('paper_id', '')}` 第 {attrs.get('page', '?')} 页"
    ]
    if attrs.get("verification") and attrs["verification"] != "exact-match":
        lines.append(f"> （{attrs['verification']}：同一段文字在原文里出现多次）")
    lines.append(">")
    lines.append(f"> {attrs.get('quote', '')}")
    lines.append("")
    return "\n".join(lines), [
        {"code": LOSS_EVIDENCE_SNAPSHOT, "detail": _LOSS_TEXT[LOSS_EVIDENCE_SNAPSHOT]}
    ]


def _render_data(block: dict) -> tuple[str, list[dict]]:
    attrs = block.get("attrs") or {}
    lines = [f"> **数据收据** · `{attrs.get('receipt_id', '')}`"]
    if attrs.get("question"):
        lines.append(">")
        lines.append(f"> 回答：{attrs['question']}")
    detail = []
    if attrs.get("unit"):
        detail.append(f"单位 {attrs['unit']}")
    if attrs.get("grain"):
        detail.append(f"粒度 {attrs['grain']}")
    if attrs.get("denominator"):
        detail.append(f"分母 {attrs['denominator']}")
    if attrs.get("row_count") is not None:
        detail.append(f"{attrs['row_count']} 行")
    if detail:
        lines.append(">")
        lines.append(f"> {' · '.join(detail)}")
    lines.append("")
    return "\n".join(lines), [
        {"code": LOSS_EVIDENCE_SNAPSHOT, "detail": _LOSS_TEXT[LOSS_EVIDENCE_SNAPSHOT]}
    ]


def _render_finding(block: dict) -> tuple[str, list[dict]]:
    attrs = block.get("attrs") or {}
    stance = attrs.get("stance") or "support"
    label = {"support": "结论", "counterevidence": "反证", "gap": "缺口"}.get(
        stance, "结论"
    )
    lines = [f"**{label}**：{attrs.get('claim', '')}"]
    if attrs.get("limitations"):
        lines.append("")
        lines.append(f"> 局限：{attrs['limitations']}")
    lines.append("")
    return "\n".join(lines), []


def export_markdown(
    document: dict, values: dict | None = None
) -> tuple[str, list[dict]]:
    """导出成 Markdown，返回 (文本, 损失清单)。

    values 是表格算出来的值；不给就只导出单元格里存的源码。
    """
    values = values or {}
    losses: list[dict] = []
    parts = [f"# {document.get('title') or '未命名笔记'}", ""]

    for block in document.get("blocks") or []:
        kind = block.get("kind")
        attrs = block.get("attrs") or {}
        if kind == "text":
            parts.extend([attrs.get("text", ""), ""])
        elif kind == "heading":
            level = max(1, min(6, int(attrs.get("level") or 1)))
            parts.extend([f"{'#' * (level + 1)} {attrs.get('text', '')}", ""])
        elif kind == "evidence":
            text, block_losses = _render_evidence(block)
            parts.append(text)
            losses.extend(block_losses)
        elif kind == "data":
            text, block_losses = _render_data(block)
            parts.append(text)
            losses.extend(block_losses)
        elif kind == "table":
            text, block_losses = _render_table(block, values)
            parts.append(text)
            losses.extend(block_losses)
        elif kind == "finding":
            text, block_losses = _render_finding(block)
            parts.append(text)
            losses.extend(block_losses)

    if document.get("notes"):
        parts.extend(["---", "", document["notes"], ""])

    parts.extend(
        [
            "---",
            "",
            "_证据只说明引文出现在原文的哪一页，不说明结论在科学上成立。_",
            "",
        ]
    )

    unique = []
    seen = set()
    for loss in losses:
        key = (loss["code"], loss.get("detail"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(loss)

    return "\n".join(parts), unique
