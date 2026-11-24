"""面板异步状态：一份词表，后端与前端读同一份。

Pero 的设计契约说：分别表达**有哪些数据、请求正在做什么、业务结果是什么**。
这里照这个思路落成三个正交的轴：

- ``data``    —— 有哪些数据：none / partial / stale / complete
- ``request`` —— 请求正在做什么：idle / first_load / refresh / submitting / …
- ``result``  —— 业务结果是什么：ok / empty / failed / unavailable

三轴组合出最终状态。词表与规则表只写在
``ui/web-minimal/assets/async-state.js`` 里（那段 JSON 被前后端同时读），
所以不会出现「后端说 failed、前端只认识 error」这种漂移。

**这套状态只说界面现在处于什么状态，从不说结论是否成立。**
科学验证由 acceptance / verification 那套封闭词表负责（见
``src/papers/records.py``），两层互不冒充。
"""

from __future__ import annotations

import json
import os
import re

from src.utils.config import BASE_DIR

# 词表与规则表所在的文件；前端也加载同一个文件。
SPEC_PATH = os.path.join(BASE_DIR, "ui", "web-minimal", "assets", "async-state.js")

_SPEC_BLOCK = re.compile(
    r"/\*\s*purrcat:async-state:spec\s*\*/(.*?)/\*\s*purrcat:async-state:spec:end\s*\*/",
    re.DOTALL,
)

_SPEC_CACHE: dict | None = None


class AsyncStateError(Exception):
    """状态词表读不出来，或用到了词表之外的值。"""


def load_spec() -> dict:
    """读出词表与规则表；文件缺失或损坏时抛 AsyncStateError。"""
    global _SPEC_CACHE
    if _SPEC_CACHE is not None:
        return _SPEC_CACHE
    try:
        with open(SPEC_PATH, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise AsyncStateError(f"读不到异步状态词表：{SPEC_PATH}") from exc
    match = _SPEC_BLOCK.search(text)
    if not match:
        raise AsyncStateError(f"异步状态词表格式不对：{SPEC_PATH}")
    body = match.group(1)
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end < start:
        raise AsyncStateError(f"异步状态词表里没有 JSON：{SPEC_PATH}")
    try:
        spec = json.loads(body[start : end + 1])
    except ValueError as exc:
        raise AsyncStateError(f"异步状态词表不是合法 JSON：{SPEC_PATH}") from exc
    _SPEC_CACHE = spec
    return spec


def _values(name: str) -> tuple[str, ...]:
    spec = load_spec()
    values = spec.get(name)
    if not isinstance(values, list) or not values:
        raise AsyncStateError(f"异步状态词表缺少 {name}")
    return tuple(str(item) for item in values)


def data_values() -> tuple[str, ...]:
    """有哪些数据。"""
    return _values("data")


def request_values() -> tuple[str, ...]:
    """请求正在做什么。"""
    return _values("request")


def result_values() -> tuple[str, ...]:
    """业务结果是什么。"""
    return _values("result")


def state_values() -> tuple[str, ...]:
    """最终状态的全集。"""
    return _values("state")


def reason_values() -> tuple[str, ...]:
    """状态原因（为什么空 / 为什么失败 / 为什么不可用）。"""
    return _values("reason")


def action_values() -> tuple[str, ...]:
    """用户可以采取的下一步。"""
    return _values("action")


def _check(value: str, allowed: tuple[str, ...], axis: str) -> str:
    if value not in allowed:
        raise AsyncStateError(f"{axis} 取值非法：{value!r}，可用：{', '.join(allowed)}")
    return value


def derive(
    data: str = "complete",
    request: str = "idle",
    result: str = "ok",
) -> str:
    """三轴组合出最终状态。

    规则表按顺序命中第一条；``data``/``request``/``result`` 之外的取值直接拒收，
    不做静默兜底——拼错的状态名比报错更难查。
    """
    spec = load_spec()
    d = _check(data, data_values(), "data")
    q = _check(request, request_values(), "request")
    r = _check(result, result_values(), "result")
    for rule in spec.get("rules") or []:
        if "data" in rule and rule["data"] != d:
            continue
        if "request" in rule and rule["request"] != q:
            continue
        if "result" in rule and rule["result"] != r:
            continue
        return str(rule["state"])
    raise AsyncStateError(f"规则表没有覆盖 {d}/{q}/{r}")


def status(
    data: str = "complete",
    request: str = "idle",
    result: str = "ok",
    reason: str = "",
    detail: str = "",
    action: str = "",
) -> dict:
    """构造一份状态描述，供接口与工具共用。

    ``reason`` 与 ``action`` 留空表示「没有更具体的说法」，
    不写「未知」之类的占位词——空就是空。
    """
    state = derive(data=data, request=request, result=result)
    payload = {
        "state": state,
        "data": data,
        "request": request,
        "result": result,
    }
    if reason:
        payload["reason"] = _check(reason, reason_values(), "reason")
    if detail:
        payload["detail"] = str(detail)
    if action:
        payload["action"] = _check(action, action_values(), "action")
    return payload
