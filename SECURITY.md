# Security Policy

## Supported versions

This project is early-stage. Security fixes are applied to the default branch and should be consumed by deploying the latest passing release or a known-good SHA image.

Recommended production practice:

- pin deployments to a release tag or SHA tag
- keep Dependabot PRs reviewed and merged when CI/security checks pass
- rerun the `security` workflow after security-sensitive dependency or image changes

## Reporting a vulnerability

Please do not open a public issue containing live secrets, ConnectWise credentials, bearer tokens, customer data, or exploit payloads against real systems.

Preferred reporting paths:

1. Use GitHub private vulnerability reporting if enabled for this repository.
2. If private reporting is not available, open a minimal public issue using the security template and keep details high-level until a private channel is arranged.

A useful report includes:

- affected version, image tag, or commit SHA
- whether the issue affects HTTP transport, stdio transport, container image, dependencies, logging, or ConnectWise API handling
- expected impact
- safe reproduction notes using redacted or synthetic data
- suggested remediation, if known

## Secret handling

Never include these in issues, PRs, logs, screenshots, or examples:

- `CW_PUBLIC_KEY`
- `CW_PRIVATE_KEY`
- `CW_CLIENT_ID` when tenant-specific
- `AUTH_BEARER_TOKEN`
- customer names, ticket contents, contact data, notes, or time entries from a real tenant

Use synthetic examples in docs, tests, screenshots, and bug reports.

## Security controls in this repository

The repository currently uses:

- bearer-token protection for `/mcp`
- optional IP/CIDR allowlisting for `/mcp`
- unauthenticated `/live` for lightweight liveness probes
- unauthenticated `/health` for minimal readiness/upstream checks
- non-root container runtime
- runtime image cleanup to remove package-management/build tooling
- Docker runtime smoke tests in CI
- Ruff, mypy, and pytest gates
- CodeQL analysis
- Trivy container scanning
- Dependabot for Python and GitHub Actions updates
- branch protection on `main`

## Deployment security checklist

Before exposing the service beyond a private network:

- keep `AUTH_ENABLED=true`
- use HTTPS at the proxy/platform layer
- use a long random `AUTH_BEARER_TOKEN`
- store credentials as platform secrets, not plain files in the repo
- restrict source IPs at the firewall, proxy, platform, or `AUTH_ALLOWED_IPS`
- prefer private/internal ingress for Azure Container Apps or equivalent platforms
- verify `/live`, then `/health`, then a safe read-only MCP tool
