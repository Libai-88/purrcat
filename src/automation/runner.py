"""自动化的执行器：到点把指示推给 Agent，并如实记下这次发生了什么。

三条规矩：

1. **先记后跑。** 触发之前先落一条 `queued` 回执，再去推 Agent。
   推失败或进程崩了，这次也已经被记下来了。
2. **Agent 忙就不推。** 忙的时候不排队、不堆积；下一次机会再来。
   这跟心跳那套「等空闲再注入」的做法一致（见 `src/agent/heartbeat.py`）。
3. **只报运行状态，不报结论可信度。** 回执说「跑完了 / 跑挂了」，
   不说「它核对的结果对不对」——那是 acceptance / verification 的事。
"""

from __future__ import annotations

import threading
import time

from src.automation import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    AutomationError,
    due,
    get_run,
    mark_triggered,
    record_run,
    update_run,
)

# 每秒看一次到点没到；跟心跳同一量级。
POLL_SECONDS = 1.0

# 等 Agent 空闲的最长时间：超过就不等了，这一轮留给下一次机会。
IDLE_WAIT_SECONDS = 30.0

# 推完之后等这一轮跑完的最长时间。
TURN_WAIT_SECONDS = 1800.0


def _agent_idle() -> bool:
    """Agent 现在空闲吗。拿不到 Agent 时按空闲算——那说明还没初始化。"""
    try:
        from src.agent.manager import manager as agent_manager

        agent = agent_manager._agent
        return agent is None or agent.state == "idle"
    except Exception:
        return True


def _wait_idle(timeout: float = IDLE_WAIT_SECONDS) -> bool:
    """等 Agent 空闲。等不到就返回 False。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _agent_idle():
            return True
        time.sleep(0.5)
    return False


def _session_id() -> str:
    try:
        from src.agent.manager import manager as agent_manager

        agent = agent_manager._agent
        return str(getattr(agent, "session_id", "") or "")
    except Exception:
        return ""


def _push(instruction: str) -> bool:
    """把指示推进 Agent 的当前会话。推不进去就返回 False。"""
    try:
        from src.agent.manager import manager as agent_manager

        agent_manager.agent_force_push(content=instruction, type="user")
        return True
    except Exception:
        return False


def _run_one(item: dict) -> dict:
    """跑一条自动化，返回它的回执。

    顺序很重要：先排队、再等空闲、再推、最后记结果。
    """
    instruction = str(item.get("instruction") or "")
    title = str(item.get("title") or item.get("id") or "")

    # 先记后跑：排上了就是排上了，别等跑完才留痕。
    run = record_run(item["id"], title, instruction, state=RUN_QUEUED)

    # 记下推送前的历史长度：这一轮判成败只看它之后新增的消息。
    before = _history_size()

    try:
        mark_triggered(item["id"])
    except AutomationError:
        pass

    if not _wait_idle():
        update_run(run["id"], RUN_FAILED, detail="等 Agent 空闲超时，这一轮没有跑")
        return get_run(run["id"])

    if not _push(instruction):
        update_run(run["id"], RUN_FAILED, detail="没能把指示推给 Agent")
        return get_run(run["id"])

    update_run(run["id"], RUN_RUNNING, session_id=_session_id())
    outcome = _wait_turn(before)
    update_run(run["id"], outcome["state"], detail=outcome["detail"])
    # 回读一次：update_run 是从磁盘重新读出来改的，手上这份是排队时的旧快照。
    return get_run(run["id"])


def _history_size() -> int:
    """现在历史里有多少条消息——用来只判这一轮、不算旧账。"""
    try:
        from src.agent.manager import manager as agent_manager

        agent = agent_manager._agent
        return len(agent.get_history()) if agent else 0
    except Exception:
        return 0


def _wait_turn(history_size: int = 0) -> dict:
    """等这一轮跑完，回报运行状态。

    **Agent 回到 idle 不等于这一轮成功。** 中途出错时历史里会留下一条
    ``[Error.Fault] 交互断层``，被强制打断时是 ``[Warn.Interrupt]``——
    看一眼这一轮最后一条 assistant 消息，才知道到底怎么样。

    也不能只看 idle：刚推完的那一刻 Agent 还没开始处理，也是 idle。
    所以要等到这一轮**真的产出了 assistant 消息**才下判断。
    """
    deadline = time.monotonic() + TURN_WAIT_SECONDS
    while time.monotonic() < deadline:
        if _agent_idle():
            verdict = _judge(history_size)
            if verdict is not None:
                return verdict
        time.sleep(0.5)
    return {"state": RUN_FAILED, "detail": "等了太久，这一轮还没结束"}


def _judge(history_size: int) -> dict | None:
    """看这一轮最后说了什么，判它是跑成了还是出了岔子。

    这一轮还没产出 assistant 消息时返回 None——说明它还没开始，
    不能因为「Agent 现在是 idle」就说它跑完了。
    """
    try:
        from src.agent.manager import manager as agent_manager

        agent = agent_manager._agent
        history = agent.get_history() if agent else []
    except Exception:
        return {"state": RUN_SUCCEEDED, "detail": "Agent 跑完了"}

    # 只看这一轮新产生的消息，别把上几轮的旧账算进来。
    fresh = history[history_size:] if history_size else history
    for message in reversed(fresh):
        if message.get("role") != "assistant":
            continue
        content = str(message.get("content") or "")
        if content.startswith("[Error.Fault]"):
            return {"state": RUN_FAILED, "detail": content[:200]}
        if content.startswith("[Warn.Interrupt]"):
            return {"state": RUN_CANCELLED, "detail": content[:200]}
        return {"state": RUN_SUCCEEDED, "detail": "Agent 跑完了"}
    # 这一轮还没说话：Agent 还没开始处理，或这一轮什么也没产出。
    return None


def run_due(now=None) -> list[dict]:
    """跑掉所有到点的自动化。

    Agent 忙的时候整轮跳过——这一轮不排队，等下一个机会。
    """
    results = []
    for item in due(now):
        if not _agent_idle():
            # 忙：这一轮不跑，也不留回执（没有真的排上什么）。
            continue
        results.append(_run_one(item))
    return results


def run_now(automation_id: str) -> dict:
    """手动触发一次。用来验证这条自动化确实能用。"""
    from src.automation import get_automation

    item = get_automation(automation_id)
    if item is None:
        raise AutomationError(f"没有这条自动化：{automation_id}")
    return _run_one(item)


class AutomationRunner:
    """后台线程：看着表，到点就跑。"""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="AutomationRunner"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                run_due()
            except Exception:
                # 一次失败不能让线程死掉：下个周期还要接着看表。
                pass
            self._stop.wait(POLL_SECONDS)


_RUNNER: AutomationRunner | None = None


def get_runner() -> AutomationRunner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = AutomationRunner()
    return _RUNNER
