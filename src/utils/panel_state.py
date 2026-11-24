"""把领域事实翻译成面板状态。

面板要分清的是三件事：**有哪些数据**、**请求正在做什么**、**业务结果是什么**。
服务端负责前两件里自己知道的那部分（data 与 result），客户端负责 request。

这里只做翻译：把「原文件丢了」「查询没命中」「页码越界」这类领域事实，
映射到封闭词表里的取值。映射不到就退到 ``server``，不自己造词。
"""

from __future__ import annotations

from src.utils.async_state import status

# —— data 轴 ——

DATA_NONE = "none"
DATA_PARTIAL = "partial"
DATA_STALE = "stale"
DATA_COMPLETE = "complete"

# —— result 轴 ——

RESULT_PENDING = "pending"
RESULT_OK = "ok"
RESULT_EMPTY = "empty"
RESULT_FAILED = "failed"
RESULT_UNAVAILABLE = "unavailable"

# —— reason 轴 ——

REASON_NO_DATA = "no_data"
REASON_FILTER_NO_MATCH = "filter_no_match"
REASON_TASK_PENDING = "task_pending"
REASON_SOURCE_MISSING = "source_missing"
REASON_SOURCE_CHANGED = "source_changed"
REASON_PERMISSION = "permission"
REASON_PREREQUISITE = "prerequisite"
REASON_NOT_FOUND = "not_found"
REASON_CONFLICT = "conflict"
REASON_PARSE = "parse"
REASON_IO = "io"
REASON_SERVER = "server"

# —— action 轴 ——

ACTION_NONE = "none"
ACTION_RETRY = "retry"
ACTION_IMPORT = "import"
ACTION_ADJUST_FILTER = "adjust_filter"
ACTION_START_TASK = "start_task"
ACTION_GRANT_PERMISSION = "grant_permission"
ACTION_OPEN_SETTINGS = "open_settings"


def ready(request: str = "idle", detail: str = "") -> dict:
    """内容都在。"""
    return status(data=DATA_COMPLETE, request=request, result=RESULT_OK, detail=detail)


def empty(
    reason: str = REASON_NO_DATA, request: str = "idle", detail: str = ""
) -> dict:
    """成功但没有内容——要分清是「从没有过」还是「筛掉了」还是「还没跑完」。"""
    action = {
        REASON_NO_DATA: ACTION_IMPORT,
        REASON_FILTER_NO_MATCH: ACTION_ADJUST_FILTER,
        REASON_TASK_PENDING: ACTION_START_TASK,
    }.get(reason, ACTION_NONE)
    return status(
        data=DATA_NONE,
        request=request,
        result=RESULT_EMPTY,
        reason=reason,
        detail=detail,
        action=action,
    )


def stale(
    reason: str = REASON_SOURCE_CHANGED, request: str = "idle", detail: str = ""
) -> dict:
    """内容还在，但已经不是最新的了。"""
    return status(
        data=DATA_STALE,
        request=request,
        result=RESULT_OK,
        reason=reason,
        detail=detail,
        action=ACTION_IMPORT,
    )


def partial(detail: str = "", request: str = "idle") -> dict:
    """只有一部分可用。"""
    return status(
        data=DATA_PARTIAL,
        request=request,
        result=RESULT_OK,
        reason=REASON_IO,
        detail=detail,
        action=ACTION_RETRY,
    )


def failed(
    reason: str = REASON_SERVER, request: str = "idle", detail: str = ""
) -> dict:
    """请求本身失败了。"""
    action = ACTION_RETRY if reason != REASON_NOT_FOUND else ACTION_NONE
    return status(
        data=DATA_NONE,
        request=request,
        result=RESULT_FAILED,
        reason=reason,
        detail=detail,
        action=action,
    )


def unavailable(
    reason: str = REASON_PREREQUISITE,
    request: str = "idle",
    detail: str = "",
) -> dict:
    """不是失败，是条件没满足：缺权限、缺环境、原件不在了。"""
    action = {
        REASON_PERMISSION: ACTION_GRANT_PERMISSION,
        REASON_PREREQUISITE: ACTION_OPEN_SETTINGS,
        REASON_SOURCE_MISSING: ACTION_IMPORT,
        REASON_SOURCE_CHANGED: ACTION_IMPORT,
    }.get(reason, ACTION_NONE)
    return status(
        data=DATA_NONE,
        request=request,
        result=RESULT_UNAVAILABLE,
        reason=reason,
        detail=detail,
        action=action,
    )


def from_http(code: int, detail: str = "", request: str = "idle") -> dict:
    """按 HTTP 状态码翻译一次失败。

    404 是「对象不存在」，403 是「没权限」，409 是「和当前内容对不上」，
    422/400 是请求本身有问题，其余归到服务端出错。
    """
    if code == 404:
        return failed(reason=REASON_NOT_FOUND, request=request, detail=detail)
    if code == 403:
        return unavailable(reason=REASON_PERMISSION, request=request, detail=detail)
    if code == 409:
        return failed(reason=REASON_CONFLICT, request=request, detail=detail)
    if code in (400, 422):
        return failed(reason=REASON_PARSE, request=request, detail=detail)
    return failed(reason=REASON_SERVER, request=request, detail=detail)
