"""研究文档与表格公式引擎（SPEC-030）。

锁住三条最容易出错的地方：引文必须逐字在原文里、错误必须穿过聚合函数、
循环引用必须是能认出来的错误值而不是 0。
"""

from __future__ import annotations

import pytest

from src.notebook import document as doc
from src.notebook import table
from src.papers import library as paper_library
from tests.support.pdf_factory import write_pdf


@pytest.fixture
def papers_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_library, "DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def paper(papers_home, tmp_path):
    path = write_pdf(tmp_path / "paper.pdf", [["Evidence", "We report 19.1434 cm2."]])
    return paper_library.import_paper(str(path))["id"]


def _sheet(cells: dict[str, str], rows: int = 5, columns: int = 5) -> dict:
    return {"rows": rows, "columns": columns, "cells": cells}


# ---------- 公式求值 ----------


def test_plain_values_are_read_as_is():
    values = table.evaluate_sheet(_sheet({"A1": "3", "A2": "4.5", "A3": "TRUE"}))

    assert values["A1"] == 3
    assert values["A2"] == 4.5
    assert values["A3"] is True


def test_arithmetic():
    values = table.evaluate_sheet(
        _sheet({"A1": "3", "A2": "4", "B1": "=A1+A2", "B2": "=A1*A2"})
    )

    assert values["B1"] == 7
    assert values["B2"] == 12


def test_sum_over_range():
    values = table.evaluate_sheet(
        _sheet({"A1": "1", "A2": "2", "A3": "3", "B1": "=SUM(A1:A3)"})
    )

    assert values["B1"] == 6


def test_average_and_extremes():
    values = table.evaluate_sheet(
        _sheet(
            {
                "A1": "10",
                "A2": "20",
                "A3": "30",
                "B1": "=AVERAGE(A1:A3)",
                "B2": "=MIN(A1:A3)",
                "B3": "=MAX(A1:A3)",
            }
        )
    )

    assert values["B1"] == 20
    assert values["B2"] == 10
    assert values["B3"] == 30


def test_formula_cell_stores_source_not_value():
    """单元格存的是源码，值是渲染时的投影。"""
    sheet = _sheet({"A1": "3", "B1": "=A1*2"})

    assert sheet["cells"]["B1"] == "=A1*2"
    assert table.evaluate_sheet(sheet)["B1"] == 6


# ---------- 错误传播 ----------


def test_error_in_referenced_cell_propagates_through_sum():
    """引用到的格子里有错误，SUM 的结果也是错误——不能把错误跳过去。"""
    values = table.evaluate_sheet(
        _sheet({"A1": "10", "A2": "=1/0", "A3": "20", "B1": "=SUM(A1:A3)"})
    )

    assert values["A2"] == table.ERROR_DIV0
    assert values["B1"] == table.ERROR_DIV0


def test_error_propagates_through_average():
    values = table.evaluate_sheet(
        _sheet({"A1": "10", "A2": "=1/0", "A3": "20", "B1": "=AVERAGE(A1:A3)"})
    )

    assert values["B1"] == table.ERROR_DIV0


def test_circular_reference_is_a_distinct_error_not_zero():
    """循环必须是能认出来的错误值；0 会被当成有效测量值混进均值。"""
    values = table.evaluate_sheet(_sheet({"A1": "=A1"}))

    assert values["A1"] == table.ERROR_CIRC
    assert values["A1"] != 0


def test_indirect_cycle_is_detected():
    values = table.evaluate_sheet(_sheet({"A1": "=B1", "B1": "=A1"}))

    assert values["A1"] == table.ERROR_CIRC
    assert values["B1"] == table.ERROR_CIRC


def test_division_by_zero():
    values = table.evaluate_sheet(_sheet({"A1": "=1/0"}))

    assert values["A1"] == table.ERROR_DIV0


def test_unknown_function_is_name_error():
    values = table.evaluate_sheet(_sheet({"A1": "=NOSUCHFN(1)"}))

    assert values["A1"] == table.ERROR_NAME


# ---------- 易变与外部调用被拒绝 ----------


@pytest.mark.parametrize(
    "formula",
    [
        "=NOW()",
        "=TODAY()",
        "=RAND()",
        "=RANDBETWEEN(1,2)",
        '=PY("x")',
        '=WEBSERVICE("u")',
    ],
)
def test_volatile_and_external_functions_are_refused(formula):
    """这些函数的结果不可复现，一律拒绝。"""
    values = table.evaluate_sheet(_sheet({"A1": formula}))

    assert values["A1"] == table.ERROR_NAME


