from __future__ import annotations

from typing import Any

from connectwise_manage_mcp.app import mcp
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient


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

    return {
        "id": member.get("id"),
        "identifier": member.get("identifier"),
        "name": member.get("name")
        or " ".join(part for part in [member.get("firstName"), member.get("lastName")] if part),
        "email": member.get("officeEmail"),
        "inactive": member.get("inactiveFlag"),
        "licenseClass": (member.get("licenseClass") or {}).get("name"),
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


@mcp.tool(description="List or search service boards for safer ticket classification workflows.")
async def list_boards(
    name: str | None = None,
    inactive: bool | None = False,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """List boards and return both summaries and raw API data."""

    client = ConnectWiseClient()
    boards = await client.list_boards(name=name, inactive=inactive, page=page, page_size=page_size)
    return {
        "ok": True,
        "count": len(boards),
        "data": [_board_summary(board) for board in boards],
        "raw": boards,
    }


@mcp.tool(description="Get the main lookup sets for a service board before updating ticket classifications. Expects numeric ids: board_id is required, type_id is only for subtype lookup, and subtype_id is only for item lookup. Use this before write calls that need valid board-specific status, type, subtype, item, or team values.")
async def get_board_lookup(
    board_id: int,
    type_id: int | None = None,
    subtype_id: int | None = None,
) -> dict[str, Any]:
    """Fetch the main lookup sets needed to classify tickets on a board.

    Args:
        board_id: Numeric board id.
        type_id: Optional numeric type id used to also fetch subtypes.
        subtype_id: Optional numeric subtype id used to also fetch items.

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
        "raw": {
            "statuses": statuses,
            "types": types,
            "teams": teams,
        },
    }

    if type_id is not None:
        subtypes = await client.get_board_subtypes(board_id, type_id)
        result["subtypes"] = [_board_type_summary(subtype) for subtype in subtypes]
        result["raw"]["subtypes"] = subtypes

        if subtype_id is not None:
            items = await client.get_board_items(board_id, type_id, subtype_id)
            result["items"] = [_board_type_summary(item) for item in items]
            result["raw"]["items"] = items

    return result


@mcp.tool(description="Get service board statuses for a board id. Expects a numeric board_id and returns status ids plus names. Usually call list_boards first if you only know the board name, then use the returned status names in update_ticket_status or update_ticket_classifications.")
async def get_board_statuses(board_id: int) -> dict[str, Any]:
    """Fetch statuses for a specific service board.

    Args:
        board_id: Numeric board id.

    Returns:
        A tool response containing normalized status summaries and raw records.

    Prerequisites:
        Call ``list_boards`` first if the correct ``board_id`` is not already known.
        Status write tools expect status names, not ids, so this tool is best used to
        discover the valid board-specific names before updating a ticket.
    """

    client = ConnectWiseClient()
    statuses = await client.get_board_statuses(board_id)
    return {
        "ok": True,
        "boardId": board_id,
        "count": len(statuses),
        "data": [_board_status_summary(status) for status in statuses],
        "raw": statuses,
    }


@mcp.tool(description="Get service board types for a board id. Expects a numeric board_id and returns type ids plus names. Usually call list_boards first if you only know the board name.")
async def get_board_types(board_id: int) -> dict[str, Any]:
    """Fetch board types for a specific service board."""

    client = ConnectWiseClient()
    board_types = await client.get_board_types(board_id)
    return {
        "ok": True,
        "boardId": board_id,
        "count": len(board_types),
        "data": [_board_type_summary(board_type) for board_type in board_types],
        "raw": board_types,
    }


@mcp.tool(description="Get service board subtypes for a numeric board_id and type_id pair. Use this when a smaller hierarchy-specific lookup is easier than get_board_lookup.")
async def get_board_subtypes(board_id: int, type_id: int) -> dict[str, Any]:
    """Fetch board subtypes for a specific board type."""

    client = ConnectWiseClient()
    subtypes = await client.get_board_subtypes(board_id, type_id)
    return {
        "ok": True,
        "boardId": board_id,
        "typeId": type_id,
        "count": len(subtypes),
        "data": [_board_type_summary(subtype) for subtype in subtypes],
        "raw": subtypes,
    }


@mcp.tool(description="Get service board items for a numeric board_id, type_id, and subtype_id combination. Returns item ids plus names that can then be used to choose the item name for ticket updates.")
async def get_board_items(board_id: int, type_id: int, subtype_id: int) -> dict[str, Any]:
    """Fetch board items for a specific board type and subtype."""

    client = ConnectWiseClient()
    items = await client.get_board_items(board_id, type_id, subtype_id)
    return {
        "ok": True,
        "boardId": board_id,
        "typeId": type_id,
        "subtypeId": subtype_id,
        "count": len(items),
        "data": [_board_type_summary(item) for item in items],
        "raw": items,
    }


@mcp.tool(description="Search ConnectWise members before ownership or time-entry workflows. Use this to find the member_identifier string required by add_ticket_time_entry. Do not confuse member_identifier with the numeric member id.")
async def search_members(
    identifier: str | None = None,
    name: str | None = None,
    inactive: bool | None = False,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Search members and return both summaries and raw API data.

    Args:
        identifier: Optional partial identifier match.
        name: Optional partial first name, last name, or email match.
        inactive: Whether to include inactive members.
        page: 1-based results page.
        page_size: Requested page size.
    """

    client = ConnectWiseClient()
    members = await client.search_members(
        identifier=identifier,
        name=name,
        inactive=inactive,
        page=page,
        page_size=page_size,
    )
    return {
        "ok": True,
        "count": len(members),
        "data": [_member_summary(member) for member in members],
        "raw": members,
    }


@mcp.tool(description="List or search ConnectWise work types before creating time entries. add_ticket_time_entry expects a work type name, so use this first when the valid names are uncertain.")
async def list_work_types(
    name: str | None = None,
    inactive: bool | None = False,
    page: int = 1,
    page_size: int = 50,
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
    return {
        "ok": True,
        "count": len(work_types),
        "data": [_work_type_summary(item) for item in work_types],
        "raw": work_types,
    }


@mcp.tool(description="List or search ConnectWise work roles before creating time entries. add_ticket_time_entry expects a work role name, so use this first when the valid names are uncertain.")
async def list_work_roles(
    name: str | None = None,
    inactive: bool | None = False,
    page: int = 1,
    page_size: int = 50,
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
    return {
        "ok": True,
        "count": len(work_roles),
        "data": [_work_role_summary(item) for item in work_roles],
        "raw": work_roles,
    }
