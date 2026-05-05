from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

import pytest

from connectwise_manage_mcp.config import get_settings
from connectwise_manage_mcp.connectwise import client as client_module
from connectwise_manage_mcp.connectwise.client import ConnectWiseClient, ConnectWiseError


class FakeResponse:
    def __init__(self, status_code: int, json_data: Any = None, text: str = "", content: bytes | None = None) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.content = content if content is not None else (b"" if json_data is None else b"json")

    def json(self) -> Any:
        return self._json_data


class FakeAsyncClient:
    def __init__(self, *, timeout: float, handler: Callable[..., FakeResponse], calls: list[dict[str, Any]]) -> None:
        self.timeout = timeout
        self._handler = handler
        self._calls = calls

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self._calls.append({"method": method, "url": url, **kwargs})
        return self._handler(method, url, **kwargs)


@pytest.fixture(autouse=True)
def configured_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    env = {
        "CW_BASE_URL": "https://cw.example.com/v4_6_release/apis/3.0",
        "CW_COMPANY_ID": "exampleco",
        "CW_PUBLIC_KEY": "public-key",
        "CW_PRIVATE_KEY": "private-key",
        "CW_CLIENT_ID": "client-id",
        "CW_PAGE_SIZE": "50",
        "CW_MAX_PAGE_SIZE": "100",
        "CW_TIMEOUT_SECONDS": "12",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def install_fake_async_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[..., FakeResponse],
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def factory(*, timeout: float) -> FakeAsyncClient:
        return FakeAsyncClient(timeout=timeout, handler=handler, calls=calls)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", factory)
    return calls


async def test_request_builds_headers_and_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data={"ok": True, "url": url}),
    )

    client = ConnectWiseClient()
    result = await client.get_ticket(12345)

    assert result == {"ok": True, "url": "https://cw.example.com/v4_6_release/apis/3.0/service/tickets/12345"}
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/service/tickets/12345")
    assert calls[0]["headers"]["clientId"] == "client-id"
    assert calls[0]["headers"]["Authorization"].startswith("Basic ")


async def test_request_returns_ok_for_empty_success(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(204, json_data=None, content=b""),
    )

    client = ConnectWiseClient()

    assert await client.update_ticket_status(12345, "Closed") == {"ok": True}


async def test_request_raises_clean_error_for_api_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(500, text="server exploded", content=b"server exploded"),
    )

    client = ConnectWiseClient()

    with pytest.raises(ConnectWiseError, match="ConnectWise API error 500: server exploded"):
        await client.healthcheck()


async def test_search_tickets_builds_expected_conditions_and_caps_page_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data=[]),
    )

    client = ConnectWiseClient()
    await client.search_tickets(
        board='Service "Desk"',
        status="New",
        company="Example Co",
        summary="VPN",
        page=2,
        page_size=500,
    )

    params = calls[0]["params"]
    assert params["page"] == 2
    assert params["pageSize"] == 100
    assert params["orderBy"] == "lastUpdated desc"
    assert params["conditions"] == (
        'board/name="Service \\\"Desk\\\"" and '
        'status/name="New" and '
        'company/name contains "Example Co" and '
        'summary contains "VPN"'
    )


async def test_search_tickets_clamps_negative_page_size_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data=[]),
    )

    client = ConnectWiseClient()
    await client.search_tickets(summary="VPN", page_size=-5)

    assert calls[0]["params"]["pageSize"] == 1


