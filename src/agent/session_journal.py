"""分支历史的追加日志（journal）。

取舍：snapshot（``<branch>.json``）仍是完整 JSON 数组，任何不认识 journal 的读方
都不会读到半截数据；journal（``<branch>.journal.jsonl``）只承载 snapshot 之后的
增量，每行一个带序号的消息。序号让回放只接受「紧接 snapshot 末尾」的连续段，
半行与脏行一律丢弃，而不是拼出一段错误历史。
"""

from __future__ import annotations

import json
import os

JOURNAL_SUFFIX = ".journal.jsonl"
# 🌟 压实阈值：超过任一条件就把 journal 折叠进 snapshot，避免回放无限变长。
COMPACT_EVERY = 200
COMPACT_INTERVAL_SECONDS = 30.0


def journal_path(branch_file: str) -> str:
    return f"{branch_file}{JOURNAL_SUFFIX}"


def append(branch_file: str, entries, start_index: int) -> int:
    """把 ``entries`` 从序号 ``start_index`` 起追加到 journal，返回写入行数。"""

    if not entries:
        return 0
    path = journal_path(branch_file)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    written = 0
    with open(path, "a", encoding="utf-8") as handle:
        for offset, message in enumerate(entries):
            line = json.dumps(
                {"i": start_index + offset, "m": message},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            handle.write(line + "\n")
            written += 1
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    return written


def read(branch_file: str) -> list[dict]:
    """读取 journal；文件缺失或单行损坏都不抛出。"""

    path = journal_path(branch_file)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return []

    entries: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("i"), int):
            entries.append(entry)
    return entries


def replay(snapshot, entries: list[dict]):
    """把连续增量接到 snapshot 之后；跳号视作脏数据，直接停在那里。"""

    result = list(snapshot)
    for entry in sorted(entries, key=lambda item: item["i"]):
        if entry["i"] == len(result):
            result.append(entry.get("m"))
    return result


def line_count(branch_file: str) -> int:
    path = journal_path(branch_file)
    try:
        with open(path, "rb") as handle:
            return handle.read().count(b"\n")
    except OSError:
        return 0


def clear(branch_file: str) -> None:
    try:
        os.unlink(journal_path(branch_file))
    except OSError:
        pass
