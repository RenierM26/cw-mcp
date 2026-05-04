from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from connectwise_manage_mcp.app import mcp
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient, ConnectWiseError


def _with_optional_raw(result: dict[str, Any], raw: Any, *, include_raw: bool) -> dict[str, Any]:
    """Attach raw API payloads only when callers explicitly request them."""

    if include_raw:
        result["raw"] = raw
    return result


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



def _configuration_summary(configuration: dict[str, Any]) -> dict[str, Any]:
    """Normalize a ConnectWise configuration into a compact, matching-friendly shape."""

    company = configuration.get("company") or {}
    contact = configuration.get("contact") or {}
    config_type = configuration.get("type") or {}
    status = configuration.get("status") or {}
    return {
        "id": configuration.get("id"),
        "name": configuration.get("name"),
        "type": config_type.get("name"),
        "status": status.get("name"),
        "companyId": company.get("id"),
        "company": company.get("name"),
        "contactId": contact.get("id"),
        "contact": contact.get("name"),
        "deviceIdentifier": configuration.get("deviceIdentifier"),
        "serialNumber": configuration.get("serialNumber"),
        "tagNumber": configuration.get("tagNumber"),
        "lastLoginName": configuration.get("lastLoginName"),
        "ipAddress": configuration.get("ipAddress"),
        "active": configuration.get("activeFlag"),
        "updatedAt": configuration.get("_info", {}).get("lastUpdated") or configuration.get("lastUpdated"),
    }


def _configuration_reference_summary(reference: dict[str, Any]) -> dict[str, Any]:
    """Normalize a ticket configuration reference."""

    return {
        "id": reference.get("id"),
        "deviceIdentifier": reference.get("deviceIdentifier"),
    }


def _username_candidates(ticket: dict[str, Any], contact_configurations: list[dict[str, Any]]) -> list[str]:
    """Collect likely username strings from ticket contact and contact-owned configs."""

    values: list[str] = []
    contact = ticket.get("contact") or {}
    for value in (
        ticket.get("contactEmailLookup"),
        ticket.get("contactEmailAddress"),
        contact.get("email"),
        contact.get("defaultEmailAddress"),
        contact.get("name"),
        ticket.get("contactName"),
    ):
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
            if "@" in value:
                values.append(value.split("@", 1)[0].strip())

    for configuration in contact_configurations:
        for value in (
            configuration.get("lastLoginName"),
            configuration.get("deviceIdentifier"),
            configuration.get("name"),
        ):
            if isinstance(value, str) and value.strip():
                values.append(value.strip())

    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def _clean_match_value(value: str | None) -> str:
    """Normalize user/device strings for fuzzy comparison."""

    if not value:
        return ""
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _configuration_match_score(configuration: dict[str, Any], usernames: list[str]) -> dict[str, Any]:
    """Score a configuration against candidate usernames without hiding the reason."""

    searchable = {
        "lastLoginName": configuration.get("lastLoginName"),
        "deviceIdentifier": configuration.get("deviceIdentifier"),
        "name": configuration.get("name"),
    }
    best = {"score": 0.0, "matchedUsername": None, "matchedField": None, "matchedValue": None}
    for username in usernames:
        clean_username = _clean_match_value(username)
        if not clean_username:
            continue
        for field, value in searchable.items():
            if not isinstance(value, str) or not value.strip():
                continue
            clean_value = _clean_match_value(value)
            if not clean_value:
                continue
            if clean_username == clean_value:
                score = 1.0
            elif clean_username in clean_value or clean_value in clean_username:
                score = min(len(clean_username), len(clean_value)) / max(len(clean_username), len(clean_value))
                score = max(score, 0.92)
            else:
                score = SequenceMatcher(None, clean_username, clean_value).ratio()
            if score > best["score"]:
                best = {
                    "score": round(score, 3),
                    "matchedUsername": username,
                    "matchedField": field,
                    "matchedValue": value,
                }
    return best

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


def _ticket_description(ticket: dict[str, Any], notes: list[dict[str, Any]]) -> str | None:
    """Return the best available ticket description without inventing one."""

    direct_description = ticket.get("initialDescription") or ticket.get("detailDescription")
    if isinstance(direct_description, str) and direct_description:
        return direct_description

    detail_notes = [note for note in notes if note.get("detailDescriptionFlag")]
    if not detail_notes:
        return None

    oldest_detail_note = sorted(
        detail_notes,
        key=lambda note: note.get("dateCreated") or note.get("_info", {}).get("dateEntered") or "",
    )[0]
    text = (
        oldest_detail_note.get("text")
        or oldest_detail_note.get("noteText")
        or oldest_detail_note.get("detailDescription")
    )
    return text if isinstance(text, str) and text else None


def _managed_note_marker(note_key: str) -> str:
    """Return the stable marker used to find an idempotent managed note."""

    safe_key = note_key.strip()
    if not safe_key:
        raise ConnectWiseError("note_key must not be empty.")
    return f"[cw-mcp-managed-note:{safe_key}]"


def _managed_note_text(note_key: str, content: str) -> str:
    """Prefix managed note content with a stable key marker."""

    return f"{_managed_note_marker(note_key)}\n\n{content}"


def _compose_text_field(
    field_name: str,
    value: str | None,
    lines: list[str] | None = None,
    blocks: list[str] | None = None,
    *,
    required: bool = True,
) -> str | None:
    """Build note text from a direct string, lines, or paragraph blocks."""

    provided = [
        name
        for name, candidate in (
            (field_name, value),
            (f"{field_name}_lines", lines),
            (f"{field_name}_blocks", blocks),
        )
        if candidate is not None
    ]
    if len(provided) > 1:
        raise ConnectWiseError(f"Provide only one of {', '.join(provided)}.")
    if lines is not None:
        value = "\n".join(lines)
    if blocks is not None:
        value = "\n\n".join(blocks)
    if required and value is None:
        raise ConnectWiseError(f"{field_name} is required.")
    return value



def _normalize_note_text(value: str | None) -> str:
    """Normalize note text for duplicate detection."""

    return "\n".join((value or "").strip().splitlines())


def _note_member_id(note: dict[str, Any]) -> int | None:
    """Extract the ConnectWise member id that created a note when available."""

    member = note.get("member") or {}
    member_id = member.get("id")
    return member_id if isinstance(member_id, int) else None


