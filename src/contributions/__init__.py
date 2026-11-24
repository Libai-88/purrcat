"""贡献工作区：本地工作区 → diff → 审阅 → 草稿 PR。

两条硬规则：

- **Agent 不发布**：提示词里明确禁止 commit / push / fork / PR；
  发布权留给用户。
- **review token 是 diff 的乐观锁**：审阅后文件又变了，就不能拿旧审阅发 PR。

贡献状态只说流程走到哪一步，不带 acceptance / verification——
「草稿 PR 建好了」不等于「贡献会被接受」。
"""

from __future__ import annotations

from src.contributions import domain, gitops, store
from src.contributions.domain import (
    AGENT_INSTRUCTION,
    STATUS_VALUES,
    ContributionError,
    ReviewChanged,
)

__all__ = [
    "AGENT_INSTRUCTION",
    "ContributionError",
    "ReviewChanged",
    "STATUS_VALUES",
    "domain",
    "gitops",
    "store",
]
