from __future__ import annotations

from typing import Any

from connectwise_manage_mcp.app import mcp
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient


def _with_optional_raw(result: dict[str, Any], raw: Any, *, include_raw: bool) -> dict[str, Any]:
    """Attach raw API payloads only when callers explicitly request them."""

    if include_raw:
        result["raw"] = raw
    return result


def _company_summary(company: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw company record into a compact, tool-friendly shape.

    The summary keeps the fields most often needed for ticket creation and lookup flows.
    """

    company_type = company.get("type") or {}
    status = company.get("status") or {}
    return {
        "id": company.get("id"),
        "name": company.get("name"),
        "identifier": company.get("identifier"),
        "status": status.get("name"),
        "type": company_type.get("name"),
    }


@mcp.tool(description="Get a single ConnectWise company by numeric id. Use this when you already know company_id and want the current company details without searching first.")
async def get_company(company_id: int) -> dict[str, Any]:
    """Fetch one company and include a compact summary alongside the raw payload.

    Args:
        company_id: Numeric ConnectWise company id.

    Returns:
        A tool response containing the raw company record and a compact summary.
    """

    client = ConnectWiseClient()
    company = await client.get_company(company_id)
    return {"ok": True, "data": company, "summary": _company_summary(company)}


@mcp.tool(description="Search ConnectWise companies by name or identifier. Use this before create_ticket when you need the numeric company_id, because create_ticket expects company_id and not a company name.")
async def search_companies(
    name: str | None = None,
    identifier: str | None = None,
    page: int = 1,
    page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Search companies and return both summaries and raw API data.

    Args:
        name: Optional partial company-name match.
        identifier: Optional partial company identifier match.
        page: 1-based results page.
        page_size: Requested page size.
        include_raw: When true, include the full raw ConnectWise records.

    Returns:
        A tool response containing compact company summaries and raw records.
    """

    client = ConnectWiseClient()
    companies = await client.search_companies(
        name=name,
        identifier=identifier,
        page=page,
        page_size=page_size,
    )
    return _with_optional_raw({
        "ok": True,
        "count": len(companies),
        "data": [_company_summary(company) for company in companies],
    }, companies, include_raw=include_raw)
