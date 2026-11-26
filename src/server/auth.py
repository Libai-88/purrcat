"""本地 API 边界：只接受本机调用，且要求持有网关 token。

桌面壳与 iframe 插件都与后端同源（``127.0.0.1:<port>``），因此用
``SameSite=Strict`` 的 HttpOnly cookie 让浏览器自动携带凭证——前端不需要改
任何一处 fetch；外部脚本与编辑器侧走 ``X-PurrCat-Token`` 头，与 ``/acp/*``
复用同一个 token 文件，避免维护第二套凭证。

豁免范围只放两类：静态首屏（``/minimal``，cookie 正是在这次响应上下发）与
健康检查（进程就绪探测）。其余 ``/api/*`` 一律校验。
"""

from __future__ import annotations

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from src.utils.config import get_acp_token

TOKEN_HEADER = "X-PurrCat-Token"
TOKEN_COOKIE = "purrcat_token"

# 精确匹配：只有这两个端点可以在无凭证时访问。
EXEMPT_PATHS = frozenset({"/api/health"})
# 前缀匹配：静态宿主与其 iframe 插件页面。
EXEMPT_PREFIXES = ("/minimal",)

_COOKIE_MAX_AGE = 365 * 24 * 3600


def is_exempt(path: str) -> bool:
    """豁免判定统一收口，新增豁免必须同时改这里与测试。"""

    if path in EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def presents_valid_token(request: Request) -> bool:
    """比对请求携带的凭证；头优先，其次同源 cookie。"""

    supplied = request.headers.get(TOKEN_HEADER, "") or request.cookies.get(
        TOKEN_COOKIE, ""
    )
    token = get_acp_token()
    if not supplied:
        return False
    return secrets.compare_digest(supplied, token)


async def guard_local_api(request: Request, call_next):
    """``/api/*`` 强制鉴权；首次加载静态宿主时下发同源 cookie。"""

    path = request.url.path

    # 预检请求不带凭证，交给 CORS 中间件回答；真正的请求仍要过下面的校验。
    if request.method == "OPTIONS":
        return await call_next(request)

    if path.startswith("/api/") and not is_exempt(path):
        if not presents_valid_token(request):
            return JSONResponse(
                status_code=401,
                content={"detail": "invalid API token"},
            )

    response = await call_next(request)

    if path.startswith("/minimal") and TOKEN_COOKIE not in request.cookies:
        response.set_cookie(
            TOKEN_COOKIE,
            get_acp_token(),
            httponly=True,
            samesite="strict",
            path="/",
            max_age=_COOKIE_MAX_AGE,
        )

    return response
