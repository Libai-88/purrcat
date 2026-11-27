"""模型目录 API：三个端点的错误映射与透传（L0，直接调函数，不联网）。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.model import catalog
from src.server.api import config


def test_providers_endpoint_exposes_presets():
    out = config.api_model_providers()
    providers = out["providers"]
    ids = [p["id"] for p in providers]
    assert "deepseek" in ids
    assert "ollama" in ids
    assert ids[-1] == "custom"
    deepseek = next(p for p in providers if p["id"] == "deepseek")
    assert deepseek["base_url"] == "https://api.deepseek.com"
    assert deepseek["defaults"]["max_token"] == catalog.DEFAULT_FIELDS["max_token"]
    assert "hosts" not in deepseek  # 内部字段不外泄


def test_list_endpoint_maps_model_list_error(monkeypatch):
    def boom(base_url, api_key=None):
        raise catalog.ModelListError("unauthorized", "API Key 无效")

    monkeypatch.setattr(catalog, "list_models", boom)
    with pytest.raises(HTTPException) as err:
        config.api_model_list(
            {"base_url": "https://api.deepseek.com", "api_key": "sk-bad"}
        )
    assert err.value.status_code == 400
    assert err.value.detail == {"code": "unauthorized", "message": "API Key 无效"}


def test_list_endpoint_passes_params_through(monkeypatch):
    seen = {}

    def fake(base_url, api_key=None):
        seen["base_url"] = base_url
        seen["api_key"] = api_key
        return {"ok": True, "models": [{"id": "deepseek-flash"}]}

    monkeypatch.setattr(catalog, "list_models", fake)
    out = config.api_model_list(
        {"base_url": "https://api.deepseek.com", "api_key": "sk-test"}
    )
    assert out["models"] == [{"id": "deepseek-flash"}]
    assert seen == {"base_url": "https://api.deepseek.com", "api_key": "sk-test"}


def test_suggest_endpoint_requires_model_name():
    with pytest.raises(HTTPException) as err:
        config.api_model_suggest({"base_url": "https://api.deepseek.com"})
    assert err.value.status_code == 400
    assert err.value.detail["code"] == "no_model"


def test_suggest_endpoint_returns_fields(monkeypatch):
    monkeypatch.setattr(catalog, "_openrouter_items", lambda: None)
    out = config.api_model_suggest(
        {"model": "openai:deepseek-flash", "base_url": "https://api.deepseek.com"}
    )
    assert out["matched_by"] == "builtin_family"
    assert out["fields"]["max_token"] == 1000000


def test_suggest_endpoint_accepts_model_id_alias(monkeypatch):
    monkeypatch.setattr(catalog, "_openrouter_items", lambda: None)
    out = config.api_model_suggest({"model_id": "qwen3", "base_url": ""})
    assert out["model"] == "qwen3"
    assert out["fields"]["max_token"] > 0
