from __future__ import annotations

from typing import Any

import pytest

from connectwise_manage_mcp.connectwise.client import ConnectWiseError
from connectwise_manage_mcp.tools import tickets as tickets_module


class FakeClient:
    def __init__(self) -> None:
        self.updated_status: tuple[int, str] | None = None
        self.updated_classifications: dict[str, Any] | None = None
        self.added_time_entry: dict[str, Any] | None = None

    async def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        return {
            "id": ticket_id,
            "board": {"id": 12, "name": "Service Desk"},
            "type": {"name": "Incident"},
            "subType": {"name": "Remote Access"},
        }

    async def get_board_statuses(self, board_id: int) -> list[dict[str, Any]]:
        return [
            {"id": 1, "name": "New"},
            {"id": 2, "name": "In Progress"},
        ]

    async def update_ticket_status(self, ticket_id: int, status: str) -> dict[str, Any]:
        self.updated_status = (ticket_id, status)
        return {"ok": True}

    async def list_boards(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 12, "name": "Service Desk"}]

    async def get_board_teams(self, board_id: int) -> list[dict[str, Any]]:
        return [{"id": 4, "name": "Helpdesk"}]

    async def get_board_types(self, board_id: int) -> list[dict[str, Any]]:
        return [{"id": 3, "name": "Incident"}]

    async def get_board_subtypes(self, board_id: int, type_id: int) -> list[dict[str, Any]]:
        return [{"id": 9, "name": "Remote Access"}]

    async def get_board_items(self, board_id: int, type_id: int, subtype_id: int) -> list[dict[str, Any]]:
        return [{"id": 14, "name": "VPN"}]

    async def update_ticket_classifications(self, ticket_id: int, **kwargs: Any) -> dict[str, Any]:
        self.updated_classifications = {"ticket_id": ticket_id, **kwargs}
        return {"ok": True}

    async def search_members(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 1, "identifier": "helpdesk1"}]

    async def list_work_types(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 1, "name": "Remote Support"}]

    async def list_work_roles(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 1, "name": "Engineer"}]

    async def list_locations(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 7, "name": "HQ"}]

    async def add_time_entry(self, **kwargs: Any) -> dict[str, Any]:
        self.added_time_entry = kwargs
        return {
            "id": 77,
            "member": {"identifier": kwargs["member_identifier"]},
            "timeStart": kwargs["time_start"],
            "timeEnd": kwargs.get("time_end"),
            "actualHours": kwargs.get("actual_hours"),
            "hoursDeduct": kwargs.get("hours_deduct"),
            "locationId": kwargs.get("location_id"),
            "billableOption": kwargs.get("billable_option"),
            "workType": {"name": kwargs.get("work_type")},
            "workRole": {"name": kwargs.get("work_role")},
            "notes": kwargs.get("notes"),
            "internalNotes": kwargs.get("internal_notes"),
        }


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient()
    monkeypatch.setattr(tickets_module, "ConnectWiseClient", lambda: client)
    return client


async def test_update_ticket_status_rejects_unknown_status(fake_client: FakeClient) -> None:
    with pytest.raises(ConnectWiseError, match="Status 'Closed' is not valid for board 'Service Desk'"):
        await tickets_module.update_ticket_status(12345, "Closed")

    assert fake_client.updated_status is None


async def test_update_ticket_classifications_rejects_invalid_item_for_hierarchy(
    fake_client: FakeClient,
) -> None:
    with pytest.raises(
        ConnectWiseError,
        match="Item 'Router' is not valid for board 'Service Desk', type 'Incident', and subtype 'Remote Access'",
    ):
        await tickets_module.update_ticket_classifications(
            12345,
            type_name="Incident",
            sub_type_name="Remote Access",
            item_name="Router",
        )

    assert fake_client.updated_classifications is None


