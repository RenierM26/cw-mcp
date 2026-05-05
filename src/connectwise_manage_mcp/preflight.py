from __future__ import annotations

import json
import sys
from typing import Any

from connectwise_manage_mcp.config import get_settings


def _check_settings() -> dict[str, Any]:
    settings = get_settings()
    missing = [
        name
        for name, value in {
            "CW_BASE_URL": settings.cw_base_url,
            "CW_COMPANY_ID": settings.cw_company_id,
            "CW_PUBLIC_KEY": settings.cw_public_key,
            "CW_PRIVATE_KEY": settings.cw_private_key,
            "CW_CLIENT_ID": settings.cw_client_id,
        }.items()
        if not value
    ]

    warnings: list[str] = []
    if not settings.auth_enabled:
        warnings.append("AUTH_ENABLED is false. Only use this for local development.")
    elif not settings.auth_bearer_token:
        warnings.append("AUTH_ENABLED is true but AUTH_BEARER_TOKEN is empty.")

    if settings.auth_allowed_ips and not settings.auth_trust_x_forwarded_for:
        warnings.append(
            "AUTH_ALLOWED_IPS is set. If running behind a trusted proxy, set "
            "AUTH_TRUST_X_FORWARDED_FOR=true only when forwarded headers are controlled."
        )

    return {
        "ok": not missing and not any("AUTH_BEARER_TOKEN is empty" in item for item in warnings),
        "configured": not missing,
        "missing": missing,
        "warnings": warnings,
        "server": {
            "transport": settings.transport,
            "mcpStatelessHttp": settings.mcp_stateless_http,
            "host": settings.host,
            "port": settings.port,
            "authEnabled": settings.auth_enabled,
            "ipAllowlistEnabled": bool(settings.auth_allowed_ips),
        },
        "connectwise": {
            "baseUrlConfigured": bool(settings.cw_base_url),
            "companyIdConfigured": bool(settings.cw_company_id),
            "publicKeyConfigured": bool(settings.cw_public_key),
            "privateKeyConfigured": bool(settings.cw_private_key),
            "clientIdConfigured": bool(settings.cw_client_id),
            "apiVersion": settings.cw_api_version,
            "timeoutSeconds": settings.cw_timeout_seconds,
            "pageSize": settings.cw_page_size,
            "maxPageSize": settings.cw_max_page_size,
        },
    }


def main() -> None:
    """Validate local environment-backed configuration without calling ConnectWise."""

    try:
        result = _check_settings()
    except Exception as exc:  # noqa: BLE001 - CLI should surface config parser failures cleanly.
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
