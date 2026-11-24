"""ResearchRecord 工具：保存、列出与读取研究记录。"""

from __future__ import annotations

from src.papers import records
from src.tool.utils.format import error_response, text_response


def _render_summary(record: dict) -> str:
    """记录列表里的一行摘要。"""
    papers = len(record.get("papers") or [])
    claims = len(record.get("claims") or [])
    return (
        f"- `{record.get('id')}` — {record.get('title') or record.get('question', '')}"
        f"（{claims} 条结论 / {papers} 篇论文 / {record.get('acceptance', '')}）"
    )


def _render_record(record: dict) -> str:
    """把一条记录渲染成可读的 Markdown。"""
    lines = [
        f"# {record.get('title') or record.get('question')}",
        "",
        f"- 问题：{record.get('question', '')}",
        f"- 可信度状态：{record.get('acceptance', records.ACCEPTANCE_UNVERIFIED)}",
        f"- 记录 id：`{record.get('id')}`",
        "",
        "## 结论",
        "",
    ]
    for claim in record.get("claims") or []:
        lines.append(f"### [{claim.get('stance', '')}] {claim.get('text', '')}")
        for item in claim.get("evidence") or []:
            lines.append("")
            lines.append(
                f"- {item.get('paper_id')} 第 {item.get('page')} 页"
                f"（{item.get('verification', '')}）：{item.get('quote', '')}"
            )
        lines.append("")

    findings = record.get("findings") or []
    if findings:
        lines.append("## 发现")
        lines.append("")
        lines.extend(f"- {item}" for item in findings)
        lines.append("")

    gaps = record.get("gaps") or []
    if gaps:
        lines.append("## 未解决的问题")
        lines.append("")
        lines.extend(f"- {item}" for item in gaps)
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("证据只说明引文出现在原文的哪一页，不说明结论在科学上成立。")
    return "\n".join(lines)


def Research(
    action: str,
    record_id: str = None,
    title: str = None,
    question: str = None,
    claims: list = None,
    papers: list = None,
    findings: list = None,
    gaps: list = None,
    acceptance: str = None,
    project_id: str = None,
    **kwargs,
) -> str:
    """研究记录工具。"""
    try:
        if action == "save":
            if not question:
                return error_response(
                    "action=save 需要提供 question（这次研究要回答的问题）"
                )
            if not claims:
                return error_response("action=save 需要提供 claims（研究得出的结论）")
            record = records.build_record(
                question=question,
                claims=claims,
                papers=papers,
                findings=findings,
                gaps=gaps,
                title=title or "",
                project_id=project_id or "",
                acceptance=acceptance or records.ACCEPTANCE_UNVERIFIED,
            )
            records.save_record(record)
            return text_response(
                f"已保存研究记录 `{record['id']}`："
                f"{len(record['claims'])} 条结论，"
                f"{len(record['papers'])} 篇论文，"
                f"可信度状态 {record['acceptance']}。\n\n" + _render_record(record),
                f"🗂 ResearchRecord [{record['id']}]",
            )

        if action == "list":
            items = records.list_records()
            if not items:
                return text_response("还没有研究记录。", "🗂 ResearchRecord | 0 条")
            lines = ["# 研究记录", ""]
            lines.extend(_render_summary(item) for item in items)
            return text_response(
                "\n".join(lines), f"🗂 ResearchRecord | {len(items)} 条"
            )

        if action == "read":
            if not record_id:
                return error_response("action=read 需要提供 record_id")
            record = records.get_record(record_id)
            if record is None:
                return error_response(f"没有这条研究记录：{record_id}")
            return text_response(
                _render_record(record), f"🗂 ResearchRecord [{record_id}]"
            )

        return error_response(f"未知的 action: {action}。可用：save / list / read")
    except records.RecordError as exc:
        return error_response(str(exc))
    except Exception as exc:
        return error_response(f"研究记录操作失败: {exc}")
