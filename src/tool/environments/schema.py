"""Environments 工具的 schema：只读环境探测。"""

from __future__ import annotations

ENVIRONMENTS_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "Environments",
        "description": (
            "只读环境探测工具：看本机有哪些科研工具（Python、Git、uv、Node、Docker）、"
            "版本与就绪度，以及有哪些执行能力。"
            "观察不等于授权，更不等于验证：观察到软件在，不代表它能跑某个实验，"
            "也不代表用它算出来的结果是对的。工具不装东西、不改系统。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "observe", "capabilities"],
                    "description": (
                        "list=看工具目录（不探测）；observe=只读探测（不填 tool_id 则探测全部）；"
                        "capabilities=看能力声明及其边界"
                    ),
                },
                "tool_id": {
                    "type": "string",
                    "description": "action=observe 时指定工具 id；不填则观察全部。",
                },
                "capability_id": {
                    "type": "string",
                    "description": "action=capabilities 时查某一项能力；不填则列全部。",
                },
            },
            "required": ["action"],
        },
    },
}

__all__ = ["ENVIRONMENTS_TOOL_SCHEMA"]
