"""请求预算：rpm / tpm 真的会阻塞（L0，注入假时钟，不真睡）。"""

from __future__ import annotations

import threading

import pytest

from src.model.manager import rate_limit


class FakeClock:
    """可控时钟 + 睡眠：sleep 直接推进时间，测试秒级跑完。"""

    def __init__(self):
        self.now = 0.0
        self.slept = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, seconds)
        self.slept += max(0.0, seconds)


def _budget(rpm=0, tpm=0):
    clock = FakeClock()
    budget = rate_limit.RequestBudget(
        rpm=rpm, tpm=tpm, clock=clock.monotonic, sleep=clock.sleep
    )
    return budget, clock


def test_disabled_budget_never_waits():
    budget, clock = _budget(rpm=0, tpm=0)
    assert budget.enabled is False
    assert budget.wait_seconds(10**9) == 0
    assert budget.reserve(10**9) == 0
    assert clock.slept == 0


def test_rpm_blocks_after_window_is_full():
    budget, clock = _budget(rpm=3)
    for _ in range(3):
        assert budget.reserve(0) == 0
    # 第 4 次必须等到窗口内第一条（t=0）滑出 60 s
    waited = budget.reserve(0)
    assert waited == pytest.approx(60.0)
    assert clock.now == pytest.approx(60.0)


def test_rpm_window_slides_gradually():
    budget, clock = _budget(rpm=1)
    budget.reserve(0)
    clock.now = 30.0
    assert budget.wait_seconds(0) == pytest.approx(30.0)
    budget.reserve(0)
    assert clock.now == pytest.approx(60.0)


def test_tpm_blocks_by_token_volume():
    budget, clock = _budget(tpm=1000)
    assert budget.reserve(400) == 0
    assert budget.reserve(400) == 0
    # 第三次需要腾出 200 token 的预算 → 等第一条（400）滑出窗口
    waited = budget.reserve(400)
    assert waited == pytest.approx(60.0)
    assert clock.now == pytest.approx(60.0)


def test_tpm_single_request_over_budget_does_not_hang():
    budget, _ = _budget(tpm=100)
    assert budget.reserve(500) == 0


def test_cancel_interrupts_wait():
    budget, _ = _budget(rpm=1)
    budget.reserve(0)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        budget.reserve(0, cancel)


def test_shared_budget_per_key_and_hot_reload(monkeypatch):
    rate_limit.reset_shared_budgets()
    a = rate_limit.get_shared_budget("sk-1", 10, 1000)
    b = rate_limit.get_shared_budget("sk-1", 10, 1000)
    c = rate_limit.get_shared_budget("sk-2", 10, 1000)
    assert a is b
    assert a is not c
    assert rate_limit.get_shared_budget("sk-1", 20, 2000).rpm == 20
    rate_limit.reset_shared_budgets()
    assert rate_limit.get_shared_budget("sk-1", 10, 1000) is not a
