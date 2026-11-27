"""运行时接线：顶层旧字段也要被读到，rpm/tpm 要真的传进 LLMClient。"""

from __future__ import annotations

from src.model import catalog
from src.model.facade import model as facade


def _patch(monkeypatch, cfg):
    calls = {"semaphore": [], "client": []}

    monkeypatch.setattr(
        facade, "get_agent_model", lambda: "openai:deepseek-flash", raising=False
    )
    monkeypatch.setattr(facade, "get_main_model_config", lambda name=None: cfg)
    monkeypatch.setattr(
        facade,
        "get_key_semaphore",
        lambda key, max_concurrency=1: (
            calls["semaphore"].append(max_concurrency) or object() and "sem"
        ),
    )

    class FakeClient:
        def __init__(self, api_key, base_url, rpm=0, tpm=0):
            calls["client"].append({"rpm": rpm, "tpm": tpm, "base_url": base_url})

    monkeypatch.setattr(facade, "LLMClient", FakeClient)
    return calls


def test_agent_model_honours_legacy_top_level_limits(monkeypatch):
    cfg = {
        "base_url": "https://api.deepseek.com",
        "api_keys": ["sk-test"],
        "concurrency": 4,
        "rpm": 30,
        "tpm": 500000,
        "max_token": 1000000,
    }
    calls = _patch(monkeypatch, cfg)
    facade.AgentModel(task_id="t1")
    # 旧实现只读 limits.concurrency 会拿到默认 1，这里必须是配置里的 4
    assert calls["semaphore"] == [4]
    assert calls["client"] == [
        {"rpm": 30, "tpm": 500000, "base_url": "https://api.deepseek.com"}
    ]


def test_agent_model_prefers_nested_limits(monkeypatch):
    cfg = {
        "base_url": "https://api.deepseek.com",
        "api_keys": ["sk-test"],
        "concurrency": 9,
        "rpm": 99,
        "limits": {"concurrency": 2, "rpm": 10, "tpm": 0},
    }
    calls = _patch(monkeypatch, cfg)
    facade.AgentModel(task_id="t2")
    assert calls["semaphore"] == [2]
    assert calls["client"][0]["rpm"] == 10
    assert calls["client"][0]["tpm"] == 0


def test_agent_model_defaults_when_unconfigured(monkeypatch):
    cfg = {"base_url": "https://api.deepseek.com", "api_keys": ["sk-test"]}
    calls = _patch(monkeypatch, cfg)
    facade.AgentModel(task_id="t3")
    defaults = catalog.DEFAULT_FIELDS
    assert calls["semaphore"] == [defaults["concurrency"]]
    assert calls["client"][0]["rpm"] == defaults["rpm"]
    assert calls["client"][0]["tpm"] == defaults["tpm"]
