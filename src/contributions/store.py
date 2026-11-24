"""贡献工作区的落盘与流程。

工作区记录存在本机目录里；状态与审阅 token 都记着，便于回查。
发布是对外动作，只在 ``publish`` 里发生，且必须先过 review token 这关。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from src.contributions import domain, gitops
from src.contributions.domain import (
    STATUS_PUBLISHED,
    STATUS_READY,
    STATUS_RELEASED,
    STATUS_REVIEW,
    STATUS_WORKING,
    ContributionError,
)
from src.utils._fs import read_json, write_json_atomic
from src.utils.config import DATA_DIR

STORE_DIRNAME = "contributions"
_LOCK_FILENAME = ".lock"


def store_root() -> str:
    return os.path.join(DATA_DIR, STORE_DIRNAME)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path(task_id: str) -> str:
    return os.path.join(store_root(), f"{domain.normalize_task_id(task_id)}.json")


def save(record: dict) -> dict:
    root = store_root()
    os.makedirs(root, exist_ok=True)
    write_json_atomic(_path(record["task_id"]), record)
    return record


def get(task_id: str) -> dict | None:
    data = read_json(_path(task_id), default=None)
    return data if isinstance(data, dict) else None


def list_all() -> list[dict]:
    root = store_root()
    if not os.path.isdir(root):
        return []
    items = []
    for name in sorted(os.listdir(root)):
        if not name.endswith(".json"):
            continue
        data = read_json(os.path.join(root, name), default=None)
        if isinstance(data, dict) and data.get("task_id"):
            items.append(data)
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return items


def prepare(
    task_id: str,
    repository: str,
    workspace: str,
    title: str,
    source_url: str = "",
    source_revision: str = "",
    base: str = "main",
    base_head: str = "",
    ops: gitops.GitOps | None = None,
) -> dict:
    """建立贡献工作区。

    默认在本机已有目录上工作（``workspace`` 传进来即可）；
    只有给了 ``ops`` 才做 clone 与 checkout，测试里用假 ops。
    """
    if get(task_id):
        raise ContributionError(f"任务 {task_id} 已经有工作区了")
    record = domain.build(
        task_id=task_id,
        repository=repository,
        workspace=workspace,
        base=base,
        base_head=base_head,
        title=title,
        source_url=source_url,
        source_revision=source_revision,
    )
    if ops is not None:
        ops.clone(record["repository"], workspace)
        record["base"] = ops.default_branch(workspace)
        record["base_head"] = ops.head(workspace)
        ops.checkout(workspace, record["branch"], create=True)
    return save(record)


def review(
    task_id: str,
    ops: gitops.GitOps | None = None,
    head: str = "",
    diff: str = "",
    changed_files: list[str] | None = None,
) -> dict:
    """产生当前 diff 的审阅凭据。

    review token 是 diff 内容的指纹——审阅后文件再变，token 就对不上。
    """
    record = get(task_id)
    if record is None:
        raise ContributionError(f"没有这个任务的工作区：{task_id}")
    if ops is not None:
        head = ops.head(record["workspace"])
        diff = ops.diff(record["workspace"], record["base_head"])
        changed_files = ops.status(record["workspace"])
    token = domain.review_token(head, diff, changed_files or [])
    record["review_token"] = token
    record["head"] = head
    record["diff"] = diff
    record["changed_files"] = list(changed_files or [])
    return save(domain.transition(record, STATUS_REVIEW))


def mark_ready(task_id: str, review_token: str) -> dict:
    """用户确认审阅：把 review token 锁进记录，等发布。"""
    record = get(task_id)
    if record is None:
        raise ContributionError(f"没有这个任务的工作区：{task_id}")
    expected = str(record.get("review_token") or "")
    domain.check_review(review_token, expected)
    return save(domain.transition(record, STATUS_READY))


def publish(
    task_id: str,
    review_token: str,
    ops: gitops.GitOps | None = None,
) -> dict:
    """发草稿 PR。

    三道关，按顺序过：

    1. review token 必须对——审阅后文件变了就拒收；
    2. 先查同分支已有 PR——重试不造成重复；
    3. ``gh`` 可用且已登录。

    **只生成草稿 PR 命令**；是否执行由用户在界面上显式决定。
    """
    record = get(task_id)
    if record is None:
        raise ContributionError(f"没有这个任务的工作区：{task_id}")

    expected = str(record.get("review_token") or "")
    domain.check_review(review_token, expected)

    active = ops or gitops.RealGitOps()

    # 重试安全：先查有没有同分支的已存在 PR。
    existing = active.find_open_pr(record["repository"], record["branch"])
    if existing:
        return save(domain.transition(record, STATUS_PUBLISHED, pr_url=existing))

    if not active.gh_available():
        raise ContributionError("没找到 gh 命令，装好 GitHub CLI 再发 PR。")
    if not active.gh_authenticated():
        raise ContributionError("gh 还没登录 github.com，请先 gh auth login。")

    command = active.prepare_publish_command(
        record["repository"], record["branch"], record["title"]
    )
    # 发布命令只记在记录里，不在这里执行——发布权留给用户。
    return save(
        domain.transition(
            record,
            STATUS_PUBLISHED,
            publish_command=command,
            published_at=_now(),
        )
    )


def release(task_id: str) -> dict:
    """用户放弃这个工作区。本地改动不动——那是他们的工作。"""
    record = get(task_id)
    if record is None:
        raise ContributionError(f"没有这个任务的工作区：{task_id}")
    return save(domain.transition(record, STATUS_RELEASED))


def start(task_id: str) -> dict:
    """标记为 Agent 正在工作。"""
    record = get(task_id)
    if record is None:
        raise ContributionError(f"没有这个任务的工作区：{task_id}")
    return save(domain.transition(record, STATUS_WORKING))
