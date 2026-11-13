"""执行后端切换 API（SPEC-024 AC-6）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server.api import config as config_api


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(config_api.router)
    return TestClient(app)


def test_get_reports_local_backend(client, monkeypatch):
    """默认配置下 GET 返回本地执行，且本机 shell 可用。"""
    monkeypatch.delenv("PURRCAT_EXEC_BACKEND", raising=False)
    monkeypatch.setattr("src.utils.config._read_settings", lambda: {})
    resp = client.get("/api/config/exec")
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "local"
    assert body["local_ready"] is True
    assert body["env_override"] is False


def test_put_rejects_unknown_backend(client, monkeypatch):
    monkeypatch.delenv("PURRCAT_EXEC_BACKEND", raising=False)
    resp = client.put("/api/config/exec", json={"backend": "podman"})
    assert resp.status_code == 400


def test_put_rejects_when_env_var_wins(client, monkeypatch):
    """环境变量优先级高于界面开关，冲突时明确拒绝而不是静默失效。"""
    monkeypatch.setenv("PURRCAT_EXEC_BACKEND", "docker")
    resp = client.put("/api/config/exec", json={"backend": "local"})
    assert resp.status_code == 409


def test_put_persists_and_rebuilds_backend(client, monkeypatch):
    monkeypatch.delenv("PURRCAT_EXEC_BACKEND", raising=False)
    saved: dict = {}

    def _save(key, value):
        saved[key] = value
        return True

    called: dict = {}
    monkeypatch.setattr(config_api, "save_global_setting", _save)
    monkeypatch.setattr(
        "src.tool.bash.backends.reset_backend", lambda: called.setdefault("done", True)
    )

    resp = client.put("/api/config/exec", json={"backend": "docker"})
    assert resp.status_code == 200
    assert resp.json()["backend"] == "docker"
    assert saved["exec_backend"] == "docker"
    assert called.get("done") is True
