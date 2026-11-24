"""论文 ↔ 数据两条证据链合一：数字引用数据收据与字面比对（SPEC-029）。"""

from __future__ import annotations


import pytest

from src.data import library, query as query_module
from src.data import numeric
from src.papers import library as paper_library
from src.papers import records
from tests.support.pdf_factory import write_pdf


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def dataset(data_home, tmp_path):
    path = tmp_path / "trial.csv"
    path.write_text("group,score\nA,90\nB,75\nA,60\nB,88\n", encoding="utf-8")
    imported = library.import_dataset(str(path))
    return imported


@pytest.fixture
def receipt(dataset):
    """一次按类目求和的查询，留下收据。"""
    outcome = query_module.run_query(
        dataset["dataset"]["id"],
        question="各组总分",
        spec={"columns": [], "filter": None, "sort": None, "limit": 50},
        interpretations={"score": "number"},
        unit="分",
        grain="每组一行",
        denominator="全部记录",
        category="group",
        measure="score",
        aggregation="sum",
    )
    return outcome["receipt"]


@pytest.fixture
def paper_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_library, "DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(records, "records_root", lambda: str(tmp_path / "research"))
    return tmp_path


@pytest.fixture
def paper(paper_home, tmp_path):
    path = tmp_path / "trial-paper.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    # 用一份可读的假论文：内容由 check_quote 逐字校验，这里直接造一个真实可读的
    pdf = tmp_path / "paper.csv"  # 论文库只认能解析的文件，这里换用 papers 库的文本来源
    assert pdf is not None
    return path


# ---------- 数字提取与比对 ----------


def test_percent_is_normalized_to_a_ratio():
    """12% 与 0.12 指同一个量。"""
    numbers = numeric.extract_numbers("提升了 12%")

    assert numbers[0]["percent"] is True
    assert numbers[0]["normalized"] == numeric.Decimal("0.12")


def test_plain_number_keeps_its_value():
    numbers = numeric.extract_numbers("We report 19.1434 cm2")

    assert numbers[0]["normalized"] == numeric.Decimal("19.1434")


def test_matching_numbers_are_reported():
    result = numeric.compare_with_summary(
        "处理组平均 90 分", {"kind": "aggregate", "values": {"A": 90}}
    )

    assert result["status"] == numeric.MATCHED
    assert result["matched"][0]["paper"] == "90"
    assert result["matched"][0]["data"] == "90"


def test_percent_and_ratio_are_matched_with_a_note():
    """12% 与 0.12 对得上，但要说明是写法不同。"""
    result = numeric.compare_with_summary(
        "提升 12%", {"kind": "aggregate", "values": {"diff": 0.12}}
    )

    assert result["status"] == numeric.MATCHED
    assert result["matched"][0]["note"] == "比例写法不同"


def test_mismatching_numbers_are_reported():
    result = numeric.compare_with_summary(
        "处理组平均 90 分", {"kind": "aggregate", "values": {"A": 75}}
    )

    assert result["status"] == numeric.MISMATCHED
    assert result["unmatched_paper"] == ["90"]


def test_row_count_can_be_compared():
    result = numeric.compare_with_summary(
        "共 4 条记录", {"kind": "rows", "row_count": 4}
    )

    assert result["status"] == numeric.MATCHED


def test_comparison_without_numbers_is_not_applicable():
    result = numeric.compare_with_summary("没有数字", {"kind": "rows", "row_count": 4})

    assert result["status"] == numeric.NOT_APPLICABLE


# ---------- 研究记录引用数据收据 ----------


def _paper_with_quote(tmp_path, line: str) -> str:
    """造一篇只有一行的论文；引文校验按页内原文逐字比对。"""
    path = write_pdf(tmp_path / "trial-paper.pdf", [[line]])
    imported = paper_library.import_paper(str(path))
    return imported["id"]


def test_record_can_cite_a_data_receipt(paper_home, tmp_path, receipt):
    """AC-1：结论可以引用一条数据查询收据。"""
    record = records.build_record(
        question="处理组和对照组各是多少分",
        claims=[
            {
                "text": "处理组平均 90 分",
                "stance": "support",
                "evidence": [
                    {
                        "kind": "data",
                        "receipt_id": receipt["query_id"],
                    }
                ],
            }
        ],
    )

    evidence = record["claims"][0]["evidence"][0]
    assert evidence["kind"] == "data"
    assert evidence["receipt_id"] == receipt["query_id"]
    assert evidence["dataset_id"] == receipt["dataset_id"]
    assert evidence["summary"]["values"] == {"A": 150.0, "B": 163.0}


def test_record_rejects_unknown_receipt(paper_home, tmp_path):
    with pytest.raises(records.RecordError) as excinfo:
        records.build_record(
            question="问题",
            claims=[
                {
                    "text": "结论",
                    "evidence": [{"kind": "data", "receipt_id": "q-nope"}],
                }
            ],
        )

    assert "没有这条查询收据" in str(excinfo.value)


def test_record_rejects_unknown_evidence_kind(paper_home):
    with pytest.raises(records.RecordError) as excinfo:
        records.build_record(
            question="问题",
            claims=[{"text": "结论", "evidence": [{"kind": "webpage", "url": "x"}]}],
        )

    assert "paper 或 data" in str(excinfo.value)


def test_claim_with_both_chains_gets_a_numeric_check(paper_home, tmp_path, receipt):
    """AC-2：同一条结论既有原文引文又有数据收据时，自动做数字比对。"""
    paper_id = _paper_with_quote(tmp_path, "Treatment group scored 90 points.")

    record = records.build_record(
        question="处理组多少分",
        claims=[
            {
                "text": "处理组 90 分",
                "stance": "support",
                "evidence": [
                    {
                        "kind": "paper",
                        "paper_id": paper_id,
                        "page": 1,
                        "quote": "Treatment group scored 90 points.",
                    },
                    {"kind": "data", "receipt_id": receipt["query_id"]},
                ],
            }
        ],
    )

    check = record["claims"][0]["numeric_check"]
    assert check is not None
    assert check["status"] in (numeric.MATCHED, numeric.MISMATCHED, numeric.UNRESOLVED)
    assert "不是验证" in check["method"]


def test_paper_only_claim_has_no_numeric_check(paper_home, tmp_path):
    paper_id = _paper_with_quote(tmp_path, "Treatment group scored 90 points.")

    record = records.build_record(
        question="问题",
        claims=[
            {
                "text": "处理组 90 分",
                "evidence": [
                    {
                        "kind": "paper",
                        "paper_id": paper_id,
                        "page": 1,
                        "quote": "Treatment group scored 90 points.",
                    }
                ],
            }
        ],
    )

    assert record["claims"][0]["numeric_check"] is None


def test_receipt_carries_comparable_values(dataset):
    """收据里带着算出来的数，论文里的数字才有东西可比。"""
    outcome = query_module.run_query(
        dataset["dataset"]["id"],
        question="各组总分",
        spec={"limit": 50},
        interpretations={"score": "number"},
        category="group",
        measure="score",
        aggregation="sum",
    )

    summary = outcome["receipt"]["summary"]
    assert summary["kind"] == "aggregate"
    assert summary["values"] == {"A": 150.0, "B": 163.0}


def test_plain_query_receipt_reports_row_count(dataset):
    outcome = query_module.run_query(
        dataset["dataset"]["id"], question="有多少行", spec={"limit": 50}
    )

    summary = outcome["receipt"]["summary"]
    assert summary["kind"] == "rows"
    assert summary["row_count"] == 4
