"""研究记录：引文校验、认识论词表与存储（SPEC-026 AC-12/AC-13/AC-14）。"""

from __future__ import annotations

import json
import os

import pytest

from src.papers import library, records
from tests.support.pdf_factory import write_pdf

PAGE_ONE = [
    "A Study of Sample Evidence",
    "We report 19.1434 cm2 as the within-species sum of squares.",
    "The repeated measure agrees with the baseline.",
    "The repeated measure agrees with the baseline.",
]
PAGE_TWO = [
    "A sentence that only appears on the second page.",
]


@pytest.fixture
def papers_home(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(records, "records_root", lambda: str(tmp_path / "research"))
    return tmp_path


@pytest.fixture
def sample_pdf(tmp_path):
    source_dir = tmp_path.parent / f"rec-pdfs-{tmp_path.name}"
    return write_pdf(source_dir / "sample.pdf", [PAGE_ONE, PAGE_TWO])


@pytest.fixture
def imported(papers_home, sample_pdf):
    meta = library.import_paper(str(sample_pdf))
    return meta["id"]


def _claim(imported, quote=None, **extra):
    payload = {
        "text": "论文报告了物种内离差平方和 19.1434 cm2",
        "stance": "support",
        "evidence": [
            {
                "paper_id": imported,
                "page": 1,
                "quote": quote
                if quote is not None
                else "We report 19.1434 cm2 as the within-species sum of squares.",
            }
        ],
    }
    payload.update(extra)
    return payload


# ---------- AC-12 引文必须是原文 ----------


def test_record_requires_a_question(papers_home):
    with pytest.raises(records.RecordError):
        records.build_record(question="", claims=[{"text": "x", "evidence": []}])


def test_record_requires_at_least_one_claim(papers_home):
    with pytest.raises(records.RecordError):
        records.build_record(question="问题", claims=[])


def test_quote_must_exist_in_the_source_page(imported):
    """AC-12：引文不在原文里就拒收，不允许转述。"""
    with pytest.raises(records.RecordError) as excinfo:
        records.build_record(
            question="问题", claims=[_claim(imported, quote="我们报告了 19.1434 cm2")]
        )

    assert "原文原句" in str(excinfo.value)


def test_quote_on_wrong_page_is_rejected(imported):
    """引文在第 2 页却指第 1 页，同样拒收。"""
    with pytest.raises(records.RecordError):
        records.build_record(
            question="问题",
            claims=[
                {
                    "text": "x",
                    "evidence": [
                        {
                            "paper_id": imported,
                            "page": 1,
                            "quote": "A sentence that only appears on the second page.",
                        }
                    ],
                }
            ],
        )


def test_evidence_must_cite_a_known_paper(papers_home, imported):
    with pytest.raises(records.RecordError):
        records.build_record(
            question="问题",
            claims=[
                {
                    "text": "x",
                    "evidence": [
                        {"paper_id": "no-such-paper", "page": 1, "quote": "anything"}
                    ],
                }
            ],
        )


# ---------- AC-13 歧义不静默选 ----------


def test_ambiguous_quote_lists_all_candidates(imported):
    """AC-13：同一句在两页都出现时标为 ambiguous，并给出全部候选。"""
    record = records.build_record(
        question="问题",
        claims=[
            {
                "text": "重复测量与基线一致",
                "evidence": [
                    {
                        "paper_id": imported,
                        "page": 1,
                        "quote": "The repeated measure agrees with the baseline.",
                    }
                ],
            }
        ],
    )

    evidence = record["claims"][0]["evidence"][0]
    assert evidence["verification"] == records.VERIFICATION_AMBIGUOUS
    assert len(evidence["candidates"]) == 2  # 同一页里出现两次
    assert evidence["candidates"][0]["start"] < evidence["candidates"][1]["start"]


def test_exact_quote_is_marked_exact(imported):
    record = records.build_record(question="问题", claims=[_claim(imported)])

    evidence = record["claims"][0]["evidence"][0]
    assert evidence["verification"] == records.VERIFICATION_EXACT
    assert len(evidence["candidates"]) == 1
    assert evidence["candidates"][0]["end"] > evidence["candidates"][0]["start"]


# ---------- AC-14 认识论词表 ----------


def test_unknown_acceptance_is_rejected(imported):
    with pytest.raises(records.RecordError):
        records.build_record(
            question="问题", claims=[_claim(imported)], acceptance="definitely-true"
        )


def test_unknown_stance_is_rejected(imported):
    with pytest.raises(records.RecordError):
        records.build_record(
            question="问题", claims=[_claim(imported, stance="proves")]
        )


def test_default_acceptance_is_unverified(imported):
    record = records.build_record(question="问题", claims=[_claim(imported)])

    assert record["acceptance"] == records.ACCEPTANCE_UNVERIFIED
    assert record["claims"][0]["acceptance"] == records.ACCEPTANCE_UNVERIFIED


def test_claim_without_evidence_is_rejected(imported):
    with pytest.raises(records.RecordError):
        records.build_record(
            question="问题", claims=[{"text": "空口结论", "evidence": []}]
        )


# ---------- 存储 ----------


def test_saved_record_is_listed_and_readable(imported):
    record = records.build_record(question="问题", claims=[_claim(imported)])
    records.save_record(record)

    listed = records.list_records()
    assert len(listed) == 1
    assert listed[0]["id"] == record["id"]
    assert records.get_record(record["id"])["question"] == "问题"


def test_saved_record_writes_a_readable_report(imported):
    record = records.build_record(question="问题", claims=[_claim(imported)])
    records.save_record(record)

    report_path = os.path.join(
        records.records_root(), record["id"], records.REPORT_FILENAME
    )
    report = open(report_path, encoding="utf-8").read()
    assert "结论" in report
    assert "19.1434" in report
    assert "不说明结论在科学上成立" in report


def test_saved_record_is_valid_json_on_disk(imported):
    record = records.build_record(question="问题", claims=[_claim(imported)])
    records.save_record(record)

    path = os.path.join(records.records_root(), record["id"], records.RECORD_FILENAME)
    with open(path, encoding="utf-8") as handle:
        stored = json.load(handle)
    assert stored["id"] == record["id"]
    assert stored["claims"][0]["evidence"][0]["quote"]
