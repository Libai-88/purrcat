"""科研类接口的状态回执。

面板要分清三件事：有哪些数据、请求在做什么、业务结果是什么。
服务端知道其中两件（data 与 result），把结果连同状态一起回给面板；
request 由客户端自己补（它知道这是首次加载还是刷新）。

成功响应保持原样（契约冻结）；只有错误响应多带一个 ``status``，
让面板能分清「不可用」和「失败」，也知道该给「重试」还是「导入」。
"""

from __future__ import annotations

from fastapi import HTTPException

from src.utils import panel_state


class ResearchError(HTTPException):
    """带状态语义的科研类错误。

    ``status`` 里说明这次失败属于哪一类，以及用户下一步能做什么。
    """

    def __init__(
        self,
        exc: Exception,
        code: int = 400,
        request: str = "idle",
        reason: str = "",
    ):
        detail = str(exc)
        super().__init__(status_code=code, detail=detail)
        self.status = classify(exc, detail, request, code=code, reason=reason)


def classify(
    exc: Exception,
    detail: str,
    request: str = "idle",
    code: int = 400,
    reason: str = "",
) -> dict:
    """把领域失败翻译成状态。

    调用方已经知道失败原因时直接给 ``reason``；给不出才退回按文案判断。

    「原文件丢了」和「原文件变了」不是失败，是不可用——前者缺数据，
    后者数据过期；这两者都给出「重新导入」的下一步，而不是「重试」。
    """
    if reason:
        if reason == panel_state.REASON_NOT_FOUND:
            return panel_state.failed(reason=reason, request=request, detail=detail)
        if reason == panel_state.REASON_CONFLICT:
            return panel_state.failed(reason=reason, request=request, detail=detail)
        if reason == panel_state.REASON_PREREQUISITE:
            return panel_state.unavailable(
                reason=reason, request=request, detail=detail
            )
        return panel_state.failed(reason=reason, request=request, detail=detail)

    if "原文件已丢失" in detail:
        return panel_state.unavailable(
            reason=panel_state.REASON_SOURCE_MISSING, request=request, detail=detail
        )
    if "原文件大小已变" in detail or "大小与登记的不一致" in detail:
        return panel_state.unavailable(
            reason=panel_state.REASON_SOURCE_CHANGED, request=request, detail=detail
        )
    if (
        "没有这个数据集" in detail
        or "论文库中没有" in detail
        or "没有这一版" in detail
        or "超出范围" in detail
    ):
        return panel_state.failed(
            reason=panel_state.REASON_NOT_FOUND, request=request, detail=detail
        )
    if code == 409:
        return panel_state.failed(
            reason=panel_state.REASON_CONFLICT, request=request, detail=detail
        )
    if code == 403:
        return panel_state.unavailable(
            reason=panel_state.REASON_PERMISSION, request=request, detail=detail
        )
    kind = getattr(exc, "status", "")
    if kind == "unsupported":
        return panel_state.unavailable(
            reason=panel_state.REASON_PREREQUISITE, request=request, detail=detail
        )
    if kind == "invalid":
        return panel_state.failed(
            reason=panel_state.REASON_PARSE, request=request, detail=detail
        )
    # 检查失败时带着原文件的可用性：原件没了是「不可用」，不是「解析失败」。
    if kind == "missing":
        return panel_state.unavailable(
            reason=panel_state.REASON_SOURCE_MISSING, request=request, detail=detail
        )
    if kind == "changed":
        return panel_state.unavailable(
            reason=panel_state.REASON_SOURCE_CHANGED, request=request, detail=detail
        )
    return panel_state.failed(
        reason=panel_state.REASON_SERVER, request=request, detail=detail
    )


def fail(
    exc: Exception,
    code: int = 400,
    request: str = "idle",
    reason: str = "",
) -> ResearchError:
    """构造带状态的错误；调用方照常 ``raise``。"""
    return ResearchError(exc, code=code, request=request, reason=reason)
