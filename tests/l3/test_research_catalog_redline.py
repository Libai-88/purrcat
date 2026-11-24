"""科研技能目录不得改变工具注册表（SPEC-025 AC-5）。

目录能力走 Search / Fetch 两个既有工具，不得新增 native tool。
"""

from __future__ import annotations

from src.tool import AGENT_TOOL_SCHEMA
from src.tool.utils.route import TOOL_FUNC_MAP

SCHEMAS = [entry.get("function", entry) for entry in AGENT_TOOL_SCHEMA]
TOOL_NAMES = {schema["name"] for schema in SCHEMAS}

# 只禁目录专属的工具名。Research（研究记录）与目录无关，不在此列。
_FORBIDDEN = {"catalog", "researchcatalog", "researchskill", "skillcatalog"}


def test_no_catalog_tool_was_added():
    """AC-5：目录能力没有引入新的 native tool。"""
    assert not (TOOL_NAMES & _FORBIDDEN)
    assert not (set(TOOL_FUNC_MAP) & _FORBIDDEN), (
        f"目录能力不应注册新工具，当前注册表: {sorted(TOOL_FUNC_MAP)}"
    )
