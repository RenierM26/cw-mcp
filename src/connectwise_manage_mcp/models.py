from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Generic wrapper used by tools that return a success flag plus payload.

    This model is intentionally loose because most MCP tools in this repo return
    lightly normalized ConnectWise data alongside raw API responses.
    """

    ok: bool = True
    data: Any = None
    message: str | None = None


class TicketSummary(BaseModel):
    """Compact ticket shape exposed by ticket-oriented tools.

    The summary keeps the most useful classification and ownership fields close at
    hand without forcing callers to inspect the full raw ticket payload.
    """

    id: int | None = None
    summary: str | None = None
    board: str | None = None
    status: str | None = None
    company: str | None = None
    contact: str | None = None
    owner: str | None = None
    updated_at: str | None = Field(default=None, alias="updatedAt")


class CompanySummary(BaseModel):
    """Compact company shape exposed by company lookup tools.

    It is meant for quick selection or validation steps before a tool needs the
    full company record.
    """

    id: int | None = None
    name: str | None = None
    identifier: str | None = None
    status: str | None = None
    type: str | None = None


class ContactSummary(BaseModel):
    """Compact contact shape exposed by contact lookup tools.

    It keeps the display name and best-effort email/phone extraction in one
    predictable shape for downstream workflows.
    """

    id: int | None = None
    name: str | None = None
    company: str | None = None
    email: str | None = None
    phone: str | None = None
