#!/bin/sh
# Is the studio connector alive from the outside? Used by release.sh on the VPS (with
# --resolve to this machine) and by the deploy workflow from a runner. Holds no credential:
#   1. GET /healthz answers 200 - the server reads its store;
#   2. GET /.well-known/oauth-protected-resource/mcp answers 200 - the OAuth routes are up;
#   3. a keyless POST /mcp initialize passes the DNS-rebinding guard (a wrong Host is 421) and
#      gets 401 with `WWW-Authenticate: Bearer resource_metadata=...` - the challenge
#      claude.ai follows to sign in.
# The transport behind the OAuth front is proven by `http_app probe` inside the container
# (release.sh), the way the harness proves it with its probe key.
#
#   probe.sh <base-url> [curl args, e.g. --resolve host:443:127.0.0.1]
# Exit 0 alive; 1 not.
set -u
[ $# -ge 1 ] || { echo "usage: probe.sh <base-url> [curl args]" >&2; exit 2; }
base=${1%/}
shift
work=$(mktemp -d) || exit 1
trap 'rm -rf "$work"' EXIT
INITIALIZE='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"studio-probe","version":"1"}}}'

code=$(curl -sS --max-time 5 "$@" -o "$work/body" -w '%{http_code}' "$base/healthz" 2>/dev/null)
[ "$code" = "200" ] || { echo "probe: /healthz answered ${code:-nothing}"; exit 1; }

code=$(curl -sS --max-time 5 "$@" -o "$work/body" -w '%{http_code}' \
  "$base/.well-known/oauth-protected-resource/mcp" 2>/dev/null)
if [ "$code" != "200" ] || ! grep -q '"authorization_servers"' "$work/body"; then
  echo "probe: resource metadata answered ${code:-nothing}"
  exit 1
fi

code=$(curl -sS --max-time 5 "$@" -D "$work/head" -o "$work/body" -w '%{http_code}' \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  --data "$INITIALIZE" "$base/mcp" 2>/dev/null)
if [ "$code" != "401" ] || ! grep -qi '^www-authenticate: Bearer resource_metadata=' "$work/head"; then
  echo "probe: keyless /mcp answered ${code:-nothing} (want 401 with the OAuth challenge)"
  exit 1
fi
echo "probe: /healthz 200, OAuth metadata 200, /mcp 401 with the sign-in challenge"
