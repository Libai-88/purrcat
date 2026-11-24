"""科研技能目录的按需安装链路（SPEC-025 AC-2/AC-3/AC-6）。

用内存里的假 zip 替换网络下载，验证的是安装编排而非下载本身。
"""

from __future__ import annotations

import json

import pytest

from src.tool.fetch.skill_fetch import load_skill
from src.utils import research_catalog

COMMIT = "b" * 40
SKILL_MD = """---
name: kaplan-meier
description: Run a survival analysis with Kaplan-Meier curves and log-rank tests.
license: MIT
---

# Kaplan-Meier

1. 检查删失数据
2. 拟合生存曲线
"""


@pytest.fixture
def catalog_env(tmp_path, monkeypatch):
    """把目录、skills 目录与沙盒都指向临时位置。"""
    research_catalog.reset_catalog_cache()

    catalog_path = tmp_path / "research-catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-11-24T00:00:00+00:00",
                "skills": [
                    {
                        "name": "kaplan-meier",
                        "description": "Run a survival analysis with Kaplan-Meier curves.",
                        "category": "statistics",
                        "license": "MIT",
                        "files": ["SKILL.md", "scripts/run.py"],
                        "source": {
                            "repository": "owner/repo",
                            "commit": COMMIT,
                            "path": "skills/kaplan-meier",
                            "url": "",
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    vm_dir = tmp_path / "agent_vm"

    monkeypatch.setattr(research_catalog, "RESEARCH_CATALOG_PATH", str(catalog_path))
    monkeypatch.setattr(
        research_catalog, "RESEARCH_CATALOG_SHIPPED_PATH", str(tmp_path / "none.json")
    )
    monkeypatch.setattr("src.utils.skill_helper.SKILL_DIR", str(skill_dir))
    monkeypatch.setattr("src.server.api.market_archive.SKILL_DIR", str(skill_dir))
    monkeypatch.setattr("src.server.api.research_install.SKILL_DIR", str(skill_dir))
    monkeypatch.setattr("src.tool.fetch.skill_fetch.AGENT_VM_DIR", str(vm_dir))
    monkeypatch.setattr("src.tool.search.skill_search.SKILL_DIR", str(skill_dir))

    yield skill_dir

    research_catalog.reset_catalog_cache()


def _fake_tree_payload(repo="owner/repo", commit=COMMIT, path="skills/kaplan-meier"):
    """一份只含该技能文件的仓库树。"""
    return {
        "sha": commit,
        "tree": [
            {"type": "blob", "path": "README.md", "size": 10},
            {"type": "blob", "path": f"{path}/SKILL.md", "size": 120},
            {"type": "blob", "path": f"{path}/scripts/run.py", "size": 20},
        ],
    }


def _fake_http(monkeypatch, requested):
    """把文件树与原文下载都换成本地替身。"""

    def fake_get(url):
        requested.append(url)
        if "api.github.com" in url:
            return json.dumps(_fake_tree_payload()).encode("utf-8")
        return SKILL_MD.encode("utf-8")

    monkeypatch.setattr("src.server.api.research_install._http_get", fake_get)
    monkeypatch.setattr("src.server.api.research_install._tree_cache", {})


def test_fetch_installs_catalog_skill_on_demand(catalog_env, monkeypatch):
    """AC-2：取一个未安装的目录技能时自动安装并返回 SOP。"""
    requested = []
    _fake_http(monkeypatch, requested)

    result, error = load_skill("kaplan-meier")

    assert error is None
    assert result["name"] == "kaplan-meier"
    assert "生存曲线" in result["content"]
    assert (catalog_env / "kaplan-meier" / "SKILL.md").exists()


def test_install_pins_commit_not_branch(catalog_env, monkeypatch):
    """AC-3：下载用的是固定 commit，不是分支名。"""
    requested = []
    _fake_http(monkeypatch, requested)

    load_skill("kaplan-meier")

    assert requested, "应当发起下载请求"
    assert all(COMMIT in url for url in requested), requested
    assert all("/refs/heads/" not in url for url in requested), requested


def test_install_only_fetches_the_skill_own_directory(catalog_env, monkeypatch):
    """只取该技能目录下的文件，不下整个仓库。"""
    requested = []
    _fake_http(monkeypatch, requested)

    load_skill("kaplan-meier")

    raw_urls = [url for url in requested if "raw.githubusercontent.com" in url]
    assert raw_urls, "应当按文件取原文"
    assert all("skills/kaplan-meier/" in url for url in raw_urls), raw_urls


def test_install_uses_catalog_file_list_without_api(catalog_env, monkeypatch):
    """目录条目自带文件清单时，安装完全不依赖 api.github.com。"""
    requested = []

    def fake_get(url):
        requested.append(url)
        return SKILL_MD.encode("utf-8")

    monkeypatch.setattr("src.server.api.research_install._http_get", fake_get)

    result, error = load_skill("kaplan-meier")

    assert error is None
    assert result["name"] == "kaplan-meier"
    assert not any("api.github.com" in url for url in requested), requested
    assert (catalog_env / "kaplan-meier" / "scripts" / "run.py").exists()


def test_repeated_install_is_idempotent(catalog_env, monkeypatch):
    """AC-6：同一 commit 重复安装得到相同内容。"""
    requested = []
    _fake_http(monkeypatch, requested)

    first, _ = load_skill("kaplan-meier")
    second, _ = load_skill("kaplan-meier")

    assert first["content"] == second["content"]


def test_unknown_skill_raises_not_found(catalog_env, monkeypatch):
    """目录里没有、本地也没有时，仍然报未找到。"""
    requested = []
    _fake_http(monkeypatch, requested)

    from src.tool.fetch.exceptions import SkillNotFoundError

    with pytest.raises(SkillNotFoundError):
        load_skill("not-in-catalog")


def test_install_failure_leaves_skill_absent(catalog_env, monkeypatch):
    """下载失败时不留下半成品目录。"""

    def boom(url):
        raise RuntimeError("network down")

    monkeypatch.setattr("src.server.api.research_install._http_get", boom)
    monkeypatch.setattr("src.server.api.research_install._tree_cache", {})

    from src.tool.fetch.exceptions import SkillNotFoundError

    with pytest.raises(SkillNotFoundError):
        load_skill("kaplan-meier")

    assert not (catalog_env / "kaplan-meier").exists()
