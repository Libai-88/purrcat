"""本地执行后端的真实命令执行与超时（SPEC-024 AC-1/AC-2）。"""

from __future__ import annotations

import pytest

from src.tool.bash.backends.local import LocalShellBackend
from src.tool.bash.exceptions import BashTimeoutError


@pytest.fixture
def backend(tmp_path):
    item = LocalShellBackend(workspace_dir=str(tmp_path / "agent_vm"))
    item.start()
    return item


def test_echo_runs_in_workspace(backend):
    """AC-1：无 Docker 也能执行命令，cwd 是配置的工作目录。"""
    code, output, cwd = backend.execute("s1", "echo hello", 30)
    assert code == 0
    assert "hello" in output
    assert cwd == backend.workspace


def test_pwd_matches_workspace(backend):
    """AC-1：命令的工作目录就是 agent_vm 工作区（Git Bash 会把盘符映射成 /c/...）。"""
    code, output, _cwd = backend.execute("s1", "pwd", 30)
    assert code == 0
    assert output.strip().replace("\\", "/").endswith("agent_vm")


def test_nonzero_exit_code_is_reported(backend):
    code, _output, _cwd = backend.execute("s1", "exit 3", 30)
    assert code == 3


def test_stderr_is_captured(backend):
    code, output, _cwd = backend.execute("s1", "echo boom 1>&2; exit 1", 30)
    assert code == 1
    assert "boom" in output


def test_timeout_raises_and_keeps_partial_output(backend):
    """AC-2：超时终止命令并抛出带部分输出的异常。"""
    with pytest.raises(BashTimeoutError):
        backend.execute("s1", "echo before; sleep 3", 1)


def test_empty_command_is_rejected(backend):
    with pytest.raises(ValueError):
        backend.execute("s1", "   ", 30)
