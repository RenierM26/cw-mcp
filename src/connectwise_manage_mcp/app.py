from __future__ import annotations

from fastmcp import FastMCP

from connectwise_manage_mcp.config import get_settings

settings = get_settings()
mcp = FastMCP(settings.server_name)
