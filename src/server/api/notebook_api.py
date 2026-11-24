"""研究文档的 HTTP 接口：给笔记面板和 Agent 用。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.notebook import document as doc
from src.notebook import export as export_module
from src.notebook import store, table

router = APIRouter(prefix="/api/notebooks", tags=["Notebook"])


class CommitReq(BaseModel):
    document: dict
    expected_revision: int | None = None


class EvaluateReq(BaseModel):
    document: dict


@router.get("")
def list_documents():
    """列出所有笔记。"""
    return {"documents": store.list_documents()}


@router.post("/evaluate")
def evaluate(req: EvaluateReq):
    """算出一个文档里所有表格的值。

    公式引擎只有一份实现（Python），面板与 Agent 都调它，避免两份实现漂移。
    """
    try:
        validated = doc.validate_document(req.document)
    except doc.DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sheets = {}
    for index, block in enumerate(validated["blocks"]):
        if block["kind"] != doc.BLOCK_TABLE:
            continue
        name = block.get("block_id") or f"Sheet{index + 1}"
        sheets[name] = block["attrs"]["sheet"]

    values = table.evaluate_sheets(sheets)
    return {"values": values, "sheets": list(sheets)}


@router.get("/{doc_id}")
def read_document(doc_id: str, revision: int | None = None):
    """读某一版修订；不给修订号就读最新版。"""
    try:
        record = store.read(doc_id, revision)
    except store.NotebookError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return record


@router.post("/{doc_id}")
def commit_document(doc_id: str, req: CommitReq):
    """提交一次修订；修订号对不上会报冲突。"""
    try:
        return store.commit(doc_id, req.document, req.expected_revision)
    except store.RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except doc.DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except store.NotebookError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{doc_id}/history")
def document_history(doc_id: str):
    """修订历史。"""
    return {"history": store.revision_history(doc_id)}


@router.get("/{doc_id}/export")
def export_document(doc_id: str, revision: int | None = None):
    """导出成 Markdown，附一份损失清单。"""
    try:
        record = store.read(doc_id, revision)
    except store.NotebookError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    document = record["document"]
    sheets = {}
    for index, block in enumerate(document.get("blocks") or []):
        if block["kind"] != doc.BLOCK_TABLE:
            continue
        name = block.get("block_id") or f"Sheet{index + 1}"
        sheets[name] = block["attrs"]["sheet"]

    values = table.evaluate_sheets(sheets)
    merged = {}
    for sheet_name, sheet_values in values.items():
        merged.update(sheet_values)

    markdown, losses = export_module.export_markdown(document, merged)
    return {"markdown": markdown, "losses": losses, "revision": record["revision"]}
