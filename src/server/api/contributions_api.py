"""贡献工作区的 HTTP 接口：给贡献面板与 Agent 侧用。

发布是对外动作，只在 ``POST /publish`` 里发生，且需要用户显式调用。
审阅 token 是 diff 的乐观锁——过期就拒收。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.contributions import store
from src.contributions.domain import ContributionError, ReviewChanged

router = APIRouter(prefix="/api/contributions", tags=["Contributions"])


class PrepareReq(BaseModel):
    task_id: str
    repository: str
    workspace: str
    title: str
    source_url: str = ""
    source_revision: str = ""


class TokenReq(BaseModel):
    review_token: str


@router.get("")
def list_all():
    return {"contributions": store.list_all()}


@router.get("/{task_id}")
def read(task_id: str):
    record = store.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"没有这个任务的工作区：{task_id}")
    return record


@router.post("/prepare")
def prepare(req: PrepareReq):
    try:
        return store.prepare(
            task_id=req.task_id,
            repository=req.repository,
            workspace=req.workspace,
            title=req.title,
            source_url=req.source_url,
            source_revision=req.source_revision,
        )
    except ContributionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{task_id}/start")
def start(task_id: str):
    try:
        return store.start(task_id)
    except ContributionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{task_id}/review")
def review(task_id: str):
    try:
        return store.review(task_id)
    except ContributionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{task_id}/ready")
def ready(task_id: str, req: TokenReq):
    try:
        return store.mark_ready(task_id, req.review_token)
    except ReviewChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ContributionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{task_id}/publish")
def publish(task_id: str, req: TokenReq):
    """发草稿 PR。用户显式调用才会走到这里。"""
    try:
        return store.publish(task_id, req.review_token)
    except ReviewChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ContributionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{task_id}/release")
def release(task_id: str):
    try:
        return store.release(task_id)
    except ContributionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
