#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:-connectwise-manage-mcp:test}"
NAME="${SMOKE_CONTAINER_NAME:-cwmcp-smoke-$RANDOM}"
PORT="${SMOKE_PORT:-18000}"
TOKEN="${SMOKE_AUTH_TOKEN:-smoke-test-token}"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup

docker run -d \
  --name "$NAME" \
  -p "127.0.0.1:${PORT}:8000" \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  -e AUTH_ENABLED=true \
  -e AUTH_BEARER_TOKEN="$TOKEN" \
  -e CW_BASE_URL=https://cw.invalid/v4_6_release/apis/3.0 \
  -e CW_COMPANY_ID=smoke \
  -e CW_PUBLIC_KEY=smoke-public \
  -e CW_PRIVATE_KEY=smoke-private \
  -e CW_CLIENT_ID=smoke-client \
  "$IMAGE" >/dev/null

base="http://127.0.0.1:${PORT}"

for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "$base/health" >/tmp/cwmcp-health.json 2>/dev/null; then
    break
  fi
  # /health may return 502 with fake upstream credentials once the app is ready.
  status="$(curl -sS -o /tmp/cwmcp-health.json -w '%{http_code}' --max-time 2 "$base/health" 2>/dev/null || true)"
  if [ "$status" = "502" ] || [ "$status" = "503" ]; then
    break
  fi
  sleep 1
done

health_status="$(curl -sS -o /tmp/cwmcp-health.json -w '%{http_code}' --max-time 5 "$base/health")"
case "$health_status" in
  200|502|503) ;;
  *) echo "Expected /health to be reachable, got HTTP $health_status" >&2; cat /tmp/cwmcp-health.json >&2; exit 1 ;;
esac

unauth_status="$(curl -sS -o /tmp/cwmcp-unauth.json -w '%{http_code}' --max-time 5 "$base/mcp")"
if [ "$unauth_status" != "401" ]; then
  echo "Expected unauthenticated /mcp to return 401, got HTTP $unauth_status" >&2
  cat /tmp/cwmcp-unauth.json >&2
  exit 1
fi

auth_status="$(curl -sS -o /tmp/cwmcp-auth.json -w '%{http_code}' --max-time 5 -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" "$base/mcp")"
case "$auth_status" in
  200|202|400|404|405|406) ;;
  401|403) echo "Expected authenticated /mcp not to be rejected, got HTTP $auth_status" >&2; cat /tmp/cwmcp-auth.json >&2; exit 1 ;;
  *) echo "Unexpected authenticated /mcp status HTTP $auth_status" >&2; cat /tmp/cwmcp-auth.json >&2; exit 1 ;;
esac

echo "Runtime smoke tests passed for $IMAGE"
