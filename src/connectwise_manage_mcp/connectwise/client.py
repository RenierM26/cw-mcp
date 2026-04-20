from __future__ import annotations

import base64
from typing import Any

import httpx

from connectwise_manage_mcp.config import get_settings


class ConnectWiseError(RuntimeError):
    pass


class ConnectWiseClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _auth_header(self) -> str:
        raw = f"{self.settings.cw_company_id}+{self.settings.cw_public_key}:{self.settings.cw_private_key}"
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._auth_header(),
            "clientId": self.settings.cw_client_id,
            "Accept": f"application/vnd.connectwise.com+json; version={self.settings.cw_api_version}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        base = self.settings.cw_base_url.rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{base}{suffix}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        if not self.settings.is_configured:
            raise ConnectWiseError("ConnectWise settings are incomplete. Fill in the env vars first.")

        async with httpx.AsyncClient(timeout=self.settings.cw_timeout_seconds) as client:
            response = await client.request(
                method,
                self._url(path),
                headers=self._headers(),
                params=params,
                json=json,
            )

        if response.status_code >= 400:
            detail = response.text[:1000]
            raise ConnectWiseError(f"ConnectWise API error {response.status_code}: {detail}")

        if response.status_code == 204 or not response.content:
            return {"ok": True}

        return response.json()

    async def healthcheck(self) -> dict[str, Any]:
        return await self._request("GET", "/system/info")

    async def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/service/tickets/{ticket_id}")

    async def search_tickets(
        self,
        *,
        board: str | None = None,
        status: str | None = None,
        company: str | None = None,
        summary: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        if board:
            conditions.append(f'board/name="{self._escape(board)}"')
        if status:
            conditions.append(f'status/name="{self._escape(status)}"')
        if company:
            conditions.append(f'company/name contains "{self._escape(company)}"')
        if summary:
            conditions.append(f'summary contains "{self._escape(summary)}"')

        params = {
            "page": page,
            "pageSize": min(page_size or self.settings.cw_page_size, self.settings.cw_max_page_size),
            "orderBy": "lastUpdated desc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        return await self._request("GET", "/service/tickets", params=params)

    async def create_ticket(
        self,
        *,
        company_id: int,
        board: str,
        summary: str,
        initial_description: str,
        contact_id: int | None = None,
        priority: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "company": {"id": company_id},
            "board": {"name": board},
            "summary": summary,
            "initialDescription": initial_description,
        }
        if contact_id is not None:
            payload["contact"] = {"id": contact_id}
        if priority:
            payload["priority"] = {"name": priority}
        return await self._request("POST", "/service/tickets", json=payload)

    async def update_ticket_status(self, ticket_id: int, status: str) -> dict[str, Any]:
        patches = [{"op": "replace", "path": "status", "value": {"name": status}}]
        return await self._request("PATCH", f"/service/tickets/{ticket_id}", json=patches)

    async def update_ticket_classifications(
        self,
        ticket_id: int,
        *,
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
        patches: list[dict[str, Any]] = []

        def add_replace(path: str, value: Any) -> None:
            patches.append({"op": "replace", "path": path, "value": value})

        if status:
            add_replace("status", {"name": status})
        if priority:
            add_replace("priority", {"name": priority})
        if board:
            add_replace("board", {"name": board})
        if type_name:
            add_replace("type", {"name": type_name})
        if sub_type_name:
            add_replace("subType", {"name": sub_type_name})
        if item_name:
            add_replace("item", {"name": item_name})
        if team:
            add_replace("team", {"name": team})
        if severity:
            add_replace("severity", {"name": severity})
        if impact:
            add_replace("impact", {"name": impact})
        if source:
            add_replace("source", {"name": source})

        if not patches:
            raise ConnectWiseError("No classification fields were provided to update.")

        return await self._request("PATCH", f"/service/tickets/{ticket_id}", json=patches)

    async def add_ticket_note(self, ticket_id: int, text: str, internal: bool = True) -> dict[str, Any]:
        payload = {
            "text": text,
            "detailDescriptionFlag": True,
            "internalAnalysisFlag": internal,
            "resolutionFlag": False,
        }
        return await self._request("POST", f"/service/tickets/{ticket_id}/notes", json=payload)

    async def get_ticket_notes(
        self,
        ticket_id: int,
        *,
        page: int = 1,
        page_size: int | None = None,
        order_by: str = "dateCreated desc",
    ) -> list[dict[str, Any]]:
        params = {
            "page": page,
            "pageSize": min(page_size or self.settings.cw_page_size, self.settings.cw_max_page_size),
            "orderBy": order_by,
        }
        return await self._request("GET", f"/service/tickets/{ticket_id}/notes", params=params)

    async def get_ticket_time_entries(
        self,
        ticket_id: int,
        *,
        page: int = 1,
        page_size: int | None = None,
        order_by: str = "dateEntered desc",
    ) -> list[dict[str, Any]]:
        params = {
            "conditions": f'(chargeToType="ServiceTicket" OR chargeToType="ProjectTicket") AND chargeToId={ticket_id}',
            "page": page,
            "pageSize": min(page_size or self.settings.cw_page_size, self.settings.cw_max_page_size),
            "orderBy": order_by,
        }
        return await self._request("GET", "/time/entries", params=params)

    async def add_time_entry(
        self,
        *,
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
        payload: dict[str, Any] = {
            "chargeToType": "ServiceTicket",
            "chargeToId": ticket_id,
            "member": {"identifier": member_identifier},
            "timeStart": time_start,
        }
        if time_end:
            payload["timeEnd"] = time_end
        if hours_deduct is not None:
            payload["hoursDeduct"] = hours_deduct
        if actual_hours is not None:
            payload["actualHours"] = actual_hours
        if billable_option:
            payload["billableOption"] = billable_option
        if work_type:
            payload["workType"] = {"name": work_type}
        if work_role:
            payload["workRole"] = {"name": work_role}
        if notes:
            payload["notes"] = notes
        if internal_notes:
            payload["internalNotes"] = internal_notes
        if email_resource_flag:
            payload["emailResourceFlag"] = True
        if email_contact_flag:
            payload["emailContactFlag"] = True
        if email_cc_flag:
            payload["emailCcFlag"] = True

        return await self._request("POST", "/time/entries", json=payload)

    async def get_company(self, company_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/company/companies/{company_id}")

    async def list_boards(
        self,
        *,
        name: str | None = None,
        inactive: bool | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        if name:
            conditions.append(f'name contains "{self._escape(name)}"')
        if inactive is not None:
            conditions.append(f'inactiveFlag={str(inactive).lower()}')

        params = {
            "page": page,
            "pageSize": min(page_size or self.settings.cw_page_size, self.settings.cw_max_page_size),
            "orderBy": "name asc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        return await self._request("GET", "/service/boards", params=params)

    async def get_board_statuses(self, board_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/service/boards/{board_id}/statuses")

    async def get_board_types(self, board_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/service/boards/{board_id}/types")

    async def get_board_subtypes(self, board_id: int, type_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/service/boards/{board_id}/types/{type_id}/subtypes")

    async def get_board_items(self, board_id: int, type_id: int, subtype_id: int) -> list[dict[str, Any]]:
        path = f"/service/boards/{board_id}/types/{type_id}/subtypes/{subtype_id}/items"
        return await self._request("GET", path)

    async def get_board_teams(self, board_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/service/boards/{board_id}/teams")

    async def search_companies(
        self,
        *,
        name: str | None = None,
        identifier: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        if name:
            conditions.append(f'name contains "{self._escape(name)}"')
        if identifier:
            conditions.append(f'identifier contains "{self._escape(identifier)}"')

        params = {
            "page": page,
            "pageSize": min(page_size or self.settings.cw_page_size, self.settings.cw_max_page_size),
            "orderBy": "name asc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        return await self._request("GET", "/company/companies", params=params)

    async def search_contacts(
        self,
        *,
        company_id: int | None = None,
        name: str | None = None,
        email: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        if company_id is not None:
            conditions.append(f'company/id={company_id}')
        if name:
            conditions.append(f'name contains "{self._escape(name)}"')
        if email:
            conditions.append(f'defaultEmailAddress contains "{self._escape(email)}"')

        params = {
            "page": page,
            "pageSize": min(page_size or self.settings.cw_page_size, self.settings.cw_max_page_size),
            "orderBy": "lastName asc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        return await self._request("GET", "/company/contacts", params=params)

    async def search_members(
        self,
        *,
        identifier: str | None = None,
        name: str | None = None,
        inactive: bool | None = False,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        if identifier:
            conditions.append(f'identifier contains "{self._escape(identifier)}"')
        if name:
            escaped = self._escape(name)
            conditions.append(
                f'(firstName contains "{escaped}" OR lastName contains "{escaped}" OR officeEmail contains "{escaped}")'
            )
        if inactive is not None:
            conditions.append(f'inactiveFlag={str(inactive).lower()}')

        params = {
            "page": page,
            "pageSize": min(page_size or self.settings.cw_page_size, self.settings.cw_max_page_size),
            "orderBy": "identifier asc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        return await self._request("GET", "/system/members", params=params)

    async def list_work_types(
        self,
        *,
        name: str | None = None,
        inactive: bool | None = False,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        if name:
            conditions.append(f'name contains "{self._escape(name)}"')
        if inactive is not None:
            conditions.append(f'inactiveFlag={str(inactive).lower()}')

        params = {
            "page": page,
            "pageSize": min(page_size or self.settings.cw_page_size, self.settings.cw_max_page_size),
            "orderBy": "name asc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        return await self._request("GET", "/time/workTypes", params=params)

    async def list_work_roles(
        self,
        *,
        name: str | None = None,
        inactive: bool | None = False,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        if name:
            conditions.append(f'name contains "{self._escape(name)}"')
        if inactive is not None:
            conditions.append(f'inactiveFlag={str(inactive).lower()}')

        params = {
            "page": page,
            "pageSize": min(page_size or self.settings.cw_page_size, self.settings.cw_max_page_size),
            "orderBy": "name asc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        return await self._request("GET", "/time/workRoles", params=params)

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace('"', '\\"')