async def test_list_tickets_about_to_breach_uses_slim_fields_and_filters_active_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = client_module.dt.datetime.now(client_module.dt.timezone.utc).replace(microsecond=0)

    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(
            200,
            json_data=(
                [
                    {
                        "id": 1,
                        "summary": "VPN user locked out",
                        "board": {"name": "Service Desk"},
                        "status": {"name": "Assigned"},
                        "company": {"name": "Example Co"},
                        "owner": {"name": "Example Owner"},
                        "priority": {"name": "Priority 2 - High"},
                        "sla": {"name": "Standard SLA"},
                        "slaStatus": "Respond soon",
                        "respondByGoalUTC": (now + client_module.dt.timedelta(minutes=45)).isoformat().replace("+00:00", "Z"),
                    },
                    {
                        "id": 2,
                        "summary": "Old closed ticket",
                        "board": {"name": "Service Desk"},
                        "status": {"name": ">Closed"},
                        "company": {"name": "Example Co"},
                        "resolutionGoalUTC": (now + client_module.dt.timedelta(minutes=20)).isoformat().replace("+00:00", "Z"),
                    },
                    {
                        "id": 3,
                        "summary": "Already overdue",
                        "board": {"name": "Service Desk"},
                        "status": {"name": "In Progress"},
                        "company": {"name": "Example Co"},
                        "resolutionGoalUTC": (now - client_module.dt.timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
                    },
                ]
                if kwargs["params"]["page"] == 1
                else []
            ),
        ),
    )

    client = ConnectWiseClient()
    result = await client.list_tickets_about_to_breach(hours=2, board="Service Desk", company="Example")

    assert [ticket["id"] for ticket in result["about_to_breach"]] == [1]
    assert [ticket["id"] for ticket in result["overdue"]] == [3]
    assert result["about_to_breach"][0]["_slaRisk"]["stage"] == "Respond"
    assert calls[0]["params"]["conditions"] == (
        'closedFlag=false and board/name="Service Desk" and company/name contains "Example"'
    )
    assert calls[0]["params"]["fields"] == (
        "id,summary,closedFlag,isInSla,slaStatus,board/name,status/name,company/name,owner/name,priority/name,sla/name,"
        "respondByGoalUTC,dateResponded,resplanGoalUTC,dateResplan,resolutionGoalUTC"
    )


async def test_get_ticket_configurations_calls_service_ticket_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data=[{"id": 77, "deviceIdentifier": "LAPTOP-77"}]),
    )

    client = ConnectWiseClient()
    result = await client.get_ticket_configurations(12345, page=2, page_size=500)

    assert result == [{"id": 77, "deviceIdentifier": "LAPTOP-77"}]
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/service/tickets/12345/configurations")
    assert calls[0]["params"] == {"page": 2, "pageSize": 100}


async def test_add_ticket_configuration_posts_configuration_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(201, json_data={"id": 77, "deviceIdentifier": "LAPTOP-77"}),
    )

    client = ConnectWiseClient()
    result = await client.add_ticket_configuration(
        12345,
        configuration_id=77,
        device_identifier="LAPTOP-77",
    )

    assert result == {"id": 77, "deviceIdentifier": "LAPTOP-77"}
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/service/tickets/12345/configurations")
    assert calls[0]["json"] == {"id": 77, "deviceIdentifier": "LAPTOP-77"}


async def test_search_company_configurations_builds_username_conditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data=[]),
    )

    client = ConnectWiseClient()
    await client.search_company_configurations(
        company_id=12,
        contact_id=34,
        username='jane"s',
        active=True,
        page_size=10,
    )

    params = calls[0]["params"]
    assert calls[0]["url"].endswith("/company/configurations")
    assert params["page"] == 1
    assert params["pageSize"] == 10
    assert params["orderBy"] == "name asc"
    assert params["conditions"] == (
        'company/id=12 and contact/id=34 and '
        '(lastLoginName contains "jane\\"s" or name contains "jane\\"s" or deviceIdentifier contains "jane\\"s") and '
        'activeFlag=true'
    )

async def test_search_members_builds_expected_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data=[]),
    )

    client = ConnectWiseClient()
    await client.search_members(identifier='member"-001', name="example", inactive=False, page=2, page_size=5)

    params = calls[0]["params"]
    assert params["page"] == 1
    assert params["pageSize"] == 50
    assert params["orderBy"] == "identifier asc"
    assert params["conditions"] == (
        'identifier contains "member\\"-001" and '
        '(firstName contains "example" or lastName contains "example" or officeEmail contains "example")'
    )


async def test_search_members_raises_clean_error_for_non_list_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(
            200,
            json_data={"code": "BadRequest", "message": "Invalid conditions expression"},
        ),
    )

    client = ConnectWiseClient()

    with pytest.raises(
        ConnectWiseError,
        match=r"unexpected non-list response for GET /system/members: .*Invalid conditions expression",
    ):
        await client.search_members(name="example")


