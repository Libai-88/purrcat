"""研究记录的 HTTP 接口：给论文阅读面板等界面用。

Agent 侧走 `ResearchRecord` 工具（src/tool/research/），这里服务界面：
列记录、读记录、以及人工复核改可信度状态。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.papers import records

router = APIRouter(prefix="/api/research", tags=["Research Records"])


class AcceptanceReq(BaseModel):
    acceptance: str
    note: str = ""


@router.get("/records")
def list_records():
    """列出研究记录。"""
    return {"records": records.list_records()}


@router.get("/records/{record_id}")
def get_record(record_id: str):
    """读一条研究记录。"""
    record = records.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"没有这条研究记录: {record_id}")
    return record


@router.post("/records/{record_id}/acceptance")
def set_acceptance(record_id: str, req: AcceptanceReq):
    """人工复核：改记录的可信度状态。

    复核是人工动作，所以要留下说明；改动直接落在记录上，并记下上一次的状态。
    """
    record = records.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"没有这条研究记录: {record_id}")

    acceptance = (req.acceptance or "").strip()
    if acceptance not in records.ACCEPTANCE_VALUES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"acceptance 取值非法：{acceptance!r}，"
                f"可用：{', '.join(records.ACCEPTANCE_VALUES)}"
            ),
        )

    note = (req.note or "").strip()
    history = list(record.get("review_history") or [])
    history.append(
        {
            "from": record.get("acceptance"),
            "to": acceptance,
            "note": note,
            "at": records.now(),
        }
    )
    updated = {
        **record,
        "acceptance": acceptance,
        "updated_at": records.now(),
        "review_history": history,
    }
    records.save_record(updated)
    return updated
