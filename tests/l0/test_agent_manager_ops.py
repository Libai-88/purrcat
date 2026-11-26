"""AgentManager 会话切换原子操作与会话删除（SPEC-006）。"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

from src.agent import session_store
from src.agent.manager import AgentManager
from src.agent.session_store import SessionStore


def test_wait_until_idle_returns_immediately_when_idle():
    manager = object.__new__(AgentManager)
    manager._agent = SimpleNamespace(state="idle")

    manager._wait_until_idle("waiting")


def test_wait_until_idle_waits_for_idle():
    manager = object.__new__(AgentManager)
    manager._agent = SimpleNamespace(state="handling")

    calls = []

    def fake_wait(timeout=None):
        calls.append(timeout)
        manager._agent.state = "idle"
        return True

    manager._agent.wait_until_idle = fake_wait

    assert manager._wait_until_idle("waiting") is True
    assert calls, "忙等必须真正走一次等待，而不是直接跳过"


def test_wait_until_idle_reports_timeout():
    manager = object.__new__(AgentManager)
    manager._agent = SimpleNamespace(
        state="handling", wait_until_idle=lambda t=None: False
    )

    assert manager._wait_until_idle("waiting", timeout=0.1) is False


def test_adopt_session_switches_all_fields_under_lock():
    manager = object.__new__(AgentManager)
    lock = threading.RLock()
    manager._agent = SimpleNamespace(
        session_id="old",
        current_history=[],
        window_token=1,
        consumed_tokens=2,
        _history_lock=lock,
    )
    history = [{"role": "system", "content": "s"}]

    manager._adopt_session("new", history, 10, 20)

    assert manager._agent.session_id == "new"
    assert manager._agent.current_history is history
    assert manager._agent.window_token == 10
    assert manager._agent.consumed_tokens == 20


def test_session_store_delete_removes_dir_and_index(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    session_dir = sessions_dir / "session_x"
    session_dir.mkdir(parents=True)
    (session_dir / "meta.json").write_text("{}", encoding="utf-8")
    index_path = sessions_dir / "index.json"
    index_path.write_text(
        json.dumps({"session_x": {"alias": "x"}, "session_y": {"alias": "y"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(session_store, "SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(session_store, "SESSION_INDEX_PATH", str(index_path))

    SessionStore.delete_session("session_x")

    assert not session_dir.exists()
    assert json.loads(index_path.read_text(encoding="utf-8")) == {
        "session_y": {"alias": "y"}
    }


def test_session_store_delete_is_idempotent_for_missing_session(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    index_path = sessions_dir / "index.json"
    index_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(session_store, "SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(session_store, "SESSION_INDEX_PATH", str(index_path))

    SessionStore.delete_session("session_missing")

    assert json.loads(index_path.read_text(encoding="utf-8")) == {}
