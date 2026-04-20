from __future__ import annotations

from typing import Any

from connectwise_manage_mcp.app import mcp
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient


def _ticket_summary(ticket: dict[str, Any]) -> dict[str, Any]:
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


@mcp.tool(description="Get a single ConnectWise service ticket by id.")
async def get_ticket(ticket_id: int) -> dict[str, Any]:
    client = ConnectWiseClient()
    ticket = await client.get_ticket(ticket_id)
    return {"ok": True, "data": ticket, "summary": _ticket_summary(ticket)}


@mcp.tool(description="Get a ticket with summary, description, notes, and time entries in one call.")
async def get_ticket_bundle(
    ticket_id: int,
    notes_page_size: int = 50,
    time_entries_page_size: int = 50,
) -> dict[str, Any]:
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


@mcp.tool(description="Create a new ConnectWise service ticket.")
async def create_ticket(
    company_id: int,
    board: str,
    summary: str,
    initial_description: str,
    contact_id: int | None = None,
    priority: str | None = None,
) -> dict[str, Any]:
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


@mcp.tool(description="Update the status of an existing ConnectWise service ticket.")
async def update_ticket_status(ticket_id: int, status: str) -> dict[str, Any]:
    client = ConnectWiseClient()
    result = await client.update_ticket_status(ticket_id, status)
    return {"ok": True, "data": result, "ticketId": ticket_id, "newStatus": status}


@mcp.tool(description="Add a note to a ConnectWise service ticket.")
async def add_ticket_note(ticket_id: int, text: str, internal: bool = True) -> dict[str, Any]:
    client = ConnectWiseClient()
    result = await client.add_ticket_note(ticket_id, text=text, internal=internal)
    return {"ok": True, "data": result, "ticketId": ticket_id, "internal": internal}


@mcp.tool(description="Get notes for a ConnectWise service ticket.")
async def get_ticket_notes(ticket_id: int, page: int = 1, page_size: int = 50) -> dict[str, Any]:
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
    client = ConnectWiseClient()
    entries = await client.get_ticket_time_entries(ticket_id, page=page, page_size=page_size)
    return {
        "ok": True,
        "count": len(entries),
        "data": [_time_entry_summary(entry) for entry in entries],
        "raw": entries,
    }


@mcp.tool(description="Update ticket classification fields like status, priority, board, type, subtype, item, team, severity, impact, or source.")
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
    client = ConnectWiseClient()
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


@mcp.tool(description="Add a time entry against a ConnectWise service ticket.")
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
    client = ConnectWiseClient()
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
