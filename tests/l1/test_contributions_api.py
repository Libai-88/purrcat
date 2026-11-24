"""贡献工作区的接口（SPEC-035）。

发布是对外动作，测试里用假 ops，不打真实 GitHub。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.contributions import store
from src.server.api import contributions_api
from src.tool.contributions.contributions import Contributions


@pytest.fixture
def contribution_home(tmp_path, monkeypatch):
    import src.utils.config as config
    import src.contributions.store as store_module

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        store_module, "store_root", lambda: str(tmp_path / "data" / "contributions")
    )
    return tmp_path


@pytest.fixture
def client(contribution_home):
    app = FastAPI()
    app.include_router(contributions_api.router)
    return TestClient(app)


def _prepare(client):
    return client.post(
        "/api/contributions/prepare",
        json={
            "task_id": "t1",
            "repository": "o/r",
            "workspace": "/tmp/ws",
            "title": "修一处口径",
        },
    ).json()


def test_prepare_and_list(client, contribution_home):
    created = _prepare(client)
    assert created["status"] == "prepared"

    listing = client.get("/api/contributions").json()
    assert len(listing["contributions"]) == 1


def test_read_unknown_is_404(client, contribution_home):
    assert client.get("/api/contributions/nope").status_code == 404


def test_review_produces_a_token(client, contribution_home):
    _prepare(client)
    response = client.post("/api/contributions/t1/review")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "review"
    assert data["review_token"]
    # 没有 ops 时 diff 是空的，但 token 还是能算出来。
    assert "acceptance" not in data
    assert "verification" not in data


def test_ready_with_wrong_token_is_409(client, contribution_home):
    _prepare(client)
    client.post("/api/contributions/t1/review")

    response = client.post(
        "/api/contributions/t1/ready", json={"review_token": "wrong"}
    )

    assert response.status_code == 409


def test_publish_uses_draft_command(client, contribution_home, monkeypatch):
    """发布只走草稿命令；用假 ops，不碰 GitHub。"""
    import src.contributions.store as store_module

    class FakeOps:
        def find_open_pr(self, repository, branch):
            return ""

        def gh_available(self):
            return True

        def gh_authenticated(self):
            return True

        def prepare_publish_command(self, repository, branch, title):
            return f"gh pr create --draft --repo {repository} --head {branch}"

    monkeypatch.setattr(store_module.gitops, "RealGitOps", FakeOps)
    _prepare(client)
    reviewed = client.post("/api/contributions/t1/review").json()
    client.post(
        "/api/contributions/t1/ready", json={"review_token": reviewed["review_token"]}
    )

    response = client.post(
        "/api/contributions/t1/publish",
        json={"review_token": reviewed["review_token"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "published"
    assert "--draft" in data["publish_command"]


def test_release_keeps_local_work(client, contribution_home):
    _prepare(client)
    client.post("/api/contributions/t1/review")

    response = client.post("/api/contributions/t1/release")

    assert response.status_code == 200
    assert response.json()["status"] == "released"
    assert store.get("t1")["workspace"] == "/tmp/ws"


# ---------- Agent 工具 ----------


def test_tool_start_returns_the_no_publish_instruction(contribution_home):
    Contributions(
        action="prepare",
        task_id="t1",
        repository="o/r",
        workspace="/tmp/ws",
        title="标题",
    )

    result = Contributions(action="start", task_id="t1")

    assert "不要" in result["content"]
    assert "pull request" in result["content"]


def test_tool_review_returns_a_token(contribution_home):
    Contributions(
        action="prepare",
        task_id="t2",
        repository="o/r",
        workspace="/tmp/ws",
        title="标题",
    )

    result = Contributions(action="review", task_id="t2")

    assert "review token" in result["content"]


def test_tool_publish_needs_a_token(contribution_home):
    Contributions(
        action="prepare",
        task_id="t3",
        repository="o/r",
        workspace="/tmp/ws",
        title="标题",
    )

    result = Contributions(action="publish", task_id="t3")

    assert "review_token" in result["content"]
