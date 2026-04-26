from __future__ import annotations

import pytest

from connectwise_manage_mcp.config import Settings, get_settings


def test_boolean_env_parser_rejects_unknown_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "maybe")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="AUTH_ENABLED must be a boolean"):
        get_settings()


def test_port_must_be_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "eight-thousand")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="PORT must be an integer"):
        get_settings()


def test_numeric_settings_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_TIMEOUT_SECONDS", "0")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="CW_TIMEOUT_SECONDS must be greater than 0"):
        get_settings()


def test_page_size_cannot_exceed_maximum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_PAGE_SIZE", "200")
    monkeypatch.setenv("CW_MAX_PAGE_SIZE", "100")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="CW_PAGE_SIZE cannot be greater than CW_MAX_PAGE_SIZE"):
        get_settings()


def test_invalid_ip_allowlist_fails_early() -> None:
    with pytest.raises(ValueError, match="AUTH_ALLOWED_IPS contains an invalid IP/CIDR"):
        Settings(auth_allowed_ips=["not-an-ip"])
