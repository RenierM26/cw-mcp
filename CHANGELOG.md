# Changelog

All notable changes to this project should be documented in this file.

This project follows a lightweight [Keep a Changelog](https://keepachangelog.com/) style. Versions should use semantic version tags such as `v0.1.0`.

## [Unreleased]

### Added

- Added `update_ticket_classifications_fast` for high-volume automation flows that already know valid ticket classification values and need to avoid preflight read/lookup calls.
- `update_ticket_classifications` now accepts numeric `board_id` to move tickets without first resolving the board name.
- Preflight configuration CLI (`cwmcp-preflight`) for local/deployment validation without calling ConnectWise.
- CI gates for Ruff, mypy, pytest, Docker image build, and runtime container smoke testing.
- CodeQL analysis and Trivy container vulnerability scanning.
- Dependabot configuration for Python dependencies and GitHub Actions.
- Hardened Docker runtime defaults, including non-root execution and removal of package/build tooling from the final image.
- Hardened Docker Compose deployment example and deployment documentation.
- Release workflow for semver-tagged GitHub Releases and GHCR images.
- Runtime smoke-test script for local and CI container validation.
- Production deployment, security model, and release/deploy checklist documentation.
- Early environment/configuration validation with clear startup errors.
- Package metadata including license expression, project URLs, keywords, and classifiers.
- Separate `/live` liveness endpoint and `/health` readiness/upstream health endpoint.
- Issue templates, pull request template, and security policy.

### Changed

- GitHub Actions Docker actions updated to newer Node 24-compatible releases.
- Release workflow now publishes `latest`; default-branch builds publish `main` and `sha-*` only.
- Release workflow now renders GitHub release notes from `CHANGELOG.md`.
- Docker and Compose probe guidance now uses `/live` for liveness and `/health` for ConnectWise readiness.
- Deployment guidance recommends pinned release/SHA image tags instead of relying on `latest`.

### Security

- `/mcp` remains protected by bearer authentication when `AUTH_ENABLED=true`.
- Optional IP/CIDR allowlisting is documented for `/mcp`.
- Final runtime image no longer retains `pip`, `setuptools`, or `wheel` metadata/tooling.

## [0.1.0] - Initial project version

### Added

- FastMCP server for ConnectWise Manage ticket-focused workflows.
- HTTP and stdio transports.
- Bearer-token middleware and optional IP allowlist.
- ConnectWise client wrapper with central auth, request, and error handling.
- Health endpoint for configuration and ConnectWise reachability checks.
- Ticket, company, contact, board lookup, member, work type, and work role tools.
- Initial tests, Dockerfile, README, and Azure Container Apps notes.
