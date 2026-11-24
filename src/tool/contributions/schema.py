"""Contributions 工具的 schema：本地工作区 → diff → 审阅 → 草稿 PR。"""

from __future__ import annotations

CONTRIBUTIONS_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "Contributions",
        "description": (
            "贡献工作区工具：准备一个 GitHub 仓库的本地工作区，在里面改代码，"
            "产生 diff 与审阅凭据，最后发草稿 PR。"
            "重要：Agent 只能用这个工具准备、启动与审阅；"
            "不能自己 commit / push / fork / 开 PR——发布权留给用户，"
            "且只能发草稿 PR。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "prepare",
                        "start",
                        "review",
                        "ready",
                        "publish",
                        "release",
                    ],
                    "description": (
                        "list=列工作区；prepare=建立；start=开始（返回给 Agent 的指示）；"
                        "review=产生 diff 与审阅凭据；ready=用户标记审阅完成；"
                        "publish=用户发草稿 PR；release=释放工作区"
                    ),
                },
                "task_id": {"type": "string", "description": "任务 id。"},
                "repository": {
                    "type": "string",
                    "description": "owner/repo；action=prepare 时必填。",
                },
                "workspace": {
                    "type": "string",
                    "description": "本机工作区目录；action=prepare 时必填。",
                },
                "title": {"type": "string", "description": "贡献标题。"},
                "source_url": {
                    "type": "string",
                    "description": "来源链接（研究工件），作为来源凭据。",
                },
                "source_revision": {"type": "string", "description": "来源版本。"},
                "review_token": {
                    "type": "string",
                    "description": (
                        "审阅凭据（diff 指纹）；action=ready/publish 时必填。"
                        "审阅后文件若变了，必须重新 review 拿新 token。"
                    ),
                },
            },
            "required": ["action"],
        },
    },
}

__all__ = ["CONTRIBUTIONS_TOOL_SCHEMA"]
