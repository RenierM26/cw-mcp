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

Recommended secret mapping in Container Apps:
- env `CW_PUBLIC_KEY` -> secret `cw-public-key`
- env `CW_PRIVATE_KEY` -> secret `cw-private-key`

## Suggested networking model

If n8n is already in Azure, the cleanest path is:
- place this app in the same Container Apps environment as n8n, or at least the same VNet-connected environment
- expose this service with **internal ingress**
- have n8n connect to the internal FQDN

If that is awkward, external ingress also works, but then you should put simple auth and IP restrictions in front of it.

## MCP endpoint

The MCP endpoint is:

```text
https://<your-app-fqdn>/mcp
```

Health endpoint:

```text
https://<your-app-fqdn>/health
```

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
    cw-private-key='<your-private-key>'
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
    CW_BASE_URL='https://your-company.connectwise.com/v4_6_release/apis/3.0' \
    CW_COMPANY_ID='your_company_id' \
    CW_CLIENT_ID='your_client_id' \
    CW_API_VERSION=2024.1 \
    CW_TIMEOUT_SECONDS=30 \
    CW_PAGE_SIZE=50 \
    CW_MAX_PAGE_SIZE=100 \
    CW_PUBLIC_KEY=secretref:cw-public-key \
    CW_PRIVATE_KEY=secretref:cw-private-key
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

If n8n sits in the same private environment, prefer the internal URL. That keeps the ConnectWise wrapper off the public internet.

## Operational advice

- start with one replica until behavior is stable
- keep request timeouts conservative, ConnectWise can be slow and annoying
- use lookup tools before classification updates to reduce bad writes
- keep logs on, but do not log raw secrets
- if you later expose it externally, add auth before broad use

## Good first smoke tests

After deployment, verify:

1. `GET /health`
2. MCP client can connect to `/mcp`
3. `list_boards`
4. `search_members`
5. `get_ticket_bundle` on a safe test ticket
6. `add_ticket_note` on a test ticket
7. `add_ticket_time_entry` on a test ticket
