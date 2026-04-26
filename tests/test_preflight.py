from __future__ import annotations

import pytest

from connectwise_manage_mcp.config import get_settings
from connectwise_manage_mcp.preflight import _check_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_preflight_reports_missing_required_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "CW_BASE_URL",
        "CW_COMPANY_ID",
        "CW_PUBLIC_KEY",
        "CW_PRIVATE_KEY",
        "CW_CLIENT_ID",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AUTH_BEARER_TOKEN", "token")

    result = _check_settings()

    assert result["ok"] is False
    assert result["configured"] is False
    assert result["missing"] == [
        "CW_BASE_URL",
        "CW_COMPANY_ID",
        "CW_PUBLIC_KEY",
        "CW_PRIVATE_KEY",
        "CW_CLIENT_ID",
    ]


def test_preflight_does_not_echo_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_BASE_URL", "https://cw.example.com/v4_6_release/apis/3.0")
    monkeypatch.setenv("CW_COMPANY_ID", "company")
    monkeypatch.setenv("CW_PUBLIC_KEY", "public-secret")
    monkeypatch.setenv("CW_PRIVATE_KEY", "private-secret")
    monkeypatch.setenv("CW_CLIENT_ID", "client-secret")
    monkeypatch.setenv("AUTH_BEARER_TOKEN", "bearer-secret")

    result = _check_settings()
    rendered = str(result)

    assert result["ok"] is True
    assert "public-secret" not in rendered
    assert "private-secret" not in rendered
    assert "client-secret" not in rendered
    assert "bearer-secret" not in rendered
    assert result["connectwise"]["privateKeyConfigured"] is True
