"""会话级能力快照：模式映射、老会话不砍能力、meta 只写一次。"""

from __future__ import annotations

import pytest

from src.agent import capabilities
from src.agent import session_store as store_mod
from src.agent.session_layout import meta_path, read_json
from src.agent.session_store import SessionStore
from src.tool.registry import ALL_CAPABILITIES, CORE, RESEARCH

SESSION_ID = "session_cap01"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "SESSIONS_DIR", str(tmp_path))
    monkeypatch.setattr(store_mod, "SESSION_INDEX_PATH", str(tmp_path / "index.json"))
    import src.utils.config as config_mod

    monkeypatch.setattr(config_mod, "SESSIONS_DIR", str(tmp_path))
    SessionStore._written.clear()
    SessionStore._compacted_at.clear()
    return tmp_path


def _meta(root) -> dict:
    return read_json(meta_path(str(root), SESSION_ID)) or {}


def test_mode_mapping():
    assert capabilities.capabilities_for_mode("work") == [CORE]
    assert capabilities.capabilities_for_mode("science") == [CORE, RESEARCH]
    assert capabilities.capabilities_for_mode("SCIENCE ") == [CORE, RESEARCH]


def test_unknown_mode_keeps_full_capabilities():
    assert capabilities.capabilities_for_mode("") == list(ALL_CAPABILITIES)
    assert capabilities.capabilities_for_mode("layout-v2") == list(ALL_CAPABILITIES)
    assert capabilities.capabilities_for_mode(None) == list(ALL_CAPABILITIES)


def test_legacy_session_without_snapshot_gets_everything(env):
    SessionStore.save_session(SESSION_ID, [{"role": "user", "content": "hi"}])
    assert "capabilities" not in _meta(env)
    assert capabilities.resolve(SESSION_ID) == list(ALL_CAPABILITIES)


def test_resolve_reads_the_snapshot(env):
    SessionStore.save_session(
        SESSION_ID,
        [{"role": "user", "content": "hi"}],
        mode="work",
        capabilities=[CORE],
    )
    assert capabilities.resolve(SESSION_ID) == [CORE]
    assert _meta(env)["mode"] == "work"


def test_later_saves_do_not_overwrite_the_snapshot(env):
    history = [{"role": "user", "content": "hi"}]
    SessionStore.save_session(SESSION_ID, history, mode="work", capabilities=[CORE])
    SessionStore.save_session(
        SESSION_ID, history + [{"role": "assistant", "content": "yo"}]
    )

    meta = _meta(env)
    assert meta["capabilities"] == [CORE]
    assert meta["mode"] == "work"


def test_snapshot_uses_current_mode(env, monkeypatch):
    monkeypatch.setattr(capabilities, "current_mode", lambda: "work")
    snap = capabilities.snapshot()
    assert snap == {"mode": "work", "capabilities": [CORE]}


def test_snapshot_without_mode_is_full(env, monkeypatch):
    monkeypatch.setattr(capabilities, "current_mode", lambda: "")
    snap = capabilities.snapshot()
    assert snap["capabilities"] == list(ALL_CAPABILITIES)
