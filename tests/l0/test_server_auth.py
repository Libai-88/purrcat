"""本地 API 边界：无凭证拒绝、cookie 下发、豁免范围与常量时间比较。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.server import auth

_TOKEN = "fixed-test-token"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(auth, "get_acp_token", lambda: _TOKEN)

    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/secret")
    def secret():
        return {"ok": True}

    @app.get("/minimal/index.html")
    def minimal_page():
        return {"ok": True}

    app.middleware("http")(auth.guard_local_api)
    return TestClient(app)


def test_rejects_request_without_credentials(client):
    assert client.get("/api/secret").status_code == 401


def test_accepts_header_token(client):
    resp = client.get("/api/secret", headers={auth.TOKEN_HEADER: _TOKEN})
    assert resp.status_code == 200


def test_accepts_cookie_token(client):
    client.cookies.set(auth.TOKEN_COOKIE, _TOKEN)
    assert client.get("/api/secret").status_code == 200


def test_rejects_wrong_token(client):
    assert (
        client.get("/api/secret", headers={auth.TOKEN_HEADER: "nope"}).status_code
        == 401
    )


def test_health_is_exempt(client):
    assert client.get("/api/health").status_code == 200


def test_static_host_is_exempt_and_sets_cookie(client):
    resp = client.get("/minimal/index.html")
    assert resp.status_code == 200
    assert auth.TOKEN_COOKIE in resp.cookies


def test_cookie_is_hardened(client):
    resp = client.get("/minimal/index.html")
    header = resp.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "samesite=strict" in header
    assert "path=/" in header


def test_static_host_does_not_reissue_cookie(client):
    client.cookies.set(auth.TOKEN_COOKIE, _TOKEN)
    resp = client.get("/minimal/index.html")
    assert auth.TOKEN_COOKIE not in resp.cookies


def test_options_preflight_is_not_rejected(client):
    resp = client.request("OPTIONS", "/api/secret")
    assert resp.status_code != 401


def test_is_exempt_matches_prefix_not_substring():
    assert auth.is_exempt("/minimal/index.html")
    assert auth.is_exempt("/api/health")
    assert not auth.is_exempt("/api/healthz/../secret")
    assert not auth.is_exempt("/api/minimal")
