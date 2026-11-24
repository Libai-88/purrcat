"""科研类接口的状态回执（SPEC-031）。

面板要分清「有哪些数据 / 请求在做什么 / 业务结果是什么」，
服务端回给它的 ``status`` 里带其中两轴；第三轴由客户端补。
"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.data import library
from src.server.api import data_api, notebook_api, papers_api
from src.server.api.research_status import ResearchError, classify
from src.utils import panel_state


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def notebook_home(tmp_path, monkeypatch):
    import src.utils.config as config

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _client(router) -> TestClient:
    """按生产形态装配：带上研究类错误的状态回执。"""
    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(ResearchError)
    def _handler(request, exc: ResearchError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "status": exc.status},
        )

    return TestClient(app)


# ---------- 面板状态词表 ----------


def test_translation_uses_only_closed_vocabulary():
    """翻译出来的每一项都必须在词表里，不能自己造词。"""
    from src.utils import async_state

    cases = [
        panel_state.ready(),
        panel_state.empty(),
        panel_state.stale(),
        panel_state.partial(),
        panel_state.failed(),
        panel_state.unavailable(),
        panel_state.from_http(404),
        panel_state.from_http(403),
        panel_state.from_http(409),
    ]
    for payload in cases:
        assert payload["data"] in async_state.data_values()
        assert payload["request"] in async_state.request_values()
        assert payload["result"] in async_state.result_values()
        assert payload["state"] in async_state.state_values()
        if "reason" in payload:
            assert payload["reason"] in async_state.reason_values()
        if "action" in payload:
            assert payload["action"] in async_state.action_values()


def test_empty_states_offer_different_next_steps():
    """「从没有过」「筛掉了」「还没跑完」要给不同的入口，不能一个空壳通吃。"""
    first = panel_state.empty(reason=panel_state.REASON_NO_DATA)
    filtered = panel_state.empty(reason=panel_state.REASON_FILTER_NO_MATCH)
    pending = panel_state.empty(reason=panel_state.REASON_TASK_PENDING)

    actions = {first["action"], filtered["action"], pending["action"]}
    assert len(actions) == 3


def test_source_missing_is_unavailable_not_failed():
    """原件丢了是「不可用」，不是「失败」——重试没有用，得重新导入。"""
    payload = panel_state.unavailable(reason=panel_state.REASON_SOURCE_MISSING)

    assert payload["result"] == "unavailable"
    assert payload["action"] == panel_state.ACTION_IMPORT


def test_stale_offers_reimport():
    payload = panel_state.stale()

    assert payload["data"] == panel_state.DATA_STALE
    assert payload["action"] == panel_state.ACTION_IMPORT


def test_http_403_is_permission_not_failure():
    payload = panel_state.from_http(403)

    assert payload["result"] == "unavailable"
    assert payload["reason"] == panel_state.REASON_PERMISSION
    assert payload["action"] == panel_state.ACTION_GRANT_PERMISSION


def test_http_409_is_conflict():
    payload = panel_state.from_http(409)

    assert payload["reason"] == panel_state.REASON_CONFLICT


# ---------- 翻译 ----------


def test_paper_not_found_is_not_found():
    detail = "论文库中没有这篇论文: p1"
    status = classify(Exception(detail), detail)

    assert status["reason"] == panel_state.REASON_NOT_FOUND
    assert status["state"] == "first_load_failed"


def test_page_out_of_range_is_not_found():
    detail = "页码超出范围: 9（共 3 页）"
    status = classify(Exception(detail), detail)

    assert status["reason"] == panel_state.REASON_NOT_FOUND


def test_source_missing_classifies_as_unavailable():
    detail = "原文件已丢失，无法读取，也不会用旧数据代替"
    status = classify(Exception(detail), detail)

    assert status["result"] == "unavailable"
    assert status["reason"] == panel_state.REASON_SOURCE_MISSING


# ---------- 论文接口 ----------


def test_paper_api_carries_status_on_failure():
    client = _client(papers_api.router)

    resp = client.get("/api/papers/nope/pages/1")

    assert resp.status_code == 400
    payload = resp.json()
    assert payload["status"]["reason"] == panel_state.REASON_NOT_FOUND
    assert payload["status"]["state"] == "first_load_failed"


# ---------- 笔记接口 ----------


def test_revision_conflict_is_reported_as_conflict(notebook_home):
    client = _client(notebook_api.router)
    document = {
        "schema_version": 1,
        "title": "冲突测试",
        "blocks": [{"kind": "text", "attrs": {"text": "第一段"}}],
        "acceptance": "unverified",
    }
    client.post("/api/notebooks/nb1", json={"document": document})

    resp = client.post(
        "/api/notebooks/nb1", json={"document": document, "expected_revision": 0}
    )

    assert resp.status_code == 409
    body = resp.json()
    assert body["status"]["reason"] == panel_state.REASON_CONFLICT
    assert body["status"]["state"] == "first_load_failed"


def test_invalid_document_is_parse_failure(notebook_home):
    client = _client(notebook_api.router)

    resp = client.post(
        "/api/notebooks/nb2",
        json={"document": {"schema_version": 1, "blocks": [{"kind": "mystery"}]}},
    )

    assert resp.status_code == 400
    assert resp.json()["status"]["reason"] == panel_state.REASON_PARSE


# ---------- 数据接口 ----------


def test_missing_source_is_unavailable(data_home, tmp_path):
    """原文件丢了之后读这一版：不可用，而不是「失败后重试」。"""
    source = tmp_path / "rows.csv"
    source.write_text("name,score\nA,1\n", encoding="utf-8")
    imported = library.import_dataset(str(source))

    # 原件被移走：登记还在，原件不在了。
    os.unlink(os.path.join(library.files_root(), imported["asset"]["id"]))

    client = _client(data_api.router)
    resp = client.get(f"/api/data/datasets/{imported['dataset']['id']}/inspection")

    assert resp.status_code == 400
    body = resp.json()
    assert body["status"]["result"] == "unavailable"
    assert body["status"]["reason"] == panel_state.REASON_SOURCE_MISSING
    assert body["status"]["action"] == panel_state.ACTION_IMPORT


def test_unknown_dataset_is_not_found(data_home):
    client = _client(data_api.router)

    resp = client.get("/api/data/datasets/ds-nope/inspection")

    assert resp.status_code == 404
    assert resp.json()["status"]["reason"] == panel_state.REASON_NOT_FOUND