def test_external_workbook_reference_is_refused():
    values = table.evaluate_sheet(_sheet({"A1": "='[Other]Sheet1'!A1"}))

    assert values["A1"] == table.ERROR_NAME


def test_iferror_catches_an_error():
    values = table.evaluate_sheet(_sheet({"A1": "=IFERROR(1/0,42)"}))

    assert values["A1"] == 42


# ---------- 文档模型 ----------


def test_document_requires_known_block_kinds():
    with pytest.raises(doc.DocumentError):
        doc.validate_document({"schema_version": 1, "blocks": [{"kind": "mystery"}]})


def test_document_requires_current_schema_version():
    with pytest.raises(doc.DocumentError):
        doc.validate_document({"schema_version": 99, "blocks": []})


def test_evidence_block_accepts_verbatim_quote(paper):
    """逐字引文通过校验。"""
    document = doc.validate_document(
        {
            "schema_version": 1,
            "title": "笔记",
            "blocks": [
                {
                    "kind": "evidence",
                    "block_id": "ev1",
                    "attrs": {
                        "paper_id": paper,
                        "page": 1,
                        "quote": "We report 19.1434 cm2.",
                    },
                }
            ],
        }
    )

    assert document["blocks"][0]["attrs"]["verification"] == "exact-match"


def test_evidence_block_rejects_rewritten_quote(paper):
    """改写过的引文不是证据，拒收。"""
    with pytest.raises(doc.DocumentError):
        doc.validate_document(
            {
                "schema_version": 1,
                "title": "笔记",
                "blocks": [
                    {
                        "kind": "evidence",
                        "block_id": "ev1",
                        "attrs": {
                            "paper_id": paper,
                            "page": 1,
                            "quote": "我们报告了 19.1434 cm2",
                        },
                    }
                ],
            }
        )


def test_evidence_block_rejects_unknown_paper(paper):
    with pytest.raises(doc.DocumentError):
        doc.validate_document(
            {
                "schema_version": 1,
                "title": "笔记",
                "blocks": [
                    {
                        "kind": "evidence",
                        "block_id": "ev1",
                        "attrs": {"paper_id": "no-such", "page": 1, "quote": "x"},
                    }
                ],
            }
        )


def test_finding_must_reference_blocks_in_the_same_document(paper):
    """结论只能引用本文件里的证据块。"""
    with pytest.raises(doc.DocumentError):
        doc.validate_document(
            {
                "schema_version": 1,
                "title": "笔记",
                "blocks": [
                    {
                        "kind": "finding",
                        "block_id": "f1",
                        "attrs": {"claim": "结论", "evidence_ids": ["ev-missing"]},
                    }
                ],
            }
        )


def test_finding_can_reference_an_evidence_block(paper):
    document = doc.validate_document(
        {
            "schema_version": 1,
            "title": "笔记",
            "blocks": [
                {
                    "kind": "evidence",
                    "block_id": "ev1",
                    "attrs": {
                        "paper_id": paper,
                        "page": 1,
                        "quote": "We report 19.1434 cm2.",
                    },
                },
                {
                    "kind": "finding",
                    "block_id": "f1",
                    "attrs": {
                        "claim": "论文报告了 19.1434 cm2",
                        "stance": "support",
                        "evidence_ids": ["ev1"],
                    },
                },
            ],
        }
    )

    assert len(document["blocks"]) == 2
    assert document["blocks"][1]["attrs"]["evidence_ids"] == ["ev1"]


def test_duplicate_block_ids_are_refused(paper):
    """带 id 的块（表格、证据）不能重号。"""
    with pytest.raises(doc.DocumentError):
        doc.validate_document(
            {
                "schema_version": 1,
                "title": "笔记",
                "blocks": [
                    {
                        "kind": "table",
                        "block_id": "t1",
                        "attrs": {"sheet": {"rows": 1, "columns": 1, "cells": {}}},
                    },
                    {
                        "kind": "table",
                        "block_id": "t1",
                        "attrs": {"sheet": {"rows": 1, "columns": 1, "cells": {}}},
                    },
                ],
            }
        )


def test_unknown_acceptance_is_refused():
    with pytest.raises(doc.DocumentError):
        doc.validate_document(
            {"schema_version": 1, "title": "笔记", "blocks": [], "acceptance": "sure"}
        )


def test_digest_changes_with_content():
    first = doc.new_document("标题")
    second = doc.new_document("标题")
    second["blocks"].append({"kind": "text", "attrs": {"text": "x"}})

    assert doc.document_digest(first) != doc.document_digest(second)
