"""科研环境的领域规则（SPEC-034）。

最要紧的边界：观察 ≠ 授权 ≠ 验证。
探测记录里没有 acceptance / verification，就绪度是三态。
"""

from __future__ import annotations

from src.environments.catalog import (
    CAPABILITY_IDS,
    READINESS_VALUES,
    EnvironmentError,
    get_capability,
    get_tool,
    list_capabilities,
    list_tools,
)
from src.environments.observer import MISSING, READY, UNKNOWN


def test_readiness_is_three_valued():
    """信息不足时说 unknown，不猜一个 ready 出来。"""
    assert READINESS_VALUES == (READY, MISSING, UNKNOWN)
    assert len(set(READINESS_VALUES)) == 3


def test_capability_vocabulary_is_closed():
    assert CAPABILITY_IDS
    assert len(set(CAPABILITY_IDS)) == len(CAPABILITY_IDS)


def test_every_capability_says_what_it_cannot_imply():
    """能力声明里「不能推出什么」才是边界所在。"""
    for cap in list_capabilities():
        assert cap["can"]
        assert cap["cannot"]
        assert len(cap["cannot"]) > 10


def test_capability_lookup_rejects_unknown():
    try:
        get_capability("magic")
    except EnvironmentError:
        pass
    else:
        raise AssertionError("未知能力应该被拒收")


def test_tool_catalog_is_complete():
    ids = [item["id"] for item in list_tools()]
    assert "python" in ids
    assert "git" in ids
    assert "uv" in ids
    assert len(ids) == len(set(ids))


def test_tool_lookup_rejects_unknown():
    try:
        get_tool("not-a-tool")
    except EnvironmentError:
        pass
    else:
        raise AssertionError("未知工具应该被拒收")


def test_observe_a_tool_has_no_acceptance_or_verification(monkeypatch):
    """AC-3：观察记录只说观察到什么，不给结论盖章。"""
    import src.environments.observer as observer

    monkeypatch.setattr(observer, "_path", lambda: None)
    monkeypatch.setattr(observer.shutil, "which", lambda *a, **k: None)

    record = observer.observe_tool("git")

    assert record["readiness"] == MISSING
    assert "acceptance" not in record
    assert "verification" not in record


def test_observation_records_when_and_how(monkeypatch):
    """AC-5：观察记录带时刻与观察方式。"""
    import src.environments.observer as observer

    monkeypatch.setattr(observer, "_path", lambda: None)
    monkeypatch.setattr(observer.shutil, "which", lambda *a, **k: None)

    record = observer.observe_tool("git")

    assert record["observed_at"]
    assert record["observed_by"]


def test_tool_not_found_is_missing_not_unknown(monkeypatch):
    """明确找不到 → missing；找到了但查不到版本 → unknown。两者要分开。"""
    import src.environments.observer as observer

    monkeypatch.setattr(observer, "_path", lambda: None)
    monkeypatch.setattr(observer.shutil, "which", lambda *a, **k: None)

    assert observer.observe_tool("git")["readiness"] == MISSING


def test_version_query_failure_is_unknown(monkeypatch):
    """找到了可执行文件但版本查询失败 → unknown，不猜一个版本。"""
    import src.environments.observer as observer

    monkeypatch.setattr(observer, "_path", lambda: None)
    monkeypatch.setattr(observer.shutil, "which", lambda *a, **k: "/usr/bin/git")

    def _boom(*args, **kwargs):
        raise OSError("cannot run")

    monkeypatch.setattr(observer.subprocess, "run", _boom)

    record = observer.observe_tool("git")

    assert record["readiness"] == UNKNOWN
    assert record["version"] == ""


def test_observe_all_includes_backend_and_capabilities(monkeypatch):
    import src.environments.observer as observer

    monkeypatch.setattr(observer, "_path", lambda: None)
    monkeypatch.setattr(observer.shutil, "which", lambda *a, **k: None)

    report = observer.observe_all(["git", "uv"])

    assert set(report["observations"]) == {"git", "uv"}
    assert "exec_backend" in report
    assert len(report["capabilities"]) == len(CAPABILITY_IDS)
    assert "note" in report
