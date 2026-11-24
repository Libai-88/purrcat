"""连接器的 HTTP 接口：给连接器面板与 Agent 侧用。

面板看得到：有哪些连接器、某次拉取留下了什么凭据、拉取失败是哪一类。
凭据里只有出处，没有可信度——那不在这一层。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.connectors import catalog, landing, provenance
from src.connectors.catalog import ConnectorError, PullError

router = APIRouter(prefix="/api/connectors", tags=["Connectors"])


class SearchReq(BaseModel):
    connector_id: str
    query: str
    count: int = 10


class PullReq(BaseModel):
    connector_id: str
    query: str
    count: int = 10


class PaperReq(BaseModel):
    connector_id: str = "arxiv"
    pdf_url: str
    title: str = ""


@router.get("")
def list_all():
    """列出连接器目录与最近的来源凭据。"""
    return {
        "connectors": catalog.list_connectors(),
        "provenance": provenance.list_all(limit=50),
    }


@router.get("/{connector_id}")
def read_connector(connector_id: str):
    """读一个连接器的目录信息。"""
    try:
        return catalog.get_connector(connector_id)
    except ConnectorError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/search")
def search(req: SearchReq):
    """只检索，不落库。

    检索结果本身也是**候选**，不是结论——所以这里不写来源凭据，
    凭据是「真的拉下来并入库了」才有的。
    """
    try:
        catalog.get_connector(req.connector_id)
        outcome = landing.search(req.connector_id, req.query, req.count)
    except ConnectorError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PullError as exc:
        raise HTTPException(
            status_code=502, detail={"message": exc.message, "kind": exc.kind}
        ) from exc
    return outcome


@router.post("/pull")
def pull(req: PullReq):
    """拉取并入库，留下来源凭据。"""
    try:
        catalog.get_connector(req.connector_id)
        outcome = landing.land_metadata(req.connector_id, req.query, req.count)
    except ConnectorError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PullError as exc:
        raise HTTPException(
            status_code=502, detail={"message": exc.message, "kind": exc.kind}
        ) from exc
    return outcome


@router.post("/paper")
def pull_paper(req: PaperReq):
    """把论文原文 PDF 拉进论文库。"""
    try:
        catalog.get_connector(req.connector_id)
        outcome = landing.land_paper(req.connector_id, req.pdf_url, req.title)
    except ConnectorError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PullError as exc:
        raise HTTPException(
            status_code=502, detail={"message": exc.message, "kind": exc.kind}
        ) from exc
    return outcome


@router.get("/provenance/{provenance_id}")
def read_provenance(provenance_id: str):
    """读一条来源凭据。"""
    record = provenance.get(provenance_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"没有这条来源凭据：{provenance_id}"
        )
    return record
