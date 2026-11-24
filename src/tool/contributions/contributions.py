"""Contributions 工具：本地工作区 → diff → 审阅 → 草稿 PR。

**Agent 不许自己发布。** ``start`` 返回的提示词里明确写着
不要 commit / push / fork / 开 PR——发布权留给用户。
"""

from __future__ import annotations

from src.contributions import domain, store
from src.contributions.domain import ContributionError, ReviewChanged
from src.tool.utils.format import error_response, text_response


def _render(record: dict) -> str:
    lines = [
        f"## {record.get('title', record.get('task_id', ''))}",
        f"- 任务：`{record.get('task_id', '')}`　状态：{record.get('status', '')}",
        f"- 仓库：{record.get('repository', '')}　分支：{record.get('branch', '')}",
        f"- 工作区：{record.get('workspace', '')}",
        f"- 基准提交：{record.get('base_head', '') or '—'}",
    ]
    if record.get("pr_url"):
        lines.append(f"- 草稿 PR：{record['pr_url']}")
    if record.get("publish_command"):
        lines.append(f"- 待执行的发布命令：\n  {record['publish_command']}")
    return "\n".join(lines)


def Contributions(
    action: str,
    task_id: str = None,
    repository: str = None,
    workspace: str = None,
    title: str = None,
    source_url: str = None,
    source_revision: str = None,
    review_token: str = None,
    ops=None,
    **kwargs,
) -> str:
    """贡献工作区工具：准备、启动、审阅、标记就绪、发布草稿 PR、释放。

    Agent 侧只能走到 ``review``——它看 diff、交回审阅凭据，
    但不能发 PR。``ready`` 与 ``publish`` 是用户的显式动作。

    Args:
        action: list / prepare / start / review / ready / publish / release
        task_id: 任务 id
        repository: owner/repo；action=prepare 时必填
        workspace: 本机目录；action=prepare 时必填
        title: 贡献标题；action=prepare 时必填
        source_url / source_revision: 来源凭据
        review_token: action=ready/publish 时必填，审阅的乐观锁

    Returns:
        格式化后的 JSON 字符串，包含 timestamp, type, content, snip
    """
    try:
        if not action:
            return error_response(
                "缺少必需参数 'action'。"
                "可选：list / prepare / start / review / ready / publish / release。",
                "缺少 action",
            )
        action = str(action).strip().lower()

        if action == "list":
            items = store.list_all()
            if not items:
                return text_response("还没有贡献工作区。", "🔀 0 个")
            body = "# 贡献工作区\n\n" + "\n".join(_render(item) for item in items)
            return text_response(body, f"🔀 {len(items)} 个")

        if action == "prepare":
            missing = [
                name
                for name, value in (
                    ("task_id", task_id),
                    ("repository", repository),
                    ("workspace", workspace),
                    ("title", title),
                )
                if not value
            ]
            if missing:
                return error_response(
                    f"action=prepare 缺少：{', '.join(missing)}", "参数缺失"
                )
            record = store.prepare(
                task_id=task_id,
                repository=repository,
                workspace=workspace,
                title=title,
                source_url=source_url or "",
                source_revision=source_revision or "",
                ops=ops,
            )
            return text_response(
                _render(record) + "\n\n工作区已就绪，下一步用 action=start 开始。",
                "✅ 工作区已建立",
            )

        if not task_id:
            return error_response(f"action={action} 需要 task_id。", "参数缺失")

        if action == "start":
            record = store.start(task_id)
            return text_response(
                _render(record) + "\n\n" + domain.AGENT_INSTRUCTION,
                "🔀 开始工作",
            )

        if action == "review":
            record = store.review(task_id, ops=ops)
            changed = len(record.get("changed_files") or [])
            return text_response(
                _render(record)
                + f"\n\n审阅凭据（review token）：`{record['review_token']}`\n"
                + f"改动文件 {changed} 个。请人审阅这份 diff；\n"
                + "审阅之后文件若再变，token 就对不上，必须先刷新 diff 重新审阅。",
                f"🔍 {changed} 个文件",
            )

        if action in ("ready", "publish"):
            if not review_token:
                return error_response(
                    f"action={action} 需要 review_token（审阅凭据）。", "参数缺失"
                )
            if action == "ready":
                record = store.mark_ready(task_id, review_token)
                return text_response(
                    _render(record) + "\n\n已标记就绪。发布要由用户显式触发。",
                    "✅ 已就绪",
                )
            record = store.publish(task_id, review_token, ops=ops)
            return text_response(
                _render(record) + "\n\n草稿 PR 已准备好（或已存在）。",
                "🔀 草稿 PR",
            )

        if action == "release":
            record = store.release(task_id)
            return text_response(
                _render(record) + "\n\n工作区已释放；本地改动没动。",
                "✅ 已释放",
            )

        return error_response(
            f"无效的 action '{action}'。"
            "可选：list / prepare / start / review / ready / publish / release。",
            "参数错误",
        )

    except ReviewChanged as exc:
        return error_response(str(exc), "❌ 审阅已过期")
    except ContributionError as exc:
        return error_response(str(exc), "❌ 操作失败")
    except Exception as exc:
        return error_response(f"贡献工具异常：{exc}", "❌ 执行失败")


__all__ = ["Contributions"]