def _time_entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw time entry into a compact summary."""

    member = entry.get("member") or {}
    work_type = entry.get("workType") or {}
    work_role = entry.get("workRole") or {}
    location = entry.get("location") or {}
    return {
        "id": entry.get("id"),
        "member": member.get("identifier") or member.get("name"),
        "timeStart": entry.get("timeStart"),
        "timeEnd": entry.get("timeEnd"),
        "actualHours": entry.get("actualHours"),
        "hoursDeduct": entry.get("hoursDeduct"),
        "locationId": entry.get("locationId") or location.get("id"),
        "location": location.get("name"),
        "billableOption": entry.get("billableOption"),
        "workType": work_type.get("name"),
        "workRole": work_role.get("name"),
        "notes": entry.get("notes"),
        "internalNotes": entry.get("internalNotes"),
    }


def _schedule_entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw schedule entry into a compact summary."""

    member = entry.get("member") or {}
    schedule_type = entry.get("type") or {}
    status = entry.get("status") or {}
    return {
        "id": entry.get("id"),
        "ticketId": entry.get("objectId"),
        "name": entry.get("name"),
        "member": member.get("identifier") or member.get("name"),
        "memberId": member.get("id"),
        "type": schedule_type.get("name") or schedule_type.get("id"),
        "dateStart": entry.get("dateStart"),
        "dateEnd": entry.get("dateEnd"),
        "hours": entry.get("hours"),
        "done": entry.get("doneFlag"),
        "acknowledged": entry.get("acknowledgedFlag"),
        "owner": entry.get("ownerFlag"),
        "status": status.get("name"),
        "closeDate": entry.get("closeDate"),
    }


def _sla_risk_summary(ticket: dict[str, Any]) -> dict[str, Any]:
    """Normalize a slim SLA-risk ticket record into a compact result shape."""

    risk = ticket.get("_slaRisk") or {}
    return {
        "id": ticket.get("id"),
        "summary": ticket.get("summary"),
        "board": (ticket.get("board") or {}).get("name"),
        "status": (ticket.get("status") or {}).get("name"),
        "company": (ticket.get("company") or {}).get("name"),
        "owner": (ticket.get("owner") or {}).get("name"),
        "priority": (ticket.get("priority") or {}).get("name"),
        "sla": (ticket.get("sla") or {}).get("name"),
        "slaStatus": ticket.get("slaStatus"),
        "stage": risk.get("stage"),
        "minutesToBreach": risk.get("minutesToBreach"),
        "breachAt": risk.get("breachAt"),
        "isInSla": ticket.get("isInSla"),
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


def _find_by_id(records: list[dict[str, Any]], record_id: int) -> dict[str, Any] | None:
    """Return the first record whose id matches the provided id."""

    for record in records:
        if record.get("id") == record_id:
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


def _sorted_present_ids(records: list[dict[str, Any]]) -> list[str]:
    """Collect a sorted list of id values from raw API records."""

    values: list[int] = []
    for record in records:
        value = record.get("id")
        if isinstance(value, int):
            values.append(value)
    return [str(value) for value in sorted(values)]


def _parse_iso_timestamp(value: str, field_name: str) -> None:
    """Validate a timestamp string early so tool errors stay readable."""

    candidate = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ConnectWiseError(
            f"{field_name} must be an ISO-8601 timestamp, for example 2026-04-20T15:30:00Z."
        ) from exc


async def _validate_member_identifier(client: ConnectWiseClient, member_identifier: str) -> None:
    """Ensure a ConnectWise member identifier exists before assignment-style writes."""

    members = await client.search_members(identifier=member_identifier, inactive=False, page_size=100)
    member = _find_by_name(members, member_identifier, field="identifier")
    if member is None:
        valid_names = _sorted_present_strings(members, field="identifier")
        suggestion = f" Nearby matches: {', '.join(valid_names)}" if valid_names else ""
        raise ConnectWiseError(
            f"Unknown member_identifier '{member_identifier}'. Call search_members first and use the exact identifier.{suggestion}"
        )


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
    status: str | None = None,
    status_id: int | None = None,
) -> None:
    """Ensure a status exists on the chosen board before patching a ticket."""

    if status and status_id is not None:
        raise ConnectWiseError("Provide either status or status_id, not both.")
    statuses = await client.get_board_statuses(board_id)
    if status and _find_by_name(statuses, status) is None:
        valid_names = _sorted_present_strings(statuses)
        raise ConnectWiseError(
            f"Status '{status}' is not valid for board '{board_name}'. "
            f"Call get_board_statuses or get_board_lookup first. Valid statuses: {', '.join(valid_names)}"
        )
    if status_id is not None and _find_by_id(statuses, status_id) is None:
        valid_ids = _sorted_present_ids(statuses)
        raise ConnectWiseError(
            f"status_id '{status_id}' is not valid for board '{board_name}'. "
            f"Call get_board_statuses first. Valid status ids: {', '.join(valid_ids)}"
        )


