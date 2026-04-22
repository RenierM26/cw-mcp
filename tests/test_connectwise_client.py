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


async def test_get_board_subtypes_uses_board_level_endpoint_and_filters_by_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(
            200,
            json_data=[
                {"id": 9, "name": "Remote Access", "typeAssociationIds": [3]},
                {"id": 10, "name": "Server", "typeAssociationIds": [4]},
                {"id": 11, "name": "Fallback Shape", "typeAssociation": {"id": 3}},
            ],
        ),
    )

    client = ConnectWiseClient()
    subtypes = await client.get_board_subtypes(12, 3)

    assert calls[0]["url"].endswith("/service/boards/12/subtypes")
    assert calls[0]["params"] == {
        "conditions": "inactiveFlag=false",
        "childConditions": "typeAssociation/id=3",
        "fields": "id,name",
        "orderBy": "name asc",
    }
    assert [item["id"] for item in subtypes] == [9, 10, 11]


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