async def test_search_contacts_uses_first_last_nickname_and_filters_email_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CW_PAGE_SIZE", "1")
    get_settings.cache_clear()

    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(
            200,
            json_data=(
                [
                    {
                        "id": 2,
                        "firstName": "Janet",
                        "lastName": "Other",
                        "communicationItems": [{"value": "janet@elsewhere.com"}],
                    }
                ]
                if kwargs["params"]["page"] == 1
                else [
                    {
                        "id": 1,
                        "firstName": "Jane",
                        "lastName": "Smith",
                        "communicationItems": [{"value": "jane.smith@example.com"}],
                    }
                ]
            ),
        ),
    )

    client = ConnectWiseClient()
    contacts = await client.search_contacts(name="Jane", email="smith@example.com")

    assert [contact["id"] for contact in contacts] == [1]
    assert calls[0]["params"]["conditions"] == (
        '(firstName contains "Jane" OR lastName contains "Jane" OR nickName contains "Jane")'
    )
    assert [call["params"]["page"] for call in calls] == [1, 2]


async def test_search_contacts_splits_full_name_into_multiple_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data=[]),
    )

    client = ConnectWiseClient()
    await client.search_contacts(company_id=250, name="Renier Moorcroft")

    assert calls[0]["params"]["conditions"] == (
        'company/id=250 and '
        '(firstName contains "Renier" OR lastName contains "Renier" OR nickName contains "Renier") AND '
        '(firstName contains "Moorcroft" OR lastName contains "Moorcroft" OR nickName contains "Moorcroft")'
    )


async def test_time_entry_lookup_endpoints_filter_inactive_locally_not_in_conditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(
            200,
            json_data=[
                {"id": 1, "identifier": "helpdesk1", "inactiveFlag": False, "name": "Helpdesk One"},
                {"id": 2, "identifier": "olduser", "inactiveFlag": True, "name": "Old User"},
            ],
        ),
    )

    client = ConnectWiseClient()
    members = await client.search_members(identifier="help", inactive=False)
    work_types = await client.list_work_types(name="Remote", inactive=False)
    work_roles = await client.list_work_roles(name="Engineer", inactive=False)
    locations = await client.list_locations(name="HQ", inactive=False)

    assert [member["id"] for member in members] == [1]
    assert [item["id"] for item in work_types] == [1]
    assert [item["id"] for item in work_roles] == [1]
    assert [item["id"] for item in locations] == [1]

    for call in calls:
        conditions = (call.get("params") or {}).get("conditions", "")
        assert "inactiveFlag=" not in conditions


async def test_list_work_roles_refills_sparse_filtered_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CW_PAGE_SIZE", "2")
    get_settings.cache_clear()

    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(
            200,
            json_data=(
                [
                    {"id": 1, "name": "Desktop Support (Ad hoc)", "inactiveFlag": True},
                    {"id": 2, "name": "Office (Zero Rated)", "inactiveFlag": False},
                ]
                if kwargs["params"]["page"] == 1
                else [
                    {"id": 3, "name": "Pre-Sales (Zero Rated)", "inactiveFlag": False},
                ]
            ),
        ),
    )

    client = ConnectWiseClient()
    page_one = await client.list_work_roles(name="Role", inactive=False, page=1, page_size=1)
    page_two = await client.list_work_roles(name="Role", inactive=False, page=2, page_size=1)

    assert [item["id"] for item in page_one] == [2]
    assert [item["id"] for item in page_two] == [3]
    assert [call["params"]["page"] for call in calls] == [1, 1, 2]
    assert all(call["params"]["pageSize"] == 2 for call in calls)


async def test_add_time_entry_only_sends_optional_fields_when_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data={"id": 77}),
    )

    client = ConnectWiseClient()
    await client.add_time_entry(
        ticket_id=12345,
        member_identifier="helpdesk1",
        time_start="2026-04-20T15:30:00Z",
        actual_hours=0.25,
        location_id=7,
        work_type="Remote Support",
        notes="Worked issue",
        email_contact_flag=True,
    )

    payload = calls[0]["json"]
    assert payload == {
        "chargeToType": "ServiceTicket",
        "chargeToId": 12345,
        "member": {"identifier": "helpdesk1"},
        "timeStart": "2026-04-20T15:30:00Z",
        "actualHours": 0.25,
        "location": {"id": 7},
        "workType": {"name": "Remote Support"},
        "notes": "Worked issue",
        "emailContactFlag": True,
    }


