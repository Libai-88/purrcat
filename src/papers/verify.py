"""证据核对：判断论文原文是否支持一条断言。

核对只依据已导入论文自己的文本，不做外部检索，也不引入模型推断。
它回答的是「原文里有没有这句话」，不是「这个科学结论对不对」。
"""

from __future__ import annotations

from src.papers import library, locate

# 核对结论
SUPPORTED = "supported"
PARTIAL = "partial"
NOT_FOUND = "not_found"

_VERDICT_TEXT = {
    SUPPORTED: "原文支持",
    PARTIAL: "原文部分支持",
    NOT_FOUND: "原文未提及",
}

# 未找到时给出几个最接近的候选页
_CANDIDATE_PAGES = 3


def _pages_with_evidence(paper_id: str, quote: str) -> list[dict]:
    """在整篇论文里定位引文。"""
    hits = []
    for number, text in enumerate(library.all_pages(paper_id), start=1):
        for match in locate.find_quote(text, quote):
            hits.append({"page": number, **match})
    return hits


def _best_match(paper_id: str, subject: str) -> dict:
    """在整篇论文里找与给定文本最接近的一处。"""
    best = {"coverage": 0.0, "matched": 0, "total": 0, "evidence": None, "page": 0}
    for number, text in enumerate(library.all_pages(paper_id), start=1):
        result = locate.match_claim(text, subject)
        if result["coverage"] > best["coverage"]:
            best = {**result, "page": number}
    return best


def _candidate_pages(paper_id: str, subject: str) -> list[dict]:
    """没找到时，给出最接近的候选页，便于人工判断。"""
    scored = []
    for number, text in enumerate(library.all_pages(paper_id), start=1):
        result = locate.match_claim(text, subject)
        if result["coverage"] > 0:
            scored.append(
                {
                    "page": number,
                    "coverage": result["coverage"],
                    "excerpt": (result.get("evidence") or {}).get("excerpt", ""),
                }
            )
    scored.sort(key=lambda item: -item["coverage"])
    return scored[:_CANDIDATE_PAGES]


def verify_claim(paper_id: str, claim: str, quote: str = "") -> dict:
    """核对一条断言是否有原文支撑。

    给了引文就先按引文定位：找到即为支持；找不到再按引文的关键词比对，区分
    「原文措辞不同但说的同一件事」与「原文确实没提」。没给引文时按断言的关键词比对。
    """
    claim = (claim or "").strip()
    quote = (quote or "").strip()
    if not claim and not quote:
        raise library.PaperError("需要给出断言或引文其一")

    if library.get_paper(paper_id) is None:
        raise library.PaperError(f"论文库中没有这篇论文: {paper_id}")

    if quote:
        quote_hits = _pages_with_evidence(paper_id, quote)
        if quote_hits:
            return {
                "verdict": SUPPORTED,
                "verdict_text": _VERDICT_TEXT[SUPPORTED],
                "evidence": {
                    "page": quote_hits[0]["page"],
                    "excerpt": quote_hits[0]["excerpt"],
                    "start": quote_hits[0]["start"],
                    "end": quote_hits[0]["end"],
                },
                "quote_found": True,
                "coverage": 1.0,
                "candidates": [],
            }
        subject = quote
    else:
        subject = claim

    best = _best_match(paper_id, subject)
    verdict = locate.verdict_for(best["coverage"], best["matched"], best["total"])

    evidence = None
    if verdict != NOT_FOUND and best.get("evidence"):
        # 只在有支持时才给证据位置；找不到时最接近的一页放在 candidates 里，
        # 免得被当成「原文确实这么写」
        evidence = {
            "page": best["page"],
            "excerpt": best["evidence"]["excerpt"],
            "start": best["evidence"]["start"],
            "end": best["evidence"]["end"],
        }
    return {
        "verdict": verdict,
        "verdict_text": _VERDICT_TEXT[verdict],
        "evidence": evidence,
        "quote_found": False,
        "coverage": best["coverage"],
        "candidates": [] if verdict != NOT_FOUND else _candidate_pages(paper_id, subject),
    }
