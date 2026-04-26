# Docker Compose deployment

This is the simplest self-hosted deployment path for `connectwise-manage-mcp`.

## 1. Prepare configuration

Copy the example environment file and fill in real values:

```bash
cp .env.example .env
```

Required values:

- `CW_BASE_URL`
- `CW_COMPANY_ID`
- `CW_PUBLIC_KEY`
- `CW_PRIVATE_KEY`
- `CW_CLIENT_ID`
- `AUTH_BEARER_TOKEN`

Use a long random bearer token. Treat it like a password.

## 2. Start the service

```bash
docker compose -f compose.example.yml up -d
```

The service listens on port `8000` by default:

```text
http://localhost:8000/mcp
http://localhost:8000/health
```

## 3. Recommended production shape

Prefer putting this service behind a reverse proxy or private network rather than exposing it directly.

Good defaults:

- keep `AUTH_ENABLED=true`
- use HTTPS at the proxy layer
- restrict source IPs at the proxy/firewall where possible
- optionally set `AUTH_ALLOWED_IPS` for an additional application-level allowlist
- keep `.env` out of git
- deploy immutable image tags when practical, for example a Git SHA tag instead of `latest`

## 4. Compose hardening included

The example Compose file applies conservative container hardening:

- runs the image's non-root user
- read-only root filesystem
- temporary writable `/tmp`
- drops Linux capabilities
- disables privilege escalation
- enables a health check

The health check calls `/health`, which verifies both local configuration and ConnectWise reachability. If ConnectWise is down or credentials are wrong, the container will report unhealthy.

## 5. Updating

With the default `latest` tag:

```bash
docker compose -f compose.example.yml pull
docker compose -f compose.example.yml up -d
```

For stricter production deployments, replace `latest` with the SHA tag published by GitHub Actions.