async def test_add_time_entry_preserves_multiline_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data={"id": 77}),
    )

    formatted_note = "Worked issue:\n\n  - reset MFA\n  - confirmed VPN"

    client = ConnectWiseClient()
    await client.add_time_entry(
        ticket_id=12345,
        member_identifier="helpdesk1",
        time_start="2026-04-20T15:30:00Z",
        notes=formatted_note,
        internal_notes="Internal:\n\n  no escalation needed",
    )

    payload = calls[0]["json"]
    assert payload["notes"] == formatted_note
    assert payload["internalNotes"] == "Internal:\n\n  no escalation needed"


async def test_get_board_subtypes_uses_association_endpoint_and_dedupes_by_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(
            200,
            json_data=[
                {"id": 1, "subType": {"id": 9, "name": "Remote Access"}},
                {"id": 2, "subType": {"id": 9, "name": "Remote Access"}},
                {"id": 3, "subType": {"id": 10, "name": "Server"}},
            ],
        ),
    )

    client = ConnectWiseClient()
    subtypes = await client.get_board_subtypes(12, 3)

    assert calls[0]["url"].endswith("/service/boards/12/typeSubTypeItemAssociations")
    assert calls[0]["params"] == {
        "conditions": "type/id=3",
        "fields": "subType/id,subType/name",
        "orderBy": "subType/name asc",
        "page": 1,
        "pageSize": 100,
    }
    assert subtypes == [
        {"id": 9, "name": "Remote Access"},
        {"id": 10, "name": "Server"},
    ]


async def test_get_board_items_uses_board_level_endpoint_and_filters_by_subtype_associations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(
            200,
            json_data=[
                {"item": {"id": 14, "name": "VPN"}},
                {"item": {"id": 16, "name": "Fallback Shape"}},
                {"item": {"id": 14, "name": "VPN"}},
            ],
        ),
    )

    client = ConnectWiseClient()
    items = await client.get_board_items(12, 3, 9)

    assert calls[0]["url"].endswith("/service/boards/12/typeSubTypeItemAssociations")
    assert calls[0]["params"] == {
        "conditions": "type/id=3 and subType/id=9 and item/inactiveFlag=false",
        "fields": "item/id,item/name",
        "orderBy": "item/name asc",
        "page": 1,
        "pageSize": 100,
    }
    assert [item["id"] for item in items] == [14, 16]


async def test_request_fails_fast_when_settings_are_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CW_CLIENT_ID", raising=False)
    get_settings.cache_clear()

    client = ConnectWiseClient()

    with pytest.raises(ConnectWiseError, match="ConnectWise settings are incomplete"):
        await client.healthcheck()


async def test_request_wraps_httpx_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(*, timeout: float) -> FakeAsyncClient:
        class FailingAsyncClient(FakeAsyncClient):
            async def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
                raise client_module.httpx.ConnectTimeout("timed out")

        return FailingAsyncClient(timeout=timeout, handler=lambda *args, **kwargs: FakeResponse(200), calls=[])

    monkeypatch.setattr(client_module.httpx, "AsyncClient", factory)

    client = ConnectWiseClient()

    with pytest.raises(ConnectWiseError, match="ConnectWise request failed: timed out"):
        await client.healthcheck()


async def test_request_wraps_non_json_success_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data=None, content=b"<html>oops</html>"),
    )

    def bad_json() -> Any:
        raise ValueError("not json")

    response = FakeResponse(200, json_data=None, content=b"<html>oops</html>")
    response.json = bad_json  # type: ignore[method-assign]

    monkeypatch.setattr(
        client_module.httpx,
        "AsyncClient",
        lambda *, timeout: FakeAsyncClient(timeout=timeout, handler=lambda method, url, **kwargs: response, calls=calls),
    )

    client = ConnectWiseClient()

    with pytest.raises(
        ConnectWiseError,
        match=r"ConnectWise returned a non-JSON response for GET /system/info\.",
    ):
        await client.healthcheck()


async def test_update_ticket_classifications_can_patch_board_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data={"id": 12345}),
    )

    client = ConnectWiseClient()
    await client.update_ticket_classifications(12345, board_id=12, status="In Progress")

    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith("/service/tickets/12345")
    assert {"op": "replace", "path": "board", "value": {"id": 12}} in calls[0]["json"]
    assert {"op": "replace", "path": "status", "value": {"name": "In Progress"}} in calls[0]["json"]


