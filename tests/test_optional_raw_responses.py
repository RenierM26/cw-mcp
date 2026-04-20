from __future__ import annotations

from typing import Any

import pytest

from connectwise_manage_mcp.tools import companies as companies_module
from connectwise_manage_mcp.tools import contacts as contacts_module
from connectwise_manage_mcp.tools import lookups as lookups_module
from connectwise_manage_mcp.tools import tickets as tickets_module


class FakeClient:
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

    async def get_board_teams(self, board_id: int) -> list[dict[str, Any]]:
        return [{"id": 4, "name": "Helpdesk"}]

    async def search_tickets(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 12345, "summary": "VPN issue", "board": {"name": "Service Desk"}}]

    async def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        return {
            "id": ticket_id,
            "summary": "VPN issue",
            "board": {"name": "Service Desk"},
        }

    async def get_ticket_notes(self, ticket_id: int, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 10, "text": "Investigating"}]

    async def get_ticket_time_entries(self, ticket_id: int, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 20, "timeStart": "2026-04-20T15:30:00Z"}]


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


async def test_search_tickets_omits_raw_by_default(fake_client: FakeClient) -> None:
    result = await tickets_module.search_tickets(summary="VPN")

    assert "raw" not in result
    assert result["data"][0]["summary"] == "VPN issue"
