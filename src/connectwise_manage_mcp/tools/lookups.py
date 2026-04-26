from __future__ import annotations

from typing import Any

from connectwise_manage_mcp.app import mcp
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient


def _with_optional_raw(result: dict[str, Any], raw: Any, *, include_raw: bool) -> dict[str, Any]:
    """Attach raw API payloads only when callers explicitly request them."""

    if include_raw:
        result["raw"] = raw
    return result


def _board_summary(board: dict[str, Any]) -> dict[str, Any]:
    """Normalize a board record for lookup-oriented responses."""

    return {
        "id": board.get("id"),
        "name": board.get("name"),
        "inactive": board.get("inactiveFlag"),
        "projectFlag": board.get("projectFlag"),
        "workRole": (board.get("workRole") or {}).get("name"),
        "workType": (board.get("workType") or {}).get("name"),
    }


def _board_status_summary(status: dict[str, Any]) -> dict[str, Any]:
    """Normalize a board status record for lookup-oriented responses."""

    board = status.get("board") or {}
    return {
        "id": status.get("id"),
        "name": status.get("name"),
        "board": board.get("name"),
        "sort": status.get("sortOrder"),
        "closed": status.get("closedStatusFlag"),
        "inactive": status.get("inactiveFlag"),
    }


def _board_type_summary(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a board type, subtype, or item record."""

    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "inactive": item.get("inactiveFlag"),
        "defaultFlag": item.get("defaultFlag"),
    }


def _board_team_summary(team: dict[str, Any]) -> dict[str, Any]:
    """Normalize a board team record for lookup-oriented responses."""

    return {
        "id": team.get("id"),
        "name": team.get("name"),
        "location": (team.get("location") or {}).get("name"),
        "department": (team.get("department") or {}).get("name"),
    }


def _member_summary(member: dict[str, Any]) -> dict[str, Any]:
    """Normalize a member record for assignment and time-entry workflows."""

    license_class = member.get("licenseClass")
    if isinstance(license_class, dict):
        license_class_name = license_class.get("name")
    else:
        license_class_name = license_class

    return {
        "id": member.get("id"),
        "identifier": member.get("identifier"),
        "name": member.get("name")
        or " ".join(part for part in [member.get("firstName"), member.get("lastName")] if part),
        "email": member.get("officeEmail"),
        "inactive": member.get("inactiveFlag"),
        "licenseClass": license_class_name,
    }


def _work_type_summary(work_type: dict[str, Any]) -> dict[str, Any]:
    """Normalize a work type record for time-entry workflows."""

    return {
        "id": work_type.get("id"),
        "name": work_type.get("name"),
        "inactive": work_type.get("inactiveFlag"),
        "billTime": work_type.get("billTime"),
    }


def _work_role_summary(work_role: dict[str, Any]) -> dict[str, Any]:
    """Normalize a work role record for time-entry workflows."""

    return {
        "id": work_role.get("id"),
        "name": work_role.get("name"),
        "inactive": work_role.get("inactiveFlag"),
    }


def _location_summary(location: dict[str, Any]) -> dict[str, Any]:
    """Normalize a location record for time-entry workflows."""

    return {
        "id": location.get("id"),
        "name": location.get("name"),
        "inactive": location.get("inactiveFlag"),
        "defaultFlag": location.get("defaultFlag"),
    }


@mcp.tool(description="List or search service boards before ticket create or classification updates. Use this when you need the exact board name for create_ticket, or the numeric board_id needed by get_board_lookup, get_board_statuses, get_board_types, or get_board_subtypes.")
async def list_boards(
    name: str | None = None,
    inactive: bool | None = False,
    page: int = 1,
    page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """List boards and return both summaries and raw API data."""

    client = ConnectWiseClient()
    boards = await client.list_boards(name=name, inactive=inactive, page=page, page_size=page_size)
    return _with_optional_raw({
        "ok": True,
        "count": len(boards),
        "data": [_board_summary(board) for board in boards],
    }, boards, include_raw=include_raw)


@mcp.tool(description="Get the main lookup sets for a service board before update_ticket_status or update_ticket_classifications. Expects numeric ids: board_id is required, type_id is only for subtype lookup, and subtype_id is only for item lookup. Important hierarchy rule: item choices depend on subtype, and subtype choices depend on type. Returns the valid board-specific status, type, subtype, item, and team names that the write tools expect.")
async def get_board_lookup(
    board_id: int,
    type_id: int | None = None,
    subtype_id: int | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Fetch the main lookup sets needed to classify tickets on a board.

    Args:
        board_id: Numeric board id.
        type_id: Optional numeric type id used to also fetch subtypes.
        subtype_id: Optional numeric subtype id used to also fetch items.
        include_raw: When true, include raw lookup payloads alongside normalized summaries.

    Returns:
        A combined lookup payload with normalized summaries plus raw API data.

    Prerequisites:
        Call ``list_boards`` first if the correct ``board_id`` is not already known.
        Write tools such as ``update_ticket_classifications`` use names, not ids, so this
        lookup is the safest way to discover valid names before patching a ticket.
    """

    client = ConnectWiseClient()
    statuses = await client.get_board_statuses(board_id)
    types = await client.get_board_types(board_id)
    teams = await client.get_board_teams(board_id)

    result: dict[str, Any] = {
        "ok": True,
        "boardId": board_id,
        "statuses": [_board_status_summary(status) for status in statuses],
        "types": [_board_type_summary(board_type) for board_type in types],
        "teams": [_board_team_summary(team) for team in teams],
    }

    raw_payload: dict[str, Any] = {
        "statuses": statuses,
        "types": types,
        "teams": teams,
    }

    if type_id is not None:
        subtypes = await client.get_board_subtypes(board_id, type_id)
        result["subtypes"] = [_board_type_summary(subtype) for subtype in subtypes]
        raw_payload["subtypes"] = subtypes

        if subtype_id is not None:
            items = await client.get_board_items(board_id, type_id, subtype_id)
            result["items"] = [_board_type_summary(item) for item in items]
            raw_payload["items"] = items

    return _with_optional_raw(result, raw_payload, include_raw=include_raw)


@mcp.tool(description="Get service board statuses for a board id. Expects a numeric board_id and returns status ids plus names. Usually call list_boards first if you only know the board name, then use the returned status names in update_ticket_status or update_ticket_classifications.")
async def get_board_statuses(board_id: int, include_raw: bool = False) -> dict[str, Any]:
    """Fetch statuses for a specific service board.

    Args:
        board_id: Numeric board id.
        include_raw: When true, include the full raw ConnectWise records.

    Returns:
        A tool response containing normalized status summaries and raw records.

    Prerequisites:
        Call ``list_boards`` first if the correct ``board_id`` is not already known.
        Status write tools expect status names, not ids, so this tool is best used to
        discover the valid board-specific names before updating a ticket.
    """

    client = ConnectWiseClient()
    statuses = await client.get_board_statuses(board_id)
    return _with_optional_raw({
        "ok": True,
        "boardId": board_id,
        "count": len(statuses),
        "data": [_board_status_summary(status) for status in statuses],
    }, statuses, include_raw=include_raw)


@mcp.tool(description="Step 1 for ticket classification. Give board_id. Returns type ids and type names for that board. Choose one type before asking for subtypes.")
async def get_board_types(board_id: int, include_raw: bool = False) -> dict[str, Any]:
    """Fetch board types for a specific service board."""

    client = ConnectWiseClient()
    board_types = await client.get_board_types(board_id)
    return _with_optional_raw({
        "ok": True,
        "boardId": board_id,
        "count": len(board_types),
        "data": [_board_type_summary(board_type) for board_type in board_types],
    }, board_types, include_raw=include_raw)


@mcp.tool(description="Step 2 for ticket classification. Give board_id and the chosen type_id. Returns subtype ids and subtype names. Choose one subtype before asking for items.")
async def get_board_subtypes(board_id: int, type_id: int, include_raw: bool = False) -> dict[str, Any]:
    """Fetch board subtypes for a specific board type."""

    client = ConnectWiseClient()
    subtypes = await client.get_board_subtypes(board_id, type_id)
    return _with_optional_raw({
        "ok": True,
        "boardId": board_id,
        "typeId": type_id,
        "count": len(subtypes),
        "data": [_board_type_summary(subtype) for subtype in subtypes],
    }, subtypes, include_raw=include_raw)


@mcp.tool(description="Step 3 for ticket classification. Give board_id, chosen type_id, and chosen subtype_id. Returns item ids and item names. Use the chosen type name, subtype name, and item name when updating the ticket.")
async def get_board_items(
    board_id: int,
    type_id: int,
    subtype_id: int,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Fetch board items for a specific board type and subtype."""

    client = ConnectWiseClient()
    items = await client.get_board_items(board_id, type_id, subtype_id)
    return _with_optional_raw({
        "ok": True,
        "boardId": board_id,
        "typeId": type_id,
        "subtypeId": subtype_id,
        "count": len(items),
        "data": [_board_type_summary(item) for item in items],
    }, items, include_raw=include_raw)


@mcp.tool(description="Small-model helper for ticket classification. Use this when you have ticket_id and board_id from a webhook. Call order: 1) board_id only returns types. 2) add type_id to return subtypes for that type. 3) add subtype_id to return items for that subtype. Do not choose subtype before type. Do not choose item before subtype.")
async def get_ticket_type_hierarchy(
    board_id: int,
    type_id: int | None = None,
    subtype_id: int | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Fetch only type/subtype/item lookup data for ticket classification.

    This is narrower than get_board_lookup. It does not fetch statuses or teams.
    It is intended for LLM or n8n workflows that classify a ticket from a known board id.
    """

    client = ConnectWiseClient()
    raw_payload: dict[str, Any] = {}
    result: dict[str, Any] = {
        "ok": True,
        "boardId": board_id,
        "nextStep": "choose type_id, then call again with board_id and type_id",
    }

    types = await client.get_board_types(board_id)
    raw_payload["types"] = types
    result["types"] = [_board_type_summary(board_type) for board_type in types]

    if type_id is not None:
        subtypes = await client.get_board_subtypes(board_id, type_id)
        raw_payload["subtypes"] = subtypes
        result["typeId"] = type_id
        result["subtypes"] = [_board_type_summary(subtype) for subtype in subtypes]
        result["nextStep"] = "choose subtype_id, then call again with board_id, type_id, and subtype_id"

        if subtype_id is not None:
            items = await client.get_board_items(board_id, type_id, subtype_id)
            raw_payload["items"] = items
            result["subtypeId"] = subtype_id
            result["items"] = [_board_type_summary(item) for item in items]
            result["nextStep"] = "choose type name, subtype name, and item name, then call update_ticket_type_hierarchy_fast"

    return _with_optional_raw(result, raw_payload, include_raw=include_raw)


@mcp.tool(description="Search ConnectWise members before ownership or time-entry workflows. Use this to find the exact member_identifier string required by add_ticket_time_entry. Do not pass the numeric member id to add_ticket_time_entry.")
async def search_members(
    identifier: str | None = None,
    name: str | None = None,
    inactive: bool | None = False,
    page: int = 1,
    page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Search members and return both summaries and raw API data.

    Args:
        identifier: Optional partial identifier match.
        name: Optional partial first name, last name, or email match.
        inactive: Whether to include inactive members.
        page: 1-based results page.
        page_size: Requested page size.
        include_raw: When true, include the full raw ConnectWise records.
    """

    client = ConnectWiseClient()
    members = await client.search_members(
        identifier=identifier,
        name=name,
        inactive=inactive,
        page=page,
        page_size=page_size,
    )
    return _with_optional_raw({
        "ok": True,
        "count": len(members),
        "data": [_member_summary(member) for member in members],
    }, members, include_raw=include_raw)


@mcp.tool(description="List or search ConnectWise work types before add_ticket_time_entry. That write tool expects work_type as an exact name, not an id, so use this first when the valid names are uncertain.")
async def list_work_types(
    name: str | None = None,
    inactive: bool | None = False,
    page: int = 1,
    page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """List work types and return both summaries and raw API data.

    This is mainly useful before creating time entries so callers can validate names.
    """

    client = ConnectWiseClient()
    work_types = await client.list_work_types(
        name=name,
        inactive=inactive,
        page=page,
        page_size=page_size,
    )
    return _with_optional_raw({
        "ok": True,
        "count": len(work_types),
        "data": [_work_type_summary(item) for item in work_types],
    }, work_types, include_raw=include_raw)


@mcp.tool(description="List or search ConnectWise work roles before add_ticket_time_entry. That write tool expects work_role as an exact name, not an id, so use this first when the valid names are uncertain.")
async def list_work_roles(
    name: str | None = None,
    inactive: bool | None = False,
    page: int = 1,
    page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """List work roles and return both summaries and raw API data.

    This is mainly useful before creating time entries so callers can validate names.
    """

    client = ConnectWiseClient()
    work_roles = await client.list_work_roles(
        name=name,
        inactive=inactive,
        page=page,
        page_size=page_size,
    )
    return _with_optional_raw({
        "ok": True,
        "count": len(work_roles),
        "data": [_work_role_summary(item) for item in work_roles],
    }, work_roles, include_raw=include_raw)


@mcp.tool(description="List or search ConnectWise locations before add_ticket_time_entry when the tenant restricts locations or a non-default location is needed. add_ticket_time_entry accepts location_id as a numeric location id, not a location name. If a time-entry create fails because of location restrictions, call this tool and retry with an allowed location_id.")
async def list_locations(
    name: str | None = None,
    inactive: bool | None = False,
    page: int = 1,
    page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """List locations and return both summaries and raw API data."""

    client = ConnectWiseClient()
    locations = await client.list_locations(
        name=name,
        inactive=inactive,
        page=page,
        page_size=page_size,
    )
    return _with_optional_raw({
        "ok": True,
        "count": len(locations),
        "data": [_location_summary(item) for item in locations],
    }, locations, include_raw=include_raw)
