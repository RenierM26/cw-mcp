from __future__ import annotations

from typing import Any

from connectwise_manage_mcp.app import mcp
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient


def _contact_summary(contact: dict[str, Any]) -> dict[str, Any]:
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


@mcp.tool(description="Search ConnectWise contacts by company, name, or email.")
async def search_contacts(
    company_id: int | None = None,
    name: str | None = None,
    email: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    client = ConnectWiseClient()
    contacts = await client.search_contacts(
        company_id=company_id,
        name=name,
        email=email,
        page=page,
        page_size=page_size,
    )
    return {
        "ok": True,
        "count": len(contacts),
        "data": [_contact_summary(contact) for contact in contacts],
        "raw": contacts,
    }
