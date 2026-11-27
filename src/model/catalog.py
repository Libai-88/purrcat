"""模型目录：provider 预设、参数画像、模型列表拉取与参数自动匹配。

这里是「模型元数据」的唯一事实源：前端不再硬编码 provider 与参数默认值，
配置中心只渲染本模块给出的候选，并在用户选中模型后请求一次 suggest。

匹配优先级（由强到弱，靠前者覆盖后者）：
1. 服务商 ``/models`` 响应里自带的元数据（OpenRouter / Groq 等会返回
   ``context_length`` / ``max_completion_tokens``，最准且实时）；
2. 内置族规则 ``FAMILIES``（只放有明确来源、且短期内不会漂移的几条）；
3. OpenRouter 公共目录（无需 key，缓存 24h）——覆盖内置表没写的第三方模型；
4. provider 默认值 → 全局默认值。

任何一层都没有时也要给出可用的保守默认，不能让用户面对空白表单。
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_FIELDS: Dict[str, Any] = {
    "max_token": 500000,
    "rpm": 60,
    "tpm": 1000000,
    "concurrency": 3,
    "vision": False,
}

#: provider 预设：base_url 只用于「一键填充」，不强制；models_paths 是候选探测路径。
PROVIDERS: List[Dict[str, Any]] = [
    {
        "id": "deepseek",
        "title": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "hosts": ["api.deepseek.com"],
        "defaults": {"rpm": 60, "tpm": 1000000, "concurrency": 3},
    },
    {
        "id": "openai",
        "title": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "hosts": ["api.openai.com"],
        "defaults": {"rpm": 500, "tpm": 2000000, "concurrency": 5},
    },
    {
        "id": "moonshot",
        "title": "Moonshot（Kimi）",
        "base_url": "https://api.moonshot.cn/v1",
        "hosts": ["api.moonshot.cn", "api.moonshot.ai"],
        "defaults": {"rpm": 60, "tpm": 1000000, "concurrency": 3},
    },
    {
        "id": "zhipu",
        "title": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "hosts": ["open.bigmodel.cn"],
        "defaults": {"rpm": 60, "tpm": 1000000, "concurrency": 3},
    },
    {
        "id": "dashscope",
        "title": "阿里云百炼（Qwen）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "hosts": ["dashscope.aliyuncs.com"],
        "defaults": {"rpm": 60, "tpm": 1000000, "concurrency": 3},
    },
    {
        "id": "volcengine",
        "title": "火山方舟（豆包）",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "hosts": ["ark.cn-beijing.volces.com"],
        "defaults": {"rpm": 60, "tpm": 1000000, "concurrency": 3},
    },
    {
        "id": "siliconflow",
        "title": "硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "hosts": ["api.siliconflow.cn"],
        "defaults": {"rpm": 60, "tpm": 1000000, "concurrency": 3},
    },
    {
        "id": "openrouter",
        "title": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "hosts": ["openrouter.ai"],
        "defaults": {"rpm": 60, "tpm": 2000000, "concurrency": 5},
    },
    {
        "id": "groq",
        "title": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "hosts": ["api.groq.com"],
        "defaults": {"rpm": 30, "tpm": 1000000, "concurrency": 3},
    },
    {
        "id": "ollama",
        "title": "Ollama（本地）",
        "base_url": "http://127.0.0.1:11434/v1",
        "hosts": ["127.0.0.1:11434", "localhost:11434"],
        "native_tags_path": "/api/tags",
        "defaults": {"rpm": 0, "tpm": 0, "concurrency": 1},
    },
    {
        "id": "lmstudio",
        "title": "LM Studio（本地）",
        "base_url": "http://127.0.0.1:1234/v1",
        "hosts": ["127.0.0.1:1234", "localhost:1234"],
        "defaults": {"rpm": 0, "tpm": 0, "concurrency": 1},
    },
    {
        "id": "custom",
        "title": "自定义（OpenAI 兼容）",
        "base_url": "",
        "hosts": [],
        "defaults": {},
    },
]

#: 内置族规则：只收录来源明确、短期不漂移的条目。顺序即优先级（先命中先返回）。
#: regex 匹配模型 id（不含 ``sdk:`` 前缀）；fields 只写与全局默认不同的项。
FAMILIES: List[Dict[str, Any]] = [
    {
        "pattern": r"^deepseek-(v4|flash|pro)",
        "fields": {"max_token": 1000000, "vision": True},
        "note": "DeepSeek V4 系列官方标注 1M 上下文、单次输出上限 384K（2026-04 官方新闻）",
    },
    {
        "pattern": r"^deepseek-(chat|reasoner|v3|r1)",
        "fields": {"max_token": 1000000},
        "note": "旧模型名已于 2026-07-24 弃用，当前指向 V4-Flash，按 1M 上下文给出",
    },
    {
        "pattern": r"^gpt-4o|^gpt-4\.1|^gpt-4-turbo",
        "fields": {"max_token": 128000},
        "note": "OpenAI GPT-4o / 4.1 系列公开上下文为 128K，以官方页面为准",
    },
    {
        "pattern": r"^gemini-",
        "fields": {"max_token": 1000000},
        "note": "Gemini 系公开上下文为 1M，以官方页面为准",
    },
]

_OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
_OR_TTL_SECONDS = 24 * 3600
_or_lock = threading.Lock()
_or_cache: Dict[str, Any] = {"at": 0.0, "items": None}


class ModelListError(Exception):
    """模型列表拉取失败；code 供前端区分「地址错 / key 错 / 服务商不开放」。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def providers_public() -> List[Dict[str, Any]]:
    """给前端的 provider 候选（不含内部 hosts 之外的敏感信息）。"""
    out: List[Dict[str, Any]] = []
    for p in PROVIDERS:
        out.append(
            {
                "id": p["id"],
                "title": p["title"],
                "base_url": p["base_url"],
                "defaults": dict(DEFAULT_FIELDS, **(p.get("defaults") or {})),
            }
        )
    return out


