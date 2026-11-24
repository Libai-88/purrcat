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


def test_default_exec_backend_is_local():
    """没配置时默认本机执行，不能静默落到 Docker。"""
    from src.tool.bash.backends import DEFAULT_BACKEND, resolve_backend_name

    assert DEFAULT_BACKEND == "local"
    # 没有任何配置时必须是本机；auto 也按本机处理。
    assert resolve_backend_name(env={}) == "local"
    assert resolve_backend_name(env={"PURRCAT_EXEC_BACKEND": "auto"}) == "local"


def test_agent_rules_do_not_assume_container_port_mapping():
    """每轮都注入的系统规则不能把容器端口映射当成默认事实。

    以前这里写着「容器 3000→宿主 13000」，没 Docker 的用户会被误导。
    """
    text = (REPO_ROOT / "src" / "agent" / "system_rules" / "RULES.md").read_text(
        encoding="utf-8"
    )
    # 不能再把映射写成既定事实。
    assert "容器 3000→宿主 13000" not in text
    assert "宿主机高位端口" not in text
    # 要说清默认是本机、Docker 只是显式切换后的可选增强。
    assert "PURRCAT_EXEC_BACKEND=local" in text
    assert "取决于当前执行后端" in text


def test_research_tools_do_not_require_docker():
    """新做的科研能力必须全走本机，不碰容器后端。

    逐个查源码：不得 import 容器引擎、不得调 docker CLI。
    """
    import re

    research_roots = [
        "src/papers",
        "src/data",
        "src/notebook",
        "src/automation",
        "src/connectors",
        "src/environments",
        "src/contributions",
        "src/utils/research_catalog.py",
    ]
    offenders = []
    # 真正会造成依赖的是：拿容器引擎、拉镜像、或把后端实例 get_backend() 拿来跑命令。
    # 只读地 import resolve_backend_name 来「报告当前后端」不算依赖——
    # 环境探测就该如实告诉用户现在走的是本机还是 Docker。
    forbidden = re.compile(
        r"get_container_engine|ImageStatusResponse|docker\s+run|docker\s+pull|"
        r"\bget_backend\s*\("
    )
    for root in research_roots:
        path = REPO_ROOT / root
        files = (
            sorted(path.rglob("*.py"))
            if path.is_dir()
            else [path]
            if path.is_file()
            else []
        )
        for item in files:
            if forbidden.search(item.read_text(encoding="utf-8")):
                offenders.append(str(item.relative_to(REPO_ROOT)))
    assert not offenders, "科研能力不该依赖容器后端：" + ", ".join(offenders)


def test_system_api_does_not_import_docker_at_module_load():
    """没有 Docker SDK 也能启动服务——Docker 只在显式选容器后端时按需加载。

    以前 system.py 顶部 `import docker`，没装 pip 包服务直接起不来。
    """
    text = (REPO_ROOT / "src" / "server" / "api" / "system.py").read_text(
        encoding="utf-8"
    )
    # 模块顶部不许有 docker import，只能在按需加载函数里出现。
    head = text[: text.find("router = ")]
    assert "import docker" not in head
    assert "def _docker_sdk()" in text


def test_server_can_be_imported_without_docker_sdk(monkeypatch):
    """真的把 docker 包挡掉，create_app 仍能装配成功。"""
    import builtins
    import importlib
    import sys

    real_import = builtins.__import__

    def _block_docker(name, *args, **kwargs):
        if name == "docker" or name.startswith("docker."):
            raise ImportError("docker blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_docker)
    for mod in list(sys.modules):
        if mod == "docker" or mod.startswith("docker."):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    for mod in ("src.server.app", "src.server.api.system"):
        sys.modules.pop(mod, None)

    try:
        app_module = importlib.import_module("src.server.app")
        app = app_module.create_app()
        assert app is not None
        assert app.openapi()["paths"]
    finally:
        for mod in ("src.server.app", "src.server.api.system"):
            sys.modules.pop(mod, None)