async def test_add_ticket_time_entry_rejects_invalid_member_identifier(
    fake_client: FakeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty_members(**kwargs: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(fake_client, "search_members", empty_members)

    with pytest.raises(ConnectWiseError, match="Unknown member_identifier 'wrong-user'"):
        await tickets_module.add_ticket_time_entry(
            ticket_id=12345,
            member_identifier="wrong-user",
            time_start="2026-04-20T15:30:00Z",
            work_type="Remote Support",
            work_role="Engineer",
        )

    assert fake_client.added_time_entry is None


async def test_add_ticket_time_entry_validates_timestamp_format(fake_client: FakeClient) -> None:
    with pytest.raises(ConnectWiseError, match="time_start must be an ISO-8601 timestamp"):
        await tickets_module.add_ticket_time_entry(
            ticket_id=12345,
            member_identifier="helpdesk1",
            time_start="20-04-2026 15:30",
            work_type="Remote Support",
            work_role="Engineer",
        )

    assert fake_client.added_time_entry is None


async def test_add_ticket_time_entry_rejects_invalid_location_id(fake_client: FakeClient) -> None:
    with pytest.raises(ConnectWiseError, match="Unknown location_id '99'"):
        await tickets_module.add_ticket_time_entry(
            ticket_id=12345,
            member_identifier="helpdesk1",
            time_start="2026-04-20T15:30:00Z",
            location_id=99,
            work_type="Remote Support",
            work_role="Engineer",
        )

    assert fake_client.added_time_entry is None


async def test_update_ticket_classifications_accepts_board_id_without_board_lookup(
    fake_client: FakeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_list_boards(**kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("list_boards should not be called when board_id is supplied")

    monkeypatch.setattr(fake_client, "list_boards", fail_list_boards)

    result = await tickets_module.update_ticket_classifications(
        12345,
        board_id=12,
        status="In Progress",
        type_name="Incident",
        sub_type_name="Remote Access",
        item_name="VPN",
    )

    assert result["ok"] is True
    assert result["updated"]["boardId"] == 12
    assert fake_client.updated_classifications is not None
    assert fake_client.updated_classifications["board_id"] == 12
    assert fake_client.updated_classifications["board"] is None


async def test_update_ticket_classifications_rejects_board_and_board_id(
    fake_client: FakeClient,
) -> None:
    with pytest.raises(ConnectWiseError, match="Provide either board or board_id, not both"):
        await tickets_module.update_ticket_classifications(12345, board="Service Desk", board_id=12)

    assert fake_client.updated_classifications is None


async def test_update_ticket_classifications_fast_skips_preflight_reads(
    fake_client: FakeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_get_ticket(ticket_id: int) -> dict[str, Any]:
        raise AssertionError("get_ticket should not be called by fast classification updates")

    async def fail_statuses(board_id: int) -> list[dict[str, Any]]:
        raise AssertionError("lookup validation should not run for fast classification updates")

    monkeypatch.setattr(fake_client, "get_ticket", fail_get_ticket)
    monkeypatch.setattr(fake_client, "get_board_statuses", fail_statuses)

    result = await tickets_module.update_ticket_classifications_fast(
        12345,
        board_id=12,
        status="In Progress",
        type_name="Incident",
    )

    assert result["ok"] is True
    assert result["validated"] is False
    assert fake_client.updated_classifications == {
        "ticket_id": 12345,
        "status": "In Progress",
        "priority": None,
        "priority_id": None,
        "board": None,
        "board_id": 12,
        "type_name": "Incident",
        "sub_type_name": None,
        "item_name": None,
        "team": None,
        "severity": None,
        "impact": None,
        "source": None,
    }


async def test_update_ticket_type_hierarchy_fast_uses_single_patch_surface(
    fake_client: FakeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_get_ticket(ticket_id: int) -> dict[str, Any]:
        raise AssertionError("get_ticket should not be called by the n8n hierarchy fast path")

    async def fail_list_boards(**kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("list_boards should not be called by the n8n hierarchy fast path")

    monkeypatch.setattr(fake_client, "get_ticket", fail_get_ticket)
    monkeypatch.setattr(fake_client, "list_boards", fail_list_boards)

    result = await tickets_module.update_ticket_type_hierarchy_fast(
        ticket_id=12345,
        board_id=65,
        type_name="Incident",
        sub_type_name="Software",
        item_name="Fix/Restore",
    )

    assert result["ok"] is True
    assert result["validated"] is False
    assert result["updated"] == {
        "boardId": 65,
        "type": "Incident",
        "subType": "Software",
        "item": "Fix/Restore",
    }
    assert fake_client.updated_classifications is not None
    assert fake_client.updated_classifications["ticket_id"] == 12345
    assert fake_client.updated_classifications["board_id"] == 65
    assert fake_client.updated_classifications["type_name"] == "Incident"
    assert fake_client.updated_classifications["sub_type_name"] == "Software"
    assert fake_client.updated_classifications["item_name"] == "Fix/Restore"
