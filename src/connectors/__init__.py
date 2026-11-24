"""科研连接器：把外部文献与数据拉进本机库，并留下来源凭据。

技能目录里已经有能查 arXiv / PubMed / OpenAlex 的技能。它们**能搜到东西**，
但搜到的东西落不到本机库，也说不清是从哪来的。

连接器补的就是这一截：

    目录（能拉什么） → 拉取 → 归一 → 入库 → 来源凭据

**凭据只说明出处，不说明可信。** 「这批数据是从 arXiv 拉的」不能推出
「这批数据是对的」——后者是研究记录里 acceptance 的事。
"""

from __future__ import annotations

from src.connectors.catalog import (
    CONNECTORS,
    ConnectorError,
    PullError,
    connector_ids,
    get_connector,
    list_connectors,
    supports,
)
from src.connectors.landing import land_metadata, land_paper, search
from src.connectors.pull import fetch
from src.connectors.provenance import build as build_provenance
from src.connectors.provenance import get as get_provenance
from src.connectors.provenance import list_all as list_provenance

__all__ = [
    "CONNECTORS",
    "ConnectorError",
    "PullError",
    "build_provenance",
    "connector_ids",
    "fetch",
    "get_connector",
    "get_provenance",
    "land_metadata",
    "land_paper",
    "list_connectors",
    "list_provenance",
    "search",
    "supports",
]
