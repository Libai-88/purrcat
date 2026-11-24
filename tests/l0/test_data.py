"""数据集库的版本、可用性与检查规则（SPEC-027）。

锁住几条硬规则：类型是声明的不是推断的、四种缺失分开算、
原文件变了或没了就用旧数据糊弄是不允许的。
"""

from __future__ import annotations

import json
import os

import pytest

from src.data import inspect as inspect_module
from src.data import library, query as query_module

CSV_CONTENT = """id,name,score,note
1,alice,90,good
2,bob,75,
3,carol,,missing
4,dave,60,good
"""

MESSY_CSV = """id,value,flag
1,001,true
2,1.5,false
3,abc,true
4,,false
"""

JSON_CONTENT = json.dumps(
    [
        {"id": 1, "name": "alice", "score": 90, "note": None},
        {"id": 2, "name": "bob", "score": 75, "note": ""},
        {"id": 3, "name": "carol"},
    ],
    ensure_ascii=False,
)


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    """把数据集库指向临时目录，测试不碰真实数据目录。"""
    monkeypatch.setattr(library, "DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(query_module.library, "DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "sample.csv"
    path.write_text(CSV_CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def imported(data_home, csv_file):
    return library.import_dataset(str(csv_file))


# ---------- 导入与版本 ----------


def test_import_creates_dataset_and_version(imported, csv_file):
    """导入后有��个数据集与一个不可变版本。"""
    dataset = imported["dataset"]
    asset = imported["asset"]

    assert dataset["id"].startswith("ds-")
    assert asset["id"].startswith("av-")
    assert dataset["versions"] == [asset["id"]]
    assert asset["format"] == "csv"
    assert asset["size"] == csv_file.stat().st_size
    assert len(asset["sha256"]) == 64


def test_same_filename_imports_separately(data_home, csv_file):
    """同名文件各自成独立数据集——只有显式「加版本」才归到一起。"""
    first = library.import_dataset(str(csv_file))
    second = library.import_dataset(str(csv_file))

    assert first["dataset"]["id"] != second["dataset"]["id"]
    assert len(library.list_datasets()) == 2


def test_add_version_appends_to_same_dataset(data_home, csv_file, tmp_path):
    """给已有数据集加版本时，版本追加而不是新建数据集。"""
    first = library.import_dataset(str(csv_file))
    other = tmp_path / "sample2.csv"
    other.write_text(CSV_CONTENT + "5,eve,55,good\n", encoding="utf-8")

    second = library.import_dataset(str(other), dataset_id=first["dataset"]["id"])

    assert second["dataset"]["id"] == first["dataset"]["id"]
    assert len(second["dataset"]["versions"]) == 2
    assert len(library.list_datasets()) == 1


def test_archived_dataset_rejects_new_version(data_home, csv_file, tmp_path):
    """归档的数据集先恢复才能加版本。"""
    first = library.import_dataset(str(csv_file))
    library.set_archived(first["dataset"]["id"], True)
    other = tmp_path / "v2.csv"
    other.write_text("id\n1\n", encoding="utf-8")

    with pytest.raises(library.DataError):
        library.import_dataset(str(other), dataset_id=first["dataset"]["id"])


# ---------- 可用性三态 ----------


def test_availability_is_present_when_size_matches(imported):
    asset = imported["asset"]
    assert library.availability(asset) == library.AVAILABLE_PRESENT


def test_availability_is_changed_when_size_differs(imported, data_home):
    """改了原文件大小 → changed。"""
    path = os.path.join(library.files_root(), imported["asset"]["id"])
    with open(path, "ab") as handle:
        handle.write(b"5,eve,55,good\n")

    assert library.availability(imported["asset"]) == library.AVAILABLE_CHANGED


def test_availability_is_missing_when_file_gone(imported, data_home):
    path = os.path.join(library.files_root(), imported["asset"]["id"])
    os.unlink(path)

    assert library.availability(imported["asset"]) == library.AVAILABLE_MISSING


def test_inspection_refuses_when_original_changed(imported, data_home):
    """AC：原文件变了就用旧数据糊弄是不允许的。"""
    path = os.path.join(library.files_root(), imported["asset"]["id"])
    with open(path, "ab") as handle:
        handle.write(b"5,eve,55,good\n")

    with pytest.raises(inspect_module.InspectionError) as excinfo:
        inspect_module.inspect_asset(imported["asset"])

    assert "旧数据" in str(excinfo.value) or "大小" in str(excinfo.value)


def test_inspection_refuses_when_original_missing(imported, data_home):
    path = os.path.join(library.files_root(), imported["asset"]["id"])
    os.unlink(path)

    with pytest.raises(inspect_module.InspectionError):
        inspect_module.inspect_asset(imported["asset"])


# ---------- 类型是声明的 ----------


def test_csv_values_stay_text(imported):
    """CSV 的值一律当文本，001 不会被变成 1。"""
    inspection = inspect_module.inspect_asset(imported["asset"])

    score = next(
        item for item in inspection["report"]["fields"] if item["name"] == "score"
    )
    assert score["interpretation"] is None
    assert "number" not in score["kinds"]


def test_leading_zeros_are_preserved(data_home, tmp_path):
    path = tmp_path / "messy.csv"
    path.write_text(MESSY_CSV, encoding="utf-8")
    imported = library.import_dataset(str(path))

    inspection = inspect_module.inspect_asset(imported["asset"])

    value_cell = inspection["rows"][0].cells["value"]
    assert value_cell.display == "001"
    assert value_cell.number is None


def test_explicit_interpretation_converts_only_that_field(data_home, tmp_path):
    """只有被点名的字段会转数字，其余保持文本。"""
    path = tmp_path / "messy.csv"
    path.write_text(MESSY_CSV, encoding="utf-8")
    imported = library.import_dataset(str(path))

    inspection = inspect_module.inspect_asset(imported["asset"], {"value": "number"})

    assert inspection["rows"][0].cells["value"].number is not None
    assert inspection["rows"][0].cells["id"].number is None


# ---------- 四种缺失分开 ----------


def test_missing_null_and_empty_are_counted_separately(data_home, tmp_path):
    """缺字段、显式 null、空字符串是三件不同的事。"""
    path = tmp_path / "rows.json"
    path.write_text(JSON_CONTENT, encoding="utf-8")
    imported = library.import_dataset(str(path))

    inspection = inspect_module.inspect_asset(imported["asset"])
    fields = {item["name"]: item for item in inspection["report"]["fields"]}

    assert fields["note"]["nulls"] == 1
    assert fields["note"]["empty"] == 1
    assert fields["note"]["missing"] == 1


def test_conversion_failure_keeps_original_text(data_home, tmp_path):
    """转不动的值保留原文，单独计数，绝不变成 0。"""
    path = tmp_path / "messy.csv"
    path.write_text(MESSY_CSV, encoding="utf-8")
    imported = library.import_dataset(str(path))

    inspection = inspect_module.inspect_asset(imported["asset"], {"value": "number"})
    field = next(
        item for item in inspection["report"]["fields"] if item["name"] == "value"
    )

    assert field["conversion_failures"] == 1
    failure_cell = inspection["rows"][2].cells["value"]
    assert failure_cell.display == "abc"
    assert failure_cell.number is None


def test_preview_interpretation_is_a_dry_run(data_home, tmp_path):
    """「预览数字」只试算，不改任何东西。"""
    path = tmp_path / "messy.csv"
    path.write_text(MESSY_CSV, encoding="utf-8")
    imported = library.import_dataset(str(path))

    preview = inspect_module.preview_interpretation(imported["asset"], "value")

    assert preview["checked"] == 4
    assert preview["conversion_failures"] == 1
    assert preview["samples"][0]["original"] == "001"
    assert preview["samples"][0]["interpreted"] == "1"


# ---------- 查询与口径 ----------


def test_numeric_comparison_requires_explicit_interpretation(imported):
    """在文本列上做数值比较是口径错误，报错而不是返回空结果。"""
    inspection = inspect_module.inspect_asset(imported["asset"])

    with pytest.raises(inspect_module.InspectionError) as excinfo:
        query_module.query_rows(
            inspection, {"filter": {"field": "score", "operator": "gte", "value": "80"}}
        )

    assert "显式解释为数字" in str(excinfo.value)


def test_numeric_comparison_works_after_interpretation(imported):
    inspection = inspect_module.inspect_asset(imported["asset"], {"score": "number"})

    result = query_module.query_rows(
        inspection, {"filter": {"field": "score", "operator": "gte", "value": "80"}}
    )

    assert result["total"] == 1


def test_aggregate_sum_requires_explicit_interpretation(imported):
    inspection = inspect_module.inspect_asset(imported["asset"])

    with pytest.raises(inspect_module.InspectionError):
        query_module.aggregate(inspection, "name", "score", "sum")


def test_aggregate_sum_after_interpretation(imported):
    inspection = inspect_module.inspect_asset(imported["asset"], {"score": "number"})

    result = query_module.aggregate(inspection, "name", "score", "sum")

    values = {group["label"]: group["value"] for group in result["groups"]}
    assert values["alice"] == 90
    assert values["bob"] == 75


def test_aggregate_count_needs_no_interpretation(imported):
    inspection = inspect_module.inspect_asset(imported["asset"])

    result = query_module.aggregate(inspection, "name", "", "count")

    values = {group["label"]: group["value"] for group in result["groups"]}
    assert values["alice"] == 1


def test_row_identity_survives_sorting(imported):
    """排序不改变行原本的序号与源行号。"""
    inspection = inspect_module.inspect_asset(imported["asset"])

    result = query_module.query_rows(
        inspection, {"sort": {"field": "name", "descending": True}}
    )

    # 按 name 降序：dave(4), carol(3), bob(2), alice(1)
    assert [row["row"] for row in result["rows"]] == [4, 3, 2, 1]


# ---------- 查询收据 ----------


def test_query_leaves_a_receipt(data_home, imported):
    """每次查询都留下收据：记了版本、口径，且默认待复核。"""
    outcome = query_module.run_query(
        imported["dataset"]["id"],
        question="每人一组多少分",
        spec={"columns": [], "filter": None, "sort": None, "limit": 50},
        interpretations={"score": "number"},
        unit="分",
        grain="每人一行",
        denominator="全部记录",
    )

    receipt = outcome["receipt"]
    assert receipt["dataset_id"] == imported["dataset"]["id"]
    assert receipt["asset_id"] == imported["asset"]["id"]
    assert receipt["sha256"] == imported["asset"]["sha256"]
    assert receipt["unit"] == "分"
    assert receipt["acceptance"] == "needs_review"
    assert query_module.get_receipt(receipt["query_id"]) is not None


def test_receipt_listing_is_newest_first(data_home, imported):
    query_module.run_query(
        imported["dataset"]["id"], question="第一个", spec={"limit": 5}
    )
    query_module.run_query(
        imported["dataset"]["id"], question="第二个", spec={"limit": 5}
    )

    receipts = query_module.list_receipts()

    assert len(receipts) == 2
    assert receipts[0]["question"] == "第二个"
