from __future__ import annotations

from typing import Any

from connectwise_manage_mcp.app import mcp
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient


def _board_summary(board: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": board.get("id"),
        "name": board.get("name"),
        "inactive": board.get("inactiveFlag"),
        "projectFlag": board.get("projectFlag"),
        "workRole": (board.get("workRole") or {}).get("name"),
        "workType": (board.get("workType") or {}).get("name"),
    }


def _board_status_summary(status: dict[str, Any]) -> dict[str, Any]:
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
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "inactive": item.get("inactiveFlag"),
        "defaultFlag": item.get("defaultFlag"),
    }


def _board_team_summary(team: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": team.get("id"),
        "name": team.get("name"),
        "location": (team.get("location") or {}).get("name"),
        "department": (team.get("department") or {}).get("name"),
    }


def _member_summary(member: dict[str, Any]) -> dict[str, Any]:
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
    return {
        "id": work_type.get("id"),
        "name": work_type.get("name"),
        "inactive": work_type.get("inactiveFlag"),
        "billTime": work_type.get("billTime"),
    }


def _work_role_summary(work_role: dict[str, Any]) -> dict[str, Any]:
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
    client = ConnectWiseClient()
    boards = await client.list_boards(name=name, inactive=inactive, page=page, page_size=page_size)
    return {
        "ok": True,
        "count": len(boards),
        "data": [_board_summary(board) for board in boards],
        "raw": boards,
    }


@mcp.tool(description="Get statuses, types, teams, and optional subtype/item hierarchy for a service board.")
async def get_board_lookup(
    board_id: int,
    type_id: int | None = None,
    subtype_id: int | None = None,
) -> dict[str, Any]:
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


@mcp.tool(description="Get service board types for a specific ConnectWise service board.")
async def get_board_types(board_id: int) -> dict[str, Any]:
    client = ConnectWiseClient()
    board_types = await client.get_board_types(board_id)
    return {
        "ok": True,
        "boardId": board_id,
        "count": len(board_types),
        "data": [_board_type_summary(board_type) for board_type in board_types],
        "raw": board_types,
    }


@mcp.tool(description="Get service board subtypes for a specific board type.")
async def get_board_subtypes(board_id: int, type_id: int) -> dict[str, Any]:
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


@mcp.tool(description="Get service board items for a specific board type and subtype.")
async def get_board_items(board_id: int, type_id: int, subtype_id: int) -> dict[str, Any]:
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


@mcp.tool(description="Search ConnectWise members for time entry assignment or ownership workflows.")
async def search_members(
    identifier: str | None = None,
    name: str | None = None,
    inactive: bool | None = False,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
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


@mcp.tool(description="List or search ConnectWise work types for time entry creation.")
async def list_work_types(
    name: str | None = None,
    inactive: bool | None = False,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
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


@mcp.tool(description="List or search ConnectWise work roles for time entry creation.")
async def list_work_roles(
    name: str | None = None,
    inactive: bool | None = False,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
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
