# Documentation

Operational docs for `connectwise-manage-mcp`:

- [Docker Compose deployment](DOCKER_COMPOSE.md)
- [Azure Container Apps deployment notes](AZURE_CONTAINER_APPS.md)

Start with Docker Compose for self-hosted deployments, or Azure Container Apps when running alongside n8n or other Azure-hosted MCP clients.

## Image tag policy

- `latest` is reserved for the newest stable GitHub Release.
- default-branch builds publish `main` and `sha-*` tags, not `latest`.
- production deployments should prefer a version tag such as `v0.1.0` or a `sha-*` tag.
- the GHCR cleanup workflow removes old untagged package versions while preserving release, `latest`, `main`, and SHA tags.
