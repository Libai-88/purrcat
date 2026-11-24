"""Connectors 工具：列目录、检索、拉取入库、查来源凭据。

与技能目录里的检索技能不同：那些技能让 Agent 临场写脚本去搜，
搜到的东西落不到本机库、也说不清从哪来的。连接器把这件事做实——
拉回来的东西进本机库，并留下来源凭据。

**凭据只说明出处，不说明可信。** 「这批数据是从 arXiv 拉的」
推不出「这批数据是对的」——后者是研究记录里 acceptance 的事。
"""

from __future__ import annotations

from src.connectors import catalog, landing, provenance
from src.connectors.catalog import ConnectorError, PullError
from src.tool.utils.format import error_response, text_response


def _render_catalog() -> str:
    lines = ["# 连接器目录", ""]
    for item in catalog.list_connectors():
        lines.append(f"## {item['name']}（`{item['id']}`）")
        lines.append(item["description"])
        lines.append(f"- 能拉：{', '.join(item['kinds'])}")
        lines.append(f"- 授权：{item['auth']}　限额：{item['rate_limit']}")
        lines.append(f"- 入库到：{item['lands']}　引用格式：{item['citation']}")
        lines.append("")
    lines.append("拉回来的东西会进本机库，并留下来源凭据。")
    return "\n".join(lines)


def _render_records(records: list[dict]) -> str:
    lines = ["# 检索结果", ""]
    for item in records:
        lines.append(f"## {item.get('title') or item.get('source_id')}")
        meta = []
        if item.get("year"):
            meta.append(str(item["year"]))
        if item.get("venue"):
            meta.append(str(item["venue"]))
        if item.get("doi"):
            meta.append(item["doi"])
        if meta:
            lines.append("　" + " · ".join(meta))
        authors = item.get("authors") or []
        if authors:
            lines.append("作者：" + ", ".join(authors[:6]))
        if item.get("abstract"):
            lines.append(item["abstract"][:400])
        if item.get("url"):
            lines.append(item["url"])
        if item.get("pdf_url"):
            lines.append(f"原文 PDF：{item['pdf_url']}")
        lines.append("")
    lines.append("这些是**候选**，不是结论。要能当证据用的，请拉取入库。")
    return "\n".join(lines)


def _render_provenance(record: dict) -> str:
    lines = [
        f"# 来源凭据 `{record.get('provenance_id', '')}`",
        "",
        f"- 来源：{record.get('connector_id', '')}",
        f"- 取回时间：{record.get('retrieved_at', '')}",
        f"- 原始请求：{record.get('request', {})}",
        f"- 内容哈希（SHA-256）：{record.get('content_sha256', '') or '—'}",
        f"- 条目数：{record.get('record_count', 0)}",
    ]
    if record.get("landed"):
        lines.append(f"- 入库到：{record['landed']} `{record.get('landed_id', '')}`")
    refs = record.get("source_refs") or []
    if refs:
        lines.append("- 原始条目链接：")
        for ref in refs[:10]:
            lines.append(f"  - {ref}")
    lines.append("")
    lines.append("凭据只说明这批东西从哪来，不说明它可不可信。")
    return "\n".join(lines)


def Connectors(
    action: str,
    connector_id: str = None,
    query: str = None,
    count: int = None,
    pdf_url: str = None,
    provenance_id: str = None,
    **kwargs,
) -> str:
    """连接器工具：把外部文献与数据拉进本机库，并留下来源凭据。

    Args:
        action: list / search / pull / paper / provenance
        connector_id: 连接器 id（arxiv、openalex、crossref、pubmed、zenodo、uniprot）
        query: 检索词；action=search/pull 时必填
        count: 拉多少条，默认 10，最多 100
        pdf_url: 论文原文 PDF 链接；action=paper 时必填
        provenance_id: 来源凭据 id；action=provenance 时指定

    Returns:
        格式化后的 JSON 字符串，包含 timestamp, type, content, snip
    """
    try:
        if not action:
            return error_response(
                "缺少必需参数 'action'。可选值：list / search / pull / paper / provenance。",
                "缺少 action",
            )
        action = str(action).strip().lower()

        if action == "list":
            body = _render_catalog()
            return text_response(body, f"🔌 {len(catalog.list_connectors())} 个连接器")

        if action in ("search", "pull"):
            if not connector_id:
                return error_response(
                    f"action={action} 需要 connector_id。"
                    f"可用：{', '.join(catalog.connector_ids())}",
                    "参数缺失",
                )
            if not query or not str(query).strip():
                return error_response(
                    f"action={action} 需要 query（检索词）。", "参数缺失"
                )
            try:
                catalog.get_connector(connector_id)
            except ConnectorError as exc:
                return error_response(str(exc), "❌ 没有这个连接器")

            if action == "search":
                outcome = landing.search(connector_id, query, count or 10)
                body = _render_records(outcome["records"])
                return text_response(body, f"🔎 {len(outcome['records'])} 条")

            outcome = landing.land_metadata(connector_id, query, count or 10)
            record = outcome["provenance"]
            dataset = outcome["dataset"]
            body = (
                f"已拉取 {record['record_count']} 条 `{connector_id}` 的结果，入库为数据集 "
                f"`{dataset['id']}`（{dataset['name']}）。\n\n"
                f"来源凭据：`{record['provenance_id']}`\n"
                f"取回时间：{record['retrieved_at']}\n"
                f"内容哈希：{record['content_sha256']}\n\n"
                "接下来可以对它跑查询、画图，查询收据能与论文里的数字对字。"
            )
            return text_response(body, f"✅ 已入库 | {record['record_count']} 条")

        if action == "paper":
            if not pdf_url:
                return error_response(
                    "action=paper 需要 pdf_url（论文原文链接）。", "参数缺失"
                )
            if not connector_id:
                connector_id = "arxiv"
            outcome = landing.land_paper(connector_id, pdf_url)
            record = outcome["provenance"]
            paper = outcome["paper"]
            body = (
                f"已把论文原文入库：`{paper['id']}`（{paper.get('title', '')}，"
                f"{paper.get('page_count', 0)} 页）。\n\n"
                f"来源凭据：`{record['provenance_id']}`\n"
                f"内容哈希：{record['content_sha256']}\n\n"
                "现在可以按页读原文、把引文定位到具体页码，引文也能逐字核对了。"
            )
            return text_response(body, "✅ 已入库 | 论文原文")

        if action == "provenance":
            if not provenance_id:
                return error_response(
                    "action=provenance 需要 provenance_id。", "参数缺失"
                )
            record = provenance.get(provenance_id)
            if record is None:
                return error_response(f"没有这条来源凭据：{provenance_id}", "❌ 未找到")
            return text_response(_render_provenance(record), "🔖 来源凭据")

        return error_response(
            f"无效的 action '{action}'。"
            "可选值：list / search / pull / paper / provenance。",
            "参数错误",
        )

    except PullError as exc:
        # 失败要说清是哪一类：连不上 / 没授权 / 限流 / 没结果 / 形态不对。
        return error_response(
            f"{exc.message}\n（失败类型：{exc.kind}）",
            f"❌ 拉取失败 · {exc.kind}",
        )
    except ConnectorError as exc:
        return error_response(str(exc), "❌ 没有这个连接器")
    except Exception as exc:
        return error_response(f"连接器工具异常：{exc}", "❌ 执行失败")


__all__ = ["Connectors"]
