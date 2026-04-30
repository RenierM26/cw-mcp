from __future__ import annotations

from typing import Any

import pytest

import connectwise_manage_mcp.tools.companies as companies_module
import connectwise_manage_mcp.tools.contacts as contacts_module
import connectwise_manage_mcp.tools.lookups as lookups_module
import connectwise_manage_mcp.tools.tickets as tickets_module


class FakeClient:
    def __init__(self) -> None:
        self.ticket: dict[str, Any] | None = None
        self.notes: list[dict[str, Any]] | None = None

    async def search_companies(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 1, "name": "Example Co", "identifier": "EXAMPLE"}]

    async def search_contacts(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 2, "name": "Jane Smith", "defaultEmailAddress": "jane@example.com"}]

    async def list_boards(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 12, "name": "Service Desk"}]

    async def get_board_statuses(self, board_id: int) -> list[dict[str, Any]]:
        return [{"id": 1, "name": "New", "board": {"name": "Service Desk"}}]

    async def get_board_types(self, board_id: int) -> list[dict[str, Any]]:
        return [{"id": 3, "name": "Incident"}]

    async def get_board_subtypes(self, board_id: int, type_id: int) -> list[dict[str, Any]]:
        return [{"id": 9, "name": "Remote Access"}]

    async def get_board_items(self, board_id: int, type_id: int, subtype_id: int) -> list[dict[str, Any]]:
        return [{"id": 14, "name": "VPN"}]

    async def get_board_teams(self, board_id: int) -> list[dict[str, Any]]:
        return [{"id": 4, "name": "Helpdesk"}]

    async def search_members(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "identifier": "member-001",
                "firstName": "Test",
                "lastName": "User",
                "officeEmail": "test.user@example.com",
                "inactiveFlag": False,
                "licenseClass": "F",
            }
        ]

    async def search_tickets(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 12345, "summary": "VPN issue", "board": {"name": "Service Desk"}}]

    async def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        if self.ticket is not None:
            return self.ticket
        return {
            "id": ticket_id,
            "summary": "VPN issue",
            "board": {"name": "Service Desk"},
        }

    async def get_ticket_notes(self, ticket_id: int, **kwargs: Any) -> list[dict[str, Any]]:
        if self.notes is not None:
            return self.notes
        return [{"id": 10, "text": "Investigating"}]

    async def get_ticket_time_entries(self, ticket_id: int, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 20, "timeStart": "2026-04-20T15:30:00Z"}]

    async def list_tickets_about_to_breach(self, **kwargs: Any) -> dict[str, list[dict[str, Any]]]:
        return {
            "about_to_breach": [
                {
                    "id": 42,
                    "summary": "VPN user locked out",
                    "board": {"name": "Service Desk"},
                    "status": {"name": "Assigned"},
                    "company": {"name": "Example Co"},
                    "owner": {"name": "Example Owner"},
                    "priority": {"name": "Priority 2 - High"},
                    "sla": {"name": "Standard SLA"},
                    "slaStatus": "Respond by today",
                    "isInSla": True,
                    "_slaRisk": {
                        "stage": "Respond",
                        "minutesToBreach": 45,
                        "breachAt": "2026-04-22T10:45:00Z",
                    },
                }
            ],
            "overdue": [],
        }


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient()
    monkeypatch.setattr(companies_module, "ConnectWiseClient", lambda: client)
    monkeypatch.setattr(contacts_module, "ConnectWiseClient", lambda: client)
    monkeypatch.setattr(lookups_module, "ConnectWiseClient", lambda: client)
    monkeypatch.setattr(tickets_module, "ConnectWiseClient", lambda: client)
    return client


async def test_search_companies_omits_raw_by_default(fake_client: FakeClient) -> None:
    result = await companies_module.search_companies(name="Example")

    assert "raw" not in result
    assert result["count"] == 1


async def test_search_contacts_includes_raw_when_requested(fake_client: FakeClient) -> None:
    result = await contacts_module.search_contacts(email="jane", include_raw=True)

    assert "raw" in result
    assert result["raw"][0]["id"] == 2


async def test_get_board_lookup_omits_raw_by_default(fake_client: FakeClient) -> None:
    result = await lookups_module.get_board_lookup(board_id=12)

    assert "raw" not in result
    assert result["statuses"][0]["name"] == "New"


