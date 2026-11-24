"""只读环境探测：看得到什么就说什么，拿不到就说 unknown。

只用 ``shutil.which`` 与短超时的 ``--version``，不改系统、不装东西。
PATH 用 ``get_enriched_env`` 合并注册表最新值——Windows 上用户刚装完
git/uv 没重启时，老进程的 PATH 还是旧的，直接 which 会误报缺失。

**观察 ≠ 授权 ≠ 验证。** 一条观测记录只说明「这个软件在这个版本被观察到了」，
不说明它能跑某个实验，更不说明用它算出来的结果是对的。
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone

from src.environments.catalog import (
    MISSING,
    READY,
    TOOLS,
    UNKNOWN,
    EnvironmentError,
    get_tool,
    list_capabilities,
)
from src.utils.config import get_enriched_env

_VERSION_TIMEOUT = 3  # 秒；探测不能卡住界面


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path() -> str | None:
    return get_enriched_env().get("PATH")


def observe_tool(tool_id: str) -> dict:
    """观察一个工具，返回三态就绪度 + 来源时刻。

    - 找到了可执行文件、版本也拿到了 → ready
    - 明确找不到可执行文件 → missing
    - 找到了但版本查询失败/超时 → unknown（不猜一个版本出来）
    """
    tool = get_tool(tool_id)
    path = _path()
    found = shutil.which(tool["command"], path=path)

    result = {
        "tool_id": tool["id"],
        "name": tool["name"],
        "kind": tool["kind"],
        "observed_at": _now(),
        "observed_by": "shutil.which + --version",
        "executable": found or "",
        "version": "",
        "readiness": UNKNOWN,
        "note": tool["note"],
    }

    if not found:
        result["readiness"] = MISSING
        return result

    try:
        completed = subprocess.run(
            [found, *tool["version_args"]],
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT,
            check=False,
        )
        output = (completed.stdout or completed.stderr or "").strip().splitlines()
        if completed.returncode == 0 and output:
            result["version"] = output[0].strip()[:200]
            result["readiness"] = READY
        else:
            result["readiness"] = UNKNOWN
    except (OSError, subprocess.SubprocessError):
        result["readiness"] = UNKNOWN

    return result


def observe_all(tool_ids: list[str] | None = None) -> dict:
    """观察全部（或指定的）工具 + 执行后端。"""
    ids = tool_ids or [item["id"] for item in TOOLS]
    observations = {}
    for tool_id in ids:
        try:
            observations[tool_id] = observe_tool(tool_id)
        except EnvironmentError:
            continue

    # 执行后端沿用既有解析，不另造一套。
    try:
        from src.tool.bash.backends import resolve_backend_name

        backend = resolve_backend_name()
    except Exception:
        backend = UNKNOWN

    return {
        "observed_at": _now(),
        "exec_backend": backend,
        "observations": observations,
        "capabilities": list_capabilities(),
        "note": (
            "这些只是观察结果：观察到软件在，不代表它能跑某个实验，"
            "更不代表用它算出来的结果是对的。"
        ),
    }
