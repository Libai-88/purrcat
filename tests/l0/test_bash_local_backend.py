"""本地执行后端的后端选择、shell 探测与命令构造（SPEC-024 AC-1/AC-3/AC-6）。"""

from __future__ import annotations

import pytest

from src.tool.bash.backends import base, local as local_backend


@pytest.fixture
def clean_settings(monkeypatch):
    """清掉环境变量并让 settings.json 读作空配置。"""
    monkeypatch.delenv("PURRCAT_EXEC_BACKEND", raising=False)
    monkeypatch.setattr("src.utils.config._read_settings", lambda: {})
    return monkeypatch


def test_backend_defaults_to_local(clean_settings):
    """AC-6：没有任何配置时默认本地执行，不要求 Docker。"""
    from src.tool.bash.backends import resolve_backend_name

    assert resolve_backend_name() == "local"


def test_env_var_selects_docker(clean_settings):
    """AC-6：显式设置 PURRCAT_EXEC_BACKEND=docker 才启用容器后端。"""
    from src.tool.bash.backends import resolve_backend_name

    clean_settings.setenv("PURRCAT_EXEC_BACKEND", "docker")
    assert resolve_backend_name() == "docker"


def test_auto_maps_to_local(clean_settings):
    """auto 在本地化的默认配置下等价于 local。"""
    from src.tool.bash.backends import resolve_backend_name

    clean_settings.setenv("PURRCAT_EXEC_BACKEND", "auto")
    assert resolve_backend_name() == "local"


def test_invalid_value_falls_back_to_local(clean_settings):
    from src.tool.bash.backends import resolve_backend_name

    clean_settings.setenv("PURRCAT_EXEC_BACKEND", "podman")
    assert resolve_backend_name() == "local"


def test_settings_file_is_honored_when_env_absent(clean_settings):
    from src.tool.bash.backends import resolve_backend_name

    clean_settings.setattr(
        "src.utils.config._read_settings", lambda: {"exec_backend": "docker"}
    )
    assert resolve_backend_name() == "docker"


def test_bash_argv_is_single_command_string():
    """AC-1：bash 后端用 -c 传整条命令，保证 &&、管道与引号原样生效。"""
    spec = base.ShellSpec("bash", "/bin/bash")
    assert spec.argv("echo hi && echo ok") == ["/bin/bash", "-c", "echo hi && echo ok"]


def test_powershell_argv_uses_non_interactive_and_utf8():
    """AC-1：PowerShell 分支非交互执行，并把控制台输出锁到 UTF-8。"""
    spec = base.ShellSpec("powershell", "pwsh")
    argv = spec.argv("echo hi")
    assert argv[:4] == ["pwsh", "-NoProfile", "-NonInteractive", "-Command"]
    assert "OutputEncoding" in argv[4]
    assert argv[4].endswith("echo hi")


def test_windows_prefers_git_bash_from_path():
    """AC-1：Windows 上 PATH 里有 bash 时优先 Git Bash。"""
    spec = base.resolve_shell(
        "win32", which=lambda name: "C:/Git/bin/bash.exe" if name == "bash" else None
    )
    assert spec.kind == "bash"
    assert spec.path == "C:/Git/bin/bash.exe"


def test_windows_falls_back_to_powershell(monkeypatch):
    """AC-1：没有 Git Bash 时回落到 PowerShell，而不是直接失败。"""
    monkeypatch.setattr(base.os.path, "isfile", lambda path: False)
    spec = base.resolve_shell(
        "win32",
        which=lambda name: "C:/Windows/pwsh.exe" if name == "pwsh" else None,
    )
    assert spec.kind == "powershell"
    assert spec.path == "C:/Windows/pwsh.exe"


def test_windows_without_any_shell_raises(monkeypatch):
    monkeypatch.setattr(base.os.path, "isfile", lambda path: False)
    with pytest.raises(RuntimeError):
        base.resolve_shell("win32", which=lambda name: None)


def test_posix_uses_bash():
    spec = base.resolve_shell("linux", which=lambda name: "/bin/bash")
    assert spec.kind == "bash"
    assert spec.path == "/bin/bash"


def test_workspace_must_stay_inside_root(tmp_path):
    """AC-3：工作目录解析后必须落在 root 之内。"""
    root = tmp_path / "agent_vm"
    root.mkdir()
    assert base.validate_workspace(str(root / "work"), str(root)) == str(
        (root / "work")
    )
    with pytest.raises(ValueError):
        base.validate_workspace(str(tmp_path), str(root))


def test_local_backend_creates_and_uses_workspace(tmp_path):
    backend = local_backend.LocalShellBackend(workspace_dir=str(tmp_path / "vm"))
    backend.start()
    assert backend.workspace == str((tmp_path / "vm").resolve())
    assert (tmp_path / "vm").is_dir()


def test_clean_env_strips_interpreter_vars_and_forces_utf8():
    env = base.clean_env(
        {"PATH": "p", "PYTHONPATH": "x", "VIRTUAL_ENV": "v", "CONDA_PREFIX": "c"}
    )
    assert "PYTHONPATH" not in env
    assert "VIRTUAL_ENV" not in env
    assert "CONDA_PREFIX" not in env
    assert env["PATH"] == "p"
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_truncate_output_keeps_head_and_tail():
    text = "头" * 40000 + "尾" * 40000
    out = base.truncate_output(text, 2000)
    assert out.startswith("头")
    assert out.endswith("尾")
    assert "输出已截断" in out
