"""贡献工作区的领域核心：值、状态机、diff 指纹。

两条硬规则：

1. **Agent 不发布。** 提示词里明确禁止它 commit / push / fork / 开 PR。
2. **review token 是 diff 的乐观锁。** 审阅后文件又变了，就不能拿旧审阅发 PR。

贡献状态只说流程走到哪一步，**不带 acceptance / verification**——
「草稿 PR 建好了」不等于「贡献会被接受」。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

# —— 状态（封闭词表）——

STATUS_PREPARED = "prepared"  # 工作区已建立，还没开始改
STATUS_WORKING = "working"  # Agent 正在里面改
STATUS_REVIEW = "review"  # 有 diff，等用户审阅
STATUS_READY = "ready"  # 已审阅，可以发 PR
STATUS_PUBLISHED = "published"  # 草稿 PR 已建
STATUS_RELEASED = "released"  # 用户放弃了这个工作区

STATUS_VALUES = (
    STATUS_PREPARED,
    STATUS_WORKING,
    STATUS_REVIEW,
    STATUS_READY,
    STATUS_PUBLISHED,
    STATUS_RELEASED,
)

# —— 错误 ——


class ContributionError(Exception):
    """贡献工作区的用法不对。"""


class ReviewChanged(ContributionError):
    """审阅之后文件又变了——必须刷新 diff 重新审阅。"""


# —— 值约束 ——

_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_TASK_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# Agent 提示词：发布权留给用户，Agent 不许自己动手。
AGENT_INSTRUCTION = (
    "在这个工作区里实现改动，并运行相应的检查。"
    "不要 commit、不要 push、不要 fork、不要开 pull request；"
    "贡献者会审阅改动，并由 PurrCat 发布。"
)


def normalize_repository(value: str) -> str:
    """仓库必须是 owner/repo；不合法就拒收。"""
    repo = str(value or "").strip()
    if not _REPO_RE.match(repo) or len(repo) > 201:
        raise ContributionError("GitHub 仓库要写成 owner/repository 的形式")
    return repo


def normalize_task_id(value: str) -> str:
    task = str(value or "").strip()
    if not _TASK_RE.match(task):
        raise ContributionError("任务 id 只允许字母、数字、- 和 _，最多 128 字符")
    return task


def branch_for(task_id: str) -> str:
    """分支名固定从任务 id 派生，不让人随便改。"""
    return f"purrcat/{normalize_task_id(task_id)}"


def review_token(head: str, diff: str, changed_files: list[str]) -> str:
    """diff 的指纹：作为「你审的就是这份」的乐观锁。

    内容包含 head、diff 与文件名列表——任何一个变了，token 都变。
    """
    payload = {
        "head": head,
        "diff": diff,
        "files": sorted(changed_files or []),
    }
    raw = "\n".join(
        [payload["head"], "|".join(payload["files"]), payload["diff"]]
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def check_review(expected: str, current: str) -> None:
    """审阅后文件被改过 → 拒收，要求刷新 diff 重新审。"""
    if not expected or expected != current:
        raise ReviewChanged("审阅之后文件变了。先刷新 diff 重新审阅，再发 PR。")


def build(
    task_id: str,
    repository: str,
    workspace: str,
    base: str,
    base_head: str,
    title: str,
    source_url: str,
    source_revision: str,
) -> dict:
    """组装一份贡献工作区记录。

    ``source_url`` / ``source_revision`` 是本次贡献的来源凭据——
    说明它从哪份研究工件来，但**不说明这个贡献好不好**。
    """
    task = normalize_task_id(task_id)
    repo = normalize_repository(repository)
    title = str(title or "").strip()
    if not title or "\n" in title or len(title) > 1000:
        raise ContributionError("标题要有内容、单行、不超过 1000 字")
    source = str(source_url or "").strip()
    if source and not source.startswith(f"https://github.com/{repo}/"):
        raise ContributionError(f"来源链接必须指向 {repo}")
    return {
        "task_id": task,
        "repository": repo,
        "workspace": workspace,
        "branch": branch_for(task),
        "base": base,
        "base_head": base_head,
        "title": title,
        "source_url": source,
        "source_revision": str(source_revision or "").strip()[:256],
        "status": STATUS_PREPARED,
        "pr_url": "",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def transition(contribution: dict, status: str, **updates) -> dict:
    """推进贡献状态。状态是封闭词表，不认识的值一律拒收。"""
    if status not in STATUS_VALUES:
        raise ContributionError(f"贡献状态非法：{status!r}")
    result = {**contribution, **updates, "status": status}
    return result


def public_view(contribution: dict) -> dict:
    """面板可见的投影。

    这里**不放** credential、token 之类——跟连接器的凭据边界一样，
    对外只说状态与产物，不泄露授权信息。
    """
    keys = (
        "task_id",
        "repository",
        "workspace",
        "branch",
        "base",
        "base_head",
        "title",
        "source_url",
        "source_revision",
        "status",
        "pr_url",
        "created_at",
    )
    return {key: contribution.get(key, "") for key in keys}
