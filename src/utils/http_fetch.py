"""到 GitHub 取数的健壮封装：重试、断点续传与限流等待。

仓库文件树动辄数 MB，慢网络下连接常在读取末尾被切断（IncompleteRead）。
这里用 Range 头续传把剩余部分补齐，不必从头再来。
"""

from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 60
DEFAULT_USER_AGENT = "purrcat-research-skills/1.0"


class FetchError(RuntimeError):
    """取数失败。"""


def _rate_limit_reset(exc: Exception) -> int | None:
    """从 403 响应里取限流重置时刻；取不到返回 None。"""
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    try:
        return int(headers.get("X-RateLimit-Reset"))
    except (TypeError, ValueError):
        return None


def fetch_bytes(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = 3,
    user_agent: str = DEFAULT_USER_AGENT,
    wait_for_limit: bool = True,
    max_resumes: int = 5,
) -> bytes:
    """取一个 URL 的完整内容。

    网络抖动重试；读取被切断时用 Range 续传；撞上未认证限额时等到重置再继续。
    """
    chunks: list[bytes] = []
    offset = 0
    attempts = 0
    resumes = 0
    limit_waits = 0
    last_error: Exception | None = None

    while attempts < retries:
        attempts += 1
        headers = {"User-Agent": user_agent}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if offset and getattr(response, "status", 200) != 206:
                    # 服务端不支持断点续传，只能从头再来
                    offset = 0
                    chunks = []
                try:
                    chunks.append(response.read())
                except http.client.IncompleteRead as exc:
                    chunks.append(exc.partial)
                    offset += len(exc.partial)
                    resumes += 1
                    if resumes > max_resumes:
                        raise FetchError(f"响应多次被截断，已放弃: {url}") from exc
                    attempts -= 1
                    continue
            return b"".join(chunks)
        except urllib.error.HTTPError as exc:
            reset_at = _rate_limit_reset(exc) if exc.code == 403 else None
            if wait_for_limit and reset_at and limit_waits < 3:
                wait = max(5, reset_at - int(time.time()) + 5)
                limit_waits += 1
                print(f"[!] 触发速率限制，等待 {wait} 秒后重试")
                time.sleep(wait)
                attempts -= 1
                continue
            last_error = exc
        except FetchError:
            raise
        except Exception as exc:
            last_error = exc
        if attempts < retries:
            time.sleep(1.5 * attempts)

    raise FetchError(f"请求失败 {url}: {last_error}")


def fetch_text(url: str, **kwargs) -> str:
    """取一个 URL 的文本内容。"""
    return fetch_bytes(url, **kwargs).decode("utf-8", errors="replace")
