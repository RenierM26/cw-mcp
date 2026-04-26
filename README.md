# ConnectWise Manage MCP

A small FastMCP server that gives n8n or any MCP-capable client a cleaner way to work with ConnectWise Manage.

This scaffold is intentionally narrow and practical:
- ticket-focused v1
- HTTP-friendly for Azure deployment
- stdio-friendly for local testing
- central auth/retry/query logic in one place
- lightweight health checks for container and platform probes

The repository is aimed at two main use cases:
- an MCP server that AI agents can call over HTTP or stdio
- a small, readable codebase you can safely adapt for your own ConnectWise tenant


## Production deployment at a glance

For production, treat this as a small private API service that happens to speak MCP:

- run the container image from GHCR
- keep `AUTH_ENABLED=true`
- use a long random `AUTH_BEARER_TOKEN`
- store ConnectWise keys and bearer tokens as platform secrets
- prefer private/internal ingress; if exposed externally, put it behind HTTPS and source restrictions
- pin deployments to a release tag or SHA tag instead of relying on `latest`

Useful docs:

- [Docker Compose deployment](docs/DOCKER_COMPOSE.md)
- [Azure Container Apps notes](docs/AZURE_CONTAINER_APPS.md)

Published image:

```text
ghcr.io/renierm26/connectwise-manage-mcp:latest
```

For repeatable deployments, prefer a versioned image once releases are cut:

```text
ghcr.io/renierm26/connectwise-manage-mcp:v0.1.0
```

## Security model

The HTTP transport exposes two important routes:

- `/mcp` — protected by bearer-token middleware when `AUTH_ENABLED=true`
- `/live` — unauthenticated liveness check for platform/container probes; does not call ConnectWise
- `/health` — unauthenticated readiness/upstream check; verifies configuration and ConnectWise reachability, but returns only minimal operational status

Additional controls:

- `AUTH_ALLOWED_IPS` can restrict `/mcp` to specific IPs or CIDR ranges
- `AUTH_TRUST_X_FORWARDED_FOR=true` can be used behind trusted proxies when enforcing forwarded client IPs
- the Docker image runs as a non-root user
- the Compose example uses a read-only filesystem, drops capabilities, and disables privilege escalation
- CI runs unit tests, type checks, linting, container startup/auth smoke tests, CodeQL, and Trivy scanning

Do not commit `.env` files or real ConnectWise credentials.

## Release and deploy checklist

Before promoting a deployment:

1. Confirm the target commit has green CI and security checks.
2. Prefer a release tag such as `v0.1.0`, or use the Git SHA image tag.
3. Update the runtime platform to the selected image tag.
4. Verify `/live` after deployment, then `/health` for upstream readiness.
5. Verify your MCP client can connect to `/mcp` with the bearer token.
6. Run a safe read-only tool first, for example `list_boards` or `search_members`.


## Architecture at a glance

The request flow is intentionally simple:

1. an MCP client calls a tool exposed by FastMCP
2. the tool function in `src/connectwise_manage_mcp/tools/` validates and shapes arguments
3. `ConnectWiseClient` builds the request, auth headers, and query conditions
4. the ConnectWise Manage REST API returns raw data
5. the tool returns both a compact summary and the raw payload when useful

That split keeps the codebase easy to reason about:
- `server.py` handles transport and health checks
- `tools/` handles MCP-facing workflows
- `connectwise/client.py` handles API communication
- `models.py` holds lightweight shared shapes
- `config.py` centralizes environment-backed settings

## Common call sequences for smaller models

If you are choosing tools programmatically, these flows are the safest starting points.

### Create a ticket

1. `search_companies` to find the numeric `company_id`
2. optional `search_contacts` to find the numeric `contact_id`
3. optional `list_boards` if the correct board name is uncertain
4. `create_ticket`

### Update ticket status safely

1. `get_ticket` to inspect the current board
2. `list_boards` if you need to confirm the board id
3. `get_board_statuses` or `get_board_lookup` to fetch valid board-specific status names
4. `update_ticket_status`

### Reclassify a ticket safely

1. `get_ticket` to inspect current values
2. `list_boards` to find the numeric board id
3. `get_board_lookup` to fetch valid status, type, subtype, item, and team names
4. if changing hierarchy fields, choose them in order: `type_name` -> `sub_type_name` -> `item_name`
5. optional `get_board_subtypes` or `get_board_items` for narrower hierarchy checks
6. `update_ticket_classifications`

