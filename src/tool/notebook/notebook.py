"""Notebook 工具：列出、读取、保存与导出研究笔记。"""

from __future__ import annotations

from src.notebook import document as doc
from src.notebook import export as export_module
from src.notebook import store, table
from src.tool.utils.format import error_response, text_response


def _render_document(record: dict) -> str:
    document = record["document"]
    lines = [
        f"# {document.get('title') or '未命名笔记'}",
        "",
        f"- 修订：第 {record.get('revision')} 版（{record.get('updated_at', '')}）",
        f"- 摘要：{str(record.get('digest', ''))[:16]}",
        f"- 可信度：{document.get('acceptance', 'unverified')}",
        "",
    ]
    for block in document.get("blocks") or []:
        kind = block.get("kind")
        attrs = block.get("attrs") or {}
        if kind == "text":
            lines.extend([attrs.get("text", ""), ""])
        elif kind == "heading":
            level = max(1, min(6, int(attrs.get("level") or 1)))
            lines.extend([f"{'#' * (level + 1)} {attrs.get('text', '')}", ""])
        elif kind == "evidence":
            lines.extend(
                [
                    f"[原文证据] `{attrs.get('paper_id', '')}` 第 {attrs.get('page', '?')} 页"
                    f"（{attrs.get('verification', '')}）",
                    f"> {attrs.get('quote', '')}",
                    "",
                ]
            )
        elif kind == "data":
            lines.extend(
                [
                    f"[数据收据] `{attrs.get('receipt_id', '')}`"
                    + (
                        f" — {attrs.get('question', '')}"
                        if attrs.get("question")
                        else ""
                    ),
                    "",
                ]
            )
        elif kind == "finding":
            lines.extend(
                [
                    f"[结论] {attrs.get('claim', '')}"
                    f"（引用 {', '.join(attrs.get('evidence_ids') or [])}）",
                    "",
                ]
            )
        elif kind == "table":
            sheet = attrs.get("sheet") or {}
            lines.extend(
                [
                    f"[表格] {attrs.get('label') or ''} "
                    f"（{sheet.get('rows', 0)} 行 × {sheet.get('columns', 0)} 列）",
                    "",
                ]
            )
    lines.extend(
        [
            "---",
            "",
            "证据只说明引文出现在原文的哪一页，不说明结论在科学上成立。",
        ]
    )
    return "\n".join(lines)


def _sheets_of(document: dict) -> dict:
    sheets = {}
    for index, block in enumerate(document.get("blocks") or []):
        if block["kind"] != doc.BLOCK_TABLE:
            continue
        name = block.get("block_id") or f"Sheet{index + 1}"
        sheets[name] = block["attrs"]["sheet"]
    return sheets


def Notebook(
    action: str,
    doc_id: str = "",
    revision: int = None,
    title: str = "",
    blocks: list = None,
    expected_revision: int = None,
    acceptance: str = "",
    **kwargs,
) -> str:
    """研究笔记工具。"""
    try:
        if action == "list":
            documents = store.list_documents()
            if not documents:
                return text_response("还没有研究笔记。", "🗒 Notebook | 0 篇")
            lines = ["# 研究笔记", ""]
            for item in documents:
                lines.append(
                    f"- `{item['doc_id']}` — {item.get('title') or '未命名'}"
                    f"（第 {item.get('revision')} 版，{item.get('block_count', 0)} 个块）"
                )
            return text_response("\n".join(lines), f"🗒 Notebook | {len(documents)} 篇")

        if action == "read":
            if not doc_id:
                return error_response("action=read 需要提供 doc_id")
            record = store.read(doc_id, revision)
            return text_response(_render_document(record), f"🗒 Notebook [{doc_id}]")

        if action == "save":
            if blocks is None:
                return error_response("action=save 需要提供 blocks")
            target = doc_id or doc.new_block_id()
            document = {
                "schema_version": doc.SCHEMA_VERSION,
                "title": title or "未命名笔记",
                "blocks": blocks,
                "acceptance": acceptance or doc.ACCEPTANCE_UNVERIFIED,
            }
            record = store.commit(target, document, expected_revision)
            return text_response(
                f"已保存《{record['document'].get('title')}》第 {record['revision']} 版"
                f"（摘要 {str(record['digest'])[:12]}）。\n\n"
                + _render_document(record),
                f"🗒 Notebook [{target}]",
            )

        if action == "export":
            if not doc_id:
                return error_response("action=export 需要提供 doc_id")
            record = store.read(doc_id, revision)
            document = record["document"]
            sheets = _sheets_of(document)
            values = table.evaluate_sheets(sheets)
            merged = {}
            for sheet_values in values.values():
                merged.update(sheet_values)
            markdown, losses = export_module.export_markdown(document, merged)
            lines = [markdown]
            if losses:
                lines.append("")
                lines.append("## 导出损失")
                lines.append("")
                for loss in losses:
                    lines.append(f"- {loss['code']}：{loss['detail']}")
            return text_response("\n".join(lines), f"🗒 Notebook 导出 [{doc_id}]")

        return error_response(
            f"未知的 action: {action}。可用：list / read / save / export"
        )
    except store.RevisionConflict as exc:
        return error_response(f"修订冲突：{exc}")
    except (doc.DocumentError, store.NotebookError) as exc:
        return error_response(str(exc))
    except Exception as exc:
        return error_response(f"笔记操作失败: {exc}")
