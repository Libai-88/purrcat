"""GitHub 取数封装的重试、断点续传与限流等待（SPEC-025）。"""

from __future__ import annotations

import http.client
import urllib.error

import pytest

from src.utils import http_fetch


class _FakeResponse:
    """模拟 HTTP 响应；``incomplete_at`` 处的第一次 read 会抛 IncompleteRead。"""

    def __init__(
        self, payload: bytes, status: int = 200, incomplete_at: int | None = None
    ):
        self._payload = payload
        self._offset = 0
        self.status = status
        self._incomplete_at = incomplete_at
        self._raised = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        if (
            self._incomplete_at is not None
            and not self._raised
            and self._offset < self._incomplete_at
        ):
            self._raised = True
            chunk = self._payload[self._offset : self._incomplete_at]
            self._offset = self._incomplete_at
            # partial 是已读到的数据，expected 是应有总长
            raise http.client.IncompleteRead(
                chunk, len(self._payload) - self._incomplete_at
            )
        chunk = self._payload[self._offset :]
        self._offset = len(self._payload)
        return chunk


def _http_error(code: int, headers: dict | None = None):
    return urllib.error.HTTPError(
        "https://example.test/x", code, "err", headers or {}, None
    )


def test_fetch_bytes_returns_payload(monkeypatch):
    monkeypatch.setattr(
        http_fetch.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse(b"hello"),
    )

    assert http_fetch.fetch_bytes("https://example.test/x") == b"hello"


def test_fetch_bytes_resumes_after_incomplete_read(monkeypatch):
    """读取被切断时用 Range 续传，把剩余部分补齐。"""
    calls = []

    def fake_urlopen(request, timeout=None):
        range_header = request.get_header("Range")
        calls.append(range_header)
        if not range_header:
            return _FakeResponse(b"0123456789", incomplete_at=4)
        return _FakeResponse(b"456789", status=206)

    monkeypatch.setattr(http_fetch.urllib.request, "urlopen", fake_urlopen)

    result = http_fetch.fetch_bytes("https://example.test/x")

    assert result == b"0123456789"
    assert calls[0] is None
    assert calls[1] == "bytes=4-"


def test_fetch_bytes_restarts_when_range_unsupported(monkeypatch):
    """服务端忽略 Range（返回 200 整份）时用它本身，不把两段拼在一起。"""
    calls = []

    def fake_urlopen(request, timeout=None):
        range_header = request.get_header("Range")
        calls.append(range_header)
        if range_header:
            # 服务端不支持续传，直接给整份
            return _FakeResponse(b"0123456789", status=200)
        return _FakeResponse(b"0123456789", incomplete_at=4)

    monkeypatch.setattr(http_fetch.urllib.request, "urlopen", fake_urlopen)

    result = http_fetch.fetch_bytes("https://example.test/x")

    assert result == b"0123456789"


def test_fetch_bytes_retries_on_transient_error(monkeypatch):
    attempts = {"n": 0}

    def fake_urlopen(request, timeout=None):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise OSError("connection reset")
        return _FakeResponse(b"ok")

    monkeypatch.setattr(http_fetch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(http_fetch.time, "sleep", lambda _seconds: None)

    assert http_fetch.fetch_bytes("https://example.test/x") == b"ok"
    assert attempts["n"] == 2


def test_fetch_bytes_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(
        http_fetch.urllib.request,
        "urlopen",
        lambda request, timeout=None: (_ for _ in ()).throw(OSError("down")),
    )
    monkeypatch.setattr(http_fetch.time, "sleep", lambda _seconds: None)

    with pytest.raises(http_fetch.FetchError):
        http_fetch.fetch_bytes("https://example.test/x", retries=2)


def test_rate_limit_reset_is_read_from_headers():
    error = _http_error(403, {"X-RateLimit-Reset": "1700000000"})

    assert http_fetch._rate_limit_reset(error) == 1700000000


def test_rate_limit_reset_is_none_without_header():
    assert http_fetch._rate_limit_reset(_http_error(403)) is None
