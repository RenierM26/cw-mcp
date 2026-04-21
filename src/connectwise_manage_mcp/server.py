from __future__ import annotations

import logging
from ipaddress import ip_address, ip_network
from typing import Any

import uvicorn
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from connectwise_manage_mcp.app import mcp
from connectwise_manage_mcp.config import get_settings
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient, ConnectWiseError

# Import tool modules so decorators register them.
from connectwise_manage_mcp.tools import companies as _companies  # noqa: F401
from connectwise_manage_mcp.tools import contacts as _contacts  # noqa: F401
from connectwise_manage_mcp.tools import lookups as _lookups  # noqa: F401
from connectwise_manage_mcp.tools import tickets as _tickets  # noqa: F401

logger = logging.getLogger(__name__)


class BearerTokenAuthMiddleware(BaseHTTPMiddleware):
    """Require an exact bearer token for protected HTTP routes."""

    def __init__(
        self,
        app: Any,
        *,
        token: str,
        protected_prefixes: tuple[str, ...],
        allowed_ips: tuple[str, ...] = (),
        trust_x_forwarded_for: bool = False,
    ) -> None:
        super().__init__(app)
        self.token = token
        self.protected_prefixes = protected_prefixes
        self.allowed_networks = (
            tuple(ip_network(value, strict=False) for value in allowed_ips) if allowed_ips else ()
        )
        self.trust_x_forwarded_for = trust_x_forwarded_for

    def _client_ip(self, request: Request) -> str | None:
        """Return the best client IP candidate for allowlist checks."""

        if self.trust_x_forwarded_for:
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                return forwarded.split(",", 1)[0].strip()
        return request.client.host if request.client else None

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """Reject protected requests that do not present the configured bearer token."""

        path = request.url.path.rstrip("/") or "/"
        if not any(path == prefix or path.startswith(f"{prefix}/") for prefix in self.protected_prefixes):
            return await call_next(request)

        if self.allowed_networks:
            client_ip = self._client_ip(request)
            if client_ip is None:
                return JSONResponse({"ok": False, "message": "Forbidden"}, status_code=403)

            try:
                parsed_ip = ip_address(client_ip)
            except ValueError:
                return JSONResponse({"ok": False, "message": "Forbidden"}, status_code=403)

            if not any(parsed_ip in network for network in self.allowed_networks):
                return JSONResponse({"ok": False, "message": "Forbidden"}, status_code=403)

        provided = request.headers.get("authorization", "").strip()
        scheme, _, token = provided.partition(" ")
        if scheme.casefold() != "bearer" or token.strip() != self.token:
            return JSONResponse(
                {"ok": False, "message": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)


def create_http_app() -> Any:
    """Build the FastMCP HTTP app with optional bearer-token protection."""

    settings = get_settings()
    middleware: list[Middleware] = []

    if settings.auth_enabled:
        if not settings.auth_bearer_token:
            raise RuntimeError(
                "AUTH_ENABLED is true but AUTH_BEARER_TOKEN is empty. "
                "Set a long random bearer token or disable auth explicitly for local development."
            )
        middleware.append(
            Middleware(
                BearerTokenAuthMiddleware,
                token=settings.auth_bearer_token,
                protected_prefixes=("/mcp",),
                allowed_ips=tuple(settings.auth_allowed_ips),
                trust_x_forwarded_for=settings.auth_trust_x_forwarded_for,
            )
        )

    return mcp.http_app(path="/mcp", middleware=middleware, transport="http")


@mcp.custom_route("/health", methods=["GET"])  # type: ignore[arg-type]
async def health(_: Any) -> Response:
    """Report whether the server is configured and whether ConnectWise is reachable.

    Returns:
        A JSON health response with an HTTP status that reflects configuration or upstream failures.
    """

    settings = get_settings()
    if not settings.is_configured:
        return JSONResponse(
            {
                "ok": False,
                "configured": False,
                "message": "ConnectWise environment variables are not fully configured.",
            },
            status_code=503,
        )

    client = ConnectWiseClient()
    try:
        await client.healthcheck()
        return JSONResponse(
            {
                "ok": True,
                "configured": True,
                "connectwiseReachable": True,
                "authEnabled": settings.auth_enabled,
                "ipAllowlistEnabled": bool(settings.auth_allowed_ips),
            }
        )
    except ConnectWiseError as exc:
        logger.warning("Healthcheck failed: %s", exc)
        return JSONResponse(
            {
                "ok": False,
                "configured": True,
                "connectwiseReachable": False,
                "authEnabled": settings.auth_enabled,
                "ipAllowlistEnabled": bool(settings.auth_allowed_ips),
                "message": str(exc),
            },
            status_code=502,
        )


def run_http() -> None:
    """Start the FastMCP server using streamable HTTP transport."""

    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    uvicorn.run(create_http_app(), host=settings.host, port=settings.port)


def run_stdio() -> None:
    """Start the FastMCP server using stdio transport."""

    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    mcp.run(transport="stdio")


if __name__ == "__main__":
    if get_settings().transport == "stdio":
        run_stdio()
    else:
        run_http()
