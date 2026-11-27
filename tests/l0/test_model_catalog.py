"""模型目录：base_url 归一、provider 识别、列表解析与参数匹配（L0，不联网）。"""

from __future__ import annotations

import pytest

from src.model import catalog


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """默认掐断 OpenRouter 公共目录，用例要联网时自行 patch 覆盖。"""
    monkeypatch.setattr(catalog, "_openrouter_items", lambda: None)
    monkeypatch.setattr(catalog, "_or_cache", {"at": 0.0, "items": None})


def test_normalize_base_url_keeps_version_prefix():
    assert catalog.normalize_base_url("  https://api.deepseek.com/  ") == (
        "https://api.deepseek.com"
    )
    assert catalog.normalize_base_url("https://api.openai.com/v1") == (
        "https://api.openai.com/v1"
    )
    assert catalog.normalize_base_url(None) == ""


def test_provider_lookup_by_host():
    assert catalog.provider_of("https://api.deepseek.com")["id"] == "deepseek"
    assert catalog.provider_of("http://127.0.0.1:11434/v1")["id"] == "ollama"
    assert catalog.provider_of("https://some-unknown-host.example.com/v1") is None
    assert catalog.provider_of("") is None


def test_candidate_urls_cover_version_and_native_paths():
    urls = catalog._candidate_urls(
        "https://api.deepseek.com", catalog.provider_of("https://api.deepseek.com")
    )
    assert urls[0] == "https://api.deepseek.com/models"
    assert "https://api.deepseek.com/v1/models" in urls

    ollama = catalog._candidate_urls(
        "http://127.0.0.1:11434/v1", catalog.provider_of("http://127.0.0.1:11434")
    )
    assert "http://127.0.0.1:11434/api/tags" in ollama


def test_parse_openai_and_ollama_payloads():
    rows = catalog._models_from_payload(
        {
            "data": [
                {
                    "id": "gpt-4o",
                    "context_length": 128000,
                    "top_provider": {"max_completion_tokens": 16384},
                },
                {"id": "claude-sonnet", "context_length": 200000},
                {"bogus": 1},
                {"id": "  "},
            ]
        }
    )
    assert [r["id"] for r in rows] == ["claude-sonnet", "gpt-4o"]
    assert rows[1]["context_length"] == 128000
    assert rows[1]["max_output"] == 16384

    tags = catalog._models_from_payload(
        {"models": [{"name": "llama3.2:latest", "model": "llama3.2:latest"}]}
    )
    assert tags == [{"id": "llama3.2:latest"}]
    assert catalog._models_from_payload({"nope": []}) == []
    assert catalog._models_from_payload(None) == []


def test_list_models_falls_through_to_v1(monkeypatch):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        if url.endswith("/v1/models"):
            return 200, {"data": [{"id": "deepseek-flash"}]}
        return 404, {"error": "not found"}

    monkeypatch.setattr(catalog, "_http_get", fake_get)
    out = catalog.list_models("https://api.deepseek.com", "sk-test")
    assert out["ok"] is True
    assert out["provider"] == "deepseek"
    assert out["endpoint"] == "https://api.deepseek.com/v1/models"
    assert out["models"] == [{"id": "deepseek-flash"}]
    assert calls[0] == "https://api.deepseek.com/models"


def test_list_models_error_codes(monkeypatch):
    monkeypatch.setattr(
        catalog, "_http_get", lambda url, headers, timeout: (401, {"error": "bad key"})
    )
    with pytest.raises(catalog.ModelListError) as err:
        catalog.list_models("https://api.openai.com/v1", "sk-bad")
    assert err.value.code == "unauthorized"

    def fake_timeout(url, headers, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(catalog, "_http_get", fake_timeout)
    with pytest.raises(catalog.ModelListError) as err2:
        catalog.list_models("https://api.openai.com/v1", "sk-x")
    assert err2.value.code == "timeout"

    monkeypatch.setattr(catalog, "_http_get", lambda url, headers, timeout: (404, {}))
    with pytest.raises(catalog.ModelListError) as err3:
        catalog.list_models("https://api.openai.com/v1", "sk-x")
    assert err3.value.code == "no_endpoint"


def test_list_models_rejects_bad_base_url():
    with pytest.raises(catalog.ModelListError) as err:
        catalog.list_models("", None)
    assert err.value.code == "no_base_url"
    with pytest.raises(catalog.ModelListError) as err2:
        catalog.list_models("api.deepseek.com", None)
    assert err2.value.code == "bad_base_url"


def test_suggest_prefers_provider_metadata():
    out = catalog.suggest(
        "openai:my-unknown-model",
        "https://api.deepseek.com",
        {"context_length": 262144, "max_output": 32768},
    )
    assert out["matched_by"] == "provider_metadata"
    assert out["fields"]["max_token"] == 262144
    assert out["meta"]["max_output"] == 32768
    assert out["model"] == "my-unknown-model"


def test_suggest_uses_builtin_family_for_deepseek_v4():
    out = catalog.suggest("deepseek-flash", "https://api.deepseek.com")
    assert out["matched_by"] == "builtin_family"
    assert out["fields"]["max_token"] == 1000000
    assert "1M" in out["note"]
    assert out["fields"]["rpm"] == 60


def test_suggest_falls_back_to_openrouter(monkeypatch):
    monkeypatch.setattr(
        catalog,
        "_openrouter_items",
        lambda: [
            {
                "id": "qwen/qwen3-32b",
                "context_length": 131072,
                "top_provider": {"max_completion_tokens": 8192},
                "architecture": {"input_modalities": ["text"]},
                "supported_parameters": ["tools", "max_tokens"],
            }
        ],
    )
    out = catalog.suggest("qwen3-32b", "https://api.siliconflow.cn/v1")
    assert out["matched_by"] == "openrouter"
    assert out["fields"]["max_token"] == 131072
    assert out["meta"]["max_output"] == 8192


def test_suggest_unknown_model_stays_conservative(monkeypatch):
    monkeypatch.setattr(catalog, "_openrouter_items", lambda: None)
    out = catalog.suggest("totally-unknown-model", None)
    assert out["matched_by"] == "default"
    assert out["fields"]["max_token"] == catalog.DEFAULT_FIELDS["max_token"]
    assert out["note"]


def test_effective_limits_reads_legacy_top_level_fields():
    legacy = {"rpm": 60, "tpm": 1000000, "concurrency": 3, "max_token": 500000}
    assert catalog.normalized_limits(legacy) == {
        "rpm": 60,
        "tpm": 1000000,
        "concurrency": 3,
    }
    nested = {"limits": {"rpm": 10, "tpm": 0, "concurrency": 5}, "rpm": 99}
    assert catalog.normalized_limits(nested)["rpm"] == 10
    assert catalog.normalized_limits(nested)["concurrency"] == 5


def test_effective_limits_is_offline_and_tolerant(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("运行时限速参数不允许联网")

    monkeypatch.setattr(catalog, "_http_get", boom)
    assert catalog.normalized_limits({}) == {
        "rpm": 60,
        "tpm": 1000000,
        "concurrency": 3,
    }
    assert catalog.normalized_limits({"rpm": "-5", "concurrency": "0"}) == {
        "rpm": 0,
        "tpm": 1000000,
        "concurrency": 1,
    }
    assert catalog.normalized_limits({"limits": "not-a-dict"})["concurrency"] == 3
