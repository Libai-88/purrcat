"""会话写路径的崩溃恢复：进程重启、半行、跳号都不能拼出错误历史（SPEC-006 / Phase 1）。

这些用例走真实文件 IO（不是内存 mock）：先按 journal 模式写盘，清掉进程内的记账
（等价于进程被杀后重启），再从磁盘读回。断言的是"重启后历史仍然完整"这件事本身。
"""

from __future__ import annotations

import json
import os

from src.agent import session_journal as journal
from src.agent import session_store as store_mod


def _msgs(count, start=0):
    return [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "id": f"m{i}",
            "content": "x" * 40,
        }
        for i in range(start, start + count)
    ]


def _prepare(tmp_path, monkeypatch, mode="journal"):
    monkeypatch.setattr(store_mod, "SESSIONS_DIR", str(tmp_path))
    monkeypatch.setenv("PURRCAT_STORE", mode)
    store_mod.SessionStore._written.clear()
    store_mod.SessionStore._compacted_at.clear()
    directory = tmp_path / "session_crash"
    os.makedirs(directory, exist_ok=True)
    return str(directory / "main.json")


def _simulate_restart():
    """进程重启：内存里的"已写到第几条"全部丢失，只能靠磁盘重建。"""
    store_mod.SessionStore._written.clear()
    store_mod.SessionStore._compacted_at.clear()


def test_restart_replays_snapshot_plus_journal(tmp_path, monkeypatch):
    path = _prepare(tmp_path, monkeypatch)
    history = _msgs(10)
    store_mod.SessionStore._write_branch("session_crash", "main", path, history)

    history = history + _msgs(10, 10)
    store_mod.SessionStore._write_branch("session_crash", "main", path, history)
    assert journal.line_count(path) == 10

    _simulate_restart()
    restored = store_mod.SessionStore.load_session_history("session_crash", "main")
    assert len(restored) == 20
    assert [m["id"] for m in restored] == [f"m{i}" for i in range(20)]


def test_truncated_journal_line_is_dropped(tmp_path, monkeypatch):
    path = _prepare(tmp_path, monkeypatch)
    history = _msgs(10)
    store_mod.SessionStore._write_branch("session_crash", "main", path, history)
    history = history + _msgs(5, 10)
    store_mod.SessionStore._write_branch("session_crash", "main", path, history)

    # 模拟崩溃：最后一行只写了一半
    with open(journal.journal_path(path), "a", encoding="utf-8") as handle:
        handle.write('{"i":15,"m":{"role":"user","id":"m15","con')
    _simulate_restart()

    restored = store_mod.SessionStore.load_session_history("session_crash", "main")
    assert len(restored) == 15
    assert restored[-1]["id"] == "m14"


def test_gap_in_journal_stops_replay(tmp_path, monkeypatch):
    path = _prepare(tmp_path, monkeypatch)
    history = _msgs(10)
    store_mod.SessionStore._write_branch("session_crash", "main", path, history)
    history = history + _msgs(5, 10)
    store_mod.SessionStore._write_branch("session_crash", "main", path, history)

    # 模拟"序号断了"：把 seq=15 的帧改成 seq=19，回放必须停在前一条，而不是跳着拼
    lines = open(journal.journal_path(path), encoding="utf-8").read().splitlines()
    lines[-1] = json.dumps(
        {"i": 19, "m": {"role": "user", "id": "m19", "content": "x" * 40}},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    with open(journal.journal_path(path), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    _simulate_restart()

    restored = store_mod.SessionStore.load_session_history("session_crash", "main")
    assert len(restored) == 14


def test_rebuild_after_rollback_discards_stale_journal(tmp_path, monkeypatch):
    path = _prepare(tmp_path, monkeypatch)
    history = _msgs(12)
    store_mod.SessionStore._write_branch("session_crash", "main", path, history)
    history = history + _msgs(6, 12)
    store_mod.SessionStore._write_branch("session_crash", "main", path, history)

    # 用户回滚到第 8 条：前缀变化 → 必须重建 snapshot 并清 journal
    store_mod.SessionStore._write_branch("session_crash", "main", path, history[:8])
    assert journal.line_count(path) == 0
    snap = json.loads(open(path, encoding="utf-8").read())
    assert len(snap) == 8

    _simulate_restart()
    restored = store_mod.SessionStore.load_session_history("session_crash", "main")
    assert len(restored) == 8


def test_legacy_mode_never_writes_journal(tmp_path, monkeypatch):
    path = _prepare(tmp_path, monkeypatch, mode="legacy")
    history = _msgs(6)
    store_mod.SessionStore._write_branch("session_crash", "main", path, history)
    assert not os.path.exists(journal.journal_path(path))
    _simulate_restart()
    assert (
        len(store_mod.SessionStore.load_session_history("session_crash", "main")) == 6
    )
