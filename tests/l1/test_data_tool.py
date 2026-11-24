"""Data 工具与接口的行为（SPEC-027 AC-2/AC-3/AC-5）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.data import library, query as query_module
from src.server.api.data_api import router
from src.tool.data.data import Data

CSV_CONTENT = """id,name,score
1,alice,90
2,bob,75
3,carol,60
"""


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "sample.csv"
    path.write_text(CSV_CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def client(data_home):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _payload(result):
    assert isinstance(result, dict), result
    return str(result.get("content", ""))


def test_import_requires_path():
    assert "path" in _payload(Data(action="import"))


def test_import_rejects_unreadable_path(data_home, csv_file, monkeypatch):
    monkeypatch.setattr("src.tool.data.data.can_read", lambda _path: False)

    result = Data(action="import", path=str(csv_file))

    assert "权限" in _payload(result)
    assert library.list_datasets() == []


def test_import_then_list(data_home, csv_file, monkeypatch):
    monkeypatch.setattr("src.tool.data.data.can_read", lambda _path: True)

    imported = Data(action="import", path=str(csv_file))
    listed = Data(action="list")

    assert "已导入" in _payload(imported)
    assert imported is not None
    assert "sample.csv" in _payload(listed)


def test_inspect_reports_fields_and_quality(data_home, csv_file, monkeypatch):
    monkeypatch.setattr("src.tool.data.data.can_read", lambda _path: True)
    Data(action="import", path=str(csv_file))
    dataset = library.list_datasets()[0]

    result = Data(action="inspect", dataset_id=dataset["id"])

    payload = _payload(result)
    assert "字段" in payload
    assert "score" in payload
    assert "转换失败" in payload


def test_inspect_reports_missing_dataset(data_home):
    result = Data(action="inspect", dataset_id="ds-nope")

    assert "没有这个数据集" in _payload(result)


def test_query_leaves_receipt_and_returns_rows(data_home, csv_file, monkeypatch):
    monkeypatch.setattr("src.tool.data.data.can_read", lambda _path: True)
    Data(action="import", path=str(csv_file))
    dataset = library.list_datasets()[0]

    result = Data(
        action="query",
        dataset_id=dataset["id"],
        question="每人一组多少分",
        interpretations={"score": "number"},
        unit="分",
        filter={"field": "score", "operator": "gte", "value": "70"},
    )

    payload = _payload(result)
    assert "查询结果" in payload
    assert "收据 id" in payload
    receipts = query_module.list_receipts()
    assert len(receipts) == 1
    assert receipts[0]["unit"] == "分"
    assert receipts[0]["acceptance"] == "needs_review"


def test_query_refuses_numeric_filter_on_text_column(data_home, csv_file, monkeypatch):
    """AC-5：文本列上的数值比较是口径错误，报错而不是空结果。"""
    monkeypatch.setattr("src.tool.data.data.can_read", lambda _path: True)
    Data(action="import", path=str(csv_file))
    dataset = library.list_datasets()[0]

    result = Data(
        action="query",
        dataset_id=dataset["id"],
        filter={"field": "score", "operator": "gte", "value": "70"},
    )

    assert "显式解释为数字" in _payload(result)


def test_receipts_action_lists_receipts(data_home, csv_file, monkeypatch):
    monkeypatch.setattr("src.tool.data.data.can_read", lambda _path: True)
    Data(action="import", path=str(csv_file))
    dataset = library.list_datasets()[0]
    Data(action="query", dataset_id=dataset["id"], question="多少人")

    result = Data(action="receipts")

    assert "查询收据" in _payload(result)


def test_unknown_action_errors():
    assert "未知的 action" in _payload(Data(action="nope"))


# ---------- 接口 ----------


def test_api_lists_datasets(client, data_home, csv_file):
    library.import_dataset(str(csv_file))

    response = client.get("/api/data/datasets")

    assert response.status_code == 200
    assert len(response.json()["datasets"]) == 1


def test_api_import_returns_asset(client, data_home, csv_file):
    response = client.post("/api/data/datasets/import", json={"path": str(csv_file)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset"]["id"].startswith("ds-")
    assert payload["asset"]["sha256"]


def test_api_inspection_returns_report(client, data_home, csv_file):
    imported = library.import_dataset(str(csv_file))

    response = client.get(f"/api/data/datasets/{imported['dataset']['id']}/inspection")

    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["row_count"] == 3
    assert len(payload["sample"]) == 3


def test_api_query_returns_receipt(client, data_home, csv_file):
    imported = library.import_dataset(str(csv_file))

    response = client.post(
        f"/api/data/datasets/{imported['dataset']['id']}/query",
        json={"question": "多少人", "spec": {"limit": 10}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["receipt"]["acceptance"] == "needs_review"
    assert payload["result"]["total"] == 3


def test_api_unknown_dataset_returns_404(client):
    response = client.get("/api/data/datasets/ds-nope")

    assert response.status_code == 404
