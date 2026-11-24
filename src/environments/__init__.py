"""科研环境：只读探测、能力声明、证据边界。

观察 ≠ 授权 ≠ 验证。这里只说「观察到什么」，
不说「能跑什么实验」，更不说「结果对不对」。
"""

from __future__ import annotations

from src.environments.catalog import (
    CAPABILITIES,
    CAPABILITY_IDS,
    READINESS_VALUES,
    TOOLS,
    EnvironmentError,
    get_capability,
    get_tool,
    list_capabilities,
    list_tools,
)
from src.environments.observer import observe_all, observe_tool

__all__ = [
    "CAPABILITIES",
    "CAPABILITY_IDS",
    "EnvironmentError",
    "READINESS_VALUES",
    "TOOLS",
    "get_capability",
    "get_tool",
    "list_capabilities",
    "list_tools",
    "observe_all",
    "observe_tool",
]