Small-model hint: `item_name` is not a board-wide independent choice. It only becomes valid after a matching `type_name` and `sub_type_name` are chosen.

### Add a time entry safely

1. `search_members` to find the `member_identifier`
2. optional `list_locations` when ConnectWise location restrictions apply and the default location may need to be overridden
3. `list_work_types` to validate `work_type`
4. `list_work_roles` to validate `work_role`
5. `add_ticket_time_entry`

Small-model hint: if a time-entry create fails with a location-related error, the recovery path should be `list_locations` and then retry `add_ticket_time_entry` with an allowed numeric `location_id`.

## Names vs ids

ConnectWise write calls mix numeric ids and human-readable names. This is the easiest place for smaller models to make mistakes.

- `company_id` and `contact_id` are numeric ids
- `board_id`, `type_id`, and `subtype_id` are numeric ids used by lookup tools
- `board` in `create_ticket` is a board name, not a board id
- `status` in `update_ticket_status` is a board-specific status name, not a status id
- `board`, `status`, `type_name`, `sub_type_name`, `item_name`, `team`, `severity`, `impact`, and `source` in `update_ticket_classifications` are names, not ids
- `type_name`, `sub_type_name`, and `item_name` in `update_ticket_classifications` are a hierarchy, not three independent fields
- choose `type_name` first, then `sub_type_name`, then `item_name`
- `member_identifier` in `add_ticket_time_entry` is a string identifier, not the numeric member id
- `location_id` in `add_ticket_time_entry` is a numeric location id
- `work_type` and `work_role` in `add_ticket_time_entry` are names, not ids

## Tool response patterns

Most tools follow one of these response shapes.

### Single-record reads

```json
{
  "ok": true,
  "data": {"...": "raw record"},
  "summary": {"...": "compact normalized view"}
}
```

### Search and list tools

```json
{
  "ok": true,
  "count": 2,
  "data": [{"...": "compact normalized view"}],
  "raw": [{"...": "raw records"}]
}
```

### Bundle tools

```json
{
  "ok": true,
  "ticket": {"summary": {}, "description": "...", "raw": {}},
  "notes": {"count": 0, "data": [], "raw": []},
  "timeEntries": {"count": 0, "data": [], "raw": []}
}
```

## Which read tool to choose

When several read tools look similar, use the narrowest tool that answers the question.

- use `search_tickets` when you do not know the ticket id yet
- use `get_ticket` when you know the ticket id and only need the current ticket record
- use `get_ticket_bundle` when you know the ticket id and need ticket details plus notes and time entries together
- use `get_ticket_notes` when you only need notes
- use `get_ticket_time_entries` when you only need time entries
- use `get_company` when you already know `company_id`
- use `search_companies` when you only know a company name or identifier fragment
- use `search_contacts` when you need a numeric `contact_id`

## Common write recovery paths

If a write fails validation or a required value is unknown, use the matching lookup tool and retry.

- unknown `company_id` for `create_ticket` -> `search_companies`
- unknown `contact_id` for `create_ticket` -> `search_contacts`
- invalid status for `update_ticket_status` -> `get_ticket`, then `get_board_statuses` or `get_board_lookup`
- invalid board, type, subtype, item, or team for `update_ticket_classifications` -> `get_ticket`, optional `list_boards`, then `get_board_lookup`
- unknown `member_identifier` for `add_ticket_time_entry` -> `search_members`
- unknown `work_type` for `add_ticket_time_entry` -> `list_work_types`
- unknown `work_role` for `add_ticket_time_entry` -> `list_work_roles`
- location-restriction error or unknown `location_id` for `add_ticket_time_entry` -> `list_locations`

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
- `get_board_statuses`
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
├── scripts/
├── tests/
├── .dockerignore
├── .env.example
├── .env.azure.example
├── compose.example.yml
├── Dockerfile
├── pyproject.toml
└── README.md
```


## Operations quick links

- Local HTTP endpoint: `http://localhost:8000/mcp`
- Liveness endpoint: `http://localhost:8000/live`
- Readiness/upstream health endpoint: `http://localhost:8000/health`
- Compose example: `compose.example.yml`
- Runtime smoke test: `scripts/runtime-smoke.sh`
- CI workflow: `.github/workflows/ci.yml`
- Security workflow: `.github/workflows/security.yml`
- Release workflow: `.github/workflows/release.yml`
- Security policy: `SECURITY.md`
- Changelog: `CHANGELOG.md`

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
- `AUTH_BEARER_TOKEN`
- optionally `AUTH_ALLOWED_IPS`

