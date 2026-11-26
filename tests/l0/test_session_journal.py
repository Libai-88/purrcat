"""分支 journal：增量追加、回放、压实、回退重建与 legacy 回退。"""

from __future__ import annotations

import json

import pytest

from src.agent import session_journal as journal_mod
from src.agent import session_store as store_mod
from src.agent.session_layout import branch_path
from src.agent.session_store import SessionStore

SESSION_ID = "session_jtest"


def _branch_file(root) -> str:
    return branch_path(str(root), SESSION_ID, "main")


def _msg(index: int, role: str = "user") -> dict:
    return {"role": role, "content": f"m{index}"}


def _snapshot(root) -> list:
    with open(_branch_file(root), "r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "SESSIONS_DIR", str(tmp_path))
    monkeypatch.setattr(store_mod, "SESSION_INDEX_PATH", str(tmp_path / "index.json"))
    # 关掉自动压实，让「追加」与「压实」两件事在测试里可分开观察。
    monkeypatch.setattr(journal_mod, "COMPACT_EVERY", 1000)
    monkeypatch.setattr(journal_mod, "COMPACT_INTERVAL_SECONDS", 10**6)
    monkeypatch.delenv("PURRCAT_STORE", raising=False)
    SessionStore._written.clear()
    SessionStore._compacted_at.clear()
    return tmp_path


def test_first_save_writes_full_snapshot(env):
    history = [_msg(i) for i in range(6)]
    SessionStore.save_session(SESSION_ID, history, consumed_tokens=0)

    assert _snapshot(env) == history
    assert journal_mod.line_count(_branch_file(env)) == 0


def test_second_save_appends_only_the_delta(env):
    history = [_msg(i) for i in range(6)]
    SessionStore.save_session(SESSION_ID, history, consumed_tokens=0)

    grown = history + [_msg(6), _msg(7)]
    SessionStore.save_session(SESSION_ID, grown, consumed_tokens=0)

    # snapshot 仍是旧长度，增量在 journal 里，读路径负责拼起来。
    assert len(_snapshot(env)) == 6
    assert journal_mod.line_count(_branch_file(env)) == 2
    assert SessionStore.load_session_history(SESSION_ID) == grown


def test_noop_save_does_not_touch_disk(env):
    history = [_msg(i) for i in range(4)]
    SessionStore.save_session(SESSION_ID, history, consumed_tokens=0)
    before = (
        _snapshot(env),
        journal_mod.line_count(_branch_file(env)),
    )

    SessionStore.save_session(SESSION_ID, list(history), consumed_tokens=0)
    after = (
        _snapshot(env),
        journal_mod.line_count(_branch_file(env)),
    )
    assert before == after


def test_compaction_folds_journal_into_snapshot(env, monkeypatch):
    monkeypatch.setattr(journal_mod, "COMPACT_EVERY", 2)
    history = [_msg(i) for i in range(3)]
    SessionStore.save_session(SESSION_ID, history, consumed_tokens=0)

    grown = history + [_msg(3), _msg(4)]
    SessionStore.save_session(SESSION_ID, grown, consumed_tokens=0)

    assert _snapshot(env) == grown
    assert journal_mod.line_count(_branch_file(env)) == 0


def test_rollback_rebuilds_snapshot(env):
    history = [_msg(i) for i in range(6)]
    SessionStore.save_session(SESSION_ID, history, consumed_tokens=0)

    short = history[:3]
    SessionStore.save_session(SESSION_ID, short, consumed_tokens=0)

    assert _snapshot(env) == short
    assert journal_mod.line_count(_branch_file(env)) == 0
    assert SessionStore.load_session_history(SESSION_ID) == short


def test_same_length_rewrite_rebuilds_snapshot(env):
    history = [_msg(i) for i in range(4)]
    SessionStore.save_session(SESSION_ID, history, consumed_tokens=0)

    rewritten = history[:3] + [{"role": "user", "content": "rewritten"}]
    SessionStore.save_session(SESSION_ID, rewritten, consumed_tokens=0)

    assert _snapshot(env) == rewritten
    assert journal_mod.line_count(_branch_file(env)) == 0


def test_legacy_mode_never_writes_journal(env, monkeypatch):
    monkeypatch.setenv("PURRCAT_STORE", "legacy")
    history = [_msg(i) for i in range(3)]
    SessionStore.save_session(SESSION_ID, history, consumed_tokens=0)
    grown = history + [_msg(3)]
    SessionStore.save_session(SESSION_ID, grown, consumed_tokens=0)

    assert _snapshot(env) == grown
    assert journal_mod.line_count(_branch_file(env)) == 0
    assert SessionStore.load_session_history(SESSION_ID) == grown


def test_corrupt_journal_line_is_skipped(env):
    history = [_msg(0)]
    SessionStore.save_session(SESSION_ID, history, consumed_tokens=0)
    grown = history + [_msg(1)]
    SessionStore.save_session(SESSION_ID, grown, consumed_tokens=0)

    with open(journal_mod.journal_path(_branch_file(env)), "a", encoding="utf-8") as h:
        h.write('{"i": 9, "m": \n')

    assert SessionStore.load_session_history(SESSION_ID) == grown


def test_out_of_order_journal_entry_stops_replay(env):
    history = [_msg(0), _msg(1)]
    SessionStore.save_session(SESSION_ID, history, consumed_tokens=0)

    with open(journal_mod.journal_path(_branch_file(env)), "w", encoding="utf-8") as h:
        h.write(json.dumps({"i": 5, "m": _msg(5)}) + "\n")

    # 跳号意味着中间缺口，宁可少读也不能拼错。
    assert SessionStore.load_session_history(SESSION_ID) == history


def test_delete_branch_clears_journal(env):
    history = [_msg(0), _msg(1)]
    SessionStore.save_session(SESSION_ID, history, branch_id="sub", consumed_tokens=0)

    sub_file = branch_path(str(env), SESSION_ID, "sub")
    with open(journal_mod.journal_path(sub_file), "w", encoding="utf-8") as h:
        h.write(json.dumps({"i": 2, "m": _msg(2)}) + "\n")

    assert SessionStore.delete_branch(SESSION_ID, "sub") is True
    assert journal_mod.line_count(sub_file) == 0
    assert f"{SESSION_ID}:sub" not in SessionStore._written
