"""并发/忙时接口契约的 L0 用例（SPEC-022）。

Phase 3 把等待改成事件驱动后，"Agent 忙到超时"从原来的静默放弃变成可判定的返回值。
这些用例锁住 HTTP 层的出口：切会话失败是 409、新建/分支超时是 409，而不是 200 假成功。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.server.api import chat


@pytest.fixture(autouse=True)
def _no_manager_init(monkeypatch):
    """端点内部会真实初始化 AgentManager（读盘 + 起线程），单测里必须掐掉。"""
    monkeypatch.setattr(chat, "_ensure_manager_initialized", lambda: None)


def test_checkout_returns_ok_when_switch_succeeds(monkeypatch):
    import src.agent

    monkeypatch.setattr(src.agent, "switch_session", lambda sid: True)

    assert chat.checkout_session_api("session_abc") == {"status": "ok"}


def test_checkout_reports_409_when_agent_still_busy(monkeypatch):
    """switch_session 返回 False 表示没有真的切过去，必须让调用方看到失败。"""
    import src.agent

    monkeypatch.setattr(src.agent, "switch_session", lambda sid: False)

    with pytest.raises(HTTPException) as exc:
        chat.checkout_session_api("session_abc")

    assert exc.value.status_code == 409
    assert "仍在处理上一轮" in exc.value.detail


def test_checkout_rejects_malformed_session_id():
    with pytest.raises(HTTPException) as exc:
        chat.checkout_session_api("requests")

    assert exc.value.status_code == 400


def test_new_session_maps_timeout_to_409(monkeypatch):
    def _boom(**kwargs):
        raise TimeoutError("Agent 仍在处理上一个请求，请稍后新建会话")

    monkeypatch.setattr(chat, "new_session", _boom)

    with pytest.raises(HTTPException) as exc:
        chat.create_new_session(chat.NewSessionReq(alias="probe"))

    assert exc.value.status_code == 409
    assert "请稍后新建会话" in exc.value.detail


def test_branch_session_maps_timeout_to_409(monkeypatch):
    import src.agent

    monkeypatch.setattr(src.agent, "switch_session", lambda sid: True)

    def _boom(**kwargs):
        raise TimeoutError("Agent 仍在处理上一个请求，请稍后创建分支")

    monkeypatch.setattr(chat, "branch_session", _boom, raising=False)
    monkeypatch.setattr(src.agent, "branch_session", _boom)

    with pytest.raises(HTTPException) as exc:
        chat.branch_session_api("session_abc", chat.BranchSessionReq(alias="sub"))

    assert exc.value.status_code == 409
    assert "请稍后创建分支" in exc.value.detail


def test_chat_endpoint_returns_processing_even_while_busy(monkeypatch):
    """忙时发消息不被拒：入队后立刻返回 processing，排队深度由 /status 透出。"""

    class _BG:
        def __init__(self):
            self.tasks = []

        def add_task(self, fn, *args, **kwargs):
            self.tasks.append((fn, args))

    bg = _BG()
    out = chat.chat(chat.ChatReq(session_id="session_abc", message="hi"), bg)

    assert out["status"] == "processing"
    assert len(bg.tasks) == 1
    assert bg.tasks[0][1][0] == "session_abc"
