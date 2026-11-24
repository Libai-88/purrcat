"""Paper 工具：论文库导入、按页读原文、引文定位与证据核对。"""

from __future__ import annotations

from src.papers import library, verify
from src.tool.filesystem.utils import can_read
from src.tool.utils.format import error_response, text_response


def _render_papers(papers: list[dict]) -> str:
    """把论文列表渲染成紧凑的 Markdown。"""
    if not papers:
        return "论文库还是空的，先用 action=import 导入一篇 PDF。"
    lines = ["# 论文库", ""]
    for item in papers:
        lines.append(
            f"- `{item['id']}` — {item.get('title') or '(无标题)'}"
            f"（{item.get('page_count', 0)} 页，{item.get('file_name', '')}）"
        )
    return "\n".join(lines)


def _render_locate(paper_id: str, quote: str) -> str:
    """渲染引文定位结果。"""
    hits = verify._pages_with_evidence(paper_id, quote)
    if not hits:
        best = verify._best_match(paper_id, quote)
        lines = [
            f"在《{paper_id}》里没有定位到这段引文。",
            f"关键词覆盖率 {best['coverage']:.0%}。",
        ]
        for candidate in verify._candidate_pages(paper_id, quote):
            lines.append(
                f"- 最接近：第 {candidate['page']} 页（{candidate['coverage']:.0%}）"
                f" — {candidate['excerpt'][:120]}"
            )
        return "\n".join(lines)

    lines = [f"在《{paper_id}》里定位到 {len(hits)} 处：", ""]
    for hit in hits:
        lines.append(f"- 第 {hit['page']} 页（字符 {hit['start']}–{hit['end']}）")
        lines.append(f"  > {hit['excerpt']}")
    return "\n".join(lines)


def _render_verify(paper_id: str, result: dict) -> str:
    """渲染核对结论。"""
    lines = [f"# 核对结论：{result['verdict_text']}", ""]
    if result["quote_found"]:
        lines.append("给出的引文在原文中原样出现。")
    else:
        lines.append("给出的引文未在原文中原样出现，以下按关键词比对。")
    lines.append(f"关键词覆盖率：{result['coverage']:.0%}")

    evidence = result.get("evidence")
    if evidence:
        lines.append("")
        lines.append(f"证据位置：第 {evidence['page']} 页")
        lines.append(f"> {evidence['excerpt']}")
    else:
        lines.append("")
        lines.append("原文里没有找到对应内容。")
        for candidate in result.get("candidates") or []:
            lines.append(
                f"- 最接近：第 {candidate['page']} 页（{candidate['coverage']:.0%}）"
                f" — {candidate['excerpt'][:120]}"
            )
    lines.append("")
    lines.append("注意：这只说明原文有没有这句话，不代表该结论在科学上成立。")
    return "\n".join(lines)


def Paper(
    action: str,
    path: str = None,
    paper_id: str = None,
    page: int = None,
    quote: str = None,
    claim: str = None,
    **kwargs,
) -> str:
    """论文库与证据核对工具。"""
    try:
        if action == "import":
            if not path:
                return error_response(
                    "action=import 需要提供 path（本机 PDF 的绝对路径）"
                )
            if not can_read(path):
                return error_response(
                    f"没有读取该文件的权限：{path}。如需授权，先向用户申请。"
                )
            meta = library.import_paper(path)
            return text_response(
                f"已导入《{meta['title']}》，共 {meta['page_count']} 页。\n"
                f"论文 id：`{meta['id']}`",
                f"📄 Paper [{meta['id']}]",
            )

        if action == "list":
            return text_response(
                _render_papers(library.list_papers()),
                f"📚 Paper | {len(library.list_papers())}篇",
            )

        if action == "page":
            if not paper_id:
                return error_response("action=page 需要提供 paper_id")
            if page is None:
                return error_response("action=page 需要提供 page（从 1 开始）")
            text = library.page_text(paper_id, int(page))
            return text_response(
                f"# {paper_id} 第 {page} 页\n\n{text}",
                f"📖 Paper [{paper_id}] p{page}",
            )

        if action == "locate":
            if not paper_id:
                return error_response("action=locate 需要提供 paper_id")
            if not quote:
                return error_response("action=locate 需要提供 quote（原文引文）")
            return text_response(
                _render_locate(paper_id, quote),
                f"🔎 Paper [{paper_id}]",
            )

        if action == "verify":
            if not paper_id:
                return error_response("action=verify 需要提供 paper_id")
            if not claim and not quote:
                return error_response("action=verify 需要提供 claim 或 quote 其一")
            result = verify.verify_claim(paper_id, claim or "", quote or "")
            return text_response(
                _render_verify(paper_id, result),
                f"🧾 Paper [{paper_id}] {result['verdict_text']}",
            )

        return error_response(
            f"未知的 action: {action}。可用：import / list / page / locate / verify"
        )
    except library.PaperError as exc:
        return error_response(str(exc))
    except Exception as exc:
        return error_response(f"论文操作失败: {exc}")
