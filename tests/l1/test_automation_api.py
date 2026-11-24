"""自动化的 HTTP 接口与触发链路（SPEC-032）。

关键断言：到点真的会跑一次并留下回执；Agent 忙时不跑、不堆回执。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.automation import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_SUCCEEDED,
    list_runs,
)
from src.automation import runner as automation_runner
from src.server.api import automation_api


@pytest.fixture
def automation_home(tmp_path, monkeypatch):
    import src.automation as automation

    monkeypatch.setattr(
        automation, "AUTOMATIONS_FILE", str(tmp_path / "automations.json")
    )
    return tmp_path


@pytest.fixture
def client(automation_home):
    app = FastAPI()
    app.include_router(automation_api.router)
    return TestClient(app)


@pytest.fixture
def fake_agent(monkeypatch):
    """替掉真的 Agent：记录被推了什么，并按剧本给出这一轮的结果。

    ``outcome`` 可以是 ``ok`` / ``fault`` / ``interrupt``——对应 Agent
    历史里最后那条 assistant 消息的三种形态。
    """
    pushed: list[str] = []
    state = {"value": "idle"}
    history: list[dict] = []
    outcome = {"value": "ok"}

    class _Agent:
        session_id = "sess-test"

        @property
        def state(self):
            return state["value"]

        def get_history(self):
            return list(history)

    monkeypatch.setattr("src.agent.manager.manager._agent", _Agent(), raising=False)
    monkeypatch.setattr(
        automation_runner,
        "_agent_idle",
        lambda: state["value"] == "idle",
    )

    def _push(instruction: str) -> bool:
        pushed.append(instruction)
        history.append({"role": "user", "content": instruction})
        if outcome["value"] == "silent":
            # 这一轮什么也没产出：Agent 推了但没说话。
            return True
        if outcome["value"] == "fault":
            history.append(
                {"role": "assistant", "content": "[Error.Fault] 交互断层: 401 鉴权失败"}
            )
        elif outcome["value"] == "interrupt":
            history.append(
                {"role": "assistant", "content": "[Warn.Interrupt] 运行被强制中断。"}
            )
        else:
            history.append({"role": "assistant", "content": "查完了，标题如下……"})
        return True

    monkeypatch.setattr(automation_runner, "_push", _push)
    monkeypatch.setattr(automation_runner, "_session_id", lambda: "sess-test")
    # 等这一轮的上限压到很短：静默那一轮否则要干等三十分钟。
    monkeypatch.setattr(automation_runner, "TURN_WAIT_SECONDS", 1.0)
    return {"pushed": pushed, "state": state, "outcome": outcome}


# ---------- 定义 ----------


def test_create_and_list(client, automation_home):
    response = client.post(
        "/api/automations",
        json={
            "title": "查新论文",
            "instruction": "看看 arXiv 上有没有新论文",
            "trigger_time": "08:30",
            "repeat_rule": "everyday",
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["id"].startswith("auto_")

    listing = client.get("/api/automations").json()
    assert len(listing["automations"]) == 1
    assert listing["counts"][RUN_QUEUED] == 0


def test_create_rejects_bad_input(client, automation_home):
    response = client.post(
        "/api/automations",
        json={"title": "x", "instruction": "y", "trigger_time": "八点半"},
    )

    assert response.status_code == 400


def test_read_update_delete(client, automation_home):
    created = client.post(
        "/api/automations",
        json={
            "title": "查新论文",
            "instruction": "做点什么",
            "trigger_time": "08:30",
        },
    ).json()

    read = client.get(f"/api/automations/{created['id']}")
    assert read.status_code == 200
    assert read.json()["automation"]["title"] == "查新论文"

    changed = client.put(f"/api/automations/{created['id']}", json={"title": "新名字"})
    assert changed.status_code == 200
    assert changed.json()["title"] == "新名字"

    removed = client.delete(f"/api/automations/{created['id']}")
    assert removed.status_code == 200
    assert client.get(f"/api/automations/{created['id']}").status_code == 404


# ---------- 触发 ----------


def test_due_automation_actually_runs_and_leaves_a_run(
    client, automation_home, fake_agent
):
    """AC-2：到点会真的推给 Agent，并留下回执。"""
    from datetime import datetime, timezone

    import src.automation as automation

    # 用确定的基准时刻建一条 08:30 的自动化，让下一次触发落在今天。
    base = datetime.now(timezone.utc).replace(hour=7, minute=0, second=0, microsecond=0)
    automation.create("查新论文", "看看 arXiv 上有没有新论文", "08:30", now=base)

    results = automation_runner.run_due(now=base.replace(hour=9))

    assert len(results) == 1
    assert fake_agent["pushed"] == ["看看 arXiv 上有没有新论文"]

    runs = list_runs()
    assert len(runs) == 1
    assert runs[0]["state"] == RUN_SUCCEEDED


def test_busy_agent_defers_without_queuing_a_run(client, automation_home, fake_agent):
    """AC-3：Agent 忙的时候这一轮不跑，也不留回执。

    留一条 queued 回执等于说「排上了」，但实际上什么都没排——
    那正是 Pero 说的「排上了 ≠ 跑完了」要防的混淆。
    """
    from datetime import datetime, timezone

    base = datetime.now(timezone.utc).replace(hour=7, minute=0, second=0, microsecond=0)
    import src.automation as automation

    automation.create("查新论文", "做点什么", "08:30", now=base)

    fake_agent["state"]["value"] = "handling"
    results = automation_runner.run_due(now=base.replace(hour=9))

    assert results == []
    assert list_runs() == []
    assert fake_agent["pushed"] == []


def test_manual_run_leaves_a_receipt(client, automation_home, fake_agent):
    """AC-7：手动触发也会留下回执。"""
    created = client.post(
        "/api/automations",
        json={
            "title": "查新论文",
            "instruction": "做点什么",
            "trigger_time": "08:30",
        },
    ).json()

    response = client.post(f"/api/automations/{created['id']}/run")

    assert response.status_code == 200
    run = response.json()["run"]
    assert run["state"] == RUN_SUCCEEDED
    assert fake_agent["pushed"] == ["做点什么"]


def test_run_of_unknown_automation_is_404(client, automation_home, fake_agent):
    response = client.post("/api/automations/auto_nope/run")

    assert response.status_code == 404


def test_a_faulty_turn_is_recorded_as_failed(client, automation_home, fake_agent):
    """Agent 回到 idle 不等于这一轮成功。

    中途出了断层（模型鉴权失败之类），回执必须说 failed——
    说 succeeded 就是把一次失败报成了成功。
    """
    fake_agent["outcome"]["value"] = "fault"
    created = client.post(
        "/api/automations",
        json={
            "title": "查新论文",
            "instruction": "做点什么",
            "trigger_time": "08:30",
        },
    ).json()

    response = client.post(f"/api/automations/{created['id']}/run")

    run = response.json()["run"]
    assert run["state"] == RUN_FAILED
    assert "交互断层" in run["detail"]


def test_an_interrupted_turn_is_recorded_as_cancelled(
    client, automation_home, fake_agent
):
    fake_agent["outcome"]["value"] = "interrupt"
    created = client.post(
        "/api/automations",
        json={
            "title": "查新论文",
            "instruction": "做点什么",
            "trigger_time": "08:30",
        },
    ).json()

    response = client.post(f"/api/automations/{created['id']}/run")

    run = response.json()["run"]
    assert run["state"] == RUN_CANCELLED


def test_a_silent_turn_is_not_reported_as_succeeded(
    client, automation_home, fake_agent
):
    """这一轮什么也没产出，不能报「跑完了」。

    刚推完的那一刻 Agent 也是 idle，但那时它还没开始处理这一轮。
    """
    fake_agent["outcome"]["value"] = "silent"
    created = client.post(
        "/api/automations",
        json={
            "title": "查新论文",
            "instruction": "做点什么",
            "trigger_time": "08:30",
        },
    ).json()

    response = client.post(f"/api/automations/{created['id']}/run")

    run = response.json()["run"]
    assert run["state"] != RUN_SUCCEEDED


def test_a_clean_turn_is_recorded_as_succeeded(client, automation_home, fake_agent):
    created = client.post(
        "/api/automations",
        json={
            "title": "查新论文",
            "instruction": "做点什么",
            "trigger_time": "08:30",
        },
    ).json()

    response = client.post(f"/api/automations/{created['id']}/run")

    run = response.json()["run"]
    assert run["state"] == RUN_SUCCEEDED


def test_runs_endpoint_lists_receipts(client, automation_home, fake_agent):
    created = client.post(
        "/api/automations",
        json={
            "title": "查新论文",
            "instruction": "做点什么",
            "trigger_time": "08:30",
        },
    ).json()
    client.post(f"/api/automations/{created['id']}/run")

    response = client.get(f"/api/automations/{created['id']}")

    assert response.status_code == 200
    assert len(response.json()["runs"]) == 1
