"""科研自动化：到点让 Agent 跑一次，并留下回执。

与 `Cron` 闹钟的区别：闹钟只记着「明天 08:30 提醒我」，自动化到点**真的会让
Agent 跑一段指示**，并留下一条回执说明这次实际发生了什么。

回执最要紧的不变量（借自 Pero 的自动化设计）：

    排上了 ≠ 跑完了，跑完了 ≠ 结论对。

所以回执只用「运行状态」这一套词表，不带 acceptance / verification——
「任务跑完了」和「它核对的结果可信」是两件事，各有各的词表。
"""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone

from src.tool.cron.cron_rules import (
    is_valid_repeat_rule,
    is_valid_trigger_time,
    next_run_time,
)
from src.utils._fs import read_json, write_json_atomic
from src.utils.config import AGENT_CORE_DIR

AUTOMATIONS_FILE = os.path.join(AGENT_CORE_DIR, "automations.json")

# —— 运行状态（封闭词表）——
# queued   —— 已排上，但 Agent 还没真的开始跑
# running  —— Agent 正在跑这一条
# succeeded—— 这一条跑完了，中途没有报错
# failed   —— 这一条跑完了，但中途出错
# cancelled—— 这一条被取消，没有跑完
RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"

RUN_VALUES = (
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    RUN_FAILED,
    RUN_CANCELLED,
)

# 终态：跑完了（不管成没成）就不再变化
RUN_TERMINAL = (RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED)

# 回执上限：只追加，超了丢最老的
MAX_RUNS = 200

_LOCK = threading.RLock()


