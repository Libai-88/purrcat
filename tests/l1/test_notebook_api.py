"""研究笔记的修订存储、导出与接口（SPEC-030）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.notebook import export as export_module
from src.notebook import store
from src.server.api.notebook_api import router


@pytest.fixture
def notebook_home(tmp_path, monkeypatch):
    """把笔记库指向临时目录，测试不碰真实数据目录。"""
    import src.utils.config as config

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def client(notebook_home):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _document(title: str = "笔记") -> dict:
    return {
        "schema_version": 1,
        "title": title,
        "blocks": [{"kind": "text", "attrs": {"text": "第一段"}}],
        "acceptance": "unverified",
    }


# ---------- 修订存储 ----------


def test_commit_creates_first_revision(notebook_home):
    record = store.commit("nb1", _document())

    assert record["revision"] == 1
    assert store.latest_revision("nb1") == 1
    assert record["digest"]


def test_commit_appends_revision(notebook_home):
    store.commit("nb1", _document())
    record = store.commit("nb1", _document("改过的标题"))

    assert record["revision"] == 2
    assert store.read("nb1")["document"]["title"] == "改过的标题"


def test_older_revisions_stay_readable(notebook_home):
    store.commit("nb1", _document("第一版"))
    store.commit("nb1", _document("第二版"))

    assert store.read("nb1", 1)["document"]["title"] == "第一版"
    assert store.read("nb1", 2)["document"]["title"] == "第二版"


def test_conflicting_revision_is_refused(notebook_home):
    """修订号对不上就报冲突，不覆盖别人的改动。"""
    store.commit("nb1", _document())

    with pytest.raises(store.RevisionConflict):
        store.commit("nb1", _document(), expected_revision=0)


def test_matching_expected_revision_commits(notebook_home):
    store.commit("nb1", _document())
    record = store.commit("nb1", _document("第二版"), expected_revision=1)

    assert record["revision"] == 2


def test_history_lists_revisions_newest_first(notebook_home):
    store.commit("nb1", _document())
    store.commit("nb1", _document("第二版"))

    history = store.revision_history("nb1")

    assert [item["revision"] for item in history] == [2, 1]


def test_documents_are_listed(notebook_home):
    store.commit("nb1", _document("第一篇"))
    store.commit("nb2", _document("第二篇"))

    titles = {item["title"] for item in store.list_documents()}

    assert titles == {"第一篇", "第二篇"}


# ---------- 导出 ----------


def test_export_renders_blocks(notebook_home):
    document = {
        "schema_version": 1,
        "title": "导出测试",
        "blocks": [
            {"kind": "heading", "attrs": {"text": "小节", "level": 1}},
            {"kind": "text", "attrs": {"text": "正文内容"}},
            {
                "kind": "finding",
                "block_id": "f1",
                "attrs": {
                    "claim": "一条结论",
                    "stance": "support",
                    "limitations": "有局限",
                    "evidence_ids": [],
                },
            },
        ],
        "acceptance": "unverified",
    }

    markdown, losses = export_module.export_markdown(document)

    assert "# 导出测试" in markdown
    assert "小节" in markdown
    assert "正文内容" in markdown
    assert "一条结论" in markdown
    assert "有局限" in markdown
    assert "不说明结论在科学上成立" in markdown


def test_export_reports_formula_loss(notebook_home):
    """有损格式必须说清楚丢了什么，不能悄悄替代。"""
    document = {
        "schema_version": 1,
        "title": "带公式",
        "blocks": [
            {
                "kind": "table",
                "block_id": "t1",
                "attrs": {
                    "sheet": {
                        "rows": 2,
                        "columns": 2,
                        "cells": {"A1": "1", "B1": "=SUM(A1:A1)"},
                    },
                },
            }
        ],
        "acceptance": "unverified",
    }

    markdown, losses = export_module.export_markdown(document, {"B1": 1.0})

    codes = {loss["code"] for loss in losses}
    assert export_module.LOSS_FORMULA in codes
    assert "1" in markdown


def test_export_of_evidence_records_its_loss(notebook_home):
    document = {
        "schema_version": 1,
        "title": "带证据",
        "blocks": [
            {
                "kind": "evidence",
                "block_id": "ev1",
                "attrs": {
                    "paper_id": "p1",
                    "page": 1,
                    "quote": "原文",
                    "verification": "exact-match",
                },
            }
        ],
        "acceptance": "unverified",
    }

    markdown, losses = export_module.export_markdown(document)

    assert export_module.LOSS_EVIDENCE_SNAPSHOT in {loss["code"] for loss in losses}
    assert "原文" in markdown


# ---------- 接口 ----------


def test_evaluate_route_is_not_swallowed_by_doc_id(client, notebook_home):
    """回归：/evaluate 曾被 /{doc_id} 抢先匹配，建出一堆垃圾笔记。"""
    response = client.post("/api/notebooks/evaluate", json={"document": _document()})

    assert response.status_code == 200
    assert "values" in response.json()
    assert store.list_documents() == [], "求值不该留下笔记"


def test_commit_and_read_through_api(client, notebook_home):
    response = client.post(
        "/api/notebooks/nb1", json={"document": _document("接口提交")}
    )

    assert response.status_code == 200
    assert response.json()["revision"] == 1

    read = client.get("/api/notebooks/nb1")
    assert read.json()["document"]["title"] == "接口提交"


def test_conflict_returns_409(client, notebook_home):
    client.post("/api/notebooks/nb1", json={"document": _document()})

    response = client.post(
        "/api/notebooks/nb1",
        json={"document": _document("改过"), "expected_revision": 0},
    )

    assert response.status_code == 409


def test_invalid_document_returns_400(client, notebook_home):
    response = client.post(
        "/api/notebooks/nb1",
        json={"document": {"schema_version": 1, "blocks": [{"kind": "mystery"}]}},
    )

    assert response.status_code == 400


def test_export_through_api_reports_losses(client, notebook_home):
    document = {
        "schema_version": 1,
        "title": "导出",
        "blocks": [
            {
                "kind": "table",
                "block_id": "t1",
                "attrs": {
                    "sheet": {
                        "rows": 1,
                        "columns": 2,
                        "cells": {"A1": "1", "B1": "=A1+1"},
                    },
                },
            }
        ],
        "acceptance": "unverified",
    }
    client.post("/api/notebooks/nb1", json={"document": document})

    response = client.get("/api/notebooks/nb1/export")

    assert response.status_code == 200
    payload = response.json()
    assert "# 导出" in payload["markdown"]
    assert any(loss["code"] == export_module.LOSS_FORMULA for loss in payload["losses"])
