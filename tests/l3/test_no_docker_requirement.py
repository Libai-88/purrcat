"""静态约束：安装脚本、工具描述与文档不再要求 Docker（SPEC-024 AC-5/AC-7）。"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_install_ps1_has_no_docker_install_step():
    """AC-5：PowerShell 安装脚本不再安装 Docker Desktop。"""
    text = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "Docker.DockerDesktop" not in text
    assert "Docker Desktop.exe" not in text


def test_install_sh_has_no_docker_install_step():
    """AC-5：shell 安装脚本不再安装 Docker。"""
    text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    assert "get.docker.com" not in text
    assert "brew install --cask docker" not in text
    assert "ensure_docker" not in text


def test_bash_tool_description_does_not_claim_docker_sandbox():
    """工具描述必须如实说明执行位置，模型据此写对 shell 语法。"""
    from src.tool.bash.schema import BASH_TOOL_SCHEMA

    description = BASH_TOOL_SCHEMA["function"]["description"]
    assert "Docker" not in description
    assert "本地" in description


def test_readmes_no_longer_require_docker():
    """AC-7：README 明确不安装 Docker 即可使用。"""
    zh = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "不需要安装 Docker" in zh
    assert "Docker is **not** required" in en


def test_dev_guide_lists_local_shell():
    text = (REPO_ROOT / "docs" / "develop" / "README.md").read_text(encoding="utf-8")
    assert "本机 shell" in text


def test_main_no_longer_pulls_sandbox_image_on_startup():
    text = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    assert "ensure_sandbox_image" not in text