def test_update_ticket_classifications_rejects_board_name_and_id() -> None:
    client = ConnectWiseClient()

    with pytest.raises(ConnectWiseError, match="Provide either board or board_id, not both"):
        import asyncio

        asyncio.run(client.update_ticket_classifications(12345, board="Service Desk", board_id=12))


async def test_update_ticket_classifications_uses_priority_id_and_primitive_impact_severity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data={"id": 12345}),
    )

    client = ConnectWiseClient()
    await client.update_ticket_classifications(
        12345,
        priority_id=7,
        severity="Low",
        impact="Low",
    )

    assert {"op": "replace", "path": "priority", "value": {"id": 7}} in calls[0]["json"]
    assert {"op": "replace", "path": "severity", "value": "Low"} in calls[0]["json"]
    assert {"op": "replace", "path": "impact", "value": "Low"} in calls[0]["json"]


async def test_update_ticket_classifications_prefers_lookup_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data={"id": 12345}),
    )

    client = ConnectWiseClient()
    await client.update_ticket_classifications(
        12345,
        status_id=2,
        type_id=3,
        subtype_id=9,
        item_id=14,
        team_id=4,
    )

    assert {"op": "replace", "path": "status", "value": {"id": 2}} in calls[0]["json"]
    assert {"op": "replace", "path": "type", "value": {"id": 3}} in calls[0]["json"]
    assert {"op": "replace", "path": "subType", "value": {"id": 9}} in calls[0]["json"]
    assert {"op": "replace", "path": "item", "value": {"id": 14}} in calls[0]["json"]
    assert {"op": "replace", "path": "team", "value": {"id": 4}} in calls[0]["json"]


def test_update_ticket_classifications_rejects_priority_name_and_id() -> None:
    client = ConnectWiseClient()

    with pytest.raises(ConnectWiseError, match="Provide either priority or priority_id, not both"):
        import asyncio

        asyncio.run(client.update_ticket_classifications(12345, priority="Priority 4 - Low", priority_id=7))


async def test_update_ticket_details_patches_summary_and_initial_description_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(method: str, url: str, **kwargs: Any) -> FakeResponse:
        if method == "GET" and url.endswith("/service/tickets/12345/notes"):
            return FakeResponse(
                200,
                json_data=[
                    {"id": 1, "text": "first internal", "detailDescriptionFlag": False},
                    {"id": 2, "text": "old description", "detailDescriptionFlag": True},
                ],
            )
        return FakeResponse(200, json_data={"id": 12345})

    calls = install_fake_async_client(monkeypatch, handler)

    client = ConnectWiseClient()
    await client.update_ticket_details(
        12345,
        summary="Updated subject",
        initial_description="Updated initial description",
    )

    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith("/service/tickets/12345")
    assert calls[0]["json"] == [{"op": "replace", "path": "summary", "value": "Updated subject"}]
    assert calls[1]["method"] == "GET"
    assert calls[1]["url"].endswith("/service/tickets/12345/notes")
    assert calls[1]["params"]["orderBy"] == "dateCreated asc"
    assert calls[2]["method"] == "PATCH"
    assert calls[2]["url"].endswith("/service/tickets/12345/notes/2")
    assert calls[2]["json"] == [{"op": "replace", "path": "text", "value": "Updated initial description"}]


async def test_update_ticket_details_requires_a_field() -> None:
    client = ConnectWiseClient()

    with pytest.raises(ConnectWiseError, match="No ticket detail fields"):
        await client.update_ticket_details(12345)


async def test_update_ticket_details_creates_initial_description_note_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(method: str, url: str, **kwargs: Any) -> FakeResponse:
        if method == "GET" and url.endswith("/service/tickets/12345/notes"):
            return FakeResponse(200, json_data=[])
        if method == "POST" and url.endswith("/service/tickets/12345/notes"):
            return FakeResponse(201, json_data={"id": 9, **kwargs["json"]})
        return FakeResponse(200, json_data={"id": 12345})

    calls = install_fake_async_client(monkeypatch, handler)

    client = ConnectWiseClient()
    await client.update_ticket_details(12345, initial_description="New initial description")

    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/service/tickets/12345/notes")
    assert calls[0]["params"]["orderBy"] == "dateCreated asc"
    assert calls[1]["method"] == "POST"
    assert calls[1]["url"].endswith("/service/tickets/12345/notes")
    assert calls[1]["json"] == {
        "text": "New initial description",
        "detailDescriptionFlag": True,
        "internalAnalysisFlag": False,
        "resolutionFlag": False,
    }




