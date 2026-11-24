"""贡献工作区的领域规则（SPEC-035）。

两条硬规则：Agent 不发布；review token 是 diff 的乐观锁。
"""

from __future__ import annotations

import pytest

from src.contributions import domain, store
from src.contributions.domain import (
    AGENT_INSTRUCTION,
    STATUS_PUBLISHED,
    STATUS_READY,
    STATUS_REVIEW,
    ContributionError,
    ReviewChanged,
)


@pytest.fixture
def contribution_home(tmp_path, monkeypatch):
    import src.utils.config as config
    import src.contributions.store as store_module

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        store_module, "store_root", lambda: str(tmp_path / "data" / "contributions")
    )
    return tmp_path


# ---------- 值约束 ----------


def test_repository_must_be_owner_repo():
    assert domain.normalize_repository("PurrPod/purrcat") == "PurrPod/purrcat"
    with pytest.raises(ContributionError):
        domain.normalize_repository("just-a-name")


def test_task_id_is_restricted():
    assert domain.normalize_task_id("my_task-1") == "my_task-1"
    with pytest.raises(ContributionError):
        domain.normalize_task_id("../escape")


def test_branch_is_derived_from_task():
    assert domain.branch_for("abc") == "purrcat/abc"


def test_title_must_be_single_line():
    with pytest.raises(ContributionError):
        domain.build("t1", "o/r", "/w", "main", "head", "一行\n两行", "", "")


def test_source_url_must_point_to_the_repository():
    with pytest.raises(ContributionError):
        domain.build(
            "t1",
            "o/r",
            "/w",
            "main",
            "head",
            "标题",
            "https://github.com/other/repo/pull/1",
            "",
        )


# ---------- Agent 不发布 ----------


def test_agent_instruction_forbids_publishing():
    """AC-2：提示词必须明确禁止 Agent 自己发布。"""
    for verb in ("commit", "push", "fork", "pull request"):
        assert verb in AGENT_INSTRUCTION


def test_agent_instruction_is_in_chinese():
    """提示词要说 Agent 看得懂的话。"""
    assert "不要" in AGENT_INSTRUCTION
    assert "贡献者会审阅" in AGENT_INSTRUCTION


# ---------- review token ----------


def test_review_token_is_a_diff_fingerprint():
    token1 = domain.review_token("head1", "diff-a", ["f.py"])
    token2 = domain.review_token("head1", "diff-a", ["f.py"])
    assert token1 == token2


def test_review_token_changes_when_diff_changes():
    """AC-3：文件变了，token 就变。"""
    original = domain.review_token("head1", "diff-a", ["f.py"])
    changed = domain.review_token("head1", "diff-b", ["f.py"])
    assert original != changed


def test_review_token_changes_when_a_file_is_added():
    original = domain.review_token("head1", "diff-a", ["f.py"])
    changed = domain.review_token("head1", "diff-a", ["f.py", "g.py"])
    assert original != changed


def test_stale_token_is_refused():
    """AC-4：拿旧 token 发 PR 被拒收。"""
    with pytest.raises(ReviewChanged) as excinfo:
        domain.check_review("old-token", "new-token")
    assert "刷新" in str(excinfo.value)


def test_empty_token_is_refused():
    with pytest.raises(ReviewChanged):
        domain.check_review("", "current")


# ---------- 贡献状态 ----------


def test_status_vocabulary_is_closed():
    record = domain.build("t1", "o/r", "/w", "main", "head", "标题", "", "")
    with pytest.raises(ContributionError):
        domain.transition(record, "也许发布了吧")


def test_contribution_has_no_acceptance_or_verification(contribution_home):
    """AC-7：贡献状态只说流程，不给结论盖章。"""
    record = domain.build("t1", "o/r", "/w", "main", "head", "标题", "", "")
    assert "acceptance" not in record
    assert "verification" not in record


def test_public_view_has_no_credentials():
    """对外投影不含 token / 凭据字段。"""
    record = domain.build("t1", "o/r", "/w", "main", "head", "标题", "", "")
    record["review_token"] = "secret-token"
    record["credential"] = "secret"
    view = domain.public_view(record)
    assert "review_token" not in view
    assert "credential" not in view


# ---------- 工作区流程 ----------


def test_prepare_creates_a_workspace(contribution_home):
    record = store.prepare("t1", "o/r", "/tmp/ws", "标题")
    assert record["status"] == "prepared"
    assert store.get("t1")["title"] == "标题"


def test_prepare_refuses_duplicate(contribution_home):
    store.prepare("t1", "o/r", "/tmp/ws", "标题")
    with pytest.raises(ContributionError):
        store.prepare("t1", "o/r", "/tmp/ws2", "另一个标题")


def test_review_produces_token(contribution_home):
    store.prepare("t1", "o/r", "/tmp/ws", "标题")
    record = store.review("t1", head="head1", diff="+new line", changed_files=["f.py"])
    assert record["status"] == STATUS_REVIEW
    assert record["review_token"]
    assert record["diff"] == "+new line"
    assert record["changed_files"] == ["f.py"]


def test_publish_is_refused_without_ready(contribution_home):
    """审阅之前不能发 PR。"""
    store.prepare("t1", "o/r", "/tmp/ws", "标题")
    store.review("t1", head="h", diff="d", changed_files=["f.py"])
    with pytest.raises(ReviewChanged):
        store.publish("t1", "wrong-token")


def test_publish_only_generates_a_draft_command(contribution_home):
    """AC-6 + 发布权留给用户：只生成草稿命令，不执行。"""

    class FakeOps:
        def find_open_pr(self, repository, branch):
            return ""

        def gh_available(self):
            return True

        def gh_authenticated(self):
            return True

        def prepare_publish_command(self, repository, branch, title):
            return f"gh pr create --draft --repo {repository} --head {branch}"

    store.prepare("t1", "o/r", "/tmp/ws", "标题")
    reviewed = store.review("t1", head="h", diff="d", changed_files=["f.py"])
    ready = store.mark_ready("t1", reviewed["review_token"])
    assert ready["status"] == STATUS_READY

    published = store.publish("t1", reviewed["review_token"], ops=FakeOps())
    assert published["status"] == STATUS_PUBLISHED
    assert "--draft" in published["publish_command"]


def test_existing_pr_is_returned_without_creating_a_new_one(contribution_home):
    """AC-5：重试安全——先查有没有同分支的已存在 PR。"""
    called = []

    class FakeOps:
        def find_open_pr(self, repository, branch):
            called.append((repository, branch))
            return "https://github.com/o/r/pull/7"

    store.prepare("t1", "o/r", "/tmp/ws", "标题")
    reviewed = store.review("t1", head="h", diff="d", changed_files=["f.py"])

    published = store.publish("t1", reviewed["review_token"], ops=FakeOps())

    assert published["pr_url"] == "https://github.com/o/r/pull/7"
    assert called == [("o/r", "purrcat/t1")]


def test_gh_not_installed_keeps_the_work(contribution_home):
    """AC-8：发布失败时本地工作区还在。"""

    class FakeOps:
        def find_open_pr(self, repository, branch):
            return ""

        def gh_available(self):
            return False

    store.prepare("t1", "o/r", "/tmp/ws", "标题")
    reviewed = store.review("t1", head="h", diff="d", changed_files=["f.py"])
    store.mark_ready("t1", reviewed["review_token"])

    with pytest.raises(ContributionError):
        store.publish("t1", reviewed["review_token"], ops=FakeOps())

    assert store.get("t1")["status"] == STATUS_READY
