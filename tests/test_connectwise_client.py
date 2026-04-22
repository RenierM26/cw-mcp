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
    await client.search_members(identifier='TK"ekana', name="Tshepiso", inactive=False, page=2, page_size=5)

    params = calls[0]["params"]
    assert params["page"] == 2
    assert params["pageSize"] == 5
    assert params["orderBy"] == "identifier asc"
    assert params["conditions"] == (
        'identifier contains "TK\\"ekana" and '
        '(firstName contains "Tshepiso" or lastName contains "Tshepiso" or officeEmail contains "Tshepiso") and '
        'inactiveFlag=false'
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
        await client.search_members(name="Tshepiso")


async def test_list_work_roles_raises_clean_error_for_non_list_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_async_client(
        monkeypatch,
        lambda method, url, **kwargs: FakeResponse(
            200,
            json_data={"code": "BadRequest", "message": "Unexpected response shape"},
        ),
    )

    client = ConnectWiseClient()

    with pytest.raises(
        ConnectWiseError,
        match=r"unexpected non-list response for GET /time/workRoles: .*Unexpected response shape",
    ):
        await client.list_work_roles(page_size=5)


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
        "locationId": 7,
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
    assert [item["id"] for item in subtypes] == [9, 11]


async def test_get_board_items_uses_board_level_endpoint_and_filters_by_subtype_associations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(method: str, url: str, **kwargs: Any) -> FakeResponse:
        if url.endswith("/service/boards/12/items"):
            return FakeResponse(
                200,
                json_data=[
                    {"id": 14, "name": "VPN"},
                    {"id": 15, "name": "Server"},
                    {"id": 16, "name": "Fallback Shape"},
                ],
            )
        if url.endswith("/service/boards/12/items/14/associations"):
            return FakeResponse(200, json_data=[{"id": 1, "subTypeAssociationIds": [9]}])
        if url.endswith("/service/boards/12/items/15/associations"):
            return FakeResponse(200, json_data=[{"id": 2, "subTypeAssociationIds": [10]}])
        if url.endswith("/service/boards/12/items/16/associations"):
            return FakeResponse(200, json_data=[{"id": 3, "subTypeAssociation": {"id": 9}}])
        raise AssertionError(f"Unexpected URL: {url}")

    calls = install_fake_async_client(monkeypatch, handler)

    client = ConnectWiseClient()
    items = await client.get_board_items(12, 3, 9)

    assert calls[0]["url"].endswith("/service/boards/12/items")
    assert [call["url"].split("/v4_6_release/apis/3.0")[-1] for call in calls[1:]] == [
        "/service/boards/12/items/14/associations",
        "/service/boards/12/items/15/associations",
        "/service/boards/12/items/16/associations",
    ]
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