def provider_of(base_url: Optional[str]) -> Optional[Dict[str, Any]]:
    """按 host 反查 provider；未知地址返回 None（调用方按 custom 处理）。"""
    if not base_url:
        return None
    host = base_url.strip().lower()
    host = re.sub(r"^https?://", "", host)
    host = host.split("/", 1)[0]
    for p in PROVIDERS:
        for h in p.get("hosts") or []:
            if host == h or host.endswith("." + h):
                return p
    return None


def normalize_base_url(base_url: Optional[str]) -> str:
    """只做确定性整理：去空白、去尾部斜杠，不去 /v1（服务商可能自带前缀）。"""
    return (base_url or "").strip().rstrip("/")


def _candidate_urls(base_url: str, provider: Optional[Dict[str, Any]]) -> List[str]:
    base = normalize_base_url(base_url)
    if not base:
        return []
    root = base[: -len("/v1")] if base.endswith("/v1") else base
    cands = [f"{base}/models", f"{root}/v1/models"]
    native = (provider or {}).get("native_tags_path")
    if native:
        cands.append(f"{root}{native}")
    seen: List[str] = []
    for c in cands:
        if c not in seen:
            seen.append(c)
    return seen


def _http_get(url: str, headers: Dict[str, str], timeout: float) -> Tuple[int, Any]:
    """薄封装便于测试注入；返回 (status, json_payload)。"""
    import httpx

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        try:
            payload = resp.json()
        except Exception:
            payload = None
        return resp.status_code, payload


def _models_from_payload(payload: Any) -> List[Dict[str, Any]]:
    """兼容 OpenAI ``{data:[{id}]}``、OpenRouter 同形、Ollama ``{models:[{name}]}``。"""
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        rows = payload.get("models")
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid = row.get("id") or row.get("name") or row.get("model")
        if not isinstance(mid, str) or not mid.strip():
            continue
        item: Dict[str, Any] = {"id": mid.strip()}
        ctx = row.get("context_length") or row.get("context_window")
        top = row.get("top_provider")
        if isinstance(top, dict):
            ctx = ctx or top.get("context_length")
            item_ctx_cap = top.get("max_completion_tokens")
            if isinstance(item_ctx_cap, int) and item_ctx_cap > 0:
                item["max_output"] = item_ctx_cap
        if isinstance(ctx, int) and ctx > 0:
            item["context_length"] = ctx
        out.append(item)
    out.sort(key=lambda m: m["id"].lower())
    return out


