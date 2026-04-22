from __future__ import annotations

import base64
import json as jsonlib
from typing import Any

import httpx

from connectwise_manage_mcp.config import get_settings


class ConnectWiseError(RuntimeError):
    """Raised when local configuration or a ConnectWise API call fails."""

    pass


class ConnectWiseClient:
    """Thin async wrapper around the ConnectWise Manage REST API.

    The client centralizes auth headers, URL construction, pagination defaults,
    and common error handling so the MCP tool layer can stay small and focused.
    """

    def __init__(self) -> None:
        """Load cached runtime settings for subsequent API calls."""

        self.settings = get_settings()

    def _auth_header(self) -> str:
        """Build the Basic auth header expected by ConnectWise Manage."""

        raw = f"{self.settings.cw_company_id}+{self.settings.cw_public_key}:{self.settings.cw_private_key}"
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"

    def _headers(self) -> dict[str, str]:
        """Return standard headers shared by all ConnectWise API requests."""

        return {
            "Authorization": self._auth_header(),
            "clientId": self.settings.cw_client_id,
            "Accept": f"application/vnd.connectwise.com+json; version={self.settings.cw_api_version}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        """Join the configured base URL with an API path fragment."""

        base = self.settings.cw_base_url.rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{base}{suffix}"

    def _bounded_page_size(self, page_size: int | None) -> int:
        """Clamp requested page sizes into a ConnectWise-safe positive range."""

        if page_size is None:
            return self.settings.cw_page_size
        return max(1, min(page_size, self.settings.cw_max_page_size))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Execute a single HTTP request and normalize ConnectWise-style errors.

        Args:
            method: HTTP verb to send to ConnectWise.
            path: API path relative to ``cw_base_url``.
            params: Optional query-string parameters.
            json: Optional JSON body for POST or PATCH requests.

        Returns:
            Parsed JSON from the response, or ``{"ok": True}`` for empty success responses.

        Raises:
            ConnectWiseError: If configuration is incomplete or the API returns an error.
        """

        if not self.settings.is_configured:
            raise ConnectWiseError("ConnectWise settings are incomplete. Fill in the env vars first.")

        try:
            async with httpx.AsyncClient(timeout=self.settings.cw_timeout_seconds) as client:
                response = await client.request(
                    method,
                    self._url(path),
                    headers=self._headers(),
                    params=params,
                    json=json,
                )
        except httpx.HTTPError as exc:
            raise ConnectWiseError(f"ConnectWise request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:1000]
            raise ConnectWiseError(f"ConnectWise API error {response.status_code}: {detail}")

        if response.status_code == 204 or not response.content:
            return {"ok": True}

        try:
            return response.json()
        except ValueError as exc:
            raise ConnectWiseError(
                f"ConnectWise returned a non-JSON response for {method} {path}."
            ) from exc

    def _expect_list_response(self, payload: Any, *, method: str, path: str) -> list[dict[str, Any]]:
        """Return list payloads unchanged, or raise a clear error for unexpected shapes."""

        if isinstance(payload, list):
            return payload

        if isinstance(payload, dict):
            detail = jsonlib.dumps(payload)[:1000]
        else:
            detail = repr(payload)[:1000]

        raise ConnectWiseError(
            f"ConnectWise returned an unexpected non-list response for {method} {path}: {detail}"
        )

    async def healthcheck(self) -> dict[str, Any]:
        """Fetch basic system information to verify API reachability."""

        return await self._request("GET", "/system/info")

    async def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        """Fetch a single service ticket by numeric identifier."""

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
        """Search service tickets with simple business-facing filters.

        Args:
            board: Optional board name to match exactly.
            status: Optional status name to match exactly.
            company: Optional partial company name match.
            summary: Optional partial ticket summary match.
            page: 1-based results page.
            page_size: Requested page size, capped to configured maximum.

        Returns:
            A list of raw ConnectWise ticket records.
        """

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
            "pageSize": self._bounded_page_size(page_size),
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
        """Create a new service ticket with the minimum common fields.

        Args:
            company_id: Numeric ConnectWise company id.
            board: Destination board name.
            summary: Ticket summary line.
            initial_description: Main body/description for the ticket.
            contact_id: Optional numeric contact id to associate.
            priority: Optional priority name.

        Returns:
            The raw ConnectWise ticket payload for the newly created ticket.
        """

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
        """Replace the current ticket status by name."""

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
        """Patch one or more ticket classification fields in a single API call.

        Args:
            ticket_id: Numeric ticket id to update.
            status: Optional status name.
            priority: Optional priority name.
            board: Optional board name.
            type_name: Optional ticket type name.
            sub_type_name: Optional ticket subtype name.
            item_name: Optional ticket item name.
            team: Optional team name.
            severity: Optional severity name.
            impact: Optional impact name.
            source: Optional source name.

        Returns:
            The raw ConnectWise response payload for the patch request.

        Raises:
            ConnectWiseError: If no fields were supplied.
        """

        patches: list[dict[str, Any]] = []

        def add_replace(path: str, value: Any) -> None:
            """Append a JSON Patch replace operation for the ticket update."""

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
        """Create a note entry on a service ticket."""

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
        """Return ticket notes ordered for review workflows."""

        params = {
            "page": page,
            "pageSize": self._bounded_page_size(page_size),
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
        """Return time entries linked to the given ticket."""

        params = {
            "conditions": f'(chargeToType="ServiceTicket" OR chargeToType="ProjectTicket") AND chargeToId={ticket_id}',
            "page": page,
            "pageSize": self._bounded_page_size(page_size),
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
        location_id: int | None = None,
        billable_option: str | None = None,
        work_type: str | None = None,
        work_role: str | None = None,
        notes: str | None = None,
        internal_notes: str | None = None,
        email_resource_flag: bool = False,
        email_contact_flag: bool = False,
        email_cc_flag: bool = False,
    ) -> dict[str, Any]:
        """Create a time entry tied to a service ticket.

        Args:
            ticket_id: Numeric service ticket id.
            member_identifier: ConnectWise member identifier.
            time_start: Entry start timestamp in ConnectWise-compatible format.
            time_end: Optional entry end timestamp.
            hours_deduct: Optional hours-to-deduct value.
            actual_hours: Optional actual hours value.
            location_id: Optional numeric location id to force on the time entry.
            billable_option: Optional billable option name/value.
            work_type: Optional work type name.
            work_role: Optional work role name.
            notes: Optional customer-facing notes.
            internal_notes: Optional internal-only notes.
            email_resource_flag: Whether to email the resource.
            email_contact_flag: Whether to email the contact.
            email_cc_flag: Whether to email CC recipients.

        Returns:
            The raw ConnectWise time-entry payload returned by the API.
        """

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
        if location_id is not None:
            payload["location"] = {"id": location_id}
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
        """Fetch a single company by numeric identifier."""

        return await self._request("GET", f"/company/companies/{company_id}")

    async def list_boards(
        self,
        *,
        name: str | None = None,
        inactive: bool | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        """List service boards with optional name and inactive filters."""

        conditions: list[str] = []
        if name:
            conditions.append(f'name contains "{self._escape(name)}"')
        if inactive is not None:
            conditions.append(f'inactiveFlag={str(inactive).lower()}')

        params = {
            "page": page,
            "pageSize": self._bounded_page_size(page_size),
            "orderBy": "name asc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        return await self._request("GET", "/service/boards", params=params)

    async def get_board_statuses(self, board_id: int) -> list[dict[str, Any]]:
        """Fetch statuses available for a given service board."""

        return await self._request("GET", f"/service/boards/{board_id}/statuses")

    async def get_board_types(self, board_id: int) -> list[dict[str, Any]]:
        """Fetch types available for a given service board."""

        return await self._request(
            "GET",
            f"/service/boards/{board_id}/types",
            params={
                "conditions": "inactiveFlag=false",
                "fields": "id,name",
                "orderBy": "name asc",
            },
        )

    async def get_board_subtypes(self, board_id: int, type_id: int) -> list[dict[str, Any]]:
        """Fetch subtypes for a specific board/type combination.

        ConnectWise exposes board subtypes at the board level rather than under a nested
        ``/types/{type_id}/subtypes`` route. Query the board-level collection with an
        active-only parent condition plus childConditions for the type association so the
        response stays compact and hierarchy-specific.
        """

        return await self._request(
            "GET",
            f"/service/boards/{board_id}/subtypes",
            params={
                "conditions": "inactiveFlag=false",
                "childConditions": f"typeAssociation/id={type_id}",
                "fields": "id,name",
                "orderBy": "name asc",
            },
        )

    async def get_board_items(self, board_id: int, type_id: int, subtype_id: int) -> list[dict[str, Any]]:
        """Fetch items for a specific board/type/subtype combination.

        ConnectWise item hierarchy lookups are exposed through the dedicated board
        type/subtype/item association endpoint rather than the plain board-items list.
        Query the association collection server-side, then return a compact deduplicated
        item list with only ``id`` and ``name``.
        """

        associations = await self._request(
            "GET",
            f"/service/boards/{board_id}/typeSubTypeItemAssociations",
            params={
                "conditions": (
                    f"type/id={type_id} and subType/id={subtype_id} and item/inactiveFlag=false"
                ),
                "fields": "item/id,item/name",
                "orderBy": "item/name asc",
            },
        )

        items_by_id: dict[int, dict[str, Any]] = {}
        for association in associations:
            item = association.get("item") or {}
            item_id = item.get("id")
            item_name = item.get("name")
            if isinstance(item_id, int) and item_id not in items_by_id:
                items_by_id[item_id] = {"id": item_id, "name": item_name}
        return list(items_by_id.values())

    async def get_board_item_associations(self, board_id: int, item_id: int) -> list[dict[str, Any]]:
        """Fetch subtype-association records for a board item."""

        path = f"/service/boards/{board_id}/items/{item_id}/associations"
        return await self._request("GET", path)

    async def get_board_teams(self, board_id: int) -> list[dict[str, Any]]:
        """Fetch teams configured for a given service board."""

        return await self._request("GET", f"/service/boards/{board_id}/teams")

    async def search_companies(
        self,
        *,
        name: str | None = None,
        identifier: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search companies by name and optional external identifier."""

        conditions: list[str] = []
        if name:
            conditions.append(f'name contains "{self._escape(name)}"')
        if identifier:
            conditions.append(f'identifier contains "{self._escape(identifier)}"')

        params = {
            "page": page,
            "pageSize": self._bounded_page_size(page_size),
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
        """Search contacts by company, name, or email address."""

        conditions: list[str] = []
        if company_id is not None:
            conditions.append(f'company/id={company_id}')
        if name:
            conditions.append(self._contact_name_condition(name))

        params = {
            "page": page,
            "pageSize": self._bounded_page_size(page_size),
            "orderBy": "lastName asc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        if not email:
            payload = await self._request("GET", "/company/contacts", params=params)
            return self._expect_list_response(payload, method="GET", path="/company/contacts")

        return await self._request_filtered_contacts_page(
            params=params,
            email=email,
        )

    async def search_members(
        self,
        *,
        identifier: str | None = None,
        name: str | None = None,
        inactive: bool | None = False,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search members for assignment and time-entry workflows."""

        conditions: list[str] = []
        if identifier:
            conditions.append(f'identifier contains "{self._escape(identifier)}"')
        if name:
            escaped = self._escape(name)
            conditions.append(
                f'(firstName contains "{escaped}" or lastName contains "{escaped}" or officeEmail contains "{escaped}")'
            )

        params = {
            "page": page,
            "pageSize": self._bounded_page_size(page_size),
            "orderBy": "identifier asc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        return await self._request_filtered_inactive_page(
            "/system/members",
            params=params,
            inactive=inactive,
        )

    async def list_work_types(
        self,
        *,
        name: str | None = None,
        inactive: bool | None = False,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        """List work types with optional filtering for inactive entries."""

        conditions: list[str] = []
        if name:
            conditions.append(f'name contains "{self._escape(name)}"')

        params = {
            "page": page,
            "pageSize": self._bounded_page_size(page_size),
            "orderBy": "name asc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        return await self._request_filtered_inactive_page(
            "/time/workTypes",
            params=params,
            inactive=inactive,
        )

    async def list_work_roles(
        self,
        *,
        name: str | None = None,
        inactive: bool | None = False,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        """List work roles with optional filtering for inactive entries."""

        conditions: list[str] = []
        if name:
            conditions.append(f'name contains "{self._escape(name)}"')

        params = {
            "page": page,
            "pageSize": self._bounded_page_size(page_size),
            "orderBy": "name asc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        return await self._request_filtered_inactive_page(
            "/time/workRoles",
            params=params,
            inactive=inactive,
        )

    async def list_locations(
        self,
        *,
        name: str | None = None,
        inactive: bool | None = False,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        """List system locations for time-entry validation workflows."""

        conditions: list[str] = []
        if name:
            conditions.append(f'name contains "{self._escape(name)}"')

        params = {
            "page": page,
            "pageSize": self._bounded_page_size(page_size),
            "orderBy": "name asc",
        }
        if conditions:
            params["conditions"] = " and ".join(conditions)

        return await self._request_filtered_inactive_page(
            "/system/locations",
            params=params,
            inactive=inactive,
        )

    @staticmethod
    def _escape(value: str) -> str:
        """Escape double quotes for ConnectWise conditions expressions."""

        return value.replace('"', '\\"')

    @staticmethod
    def _filter_inactive_records(records: list[dict[str, Any]], inactive: bool | None) -> list[dict[str, Any]]:
        """Apply an inactive filter locally when an endpoint does not support it in conditions.

        Some ConnectWise endpoints return ``inactiveFlag`` but reject it inside the
        server-side ``conditions`` expression with ``APIFindCondition`` errors. To keep
        lookups reliable, fetch the narrowed dataset first and then filter locally when
        the inactive state is present on the returned record.
        """

        if inactive is None:
            return records

        filtered: list[dict[str, Any]] = []
        for record in records:
            record_inactive = record.get("inactiveFlag")
            if isinstance(record_inactive, bool) and record_inactive != inactive:
                continue
            filtered.append(record)
        return filtered

    async def _request_filtered_inactive_page(
        self,
        path: str,
        *,
        params: dict[str, Any],
        inactive: bool | None,
    ) -> list[dict[str, Any]]:
        """Fetch enough raw pages to build a stable filtered page.

        Some ConnectWise endpoints reject ``inactiveFlag`` in ``conditions``, so the
        client filters inactive records locally. When the upstream API sorts inactive
        rows first, filtering after a single paged request can yield sparse or empty
        pages even though matching active rows exist later. To keep pagination useful,
        fetch successive raw pages until the requested filtered page is filled or the
        upstream endpoint is exhausted.
        """

        page = max(1, int(params.get("page", 1)))
        requested_size = self._bounded_page_size(params.get("pageSize"))

        base_params = dict(params)
        base_params["pageSize"] = max(requested_size, self.settings.cw_page_size)

        if inactive is None:
            payload = await self._request("GET", path, params=base_params)
            return self._expect_list_response(payload, method="GET", path=path)

        target_start = (page - 1) * requested_size
        target_end = target_start + requested_size
        collected: list[dict[str, Any]] = []
        upstream_page = 1

        while len(collected) < target_end:
            page_params = dict(base_params)
            page_params["page"] = upstream_page
            payload = await self._request("GET", path, params=page_params)
            records = self._expect_list_response(payload, method="GET", path=path)
            if not records:
                break

            collected.extend(self._filter_inactive_records(records, inactive))

            if len(records) < page_params["pageSize"]:
                break
            upstream_page += 1

        return collected[target_start:target_end]

    @staticmethod
    def _filter_contacts_by_email(contacts: list[dict[str, Any]], email: str | None) -> list[dict[str, Any]]:
        """Filter contacts locally by email to avoid endpoint-specific condition issues."""

        if not email:
            return contacts

        target = email.strip().casefold()
        filtered: list[dict[str, Any]] = []
        for contact in contacts:
            communication_items = contact.get("communicationItems") or []
            communication_values = [
                (item.get("value") or "").casefold()
                for item in communication_items
                if isinstance(item, dict)
            ]
            candidates = communication_values + [
                str(contact.get("defaultEmailAddress") or "").casefold(),
                str(contact.get("emailAddress") or "").casefold(),
            ]
            if any(target in candidate for candidate in candidates if candidate):
                filtered.append(contact)
        return filtered

    def _contact_name_condition(self, name: str) -> str:
        """Build a contact-name query that works for first-name, surname, and full-name input."""

        terms = self._split_search_terms(name)
        groups = [
            (
                f'(firstName contains "{self._escape(term)}" '
                f'OR lastName contains "{self._escape(term)}" '
                f'OR nickName contains "{self._escape(term)}")'
            )
            for term in terms
        ]
        return " AND ".join(groups)

    async def _request_filtered_contacts_page(
        self,
        *,
        params: dict[str, Any],
        email: str,
    ) -> list[dict[str, Any]]:
        """Fetch enough contact pages to build a stable email-filtered result page."""

        page = max(1, int(params.get("page", 1)))
        requested_size = self._bounded_page_size(params.get("pageSize"))

        base_params = dict(params)
        base_params["pageSize"] = max(requested_size, self.settings.cw_page_size)

        target_start = (page - 1) * requested_size
        target_end = target_start + requested_size
        collected: list[dict[str, Any]] = []
        upstream_page = 1

        while len(collected) < target_end:
            page_params = dict(base_params)
            page_params["page"] = upstream_page
            payload = await self._request("GET", "/company/contacts", params=page_params)
            records = self._expect_list_response(payload, method="GET", path="/company/contacts")
            if not records:
                break

            collected.extend(self._filter_contacts_by_email(records, email))

            if len(records) < page_params["pageSize"]:
                break
            upstream_page += 1

        return collected[target_start:target_end]

    @staticmethod
    def _split_search_terms(value: str) -> list[str]:
        """Split free-text search input into non-empty whitespace-separated terms."""

        terms = [part for part in value.split() if part]
        return terms or [value]

    @staticmethod
    def _subtype_matches_type(subtype: dict[str, Any], type_id: int) -> bool:
        """Return whether a board subtype is associated with the requested board type id."""

        type_association_ids = subtype.get("typeAssociationIds")
        if isinstance(type_association_ids, list):
            return any(candidate == type_id for candidate in type_association_ids)

        type_association = subtype.get("typeAssociation") or {}
        if type_association.get("id") == type_id:
            return True

        type_associations = subtype.get("typeAssociations")
        if isinstance(type_associations, list):
            return any((item or {}).get("id") == type_id for item in type_associations if isinstance(item, dict))

        return False

    @staticmethod
    def _item_association_matches_subtype(association: dict[str, Any], subtype_id: int) -> bool:
        """Return whether an item association includes the requested board subtype id."""

        subtype_association_ids = association.get("subTypeAssociationIds")
        if isinstance(subtype_association_ids, list):
            return any(candidate == subtype_id for candidate in subtype_association_ids)

        subtype_association = association.get("subTypeAssociation") or {}
        if subtype_association.get("id") == subtype_id:
            return True

        subtype_associations = association.get("subTypeAssociations")
        if isinstance(subtype_associations, list):
            return any((item or {}).get("id") == subtype_id for item in subtype_associations if isinstance(item, dict))

        return False
