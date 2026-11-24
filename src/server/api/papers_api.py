"""论文库的 HTTP 接口：给论文阅读面板等界面用。

Agent 侧走 `Paper` 工具（src/tool/paper/），这里只服务界面：
列论文、读某页原文、导入。

失败时错误体里多一个 ``status``，面板据此分清「不可用」和「失败」。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.papers import library
from src.server.api import research_status
from src.tool.filesystem.utils import can_read

router = APIRouter(prefix="/api/papers", tags=["Paper Library"])


class PaperImportReq(BaseModel):
    path: str


@router.get("")
def list_papers():
    """列出论文库中的论文。"""
    return {"papers": library.list_papers()}


@router.post("/import")
def import_paper(req: PaperImportReq):
    """导入本机 PDF 到论文库，返回论文元数据。

    解析在请求线程里跑（FastAPI 的同步路由走线程池），大 PDF 会让这次请求等上几秒。
    """
    path = (req.path or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="缺少 path")
    if not can_read(path):
        raise HTTPException(status_code=403, detail=f"没有读取该文件的权限: {path}")
    try:
        return library.import_paper(path)
    except library.PaperError as exc:
        raise research_status.fail(exc) from exc


@router.get("/{paper_id}")
def get_paper(paper_id: str):
    """取一篇论文的元数据。"""
    meta = library.get_paper(paper_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"论文库中没有这篇论文: {paper_id}")
    return meta


@router.get("/{paper_id}/pages/{page}")
def get_page(paper_id: str, page: int):
    """读某篇论文某一页的原文。"""
    try:
        text = library.page_text(paper_id, page)
    except library.PaperError as exc:
        raise research_status.fail(exc) from exc
    return {"paper_id": paper_id, "page": page, "text": text}


@router.get("/{paper_id}/fulltext")
def get_fulltext(paper_id: str):
    """读整篇原文（分页拼接）。"""
    try:
        pages = library.all_pages(paper_id)
    except library.PaperError as exc:
        raise research_status.fail(exc) from exc
    return {"paper_id": paper_id, "pages": pages}
