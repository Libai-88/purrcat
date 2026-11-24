"""Paper 工具的行为：导入、列表、读页、定位与核对（SPEC-026 AC-2/AC-3/AC-7/AC-8）。"""

from __future__ import annotations

import json

import pytest

from src.papers import library
from src.tool.paper.paper import Paper
from src.tool.utils.route import resolve_tool
from tests.support.pdf_factory import write_pdf

PAGE_ONE = [
    "A Study of Sample Evidence",
    "The quick brown fox jumps over the lazy dog.",
    "We report 19.1434 cm2 as the within-species sum of squares.",
]


@pytest.fixture
def papers_home(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def sample_pdf(tmp_path):
    source_dir = tmp_path.parent / f"pdfs-{tmp_path.name}"
    return write_pdf(source_dir / "sample.pdf", [PAGE_ONE])


def _payload(result):
    """从工具响应里取出正文。"""
    assert isinstance(result, dict), result
    return json.dumps(result, ensure_ascii=False)


def test_paper_tool_is_registered():
    """AC-8：Paper 在工具注册表里，且能解析到可调用对象。"""
    assert callable(resolve_tool("paper"))


def test_import_then_list(papers_home, sample_pdf, monkeypatch):
    """AC-2：导入后能在列表里看到。"""
    monkeypatch.setattr(
        "src.tool.paper.paper.can_read", lambda _path: True
    )

    imported = Paper(action="import", path=str(sample_pdf))
    assert "已导入" in _payload(imported)

    listed = Paper(action="list")
    assert "sample" in _payload(listed)


def test_import_requires_read_permission(papers_home, sample_pdf, monkeypatch):
    """AC-9：没有读取权限时拒绝导入。"""
    monkeypatch.setattr("src.tool.paper.paper.can_read", lambda _path: False)

    result = Paper(action="import", path=str(sample_pdf))

    assert "权限" in _payload(result)
    assert library.list_papers() == []


def test_import_scanned_pdf_reports_error(papers_home, tmp_path, monkeypatch):
    """AC-7：扫描件导入时明确报错。"""
    monkeypatch.setattr("src.tool.paper.paper.can_read", lambda _path: True)
    scanned = write_pdf(tmp_path.parent / f"scan-{tmp_path.name}.pdf", [[]])

    result = Paper(action="import", path=str(scanned))

    assert "文本层" in _payload(result)


def test_page_returns_text(papers_home, sample_pdf, monkeypatch):
    """AC-3：按页读原文。"""
    monkeypatch.setattr("src.tool.paper.paper.can_read", lambda _path: True)
    Paper(action="import", path=str(sample_pdf))
    paper_id = library.list_papers()[0]["id"]

    result = Paper(action="page", paper_id=paper_id, page=1)

    assert "quick brown fox" in _payload(result)


def test_page_out_of_range_errors(papers_home, sample_pdf, monkeypatch):
    """AC-3：页码越界明确报错。"""
    monkeypatch.setattr("src.tool.paper.paper.can_read", lambda _path: True)
    Paper(action="import", path=str(sample_pdf))
    paper_id = library.list_papers()[0]["id"]

    result = Paper(action="page", paper_id=paper_id, page=99)

    assert "页码超出范围" in _payload(result)


def test_locate_reports_page_and_excerpt(papers_home, sample_pdf, monkeypatch):
    """AC-4：定位到页码与上下文。"""
    monkeypatch.setattr("src.tool.paper.paper.can_read", lambda _path: True)
    Paper(action="import", path=str(sample_pdf))
    paper_id = library.list_papers()[0]["id"]

    result = Paper(
        action="locate",
        paper_id=paper_id,
        quote="The quick brown fox jumps over the lazy dog",
    )

    payload = _payload(result)
    assert "第 1 页" in payload
    assert "quick brown fox" in payload


def test_verify_reports_verdict(papers_home, sample_pdf, monkeypatch):
    """AC-6：核对给出结论与证据位置。"""
    monkeypatch.setattr("src.tool.paper.paper.can_read", lambda _path: True)
    Paper(action="import", path=str(sample_pdf))
    paper_id = library.list_papers()[0]["id"]

    result = Paper(
        action="verify",
        paper_id=paper_id,
        claim="论文报告了 19.1434 cm2 的离差平方和",
        quote="We report 19.1434 cm2 as the within-species sum of squares.",
    )

    payload = _payload(result)
    assert "原文支持" in payload
    assert "第 1 页" in payload


def test_verify_reports_not_found(papers_home, sample_pdf, monkeypatch):
    """AC-6：原文没提时明确给出未提及。"""
    monkeypatch.setattr("src.tool.paper.paper.can_read", lambda _path: True)
    Paper(action="import", path=str(sample_pdf))
    paper_id = library.list_papers()[0]["id"]

    result = Paper(
        action="verify",
        paper_id=paper_id,
        claim="photosynthesis thylakoid stroma chloroplast grana quantum",
    )

    payload = _payload(result)
    assert "原文未提及" in payload


def test_unknown_action_errors(papers_home):
    result = Paper(action="nope")

    assert "未知的 action" in _payload(result)


def test_missing_paper_id_errors(papers_home):
    assert "paper_id" in _payload(Paper(action="page", page=1))
    assert "paper_id" in _payload(Paper(action="locate", quote="x"))
    assert "paper_id" in _payload(Paper(action="verify", claim="x"))
