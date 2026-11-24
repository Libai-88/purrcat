"""Automation 工具：让 Agent 自己安排定时任务。

与 `Cron` 闹钟的区别：闹钟只提醒，自动化到点**真的会让 Agent 跑一段指示**，
并留下一条回执说明这次实际发生了什么。

提醒 Agent 一条：排上了不等于跑完了，跑完了也不等于结论对。
"""

from __future__ import annotations

from src.automation import (
    RUN_VALUES,
    AutomationError,
    counts,
    create,
    delete,
    get_automation,
    list_automations,
    list_runs,
    update,
)
from src.tool.utils.format import error_response, text_response

# 运行状态的解释，让 Agent 知道回执说的是什么。
_STATE_TEXT = {
    "queued": "已排上，但还没跑",
    "running": "正在跑",
    "succeeded": "跑完了，中途没出错",
    "failed": "跑完了，但中途出错",
    "cancelled": "被取消了，没跑完",
}


def _render(item: dict) -> str:
    lines = [
        f"- `{item['id']}` {item.get('title', '')}",
        f"  时间: {item.get('trigger_time', '?')} · 重复: {item.get('repeat_rule', 'none')}"
        f" · {'启用' if item.get('enabled') else '停用'}",
        f"  下次: {item.get('next_run_at') or '—'} · 上次: {item.get('last_run_at') or '—'}",
        f"  指示: {item.get('instruction', '')}",
    ]
    return "\n".join(lines)


def _render_runs(runs: list[dict]) -> str:
    if not runs:
        return "还没有运行记录。"
    lines = ["# 运行回执", ""]
    for run in runs:
        state = run.get("state", "queued")
        lines.append(
            f"- `{run.get('id', '')}` {run.get('title', '')} — "
            f"{_STATE_TEXT.get(state, state)}"
        )
        lines.append(
            f"  排队: {run.get('queued_at', '')} · 结束: {run.get('finished_at') or '—'}"
        )
        if run.get("detail"):
            lines.append(f"  说明: {run['detail']}")
    lines.append("")
    lines.append("回执只说这次运行怎么样，不说它核对出来的结论可不可信。")
    return "\n".join(lines)


def Automation(
    action: str,
    title: str = None,
    instruction: str = None,
    trigger_time: str = None,
    repeat_rule: str = None,
    enabled: bool = None,
    automation_id: str = None,
    **kwargs,
) -> str:
    """自动化工具：管理「到点让 Agent 跑一段指示」的定时任务。

    Args:
        action: 操作类型，list / create / read / update / delete / run / runs
        title: 自动化名字；action=create 时必填
        instruction: 到点推给 Agent 的那段指示；action=create 时必填
        trigger_time: 触发时刻，HH:MM（如 08:30）；action=create 时必填
        repeat_rule: 重复规则，none / everyday / weekly_1..weekly_7
        enabled: 是否启用
        automation_id: 自动化 id；read/update/delete/run/runs 时指定

    Returns:
        格式化后的 JSON 字符串，包含 timestamp, type, content, snip
    """
    try:
        if not action:
            return error_response(
                "缺少必需参数 'action'。可选值：list / create / read / update / delete / run / runs。",
                "缺少 action",
            )
        action = str(action).strip().lower()

        if action == "list":
            items = list_automations()
            if not items:
                return text_response("还没有自动化。", "⏰ 0 条")
            body = "# 自动化\n\n" + "\n".join(_render(item) for item in items)
            return text_response(body, f"⏰ {len(items)} 条")

        if action == "create":
            if not title or not str(title).strip():
                return error_response("create 需要 title（自动化名字）。", "参数缺失")
            if not instruction or not str(instruction).strip():
                return error_response(
                    "create 需要 instruction：到点让 Agent 做什么，写清楚些。",
                    "参数缺失",
                )
            if not trigger_time:
                return error_response(
                    "create 需要 trigger_time（HH:MM，如 08:30）。", "参数缺失"
                )
            item = create(
                title=title,
                instruction=instruction,
                trigger_time=trigger_time,
                repeat_rule=repeat_rule or "none",
                enabled=True if enabled is None else bool(enabled),
            )
            return text_response(
                f"已创建自动化 `{item['id']}`：{item['title']}\n"
                f"下次触发：{item.get('next_run_at') or '—'}",
                f"⏰ 已创建 | {item.get('trigger_time')}",
            )

        if action in ("read", "update", "delete", "run", "runs"):
            if not automation_id:
                return error_response(
                    f"action={action} 需要 automation_id。", "参数缺失"
                )
            if action == "read":
                item = get_automation(automation_id)
                if item is None:
                    return error_response(
                        f"没有这条自动化：{automation_id}", "❌ 未找到"
                    )
                return text_response(
                    _render(item), f"⏰ {item.get('title', automation_id)}"
                )
            if action == "runs":
                runs = list_runs(automation_id=automation_id, limit=50)
                return text_response(_render_runs(runs), f"⏰ {len(runs)} 条回执")
            if action == "update":
                item = update(
                    automation_id,
                    title=title,
                    instruction=instruction,
                    trigger_time=trigger_time,
                    repeat_rule=repeat_rule,
                    enabled=enabled,
                )
                return text_response(
                    f"已更新 `{item['id']}`。\n{_render(item)}",
                    f"⏰ 已更新 | {item.get('title', '')}",
                )
            if action == "delete":
                result = delete(automation_id)
                return text_response(
                    f"已删除自动化 `{result['id']}`（{result.get('title', '')}）。"
                    "已经跑完的回执留着没动。",
                    "✅ 已删除",
                )
            # action == "run"
            from src.automation import runner as automation_runner

            run = automation_runner.run_now(automation_id)
            state = run.get("state", "queued")
            return text_response(
                f"手动跑了一次 `{run.get('id', '')}`："
                f"{_STATE_TEXT.get(state, state)}"
                + (f"\n{run['detail']}" if run.get("detail") else ""),
                f"⏰ {_STATE_TEXT.get(state, state)}",
            )

        return error_response(
            f"无效的 action '{action}'。可选值：list / create / read / update / delete / run / runs。",
            "参数错误",
        )

    except AutomationError as exc:
        return error_response(str(exc), "❌ 操作失败")
    except Exception as exc:
        return error_response(f"自动化工具异常：{exc}", "❌ 执行失败")


__all__ = ["Automation", "RUN_VALUES", "counts"]
