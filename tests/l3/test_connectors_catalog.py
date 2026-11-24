"""连接器目录的静态约束（SPEC-033 AC-1）。

目录是**封闭词表**：登记在册的源才能被拉取。
这里把目录结构冻住，防止有人随手往里加一个没验证过的源。
"""

from __future__ import annotations

import pytest

from src.connectors import catalog

# 目录里登记的源。改动这里必须同时改 spec 与文档。
EXPECTED_CONNECTORS = (
    "arxiv",
    "crossref",
    "openalex",
    "pubmed",
    "uniprot",
    "zenodo",
)


def test_catalog_contents_are_frozen(repo_root):
    """目录内容冻结：加源是��个显式的决定，不是顺手的事。"""
    assert catalog.connector_ids() == EXPECTED_CONNECTORS


def test_every_connector_has_a_pull_implementation(repo_root):
    """登记在目录里的源都要真的接得上——不能只有一张卡片。"""
    from src.connectors import pull

    for connector_id in catalog.connector_ids():
        assert connector_id in pull._FETCHERS, f"{connector_id} 没有对应的拉取实现"


def test_no_implementation_without_a_catalog_entry(repo_root):
    """反过来也成立：实现了的源必须在目录里登记。"""
    from src.connectors import pull

    for connector_id in pull._FETCHERS:
        assert connector_id in catalog.connector_ids(), f"{connector_id} 没登记在目录里"


@pytest.mark.parametrize("connector_id", EXPECTED_CONNECTORS)
def test_each_connector_declares_how_to_cite_it(connector_id):
    """每个源都要能给出引用格式——不然拉回来的东西没法写进论文。"""
    item = catalog.get_connector(connector_id)
    assert item["citation"]
    assert item["home"].startswith("https://")


@pytest.mark.parametrize("connector_id", EXPECTED_CONNECTORS)
def test_each_connector_declares_its_rate_limit(connector_id):
    """限额要写出来：不知道限额就可能把源站用挂。"""
    item = catalog.get_connector(connector_id)
    assert item["rate_limit"]
