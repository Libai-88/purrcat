"""研究记录：把一次研究的问题、结论与证据存成可回看的工件。

沿用一条硬规则：**证据是位置声明，不是真理声明**。
每条证据只说明「这句话出现在原文的哪一页哪一段」，不说明「这句话是对的」。
因此每份记录都带一个封闭词表里的 acceptance，读者必须自己判断可信度。

引文以原文为准：写进记录的引文必须逐字出现在那一页里，否则整条记录拒收。
引文在该页出现多次时不静默挑一个，而是标成 ambiguous 并列出全部候选。
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone

from src.papers import library, locate

# —— 认识论词表（封闭，取值之外一律拒收）——

ACCEPTANCE_UNVERIFIED = "unverified"
ACCEPTANCE_NEEDS_REVIEW = "needs_review"
ACCEPTANCE_ACCEPTED = "accepted"
ACCEPTANCE_REJECTED = "rejected"

ACCEPTANCE_VALUES = (
    ACCEPTANCE_UNVERIFIED,
    ACCEPTANCE_NEEDS_REVIEW,
    ACCEPTANCE_ACCEPTED,
    ACCEPTANCE_REJECTED,
)

STANCE_SUPPORT = "support"
STANCE_COUNTEREVIDENCE = "counterevidence"
STANCE_GAP = "gap"

STANCE_VALUES = (STANCE_SUPPORT, STANCE_COUNTEREVIDENCE, STANCE_GAP)

# 证据在原文里的定位结果
VERIFICATION_EXACT = "exact-match"
VERIFICATION_AMBIGUOUS = "ambiguous"
VERIFICATION_PAGE_ONLY = "page-only"
VERIFICATION_NOT_RUN = "not-run"

VERIFICATION_VALUES = (
    VERIFICATION_EXACT,
    VERIFICATION_AMBIGUOUS,
    VERIFICATION_PAGE_ONLY,
    VERIFICATION_NOT_RUN,
)

# 一条结论最多带多少条证据
MAX_EVIDENCE_PER_CLAIM = 8
# 一份记录最多多少条结论
MAX_CLAIMS = 40
# 一份记录最多引用多少篇论文
MAX_PAPERS = 16

RECORDS_DIRNAME = "research"
RECORD_FILENAME = "record.json"
REPORT_FILENAME = "report.md"


class RecordError(Exception):
    """研究记录操作失败。"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def records_root() -> "os.PathLike[str]":
    """研究记录根目录。"""
    from src.utils.config import DATA_DIR

    return os.path.join(DATA_DIR, RECORDS_DIRNAME)


def _record_dir(record_id: str) -> str:
    return os.path.join(records_root(), record_id)


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def _check_word(value: str, allowed: tuple[str, ...], field: str) -> str:
    if value not in allowed:
        raise RecordError(f"{field} 取值非法：{value!r}，可用：{', '.join(allowed)}")
    return value


def _check_quote(paper_id: str, page: int, quote: str) -> dict:
    """校验一条引文确实在那一页里，并给出定位结果。

    返回 verification 与候选区间；引文不在该页则抛错——证据必须是原文。
    """
    if not quote.strip():
        raise RecordError("引文不能为空")
    text = library.page_text(paper_id, page)
    hits = locate.find_quote(text, quote)
    if not hits:
        raise RecordError(
            f"引文不在论文 {paper_id} 第 {page} 页里："
            f"{quote[:80]!r}。证据必须是原文原句，不能改写或转述。"
        )
    if len(hits) == 1:
        return {
            "verification": VERIFICATION_EXACT,
            "candidates": [
                {"page": page, "start": hits[0]["start"], "end": hits[0]["end"]}
            ],
        }
    return {
        "verification": VERIFICATION_AMBIGUOUS,
        "candidates": [
            {"page": page, "start": hit["start"], "end": hit["end"]} for hit in hits
        ],
    }


