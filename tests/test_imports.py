from connectwise_manage_mcp.server import run_http, run_stdio


def test_imports() -> None:
    assert callable(run_http)
    assert callable(run_stdio)