async def test_get_ticket_schedule_entries_uses_full_schedule_entries_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data=[{"id": 88, "objectId": 12345}]),
    )

    client = ConnectWiseClient()
    entries = await client.get_ticket_schedule_entries(12345, page=2, page_size=10)

    assert entries == [{"id": 88, "objectId": 12345}]
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/schedule/entries")
    assert calls[0]["params"] == {
        "conditions": "objectId=12345 and type/id=4",
        "page": 2,
        "pageSize": 10,
        "orderBy": "dateStart desc",
    }


async def test_add_ticket_schedule_entry_builds_service_ticket_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(201, json_data={"id": 88, **kwargs["json"]}),
    )

    client = ConnectWiseClient()
    result = await client.add_ticket_schedule_entry(
        ticket_id=12345,
        member_identifier="helpdesk1",
        date_start="2026-04-28T10:00:00Z",
        date_end="2026-04-28T10:30:00Z",
        hours=0.5,
        allow_schedule_conflicts=True,
    )

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/schedule/entries")
    assert calls[0]["json"] == {
        "objectId": 12345,
        "type": {"id": 4},
        "member": {"identifier": "helpdesk1"},
        "doneFlag": False,
        "acknowledgedFlag": False,
        "ownerFlag": False,
        "dateStart": "2026-04-28T10:00:00Z",
        "dateEnd": "2026-04-28T10:30:00Z",
        "hours": 0.5,
        "allowScheduleConflictsFlag": True,
    }
    assert result["id"] == 88


async def test_update_schedule_entry_patches_supplied_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data={"id": 88}),
    )

    client = ConnectWiseClient()
    await client.update_schedule_entry(88, done=True, date_start="2026-04-28T11:00:00Z")

    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith("/schedule/entries/88")
    assert calls[0]["json"] == [
        {"op": "replace", "path": "dateStart", "value": "2026-04-28T11:00:00Z"},
        {"op": "replace", "path": "doneFlag", "value": True},
    ]


async def test_update_schedule_entry_requires_a_field() -> None:
    client = ConnectWiseClient()

    with pytest.raises(ConnectWiseError, match="No schedule entry fields"):
        await client.update_schedule_entry(88)


async def test_add_ticket_note_preserves_multiline_text(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data={"id": 77}),
    )

    formatted_note = "Ticket reviewed:\n\n  - first line\n  - second line"

    client = ConnectWiseClient()
    await client.add_ticket_note(12345, formatted_note, internal=True)

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/service/tickets/12345/notes")
    assert calls[0]["json"]["text"] == formatted_note
    assert calls[0]["json"]["internalAnalysisFlag"] is True
    assert calls[0]["json"]["detailDescriptionFlag"] is False


async def test_add_ticket_note_keeps_public_note_as_detail_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data={"id": 77}),
    )

    client = ConnectWiseClient()
    await client.add_ticket_note(12345, "Public update", internal=False)

    assert calls[0]["json"]["internalAnalysisFlag"] is False
    assert calls[0]["json"]["detailDescriptionFlag"] is True


async def test_update_ticket_note_patches_text_and_internal_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(200, json_data={"id": 77}),
    )

    client = ConnectWiseClient()
    await client.update_ticket_note(12345, 77, text="Updated", internal=True)

    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith("/service/tickets/12345/notes/77")
    assert calls[0]["json"] == [
        {"op": "replace", "path": "text", "value": "Updated"},
        {"op": "replace", "path": "internalAnalysisFlag", "value": True},
        {"op": "replace", "path": "detailDescriptionFlag", "value": False},
    ]


async def test_delete_ticket_note_uses_ticket_note_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(204),
    )

    client = ConnectWiseClient()
    await client.delete_ticket_note(12345, 77)

    assert calls[0]["method"] == "DELETE"
    assert calls[0]["url"].endswith("/service/tickets/12345/notes/77")
