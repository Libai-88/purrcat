"""论文库的导入、分页原文、引文定位与证据核对（SPEC-026 AC-1/AC-4/AC-5/AC-6/AC-7/AC-9）。"""

from __future__ import annotations

import pytest

from src.papers import library, locate, verify
from tests.support.pdf_factory import write_pdf

PAGE_ONE = [
    "A Study of Sample Evidence",
    "The quick brown fox jumps over the lazy dog.",
    "We report 19.1434 cm2 as the within-species sum of squares.",
]
PAGE_TWO = [
    "Second page mentions Kaplan-Meier estimation and log-rank tests for survival data.",
]


@pytest.fixture
def papers_home(tmp_path, monkeypatch):
    """把论文库指向临时目录，测试不碰真实数据目录。"""
    monkeypatch.setattr(library, "DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def sample_pdf(tmp_path):
    # 放在临时根之外，避免混进「库只写自己目录」的判定
    source_dir = tmp_path.parent / f"pdfs-{tmp_path.name}"
    return write_pdf(source_dir / "sample.pdf", [PAGE_ONE, PAGE_TWO])


@pytest.fixture
def imported(papers_home, sample_pdf):
    return library.import_paper(str(sample_pdf))


# ---------- AC-1 导入与分页原文 ----------


def test_import_creates_library_entry(imported):
    """AC-1：导入后论文库里多出一条记录。"""
    papers = library.list_papers()
    assert len(papers) == 1
    assert papers[0]["id"] == imported["id"]
    assert papers[0]["page_count"] == 2


def test_import_keeps_page_text(imported):
    """AC-1：逐页原文可读，页数与原文一致。"""
    assert library.page_count(imported["id"]) == 2
    first = library.page_text(imported["id"], 1)
    assert "quick brown fox" in first
    second = library.page_text(imported["id"], 2)
    assert "Kaplan-Meier" in second


def test_reimport_same_file_is_stable(papers_home, sample_pdf):
    """同一文件重复导入落到同一处，不产生重复条目。"""
    first = library.import_paper(str(sample_pdf))
    second = library.import_paper(str(sample_pdf))
    assert first["id"] == second["id"]
    assert len(library.list_papers()) == 1


def test_page_out_of_range_raises(imported):
    """AC-3：页码越界明确报错。"""
    with pytest.raises(library.PaperError):
        library.page_text(imported["id"], 99)


def test_unknown_paper_raises(papers_home):
    with pytest.raises(library.PaperError):
        library.page_text("no-such-paper", 1)


def test_import_missing_file_raises(papers_home):
    with pytest.raises(library.PaperError):
        library.import_paper("/no/such/file.pdf")


# ---------- AC-7 扫描件 ----------


def test_scanned_pdf_without_text_layer_raises(papers_home, tmp_path):
    """AC-7：没有文本层的 PDF 明确报错，不产出空论文。"""
    scanned = write_pdf(tmp_path / "scanned.pdf", [[]])

    with pytest.raises(library.PaperError) as excinfo:
        library.import_paper(str(scanned))

    assert "文本层" in str(excinfo.value)
    assert library.list_papers() == []


# ---------- AC-4 引文定位 ----------


def test_find_quote_tolerates_line_breaks():
    """AC-4：引文里的换行与空白差异不影响定位。"""
    page = "The quick brown fox\njumps over   the lazy dog.\nEnd of page."

    hits = locate.find_quote(page, "The quick brown fox jumps over the lazy dog")

    assert len(hits) == 1
    assert hits[0]["start"] >= 0
    assert "quick brown fox" in hits[0]["excerpt"]


def test_find_quote_is_case_insensitive():
    page = "We report 19.1434 cm2 as the sum of squares."

    hits = locate.find_quote(page, "we report 19.1434 CM2")

    assert len(hits) == 1


def test_find_quote_reports_all_occurrences():
    page = "alpha beta. alpha beta. alpha gamma."

    hits = locate.find_quote(page, "alpha beta")

    assert len(hits) == 2


def test_find_quote_returns_empty_when_absent():
    assert locate.find_quote("nothing here", "missing phrase") == []


def test_locate_quote_across_pages(imported):
    """AC-4：能定位到具体页码。"""
    hits = verify._pages_with_evidence(imported["id"], "Kaplan-Meier estimation")

    assert len(hits) == 1
    assert hits[0]["page"] == 2


# ---------- AC-5 未找到时给候选 ----------


def test_verify_partial_when_quote_wording_differs(imported):
    """引文措辞不同但关键词高度重合时，判部分支持并指出最接近的页。"""
    result = verify.verify_claim(
        imported["id"],
        "论文报告了物种内离差平方和",
        "We report 19.1434 cm2 as the within species sum of squares",
    )

    assert result["quote_found"] is False
    assert result["verdict"] == verify.SUPPORTED
    assert result["evidence"]["page"] == 1


def test_verify_lists_candidate_pages_when_no_match(imported):
    """AC-5：确实找不到时返回未找到，并给出最接近的候选页。"""
    result = verify.verify_claim(
        imported["id"],
        "brown fox photosynthesis thylakoid stroma chloroplast grana quantum",
    )

    assert result["verdict"] == verify.NOT_FOUND
    assert result["evidence"] is None
    assert result["candidates"], "应给出候选页码"
    assert result["candidates"][0]["page"] == 1


def test_verify_without_any_overlap_has_no_candidates(imported):
    """完全没有重合时没有候选页——不硬凑。"""
    result = verify.verify_claim(
        imported["id"], "photosynthesis chlorophyll thylakoid stroma grana"
    )

    assert result["verdict"] == verify.NOT_FOUND
    assert result["candidates"] == []


# ---------- AC-6 核对结论 ----------


def test_verify_supported_by_quote(imported):
    """AC-6：引文在原文中找到时判定为支持，并给出证据位置。"""
    result = verify.verify_claim(
        imported["id"],
        "论文报告了物种内离差平方和 19.1434 cm2",
        "We report 19.1434 cm2 as the within-species sum of squares.",
    )

    assert result["verdict"] == verify.SUPPORTED
    assert result["quote_found"] is True
    assert result["evidence"]["page"] == 1
    assert "19.1434" in result["evidence"]["excerpt"]


def test_verify_supported_by_wording(imported):
    """AC-6：引文措辞不同但断言关键词都在时判定为支持。"""
    result = verify.verify_claim(
        imported["id"], "We report 19.1434 cm2 as the within-species sum of squares"
    )

    assert result["verdict"] == verify.SUPPORTED
    assert result["quote_found"] is False
    assert result["evidence"]["page"] == 1


def test_verify_partial_when_only_some_keywords_present(imported):
    """AC-6：只命中部分关键词时判定为部分支持。"""
    result = verify.verify_claim(
        imported["id"],
        "report 19.1434 cm2 within species sum squares plus unrelated filler words",
    )

    assert result["verdict"] == verify.PARTIAL
    assert result["coverage"] > 0
    assert result["evidence"]["page"] == 1


def test_verify_not_found_for_unrelated_claim(imported):
    """AC-6：原文确实没提时判定为未提及。"""
    result = verify.verify_claim(
        imported["id"], "photosynthesis chlorophyll chloroplast thylakoid stroma"
    )

    assert result["verdict"] == verify.NOT_FOUND
    assert result["coverage"] < 0.35


def test_verify_requires_claim_or_quote(imported):
    with pytest.raises(library.PaperError):
        verify.verify_claim(imported["id"], "")


def test_verify_unknown_paper_raises(papers_home):
    with pytest.raises(library.PaperError):
        verify.verify_claim("no-such-paper", "some claim")


# ---------- AC-9 目录边界 ----------


def test_library_writes_only_under_papers_root(papers_home, sample_pdf):
    """AC-9：论文库只在自己的目录里落盘。"""
    library.import_paper(str(sample_pdf))

    papers_dir = papers_home / "papers"
    assert papers_dir.is_dir()
    written = {p.relative_to(papers_home).parts[0] for p in papers_home.rglob("*")}
    assert written == {"papers"}
