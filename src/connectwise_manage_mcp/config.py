from __future__ import annotations

import os
from ipaddress import IPv4Network, IPv6Network, ip_network
from functools import lru_cache

from pydantic import BaseModel, Field, model_validator

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    """Parse an integer environment variable with a clear error message."""

    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _env_float(name: str, default: float) -> float:
    """Parse a float environment variable with a clear error message."""

    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable using common true/false spellings."""

    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be a boolean: one of true/false, yes/no, on/off, or 1/0.")


def _env_list(name: str) -> list[str]:
    """Parse a comma-separated environment variable into a trimmed string list."""

    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseModel):
    """Environment-backed runtime settings for the MCP server and API client.

    The fields intentionally mirror container or local shell environment variables
    so the same code path works in devcontainers, local shells, and hosted HTTP deployments.
    """

    server_name: str = "ConnectWise Manage MCP"
    transport: str = Field(default_factory=lambda: os.getenv("TRANSPORT", "http"))
    mcp_stateless_http: bool = Field(
        default_factory=lambda: _env_bool("MCP_STATELESS_HTTP", False)
    )
    host: str = Field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: _env_int("PORT", 8000))
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    auth_enabled: bool = Field(default_factory=lambda: _env_bool("AUTH_ENABLED", True))
    auth_bearer_token: str = Field(default_factory=lambda: os.getenv("AUTH_BEARER_TOKEN", ""))
    auth_allowed_ips: list[str] = Field(default_factory=lambda: _env_list("AUTH_ALLOWED_IPS"))
    auth_trust_x_forwarded_for: bool = Field(
        default_factory=lambda: _env_bool("AUTH_TRUST_X_FORWARDED_FOR", False)
    )

    cw_base_url: str = Field(default_factory=lambda: os.getenv("CW_BASE_URL", ""))
    cw_company_id: str = Field(default_factory=lambda: os.getenv("CW_COMPANY_ID", ""))
    cw_public_key: str = Field(default_factory=lambda: os.getenv("CW_PUBLIC_KEY", ""))
    cw_private_key: str = Field(default_factory=lambda: os.getenv("CW_PRIVATE_KEY", ""))
    cw_client_id: str = Field(default_factory=lambda: os.getenv("CW_CLIENT_ID", ""))
    cw_api_version: str = Field(default_factory=lambda: os.getenv("CW_API_VERSION", "2024.1"))
    cw_timeout_seconds: float = Field(default_factory=lambda: _env_float("CW_TIMEOUT_SECONDS", 30))
    cw_page_size: int = Field(default_factory=lambda: _env_int("CW_PAGE_SIZE", 50))
    cw_max_page_size: int = Field(default_factory=lambda: _env_int("CW_MAX_PAGE_SIZE", 100))

    @model_validator(mode="after")
    def validate_runtime_settings(self) -> Settings:
        """Fail fast with clear messages for invalid runtime configuration."""

        if self.port <= 0 or self.port > 65535:
            raise ValueError("PORT must be between 1 and 65535.")
        if self.cw_timeout_seconds <= 0:
            raise ValueError("CW_TIMEOUT_SECONDS must be greater than 0.")
        if self.cw_page_size <= 0:
            raise ValueError("CW_PAGE_SIZE must be greater than 0.")
        if self.cw_max_page_size <= 0:
            raise ValueError("CW_MAX_PAGE_SIZE must be greater than 0.")
        if self.cw_page_size > self.cw_max_page_size:
            raise ValueError("CW_PAGE_SIZE cannot be greater than CW_MAX_PAGE_SIZE.")

        try:
            self.parsed_auth_allowed_ips
        except ValueError as exc:
            raise ValueError("AUTH_ALLOWED_IPS contains an invalid IP/CIDR entry.") from exc

        return self

    @property
    def is_configured(self) -> bool:
        """Return True when the minimum ConnectWise credentials are present.

        This is the guard used by both the health endpoint and the shared client before
        any outbound API request is attempted.
        """

        return all(
            [
                self.cw_base_url,
                self.cw_company_id,
                self.cw_public_key,
                self.cw_private_key,
                self.cw_client_id,
            ]
        )

    @property
    def parsed_auth_allowed_ips(self) -> list[IPv4Network | IPv6Network]:
        """Return parsed IP/CIDR allowlist entries for optional HTTP access control."""

        return [ip_network(value, strict=False) for value in self.auth_allowed_ips]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings object so configuration is loaded once per process.

    Using a cached accessor keeps the rest of the codebase simple while still allowing
    environment-driven configuration at process start.
    """

    return Settings()