Auth defaults to enabled. For normal Docker, VM, or Azure deployments, leave it that way and use a long random bearer token.
The devcontainer disables auth automatically for local VS Code work.
If you expose the service publicly, adding `AUTH_ALLOWED_IPS` gives you a second safety layer on top of the bearer token.

Example base URL:

```text
https://your-company.connectwise.com/v4_6_release/apis/3.0
```

### 3. Install dependencies and run locally

#### With uv

```bash
uv sync
uv run cwmcp-http
```

#### With pip

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

Liveness endpoint:

```text
http://localhost:8000/live
```

Readiness/upstream health endpoint:

```text
http://localhost:8000/health
```

Notes:
- `GET /live` is browser-friendly, returns JSON, and does not call ConnectWise.
- `GET /health` is browser-friendly, returns JSON, and checks configuration plus ConnectWise reachability.
- `/health` is intentionally minimal and does not echo raw ConnectWise tenant or licensing details.
- `GET /mcp` is not a normal human web page. A plain browser request can return a protocol-level error like `406 Not Acceptable`, which is expected for FastMCP HTTP transport.
- When auth is enabled, MCP clients must send `Authorization: Bearer <AUTH_BEARER_TOKEN>` for `/mcp` requests.
- If `AUTH_ALLOWED_IPS` is set, only those source IPs or CIDR ranges can reach `/mcp`.

## Run in stdio mode

Useful for local MCP testing or editor integrations that prefer stdio transport:

```bash
cwmcp-stdio
```

## FastMCP CLI test examples

These examples are useful when you want to test the server without wiring a full client first.

### Inspect the local server from source

```bash
./.venv/bin/fastmcp inspect src/connectwise_manage_mcp/server.py
```

### List available tools from source

```bash
./.venv/bin/fastmcp list src/connectwise_manage_mcp/server.py
```

### Call a tool directly from source

```bash
./.venv/bin/fastmcp call src/connectwise_manage_mcp/server.py get_ticket --input-json '{"ticket_id": 12345}' --json
```

### Run the server with FastMCP itself over HTTP

```bash
./.venv/bin/fastmcp run src/connectwise_manage_mcp/server.py --transport http --host 127.0.0.1 --port 8000
```

### List tools from a running HTTP endpoint

```bash
./.venv/bin/fastmcp list http://127.0.0.1:8000/mcp --auth 'super-secret-token'
```

### Call a tool on a running HTTP endpoint

```bash
./.venv/bin/fastmcp call http://127.0.0.1:8000/mcp get_board_types --input-json '{"board_id": 12}' --auth 'super-secret-token' --json
```

### Open the FastMCP inspector for local development

```bash
./.venv/bin/fastmcp dev inspector src/connectwise_manage_mcp/server.py
```

Practical notes:
- source-based commands are handy before env vars or containers are fully wired
- HTTP-based commands are handy for validating the real deployed transport path
- if auth is enabled, pass the bearer token with `--auth '<token>'`
- if the server is not configured, tool calls will fail cleanly and `/health` will explain why

## Run in Docker

```bash
docker build -t connectwise-manage-mcp .
docker run --rm -p 8000:8000 --env-file .env connectwise-manage-mcp
```

Container/platform probes should generally target:
- `/live` for liveness checks that should not depend on ConnectWise availability
- `/health` for readiness checks that should include configuration and ConnectWise reachability
- `/mcp` only for actual MCP clients with a bearer token, and from allowed IPs if an allowlist is configured

## Run in VS Code devcontainer

The included devcontainer is set up to:
- install the project in editable mode
- forward container port `8000`
- auto-start `cwmcp-http` when the container starts
- disable bearer auth by default for local VS Code development

After reopening in the devcontainer, useful checks are:

