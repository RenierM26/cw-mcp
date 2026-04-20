from __future__ import annotations

from typing import Any

from connectwise_manage_mcp.app import mcp
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient


def _with_optional_raw(result: dict[str, Any], raw: Any, *, include_raw: bool) -> dict[str, Any]:
    """Attach raw API payloads only when callers explicitly request them."""

    if include_raw:
        result["raw"] = raw
    return result


def _contact_summary(contact: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw contact record into a compact, tool-friendly shape.

    The helper prefers communication items when present so the summary exposes the
    most useful email and phone values without extra parsing downstream.
    """

    company = contact.get("company") or {}
    communication_items = contact.get("communicationItems") or []
    email = next(
        (
            item.get("value")
            for item in communication_items
            if (item.get("type") or {}).get("name", "").lower() == "email"
        ),
        None,
    )
    phone = next(
        (
            item.get("value")
            for item in communication_items
            if (item.get("type") or {}).get("name", "").lower() in {"phone", "mobile"}
        ),
        None,
    )
    return {
        "id": contact.get("id"),
        "name": contact.get("name") or " ".join(
            part for part in [contact.get("firstName"), contact.get("lastName")] if part
        ),
        "company": company.get("name"),
        "email": email or contact.get("defaultEmailAddress"),
        "phone": phone,
    }


@mcp.tool(description="Search ConnectWise contacts by company, name, or email. Use this before create_ticket when you need a numeric contact_id. If filtering by company_id, pass the numeric ConnectWise company id, not the company name.")
async def search_contacts(
    company_id: int | None = None,
    name: str | None = None,
    email: str | None = None,
    page: int = 1,
    page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Search contacts and return both summaries and raw API data.

    Args:
        company_id: Optional numeric company id filter, not company name.
        name: Optional partial contact-name filter.
        email: Optional partial email filter.
        page: 1-based results page.
        page_size: Requested page size.
        include_raw: When true, include the full raw ConnectWise records.

    Prerequisites:
        Use ``search_companies`` first if you only know the company name and need the
        numeric ``company_id`` filter.

    Returns:
        A tool response containing compact contact summaries and raw records.
    """

    client = ConnectWiseClient()
    contacts = await client.search_contacts(
        company_id=company_id,
        name=name,
        email=email,
        page=page,
        page_size=page_size,
    )
    return _with_optional_raw({
        "ok": True,
        "count": len(contacts),
        "data": [_contact_summary(contact) for contact in contacts],
    }, contacts, include_raw=include_raw)
