"""科研自动化的定义与回执（SPEC-032）。

最要紧的两条不变量：

- 排上了 ≠ 跑完了（queued 与 succeeded 是两回事）；
- 跑完了 ≠ 结论对（回执里没有 acceptance / verification）。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.automation import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    RUN_VALUES,
    AutomationError,
    counts,
    create,
    delete,
    due,
    get_automation,
    list_automations,
    list_runs,
    record_run,
    update,
    update_run,
)


@pytest.fixture
def automation_home(tmp_path, monkeypatch):
    """把自动化库指向临时目录，测试不碰真实数据。"""
    import src.automation as automation

    monkeypatch.setattr(
        automation, "AUTOMATIONS_FILE", str(tmp_path / "automations.json")
    )
    return tmp_path


def _at(hour: int, minute: int = 0) -> datetime:
    base = datetime.now(timezone.utc).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return base


# ---------- 定义 ----------


def test_create_makes_a_definition(automation_home):
    item = create("查新论文", "看看 arXiv 上有没有新论文", "08:30", "everyday")

    assert item["id"].startswith("auto_")
    assert item["title"] == "查新论文"
    assert item["instruction"] == "看看 arXiv 上有没有新论文"
    assert item["enabled"] is True
    assert item["next_run_at"]
    assert list_automations() == [item]


def test_create_requires_a_title(automation_home):
    with pytest.raises(AutomationError):
        create("", "做点什么", "08:30")


def test_create_requires_an_instruction(automation_home):
    """没有指示的话，到点也不知道让 Agent 做什么。"""
    with pytest.raises(AutomationError):
        create("查新论文", "  ", "08:30")


def test_create_rejects_bad_time(automation_home):
    with pytest.raises(AutomationError):
        create("查新论文", "做点什么", "8点半")


def test_create_rejects_bad_repeat_rule(automation_home):
    with pytest.raises(AutomationError):
        create("查新论文", "做点什么", "08:30", "每天")


def test_update_changes_the_definition(automation_home):
    item = create("查新论文", "做点什么", "08:30")

    changed = update(item["id"], title="换个名字", instruction="换件事")

    assert changed["title"] == "换个名字"
    assert changed["instruction"] == "换件事"
    assert get_automation(item["id"])["title"] == "换个名字"


def test_update_recomputes_next_run(automation_home):
    item = create("查新论文", "做点什么", "08:30")

    changed = update(item["id"], trigger_time="21:15")

    assert changed["next_run_at"] != item["next_run_at"]


def test_disable_clears_next_run_and_reenable_restores(automation_home):
    """停用后不再有下一次触发；重新启用时再算一次。"""
    item = create("查新论文", "做点什么", "08:30")

    off = update(item["id"], enabled=False)
    assert off["enabled"] is False
    assert off["next_run_at"] is None

    on = update(item["id"], enabled=True)
    assert on["enabled"] is True
    assert on["next_run_at"]


def test_delete_removes_the_definition_but_keeps_runs(automation_home):
    item = create("查新论文", "做点什么", "08:30")
    record_run(item["id"], item["title"], item["instruction"])

    delete(item["id"])

    assert get_automation(item["id"]) is None
    assert len(list_runs()) == 1, "跑完的回执是历史，不该跟着定义一起没"


def test_update_unknown_id_is_refused(automation_home):
    with pytest.raises(AutomationError):
        update("auto_nope", title="x")


# ---------- 到点 ----------


def test_due_picks_an_automation_that_has_arrived(automation_home):
    # 以当天 07:00 为基准建一条 08:30 的自动化。
    create("查新论文", "做点什么", "08:30", now=_at(7))

    # 时刻已经过去 → 到点
    assert len(due(now=_at(9))) == 1
    # 时刻还没到 → 不到点
    assert due(now=_at(7, 30)) == []


def test_due_skips_disabled(automation_home):
    item = create("查新论文", "做点什么", "08:30", now=_at(7))
    update(item["id"], enabled=False)

    assert due(now=_at(9)) == []


def test_a_missed_slot_runs_once_not_a_storm(automation_home):
    """停机期间错过几个时刻，醒来后只补跑一次，不堆一堆。"""
    create("查新论文", "做点什么", "08:30", "everyday", now=_at(7))

    later = _at(23)
    assert len(due(now=later)) == 1


# ---------- 回执 ----------


def test_run_starts_as_queued_not_succeeded(automation_home):
    """AC-5：排上了不等于跑完了。"""
    item = create("查新论文", "做点什么", "08:30")

    run = record_run(item["id"], item["title"], item["instruction"])

    assert run["state"] == RUN_QUEUED
    assert run["state"] != RUN_SUCCEEDED


def test_run_states_are_a_closed_vocabulary(automation_home):
    item = create("查新论文", "做点什么", "08:30")
    run = record_run(item["id"], item["title"], item["instruction"])

    assert run["state"] in RUN_VALUES

    with pytest.raises(AutomationError):
        record_run(item["id"], item["title"], item["instruction"], state="也许成功了吧")


def test_run_progresses_to_succeeded(automation_home):
    item = create("查新论文", "做点什么", "08:30")
    run = record_run(item["id"], item["title"], item["instruction"])

    update_run(run["id"], RUN_RUNNING)
    done = update_run(run["id"], RUN_SUCCEEDED)

    assert done["state"] == RUN_SUCCEEDED
    assert done["started_at"]
    assert done["finished_at"]


def test_finished_run_is_not_rewritten(automation_home):
    """已经跑完的事情不会被后来的事件改写。"""
    item = create("查新论文", "做点什么", "08:30")
    run = record_run(item["id"], item["title"], item["instruction"])
    update_run(run["id"], RUN_SUCCEEDED)

    again = update_run(run["id"], RUN_FAILED, detail="后来的失败")

    assert again["state"] == RUN_SUCCEEDED
    assert again["detail"] == ""


def test_run_has_no_acceptance_or_verification(automation_home):
    """AC-6：回执只说运行怎么样，不说结论可不可信。"""
    item = create("查新论文", "做点什么", "08:30")
    run = record_run(item["id"], item["title"], item["instruction"])

    assert "acceptance" not in run
    assert "verification" not in run


def test_cancelled_run_is_its_own_state(automation_home):
    item = create("查新论文", "做点什么", "08:30")
    run = record_run(item["id"], item["title"], item["instruction"])

    cancelled = update_run(run["id"], RUN_CANCELLED, detail="用户取消了")

    assert cancelled["state"] == RUN_CANCELLED
    assert cancelled["detail"] == "用户取消了"


def test_counts_tally_by_state(automation_home):
    item = create("查新论文", "做点什么", "08:30")
    first = record_run(item["id"], item["title"], item["instruction"])
    update_run(first["id"], RUN_SUCCEEDED)
    record_run(item["id"], item["title"], item["instruction"])

    tally = counts()

    assert tally[RUN_SUCCEEDED] == 1
    assert tally[RUN_QUEUED] == 1


def test_runs_are_listed_newest_first(automation_home):
    item = create("查新论文", "做点什么", "08:30")
    first = record_run(item["id"], item["title"], item["instruction"])
    second = record_run(item["id"], item["title"], item["instruction"])

    runs = list_runs()

    assert runs[0]["id"] == second["id"]
    assert runs[1]["id"] == first["id"]


def test_runs_can_be_filtered_by_automation(automation_home):
    first = create("甲", "做点事", "08:30")
    second = create("乙", "做点事", "09:30")
    record_run(first["id"], first["title"], first["instruction"])
    record_run(second["id"], second["title"], second["instruction"])

    assert len(list_runs(automation_id=first["id"])) == 1