def build_record(
    question: str,
    claims: list[dict],
    papers: list[str] | None = None,
    findings: list[str] | None = None,
    gaps: list[str] | None = None,
    title: str = "",
    project_id: str = "",
    acceptance: str = ACCEPTANCE_UNVERIFIED,
) -> dict:
    """组装并校验一份研究记录。

    claims 的每一项形如：
        {"text": "断言", "stance": "support",
         "evidence": [{"paper_id": "...", "page": 3, "quote": "原文原句"}]}
    """
    question = (question or "").strip()
    if not question:
        raise RecordError("研究记录需要一个问题")

    _check_word(acceptance, ACCEPTANCE_VALUES, "acceptance")

    claim_list = claims or []
    if not claim_list:
        raise RecordError("研究记录至少需要一条结论")
    if len(claim_list) > MAX_CLAIMS:
        raise RecordError(f"结论过多（最多 {MAX_CLAIMS} 条）")

    cited_papers = list(dict.fromkeys(papers or []))
    if len(cited_papers) > MAX_PAPERS:
        raise RecordError(f"引用论文过多（最多 {MAX_PAPERS} 篇）")

    built_claims = []
    for index, raw in enumerate(claim_list, start=1):
        if not isinstance(raw, dict):
            raise RecordError(f"第 {index} 条结论格式不对")
        text = str(raw.get("text") or "").strip()
        if not text:
            raise RecordError(f"第 {index} 条结论没有正文")
        stance = _check_word(
            str(raw.get("stance") or STANCE_SUPPORT), STANCE_VALUES, "stance"
        )
        claim_acceptance = _check_word(
            str(raw.get("acceptance") or acceptance),
            ACCEPTANCE_VALUES,
            "acceptance",
        )
        evidence_list = raw.get("evidence") or []
        if not evidence_list:
            raise RecordError(f"第 {index} 条结论没有证据")
        if len(evidence_list) > MAX_EVIDENCE_PER_CLAIM:
            raise RecordError(
                f"第 {index} 条结论的证据过多（最多 {MAX_EVIDENCE_PER_CLAIM} 条）"
            )

        built_evidence = []
        for item in evidence_list:
            if not isinstance(item, dict):
                raise RecordError(f"第 {index} 条结论的证据格式不对")
            paper_id = str(item.get("paper_id") or "").strip()
            if not paper_id:
                raise RecordError(f"第 {index} 条结论的证据缺少 paper_id")
            if library.get_paper(paper_id) is None:
                raise RecordError(f"论文库里没有这篇论文：{paper_id}")
            try:
                page = int(item.get("page"))
            except (TypeError, ValueError):
                raise RecordError(f"第 {index} 条结论的证据页码不合法") from None
            quote = str(item.get("quote") or "")
            located = _check_quote(paper_id, page, quote)
            built_evidence.append(
                {
                    "paper_id": paper_id,
                    "page": page,
                    "quote": quote,
                    "verification": located["verification"],
                    "candidates": located["candidates"],
                }
            )
            if paper_id not in cited_papers:
                cited_papers.append(paper_id)

        built_claims.append(
            {
                "id": f"claim-{index}",
                "text": text,
                "stance": stance,
                "acceptance": claim_acceptance,
                "evidence": built_evidence,
            }
        )

    record_id = "rec-" + uuid.uuid4().hex[:12]
    return {
        "id": record_id,
        "title": (title or question).strip()[:120],
        "question": question,
        "project_id": (project_id or "").strip(),
        "papers": cited_papers,
        "claims": built_claims,
        "findings": [
            str(item).strip() for item in (findings or []) if str(item).strip()
        ],
        "gaps": [str(item).strip() for item in (gaps or []) if str(item).strip()],
        "acceptance": acceptance,
        "created_at": now(),
        "updated_at": now(),
    }


def save_record(record: dict) -> dict:
    """把记录落盘，并生成一份人类可读的 Markdown。"""
    record_id = record.get("id") or ""
    if not record_id:
        raise RecordError("记录缺少 id")
    target = _record_dir(record_id)
    _write_json(os.path.join(target, RECORD_FILENAME), record)
    with open(
        os.path.join(target, REPORT_FILENAME), "w", encoding="utf-8", newline="\n"
    ) as handle:
        handle.write(render_report(record))
    return record


def list_records() -> list[dict]:
    """列出研究记录（按创建时间倒序）。"""
    root = records_root()
    if not os.path.isdir(root):
        return []
    records = []
    for item in sorted(os.listdir(root)):
        meta = _read_json(os.path.join(root, item, RECORD_FILENAME))
        if isinstance(meta, dict) and meta.get("id"):
            records.append(meta)
    records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return records


def get_record(record_id: str) -> dict | None:
    """取一份研究记录。"""
    meta = _read_json(os.path.join(_record_dir(record_id), RECORD_FILENAME))
    return meta if isinstance(meta, dict) else None


def record_digest(record: dict) -> str:
    """记录内容摘要，用于判断是否被改动过。"""
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def render_report(record: dict) -> str:
    """把记录渲染成人类可读的 Markdown。"""
    lines = [
        f"# {record.get('title') or record.get('question')}",
        "",
        f"- 问题：{record.get('question', '')}",
        f"- 记录状态：{record.get('acceptance', ACCEPTANCE_UNVERIFIED)}",
        f"- 引用论文：{', '.join(record.get('papers') or []) or '（无）'}",
        "",
    ]
    lines.append("## 结论")
    lines.append("")
    for claim in record.get("claims") or []:
        lines.append(
            f"### [{claim.get('stance', STANCE_SUPPORT)}] {claim.get('text', '')}"
        )
        for item in claim.get("evidence") or []:
            lines.append("")
            lines.append(
                f"- 第 {item.get('page')} 页（{item.get('verification', VERIFICATION_NOT_RUN)}）"
                f"：{item.get('quote', '')}"
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
    lines.append(
        "证据只说明引文出现在原文的哪一页，不说明结论在科学上成立。请自行判断可信度。"
    )
    return "\n".join(lines) + "\n"
