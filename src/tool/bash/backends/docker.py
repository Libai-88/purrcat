"""Docker 沙盒后端（可选）：显式启用时复用原有 DockerManager。

DockerManager 在构造时就解析 docker 命令，未安装会直接抛 RuntimeError。
这里把它推迟到真正执行时，保证"选了 docker 但没装"不会让工具注册失败，
只在使用 Bash 时给出可读的错误。
"""

from __future__ import annotations

from src.tool.bash.exceptions import DockerNotRunningError


class DockerBackend:
    """把 DockerManager 包成统一后端接口，仅在显式选择 docker 时加载。"""

    name = "docker"

    def __init__(self):
        self._manager = None

    def start(self):
        return self

    def _ensure_manager(self):
        if self._manager is None:
            from src.tool.bash.docker_env import get_docker_manager

            try:
                self._manager = get_docker_manager()
            except RuntimeError as e:
                raise DockerNotRunningError(str(e)) from e
        return self._manager

    def execute(
        self, session_id: str, command: str, timeout: int = 30
    ) -> tuple[int, str, str]:
        return self._ensure_manager().execute(session_id, command, timeout)

    def close_shell(self, session_id: str) -> None:
        if self._manager is not None:
            self._manager.close_shell(session_id)

    def stop(self) -> None:
        if self._manager is not None:
            self._manager.stop()
