"""研究记录接口与人工复核（SPEC-026 AC-15）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.papers import library, records
from src.server.api.research_api import router
from tests.support.pdf_factory import write_pdf

PAGE_ONE = [
    "A Study of Sample Evidence",
    "We report 19.1434 cm2 as the sum of squares.",
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(records, "records_root", lambda: str(tmp_path / "research"))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def record(client, tmp_path):
    source_dir = tmp_path.parent / f"api-rec-{tmp_path.name}"
    pdf = write_pdf(source_dir / "sample.pdf", [PAGE_ONE])
    paper_id = library.import_paper(str(pdf))["id"]
    saved = records.build_record(
        question="离差平方和是多少",
        claims=[
            {
                "text": "论文报告了 19.1434 cm2",
                "evidence": [
                    {
                        "paper_id": paper_id,
                        "page": 1,
                        "quote": "We report 19.1434 cm2 as the sum of squares.",
                    }
                ],
            }
        ],
    )
    records.save_record(saved)
    return saved


def test_records_are_empty_initially(client):
    response = client.get("/api/research/records")

    assert response.status_code == 200
    assert response.json() == {"records": []}


def test_list_records_returns_saved_record(client, record):
    response = client.get("/api/research/records")

    records_list = response.json()["records"]
    assert len(records_list) == 1
    assert records_list[0]["id"] == record["id"]
    assert records_list[0]["acceptance"] == "unverified"


def test_get_record_returns_detail(client, record):
    response = client.get(f"/api/research/records/{record['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["question"] == "离差平方和是多少"
    assert payload["claims"][0]["evidence"][0]["verification"] == "exact-match"


def test_get_unknown_record_returns_404(client):
    response = client.get("/api/research/records/rec-nope")

    assert response.status_code == 404


def test_acceptance_can_be_changed_by_hand(client, record):
    """AC-15：人工复核改状态，并留下复核历史。"""
    response = client.post(
        f"/api/research/records/{record['id']}/acceptance",
        json={"acceptance": "accepted", "note": "看过原文了"},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["acceptance"] == "accepted"
    assert updated["review_history"][-1]["from"] == "unverified"
    assert updated["review_history"][-1]["to"] == "accepted"
    assert updated["review_history"][-1]["note"] == "看过原文了"


def test_unknown_acceptance_is_rejected(client, record):
    response = client.post(
        f"/api/research/records/{record['id']}/acceptance",
        json={"acceptance": "definitely-true"},
    )

    assert response.status_code == 400


def test_acceptance_on_unknown_record_returns_404(client):
    response = client.post(
        "/api/research/records/rec-nope/acceptance", json={"acceptance": "accepted"}
    )

    assert response.status_code == 404
