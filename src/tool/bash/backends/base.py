"""执行后端的公共协议与纯函数。

后端负责在受控工作目录里执行一条 shell 命令，返回 (exit_code, output, cwd)。
这里只放与环境无关的选择、构造与清洗逻辑，便于 L0 单测。
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from typing import Protocol

# 单次执行回传的文本上限：超长输出只保留头尾，避免撑爆模型上下文
MAX_OUTPUT_BYTES = 100 * 1024

# 父进程的解释器环境会让子进程用错 Python（venv/conda 混用），执行前清掉
CLEAN_ENV_KEYS = (
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "PYTHONUSERBASE",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
)

# Git for Windows 的常见安装位置（PATH 里没有 bash 时的兜底）
WINDOWS_BASH_CANDIDATES = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)


@dataclass(frozen=True)
class ShellSpec:
    """本机 shell 的描述：类型 + 可执行路径。"""

    kind: str  # "bash" | "powershell"
    path: str

    def argv(self, command: str) -> list[str]:
        if self.kind == "bash":
            return [self.path, "-c", command]
        # PowerShell 默认按控制台代码页输出，中文路径会变成乱码；先锁成 UTF-8
        prefix = "try{[Console]::OutputEncoding=[System.Text.Encoding]::UTF8}catch{};"
        return [
            self.path,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            prefix + command,
        ]


class ExecutionBackend(Protocol):
    """执行后端的统一接口（Docker 与本地实现共用）。"""

    name: str

    def start(self): ...

    def execute(
        self, session_id: str, command: str, timeout: int = 30
    ) -> tuple[int, str, str]: ...

    def close_shell(self, session_id: str) -> None: ...

    def stop(self) -> None: ...


def resolve_shell(platform: str | None = None, which=shutil.which) -> ShellSpec:
    """按平台挑选本机 shell：Windows 优先 Git Bash，其次 PowerShell。"""
    plat = platform or sys.platform
    if plat == "win32":
        found = which("bash")
        if found:
            return ShellSpec("bash", found)
        # Git 装在非 C 盘（或不在 PATH）时，从 git.exe 的位置反推 Git Bash
        git = which("git")
        if git:
            git_root = os.path.dirname(os.path.dirname(os.path.abspath(git)))
            for rel in ("bin", "usr\\bin"):
                candidate = os.path.join(git_root, rel, "bash.exe")
                if os.path.isfile(candidate):
                    return ShellSpec("bash", candidate)
        for candidate in WINDOWS_BASH_CANDIDATES:
            if os.path.isfile(candidate):
                return ShellSpec("bash", candidate)
        powershell = which("pwsh") or which("powershell")
        if powershell:
            return ShellSpec("powershell", powershell)
        raise RuntimeError("未找到可用的本地 shell（bash 或 PowerShell）")

    found = which("bash") or ("/bin/bash" if os.path.exists("/bin/bash") else None)
    if not found:
        raise RuntimeError("未找到可用的本地 shell（bash）")
    return ShellSpec("bash", found)


def validate_workspace(cwd: str, root: str) -> str:
    """校验工作目录落在 root 之内，返回解析后的绝对路径。"""
    resolved = os.path.abspath(cwd)
    root_abs = os.path.abspath(root)
    try:
        common = os.path.commonpath([resolved, root_abs])
    except ValueError as exc:  # 不同盘符
        raise ValueError(f"工作目录不在允许范围内: {resolved}") from exc
    if common != root_abs:
        raise ValueError(f"工作目录不在允许范围内: {resolved}")
    return resolved


def clean_env(base_env: dict, extra: dict | None = None) -> dict:
    """复制一份环境变量并去掉父进程的解释器痕迹。"""
    env = dict(base_env)
    for key in CLEAN_ENV_KEYS:
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def truncate_output(text: str, limit: int = MAX_OUTPUT_BYTES) -> str:
    """超长输出保留头尾：错误信息通常在末尾，开头通常有上下文。"""
    if not text:
        return text
    raw = text.encode("utf-8", "replace")
    if len(raw) <= limit:
        return text
    head = raw[: int(limit * 0.6)].decode("utf-8", "ignore")
    tail = raw[-int(limit * 0.4) :].decode("utf-8", "ignore")
    return f"{head}\n... [输出已截断，共 {len(raw)} 字节] ...\n{tail}"
