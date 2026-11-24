"""环境的 HTTP 接口：给环境面板与 Agent 侧用。

只读。这里不装东西、不改系统、不执行代码。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.environments import catalog, observer

router = APIRouter(prefix="/api/environments", tags=["Environments"])


@router.get("")
def observe_all():
    """观察全部工具 + 执行后端。"""
    return observer.observe_all()


@router.get("/tools")
def list_tools():
    """工具目录（不探测）。"""
    return {"tools": catalog.list_tools()}


@router.get("/tools/{tool_id}")
def observe_tool(tool_id: str):
    """只读观察一个工具。"""
    try:
        return observer.observe_tool(tool_id)
    except catalog.EnvironmentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/capabilities")
def list_capabilities():
    """能力声明：每种能力能做什么、不能推出什么。"""
    return {"capabilities": catalog.list_capabilities()}


@router.get("/capabilities/{capability_id}")
def read_capability(capability_id: str):
    try:
        return catalog.get_capability(capability_id)
    except catalog.EnvironmentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
