"""环境接口与工具（SPEC-034）。

关键断言：探测是只读的，不改系统；接口形状稳定。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.api import environments_api
from src.tool.environments.environments import Environments


@pytest.fixture
def client(monkeypatch):
    """把探测换成可预测的假结果。"""
    import src.environments.observer as observer

    monkeypatch.setattr(observer, "_path", lambda: None)
    monkeypatch.setattr(observer.shutil, "which", lambda *a, **k: None)

    app = FastAPI()
    app.include_router(environments_api.router)
    return TestClient(app)


def test_list_tools_does_not_probe(client):
    """目录是静态的，读它不碰系统。"""
    response = client.get("/api/environments/tools")

    assert response.status_code == 200
    tools = response.json()["tools"]
    assert "python" in [item["id"] for item in tools]
    assert all("version" not in item for item in tools), "目录里不该有探测结果"


def test_observe_all_returns_three_state_records(client):
    response = client.get("/api/environments")

    assert response.status_code == 200
    payload = response.json()
    assert "exec_backend" in payload
    for record in payload["observations"].values():
        assert record["readiness"] in ("ready", "missing", "unknown")
        assert "acceptance" not in record
        assert "verification" not in record


def test_observe_single_tool(client):
    response = client.get("/api/environments/tools/git")

    assert response.status_code == 200
    assert response.json()["tool_id"] == "git"
    assert response.json()["readiness"] == "missing"


def test_unknown_tool_is_404(client):
    assert client.get("/api/environments/tools/not-a-tool").status_code == 404


def test_capabilities_route(client):
    response = client.get("/api/environments/capabilities")

    assert response.status_code == 200
    caps = response.json()["capabilities"]
    assert caps
    for cap in caps:
        assert "cannot" in cap


def test_single_capability_route(client):
    response = client.get("/api/environments/capabilities/process")

    assert response.status_code == 200
    assert response.json()["id"] == "process"
    assert client.get("/api/environments/capabilities/nope").status_code == 404


# ---------- Agent 工具 ----------


def test_tool_list_is_static(monkeypatch):
    import src.environments.observer as observer

    monkeypatch.setattr(
        observer,
        "observe_all",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("list 不该触发探测")),
    )

    result = Environments(action="list")

    assert "Python" in result["content"]
    assert "目录" in result["content"]


def test_tool_capabilities_says_what_cannot_be_implied():
    result = Environments(action="capabilities", capability_id="process")

    assert "不能推出" in result["content"]


def test_tool_observe_has_no_verdict_fields(monkeypatch):
    import src.environments.observer as observer

    monkeypatch.setattr(observer, "_path", lambda: None)
    monkeypatch.setattr(observer.shutil, "which", lambda *a, **k: None)

    result = Environments(action="observe", tool_id="git")

    assert "缺失" in result["content"]
    assert "acceptance" not in result["content"]
