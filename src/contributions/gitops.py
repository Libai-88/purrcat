"""Git seam：贡献流程用到的所有 Git / gh 操作都从这里走。

做成 seam 有两个原因：

1. 测试能用假实现，不碰真实仓库、不发真 PR；
2. 发布是对外动作，所有发布相关操作集中在这里，便于审计。

**发布权留给用户**：``prepare_publish_command`` 只生成命令字符串，
不会执行它；执行与否由用户在界面上显式决定。
"""

from __future__ import annotations

import os
import subprocess
from typing import Protocol


class GitOps(Protocol):
    """贡献流程需要的 Git 操作。"""

    def clone(self, repository: str, workspace: str) -> None: ...
    def checkout(self, workspace: str, branch: str, create: bool) -> None: ...
    def head(self, workspace: str) -> str: ...
    def status(self, workspace: str) -> list[str]: ...
    def diff(self, workspace: str, base_head: str) -> str: ...
    def add_all(self, workspace: str) -> None: ...
    def commit(self, workspace: str, message: str) -> None: ...
    def default_branch(self, workspace: str) -> str: ...
    def gh_available(self) -> bool: ...
    def gh_authenticated(self) -> bool: ...
    def find_open_pr(self, repository: str, branch: str) -> str: ...
    def prepare_publish_command(
        self, repository: str, branch: str, title: str
    ) -> str: ...


def _run(args: list[str], cwd: str | None = None, check: bool = True) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args[:3])} 失败：{(completed.stderr or completed.stdout).strip()[:300]}"
        )
    return (completed.stdout or "").strip()


class RealGitOps:
    """真跑 git / gh 的实现。"""

    def clone(self, repository: str, workspace: str) -> None:
        os.makedirs(os.path.dirname(workspace) or ".", exist_ok=True)
        _run(
            [
                "git",
                "clone",
                "--origin",
                "upstream",
                "--single-branch",
                f"https://github.com/{repository}.git",
                workspace,
            ]
        )

    def checkout(self, workspace: str, branch: str, create: bool) -> None:
        args = ["git", "checkout"]
        if create:
            args.append("-b")
        args.append(branch)
        _run(args, cwd=workspace)

    def head(self, workspace: str) -> str:
        return _run(["git", "rev-parse", "HEAD"], cwd=workspace)

    def status(self, workspace: str) -> list[str]:
        raw = _run(["git", "status", "--porcelain"], cwd=workspace)
        return [line for line in raw.splitlines() if line.strip()]

    def diff(self, workspace: str, base_head: str) -> str:
        tracked = _run(
            ["git", "diff", "--no-ext-diff", "--binary", base_head, "--"],
            cwd=workspace,
        )
        untracked = _run(
            ["git", "ls-files", "--others", "--exclude-standard"], cwd=workspace
        )
        return "\n".join(part for part in (tracked, untracked) if part)

    def add_all(self, workspace: str) -> None:
        _run(["git", "add", "--all"], cwd=workspace)

    def commit(self, workspace: str, message: str) -> None:
        _run(["git", "commit", "-m", message], cwd=workspace)

    def default_branch(self, workspace: str) -> str:
        return _run(
            ["git", "symbolic-ref", "--short", "refs/remotes/upstream/HEAD"],
            cwd=workspace,
        )

    def gh_available(self) -> bool:
        import shutil

        return shutil.which("gh") is not None

    def gh_authenticated(self) -> bool:
        try:
            _run(["gh", "auth", "status", "--hostname", "github.com"])
            return True
        except RuntimeError:
            return False

    def find_open_pr(self, repository: str, branch: str) -> str:
        """发之前先查：重试不能造成重复 PR。"""
        raw = _run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repository,
                "--head",
                branch,
                "--state",
                "open",
                "--json",
                "url",
            ],
            check=False,
        )
        if not raw or raw == "[]":
            return ""
        try:
            import json

            items = json.loads(raw)
            return str(items[0].get("url") or "") if items else ""
        except (ValueError, IndexError, AttributeError):
            return ""

    def prepare_publish_command(self, repository: str, branch: str, title: str) -> str:
        """只生成草稿 PR 命令字符串，不执行。

        ``--draft`` 是硬要求：贡献只发草稿，不直接可合并。
        """
        import shlex

        return (
            "gh pr create --draft "
            f"--repo {shlex.quote(repository)} "
            f"--head {shlex.quote(branch)} "
            f"--title {shlex.quote(title)}"
        )
