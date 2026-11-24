"""数据集的 HTTP 接口：给数据工作台面板用。

Agent 侧走 `Data` 工具（src/tool/data/），这里服务界面。
"""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.data import inspect as inspect_module
from src.data import library, query as query_module

router = APIRouter(prefix="/api/data", tags=["Data Library"])


class ImportReq(BaseModel):
    path: str
    name: str = ""
    kind: str = "dataset"
    source: str = ""
    license: str = ""
    project_ref: str = ""
    dataset_id: str = ""


class QueryReq(BaseModel):
    asset_id: str = ""
    question: str = ""
    spec: dict = {}
    interpretations: dict = {}
    unit: str = ""
    grain: str = ""
    denominator: str = ""


@router.get("/datasets")
def list_datasets(include_archived: bool = False):
    """列出数据集。"""
    return {"datasets": library.list_datasets(include_archived=include_archived)}


@router.post("/datasets/import")
def import_dataset(req: ImportReq):
    """导入一个数据文件；给了 dataset_id 就是给该数据集追加一个版本。"""
    try:
        imported = library.import_dataset(
            req.path,
            name=req.name,
            kind=req.kind,
            source=req.source,
            license_name=req.license,
            project_ref=req.project_ref,
            dataset_id=req.dataset_id,
        )
    except library.DataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return imported


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str):
    """取一个数据集及其版本。"""
    dataset = library.get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"没有这个数据集: {dataset_id}")
    return dataset


@router.get("/datasets/{dataset_id}/inspection")
def inspect_version(dataset_id: str, asset_id: str = "", interpretations: str = ""):
    """检查某一版：字段画像与质量报告。"""
    try:
        resolved = library.resolve_version(dataset_id, asset_id)
    except library.DataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    parsed = {}
    if interpretations:
        try:
            parsed = json.loads(interpretations)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="interpretations 不是合法 JSON"
            ) from exc

    try:
        inspection = inspect_module.inspect_asset(resolved["asset"], parsed)
    except inspect_module.InspectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "dataset_id": dataset_id,
        "asset": resolved["asset"],
        "version_label": library.version_label(
            resolved["dataset"], resolved["asset"]["id"]
        ),
        "report": inspection["report"],
        "fields": inspection["fields"],
        "sample": [
            {
                "row": row.ordinal,
                "source_line": row.line,
                "cells": [cell.to_dict() for cell in row.cells.values()],
            }
            for row in inspection["rows"][:20]
        ],
    }


@router.post("/datasets/{dataset_id}/query")
def run_query(dataset_id: str, req: QueryReq):
    """跑一次查询，留下收据。"""
    try:
        outcome = query_module.run_query(
            dataset_id,
            req.asset_id,
            question=req.question,
            spec=req.spec or {},
            interpretations=req.interpretations or {},
            unit=req.unit,
            grain=req.grain,
            denominator=req.denominator,
        )
    except (library.DataError, inspect_module.InspectionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return outcome


@router.get("/receipts")
def list_receipts():
    """列出查询收据。"""
    return {"receipts": query_module.list_receipts()}


@router.get("/receipts/{query_id}")
def get_receipt(query_id: str):
    """读一条查询收据。"""
    receipt = query_module.get_receipt(query_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail=f"没有这条收据: {query_id}")
    return receipt
