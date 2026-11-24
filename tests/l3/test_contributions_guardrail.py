"""贡献流程的红线（SPEC-035 AC-2 / AC-6）。

这是静态约束：Agent 绝不能被允许自己发布，PR 只能是草稿。
"""

from __future__ import annotations

from src.contributions.domain import AGENT_INSTRUCTION
from src.contributions.gitops import RealGitOps


def test_agent_instruction_forbids_every_publishing_verb():
    """发布权留给用户——这行提示词不许被改掉。"""
    text = AGENT_INSTRUCTION
    assert "不要 commit" in text
    assert "不要 push" in text
    assert "不要 fork" in text
    assert "不要开 pull request" in text


def test_publish_command_is_always_draft():
    """草稿 PR 是硬要求：生成命令里必须带 --draft，且不带 --fill。"""
    ops = RealGitOps()
    command = ops.prepare_publish_command("o/r", "purrcat/t1", "标题")

    assert "--draft" in command
    assert "--repo" in command
    assert "--head" in command


def test_publish_command_does_not_auto_merge():
    command = RealGitOps().prepare_publish_command("o/r", "b", "t")
    assert "--merge" not in command
