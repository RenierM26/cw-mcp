from __future__ import annotations

from collections.abc import Generator

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from connectwise_manage_mcp.config import get_settings
from connectwise_manage_mcp.server import BearerTokenAuthMiddleware, ConnectWiseClient, create_http_app


@pytest.fixture
def auth_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    env = {
        "AUTH_ENABLED": "true",
        "AUTH_BEARER_TOKEN": "super-secret-token",
        "CW_BASE_URL": "https://cw.example.com/v4_6_release/apis/3.0",
        "CW_COMPANY_ID": "exampleco",
        "CW_PUBLIC_KEY": "public-key",
        "CW_PRIVATE_KEY": "private-key",
        "CW_CLIENT_ID": "client-id",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_create_http_app_requires_token_when_auth_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("AUTH_BEARER_TOKEN", raising=False)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="AUTH_ENABLED is true but AUTH_BEARER_TOKEN is empty"):
        create_http_app()



def test_mcp_requires_bearer_token(auth_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CW_CLIENT_ID", raising=False)
    get_settings.cache_clear()

    with TestClient(create_http_app()) as client:
        response = client.get("/mcp")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"ok": False, "message": "Unauthorized"}



def test_mcp_allows_bearer_token(auth_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CW_CLIENT_ID", raising=False)
    get_settings.cache_clear()

    with TestClient(create_http_app()) as client:
        response = client.get(
            "/mcp",
            headers={"Authorization": "Bearer super-secret-token", "Accept": "application/json"},
        )

    assert response.status_code == 406



def test_mcp_allows_lowercase_bearer_scheme(auth_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CW_CLIENT_ID", raising=False)
    get_settings.cache_clear()

    with TestClient(create_http_app()) as client:
        response = client.get(
            "/mcp",
            headers={"Authorization": "bearer super-secret-token", "Accept": "application/json"},
        )

    assert response.status_code == 406



def test_health_is_not_blocked_by_bearer_auth(auth_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CW_CLIENT_ID", raising=False)
    get_settings.cache_clear()

    with TestClient(create_http_app()) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["configured"] is False


def test_health_does_not_expose_raw_connectwise_payload(
    auth_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_healthcheck(self: ConnectWiseClient) -> dict[str, object]:
        return {
            "version": "2024.1",
            "licenseType": "Sensitive",
            "companyName": "Example Co",
        }

    monkeypatch.setattr(ConnectWiseClient, "healthcheck", fake_healthcheck)
    get_settings.cache_clear()

    with TestClient(create_http_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "configured": True,
        "connectwiseReachable": True,
        "authEnabled": True,
        "ipAllowlistEnabled": False,
    }


def test_mcp_respects_ip_allowlist(auth_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ALLOWED_IPS", "10.0.0.0/24")
    monkeypatch.setenv("AUTH_TRUST_X_FORWARDED_FOR", "true")
    monkeypatch.delenv("CW_CLIENT_ID", raising=False)
    get_settings.cache_clear()

    with TestClient(create_http_app()) as client:
        response = client.get(
            "/mcp",
            headers={
                "Authorization": "Bearer super-secret-token",
                "Accept": "application/json",
                "X-Forwarded-For": "192.168.1.20",
            },
        )

    assert response.status_code == 403
    assert response.json() == {"ok": False, "message": "Forbidden"}


def test_mcp_allows_request_from_allowed_forwarded_ip(
    auth_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_ALLOWED_IPS", "10.0.0.0/24,192.168.1.20")
    monkeypatch.setenv("AUTH_TRUST_X_FORWARDED_FOR", "true")
    monkeypatch.delenv("CW_CLIENT_ID", raising=False)
    get_settings.cache_clear()

    with TestClient(create_http_app()) as client:
        response = client.get(
            "/mcp",
            headers={
                "Authorization": "Bearer super-secret-token",
                "Accept": "application/json",
                "X-Forwarded-For": "192.168.1.20",
            },
        )

    assert response.status_code == 406


def test_bearer_middleware_uses_constructor_allowlist_not_cached_settings(
    auth_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_ALLOWED_IPS", "10.0.0.0/24")
    monkeypatch.setenv("AUTH_TRUST_X_FORWARDED_FOR", "true")
    get_settings.cache_clear()

    async def ok(_request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/mcp", ok)],
        middleware=[
            Middleware(
                BearerTokenAuthMiddleware,
                token="super-secret-token",
                protected_prefixes=("/mcp",),
                allowed_ips=("192.168.1.20",),
                trust_x_forwarded_for=True,
            )
        ],
    )

    with TestClient(app) as client:
        response = client.get(
            "/mcp",
            headers={
                "Authorization": "Bearer super-secret-token",
                "X-Forwarded-For": "192.168.1.20",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
