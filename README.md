# ConnectWise Manage MCP

A small FastMCP server that gives n8n or any MCP-capable client a cleaner way to work with ConnectWise Manage.

This scaffold is intentionally narrow and practical:
- ticket-focused v1
- HTTP-friendly for Azure deployment
- stdio-friendly for local testing
- central auth/retry/query logic in one place

## Included tools

- `get_ticket`
- `get_ticket_bundle`
- `search_tickets`
- `create_ticket`
- `update_ticket_status`
- `update_ticket_classifications`
- `add_ticket_note`
- `get_ticket_notes`
- `get_ticket_time_entries`
- `add_ticket_time_entry`
- `list_boards`
- `get_board_lookup`
- `get_board_types`
- `get_board_subtypes`
- `get_board_items`
- `search_members`
- `list_work_types`
- `list_work_roles`
- `get_company`
- `search_companies`
- `search_contacts`

## Project layout

```text
connectwise-manage-mcp/
├── .devcontainer/
├── .github/workflows/
├── docs/
├── src/connectwise_manage_mcp/
│   ├── connectwise/
│   ├── tools/
│   ├── app.py
│   ├── config.py
│   ├── models.py
│   └── server.py
├── tests/
├── .env.example
├── .env.azure.example
├── Dockerfile
├── pyproject.toml
└── README.md
```

## Quick start

### 1. Copy the folder wherever you want

### 2. Create your env file

```bash
cp .env.example .env
```

Fill in:
- `CW_BASE_URL`
- `CW_COMPANY_ID`
- `CW_PUBLIC_KEY`
- `CW_PRIVATE_KEY`
- `CW_CLIENT_ID`

Example base URL:

```text
https://your-company.connectwise.com/v4_6_release/apis/3.0
```

## Run locally

### With uv

```bash
uv sync
uv run cwmcp-http
```

### With pip

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cwmcp-http
```

Server endpoint:

```text
http://localhost:8000/mcp
```

Health endpoint:

```text
http://localhost:8000/health
```

## Run in stdio mode

Useful for local MCP testing:

```bash
cwmcp-stdio
```

## Run in Docker

```bash
docker build -t connectwise-manage-mcp .
docker run --rm -p 8000:8000 --env-file .env connectwise-manage-mcp
```

## Suggested Azure deploy target

Use Azure Container Apps if you want the easiest path.

Files added for that:
- `.env.azure.example`
- `docs/AZURE_CONTAINER_APPS.md`

Recommended split in Azure:
- normal config as env vars
- `CW_PUBLIC_KEY` and `CW_PRIVATE_KEY` as Container App secrets
- internal ingress if only n8n needs access

Main MCP endpoint after deploy:

```text
https://<your-app-fqdn>/mcp
```

## n8n usage options

### Option 1, n8n as plain HTTP client
Call this service from an HTTP Request node if you expose helper endpoints yourself later. This scaffold is MCP-first, so the main endpoint is `/mcp`.

### Option 2, MCP-aware client path
Use an MCP-capable client or gateway that can connect to:

```text
http://your-service-url/mcp
```

## Notes on ConnectWise Manage

This scaffold normalizes some ugly parts of the API, but it is still a thin wrapper. You will probably want to tune:
- status names per board
- required fields for your tenant
- custom field handling
- pagination limits
- agreement / board / company filtering logic

## Ticket workflow coverage in this version

This version is shaped around a common triage and update flow:

- read ticket summary and description
- read notes
- read time entries
- update classification fields like status, priority, board, type, subtype, item, team, severity, impact, and source
- add ticket notes
- add time entries
- look up valid boards, statuses, types, subtypes, items, teams, members, work types, and work roles before updating

The quickest tool for AI-driven review is `get_ticket_bundle`, which returns the ticket plus notes and time entries in one response.

The safest classification flow is usually:
1. `list_boards`
2. `get_board_lookup`
3. `update_ticket_classifications`

The safest time-entry flow is usually:
1. `search_members`
2. `list_work_types`
3. `list_work_roles`
4. `add_ticket_time_entry`

## First improvements I would make

- add board-specific status validation
- add `get_company_by_identifier`
- add `assign_ticket`
- add structured models for richer response validation
- add integration tests with mocked ConnectWise responses

## Security

Do not commit real `.env` files. Use Azure Container App secrets or Key Vault in production.
