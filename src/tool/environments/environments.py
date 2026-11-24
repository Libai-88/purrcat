"""Environments 工具：只读看环境里有什么、能做什么。

**观察 ≠ 授权 ≠ 验证。** 工具只说「观察到这个软件在这个版本」，
不说「它能跑这个实验」，更不说「用它算出来的结果是对的」。

需要装什么、要跑哪条命令——用户自己决定，工具不代劳。
"""

from __future__ import annotations

from src.environments import catalog, observer
from src.tool.utils.format import error_response, text_response


def _render_observation(record: dict) -> str:
    readiness = {
        "ready": "就绪",
        "missing": "缺失",
        "unknown": "未知（拿不到可靠信息）",
    }.get(record.get("readiness"), record.get("readiness", ""))
    lines = [
        f"## {record.get('name', record.get('tool_id', ''))} — {readiness}",
        f"- 可执行文件：{record.get('executable') or '未找到'}",
        f"- 版本：{record.get('version') or '未取得'}",
        f"- 观察时刻：{record.get('observed_at', '')}（{record.get('observed_by', '')}）",
    ]
    if record.get("note"):
        lines.append(f"- 说明：{record['note']}")
    return "\n".join(lines)


def Environments(
    action: str, tool_id: str = None, capability_id: str = None, **kwargs
) -> str:
    """只读环境探测。

    Args:
        action: list / observe / capabilities
        tool_id: action=observe 时指定工具 id；不填则观察全部
        capability_id: 查某一项能力（list 输出里会列出）

    Returns:
        格式化后的 JSON 字符串，包含 timestamp, type, content, snip
    """
    try:
        if not action:
            return error_response(
                "缺少必需参数 'action'。可选：list / observe / capabilities。",
                "缺少 action",
            )
        action = str(action).strip().lower()

        if action == "list":
            items = catalog.list_tools()
            body = "# 环境工具目录\n\n" + "\n".join(
                f"- `{item['id']}` {item['name']}（{item['kind']}）：{item['note']}"
                for item in items
            )
            body += "\n\n这是目录，不是观察结果。用 action=observe 才真的去看。"
            return text_response(body, f"🖥 {len(items)} 项工具")

        if action == "capabilities":
            if capability_id:
                try:
                    item = catalog.get_capability(capability_id)
                except catalog.EnvironmentError as exc:
                    return error_response(str(exc), "❌ 没有这种能力")
                body = (
                    f"# {item['name']}（`{item['id']}`）\n\n"
                    f"能做什么：{item['can']}\n\n"
                    f"**不能推出什么：{item['cannot']}**"
                )
                return text_response(body, f"🔧 {item['name']}")
            items = catalog.list_capabilities()
            body = "# 能力声明\n\n"
            for item in items:
                body += f"## {item['name']}（`{item['id']}`）\n"
                body += f"- 能：{item['can']}\n"
                body += f"- 不能推出：{item['cannot']}\n\n"
            body += "能力声明只说能做什么，不说明用它算出来的结果可不可信。"
            return text_response(body, f"🔧 {len(items)} 种能力")

        if action == "observe":
            if tool_id:
                try:
                    record = observer.observe_tool(tool_id)
                except catalog.EnvironmentError as exc:
                    return error_response(str(exc), "❌ 没有这个工具")
                return text_response(
                    _render_observation(record), f"🖥 {record.get('readiness')}"
                )
            report = observer.observe_all()
            parts = [
                f"# 环境观察（{report['observed_at']}）",
                "",
                f"执行后端：{report.get('exec_backend', '')}",
                "",
            ]
            for record in report["observations"].values():
                parts.append(_render_observation(record))
                parts.append("")
            parts.append(report["note"])
            return text_response("\n".join(parts), "🖥 环境观察")

        return error_response(
            f"无效的 action '{action}'。可选：list / observe / capabilities。",
            "参数错误",
        )

    except Exception as exc:
        return error_response(f"环境工具异常：{exc}", "❌ 执行失败")


__all__ = ["Environments"]
