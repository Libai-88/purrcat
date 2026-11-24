"""图表规格：口径、出处与拒收规则（SPEC-028）。"""

from __future__ import annotations

import json
import os

import pytest

from src.data import chart as chart_module
from src.data import library

CSV_CONTENT = """id,group,score
1,A,90
2,B,75
3,A,60
4,B,88
5,A,55
"""


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def imported(data_home, tmp_path):
    path = tmp_path / "chart-demo.csv"
    path.write_text(CSV_CONTENT, encoding="utf-8")
    return library.import_dataset(str(path))


def _chart(imported, **overrides):
    spec = {
        "type": "bar",
        "x": "group",
        "y": "score",
        "aggregation": "sum",
    }
    spec.update(overrides)
    return chart_module.make_chart(
        imported["dataset"]["id"],
        interpretations={"score": "number"},
        chart_type=spec.pop("type", "bar"),
        x_field=spec.pop("x", ""),
        y_field=spec.pop("y", ""),
        **spec,
    )


# ---------- 聚合与口径 ----------


def test_bar_chart_aggregates_by_category(imported):
    """按类目求和。"""
    document = _chart(imported)

    values = {row["label"]: row["value"] for row in document["rows"]}
    assert values == {"A": 205.0, "B": 163.0}
    assert document["chart"]["type"] == "bar"
    assert document["chart"]["aggregation"] == "sum"


def test_count_aggregation_needs_no_interpretation(imported):
    """计数不需要把列解释成数字。"""
    document = chart_module.make_chart(
        imported["dataset"]["id"],
        chart_type="bar",
        x_field="group",
        y_field="score",
        aggregation="count",
    )

    values = {row["label"]: row["value"] for row in document["rows"]}
    assert values == {"A": 3.0, "B": 2.0}


def test_sum_on_text_column_is_refused(imported):
    """AC-5：没解释成数字的列不能求和。"""
    with pytest.raises(chart_module.ChartError) as excinfo:
        chart_module.make_chart(
            imported["dataset"]["id"],
            chart_type="bar",
            x_field="group",
            y_field="score",
            aggregation="sum",
        )

    assert "显式解释为数字" in str(excinfo.value)


def test_label_and_value_column_must_differ(imported):
    """标签列与数值列相同就分不清横轴是什么。"""
    with pytest.raises(chart_module.ChartError) as excinfo:
        chart_module.make_chart(
            imported["dataset"]["id"],
            chart_type="bar",
            x_field="group",
            y_field="group",
            aggregation="count",
        )

    assert "必须不同" in str(excinfo.value)


def test_unknown_field_is_refused(imported):
    with pytest.raises(chart_module.ChartError):
        _chart(imported, x="nope")


def test_unknown_chart_type_is_refused(imported):
    with pytest.raises(chart_module.ChartError):
        _chart(imported, type="candlestick")


# ---------- 缺值与非法值 ----------


def test_missing_values_are_not_plotted_but_counted(data_home, tmp_path):
    """缺值与非数值不画，并计数——不给读者一根假的柱子。"""
    path = tmp_path / "holes.csv"
    path.write_text("group,score\nA,10\n,\nB,20\n", encoding="utf-8")
    imported = library.import_dataset(str(path))

    document = chart_module.make_chart(
        imported["dataset"]["id"],
        chart_type="bar",
        x_field="group",
        y_field="score",
        aggregation="sum",
        interpretations={"score": "number"},
    )

    assert len(document["rows"]) == 2
    assert document["source"]["excludedValues"] == 1


def test_scatter_needs_two_numeric_columns(imported):
    """散点图要两个数值列。"""
    with pytest.raises(chart_module.ChartError) as excinfo:
        chart_module.make_chart(
            imported["dataset"]["id"],
            chart_type="scatter",
            x_field="group",
            y_field="score",
            interpretations={"score": "number"},
        )

    assert "数值列" in str(excinfo.value)


