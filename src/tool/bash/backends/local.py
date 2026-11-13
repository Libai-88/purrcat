"""本地 shell 执行后端：直接在本机工作目录执行命令，不依赖容器。"""

from __future__ import annotations

import os
import signal
import subprocess

from src.tool.bash._shared import clean_ansi
from src.tool.bash.exceptions import BashTimeoutError
from src.utils.config import AGENT_VM_DIR

from .base import (
    ShellSpec,
    clean_env,
    resolve_shell,
    truncate_output,
    validate_workspace,
)


class LocalShellBackend:
    """在 AGENT_VM_DIR 下执行命令；每次调用独立进程，cd 不跨调用保留。"""

    name = "local"

    def __init__(
        self, workspace_dir: str | None = None, shell: ShellSpec | None = None
    ):
        self.root = os.path.abspath(workspace_dir or AGENT_VM_DIR)
        self.workspace = self.root
        self._shell = shell
        self._started = False

    def start(self):
        os.makedirs(self.root, exist_ok=True)
        self.workspace = validate_workspace(self.root, self.root)
        self._started = True
        return self

    @property
    def shell(self) -> ShellSpec:
        if self._shell is None:
            self._shell = resolve_shell()
        return self._shell

    def execute(
        self, session_id: str, command: str, timeout: int = 30
    ) -> tuple[int, str, str]:
        if not command or not command.strip():
            raise ValueError("Bash command 不能为空，请提供要执行的 Shell 指令。")
        if not self._started:
            self.start()

        argv = self.shell.argv(command)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(
            argv,
            cwd=self.workspace,
            env=clean_env(os.environ),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        try:
            output, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            partial = self._terminate(proc)
            raise BashTimeoutError(f"部分输出:\n{partial.strip()}")

        text = truncate_output(clean_ansi(output or "").strip())
        return proc.returncode, text, self.workspace

    def _terminate(self, proc: subprocess.Popen) -> str:
        """超时后终止整棵进程树，避免残留子进程继续占用端口或文件。"""
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            output, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            output = ""
        return truncate_output(clean_ansi(output or ""))

    def close_shell(self, session_id: str) -> None:
        """本地后端不维持持久 shell，无需关闭。"""

    def stop(self) -> None:
        """本地后端没有后台资源需要释放。"""