```bash
cat /tmp/cwmcp-http.log
curl http://127.0.0.1:8000/live
curl http://127.0.0.1:8000/health
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

## n8n and MCP client usage

### Option 1, MCP-aware client path
Use an MCP-capable client or gateway that can connect to:

```text
https://your-service-url/mcp
```

When auth is enabled, send:

```text
Authorization: Bearer <AUTH_BEARER_TOKEN>
```

### Option 2, plain HTTP helper routes
If you later add your own custom helper endpoints, n8n can call those with standard HTTP Request nodes. In the current scaffold, the custom helper routes are:

```text
GET /live
GET /health
```

That means the main `/mcp` endpoint should be treated as MCP transport, not as a generic REST endpoint.

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
2. `get_board_statuses` or `get_board_lookup`
3. optionally `get_board_types`, `get_board_subtypes`, or `get_board_items` for explicit hierarchy calls
4. `update_ticket_classifications`

The safest time-entry flow is usually:
1. `search_members`
2. `list_work_types`
3. `list_work_roles`
4. `add_ticket_time_entry`

A typical triage flow is:
1. `get_ticket_bundle`
2. decide on board/status/type updates
3. `update_ticket_classifications`
4. `add_ticket_note` if you want to record the action taken

## Example tool calls and results

These are intentionally small, human-readable examples of the shapes this server returns.
Exact fields from ConnectWise can vary by tenant.

### Example: `get_ticket_bundle`

Tool call arguments:

```json
{
  "ticket_id": 12345,
  "notes_page_size": 10,
  "time_entries_page_size": 10
}
```

Example result excerpt:

```json
{
  "ok": true,
  "ticket": {
    "summary": {
      "id": 12345,
      "summary": "User cannot access VPN",
      "board": "Service Desk",
      "status": "New",
      "type": "Incident",
      "subType": "Remote Access",
      "item": "VPN",
      "priority": "Priority 2",
      "company": "Example Co",
      "contact": "Jane Smith",
      "owner": "helpdesk1",
      "updatedAt": "2026-04-20T16:00:00Z"
    },
    "description": "User reports VPN login failures after password reset.",
    "raw": { "...": "full ticket payload" }
  },
  "notes": {
    "count": 2,
    "data": [
      {
        "id": 555,
        "text": "Reset VPN profile and requested retest.",
        "createdBy": "helpdesk1",
        "createdAt": "2026-04-20T15:40:00Z",
        "internal": true,
        "detail": true,
        "resolution": false
      }
    ],
    "raw": [
      { "...": "full note payload" }
    ]
  },
  "timeEntries": {
    "count": 1,
    "data": [
      {
        "id": 777,
        "member": "helpdesk1",
        "timeStart": "2026-04-20T15:30:00Z",
        "timeEnd": "2026-04-20T15:45:00Z",
        "actualHours": 0.25,
        "hoursDeduct": 0.25,
        "billableOption": "Billable",
        "workType": "Remote Support",
        "workRole": "Engineer",
        "notes": "Investigated VPN reset issue.",
        "internalNotes": null
      }
    ],
    "raw": [
      { "...": "full time entry payload" }
    ]
  }
}
```

### Example: `update_ticket_classifications`

Tool call arguments:

```json
{
  "ticket_id": 12345,
  "status": "In Progress",
  "type_name": "Incident",
  "sub_type_name": "Remote Access",
  "item_name": "VPN",
  "priority": "Priority 2"
}
```

Example result excerpt:

```json
{
  "ok": true,
  "ticketId": 12345,
  "updated": {
    "status": "In Progress",
    "priority": "Priority 2",
    "board": null,
    "type": "Incident",
    "subType": "Remote Access",
    "item": "VPN",
    "team": null,
    "severity": null,
    "impact": null,
    "source": null
  },
  "data": {
    "...": "raw patch response"
  }
}
```

### Example: `get_board_lookup`

Tool call arguments:

```json
{
  "board_id": 12,
  "type_id": 3,
  "subtype_id": 9
}
```

Example result excerpt:

```json
{
  "ok": true,
  "boardId": 12,
  "statuses": [
    {
      "id": 1,
      "name": "New",
      "board": "Service Desk",
      "sort": 0,
      "closed": false,
      "inactive": false
    }
  ],
  "types": [
    {
      "id": 3,
      "name": "Incident",
      "inactive": false,
      "defaultFlag": true
    }
  ],
  "teams": [
    {
      "id": 4,
      "name": "Helpdesk",
      "location": "HQ",
      "department": "Support"
    }
  ],
  "subtypes": [
    {
      "id": 9,
      "name": "Remote Access",
      "inactive": false,
      "defaultFlag": false
    }
  ],
  "items": [
    {
      "id": 14,
      "name": "VPN",
      "inactive": false,
      "defaultFlag": false
    }
  ],
  "raw": {
    "...": "full lookup payloads"
  }
}
```

### Example: `add_ticket_time_entry`

Tool call arguments:

```json
{
  "ticket_id": 12345,
  "member_identifier": "helpdesk1",
  "time_start": "2026-04-20T15:30:00Z",
  "time_end": "2026-04-20T15:45:00Z",
  "actual_hours": 0.25,
  "hours_deduct": 0.25,
  "location_id": 7,
  "work_type": "Remote Support",
  "work_role": "Engineer",
  "notes": "Investigated VPN reset issue."
}
```

Example result excerpt:

```json
{
  "ok": true,
  "ticketId": 12345,
  "data": {
    "...": "raw time-entry payload"
  },
  "summary": {
    "id": 777,
    "member": "helpdesk1",
    "timeStart": "2026-04-20T15:30:00Z",
    "timeEnd": "2026-04-20T15:45:00Z",
    "actualHours": 0.25,
    "hoursDeduct": 0.25,
    "locationId": 7,
    "location": null,
    "billableOption": null,
    "workType": "Remote Support",
    "workRole": "Engineer",
    "notes": "Investigated VPN reset issue.",
    "internalNotes": null
  }
}
```

## Troubleshooting

### `/health` returns `503 Service Unavailable`

This usually means the server started, but the required ConnectWise environment variables are missing.
Check:
- `CW_BASE_URL`
- `CW_COMPANY_ID`
- `CW_PUBLIC_KEY`
- `CW_PRIVATE_KEY`
- `CW_CLIENT_ID`

### `/mcp` returns `406 Not Acceptable` in a browser

That is usually expected.
The `/mcp` route is an MCP transport endpoint, not a normal browser page.
Use an MCP client, FastMCP CLI, or check `/health` in a browser instead.

### VS Code forwards a port, but nothing answers on it

In the devcontainer flow, the container may be up before the MCP server has started.
Check:

```bash
cat /tmp/cwmcp-http.log
curl http://127.0.0.1:8000/health
```

If needed, restart the server inside the container:

```bash
pkill -f cwmcp-http || true
nohup cwmcp-http >/tmp/cwmcp-http.log 2>&1 &
```

### FastMCP CLI tool calls fail immediately

That usually means one of three things:
- the server is not configured yet
- the tool arguments do not match the expected JSON shape
- auth is enabled and the bearer token was not supplied

Try these first:

```bash
./.venv/bin/fastmcp inspect src/connectwise_manage_mcp/server.py
./.venv/bin/fastmcp list src/connectwise_manage_mcp/server.py
curl http://127.0.0.1:8000/health
```

### MCP endpoint returns `401 Unauthorized`

That usually means bearer auth is enabled and the client did not send the expected token.

For HTTP clients, send:

```text
Authorization: Bearer <AUTH_BEARER_TOKEN>
```

For FastMCP CLI, use:

```bash
./.venv/bin/fastmcp list http://127.0.0.1:8000/mcp --auth '<AUTH_BEARER_TOKEN>'
```

## First improvements I would make

- add board-specific status validation
- add `get_company_by_identifier`
- add `assign_ticket`
- add structured models for richer response validation
- add integration tests with mocked ConnectWise responses

## Security

Do not commit real `.env` files. Use Azure Container App secrets or Key Vault in production.

At minimum, treat these as secrets:
- `CW_PUBLIC_KEY`
- `CW_PRIVATE_KEY`
- `CW_CLIENT_ID`
- `AUTH_BEARER_TOKEN`

It is also worth limiting exposure of the HTTP transport. If only automation clients need access, prefer private networking or internal ingress over public internet exposure.
Even with bearer auth enabled, private ingress is still the better default when available.
For public exposure, a good pattern is bearer auth plus `AUTH_ALLOWED_IPS` for the known client or gateway egress ranges.