class AutomationError(Exception):
    """自动化定义不合法。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read() -> dict:
    data = read_json(AUTOMATIONS_FILE, default=None)
    if not isinstance(data, dict):
        return {"automations": [], "runs": []}
    data.setdefault("automations", [])
    data.setdefault("runs", [])
    return data


def _write(data: dict) -> None:
    os.makedirs(os.path.dirname(AUTOMATIONS_FILE), exist_ok=True)
    write_json_atomic(AUTOMATIONS_FILE, data)


# —— 定义 ——


def create(
    title: str,
    instruction: str,
    trigger_time: str,
    repeat_rule: str = "none",
    enabled: bool = True,
    now: datetime | None = None,
) -> dict:
    """建一条自动化。

    ``instruction`` 是到点后推给 Agent 的那段指示。
    ``now`` 只给测试用：默认按当前时刻算下一次触发。
    """
    title = (title or "").strip()
    instruction = (instruction or "").strip()
    if not title:
        raise AutomationError("自动化需要一个名字")
    if not instruction:
        raise AutomationError("自动化需要一段指示，否则到点也不知道让 Agent 做什么")
    if not is_valid_trigger_time(trigger_time):
        raise AutomationError(f"时间格式错误：{trigger_time!r}，要用 HH:MM")
    if not is_valid_repeat_rule(repeat_rule):
        raise AutomationError(f"重复规则非法：{repeat_rule!r}")

    with _LOCK:
        data = _read()
        item = {
            "id": "auto_" + uuid.uuid4().hex[:8],
            "title": title,
            "instruction": instruction,
            "trigger_time": trigger_time,
            "repeat_rule": repeat_rule,
            "enabled": bool(enabled),
            "created_at": _now(),
            "next_run_at": None,
            "last_run_at": None,
        }
        item["next_run_at"] = _next_at(item, now=now)
        data["automations"].append(item)
        _write(data)
        return item


def _next_at(item: dict, now: datetime | None = None) -> str | None:
    moment = next_run_time(
        item.get("trigger_time", ""), item.get("repeat_rule", "none"), now=now
    )
    if moment is None:
        return None
    # 时间规则算出来的是本地 naive 时刻；统一按 UTC 存，免得跟别处比较时错位。
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def list_automations() -> list[dict]:
    """列出全部自动化。"""
    with _LOCK:
        return list(_read()["automations"])


def get_automation(automation_id: str) -> dict | None:
    for item in list_automations():
        if item.get("id") == automation_id:
            return item
    return None


def update(
    automation_id: str,
    title: str | None = None,
    instruction: str | None = None,
    trigger_time: str | None = None,
    repeat_rule: str | None = None,
    enabled: bool | None = None,
) -> dict:
    """改一条自动化。

    改了触发时刻或重复规则就重算下一次触发时刻；只是停用则保留原时刻，
    重新启用时再算。
    """
    with _LOCK:
        data = _read()
        for item in data["automations"]:
            if item.get("id") != automation_id:
                continue
            if title is not None:
                title = title.strip()
                if not title:
                    raise AutomationError("自动化需要一个名字")
                item["title"] = title
            if instruction is not None:
                instruction = instruction.strip()
                if not instruction:
                    raise AutomationError("自动化需要一段指示")
                item["instruction"] = instruction
            if trigger_time is not None:
                if not is_valid_trigger_time(trigger_time):
                    raise AutomationError(f"时间格式错误：{trigger_time!r}，要用 HH:MM")
                item["trigger_time"] = trigger_time
            if repeat_rule is not None:
                if not is_valid_repeat_rule(repeat_rule):
                    raise AutomationError(f"重复规则非法：{repeat_rule!r}")
                item["repeat_rule"] = repeat_rule
            if enabled is not None:
                item["enabled"] = bool(enabled)
            if (
                trigger_time is not None
                or repeat_rule is not None
                or enabled is not None
            ):
                item["next_run_at"] = _next_at(item) if item["enabled"] else None
            _write(data)
            return item
    raise AutomationError(f"没有这条自动化：{automation_id}")


def delete(automation_id: str) -> dict:
    """删掉一条自动化。已经跑完的回执留着——那是历史，不是这条定义。"""
    with _LOCK:
        data = _read()
        for index, item in enumerate(data["automations"]):
            if item.get("id") == automation_id:
                removed = data["automations"].pop(index)
                _write(data)
                return {"id": removed["id"], "title": removed.get("title", "")}
    raise AutomationError(f"没有这条自动化：{automation_id}")


def due(now: datetime | None = None) -> list[dict]:
    """到点、且处于启用状态的自动化。

    到点的判据是「下一次触发时刻已经到了或已经过去」——
    进程停机期间错过的那几个时刻，醒来后只补跑一次，不堆一堆。
    """
    moment = now or datetime.now(timezone.utc)
    ready = []
    for item in list_automations():
        if not item.get("enabled"):
            continue
        next_at = item.get("next_run_at")
        if not next_at:
            continue
        try:
            due_at = datetime.fromisoformat(next_at)
        except ValueError:
            continue
        if due_at <= moment:
            ready.append(item)
    return ready


def mark_triggered(automation_id: str) -> dict:
    """记下「刚刚触发过」，并把下一次触发时刻往后推。

    先记后跑：即使 Agent 那一步出问题，这次也已经被记下来了，
    不会因为一次崩溃就丢掉一次触发。
    """
    with _LOCK:
        data = _read()
        for item in data["automations"]:
            if item.get("id") != automation_id:
                continue
            item["last_run_at"] = _now()
            item["next_run_at"] = _next_at(item)
            _write(data)
            return item
    raise AutomationError(f"没有这条自动化：{automation_id}")


# —— 回执 ——


def record_run(
    automation_id: str,
    title: str,
    instruction: str,
    state: str = RUN_QUEUED,
    detail: str = "",
    session_id: str = "",
) -> dict:
    """记一条回执。

    ``state`` 是运行状态，不是结论可信度；回执里也不带 acceptance。
    """
    if state not in RUN_VALUES:
        raise AutomationError(f"运行状态非法：{state!r}")
    with _LOCK:
        data = _read()
        run = {
            "id": "run_" + uuid.uuid4().hex[:8],
            "automation_id": automation_id,
            "title": title,
            "instruction": instruction,
            "state": state,
            "detail": detail,
            "session_id": session_id,
            "queued_at": _now(),
            "started_at": "",
            "finished_at": "",
        }
        data["runs"].append(run)
        if len(data["runs"]) > MAX_RUNS:
            data["runs"] = data["runs"][-MAX_RUNS:]
        _write(data)
        return run


def update_run(run_id: str, state: str, detail: str = "", session_id: str = "") -> dict:
    """推进一条回执的状态。

    终态不再变——已经跑完的事情不会被后来的事件改写。
    """
    if state not in RUN_VALUES:
        raise AutomationError(f"运行状态非法：{state!r}")
    with _LOCK:
        data = _read()
        for run in data["runs"]:
            if run.get("id") != run_id:
                continue
            if run.get("state") in RUN_TERMINAL:
                return run
            run["state"] = state
            if detail:
                run["detail"] = detail
            if session_id:
                run["session_id"] = session_id
            if state == RUN_RUNNING and not run.get("started_at"):
                run["started_at"] = _now()
            if state in RUN_TERMINAL:
                run["finished_at"] = _now()
            _write(data)
            return run
    raise AutomationError(f"没有这条回执：{run_id}")


def list_runs(automation_id: str = "", limit: int = 50) -> list[dict]:
    """列回执，新的在前。"""
    with _LOCK:
        runs = list(_read()["runs"])
    if automation_id:
        runs = [run for run in runs if run.get("automation_id") == automation_id]
    runs.reverse()
    return runs[: max(0, int(limit))]


def get_run(run_id: str) -> dict | None:
    for run in list_runs(limit=MAX_RUNS):
        if run.get("id") == run_id:
            return run
    return None


def counts() -> dict:
    """按状态数一数回执。"""
    tally = {state: 0 for state in RUN_VALUES}
    for run in list_runs(limit=MAX_RUNS):
        tally[run.get("state", RUN_QUEUED)] = (
            tally.get(run.get("state", RUN_QUEUED), 0) + 1
        )
    return tally
