"""依赖检查不再把 Docker 当必需项（SPEC-024 AC-4）。"""

from __future__ import annotations

import src.utils.dependency_check as dependency_check


def test_local_execution_is_reported_ready(monkeypatch):
    """AC-4：本地后端下只要求存在一个可用 shell。"""
    monkeypatch.setattr(
        "src.tool.bash.backends.resolve_backend_name", lambda env=None: "local"
    )
    ok, reason = dependency_check._check_execution()
    assert ok, reason


def test_missing_shell_is_reported(monkeypatch):
    monkeypatch.setattr(
        "src.tool.bash.backends.resolve_backend_name", lambda env=None: "local"
    )

    def _boom():
        raise RuntimeError("no shell")

    monkeypatch.setattr("src.tool.bash.backends.resolve_shell", _boom)
    ok, reason = dependency_check._check_execution()
    assert not ok
    assert "shell" in reason


def test_collect_missing_has_no_docker_category(monkeypatch):
    """AC-4：Docker / 沙盒镜像不再出现在启动缺失清单。"""
    monkeypatch.setattr(dependency_check, "_check_git", lambda: True)
    monkeypatch.setattr(dependency_check, "_check_uv", lambda: True)
    monkeypatch.setattr(dependency_check, "_check_node", lambda: True)
    monkeypatch.setattr(dependency_check, "_check_embedding", lambda: True)
    monkeypatch.setattr(dependency_check, "_check_execution", lambda: (True, ""))

    names = [item["name"] for item in dependency_check._collect_missing()]
    assert "sandbox" not in names
    assert "docker" not in names