def list_models(
    base_url: Optional[str], api_key: Optional[str] = None, timeout: float = 8.0
) -> Dict[str, Any]:
    """拉取服务商的模型列表；依次探测 OpenAI 兼容路径与 Ollama 原生路径。

    失败抛 :class:`ModelListError`，由 API 层翻成结构化错误；成功返回的
    ``models`` 里可能带 ``context_length`` / ``max_output``（服务商提供时）。
    """
    base = normalize_base_url(base_url)
    if not base:
        raise ModelListError("no_base_url", "请先填写 BASE URL")
    if not re.match(r"^https?://", base):
        raise ModelListError("bad_base_url", "BASE URL 需要以 http:// 或 https:// 开头")
    provider = provider_of(base)
    headers = {"Accept": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    last_error: Optional[ModelListError] = None
    for url in _candidate_urls(base, provider):
        try:
            status, payload = _http_get(url, headers, timeout)
        except Exception as exc:  # 连接失败 / DNS / TLS / 超时
            name = type(exc).__name__.lower()
            code = "timeout" if "timeout" in name else "unreachable"
            msg = (
                "请求超时（8s），请检查网络或代理"
                if code == "timeout"
                else f"无法连接：{exc}"
            )
            last_error = ModelListError(code, msg)
            continue

        if status in (401, 403):
            last_error = ModelListError(
                "unauthorized",
                "API Key 无效，或该服务商不允许用这个 Key 读模型列表",
            )
            continue
        if status == 404:
            last_error = ModelListError(
                "no_endpoint",
                "该地址下没有 /models 接口：请确认 BASE URL（多数服务商要带 /v1）",
            )
            continue
        if status >= 500:
            last_error = ModelListError(
                "upstream_error", f"服务商返回 {status}，稍后再试"
            )
            continue
        if status != 200:
            last_error = ModelListError("http_error", f"服务商返回 {status}")
            continue

        models = _models_from_payload(payload)
        if not models:
            last_error = ModelListError(
                "empty", "接口通了但没解析出模型，可能是非标准返回"
            )
            continue
        return {
            "ok": True,
            "provider": (provider or {}).get("id") or "custom",
            "base_url": base,
            "endpoint": url,
            "count": len(models),
            "models": models[:2000],
        }

    raise last_error or ModelListError("no_endpoint", "没有可用的模型列表接口")


_FAMILY_COMPILED = [(re.compile(f["pattern"], re.IGNORECASE), f) for f in FAMILIES]


def _split_model_id(model_id: str) -> str:
    """``openai:deepseek-flash`` → ``deepseek-flash``（配置 key 带 sdk 前缀）。"""
    mid = (model_id or "").strip()
    if ":" in mid:
        head, tail = mid.split(":", 1)
        head = head.strip().lower()
        if head in {
            "openai",
            "anthropic",
            "azure",
            "ollama",
            "gemini",
            "google",
            "xai",
        }:
            return tail.strip()
    return mid


def _family_match(model_id: str) -> Optional[Dict[str, Any]]:
    for rx, fam in _FAMILY_COMPILED:
        if rx.search(model_id):
            return fam
    return None


def _openrouter_items() -> Optional[List[Dict[str, Any]]]:
    """OpenRouter 公共模型目录（无需 key）；失败返回 None 且不重试轰炸。"""
    now = time.time()
    with _or_lock:
        if _or_cache["items"] is not None and now - _or_cache["at"] < _OR_TTL_SECONDS:
            return _or_cache["items"]
    try:
        status, payload = _http_get(
            _OPENROUTER_URL, {"Accept": "application/json"}, 6.0
        )
        if status != 200:
            return None
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return None
        items = [
            r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)
        ]
    except Exception:
        return None
    with _or_lock:
        _or_cache["at"] = time.time()
        _or_cache["items"] = items
    return items


