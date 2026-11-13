"""执行后端工厂：默认本地执行，显式配置时才启用 Docker 沙盒。"""

from __future__ import annotations

import os

from .base import ExecutionBackend, ShellSpec, clean_env, resolve_shell

DEFAULT_BACKEND = "local"
VALID_BACKENDS = ("local", "docker", "auto")
SETTINGS_KEY = "exec_backend"

_backend: ExecutionBackend | None = None
_backend_name: str | None = None


def resolve_backend_name(env: dict | None = None) -> str:
    """环境变量优先，其次 settings.json；auto 在无容器需求时按本地处理。"""
    raw = (env or os.environ).get("PURRCAT_EXEC_BACKEND", "").strip().lower()
    if raw == "auto":
        return DEFAULT_BACKEND
    if raw in ("local", "docker"):
        return raw
    if not raw:
        try:
            from src.utils.config import _read_settings

            value = str(_read_settings().get(SETTINGS_KEY, "")).strip().lower()
            if value == "auto":
                return DEFAULT_BACKEND
            if value in ("local", "docker"):
                return value
        except Exception:
            pass
    return DEFAULT_BACKEND


def get_backend() -> ExecutionBackend:
    """按配置返回单例后端；后端名变化时重建。"""
    global _backend, _backend_name
    name = resolve_backend_name()
    if _backend is None or _backend_name != name:
        if name == "docker":
            from .docker import DockerBackend

            _backend = DockerBackend()
        else:
            from .local import LocalShellBackend

            _backend = LocalShellBackend()
        _backend_name = name
    _backend.start()
    return _backend


def reset_backend() -> None:
    """测试与切换配置后调用，丢弃单例以便下次按新配置重建。"""
    global _backend, _backend_name
    _backend = None
    _backend_name = None


__all__ = [
    "DEFAULT_BACKEND",
    "ExecutionBackend",
    "ShellSpec",
    "VALID_BACKENDS",
    "clean_env",
    "get_backend",
    "reset_backend",
    "resolve_backend_name",
    "resolve_shell",
]
