# Azure Container Apps deployment notes

These notes are tuned for the current `connectwise-manage-mcp` scaffold and an existing n8n deployment in Azure.

## Recommended shape

- **Azure Container Apps** for the MCP server
- **Azure Container Registry** for the image
- **Container App environment** shared with n8n if possible
- **Internal ingress** if only n8n and private clients need access
- **Secrets** stored as Container App secrets, optionally sourced from Key Vault later

## Runtime settings

Container:
- target port: `8000`
- ingress: `internal` preferred, `external` only if you really need it
- min replicas: `1` if you want low-latency always-on behavior
- max replicas: `1` or low single digits to start
- CPU/memory: start small, for example `0.5 vCPU` and `1Gi`

Environment variables:
- `TRANSPORT=http`
- `HOST=0.0.0.0`
- `PORT=8000`
- `LOG_LEVEL=INFO`
- `AUTH_ENABLED=true`
- `AUTH_ALLOWED_IPS` (optional, comma-separated IPs or CIDRs)
- `AUTH_TRUST_X_FORWARDED_FOR=true` when you want to enforce the allowlist using proxy-forwarded client IPs
- `CW_BASE_URL`
- `CW_COMPANY_ID`
- `CW_CLIENT_ID`
- `CW_API_VERSION=2024.1`
- `CW_TIMEOUT_SECONDS=30`
- `CW_PAGE_SIZE=50`
- `CW_MAX_PAGE_SIZE=100`

Secrets:
- `CW_PUBLIC_KEY`
- `CW_PRIVATE_KEY`
- `AUTH_BEARER_TOKEN`

Recommended secret mapping in Container Apps:
- env `CW_PUBLIC_KEY` -> secret `cw-public-key`
- env `CW_PRIVATE_KEY` -> secret `cw-private-key`
- env `AUTH_BEARER_TOKEN` -> secret `auth-bearer-token`

## Suggested networking model

If n8n is already in Azure, the cleanest path is:
- place this app in the same Container Apps environment as n8n, or at least the same VNet-connected environment
- expose this service with **internal ingress**
- have n8n connect to the internal FQDN

If that is awkward, external ingress also works, but then you should keep bearer auth enabled and preferably configure both platform-side restrictions and `AUTH_ALLOWED_IPS`.

## MCP endpoint

The MCP endpoint is:

```text
https://<your-app-fqdn>/mcp
```

Liveness endpoint:

```text
https://<your-app-fqdn>/live
```

Readiness/upstream health endpoint:

```text
https://<your-app-fqdn>/health
```

Authentication:
- `/mcp` should require `Authorization: Bearer <AUTH_BEARER_TOKEN>`
- `/live` is left open for platform liveness probes and does not call ConnectWise
- `/health` is left open for readiness checks that include ConnectWise reachability
- `/health` intentionally returns only minimal operational status and does not expose raw ConnectWise system details
- if `AUTH_ALLOWED_IPS` is set, `/mcp` will also enforce the configured IP or CIDR allowlist

## Azure CLI example

Assumes these already exist:
- resource group
- Container Apps environment
- Azure Container Registry

Set variables:

```bash
RG=rg-your-name
ENV_NAME=cae-your-env
APP_NAME=connectwise-manage-mcp
ACR_NAME=youracrname
IMAGE=youracrname.azurecr.io/connectwise-manage-mcp:latest
```

Create secrets:

```bash
az containerapp secret set \
  --name "$APP_NAME" \
  --resource-group "$RG" \
  --secrets \
    cw-public-key='<your-public-key>' \
    cw-private-key='<your-private-key>' \
    auth-bearer-token='<your-long-random-bearer-token>'
```

Create the app:

```bash
az containerapp create \
  --name "$APP_NAME" \
  --resource-group "$RG" \
  --environment "$ENV_NAME" \
  --image "$IMAGE" \
  --target-port 8000 \
  --ingress internal \
  --min-replicas 1 \
  --max-replicas 1 \
  --cpu 0.5 \
  --memory 1.0Gi \
  --registry-server "$ACR_NAME.azurecr.io" \
  --env-vars \
    TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8000 \
    LOG_LEVEL=INFO \
    AUTH_ENABLED=true \
    AUTH_ALLOWED_IPS='203.0.113.10,198.51.100.0/24' \
    AUTH_TRUST_X_FORWARDED_FOR=true \
    CW_BASE_URL='https://your-company.connectwise.com/v4_6_release/apis/3.0' \
    CW_COMPANY_ID='your_company_id' \
    CW_CLIENT_ID='your_client_id' \
    CW_API_VERSION=2024.1 \
    CW_TIMEOUT_SECONDS=30 \
    CW_PAGE_SIZE=50 \
    CW_MAX_PAGE_SIZE=100 \
    CW_PUBLIC_KEY=secretref:cw-public-key \
    CW_PRIVATE_KEY=secretref:cw-private-key \
    AUTH_BEARER_TOKEN=secretref:auth-bearer-token
```

Update the image later:

```bash
az containerapp update \
  --name "$APP_NAME" \
  --resource-group "$RG" \
  --image "$IMAGE"
```

## GitHub Actions notes

A practical production path is:
- build image in GitHub Actions
- push to ACR or GHCR
- deploy to Container Apps on `main`

If you use ACR instead of GHCR, you will probably want:
- `AZURE_CREDENTIALS`
- `AZURE_CONTAINERAPP_NAME`
- `AZURE_RESOURCE_GROUP`
- `AZURE_ACR_NAME`

## n8n connection note

For n8n MCP usage, point it at:

```text
https://<your-app-fqdn>/mcp
```

And send this header:

```text
Authorization: Bearer <AUTH_BEARER_TOKEN>
```

If you also enable `AUTH_ALLOWED_IPS`, make sure the allowlist contains the public egress IP or CIDR used by n8n or your gateway.

If n8n sits in the same private environment, prefer the internal URL. That keeps the ConnectWise wrapper off the public internet.

## Operational advice

- start with one replica until behavior is stable
- keep request timeouts conservative, ConnectWise can be slow and annoying
- use lookup tools before classification updates to reduce bad writes
- keep logs on, but do not log raw secrets
- if you later expose it externally, keep auth enabled, rotate the bearer token like any other secret, and consider `AUTH_ALLOWED_IPS` a second control rather than a replacement for private ingress

## Good first smoke tests

After deployment, verify:

1. `GET /live` for liveness
2. `GET /health` for readiness
2. MCP client can connect to `/mcp` with the bearer token
3. `list_boards`
4. `search_members`
5. `get_ticket_bundle` on a safe test ticket
6. `add_ticket_note` on a test ticket
7. `add_ticket_time_entry` on a test ticket