async def _validate_ticket_classifications(
    client: ConnectWiseClient,
    *,
    ticket: dict[str, Any],
    board: str | None,
    board_id: int | None,
    status: str | None,
    status_id: int | None,
    type_name: str | None,
    type_id: int | None,
    sub_type_name: str | None,
    subtype_id: int | None,
    item_name: str | None,
    item_id: int | None,
    team: str | None,
    team_id: int | None,
) -> None:
    """Preflight board-scoped classification values so write errors stay actionable."""

    if board and board_id is not None:
        raise ConnectWiseError("Provide either board or board_id, not both.")
    if status and status_id is not None:
        raise ConnectWiseError("Provide either status or status_id, not both.")
    if type_name and type_id is not None:
        raise ConnectWiseError("Provide either type_name or type_id, not both.")
    if sub_type_name and subtype_id is not None:
        raise ConnectWiseError("Provide either sub_type_name or subtype_id, not both.")
    if item_name and item_id is not None:
        raise ConnectWiseError("Provide either item_name or item_id, not both.")
    if team and team_id is not None:
        raise ConnectWiseError("Provide either team or team_id, not both.")

    current_board = ticket.get("board") or {}
    board_record = (
        await _resolve_board(client, board)
        if board
        else {
            "id": board_id if board_id is not None else current_board.get("id"),
            "name": current_board.get("name"),
        }
    )
    resolved_board_id = board_record.get("id")
    board_name = str(board_record.get("name") or f"id {resolved_board_id}")
    if resolved_board_id is None:
        raise ConnectWiseError(
            "Could not determine the ticket's board for validation. Call get_ticket first or provide board_id or a valid board name."
        )

    if status or status_id is not None:
        await _validate_ticket_status(
            client,
            board_id=resolved_board_id,
            board_name=board_name,
            status=status,
            status_id=status_id,
        )

    teams = await client.get_board_teams(resolved_board_id)
    if team and _find_by_name(teams, team) is None:
        valid_names = _sorted_present_strings(teams)
        raise ConnectWiseError(
            f"Team '{team}' is not valid for board '{board_name}'. "
            f"Call get_board_lookup first. Valid teams: {', '.join(valid_names)}"
        )
    if team_id is not None and _find_by_id(teams, team_id) is None:
        valid_ids = _sorted_present_ids(teams)
        raise ConnectWiseError(
            f"team_id '{team_id}' is not valid for board '{board_name}'. "
            f"Call get_board_lookup first. Valid team ids: {', '.join(valid_ids)}"
        )

    current_type = ticket.get("type") or {}
    current_sub_type = ticket.get("subType") or {}
    effective_type_name = type_name or current_type.get("name")
    effective_type_id = type_id if type_id is not None else current_type.get("id")
    effective_sub_type_name = sub_type_name or current_sub_type.get("name")
    effective_subtype_id = subtype_id if subtype_id is not None else current_sub_type.get("id")

    if not any([type_name, type_id, sub_type_name, subtype_id, item_name, item_id]):
        return

    board_types = await client.get_board_types(resolved_board_id)
    type_record = None
    if isinstance(effective_type_id, int):
        type_record = _find_by_id(board_types, effective_type_id)
        if type_record is None:
            valid_ids = _sorted_present_ids(board_types)
            raise ConnectWiseError(
                f"type_id '{effective_type_id}' is not valid for board '{board_name}'. "
                f"Call get_board_types first. Valid type ids: {', '.join(valid_ids)}"
            )
    elif effective_type_name:
        type_record = _find_by_name(board_types, effective_type_name)
        if type_record is None:
            valid_names = _sorted_present_strings(board_types)
            raise ConnectWiseError(
                f"Type '{effective_type_name}' is not valid for board '{board_name}'. "
                f"Call get_board_lookup first. Valid types: {', '.join(valid_names)}"
            )
    elif sub_type_name or subtype_id is not None or item_name or item_id is not None:
        raise ConnectWiseError(
            "A valid type_id or type_name is required before setting subtype or item. "
            "Call get_ticket_type_hierarchy first and choose type, then subtype, then item."
        )

    subtype_record = None
    effective_type_label = type_record.get("name") or type_record.get("id") if type_record else effective_type_name
    if isinstance(effective_subtype_id, int):
        if type_record is None:
            raise ConnectWiseError(
                "Could not resolve the ticket type needed to validate subtype_id. "
                "Call get_ticket_type_hierarchy first and choose a valid type."
            )
        subtypes = await client.get_board_subtypes(resolved_board_id, type_record["id"])
        subtype_record = _find_by_id(subtypes, effective_subtype_id)
        if subtype_record is None:
            valid_ids = _sorted_present_ids(subtypes)
            raise ConnectWiseError(
                f"subtype_id '{effective_subtype_id}' is not valid for board '{board_name}' and type '{effective_type_label}'. "
                f"Call get_board_subtypes first. Valid subtype ids: {', '.join(valid_ids)}"
            )
    elif effective_sub_type_name:
        if type_record is None:
            raise ConnectWiseError(
                "Could not resolve the ticket type needed to validate sub_type_name. "
                "Call get_ticket or get_board_lookup first and choose a valid type."
            )
        subtypes = await client.get_board_subtypes(resolved_board_id, type_record["id"])
        subtype_record = _find_by_name(subtypes, effective_sub_type_name)
        if subtype_record is None:
            valid_names = _sorted_present_strings(subtypes)
            raise ConnectWiseError(
                f"Subtype '{effective_sub_type_name}' is not valid for board '{board_name}' and type '{effective_type_label}'. "
                f"Call get_board_lookup or get_board_subtypes first. Valid subtypes: {', '.join(valid_names)}"
            )
    elif item_name or item_id is not None:
        raise ConnectWiseError(
            "A valid subtype_id or sub_type_name is required before setting item. "
            "Call get_ticket_type_hierarchy first and choose type, then subtype, then item."
        )

    effective_sub_type_label = (
        subtype_record.get("name") or subtype_record.get("id") if subtype_record else effective_sub_type_name
    )
    if item_id is not None:
        if type_record is None or subtype_record is None:
            raise ConnectWiseError(
                "Could not resolve the ticket type/subtype needed to validate item_id. "
                "Call get_ticket_type_hierarchy first and choose a valid hierarchy."
            )
        items = await client.get_board_items(resolved_board_id, type_record["id"], subtype_record["id"])
        if _find_by_id(items, item_id) is None:
            valid_ids = _sorted_present_ids(items)
            raise ConnectWiseError(
                f"item_id '{item_id}' is not valid for board '{board_name}', type '{effective_type_label}', and subtype '{effective_sub_type_label}'. "
                f"Call get_board_items first. Valid item ids: {', '.join(valid_ids)}"
            )
    elif item_name:
        if type_record is None or subtype_record is None:
            raise ConnectWiseError(
                "Could not resolve the ticket type/subtype needed to validate item_name. "
                "Call get_ticket or get_board_lookup first and choose a valid hierarchy."
            )
        items = await client.get_board_items(resolved_board_id, type_record["id"], subtype_record["id"])
        if _find_by_name(items, item_name) is None:
            valid_names = _sorted_present_strings(items)
            raise ConnectWiseError(
                f"Item '{item_name}' is not valid for board '{board_name}', type '{effective_type_label}', and subtype '{effective_sub_type_label}'. "
                f"Call get_board_lookup or get_board_items first. Valid items: {', '.join(valid_names)}"
            )


