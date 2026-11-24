"""连接器的接口与入库链路（SPEC-032）。

关键断言：拉回来的东西**真的进了本机库**，并且带来源凭据。
用假的 HTTP 响应，不打真实站点。
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.connectors import pull, provenance
from src.connectors.catalog import FAIL_NO_RESULTS
from src.data import library as data_library
from src.server.api import connectors_api
from src.tool.connectors.connectors import Connectors


@pytest.fixture
def connector_home(tmp_path, monkeypatch):
    """把凭据目录与数据目录都指向临时位置。"""
    import src.utils.config as config

    monkeypatch.setattr(
        provenance, "provenance_root", lambda: str(tmp_path / "provenance")
    )
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(data_library, "DATA_ROOT", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def client(connector_home):
    app = FastAPI()
    app.include_router(connectors_api.router)
    return TestClient(app)


ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
  <id>http://arxiv.org/abs/2202.07171v1</id>
  <title>Investigating the genomic background of CRISPR-Cas genomes</title>
  <summary>  We report studies of the genomic background.  </summary>
  <published>2022-02-14T10:00:00Z</published>
  <author><name>Hyunjin Shim</name></author>
  <link href="https://arxiv.org/abs/2202.07171v1" rel="alternate" type="text/html"/>
  <link href="https://arxiv.org/pdf/2202.07171v1" rel="related" type="application/pdf" title="pdf"/>
</entry>
</feed>"""


@pytest.fixture
def fake_arxiv(monkeypatch):
    """把 arXiv 的 HTTP 换成假的响应。"""
    monkeypatch.setattr(
        pull, "_fetch", lambda url, source="", **kw: ARXIV_ATOM.encode()
    )


# ---------- 目录 ----------


def test_list_connectors(client, connector_home):
    response = client.get("/api/connectors")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["connectors"]) >= 5
    assert payload["provenance"] == []


def test_unknown_connector_is_404(client, connector_home):
    response = client.get("/api/connectors/not-a-source")

    assert response.status_code == 404


# ---------- 检索 ----------


def test_search_returns_candidates_without_landing(client, connector_home, fake_arxiv):
    """检索只给候选，不入库——入库才有来源凭据。"""
    response = client.post(
        "/api/connectors/search",
        json={"connector_id": "arxiv", "query": "crispr", "count": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["records"]) == 1
    assert payload["records"][0]["title"].startswith("Investigating")

    assert data_library.list_datasets() == [], "检索不该入库"
    assert provenance.list_all() == [], "检索不该写来源凭据"


# ---------- 拉取入库 ----------


def test_pull_lands_the_data_and_records_provenance(client, connector_home, fake_arxiv):
    """AC-2、AC-3：拉回来的东西真的进了数据集库，并带来源凭据。"""
    response = client.post(
        "/api/connectors/pull",
        json={"connector_id": "arxiv", "query": "crispr", "count": 1},
    )

    assert response.status_code == 200
    payload = response.json()

    # 进了数据集库
    datasets = data_library.list_datasets()
    assert len(datasets) == 1
    assert datasets[0]["id"] == payload["dataset"]["id"]

    # 留了来源凭据
    record = payload["provenance"]
    assert record["connector_id"] == "arxiv"
    assert record["landed"] == "datasets"
    assert record["landed_id"] == payload["dataset"]["id"]
    assert record["content_sha256"]
    assert record["request"] == {"query": "crispr", "count": 1}
    assert record["record_count"] == 1

    # 凭据能按入库对象找回来
    found = provenance.for_landed(payload["dataset"]["id"])
    assert found["provenance_id"] == record["provenance_id"]


def test_pulled_dataset_is_inspectable(client, connector_home, fake_arxiv):
    """进库之后要能当表格读——不然拉下来只是一堆没用的字节。"""
    payload = client.post(
        "/api/connectors/pull",
        json={"connector_id": "arxiv", "query": "crispr", "count": 1},
    ).json()

    asset_id = payload["asset"]["id"]
    resolved = data_library.resolve_version(payload["dataset"]["id"], asset_id)
    assert resolved["asset"]["id"] == asset_id


def test_pull_source_is_recorded_on_the_asset(client, connector_home, fake_arxiv):
    """来源写在资产上：回头看这条数据是从哪来的。"""
    payload = client.post(
        "/api/connectors/pull",
        json={"connector_id": "arxiv", "query": "crispr", "count": 1},
    ).json()

    assert payload["asset"]["source"] == "arxiv:crispr"


def test_pull_failure_reports_its_kind(client, connector_home, monkeypatch):
    """失败要说清是哪一类。"""
    monkeypatch.setattr(
        pull,
        "_fetch",
        lambda url, source="", **kw: json.dumps({"hits": {"hits": []}}).encode(),
    )

    response = client.post(
        "/api/connectors/pull",
        json={"connector_id": "zenodo", "query": "nothing", "count": 1},
    )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["kind"] == FAIL_NO_RESULTS
    assert detail["message"]


# ---------- 来源凭据 ----------


def test_provenance_endpoint_returns_the_record(client, connector_home, fake_arxiv):
    payload = client.post(
        "/api/connectors/pull",
        json={"connector_id": "arxiv", "query": "crispr", "count": 1},
    ).json()

    response = client.get(
        f"/api/connectors/provenance/{payload['provenance']['provenance_id']}"
    )

    assert response.status_code == 200
    assert response.json()["connector_id"] == "arxiv"


def test_provenance_has_no_acceptance_or_verification(
    client, connector_home, fake_arxiv
):
    """AC-4：凭据只说明出处，不说明可信。"""
    payload = client.post(
        "/api/connectors/pull",
        json={"connector_id": "arxiv", "query": "crispr", "count": 1},
    ).json()

    record = payload["provenance"]
    assert "acceptance" not in record
    assert "verification" not in record


def test_unknown_provenance_is_404(client, connector_home):
    assert client.get("/api/connectors/provenance/prov-nope").status_code == 404


# ---------- Agent 工具 ----------


def test_tool_lists_the_catalog():
    result = Connectors(action="list")

    assert "arXiv" in result["content"]
    assert "OpenAlex" in result["content"]


def test_tool_pull_lands_and_reports(connector_home, fake_arxiv):
    result = Connectors(action="pull", connector_id="arxiv", query="crispr", count=1)

    assert "入库为数据集" in result["content"]
    assert "来源凭据" in result["content"]
    assert len(data_library.list_datasets()) == 1
    assert len(provenance.list_all()) == 1


def test_tool_reports_unknown_connector():
    result = Connectors(action="search", connector_id="nope", query="x")

    assert "没有这个连接器" in result["content"]


def test_tool_reports_pull_failure_kind(connector_home, monkeypatch):
    monkeypatch.setattr(
        pull,
        "_fetch",
        lambda url, source="", **kw: json.dumps({"hits": {"hits": []}}).encode(),
    )

    result = Connectors(action="pull", connector_id="zenodo", query="nothing")

    assert "失败类型" in result["content"]
    assert FAIL_NO_RESULTS in result["content"]
