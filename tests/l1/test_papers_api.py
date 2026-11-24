"""论文库的 HTTP 接口（SPEC-026 AC-2/AC-3）。

面板靠这些接口读论文库：列论文、取元数据、读某页原文、读全文。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.papers import library
from src.server.api.papers_api import router
from tests.support.pdf_factory import write_pdf

PAGE_ONE = [
    "A Study of Sample Evidence",
    "The quick brown fox jumps over the lazy dog.",
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_ROOT", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def imported(client, tmp_path):
    source_dir = tmp_path.parent / f"api-pdfs-{tmp_path.name}"
    pdf = write_pdf(source_dir / "sample.pdf", [PAGE_ONE, ["Second page here."]])
    library.import_paper(str(pdf))
    return library.list_papers()[0]


def test_list_papers_is_empty_initially(client):
    response = client.get("/api/papers")

    assert response.status_code == 200
    assert response.json() == {"papers": []}


def test_list_papers_returns_library(client, imported):
    response = client.get("/api/papers")

    papers = response.json()["papers"]
    assert len(papers) == 1
    assert papers[0]["id"] == imported["id"]
    assert papers[0]["page_count"] == 2


def test_get_paper_returns_metadata(client, imported):
    response = client.get(f"/api/papers/{imported['id']}")

    assert response.status_code == 200
    assert response.json()["title"] == imported["title"]


def test_get_unknown_paper_returns_404(client):
    response = client.get("/api/papers/no-such-paper")

    assert response.status_code == 404


def test_get_page_returns_text(client, imported):
    response = client.get(f"/api/papers/{imported['id']}/pages/1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert "quick brown fox" in payload["text"]


def test_get_page_out_of_range_returns_400(client, imported):
    response = client.get(f"/api/papers/{imported['id']}/pages/99")

    assert response.status_code == 400
    assert "页码超出范围" in response.json()["detail"]


def test_get_fulltext_returns_all_pages(client, imported):
    response = client.get(f"/api/papers/{imported['id']}/fulltext")

    assert response.status_code == 200
    pages = response.json()["pages"]
    assert len(pages) == 2
    assert "Second page here." in pages[1]


def test_import_paper_endpoint(client, tmp_path, monkeypatch):
    """导入接口把 PDF 收进论文库。"""
    monkeypatch.setattr("src.server.api.papers_api.can_read", lambda _path: True)
    source_dir = tmp_path.parent / f"api-import-{tmp_path.name}"
    pdf = write_pdf(source_dir / "new.pdf", [PAGE_ONE])

    response = client.post("/api/papers/import", json={"path": str(pdf)})

    assert response.status_code == 200
    meta = response.json()
    assert meta["page_count"] == 1
    assert len(client.get("/api/papers").json()["papers"]) == 1


def test_import_requires_path(client):
    response = client.post("/api/papers/import", json={"path": "  "})

    assert response.status_code == 400


def test_import_rejects_unreadable_path(client, tmp_path, monkeypatch):
    """没有读取权限时拒绝导入。"""
    monkeypatch.setattr("src.server.api.papers_api.can_read", lambda _path: False)
    pdf = write_pdf(tmp_path.parent / f"api-denied-{tmp_path.name}.pdf", [PAGE_ONE])

    response = client.post("/api/papers/import", json={"path": str(pdf)})

    assert response.status_code == 403
    assert client.get("/api/papers").json()["papers"] == []


def test_import_reports_scanned_pdf(client, tmp_path, monkeypatch):
    """扫描件导入时明确报错。"""
    monkeypatch.setattr("src.server.api.papers_api.can_read", lambda _path: True)
    scanned = write_pdf(tmp_path.parent / f"api-scan-{tmp_path.name}.pdf", [[]])

    response = client.post("/api/papers/import", json={"path": str(scanned)})

    assert response.status_code == 400
    assert "文本层" in response.json()["detail"]
