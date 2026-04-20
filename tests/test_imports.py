from typing import cast

from starlette.requests import Request
from starlette.responses import Response

from connectwise_manage_mcp.server import health, run_http, run_stdio


def test_imports() -> None:
    assert callable(run_http)
    assert callable(run_stdio)


async def test_health_route_returns_response() -> None:
    response = await health(cast(Request, object()))
    assert isinstance(response, Response)
