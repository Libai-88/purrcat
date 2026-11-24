"""自动化的 HTTP 接口：给自动化面板与 Agent 侧用。

面板看得到「有哪些自动化」「跑过几次」「每次的结果是什么」；
回执里只有运行状态，没有结论可信度——那是 acceptance 的事。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.automation import (
    AutomationError,
    counts,
    create,
    delete,
    get_automation,
    list_automations,
    list_runs,
    update,
)
from src.automation import runner as automation_runner

router = APIRouter(prefix="/api/automations", tags=["Automation"])


class AutomationReq(BaseModel):
    title: str
    instruction: str
    trigger_time: str
    repeat_rule: str = "none"
    enabled: bool = True


class AutomationUpdateReq(BaseModel):
    title: str | None = None
    instruction: str | None = None
    trigger_time: str | None = None
    repeat_rule: str | None = None
    enabled: bool | None = None


@router.get("")
def list_all():
    """列出自动化与最近的回执。"""
    return {
        "automations": list_automations(),
        "runs": list_runs(limit=50),
        "counts": counts(),
    }


@router.post("")
def create_automation(req: AutomationReq):
    """建一条自动化。"""
    try:
        return create(
            title=req.title,
            instruction=req.instruction,
            trigger_time=req.trigger_time,
            repeat_rule=req.repeat_rule,
            enabled=req.enabled,
        )
    except AutomationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{automation_id}")
def read_automation(automation_id: str):
    """读一条自动化与它的回执。"""
    item = get_automation(automation_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"没有这条自动化：{automation_id}")
    return {
        "automation": item,
        "runs": list_runs(automation_id=automation_id, limit=50),
    }


@router.put("/{automation_id}")
def update_automation(automation_id: str, req: AutomationUpdateReq):
    """改一条自动化。"""
    try:
        return update(
            automation_id,
            title=req.title,
            instruction=req.instruction,
            trigger_time=req.trigger_time,
            repeat_rule=req.repeat_rule,
            enabled=req.enabled,
        )
    except AutomationError as exc:
        raise HTTPException(
            status_code=404 if "没有这条" in str(exc) else 400, detail=str(exc)
        ) from exc


@router.delete("/{automation_id}")
def delete_automation(automation_id: str):
    """删掉一条自动化。已经跑完的回执留着——那是历史。"""
    try:
        return delete(automation_id)
    except AutomationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{automation_id}/run")
def run_now(automation_id: str):
    """手动触发一次。"""
    try:
        run = automation_runner.run_now(automation_id)
    except AutomationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"run": run}
