"""空闲事件：state 跃迁驱动唤醒，忙等不再空转 CPU，超时能给明确结果。"""

from __future__ import annotations

import threading
import time

from src.agent.agent import Agent


def _probe() -> Agent:
    """只装被测算状态的壳，绕开模型/记忆等重依赖。"""

    agent = Agent.__new__(Agent)
    agent._state = "idle"
    agent._idle_event = threading.Event()
    agent._idle_event.set()
    agent._busy_since = None
    return agent


def test_idle_state_sets_the_event():
    agent = _probe()
    agent.state = "handling"
    assert not agent._idle_event.is_set()

    agent.state = "idle"
    assert agent._idle_event.is_set()


def test_busy_since_tracks_the_first_transition_only():
    agent = _probe()
    agent.state = "handling"
    first = agent._busy_since
    assert isinstance(first, float)

    agent.state = "processing"
    assert agent._busy_since == first

    agent.state = "idle"
    assert agent._busy_since is None


def test_wait_returns_true_immediately_when_idle():
    agent = _probe()
    assert agent.wait_until_idle(1.0) is True


def test_wait_returns_false_on_timeout():
    agent = _probe()
    agent.state = "handling"
    started = time.monotonic()
    assert agent.wait_until_idle(0.2) is False
    assert time.monotonic() - started < 1.0


def test_wait_wakes_up_when_state_returns_to_idle():
    agent = _probe()
    agent.state = "handling"

    def release() -> None:
        time.sleep(0.25)
        agent.state = "idle"

    threading.Thread(target=release, daemon=True).start()
    assert agent.wait_until_idle(3.0) is True


def test_wait_without_timeout_is_event_driven_not_spinning():
    agent = _probe()
    agent.state = "handling"

    def release() -> None:
        time.sleep(0.2)
        agent.state = "idle"

    threading.Thread(target=release, daemon=True).start()
    # 1 秒足够：纯轮询版本也能过，但事件版不会在这 1 秒里空转上千次。
    assert agent.wait_until_idle(None) is True