def _openrouter_lookup(
    model_id: str, items: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    low = model_id.lower()
    by_id: Dict[str, Dict[str, Any]] = {}
    for r in items:
        by_id.setdefault(str(r["id"]).lower(), r)
    if low in by_id:
        return by_id[low]
    # 没有 provider 前缀时，接受 "任意厂商/<model_id>"
    tail = low.split("/")[-1]
    if "/" not in low:
        for rid, row in by_id.items():
            if rid.split("/")[-1] == tail:
                return row
    return None


def _fields_from_openrouter(
    row: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    fields: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}
    ctx = row.get("context_length")
    if isinstance(ctx, int) and ctx > 0:
        meta["context_length"] = ctx
        fields["max_token"] = ctx
    top = row.get("top_provider")
    if isinstance(top, dict):
        cap = top.get("max_completion_tokens")
        if isinstance(cap, int) and cap > 0:
            meta["max_output"] = cap
    params = row.get("supported_parameters")
    if isinstance(params, list) and "tools" in params:
        meta["tools"] = True
    modality = (
        (row.get("architecture") or {}).get("input_modalities")
        if isinstance(row.get("architecture"), dict)
        else None
    )
    if isinstance(modality, list) and "image" in modality:
        fields["vision"] = True
    return fields, meta


def suggest(
    model_id: str,
    base_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """按模型名给出参数建议，并说明依据（matched_by / note）。

    ``metadata`` 是 ``list_models`` 里同一模型的条目（服务商自带上下文时最准）。
    """
    raw = (model_id or "").strip()
    mid = _split_model_id(raw)
    provider = provider_of(base_url)
    base_fields = dict(DEFAULT_FIELDS)
    base_fields.update((provider or {}).get("defaults") or {})

    matched_by = "default"
    note = "未找到该模型的已知参数，先给保守默认；建议按服务商文档核对上下文上限"
    fields = dict(base_fields)
    extra_meta: Dict[str, Any] = {}

    # 1) 服务商元数据
    if isinstance(metadata, dict):
        ctx = metadata.get("context_length")
        if isinstance(ctx, int) and ctx > 0:
            fields["max_token"] = ctx
            matched_by = "provider_metadata"
            note = "上下文上限取自服务商 /models 返回的 context_length"
            extra_meta["context_length"] = ctx
        cap = metadata.get("max_output")
        if isinstance(cap, int) and cap > 0:
            extra_meta["max_output"] = cap

    # 2) 内置族规则
    if matched_by == "default":
        fam = _family_match(mid)
        if fam:
            fields.update(fam.get("fields") or {})
            matched_by = "builtin_family"
            note = fam.get("note") or "内置参数族"

    # 3) OpenRouter 公共目录
    if matched_by == "default":
        items = _openrouter_items()
        row = _openrouter_lookup(mid, items) if items else None
        if row:
            or_fields, or_meta = _fields_from_openrouter(row)
            fields.update(or_fields)
            extra_meta.update(or_meta)
            matched_by = "openrouter"
            note = "参数来自 OpenRouter 公共模型目录（context_length / max_completion_tokens）"

    return {
        "ok": True,
        "model": mid,
        "raw_model": raw,
        "provider": (provider or {}).get("id") or "custom",
        "matched_by": matched_by,
        "note": note,
        "fields": fields,
        "meta": extra_meta,
    }


def effective_limits(
    model_cfg: Dict[str, Any], model_id: Optional[str] = None
) -> Dict[str, Any]:
    """运行时读取限速/上下文参数：``limits.*`` 优先，兼容历史顶层字段。

    历史配置把 ``rpm`` / ``tpm`` / ``concurrency`` 写在条目顶层，而运行时只读
    ``limits``——用户填了却不生效，是本模块要修的核心问题。这里统一收口，
    两边都认，且 ``limits`` 里显式给出的值优先。

    只读本地配置，**不做任何网络请求**（运行时要可预测）。
    """
    cfg = model_cfg if isinstance(model_cfg, dict) else {}
    limits = cfg.get("limits")
    limits = limits if isinstance(limits, dict) else {}
    out: Dict[str, Any] = {}
    for key in ("rpm", "tpm", "concurrency"):
        value = limits.get(key, cfg.get(key))
        out[key] = value
    out["max_token"] = cfg.get("max_token", DEFAULT_FIELDS["max_token"])
    out["vision"] = bool(cfg.get("vision", False))
    return out


def _to_int(value: Any, default: int) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    return out


def normalized_limits(model_cfg: Dict[str, Any]) -> Dict[str, int]:
    """把可能写成字符串的限速值归一成 int，默认值兜底。"""
    eff = effective_limits(model_cfg)
    return {
        "rpm": max(0, _to_int(eff.get("rpm"), DEFAULT_FIELDS["rpm"])),
        "tpm": max(0, _to_int(eff.get("tpm"), DEFAULT_FIELDS["tpm"])),
        "concurrency": max(
            1, _to_int(eff.get("concurrency"), DEFAULT_FIELDS["concurrency"])
        ),
    }
