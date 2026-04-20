from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, Field


class Settings(BaseModel):
    server_name: str = "ConnectWise Manage MCP"
    transport: str = Field(default_factory=lambda: os.getenv("TRANSPORT", "http"))
    host: str = Field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    cw_base_url: str = Field(default_factory=lambda: os.getenv("CW_BASE_URL", ""))
    cw_company_id: str = Field(default_factory=lambda: os.getenv("CW_COMPANY_ID", ""))
    cw_public_key: str = Field(default_factory=lambda: os.getenv("CW_PUBLIC_KEY", ""))
    cw_private_key: str = Field(default_factory=lambda: os.getenv("CW_PRIVATE_KEY", ""))
    cw_client_id: str = Field(default_factory=lambda: os.getenv("CW_CLIENT_ID", ""))
    cw_api_version: str = Field(default_factory=lambda: os.getenv("CW_API_VERSION", "2024.1"))
    cw_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("CW_TIMEOUT_SECONDS", "30"))
    )
    cw_page_size: int = Field(default_factory=lambda: int(os.getenv("CW_PAGE_SIZE", "50")))
    cw_max_page_size: int = Field(default_factory=lambda: int(os.getenv("CW_MAX_PAGE_SIZE", "100")))

    @property
    def is_configured(self) -> bool:
        return all(
            [
                self.cw_base_url,
                self.cw_company_id,
                self.cw_public_key,
                self.cw_private_key,
                self.cw_client_id,
            ]
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
