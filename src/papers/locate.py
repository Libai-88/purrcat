"""在论文原文中定位引文、匹配断言。

PDF 抽出的文本带排版留下的换行与多余空白，用户引用的原句却往往是连续的一段。
这里统一把空白折叠掉再做匹配，同时保留归一化位置到原始位置的映射，
好让结果能指回原文的具体位置。
"""

from __future__ import annotations

import re
import unicodedata

# 归一化后仍保留的词：用于把断言拆成关键词序列
_WORD_RE = re.compile(r"[0-9a-z一-鿿]+")

# 匹配断言时忽略的英文虚词
_STOPWORDS = frozenset(
    """
    a an the of to in on for and or but if then than that this these those is are was
    were be been being do does did have has had with without from by as at it its
    we our you your they their he she his her i me my not no so such can could may
    might will would shall should must about into over under between within
    """.split()
)

# 断言匹配时至少要有这么多关键词才认为命中，否则短句容易误匹配
_MIN_CLAIM_TOKENS = 3
# 判定「支持」所需的关键词覆盖率
_SUPPORTED_COVERAGE = 0.8
# 判定「部分支持」所需的关键词覆盖率
_PARTIAL_COVERAGE = 0.35


def normalize(text: str) -> tuple[str, list[int]]:
    """把文本折叠空白，返回 (归一化文本, 归一化位置到原始位置的映射)。

    连续空白折成一个空格；每个归一化字符记录它在原文里的下标。
    """
    chars: list[str] = []
    mapping: list[int] = []
    in_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if not in_space:
                chars.append(" ")
                mapping.append(index)
            in_space = True
            continue
        in_space = False
        normalized = unicodedata.normalize("NFKC", char)
        for piece in normalized:
            chars.append(piece)
            mapping.append(index)
    return "".join(chars), mapping


def fold(text: str) -> str:
    """归一化并折叠大小写，用于比较。"""
    normalized, _ = normalize(text)
    return normalized.casefold()


def content_tokens(text: str) -> list[str]:
    """把断言拆成用于匹配的关键词序列（去掉虚词）。"""
    tokens = _WORD_RE.findall(fold(text))
    return [token for token in tokens if token not in _STOPWORDS and len(token) > 1]


def _context(text: str, start: int, end: int, width: int = 160) -> str:
    """取命中位置前后的一小段原文作为上下文。"""
    left = max(0, start - width // 2)
    right = min(len(text), end + width // 2)
    return text[left:right].strip()


def find_quote(page_text: str, quote: str) -> list[dict]:
    """在页面原文中找出引文的所有出现位置。

    匹配容忍换行与空白差异；返回每处的页内字符区间与上下文。
    """
    folded_quote = fold(quote).strip()
    if not folded_quote:
        return []

    folded_page, mapping = normalize(page_text)
    folded_page = folded_page.casefold()
    if len(folded_page) != len(mapping):
        # casefold 极少数情况下会改变长度，此时退化为不匹配
        return []

    matches = []
    start = folded_page.find(folded_quote)
    while start != -1:
        end = start + len(folded_quote)
        original_start = mapping[start]
        original_end = mapping[end - 1] + 1
        matches.append(
            {
                "start": original_start,
                "end": original_end,
                "excerpt": _context(page_text, original_start, original_end),
            }
        )
        start = folded_page.find(folded_quote, start + 1)
    return matches


def _page_tokens(page_text: str) -> tuple[list[str], list[int]]:
    """把页面原文切成关键词序列，并记录每个词在原文中的起点。"""
    tokens: list[str] = []
    starts: list[int] = []
    for match in re.finditer(r"[0-9a-z一-鿿]+", page_text.casefold()):
        token = unicodedata.normalize("NFKC", match.group(0))
        if token in _STOPWORDS or len(token) <= 1:
            continue
        tokens.append(token)
        starts.append(match.start())
    return tokens, starts


def match_claim(page_text: str, claim: str) -> dict:
    """把断言的关键词与页面原文做最长公共子序列匹配。

    返回覆盖率（命中关键词占比）、命中数量与证据位置。子序列允许中间夹着
    原文里的其他词，因此改写过的表述也能部分命中。
    """
    claim_tokens = content_tokens(claim)
    if not claim_tokens:
        return {"coverage": 0.0, "matched": 0, "total": 0, "evidence": None}

    page_tokens, page_starts = _page_tokens(page_text)
    if not page_tokens:
        return {
            "coverage": 0.0,
            "matched": 0,
            "total": len(claim_tokens),
            "evidence": None,
        }

    matched = _lcs_length(claim_tokens, page_tokens)
    coverage = matched / len(claim_tokens)
    evidence = None
    if matched:
        start, end = _lcs_span(claim_tokens, page_tokens)
        if start is not None:
            left = page_starts[start]
            right = page_starts[min(end, len(page_starts) - 1)] + 1
            evidence = {
                "start": left,
                "end": right,
                "excerpt": _context(page_text, left, right),
            }
    return {
        "coverage": round(coverage, 4),
        "matched": matched,
        "total": len(claim_tokens),
        "evidence": evidence,
    }


def _lcs_length(left: list[str], right: list[str]) -> int:
    """最长公共子序列长度。"""
    previous = [0] * (len(right) + 1)
    for item in left:
        current = [0]
        for index, other in enumerate(right):
            if item == other:
                current.append(previous[index] + 1)
            else:
                current.append(max(current[index], previous[index + 1]))
        previous = current
    return previous[-1]


def _lcs_span(left: list[str], right: list[str]) -> tuple[int | None, int]:
    """最长公共子序列在右侧的起止位置，用于给出证据区间。"""
    rows, cols = len(left), len(right)
    table = [[0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        for j in range(cols - 1, -1, -1):
            if left[i] == right[j]:
                table[i][j] = table[i + 1][j + 1] + 1
            else:
                table[i][j] = max(table[i + 1][j], table[i][j + 1])

    i = j = 0
    start = None
    end = 0
    while i < rows and j < cols:
        if left[i] == right[j]:
            if start is None:
                start = j
            end = j
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return start, end


def verdict_for(coverage: float, matched: int, total: int) -> str:
    """按覆盖率给出结论。"""
    if total < _MIN_CLAIM_TOKENS or matched == 0:
        return "not_found"
    if coverage >= _SUPPORTED_COVERAGE:
        return "supported"
    if coverage >= _PARTIAL_COVERAGE:
        return "partial"
    return "not_found"
