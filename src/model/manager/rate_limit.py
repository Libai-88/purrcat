"""请求预算：把配置里的 ``rpm`` / ``tpm`` 变成真实的阻塞等待。

背景：配置中心一直让用户填 RPM / TPM / 并发数，但运行时只读了 ``limits.concurrency``，
``rpm`` 与 ``tpm`` 从来没被消费——填了等于没填。这里补上最小可用的实现：
60 秒滑动窗口，rpm 限制请求条数、tpm 限制 token 总量；取 0 表示不限。

取消友好：等待按 0.5 s 分段，收到 ``cancel_event`` 立即放弃，避免打断后还要
傻等到窗口滑出。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Optional, Tuple

WINDOW_SECONDS = 60.0


class RequestBudget:
    """线程安全的 60 s 滑动窗口预算。"""

    def __init__(
        self,
        rpm: int = 0,
        tpm: int = 0,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.rpm = max(0, int(rpm or 0))
        self.tpm = max(0, int(tpm or 0))
        self._clock = clock
        self._sleep = sleep
        self._events: Deque[Tuple[float, int]] = deque()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.rpm > 0 or self.tpm > 0

    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0][0] >= WINDOW_SECONDS:
            self._events.popleft()

    def wait_seconds(self, tokens: int = 0, now: Optional[float] = None) -> float:
        """纯函数：还差多久才能放行这次请求（0 表示立刻可以）。"""
        now = self._clock() if now is None else now
        self._prune(now)
        wait = 0.0
        if self.rpm > 0 and len(self._events) >= self.rpm:
            # 需要 (len - rpm + 1) 条滑出窗口才腾出位置
            idx = len(self._events) - self.rpm
            wait = max(wait, self._events[idx][0] + WINDOW_SECONDS - now)
        if self.tpm > 0 and tokens > 0:
            total = sum(t for _, t in self._events)
            if total + tokens > self.tpm:
                need = total + tokens - self.tpm
                freed = 0
                for ts, t in self._events:
                    freed += t
                    if freed >= need:
                        wait = max(wait, ts + WINDOW_SECONDS - now)
                        break
                else:
                    # 即使全部滑出也不够（单次请求就超过预算）：不无限等待
                    wait = max(wait, 0.0)
        return max(0.0, wait)

    def reserve(self, tokens: int = 0, cancel_event=None) -> float:
        """阻塞直到预算允许，返回实际等待秒数。"""
        waited = 0.0
        while True:
            with self._lock:
                wait = self.wait_seconds(tokens)
                if wait <= 0:
                    self._events.append((self._clock(), max(0, int(tokens or 0))))
                    return waited
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("cancelled: 等待请求预算时被用户打断")
            step = min(wait, 0.5)
            self._sleep(step)
            waited += step


_SHARED: dict = {}
_SHARED_LOCK = threading.Lock()


def get_shared_budget(key: str, rpm: int, tpm: int) -> RequestBudget:
    """按 API Key 复用预算：同一把 key 的所有模型实例共享一个滑动窗口。"""
    with _SHARED_LOCK:
        budget = _SHARED.get(key)
        if budget is None:
            budget = RequestBudget(rpm=rpm, tpm=tpm)
            _SHARED[key] = budget
        else:
            # 配置热重载后以最新值为准；窗口内的历史事件保留
            budget.rpm = max(0, int(rpm or 0))
            budget.tpm = max(0, int(tpm or 0))
        return budget


def reset_shared_budgets() -> None:
    """测试用：清空共享预算。"""
    with _SHARED_LOCK:
        _SHARED.clear()
