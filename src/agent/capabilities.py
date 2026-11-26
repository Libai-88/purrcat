"""会话级能力快照：把 UI 模式固化成该会话能用哪些工具域。

为什么不是每轮按当前模式过滤：工具定义位于请求前缀，若在会话中途增删 Schema，
前缀一变，服务端 KV Cache 全部失效——而「长会话缓存命中率高」正是本项目的核心
卖点。因此能力只在会话创建时固化一次，之后切模式只改布局。

老会话（meta 里没有 ``capabilities``）一律给全量：宁可多给，也不能让一个已经在
跑科研流程的会话因为用户切到工作模式而突然失去 paper/data 工具。
"""

from __future__ import annotations

from src.tool.registry import ALL_CAPABILITIES, CORE, RESEARCH

MODE_CAPABILITIES = {
    "work": [CORE],
    "science": [CORE, RESEARCH],
}


def capabilities_for_mode(mode) -> list[str]:
    """未知/空模式一律给全量，避免配置缺失导致能力缩水。"""

    key = str(mode or "").strip().lower()
    return list(MODE_CAPABILITIES.get(key, ALL_CAPABILITIES))


def current_mode() -> str:
    """读宿主当前模式（``settings.json`` 的 ``webminConfig.mode.value``）。

    这是 UI 的全局开关，只在「新建会话」时被读取一次；读不到就返回空串，
    调用方按全量处理。
    """

    try:
        from src.utils.config import get_global_settings

        config = get_global_settings().get("webminConfig") or {}
        mode = (config.get("mode") or {}).get("value")
        return str(mode).strip().lower() if mode else ""
    except Exception:
        return ""


def resolve(session_id) -> list[str]:
    """读会话 meta 的能力快照；缺失时返回全量。"""

    if not session_id:
        return list(ALL_CAPABILITIES)
    try:
        from src.agent.session_layout import meta_path, read_json
        from src.utils.config import SESSIONS_DIR

        meta = read_json(meta_path(SESSIONS_DIR, session_id)) or {}
    except Exception:
        return list(ALL_CAPABILITIES)

    caps = meta.get("capabilities") if isinstance(meta, dict) else None
    if isinstance(caps, list) and caps:
        return [str(item) for item in caps]
    return list(ALL_CAPABILITIES)


def snapshot() -> dict:
    """新建会话要写进 meta 的能力快照。"""

    mode = current_mode()
    return {"mode": mode, "capabilities": capabilities_for_mode(mode)}