def test_scatter_plots_points_with_provenance(imported):
    document = chart_module.make_chart(
        imported["dataset"]["id"],
        chart_type="scatter",
        x_field="id",
        y_field="score",
        interpretations={"id": "number", "score": "number"},
    )

    assert len(document["rows"]) == 5
    assert document["rows"][0]["x"] == 1
    assert document["rows"][0]["rowProvenance"][0]["ordinal"] == 1


def test_repeated_coordinates_are_refused(data_home, tmp_path):
    """重复坐标点会让图上互相盖住，直接拒绝。"""
    path = tmp_path / "dupes.csv"
    path.write_text("x,y\n1,2\n1,2\n", encoding="utf-8")
    imported = library.import_dataset(str(path))

    with pytest.raises(chart_module.ChartError) as excinfo:
        chart_module.make_chart(
            imported["dataset"]["id"],
            chart_type="scatter",
            x_field="x",
            y_field="y",
            interpretations={"x": "number", "y": "number"},
        )

    assert "重复的坐标点" in str(excinfo.value)


def test_at_most_fifty_groups(data_home, tmp_path):
    """最多画 50 组，其余记进 omittedGroups。"""
    lines = ["group,score"] + [f"G{i},{i}" for i in range(60)]
    path = tmp_path / "many.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    imported = library.import_dataset(str(path))

    document = chart_module.make_chart(
        imported["dataset"]["id"],
        chart_type="bar",
        x_field="group",
        y_field="score",
        aggregation="sum",
        interpretations={"score": "number"},
    )

    assert len(document["rows"]) == 50
    assert document["source"]["omittedGroups"] == 10


# ---------- 出处 ----------


def test_chart_carries_its_provenance(imported):
    """AC：一张图必须说得清这些数字是从哪来的。"""
    document = _chart(imported)

    source = document["source"]
    assert source["datasetId"] == imported["dataset"]["id"]
    assert source["assetId"] == imported["asset"]["id"]
    assert source["sha256"] == imported["asset"]["sha256"]
    assert source["versionLabel"] == "v1"
    assert source["parserVersion"]
    assert source["dataView"]["x"] == "group"
    assert source["dataView"]["interpretations"] == ["score"]
    assert source["report"]["row_count"] == 5


def test_chart_rows_record_where_each_value_came_from(imported):
    """每个数据点带着它来自原文件第几行。"""
    document = _chart(imported)

    provenance = document["rows"][0]["rowProvenance"]
    assert provenance[0]["ordinal"] == 1
    assert provenance[0]["line"] == 2


def test_chart_states_that_method_is_a_declaration(imported):
    document = _chart(imported)

    assert "不是科学检查" in document["method"]
    assert document["acceptance"] == "needs_review"


def test_chart_records_declared_unit(imported):
    document = chart_module.make_chart(
        imported["dataset"]["id"],
        chart_type="bar",
        x_field="group",
        y_field="score",
        aggregation="sum",
        interpretations={"score": "number"},
        unit="分",
        grain="每组一行",
        denominator="全部记录",
    )

    caveats = " ".join(document["source"]["caveats"])
    assert "分" in caveats
    assert "每组一行" in caveats
    assert "全部记录" in caveats


# ---------- 内容寻址 ----------


def test_saved_chart_is_content_addressed(imported, data_home):
    """同样的口径得到同样的 id；读时校验哈希。"""
    first = _chart(imported)
    second = _chart(imported)

    assert first["id"] == second["id"]
    assert chart_module.read_chart(first["id"])["id"] == first["id"]
    assert len(chart_module.list_charts()) == 1


def test_tampered_chart_is_refused(imported, data_home):
    """存盘的文件被改动过就拒绝读。"""
    document = _chart(imported)
    path = os.path.join(chart_module.charts_root(), str(document["id"]) + ".chart.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"id": document["id"], "rows": []}, handle)

    with pytest.raises(chart_module.ChartError):
        chart_module.read_chart(document["id"])
