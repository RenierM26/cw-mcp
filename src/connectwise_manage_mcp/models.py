from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    ok: bool = True
    data: Any = None
    message: str | None = None


class TicketSummary(BaseModel):
    id: int | None = None
    summary: str | None = None
    board: str | None = None
    status: str | None = None
    company: str | None = None
    contact: str | None = None
    owner: str | None = None
    updated_at: str | None = Field(default=None, alias="updatedAt")


class CompanySummary(BaseModel):
    id: int | None = None
    name: str | None = None
    identifier: str | None = None
    status: str | None = None
    type: str | None = None


class ContactSummary(BaseModel):
    id: int | None = None
    name: str | None = None
    company: str | None = None
    email: str | None = None
    phone: str | None = None