async def _validate_time_entry_inputs(
    client: ConnectWiseClient,
    *,
    member_identifier: str,
    time_start: str,
    time_end: str | None,
    location_id: int | None,
    work_type: str | None,
    work_role: str | None,
) -> None:
    """Preflight member and work values for clearer agent-facing time-entry errors."""

    _parse_iso_timestamp(time_start, "time_start")
    if time_end:
        _parse_iso_timestamp(time_end, "time_end")

    await _validate_member_identifier(client, member_identifier)

    if location_id is not None:
        locations = await client.list_locations(inactive=False, page_size=100)
        if not any(location.get("id") == location_id for location in locations):
            valid_ids = sorted([
                candidate_id
                for location in locations
                for candidate_id in [location.get("id")]
                if isinstance(candidate_id, int)
            ])
            suggestion = f" Valid location ids: {', '.join(str(item) for item in valid_ids)}" if valid_ids else ""
            raise ConnectWiseError(
                f"Unknown location_id '{location_id}'. Call list_locations first and use an allowed numeric location id.{suggestion}"
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


@mcp.tool(description="Get a single ConnectWise service ticket by numeric id. Use this before update_ticket_status or update_ticket_classifications when you need the current board, status, type, subtype, item, team, or summary first.")
async def get_ticket(ticket_id: int) -> dict[str, Any]:
    """Fetch one ticket and include a compact summary alongside the raw payload."""

    client = ConnectWiseClient()
    ticket = await client.get_ticket(ticket_id)
    return {"ok": True, "data": ticket, "summary": _ticket_summary(ticket)}


@mcp.tool(description="Get a ticket with summary, description, notes, and time entries in one call. Use this when an agent needs the current ticket state and recent activity before deciding what write tool to call next.")
async def get_ticket_bundle(
    ticket_id: int,
    notes_page_size: int = 50,
    time_entries_page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Fetch a ticket together with its notes and time entries in one call.

    Args:
        ticket_id: Numeric service ticket id.
        notes_page_size: Max notes to fetch for the bundle.
        time_entries_page_size: Max time entries to fetch for the bundle.
        include_raw: When true, include raw ticket, note, and time-entry payloads.

    Returns:
        A combined payload containing normalized summaries plus raw API data.
    """

    client = ConnectWiseClient()
    ticket = await client.get_ticket(ticket_id)
    notes = await client.get_ticket_notes(ticket_id, page_size=notes_page_size)
    time_entries = await client.get_ticket_time_entries(ticket_id, page_size=time_entries_page_size)

    return {
        "ok": True,
        "ticket": _with_optional_raw({
            "summary": _ticket_summary(ticket),
            "description": _ticket_description(ticket, notes),
        }, ticket, include_raw=include_raw),
        "notes": _with_optional_raw({
            "count": len(notes),
            "data": [_note_summary(note) for note in notes],
        }, notes, include_raw=include_raw),
        "timeEntries": _with_optional_raw({
            "count": len(time_entries),
            "data": [_time_entry_summary(entry) for entry in time_entries],
        }, time_entries, include_raw=include_raw),
    }



@mcp.tool(description="Lookup configuration items for a ticket. Returns configurations already attached to the ticket plus configurations assigned to the ticket contact. Use this before attaching a configuration item.")
async def get_ticket_configuration_lookup(
    ticket_id: int,
    page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Fetch configuration references attached to a ticket and configs tied to the ticket contact."""

    client = ConnectWiseClient()
    ticket = await client.get_ticket(ticket_id)
    attached_refs = await client.get_ticket_configurations(ticket_id, page_size=page_size)

    hydrated_attached: list[dict[str, Any]] = []
    for reference in attached_refs:
        reference_id = reference.get("id")
        if isinstance(reference_id, int):
            hydrated_attached.append(await client.get_company_configuration(reference_id))

    contact = ticket.get("contact") or {}
    contact_id = contact.get("id")
    contact_configurations: list[dict[str, Any]] = []
    if isinstance(contact_id, int):
        contact_configurations = await client.search_company_configurations(
            contact_id=contact_id,
            page_size=page_size,
        )

    return {
        "ok": True,
        "ticketId": ticket_id,
        "ticket": _ticket_summary(ticket),
        "attached": _with_optional_raw({
            "count": len(attached_refs),
            "references": [_configuration_reference_summary(reference) for reference in attached_refs],
            "data": [_configuration_summary(configuration) for configuration in hydrated_attached],
        }, {"references": attached_refs, "configurations": hydrated_attached}, include_raw=include_raw),
        "contactConfigurations": _with_optional_raw({
            "contactId": contact_id,
            "count": len(contact_configurations),
            "data": [_configuration_summary(configuration) for configuration in contact_configurations],
        }, contact_configurations, include_raw=include_raw),
    }


@mcp.tool(description="Lookup company configurations and suggest which configuration item best matches a username. Required: company_id or ticket_id. If username is omitted with ticket_id, the tool derives candidates from the ticket contact and contact configurations.")
async def suggest_company_configuration_for_username(
    company_id: int | None = None,
    ticket_id: int | None = None,
    username: str | None = None,
    active: bool = True,
    page_size: int = 100,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Suggest the best company configuration to attach based on username-like fields."""

    if company_id is None and ticket_id is None:
        raise ConnectWiseError("Provide company_id or ticket_id.")

    client = ConnectWiseClient()
    ticket: dict[str, Any] | None = None
    contact_configurations: list[dict[str, Any]] = []
    if ticket_id is not None:
        ticket = await client.get_ticket(ticket_id)
        company_id = company_id or (ticket.get("company") or {}).get("id")
        contact_id = (ticket.get("contact") or {}).get("id")
        if isinstance(contact_id, int):
            contact_configurations = await client.search_company_configurations(
                contact_id=contact_id,
                active=active,
                page_size=page_size,
            )

    if not isinstance(company_id, int):
        raise ConnectWiseError("Could not determine company_id. Provide company_id or use a ticket with a company id.")

    usernames = [username.strip()] if isinstance(username, str) and username.strip() else []
    if ticket is not None:
        usernames.extend(_username_candidates(ticket, contact_configurations))
    usernames = list(dict.fromkeys(usernames))
    if not usernames:
        raise ConnectWiseError("Provide username, or use ticket_id for a ticket with contact username/email details.")

    configurations = await client.search_company_configurations(
        company_id=company_id,
        active=active,
        page_size=page_size,
    )
    scored = []
    for configuration in configurations:
        score = _configuration_match_score(configuration, usernames)
        scored.append({
            **_configuration_summary(configuration),
            "match": score,
        })
    scored.sort(key=lambda item: item["match"]["score"], reverse=True)

    suggestion = scored[0] if scored and scored[0]["match"]["score"] > 0 else None
    return _with_optional_raw({
        "ok": True,
        "ticketId": ticket_id,
        "companyId": company_id,
        "usernameCandidates": usernames,
        "suggestion": suggestion,
        "count": len(scored),
        "data": scored,
    }, configurations, include_raw=include_raw)

@mcp.tool(description="Search ConnectWise service tickets with simple business-facing filters like board, status, company, or summary text. Use this when you do not know the numeric ticket id yet.")
async def search_tickets(
    board: str | None = None,
    status: str | None = None,
    company: str | None = None,
    summary: str | None = None,
    page: int = 1,
    page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Search tickets and return both summaries and raw API data.

    Args:
        board: Optional board name filter.
        status: Optional status name filter.
        company: Optional partial company-name filter.
        summary: Optional partial summary filter.
        page: 1-based results page.
        page_size: Requested page size.
        include_raw: When true, include the full raw ConnectWise records.

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
    return _with_optional_raw({
        "ok": True,
        "count": len(tickets),
        "data": [_ticket_summary(ticket) for ticket in tickets],
    }, tickets, include_raw=include_raw)


@mcp.tool(description="List active tickets whose next SLA milestone (`Respond`, `Plan`, or `Resolve`) is due within the next `hours` window, default `4`. Use `board` for an exact board-name filter and `company` for a partial company-name filter. Returns near-breach tickets in `data`; set `include_overdue=true` to also return currently overdue active tickets in `overdue`. This is more efficient than broad raw ticket searches because it only fetches the fields needed for SLA risk checks.")
async def list_sla_risk_tickets(
    hours: int = 4,
    board: str | None = None,
    company: str | None = None,
    limit: int = 25,
    include_overdue: bool = False,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Return active tickets whose next SLA milestone is due soon.

    Args:
        hours: Size of the forward-looking breach window.
        board: Optional exact board-name filter.
        company: Optional partial company-name filter.
        limit: Maximum number of near-breach tickets to return.
        include_overdue: When true, also include currently overdue active tickets.
        include_raw: When true, attach the raw slim ticket records used for the result.

    Returns:
        A compact SLA-risk result set. ``count`` describes only the near-breach items
        returned in ``data``. When ``include_overdue`` is true, overdue items are
        returned separately in ``overdue`` with their own ``overdueCount``.
    """

    client = ConnectWiseClient()
    risk_sets = await client.list_tickets_about_to_breach(hours=hours, board=board, company=company)
    about_to_breach = risk_sets["about_to_breach"][: max(1, limit)]
    overdue = risk_sets["overdue"][: max(1, limit)] if include_overdue else []

    result = {
        "ok": True,
        "windowHours": max(1, hours),
        "count": len(about_to_breach),
        "data": [_sla_risk_summary(ticket) for ticket in about_to_breach],
    }
    if include_overdue:
        result["overdueCount"] = len(overdue)
        result["overdue"] = [_sla_risk_summary(ticket) for ticket in overdue]

    raw_payload = {"about_to_breach": about_to_breach}
    if include_overdue:
        raw_payload["overdue"] = overdue

    return _with_optional_raw(result, raw_payload, include_raw=include_raw)


@mcp.tool(description="Create a new ConnectWise service ticket. Expects company_id as a numeric id and board as an exact board name. Usually call search_companies first to find company_id, optional search_contacts to find contact_id, and list_boards if the board name is uncertain.")
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


@mcp.tool(description="Update basic ticket text fields. Required: ticket_id plus summary, initial_description, initial_description_lines, or initial_description_blocks. Use blocks for paragraph text; blocks join with blank lines. Summary updates patch the ticket. Initial description updates the oldest detail-description note or creates the first detail note.")
async def update_ticket_details(
    ticket_id: int,
    summary: str | None = None,
    initial_description: str | None = None,
    initial_description_lines: list[str] | None = None,
    initial_description_blocks: list[str] | None = None,
) -> dict[str, Any]:
    """Patch ticket subject/summary or initial description."""

    client = ConnectWiseClient()
    initial_description_text = _compose_text_field(
        "initial_description",
        initial_description,
        initial_description_lines,
        initial_description_blocks,
        required=False,
    )
    result = await client.update_ticket_details(
        ticket_id,
        summary=summary,
        initial_description=initial_description_text,
    )
    return {
        "ok": True,
        "ticketId": ticket_id,
        "updated": {
            "summary": summary,
            "initialDescription": initial_description_text,
        },
        "data": result,
    }


@mcp.tool(description="Update only the status of an existing ConnectWise service ticket. Expects status as a board-specific status name, not a status id. Recommended sequence: get_ticket to learn the board, then get_board_statuses or get_board_lookup to choose a valid status name, then call this tool.")
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


@mcp.tool(description="Add a note to a ticket. Required: ticket_id and text, text_lines, or text_blocks. Use text_blocks for paragraph text; blocks join with blank lines. Use internal=true for internal-only notes.")
async def add_ticket_note(
    ticket_id: int,
    text: str | None = None,
    internal: bool = True,
    text_lines: list[str] | None = None,
    text_blocks: list[str] | None = None,
) -> dict[str, Any]:
    """Add a note to a ticket and echo whether it was marked internal."""

    client = ConnectWiseClient()
    note_text = _compose_text_field("text", text, text_lines, text_blocks)
    result = await client.add_ticket_note(ticket_id, text=note_text or "", internal=internal)
    return {"ok": True, "data": result, "ticketId": ticket_id, "internal": internal}


@mcp.tool(description="Update a ticket note. Required: ticket_id, note_id, and text, text_lines, or text_blocks. Use text_blocks for paragraph text; blocks join with blank lines. Optional: internal.")
async def update_ticket_note(
    ticket_id: int,
    note_id: int,
    text: str | None = None,
    internal: bool | None = None,
    text_lines: list[str] | None = None,
    text_blocks: list[str] | None = None,
) -> dict[str, Any]:
    """Update a ticket note's text and optionally its internal flag."""

    client = ConnectWiseClient()
    note_text = _compose_text_field("text", text, text_lines, text_blocks)
    result = await client.update_ticket_note(ticket_id, note_id, text=note_text or "", internal=internal)
    return {
        "ok": True,
        "data": result,
        "ticketId": ticket_id,
        "noteId": note_id,
        "internal": internal,
    }


@mcp.tool(description="Delete an existing ConnectWise ticket note by note_id. Use get_ticket_notes first when you need to find the note id. This permanently removes the note from the ticket.")
async def delete_ticket_note(ticket_id: int, note_id: int) -> dict[str, Any]:
    """Delete a ticket note by id."""

    client = ConnectWiseClient()
    result = await client.delete_ticket_note(ticket_id, note_id)
    return {"ok": True, "data": result, "ticketId": ticket_id, "noteId": note_id}


MANAGED_INTERNAL_NOTE_KEY = "llm-ticket-summary"


@mcp.tool(description="Save the workflow-managed internal summary note on a ticket. Required: ticket_id and content, content_lines, or content_blocks. Use content_blocks for paragraph text; blocks join with blank lines. Use this for repeat LLM summaries instead of add_ticket_note.")
async def save_managed_internal_summary_note(
    ticket_id: int,
    content: str | None = None,
    content_lines: list[str] | None = None,
    content_blocks: list[str] | None = None,
) -> dict[str, Any]:
    """Idempotently create/update a workflow-managed internal note.

    This avoids ticket-update loops creating duplicate notes. Matching is scoped to
    internal notes with the same stable marker, and duplicate cleanup is limited to
    the ConnectWise member id found on those matching notes. If no marker exists yet,
    exact duplicate internal notes with the same content are also coalesced.
    """

    note_key = MANAGED_INTERNAL_NOTE_KEY
    client = ConnectWiseClient()
    content_text = _compose_text_field("content", content, content_lines, content_blocks)
    marker = _managed_note_marker(note_key)
    desired_text = _managed_note_text(note_key, content_text or "")
    desired_plain = _normalize_note_text(content_text)
    desired_full = _normalize_note_text(desired_text)

    page_size = getattr(getattr(client, "settings", None), "cw_max_page_size", 100)
    notes = await client.get_ticket_notes(
        ticket_id,
        page=1,
        page_size=page_size,
        order_by="dateCreated asc",
    )
    internal_notes = [note for note in notes if note.get("internalAnalysisFlag")]
    marker_matches = [note for note in internal_notes if marker in (note.get("text") or "")]
    exact_matches = [
        note
        for note in internal_notes
        if _normalize_note_text(note.get("text")) in {desired_plain, desired_full}
    ]
    candidates = marker_matches or exact_matches

    if not candidates:
        created = await client.add_ticket_note(ticket_id, desired_text, internal=True)
        return {
            "ok": True,
            "ticketId": ticket_id,
            "noteKey": note_key,
            "action": "created",
            "noteId": created.get("id"),
            "apiMemberId": _note_member_id(created),
            "deletedDuplicateNoteIds": [],
            "data": created,
        }

    api_member_id = _note_member_id(candidates[0])
    if api_member_id is not None:
        scoped_candidates = [note for note in candidates if _note_member_id(note) == api_member_id]
    else:
        scoped_candidates = candidates

    kept = scoped_candidates[0]
    kept_id = kept.get("id")
    if not isinstance(kept_id, int):
        raise ConnectWiseError("Could not determine the managed note id to update.")

    deleted_ids: list[int] = []
    for duplicate in scoped_candidates[1:]:
        note_id = duplicate.get("id")
        if isinstance(note_id, int):
            await client.delete_ticket_note(ticket_id, note_id)
            deleted_ids.append(note_id)

    updated = await client.update_ticket_note(ticket_id, kept_id, text=desired_text, internal=True)
    return {
        "ok": True,
        "ticketId": ticket_id,
        "noteKey": note_key,
        "action": "updated",
        "noteId": kept_id,
        "apiMemberId": api_member_id,
        "deletedDuplicateNoteIds": deleted_ids,
        "data": updated,
    }


@mcp.tool(description="Get notes for a ConnectWise service ticket. Use this when you only need notes. If you also need the ticket summary or time entries, prefer get_ticket_bundle to reduce tool hops.")
async def get_ticket_notes(
    ticket_id: int,
    page: int = 1,
    page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Return ticket notes as summaries plus raw API data."""

    client = ConnectWiseClient()
    notes = await client.get_ticket_notes(ticket_id, page=page, page_size=page_size)
    return _with_optional_raw({
        "ok": True,
        "count": len(notes),
        "data": [_note_summary(note) for note in notes],
    }, notes, include_raw=include_raw)


@mcp.tool(description="Get time entries linked to a ConnectWise service ticket. Use this when you only need time entries. If you also need the ticket summary or notes, prefer get_ticket_bundle to reduce tool hops.")
async def get_ticket_time_entries(
    ticket_id: int,
    page: int = 1,
    page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Return ticket time entries as summaries plus raw API data."""

    client = ConnectWiseClient()
    entries = await client.get_ticket_time_entries(ticket_id, page=page, page_size=page_size)
    return _with_optional_raw({
        "ok": True,
        "count": len(entries),
        "data": [_time_entry_summary(entry) for entry in entries],
    }, entries, include_raw=include_raw)


@mcp.tool(description="Safely update ticket classification fields. Required: ticket_id plus at least one field. Prefer ids where available: board_id, status_id, priority_id, type_id, subtype_id, item_id, team_id. Fetch lookup data first when ids are unknown. Critical order for hierarchy: choose type, then subtype, then item.")
async def update_ticket_classifications(
    ticket_id: int,
    status: str | None = None,
    status_id: int | None = None,
    priority: str | None = None,
    priority_id: int | None = None,
    board: str | None = None,
    board_id: int | None = None,
    type_name: str | None = None,
    type_id: int | None = None,
    sub_type_name: str | None = None,
    subtype_id: int | None = None,
    item_name: str | None = None,
    item_id: int | None = None,
    team: str | None = None,
    team_id: int | None = None,
    severity: str | None = None,
    impact: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Patch multiple ticket classification fields and echo the requested values.

    Any argument left as ``None`` is ignored, which makes the tool safe for partial updates.

    Prerequisites:
        Use ``get_ticket`` to inspect the current classification state.
        Provide either ``board`` as an exact board name or ``board_id`` as the numeric board id
        when moving a ticket to a different board. Supplying ``board_id`` avoids an extra
        board-name lookup when the id is already known.
        Use ``get_board_lookup`` or ``get_ticket_type_hierarchy`` to discover valid
        board-specific status, type, subtype, item, and team ids before patching. When
        changing hierarchy fields, choose ``type_id`` first, then ``subtype_id``,
        then ``item_id``. Do not treat ``item_id`` as an independent board-wide value.

    Returns:
        A tool response containing the requested field values and raw patch result.
    """

    client = ConnectWiseClient()
    ticket = await client.get_ticket(ticket_id)
    await _validate_ticket_classifications(
        client,
        ticket=ticket,
        board=board,
        board_id=board_id,
        status=status,
        status_id=status_id,
        type_name=type_name,
        type_id=type_id,
        sub_type_name=sub_type_name,
        subtype_id=subtype_id,
        item_name=item_name,
        item_id=item_id,
        team=team,
        team_id=team_id,
    )
    result = await client.update_ticket_classifications(
        ticket_id,
        status=status,
        status_id=status_id,
        priority=priority,
        priority_id=priority_id,
        board=board,
        board_id=board_id,
        type_name=type_name,
        type_id=type_id,
        sub_type_name=sub_type_name,
        subtype_id=subtype_id,
        item_name=item_name,
        item_id=item_id,
        team=team,
        team_id=team_id,
        severity=severity,
        impact=impact,
        source=source,
    )
    return {
        "ok": True,
        "ticketId": ticket_id,
        "updated": {
            "status": status,
            "statusId": status_id,
            "priority": priority,
            "priorityId": priority_id,
            "board": board,
            "boardId": board_id,
            "type": type_name,
            "typeId": type_id,
            "subType": sub_type_name,
            "subTypeId": subtype_id,
            "item": item_name,
            "itemId": item_id,
            "team": team,
            "teamId": team_id,
            "severity": severity,
            "impact": impact,
            "source": source,
        },
        "data": result,
    }


@mcp.tool(description="Unvalidated classification patch. Required: ticket_id plus at least one field. Prefer ids: board_id, status_id, priority_id, type_id, subtype_id, item_id, team_id. Use only when workflow data is already valid. Critical hierarchy order: type, then subtype, then item.")
async def patch_ticket_classifications_unvalidated(
    ticket_id: int,
    status: str | None = None,
    status_id: int | None = None,
    priority: str | None = None,
    priority_id: int | None = None,
    board: str | None = None,
    board_id: int | None = None,
    type_name: str | None = None,
    type_id: int | None = None,
    sub_type_name: str | None = None,
    subtype_id: int | None = None,
    item_name: str | None = None,
    item_id: int | None = None,
    team: str | None = None,
    team_id: int | None = None,
    severity: str | None = None,
    impact: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Patch ticket classifications without preflight reads.

    This is intentionally optimized for deterministic automation flows where the caller
    already has valid ConnectWise values, for example n8n jobs processing many tickets
    from a known board/status mapping. It avoids the safe tool's ``get_ticket`` and
    board lookup validation calls.

    Trade-off:
        Faster and cheaper, but ConnectWise returns the validation error directly if a
        supplied value is invalid for the ticket's board or hierarchy.
    """

    client = ConnectWiseClient()
    result = await client.update_ticket_classifications(
        ticket_id,
        status=status,
        status_id=status_id,
        priority=priority,
        priority_id=priority_id,
        board=board,
        board_id=board_id,
        type_name=type_name,
        type_id=type_id,
        sub_type_name=sub_type_name,
        subtype_id=subtype_id,
        item_name=item_name,
        item_id=item_id,
        team=team,
        team_id=team_id,
        severity=severity,
        impact=impact,
        source=source,
    )
    return {
        "ok": True,
        "ticketId": ticket_id,
        "validated": False,
        "updated": {
            "status": status,
            "statusId": status_id,
            "priority": priority,
            "priorityId": priority_id,
            "board": board,
            "boardId": board_id,
            "type": type_name,
            "typeId": type_id,
            "subType": sub_type_name,
            "subTypeId": subtype_id,
            "item": item_name,
            "itemId": item_id,
            "team": team,
            "teamId": team_id,
            "severity": severity,
            "impact": impact,
            "source": source,
        },
        "data": result,
    }


@mcp.tool(description="Unvalidated hierarchy-only classification patch. Required: ticket_id, board_id, and ids or names for type, subtype, and item. Prefer type_id, subtype_id, item_id. First call get_ticket_type_hierarchy and choose in order: type, then subtype, then item.")
async def patch_ticket_type_hierarchy_unvalidated(
    ticket_id: int,
    board_id: int,
    type_name: str | None = None,
    sub_type_name: str | None = None,
    item_name: str | None = None,
    type_id: int | None = None,
    subtype_id: int | None = None,
    item_id: int | None = None,
) -> dict[str, Any]:
    """Patch only board/type/subtype/item without preflight reads.

    This narrow tool is intended for high-volume automation surfaces where broad optional
    classification fields are inconvenient and the workflow already knows the exact
    board hierarchy values to apply.
    """

    client = ConnectWiseClient()
    if type_name is None and type_id is None:
        raise ConnectWiseError("Provide type_id or type_name.")
    if sub_type_name is None and subtype_id is None:
        raise ConnectWiseError("Provide subtype_id or sub_type_name.")
    if item_name is None and item_id is None:
        raise ConnectWiseError("Provide item_id or item_name.")
    result = await client.update_ticket_classifications(
        ticket_id,
        board_id=board_id,
        type_name=type_name,
        type_id=type_id,
        sub_type_name=sub_type_name,
        subtype_id=subtype_id,
        item_name=item_name,
        item_id=item_id,
    )
    return {
        "ok": True,
        "ticketId": ticket_id,
        "validated": False,
        "updated": {
            "boardId": board_id,
            "type": type_name,
            "typeId": type_id,
            "subType": sub_type_name,
            "subTypeId": subtype_id,
            "item": item_name,
            "itemId": item_id,
        },
        "data": result,
    }


@mcp.tool(description="Get schedule entries/resources assigned to a ConnectWise service ticket. Use this before rescheduling a resource or marking a scheduled resource done. Returns schedule_entry_id values needed by update_ticket_schedule_entry and mark_ticket_schedule_entry_done.")
async def get_ticket_schedule_entries(
    ticket_id: int,
    page: int = 1,
    page_size: int = 50,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Return schedule entries linked to a ticket."""

    client = ConnectWiseClient()
    entries = await client.get_ticket_schedule_entries(ticket_id, page=page, page_size=page_size)
    return _with_optional_raw({
        "ok": True,
        "count": len(entries),
        "data": [_schedule_entry_summary(entry) for entry in entries],
    }, entries, include_raw=include_raw)


@mcp.tool(description="Add/schedule a resource on a ConnectWise service ticket. Creates a Schedule entry linked to the ticket using member_identifier, optional date_start/date_end ISO timestamps, optional hours, and optional conflict override. Use search_members first if the exact member_identifier is unknown.")
async def add_ticket_schedule_entry(
    ticket_id: int,
    member_identifier: str,
    date_start: str | None = None,
    date_end: str | None = None,
    hours: float | None = None,
    name: str | None = None,
    done: bool = False,
    acknowledged: bool = False,
    owner: bool = False,
    allow_schedule_conflicts: bool = False,
) -> dict[str, Any]:
    """Create a ticket schedule entry/resource assignment."""

    if date_start:
        _parse_iso_timestamp(date_start, "date_start")
    if date_end:
        _parse_iso_timestamp(date_end, "date_end")
    client = ConnectWiseClient()
    await _validate_member_identifier(client, member_identifier)
    entry = await client.add_ticket_schedule_entry(
        ticket_id=ticket_id,
        member_identifier=member_identifier,
        date_start=date_start,
        date_end=date_end,
        hours=hours,
        name=name,
        done=done,
        acknowledged=acknowledged,
        owner=owner,
        allow_schedule_conflicts=allow_schedule_conflicts,
    )
    return {"ok": True, "ticketId": ticket_id, "data": entry, "summary": _schedule_entry_summary(entry)}


@mcp.tool(description="Reschedule or edit an existing ConnectWise schedule entry/resource assignment. Use get_ticket_schedule_entries first to find schedule_entry_id. Any omitted field is left unchanged; date_start/date_end are ISO timestamps.")
async def update_ticket_schedule_entry(
    schedule_entry_id: int,
    member_identifier: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    hours: float | None = None,
    name: str | None = None,
    done: bool | None = None,
    acknowledged: bool | None = None,
    owner: bool | None = None,
    allow_schedule_conflicts: bool | None = None,
) -> dict[str, Any]:
    """Patch an existing schedule entry."""

    if date_start:
        _parse_iso_timestamp(date_start, "date_start")
    if date_end:
        _parse_iso_timestamp(date_end, "date_end")
    client = ConnectWiseClient()
    if member_identifier:
        await _validate_member_identifier(client, member_identifier)
    entry = await client.update_schedule_entry(
        schedule_entry_id,
        member_identifier=member_identifier,
        date_start=date_start,
        date_end=date_end,
        hours=hours,
        name=name,
        done=done,
        acknowledged=acknowledged,
        owner=owner,
        allow_schedule_conflicts=allow_schedule_conflicts,
    )
    return {"ok": True, "scheduleEntryId": schedule_entry_id, "data": entry, "summary": _schedule_entry_summary(entry)}


@mcp.tool(description="Mark a scheduled ConnectWise ticket resource as done or not done. Use get_ticket_schedule_entries first to find schedule_entry_id. This patches doneFlag only.")
async def mark_ticket_schedule_entry_done(schedule_entry_id: int, done: bool = True) -> dict[str, Any]:
    """Patch only the schedule entry done flag."""

    client = ConnectWiseClient()
    entry = await client.update_schedule_entry(schedule_entry_id, done=done)
    return {"ok": True, "scheduleEntryId": schedule_entry_id, "done": done, "data": entry, "summary": _schedule_entry_summary(entry)}


@mcp.tool(description="Add a time entry against a ConnectWise service ticket. Expects member_identifier as the exact ConnectWise member identifier string, not numeric member id. work_type and work_role are exact names, not ids. Use notes_blocks/internal_notes_blocks for paragraph text; blocks join with blank lines. Recommended sequence: search_members, optional list_locations, list_work_types, list_work_roles, then add_ticket_time_entry.")
async def add_ticket_time_entry(
    ticket_id: int,
    member_identifier: str,
    time_start: str,
    time_end: str | None = None,
    hours_deduct: float | None = None,
    actual_hours: float | None = None,
    location_id: int | None = None,
    billable_option: str | None = None,
    work_type: str | None = None,
    work_role: str | None = None,
    notes: str | None = None,
    internal_notes: str | None = None,
    notes_lines: list[str] | None = None,
    internal_notes_lines: list[str] | None = None,
    notes_blocks: list[str] | None = None,
    internal_notes_blocks: list[str] | None = None,
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
        location_id: Optional numeric location id to force when ConnectWise location restrictions apply.
        billable_option: Optional billing behavior.
        work_type: Optional work type name.
        work_role: Optional work role name.
        notes: Optional customer-facing notes.
        internal_notes: Optional internal-only notes.
        notes_lines: Optional customer-facing note lines, joined with newlines.
        internal_notes_lines: Optional internal-only note lines, joined with newlines.
        notes_blocks: Optional customer-facing note blocks, joined with blank lines.
        internal_notes_blocks: Optional internal-only note blocks, joined with blank lines.
        email_resource_flag: Whether to email the resource.
        email_contact_flag: Whether to email the contact.
        email_cc_flag: Whether to email CC recipients.

    Prerequisites:
        Use ``search_members`` first if the member identifier is not already known.
        Use ``list_locations`` first if a restricted or non-default location may be required.
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
        location_id=location_id,
        work_type=work_type,
        work_role=work_role,
    )
    notes_text = _compose_text_field("notes", notes, notes_lines, notes_blocks, required=False)
    internal_notes_text = _compose_text_field(
        "internal_notes",
        internal_notes,
        internal_notes_lines,
        internal_notes_blocks,
        required=False,
    )
    entry = await client.add_time_entry(
        ticket_id=ticket_id,
        member_identifier=member_identifier,
        time_start=time_start,
        time_end=time_end,
        hours_deduct=hours_deduct,
        actual_hours=actual_hours,
        location_id=location_id,
        billable_option=billable_option,
        work_type=work_type,
        work_role=work_role,
        notes=notes_text,
        internal_notes=internal_notes_text,
        email_resource_flag=email_resource_flag,
        email_contact_flag=email_contact_flag,
        email_cc_flag=email_cc_flag,
    )
    return {"ok": True, "ticketId": ticket_id, "data": entry, "summary": _time_entry_summary(entry)}
