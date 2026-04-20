from __future__ import annotations

from datetime import datetime
from typing import Any

from connectwise_manage_mcp.app import mcp
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient, ConnectWiseError


def _ticket_summary(ticket: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw ticket into a compact summary for tool responses."""

    contact = ticket.get("contact") or {}
    owner = ticket.get("owner") or ticket.get("assignedTo") or {}
    company = ticket.get("company") or {}
    board = ticket.get("board") or {}
    status = ticket.get("status") or {}
    return {
        "id": ticket.get("id"),
        "summary": ticket.get("summary"),
        "board": board.get("name"),
        "status": status.get("name"),
        "type": (ticket.get("type") or {}).get("name"),
        "subType": (ticket.get("subType") or {}).get("name"),
        "item": (ticket.get("item") or {}).get("name"),
        "priority": (ticket.get("priority") or {}).get("name"),
        "company": company.get("name"),
        "contact": contact.get("name"),
        "owner": owner.get("name") or owner.get("identifier"),
        "updatedAt": ticket.get("_info", {}).get("lastUpdated") or ticket.get("lastUpdated"),
    }


def _note_summary(note: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw ticket note into a compact summary."""

    member = note.get("member") or {}
    return {
        "id": note.get("id"),
        "text": note.get("text") or note.get("noteText") or note.get("detailDescription"),
        "createdBy": member.get("identifier") or member.get("name"),
        "createdAt": note.get("dateCreated") or note.get("_info", {}).get("dateEntered"),
        "internal": note.get("internalAnalysisFlag"),
        "detail": note.get("detailDescriptionFlag"),
        "resolution": note.get("resolutionFlag"),
    }


def _time_entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw time entry into a compact summary."""

    member = entry.get("member") or {}
    work_type = entry.get("workType") or {}
    work_role = entry.get("workRole") or {}
    return {
        "id": entry.get("id"),
        "member": member.get("identifier") or member.get("name"),
        "timeStart": entry.get("timeStart"),
        "timeEnd": entry.get("timeEnd"),
        "actualHours": entry.get("actualHours"),
        "hoursDeduct": entry.get("hoursDeduct"),
        "billableOption": entry.get("billableOption"),
        "workType": work_type.get("name"),
        "workRole": work_role.get("name"),
        "notes": entry.get("notes"),
        "internalNotes": entry.get("internalNotes"),
    }


def _normalize_name(value: str | None) -> str:
    """Return a comparison-friendly representation for ConnectWise name matching."""

    return (value or "").strip().casefold()


def _find_by_name(records: list[dict[str, Any]], name: str, *, field: str = "name") -> dict[str, Any] | None:
    """Return the first record whose chosen field matches the provided name."""

    wanted = _normalize_name(name)
    for record in records:
        if _normalize_name(record.get(field)) == wanted:
            return record
    return None


def _sorted_present_strings(records: list[dict[str, Any]], field: str = "name") -> list[str]:
    """Collect a sorted list of non-empty string field values from raw API records."""

    values: list[str] = []
    for record in records:
        value = record.get(field)
        if isinstance(value, str) and value:
            values.append(value)
    return sorted(values)


def _parse_iso_timestamp(value: str, field_name: str) -> None:
    """Validate a timestamp string early so tool errors stay readable."""

    candidate = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ConnectWiseError(
            f"{field_name} must be an ISO-8601 timestamp, for example 2026-04-20T15:30:00Z."
        ) from exc


async def _resolve_board(client: ConnectWiseClient, board_name: str) -> dict[str, Any]:
    """Resolve an exact board record by name for safer board-scoped validation."""

    boards = await client.list_boards(name=board_name, inactive=False, page_size=100)
    board = _find_by_name(boards, board_name)
    if board is None:
        raise ConnectWiseError(
            f"Unknown board '{board_name}'. Call list_boards first and use an exact board name."
        )
    return board


async def _validate_ticket_status(
    client: ConnectWiseClient,
    *,
    board_id: int,
    board_name: str,
    status: str,
) -> None:
    """Ensure a status exists on the chosen board before patching a ticket."""

    statuses = await client.get_board_statuses(board_id)
    if _find_by_name(statuses, status) is None:
        valid_names = _sorted_present_strings(statuses)
        raise ConnectWiseError(
            f"Status '{status}' is not valid for board '{board_name}'. "
            f"Call get_board_statuses or get_board_lookup first. Valid statuses: {', '.join(valid_names)}"
        )


async def _validate_ticket_classifications(
    client: ConnectWiseClient,
    *,
    ticket: dict[str, Any],
    board: str | None,
    status: str | None,
    type_name: str | None,
    sub_type_name: str | None,
    item_name: str | None,
    team: str | None,
) -> None:
    """Preflight board-scoped classification values so write errors stay actionable."""

    current_board = ticket.get("board") or {}
    board_record = (
        await _resolve_board(client, board)
        if board
        else {"id": current_board.get("id"), "name": current_board.get("name")}
    )
    board_id = board_record.get("id")
    board_name = board_record.get("name")
    if board_id is None or not board_name:
        raise ConnectWiseError(
            "Could not determine the ticket's board for validation. Call get_ticket first or provide a valid board name."
        )

    if status:
        await _validate_ticket_status(client, board_id=board_id, board_name=board_name, status=status)

    teams = await client.get_board_teams(board_id)
    if team and _find_by_name(teams, team) is None:
        valid_names = _sorted_present_strings(teams)
        raise ConnectWiseError(
            f"Team '{team}' is not valid for board '{board_name}'. "
            f"Call get_board_lookup first. Valid teams: {', '.join(valid_names)}"
        )

    effective_type_name = type_name or (ticket.get("type") or {}).get("name")
    effective_sub_type_name = sub_type_name or (ticket.get("subType") or {}).get("name")

    if not any([type_name, sub_type_name, item_name]):
        return

    board_types = await client.get_board_types(board_id)
    type_record = None
    if effective_type_name:
        type_record = _find_by_name(board_types, effective_type_name)
        if type_record is None:
            valid_names = _sorted_present_strings(board_types)
            raise ConnectWiseError(
                f"Type '{effective_type_name}' is not valid for board '{board_name}'. "
                f"Call get_board_lookup first. Valid types: {', '.join(valid_names)}"
            )
    elif sub_type_name or item_name:
        raise ConnectWiseError(
            "A valid type_name is required before setting sub_type_name or item_name. "
            "Call get_board_lookup first to choose a matching hierarchy."
        )

    subtype_record = None
    if effective_sub_type_name:
        assert type_record is not None
        subtypes = await client.get_board_subtypes(board_id, type_record["id"])
        subtype_record = _find_by_name(subtypes, effective_sub_type_name)
        if subtype_record is None:
            valid_names = _sorted_present_strings(subtypes)
            raise ConnectWiseError(
                f"Subtype '{effective_sub_type_name}' is not valid for board '{board_name}' and type '{effective_type_name}'. "
                f"Call get_board_lookup or get_board_subtypes first. Valid subtypes: {', '.join(valid_names)}"
            )
    elif item_name:
        raise ConnectWiseError(
            "A valid sub_type_name is required before setting item_name. "
            "Call get_board_lookup first to choose a matching subtype and item."
        )

    if item_name:
        assert type_record is not None and subtype_record is not None
        items = await client.get_board_items(board_id, type_record["id"], subtype_record["id"])
        if _find_by_name(items, item_name) is None:
            valid_names = _sorted_present_strings(items)
            raise ConnectWiseError(
                f"Item '{item_name}' is not valid for board '{board_name}', type '{effective_type_name}', and subtype '{effective_sub_type_name}'. "
                f"Call get_board_lookup or get_board_items first. Valid items: {', '.join(valid_names)}"
            )


async def _validate_time_entry_inputs(
    client: ConnectWiseClient,
    *,
    member_identifier: str,
    time_start: str,
    time_end: str | None,
    work_type: str | None,
    work_role: str | None,
) -> None:
    """Preflight member and work values for clearer agent-facing time-entry errors."""

    _parse_iso_timestamp(time_start, "time_start")
    if time_end:
        _parse_iso_timestamp(time_end, "time_end")

    members = await client.search_members(identifier=member_identifier, inactive=False, page_size=100)
    member = _find_by_name(members, member_identifier, field="identifier")
    if member is None:
        valid_names = _sorted_present_strings(members, field="identifier")
        suggestion = f" Nearby matches: {', '.join(valid_names)}" if valid_names else ""
        raise ConnectWiseError(
            f"Unknown member_identifier '{member_identifier}'. Call search_members first and use the exact identifier.{suggestion}"
        )

    if work_type:
        work_types = await client.list_work_types(name=work_type, inactive=False, page_size=100)
        if _find_by_name(work_types, work_type) is None:
            valid_names = _sorted_present_strings(work_types)
            suggestion = f" Nearby matches: {', '.join(valid_names)}" if valid_names else ""
            raise ConnectWiseError(
                f"Unknown work_type '{work_type}'. Call list_work_types first and use an exact name.{suggestion}"
            )

    if work_role:
        work_roles = await client.list_work_roles(name=work_role, inactive=False, page_size=100)
        if _find_by_name(work_roles, work_role) is None:
            valid_names = _sorted_present_strings(work_roles)
            suggestion = f" Nearby matches: {', '.join(valid_names)}" if valid_names else ""
            raise ConnectWiseError(
                f"Unknown work_role '{work_role}'. Call list_work_roles first and use an exact name.{suggestion}"
            )


@mcp.tool(description="Get a single ConnectWise service ticket by id.")
async def get_ticket(ticket_id: int) -> dict[str, Any]:
    """Fetch one ticket and include a compact summary alongside the raw payload."""

    client = ConnectWiseClient()
    ticket = await client.get_ticket(ticket_id)
    return {"ok": True, "data": ticket, "summary": _ticket_summary(ticket)}


@mcp.tool(description="Get a ticket with summary, description, notes, and time entries in one call.")
async def get_ticket_bundle(
    ticket_id: int,
    notes_page_size: int = 50,
    time_entries_page_size: int = 50,
) -> dict[str, Any]:
    """Fetch a ticket together with its notes and time entries in one call.

    Args:
        ticket_id: Numeric service ticket id.
        notes_page_size: Max notes to fetch for the bundle.
        time_entries_page_size: Max time entries to fetch for the bundle.

    Returns:
        A combined payload containing normalized summaries plus raw API data.
    """

    client = ConnectWiseClient()
    ticket = await client.get_ticket(ticket_id)
    notes = await client.get_ticket_notes(ticket_id, page_size=notes_page_size)
    time_entries = await client.get_ticket_time_entries(ticket_id, page_size=time_entries_page_size)

    description = (
        ticket.get("initialDescription")
        or ticket.get("detailDescription")
        or ticket.get("recordType")
    )

    return {
        "ok": True,
        "ticket": {
            "summary": _ticket_summary(ticket),
            "description": description,
            "raw": ticket,
        },
        "notes": {
            "count": len(notes),
            "data": [_note_summary(note) for note in notes],
            "raw": notes,
        },
        "timeEntries": {
            "count": len(time_entries),
            "data": [_time_entry_summary(entry) for entry in time_entries],
            "raw": time_entries,
        },
    }


@mcp.tool(description="Search ConnectWise service tickets with simple business-friendly filters.")
async def search_tickets(
    board: str | None = None,
    status: str | None = None,
    company: str | None = None,
    summary: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Search tickets and return both summaries and raw API data.

    Args:
        board: Optional board name filter.
        status: Optional status name filter.
        company: Optional partial company-name filter.
        summary: Optional partial summary filter.
        page: 1-based results page.
        page_size: Requested page size.

    Returns:
        A tool response with normalized ticket summaries and raw records.
    """

    client = ConnectWiseClient()
    tickets = await client.search_tickets(
        board=board,
        status=status,
        company=company,
        summary=summary,
        page=page,
        page_size=page_size,
    )
    return {
        "ok": True,
        "count": len(tickets),
        "data": [_ticket_summary(ticket) for ticket in tickets],
        "raw": tickets,
    }


@mcp.tool(description="Create a new ConnectWise service ticket. Expects company_id as a numeric id and board as a board name. Usually call search_companies first to find company_id, optional search_contacts to find contact_id, and list_boards if the board name is uncertain.")
async def create_ticket(
    company_id: int,
    board: str,
    summary: str,
    initial_description: str,
    contact_id: int | None = None,
    priority: str | None = None,
) -> dict[str, Any]:
    """Create a ticket and include a compact summary of the created record.

    Args:
        company_id: Numeric ConnectWise company id, not company name.
        board: Service board name, not board id.
        summary: Ticket summary line.
        initial_description: Initial ticket description/body.
        contact_id: Optional numeric ConnectWise contact id.
        priority: Optional priority name.

    Prerequisites:
        Use ``search_companies`` first if the company id is not already known.
        Use ``search_contacts`` first if a contact id should be attached.
        Use ``list_boards`` first if the exact board name is uncertain.
    """

    client = ConnectWiseClient()
    ticket = await client.create_ticket(
        company_id=company_id,
        board=board,
        summary=summary,
        initial_description=initial_description,
        contact_id=contact_id,
        priority=priority,
    )
    return {"ok": True, "data": ticket, "summary": _ticket_summary(ticket)}


@mcp.tool(description="Update only the status of an existing ConnectWise service ticket. Expects status as a board-specific status name, not a status id. Usually call get_ticket and then get_board_statuses or get_board_lookup first if the valid status names are uncertain.")
async def update_ticket_status(ticket_id: int, status: str) -> dict[str, Any]:
    """Update only the ticket status and echo the requested change.

    Prerequisites:
        Status names are board-specific in ConnectWise. Use ``get_ticket`` to inspect the
        current board, then ``get_board_statuses`` or ``get_board_lookup`` to choose a valid
        status name before calling this tool.
    """

    client = ConnectWiseClient()
    ticket = await client.get_ticket(ticket_id)
    board = ticket.get("board") or {}
    board_id = board.get("id")
    board_name = board.get("name")
    if board_id is None or not board_name:
        raise ConnectWiseError(
            "Could not determine the ticket's board for status validation. Call get_ticket first and verify the ticket has a board."
        )
    await _validate_ticket_status(client, board_id=board_id, board_name=board_name, status=status)
    result = await client.update_ticket_status(ticket_id, status)
    return {"ok": True, "data": result, "ticketId": ticket_id, "newStatus": status}


@mcp.tool(description="Add a note to a ConnectWise service ticket.")
async def add_ticket_note(ticket_id: int, text: str, internal: bool = True) -> dict[str, Any]:
    """Add a note to a ticket and echo whether it was marked internal."""

    client = ConnectWiseClient()
    result = await client.add_ticket_note(ticket_id, text=text, internal=internal)
    return {"ok": True, "data": result, "ticketId": ticket_id, "internal": internal}


@mcp.tool(description="Get notes for a ConnectWise service ticket.")
async def get_ticket_notes(ticket_id: int, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """Return ticket notes as summaries plus raw API data."""

    client = ConnectWiseClient()
    notes = await client.get_ticket_notes(ticket_id, page=page, page_size=page_size)
    return {
        "ok": True,
        "count": len(notes),
        "data": [_note_summary(note) for note in notes],
        "raw": notes,
    }


@mcp.tool(description="Get time entries linked to a ConnectWise service ticket.")
async def get_ticket_time_entries(ticket_id: int, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """Return ticket time entries as summaries plus raw API data."""

    client = ConnectWiseClient()
    entries = await client.get_ticket_time_entries(ticket_id, page=page, page_size=page_size)
    return {
        "ok": True,
        "count": len(entries),
        "data": [_time_entry_summary(entry) for entry in entries],
        "raw": entries,
    }


@mcp.tool(description="Update ticket classification fields like status, priority, board, type, subtype, item, team, severity, impact, or source. Expects board, status, type_name, sub_type_name, item_name, team, severity, impact, and source as names, not ids. Usually call list_boards and get_board_lookup first so the selected values match the board hierarchy.")
async def update_ticket_classifications(
    ticket_id: int,
    status: str | None = None,
    priority: str | None = None,
    board: str | None = None,
    type_name: str | None = None,
    sub_type_name: str | None = None,
    item_name: str | None = None,
    team: str | None = None,
    severity: str | None = None,
    impact: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Patch multiple ticket classification fields and echo the requested values.

    Any argument left as ``None`` is ignored, which makes the tool safe for partial updates.

    Prerequisites:
        Use ``get_ticket`` to inspect the current classification state.
        Use ``list_boards`` to find the board id when only the board name is known.
        Use ``get_board_lookup`` to discover valid board-specific status, type, subtype,
        item, and team names before patching. This tool expects names, not ids.

    Returns:
        A tool response containing the requested field values and raw patch result.
    """

    client = ConnectWiseClient()
    ticket = await client.get_ticket(ticket_id)
    await _validate_ticket_classifications(
        client,
        ticket=ticket,
        board=board,
        status=status,
        type_name=type_name,
        sub_type_name=sub_type_name,
        item_name=item_name,
        team=team,
    )
    result = await client.update_ticket_classifications(
        ticket_id,
        status=status,
        priority=priority,
        board=board,
        type_name=type_name,
        sub_type_name=sub_type_name,
        item_name=item_name,
        team=team,
        severity=severity,
        impact=impact,
        source=source,
    )
    return {
        "ok": True,
        "ticketId": ticket_id,
        "updated": {
            "status": status,
            "priority": priority,
            "board": board,
            "type": type_name,
            "subType": sub_type_name,
            "item": item_name,
            "team": team,
            "severity": severity,
            "impact": impact,
            "source": source,
        },
        "data": result,
    }


@mcp.tool(description="Add a time entry against a ConnectWise service ticket. Expects member_identifier as the ConnectWise member identifier string, not the numeric member id. work_type and work_role are names. Usually call search_members, list_work_types, and list_work_roles first if those values are uncertain.")
async def add_ticket_time_entry(
    ticket_id: int,
    member_identifier: str,
    time_start: str,
    time_end: str | None = None,
    hours_deduct: float | None = None,
    actual_hours: float | None = None,
    billable_option: str | None = None,
    work_type: str | None = None,
    work_role: str | None = None,
    notes: str | None = None,
    internal_notes: str | None = None,
    email_resource_flag: bool = False,
    email_contact_flag: bool = False,
    email_cc_flag: bool = False,
) -> dict[str, Any]:
    """Create a time entry against a ticket and return a compact summary.

    Args:
        ticket_id: Numeric service ticket id.
        member_identifier: ConnectWise member identifier string, not member id.
        time_start: Entry start time as an ISO-8601 timestamp, for example ``2026-04-20T15:30:00Z``.
        time_end: Optional entry end time as an ISO-8601 timestamp.
        hours_deduct: Optional hours-to-deduct value.
        actual_hours: Optional actual-hours value.
        billable_option: Optional billing behavior.
        work_type: Optional work type name.
        work_role: Optional work role name.
        notes: Optional customer-facing notes.
        internal_notes: Optional internal-only notes.
        email_resource_flag: Whether to email the resource.
        email_contact_flag: Whether to email the contact.
        email_cc_flag: Whether to email CC recipients.

    Prerequisites:
        Use ``search_members`` first if the member identifier is not already known.
        Use ``list_work_types`` and ``list_work_roles`` first if the valid names are uncertain.

    Returns:
        A tool response with the raw API result and a normalized time-entry summary.
    """

    client = ConnectWiseClient()
    await _validate_time_entry_inputs(
        client,
        member_identifier=member_identifier,
        time_start=time_start,
        time_end=time_end,
        work_type=work_type,
        work_role=work_role,
    )
    entry = await client.add_time_entry(
        ticket_id=ticket_id,
        member_identifier=member_identifier,
        time_start=time_start,
        time_end=time_end,
        hours_deduct=hours_deduct,
        actual_hours=actual_hours,
        billable_option=billable_option,
        work_type=work_type,
        work_role=work_role,
        notes=notes,
        internal_notes=internal_notes,
        email_resource_flag=email_resource_flag,
        email_contact_flag=email_contact_flag,
        email_cc_flag=email_cc_flag,
    )
    return {"ok": True, "ticketId": ticket_id, "data": entry, "summary": _time_entry_summary(entry)}
