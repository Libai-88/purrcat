"""工具注册表一致性：Schema、路由、隔离与能力域必须同源，不允许漂移。"""

from __future__ import annotations

from src.tool.registry import (
    AGENT_TOOL_SCHEMA,
    BASE_TASK_TOOL_NAMES,
    BASE_TASK_TOOL_SCHEMA,
    BY_NAME,
    PROCESS_ISOLATED_TOOLS,
    SPECS,
    TOOL_FUNC_MAP,
    schemas_for,
)


def _schema_name(spec) -> str:
    return spec.schema["function"]["name"]


def test_every_registered_tool_resolves_to_the_declared_function():
    from src.tool.utils.route import resolve_tool

    for spec in SPECS:
        resolved = resolve_tool(spec.name)
        assert resolved is not None, f"{spec.name} 注册了但解析不到"
        assert resolved.__name__ == spec.func, f"{spec.name} 解析到了错误的函数"


def test_schema_and_function_names_agree():
    for spec in SPECS:
        assert _schema_name(spec) == spec.func


def test_names_are_unique_and_lowercase():
    names = [spec.name for spec in SPECS]
    assert len(names) == len(set(names)) == 19
    assert all(name == name.lower() for name in names)


def test_schema_list_is_derived_from_specs():
    assert len(AGENT_TOOL_SCHEMA) == len(SPECS)
    assert AGENT_TOOL_SCHEMA == [spec.schema for spec in SPECS]


def test_route_map_is_derived_from_specs():
    assert TOOL_FUNC_MAP == {spec.name: spec.func for spec in SPECS}


def test_isolation_list_is_exactly_the_four_blocking_tools():
    # callmcp 曾因隔离导致 MCP 连接随子进程销毁，这条断言锁住历史教训。
    assert PROCESS_ISOLATED_TOOLS == {"bash", "fetch", "request", "search"}


def test_capability_split_is_stable():
    research = {spec.name for spec in SPECS if spec.capability == "research"}
    assert research == {
        "automation",
        "connectors",
        "contributions",
        "data",
        "environments",
        "notebook",
        "paper",
        "research",
    }
    core = {spec.name for spec in SPECS if spec.capability == "core"}
    assert core == set(BY_NAME) - research
    assert len(core) == 11


def test_core_capability_never_leaks_research_tools():
    core_specs = [spec for spec in SPECS if spec.capability == "core"]
    research_names = {spec.name for spec in SPECS if spec.capability == "research"}
    assert len(core_specs) == 11
    assert not ({spec.name for spec in core_specs} & research_names)
    assert schemas_for(["core"]) == [spec.schema for spec in core_specs]


def test_full_capability_matches_the_default_list():
    assert schemas_for(["core", "research"]) == AGENT_TOOL_SCHEMA


def test_unknown_capability_falls_back_to_full_set():
    # 老会话推断不出能力域时不能砍能力，宁可给全量。
    assert schemas_for(None) == AGENT_TOOL_SCHEMA
    assert schemas_for([]) == AGENT_TOOL_SCHEMA


def test_base_task_tools_keep_historical_order():
    assert BASE_TASK_TOOL_NAMES == ("bash", "filesystem", "search", "callmcp", "fetch")
    assert BASE_TASK_TOOL_SCHEMA == [
        BY_NAME[name].schema for name in BASE_TASK_TOOL_NAMES
    ]
