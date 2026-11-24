"""面板异步状态词表与推导（SPEC-031）。

词表只有一份，写在 ``ui/web-minimal/assets/async-state.js`` 里，
前后端都从那里读，所以这里既测推导规则，也测「后端读到的就是前端那份」。
"""

from __future__ import annotations

import pytest

from src.utils import async_state


# ---------- 词表 ----------


def test_spec_file_is_readable():
    spec = async_state.load_spec()

    assert spec["version"] >= 1
    assert spec["data"] and spec["request"] and spec["result"]


def test_vocabularies_are_closed():
    """词表必须是封闭的：取值之外一律拒收。"""
    for values in (
        async_state.data_values(),
        async_state.request_values(),
        async_state.result_values(),
        async_state.state_values(),
        async_state.reason_values(),
        async_state.action_values(),
    ):
        assert values
        assert len(set(values)) == len(values), "词表里不允许重复取值"


def test_every_rule_target_is_a_known_state():
    spec = async_state.load_spec()
    known = set(async_state.state_values())

    for rule in spec["rules"]:
        assert rule["state"] in known


def test_rules_only_use_known_axis_values():
    spec = async_state.load_spec()
    axes = {
        "data": set(async_state.data_values()),
        "request": set(async_state.request_values()),
        "result": set(async_state.result_values()),
    }

    for rule in spec["rules"]:
        for axis, allowed in axes.items():
            if axis in rule:
                assert rule[axis] in allowed


# ---------- 三轴推导 ----------


def test_ready_when_everything_is_fine():
    assert async_state.derive("complete", "idle", "ok") == "ready"


def test_first_load_shows_skeleton_not_empty():
    """首次加载不能显示「暂无数据」——数据还没到，不是没有数据。

    请求还在飞的时候没有业务结果，所以 result 是 pending。
    """
    assert async_state.derive("none", "first_load", "pending") == "first_load"


def test_background_refresh_keeps_existing_content():
    """后台刷新：旧内容留着，只提示更新中。"""
    assert async_state.derive("complete", "refresh", "pending") == "refreshing"


def test_empty_result_is_distinguishable_from_loading():
    """「请求回来了但没有内容」跟「请求还在飞」是两回事。"""
    assert async_state.derive("none", "idle", "empty") == "empty"
    assert async_state.derive("none", "first_load", "pending") == "first_load"


def test_partial_data_is_not_reported_as_full():
    assert async_state.derive("partial", "idle", "ok") == "partial"


def test_stale_data_is_not_reported_as_full():
    assert async_state.derive("stale", "idle", "ok") == "stale"


def test_first_load_failure_differs_from_refresh_failure():
    """首次加载失败没有旧内容可留；刷新失败要留住上一次的结果。

    分开这两者的依据是「屏幕上现在有没有内容」——客户端才知道，
    所以 data 轴由客户端给，服务端只说业务结果。
    """
    assert async_state.derive("none", "idle", "failed") == "first_load_failed"
    assert async_state.derive("complete", "idle", "failed") == "refresh_failed"


def test_unavailable_is_distinct_from_failed():
    """缺权限 / 缺环境 / 条件未满足，跟「读失败了」不是一回事。"""
    assert async_state.derive("none", "idle", "unavailable") == "unavailable"
    assert async_state.derive("none", "idle", "failed") == "first_load_failed"


def test_refresh_unavailable_keeps_old_content():
    """来源没了但屏幕上还有旧内容：留住它，并说明取不到了。"""
    assert (
        async_state.derive("complete", "idle", "unavailable") == "refresh_unavailable"
    )


def test_pending_result_never_reported_as_failure():
    """请求还在飞的时候不能说它失败了。"""
    assert async_state.derive("none", "first_load", "pending") != "first_load_failed"
    assert async_state.derive("complete", "refresh", "pending") != "refresh_failed"


def test_submitting_and_cancelling_are_separate_states():
    assert async_state.derive("complete", "submitting", "ok") == "submitting"
    assert async_state.derive("complete", "cancelling", "ok") == "cancelling"
    assert async_state.derive("complete", "cancelled", "ok") == "cancelled"
    assert async_state.derive("complete", "completed", "ok") == "completed"


def test_request_success_does_not_mean_verified():
    """状态层只说界面处于什么状态，不给结论盖「已验证」的章。

    状态字典里不该出现 acceptance / verification 这类认识论词。
    """
    payload = async_state.status("complete", "idle", "ok")

    assert "acceptance" not in payload
    assert "verification" not in payload
    assert payload["state"] == "ready"


@pytest.mark.parametrize(
    "bad",
    [
        {"data": "nope"},
        {"request": "nope"},
        {"result": "nope"},
    ],
)
def test_unknown_axis_values_are_refused(bad):
    kwargs = {"data": "complete", "request": "idle", "result": "ok"}
    kwargs.update(bad)

    with pytest.raises(async_state.AsyncStateError):
        async_state.derive(**kwargs)


# ---------- 状态描述 ----------


def test_status_carries_three_axes():
    payload = async_state.status("stale", "idle", "ok", reason="source_changed")

    assert payload["state"] == "stale"
    assert payload["data"] == "stale"
    assert payload["request"] == "idle"
    assert payload["result"] == "ok"
    assert payload["reason"] == "source_changed"


def test_status_omits_unset_optional_fields():
    payload = async_state.status("complete", "idle", "ok")

    assert "reason" not in payload
    assert "detail" not in payload
    assert "action" not in payload


def test_status_refuses_unknown_reason_and_action():
    with pytest.raises(async_state.AsyncStateError):
        async_state.status("complete", "idle", "ok", reason="made_up")

    with pytest.raises(async_state.AsyncStateError):
        async_state.status("complete", "idle", "ok", action="made_up")


# ---------- 与前端同源 ----------


def test_python_reads_the_same_file_the_frontend_loads():
    """后端读到的词表必须来自前端加载的那个文件，不是另抄一份。"""
    spec_path = async_state.SPEC_PATH.replace("\\", "/")

    assert spec_path.endswith("ui/web-minimal/assets/async-state.js")

    source = open(async_state.SPEC_PATH, "r", encoding="utf-8").read()
    assert "purrcat:async-state:spec" in source
    assert "PurrCatAsyncSpec" in source
