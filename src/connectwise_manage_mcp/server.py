from __future__ import annotations

import logging
from typing import Any

from connectwise_manage_mcp.app import mcp
from connectwise_manage_mcp.config import get_settings
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient, ConnectWiseError

# Import tool modules so decorators register them.
from connectwise_manage_mcp.tools import companies as _companies  # noqa: F401
from connectwise_manage_mcp.tools import contacts as _contacts  # noqa: F401
from connectwise_manage_mcp.tools import lookups as _lookups  # noqa: F401
from connectwise_manage_mcp.tools import tickets as _tickets  # noqa: F401

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


@mcp.custom_route("/health", methods=["GET"])  # type: ignore[arg-type]
async def health(_: Any) -> dict[str, Any]:
    if not settings.is_configured:
        return {
            "ok": False,
            "configured": False,
            "message": "ConnectWise environment variables are not fully configured.",
        }

    client = ConnectWiseClient()
    try:
        info = await client.healthcheck()
        return {"ok": True, "configured": True, "info": info}
    except ConnectWiseError as exc:
        logger.warning("Healthcheck failed: %s", exc)
        return {"ok": False, "configured": True, "message": str(exc)}


def run_http() -> None:
    mcp.run(transport="http", host=settings.host, port=settings.port)


def run_stdio() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    if settings.transport == "stdio":
        run_stdio()
    else:
        run_http()