async def test_get_ticket_bundle_includes_raw_only_when_requested(fake_client: FakeClient) -> None:
    lean = await tickets_module.get_ticket_bundle(ticket_id=12345)
    rich = await tickets_module.get_ticket_bundle(ticket_id=12345, include_raw=True)

    assert "raw" not in lean["ticket"]
    assert "raw" not in lean["notes"]
    assert "raw" not in lean["timeEntries"]

    assert "raw" in rich["ticket"]
    assert "raw" in rich["notes"]
    assert "raw" in rich["timeEntries"]


async def test_get_ticket_bundle_uses_direct_initial_description(fake_client: FakeClient) -> None:
    fake_client.ticket = {
        "id": 12345,
        "summary": "VPN issue",
        "initialDescription": "Direct initial description",
        "recordType": "ServiceTicket",
    }
    fake_client.notes = [
        {"id": 10, "text": "Detail note description", "detailDescriptionFlag": True},
    ]

    result = await tickets_module.get_ticket_bundle(ticket_id=12345)

    assert result["ticket"]["description"] == "Direct initial description"


async def test_get_ticket_bundle_falls_back_to_oldest_detail_description_note(
    fake_client: FakeClient,
) -> None:
    fake_client.ticket = {
        "id": 12345,
        "summary": "VPN issue",
        "recordType": "ServiceTicket",
    }
    fake_client.notes = [
        {
            "id": 11,
            "text": "Newer detail description",
            "detailDescriptionFlag": True,
            "dateCreated": "2026-04-20T16:00:00Z",
        },
        {
            "id": 10,
            "text": "Oldest detail description",
            "detailDescriptionFlag": True,
            "dateCreated": "2026-04-20T15:00:00Z",
        },
        {
            "id": 12,
            "text": "Internal update",
            "detailDescriptionFlag": False,
            "dateCreated": "2026-04-20T14:00:00Z",
        },
    ]

    result = await tickets_module.get_ticket_bundle(ticket_id=12345)

    assert result["ticket"]["description"] == "Oldest detail description"


async def test_get_ticket_bundle_does_not_use_record_type_as_description(
    fake_client: FakeClient,
) -> None:
    fake_client.ticket = {
        "id": 12345,
        "summary": "VPN issue",
        "recordType": "ServiceTicket",
    }
    fake_client.notes = [{"id": 10, "text": "Investigating", "detailDescriptionFlag": False}]

    result = await tickets_module.get_ticket_bundle(ticket_id=12345)

    assert result["ticket"]["description"] is None


async def test_search_tickets_omits_raw_by_default(fake_client: FakeClient) -> None:
    result = await tickets_module.search_tickets(summary="VPN")

    assert "raw" not in result
    assert result["data"][0]["summary"] == "VPN issue"


async def test_list_sla_risk_tickets_includes_raw_when_requested(fake_client: FakeClient) -> None:
    result = await tickets_module.list_sla_risk_tickets(include_raw=True)

    assert result["count"] == 1
    assert result["data"][0]["stage"] == "Respond"
    assert result["raw"]["about_to_breach"][0]["id"] == 42


async def test_search_members_handles_string_license_class(fake_client: FakeClient) -> None:
    result = await lookups_module.search_members(name="example")

    assert result["count"] == 1
    assert result["data"][0]["identifier"] == "member-001"
    assert result["data"][0]["licenseClass"] == "F"


async def test_get_ticket_type_hierarchy_returns_only_type_tree(fake_client: FakeClient) -> None:
    result = await lookups_module.get_ticket_type_hierarchy(board_id=12, type_id=3, subtype_id=9)

    assert result["ok"] is True
    assert result["boardId"] == 12
    assert result["typeId"] == 3
    assert result["subtypeId"] == 9
    assert "statuses" not in result
    assert "teams" not in result
    assert result["types"] == [{"id": 3, "name": "Incident", "inactive": None, "defaultFlag": None}]
    assert result["subtypes"] == [{"id": 9, "name": "Remote Access", "inactive": None, "defaultFlag": None}]
    assert result["items"] == [{"id": 14, "name": "VPN", "inactive": None, "defaultFlag": None}]
    assert result["nextStep"] == "choose type_id, sub_type_id, and item_id, then call patch_ticket_type_hierarchy_unvalidated"
