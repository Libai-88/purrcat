"""科研技能目录的条目模型、分类规则与检索合并（SPEC-025 AC-1/AC-4）。"""

from __future__ import annotations

import json

import pytest

from src.tool.search.skill_search import merge_skill_results
from src.utils import research_catalog


@pytest.fixture(autouse=True)
def _isolated_catalog(tmp_path, monkeypatch):
    """把目录指向临时路径，测试不碰真实 ~/.purrcat。"""
    research_catalog.reset_catalog_cache()
    monkeypatch.setattr(
        research_catalog, "RESEARCH_CATALOG_PATH", str(tmp_path / "user-catalog.json")
    )
    monkeypatch.setattr(
        research_catalog,
        "RESEARCH_CATALOG_SHIPPED_PATH",
        str(tmp_path / "shipped-catalog.json"),
    )
    yield
    research_catalog.reset_catalog_cache()


def _write_catalog(path, skills, **extra):
    path.write_text(
        json.dumps(
            {"schema_version": 1, "skills": skills, **extra}, ensure_ascii=False
        ),
        encoding="utf-8",
    )


def _entry(name="kaplan-meier", description="", repository="owner/repo"):
    return {
        "name": name,
        "description": description,
        "category": "statistics",
        "license": "MIT",
        "source": {
            "repository": repository,
            "commit": "a" * 40,
            "path": f"skills/{name}",
            "url": f"https://github.com/{repository}/tree/{'a' * 40}/skills/{name}",
        },
    }


# ---------- AC-4 降级 ----------


def test_missing_catalog_file_yields_empty_catalog():
    """AC-4：目录文件不存在时返回空目录，不抛异常。"""
    assert research_catalog.load_catalog() == {}
    assert research_catalog.catalog_entries() == []
    assert research_catalog.find_entry("anything") is None


def test_corrupt_catalog_file_yields_empty_catalog(tmp_path):
    """AC-4：目录文件损坏时降级为空目录。"""
    (tmp_path / "user-catalog.json").write_text("{ not json", encoding="utf-8")
    research_catalog.reset_catalog_cache()

    assert research_catalog.load_catalog() == {}
    assert research_catalog.catalog_entries() == []


def test_unknown_schema_version_is_rejected(tmp_path):
    """AC-4：版本不匹配的目录文件不被采纳。"""
    (tmp_path / "user-catalog.json").write_text(
        json.dumps({"schema_version": 99, "skills": [_entry()]}), encoding="utf-8"
    )
    research_catalog.reset_catalog_cache()

    assert research_catalog.catalog_entries() == []


def test_user_catalog_overrides_shipped(tmp_path):
    """用户目录优先于发行版副本。"""
    _write_catalog(tmp_path / "shipped-catalog.json", [_entry(name="from-shipped")])
    _write_catalog(tmp_path / "user-catalog.json", [_entry(name="from-user")])
    research_catalog.reset_catalog_cache()

    names = [item["name"] for item in research_catalog.catalog_entries()]
    assert names == ["from-user"]


# ---------- 条目模型 ----------


def test_entries_require_complete_source(tmp_path):
    """来源字段不全的条目被丢弃。"""
    broken = _entry(name="broken")
    broken["source"].pop("commit")
    _write_catalog(tmp_path / "user-catalog.json", [_entry(name="good"), broken])
    research_catalog.reset_catalog_cache()

    names = [item["name"] for item in research_catalog.catalog_entries()]
    assert names == ["good"]


def test_find_entry_is_case_insensitive(tmp_path):
    _write_catalog(tmp_path / "user-catalog.json", [_entry(name="Kaplan-Meier")])
    research_catalog.reset_catalog_cache()

    assert research_catalog.find_entry("kaplan-meier") is not None
    assert research_catalog.find_entry("KAPLAN-MEIER") is not None
    assert research_catalog.find_entry("missing") is None


def test_install_url_pins_commit(tmp_path):
    """AC-3：安装链接用 commit 定位，保证可复现。"""
    _write_catalog(tmp_path / "user-catalog.json", [_entry()])
    research_catalog.reset_catalog_cache()

    url = research_catalog.entry_install_url(
        research_catalog.find_entry("kaplan-meier")
    )
    assert url == f"https://github.com/owner/repo/tree/{'a' * 40}/skills/kaplan-meier"


# ---------- 分类规则 ----------


@pytest.mark.parametrize(
    ("name", "description", "expected"),
    [
        (
            "lit-review",
            "Conduct a systematic literature review and citation audit",
            "literature",
        ),
        ("surv", "Kaplan-Meier survival analysis with log-rank test", "statistics"),
        ("ml-shap", "Machine learning workflow with SHAP interpretation", "ai"),
        ("figure", "Create publication-ready matplotlib figures", "visualization"),
        ("thesis", "Write a thesis manuscript in LaTeX", "writing"),
        (
            "slides",
            "Build an academic presentation for the group meeting",
            "presentation",
        ),
        ("未知", "无法判断的描述", "unclassified"),
    ],
)
def test_classify_maps_to_research_category(name, description, expected):
    assert research_catalog.classify(name, description) == expected


def test_category_label_is_chinese():
    assert research_catalog.category_label("statistics") == "统计检验与分析"
    assert research_catalog.category_label("nope") == "待分类"


# ---------- AC-1 检索合并 ----------


def test_merge_marks_installed_and_uninstalled():
    """AC-1：合并结果能区分本地已装与目录未装。"""
    local = [{"score": 0.8, "skill": {"name": "local-skill", "description": "本地"}}]
    catalog = [{"score": 0.9, "skill": {"name": "remote-skill", "description": "目录"}}]

    merged = merge_skill_results(local, catalog, top_k=5)

    by_name = {item["skill"]["name"]: item["skill"] for item in merged}
    assert by_name["local-skill"]["installed"] is True
    assert by_name["remote-skill"]["installed"] is False


def test_merge_normalizes_across_corpora():
    """两组分数量纲不同，归一化后才可比。"""
    local = [{"score": 0.2, "skill": {"name": "local"}}]
    catalog = [{"score": 0.9, "skill": {"name": "remote"}}]

    merged = merge_skill_results(local, catalog, top_k=5)

    scores = {item["skill"]["name"]: item["score"] for item in merged}
    # 两组各自归一化到 1.0，本地再加已安装加权
    assert scores["local"] > scores["remote"]


def test_merge_respects_top_k():
    local = [{"score": 1.0, "skill": {"name": f"l{i}"}} for i in range(5)]
    catalog = [{"score": 1.0, "skill": {"name": f"c{i}"}} for i in range(5)]

    merged = merge_skill_results(local, catalog, top_k=3)

    assert len(merged) == 3


def test_merge_with_empty_catalog_keeps_local_results():
    """目录为空时，本地检索结果原样保留。"""
    local = [{"score": 0.5, "skill": {"name": "local"}}]

    merged = merge_skill_results(local, [], top_k=5)

    assert len(merged) == 1
    assert merged[0]["skill"]["installed"] is True
