"""Paper 工具的注册红线（SPEC-026 AC-8）。"""

from __future__ import annotations

import inspect

from src.tool import AGENT_TOOL_SCHEMA
from src.tool.utils.route import (
    PROCESS_ISOLATED_TOOLS,
    SYSTEM_INJECTED_ARGUMENTS,
    TOOL_FUNC_MAP,
    resolve_tool,
)

SCHEMAS = [entry.get("function", entry) for entry in AGENT_TOOL_SCHEMA]
VARIADIC_KINDS = (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)


def _paper_schema() -> dict:
    return next(item for item in SCHEMAS if item["name"] == "Paper")


def test_paper_tool_is_exposed_and_registered():
    """AC-8：Paper 既暴露给模型，也在路由表里。"""
    names = {schema["name"] for schema in SCHEMAS}
    assert "Paper" in names
    assert TOOL_FUNC_MAP.get("paper") == "Paper"


def test_paper_schema_properties_are_accepted():
    """AC-8：schema 里声明的参数都能被函数接受。"""
    schema = _paper_schema()
    properties = set(schema["parameters"]["properties"])
    params = inspect.signature(resolve_tool("Paper")).parameters
    accepts_extra = any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values()
    )
    unaccepted = properties - set(params)
    assert not unaccepted or accepts_extra, sorted(unaccepted)


def test_paper_required_function_params_are_reachable():
    """AC-8：函数的必填参数要么由模型提供，要么在系统注入白名单里。"""
    schema = _paper_schema()
    params = inspect.signature(resolve_tool("Paper")).parameters
    required = {
        name
        for name, param in params.items()
        if param.default is inspect.Parameter.empty and param.kind not in VARIADIC_KINDS
    }
    unreachable = (
        required - set(schema["parameters"]["properties"]) - SYSTEM_INJECTED_ARGUMENTS
    )
    assert not unreachable, sorted(unreachable)


def test_paper_tool_is_not_process_isolated():
    """进程隔离白名单不可扩大：Paper 在进程内执行。"""
    assert "paper" not in PROCESS_ISOLATED_TOOLS
