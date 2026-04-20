from __future__ import annotations

from typing import Any

from connectwise_manage_mcp.app import mcp
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient


def _company_summary(company: dict[str, Any]) -> dict[str, Any]:
    company_type = company.get("type") or {}
    status = company.get("status") or {}
    return {
        "id": company.get("id"),
        "name": company.get("name"),
        "identifier": company.get("identifier"),
        "status": status.get("name"),
        "type": company_type.get("name"),
    }


@mcp.tool(description="Get a single ConnectWise company by id.")
async def get_company(company_id: int) -> dict[str, Any]:
    client = ConnectWiseClient()
    company = await client.get_company(company_id)
    return {"ok": True, "data": company, "summary": _company_summary(company)}


@mcp.tool(description="Search ConnectWise companies by name or identifier.")
async def search_companies(
    name: str | None = None,
    identifier: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    client = ConnectWiseClient()
    companies = await client.search_companies(
        name=name,
        identifier=identifier,
        page=page,
        page_size=page_size,
    )
    return {
        "ok": True,
        "count": len(companies),
        "data": [_company_summary(company) for company in companies],
        "raw": companies,
    }
