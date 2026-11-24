"""便携版配置：PURRCAT_DIR 环境变量覆盖（SPEC-036 AC-1 / AC-2）。"""

from __future__ import annotations

import importlib
import os
import sys

import pytest


@pytest.fixture
def config_module():
    """每次都重新导入 config，让环境变量变化生效。"""
    sys.modules.pop("src.utils.config", None)
    return importlib.import_module("src.utils.config")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PURRCAT_DIR", raising=False)
    yield
    sys.modules.pop("src.utils.config", None)


def test_default_is_home_dot_purrcat(monkeypatch, config_module):
    """没设环境变量时仍是 ~/.purrcat，安装版行为不变。"""
    from pathlib import Path

    assert config_module.PURRCAT_DIR == str(Path.home() / ".purrcat")


def test_env_overrides_data_root(monkeypatch, tmp_path):
    """设了变量就全链路跟着变——所有路径常量都从 PURRCAT_DIR 派生。"""
    root = str(tmp_path / "portable")
    monkeypatch.setenv("PURRCAT_DIR", root)
    sys.modules.pop("src.utils.config", None)
    config = importlib.import_module("src.utils.config")

    assert config.PURRCAT_DIR == root
    assert config.MODEL_CONFIG_PATH.startswith(root)
    assert config.AGENT_CORE_DIR.startswith(root)
    assert config.SKILL_DIR.startswith(root)
    assert config.DATA_DIR.startswith(root)


def test_relative_path_becomes_absolute(monkeypatch):
    """相对路径要转绝对，避免后端 cwd 变化导致数据目录漂移。"""
    monkeypatch.setenv("PURRCAT_DIR", "portable-data")
    sys.modules.pop("src.utils.config", None)
    config = importlib.import_module("src.utils.config")

    assert os.path.isabs(config.PURRCAT_DIR)
    assert config.PURRCAT_DIR.endswith("portable-data")


def test_tilde_is_expanded(monkeypatch):
    monkeypatch.setenv("PURRCAT_DIR", "~/my-portable")
    sys.modules.pop("src.utils.config", None)
    config = importlib.import_module("src.utils.config")

    assert "~" not in config.PURRCAT_DIR
    assert config.PURRCAT_DIR.endswith("my-portable")


def test_empty_env_falls_back_to_default(monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("PURRCAT_DIR", "   ")
    sys.modules.pop("src.utils.config", None)
    config = importlib.import_module("src.utils.config")

    assert config.PURRCAT_DIR == str(Path.home() / ".purrcat")


def test_derived_paths_are_all_under_the_override(monkeypatch, tmp_path):
    """便携版要求：数据、技能、插件、笔记、凭据全在程序目录内。"""
    root = str(tmp_path / "pc-portable")
    monkeypatch.setenv("PURRCAT_DIR", root)
    sys.modules.pop("src.utils.config", None)
    config = importlib.import_module("src.utils.config")

    derived = [
        config.MODEL_CONFIG_PATH,
        config.MCP_CONFIG_PATH,
        config.CRON_FILE,
        config.HEARTBEAT_FILE,
        config.SKILL_DIR,
        config.GRAPHS_DIR,
        config.MCP_SOURCE_DIR,
        config.SENSOR_EXTENSION_DIR,
        config.AGENT_CORE_DIR,
        config.PARADIGMS_DIR,
        config.DATA_DIR,
        config.DATABASE_DIR,
    ]
    for path in derived:
        assert str(path).startswith(root), path
