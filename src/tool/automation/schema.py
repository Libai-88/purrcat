"""Automation 工具的 schema：定时让 Agent 跑一段指示。"""

from __future__ import annotations

AUTOMATION_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "Automation",
        "description": (
            "自动化工具：安排「到点让 Agent 跑一段指示」的定时任务。"
            "与闹钟不同，自动化到点会真的执行，并留下一条运行回执。"
            "回执只说这次运行怎么样（排上了 / 跑完了 / 挂了），"
            "不说明它核对出来的结论可不可信——那是另一套词表的事。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "create",
                        "read",
                        "update",
                        "delete",
                        "run",
                        "runs",
                    ],
                    "description": (
                        "list=列出自动化；create=新建；read=读一条；update=改；"
                        "delete=删；run=手动跑一次；runs=看运行回执"
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "action=create 时必填，自动化名字。",
                },
                "instruction": {
                    "type": "string",
                    "description": (
                        "action=create 时必填：到点推给 Agent 的那段指示。"
                        "写清楚要它做什么，别写「检查一下」这种没法执行的。"
                    ),
                },
                "trigger_time": {
                    "type": "string",
                    "description": (
                        "action=create 时必填：触发时刻，24 小时制 HH:MM（如 08:30）。"
                    ),
                },
                "repeat_rule": {
                    "type": "string",
                    "enum": [
                        "none",
                        "everyday",
                        "weekly_1",
                        "weekly_2",
                        "weekly_3",
                        "weekly_4",
                        "weekly_5",
                        "weekly_6",
                        "weekly_7",
                    ],
                    "description": (
                        "重复规则：none=只跑一次；everyday=每天；weekly_1..weekly_7=周一到周日。"
                        "默认 none。"
                    ),
                },
                "enabled": {
                    "type": "boolean",
                    "description": "是否启用；action=update 时用来停用或重新启用。",
                },
                "automation_id": {
                    "type": "string",
                    "description": "自动化 id；action=read/update/delete/run/runs 时指定。",
                },
            },
            "required": ["action"],
        },
    },
}

__all__ = ["AUTOMATION_TOOL_SCHEMA"]
