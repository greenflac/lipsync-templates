"""The studio MCP server as a claude.ai CONNECTOR: streamable HTTP at /mcp behind OAuth.

WHY. As a project stdio server (`.mcp.json`) a cloud session starts it on the
session's own cold container, and it timed out on connect and could not be
reconnected from the app. A claude.ai connector is reached through
Anthropic's servers, runs warm on our machine, and is added once per person.

HOW. The same shape as the green-harness connector
(https://harness.greenflac.online/mcp, `harness/server_app/app.py`):

* the MCP SDK's streamable HTTP app, its OAuth routes (/register, /authorize,
  /token, /revoke, the two /.well-known documents) on our provider
  (`studio/mcp/oauth.py`) and our sign-in page at /oauth/login;
* one ASGI front in front of all of it that (a) answers a keyless /mcp with
  401 and a `WWW-Authenticate: Bearer resource_metadata=...` challenge, after
  the same DNS-rebinding host check the transport runs; (b) admits only a
  live OAuth access token; (c) rate-limits the OAuth paths and failed sign-ins
  per address; (d) reads every `tools/call` before the transport and, for the
  tools in `GUARDED`, refuses a call that has no signed-in user and records
  who called what (`ConnectorStore.record_call`) before the tool runs.
* Stateless and JSON responses: unlike the harness, the studio never asks
  the client anything mid-call (no elicitation), so it keeps no MCP sessions
  and there is no session to steal between users.

RUN

    python -m studio.mcp.http_app serve --port 8770           # loopback, no OAuth
    STUDIO_DOMAIN=studio.greenflac.online STUDIO_KEY_PEPPER_FILE=/run/secrets/pepper \\
        python -m studio.mcp.http_app serve --port 8770
    python -m studio.mcp.http_app new-user owner              # prints the key once
    python -m studio.mcp.http_app calls --limit 20            # who wrote / spent what

Without `STUDIO_DOMAIN` there is no OAuth: /mcp is open on the loopback for
local work, and every GUARDED tool is refused, because nobody is signed in.

ENVIRONMENT (secrets come from FILES only, as in the harness `config.secret`):

    STUDIO_DOMAIN             the public host name; turns OAuth on
    STUDIO_HOST               bind address; default 127.0.0.1 (the container sets 0.0.0.0)
    STUDIO_CONNECTOR_DB       the SQLite file; default work/connector.sqlite3
    STUDIO_KEY_PEPPER_FILE    the pepper keys and tokens are hashed under; REQUIRED with a domain
    STUDIO_VENDOR_ENV_FILE    NAME=value lines (GEMINI_API_KEY, ...) loaded into this
                              process only, so they are not in `docker inspect`
    STUDIO_TRUSTED_PROXIES    addresses/networks whose X-Forwarded-For is believed (Caddy)
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import os
import re
import secrets
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from studio.mcp.connector_store import PROBE_USER, ConnectorStore, StoreError

#: The tools that spend money or write the shared base, and what each does.
#: A call to one of them needs a signed-in user and leaves an attribution row.
#: `test_connector_http` checks every name here is a live tool, so a rename
#: cannot drop a tool out of the guard silently.
GUARDED: dict[str, str] = {
    "record_model_fact": "writes the knowledge base",
    "withdraw_model_fact": "writes the knowledge base",
    "propose_measurement": "writes the measurement proposals",
    "search_web": "spends the owner's search API key",
    "probe_model_limit": "calls a vendor API with the owner's key",
}

#: All the release probe may do (green-harness PROBE_METHODS): prove that the
#: transport behind the front answers, and nothing else.
PROBE_METHODS = ("initialize", "notifications/initialized", "tools/list", "ping")
PROBE_TOKEN_S = 60

DEFAULT_PORT = 8770
DEFAULT_DB = "work/connector.sqlite3"
LOOPBACK = "127.0.0.1"
PEPPER_MIN_CHARS = 32
OAUTH_PATHS = ("/register", "/authorize", "/token", "/revoke", "/oauth/login")
#: CHOSEN (harness constants): 60 OAuth requests per address, one back per
#: second; 10 failed sign-ins, one back per 30 s.
OAUTH_CAPACITY, OAUTH_REFILL_PER_S = 60, 1.0
LOGIN_CAPACITY, LOGIN_REFILL_PER_S = 10, 1 / 30
TOO_MANY = {"error": "too many requests from this address"}
_DOMAIN = re.compile(r"\A(?=.{1,253}\Z)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z")
_ENV_NAME = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


class ConfigError(ValueError):
    """The server refuses to start: the reason names the variable to fix."""


# - configuration (harness config.py, renamed) -


def allowed_domain(environ: Mapping[str, str]) -> str:
    value = environ.get("STUDIO_DOMAIN", "").strip().lower()
    if value and not _DOMAIN.match(value):
        raise ConfigError(
            f"STUDIO_DOMAIN {value!r} is not a plain host name (no scheme, port, path or wildcard)"
        )
    return value


def secret(environ: Mapping[str, str], name: str) -> str:
    """The content of the file `<name>_FILE`; a secret set as a variable is refused."""
    if environ.get(name):
        raise ConfigError(
            f"{name} is a secret and is read from a file only: set {name}_FILE to its path"
        )
    path = environ.get(f"{name}_FILE", "")
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").rstrip("\r\n")
    except OSError as exc:
        raise ConfigError(f"{name}_FILE: cannot read {path}: {exc.strerror}") from exc


def pepper(environ: Mapping[str, str], domain: str) -> str:
    value = secret(environ, "STUDIO_KEY_PEPPER")
    if domain and not value:
        raise ConfigError(
            "STUDIO_DOMAIN is set but STUDIO_KEY_PEPPER_FILE is not: a public server keeps "
            "keys and tokens hashed under a pepper"
        )
    if value and len(value) < PEPPER_MIN_CHARS:
        raise ConfigError(f"STUDIO_KEY_PEPPER_FILE: at least {PEPPER_MIN_CHARS} characters")
    return value


def trusted_proxies(environ: Mapping[str, str]) -> tuple[str, ...]:
    found = []
    for entry in environ.get("STUDIO_TRUSTED_PROXIES", "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError as exc:
            raise ConfigError(f"STUDIO_TRUSTED_PROXIES: {entry!r} is not an address") from exc
        found.append(entry)
    return tuple(found)


def load_vendor_env(environ: Mapping[str, str], target: dict[str, str] | Any = None) -> list[str]:
    """NAME=value lines of STUDIO_VENDOR_ENV_FILE into this process's environment.

    Returns the NAMES loaded (never the values). A name already set wins: the
    file fills gaps, it does not override the operator. Blank lines and `#`
    comments are skipped; any other line without a valid NAME= is refused,
    naming the line number only (the line may hold a key)."""
    target = os.environ if target is None else target
    path = environ.get("STUDIO_VENDOR_ENV_FILE", "")
    if not path:
        return []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"STUDIO_VENDOR_ENV_FILE: cannot read {path}: {exc.strerror}") from exc
    loaded = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not _ENV_NAME.match(name):
            raise ConfigError(f"STUDIO_VENDOR_ENV_FILE line {number}: not NAME=value")
        if name not in target:
            target[name] = value.strip().strip('"').strip("'")
            loaded.append(name)
    return loaded


# - rate limits (harness ratelimit.py, reduced) -


class Buckets:
    """A token bucket per address: `take` spends one, `has` only looks."""

    def __init__(self, capacity: float, refill_per_s: float, clock: Callable[[], float]) -> None:
        self.capacity, self.refill, self.clock = capacity, refill_per_s, clock
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def _level(self, address: str) -> float:
        level, at = self._state.get(address, (self.capacity, self.clock()))
        return min(self.capacity, level + (self.clock() - at) * self.refill)

    def has(self, address: str) -> bool:
        with self._lock:
            return self._level(address) >= 1

    def take(self, address: str) -> bool:
        with self._lock:
            level = self._level(address)
            if len(self._state) > 10_000:
                self._state.clear()
            if level < 1:
                self._state[address] = (level, self.clock())
                return False
            self._state[address] = (level - 1, self.clock())
            return True


def client_of(headers: Any, peer: str, trusted: tuple[str, ...]) -> str:
    """The client's address: the last X-Forwarded-For hop when the peer is a trusted proxy."""
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if any(peer_ip in ipaddress.ip_network(net, strict=False) for net in trusted):
        hops = [h.strip() for h in str(headers.get("x-forwarded-for", "")).split(",") if h.strip()]
        if hops:
            return hops[-1]
    return peer


def bearer(headers: Any) -> str:
    value = str(headers.get("authorization", "") or "")
    return value[len("Bearer ") :].strip() if value[:7].lower() == "bearer " else ""


# - the app -


def transport_security(domain: str = "") -> Any:
    """DNS-rebinding protection that admits the loopback and the public domain (harness F1)."""
    from mcp.server.transport_security import TransportSecuritySettings

    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", "127.0.0.1", "localhost", "[::1]"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    if domain:
        hosts += [domain, f"{domain}:*"]
        origins += [f"https://{domain}", f"https://{domain}:*"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins
    )


def tool_calls_in(body: bytes) -> list[tuple[Any, str, Any]]:
    """(id, tool name, arguments) of every tools/call in a JSON-RPC body (one or a batch)."""
    try:
        parsed = json.loads(body or b"null")
    except ValueError:
        return []
    found = []
    for message in parsed if isinstance(parsed, list) else [parsed]:
        if isinstance(message, dict) and message.get("method") == "tools/call":
            params = message.get("params") or {}
            if isinstance(params, dict):
                found.append(
                    (message.get("id"), str(params.get("name", "")), params.get("arguments") or {})
                )
    return found


def probe_only(body: bytes) -> bool:
    """Is every message in this body one the release probe may send?"""
    try:
        parsed = json.loads(body or b"null")
    except ValueError:
        return False
    messages = parsed if isinstance(parsed, list) else [parsed]
    return bool(messages) and all(
        isinstance(m, dict) and m.get("method") in PROBE_METHODS for m in messages
    )


def refusal(request_id: Any, tool: str) -> dict[str, Any]:
    """A tool result marked as an error: the model reads why, the call never ran."""
    text = (
        f"refused: `{tool}` {GUARDED.get(tool, 'is guarded')}, so it runs only for a signed-in "
        "user and is recorded under that user's name. This server has no signed-in user "
        "(no OAuth: STUDIO_DOMAIN is unset). Use the claude.ai connector, or call it from a "
        "local stdio session."
    )
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": True},
    }


def build_app(
    store: ConnectorStore,
    domain: str = "",
    trusted: tuple[str, ...] = (),
    clock: Callable[[], float] | None = None,
    warm: bool | None = None,
) -> Any:
    """The ASGI application. `domain` turns OAuth on; `warm` starts the index build at
    startup (default: what STUDIO_MCP_WARM_INDEX says, as for stdio)."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from studio.mcp import server as studio_server

    clock = clock or time.monotonic
    oauth_bucket = Buckets(OAUTH_CAPACITY, OAUTH_REFILL_PER_S, clock)
    login_bucket = Buckets(LOGIN_CAPACITY, LOGIN_REFILL_PER_S, clock)

    async def healthz(_request: Request) -> JSONResponse:
        from starlette.concurrency import run_in_threadpool

        ok = await run_in_threadpool(store.health)
        return JSONResponse(
            {"status": "ok" if ok else "the store does not answer"}, status_code=200 if ok else 503
        )

    security = transport_security(domain)
    app = studio_server.server.streamable_http_app(
        stateless_http=True, json_response=True, transport_security=security
    )
    # On this app's router, not `server.custom_route`: that list lives on the
    # module-level server and would outlive this app (and its store).
    app.router.routes.append(Route("/healthz", healthz, methods=["GET"]))
    _warm_on_startup(app, studio_server, warm)
    metadata_url = _oauth_routes(app, store, domain, login_bucket, trusted) if domain else ""
    return _front(app, store, domain, security, metadata_url, oauth_bucket, trusted)


def _warm_on_startup(app: Any, studio_server: Any, warm: bool | None) -> None:
    """Start the corpus index build when the process starts, before any user waits."""
    inner = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(a: Any) -> Any:
        if warm is None:
            studio_server.warm_index()
        elif warm:
            studio_server.warm_index({})
        async with inner(a) as state:
            yield state

    app.router.lifespan_context = lifespan


def _oauth_routes(
    app: Any, store: ConnectorStore, domain: str, login_bucket: Buckets, trusted: tuple[str, ...]
) -> str:
    """The SDK's OAuth routes on our provider, the resource metadata, the sign-in page.
    Returns the resource metadata URL a 401 at /mcp names (RFC 9728)."""
    from mcp.server.auth.routes import (
        build_resource_metadata_url,
        create_auth_routes,
        create_protected_resource_routes,
    )
    from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
    from pydantic import AnyHttpUrl
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
    from starlette.routing import Route

    from studio.mcp import oauth

    issuer = f"https://{domain}"
    provider = oauth.StudioOAuth(store, issuer)
    resource = AnyHttpUrl(f"{issuer}/mcp")

    async def login(request: Request) -> Response:
        address = client_of(request.headers, request.client.host if request.client else "", trusted)
        if request.method == "GET":
            wanted = request.query_params.get("request", "")
            pending = await run_in_threadpool(store.oauth_grant, oauth.PENDING, wanted)
            if pending is None:
                return HTMLResponse(oauth.login_page("", "", failed=True), status_code=400)
            body = json.loads(pending[2])
            return HTMLResponse(oauth.login_page(wanted, body["redirect_uri"], failed=False))
        if not login_bucket.has(address):
            return JSONResponse(TOO_MANY, status_code=429)
        raw = await request.body()
        fields = oauth.form_fields(raw[: oauth.LOGIN_BODY_MAX])
        back = await run_in_threadpool(
            provider.approve, fields.get("request", ""), fields.get("key", "")
        )
        if not back:
            login_bucket.take(address)
            return HTMLResponse(oauth.login_page("", "", failed=True), status_code=401)
        return RedirectResponse(back, status_code=302)

    routes = create_auth_routes(
        provider,
        AnyHttpUrl(issuer),
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[oauth.SCOPE], default_scopes=[oauth.SCOPE]
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    routes += create_protected_resource_routes(
        resource,
        [AnyHttpUrl(issuer)],
        scopes_supported=[oauth.SCOPE],
        resource_name="lipsync-studio",
    )
    routes.append(Route(oauth.LOGIN_PATH, login, methods=["GET", "POST"]))
    app.router.routes[:0] = routes
    return str(build_resource_metadata_url(resource))


def _front(
    app: Any,
    store: ConnectorStore,
    domain: str,
    security: Any,
    metadata_url: str,
    oauth_bucket: Buckets,
    trusted: tuple[str, ...],
) -> Any:
    """The ASGI wrapper the module docstring describes."""
    from mcp.server.transport_security import TransportSecurityMiddleware
    from starlette.concurrency import run_in_threadpool
    from starlette.datastructures import Headers
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    guard = TransportSecurityMiddleware(security)
    challenge = (
        {"WWW-Authenticate": f'Bearer resource_metadata="{metadata_url}"'} if metadata_url else {}
    )

    async def body_of(receive: Any) -> bytes:
        body, more = b"", True
        while more:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        return body

    def replay(body: bytes, receive: Any) -> Any:
        sent = False

        async def again() -> Any:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return again

    async def front(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        address = client_of(headers, (scope.get("client") or ("", 0))[0], trusted)
        path = scope["path"]
        if path in OAUTH_PATHS and scope["method"] != "OPTIONS":
            if not oauth_bucket.take(address):
                await JSONResponse(TOO_MANY, status_code=429)(scope, receive, send)
                return
        if not path.startswith("/mcp"):
            await app(scope, receive, send)
            return
        user, client_id = "", ""
        if domain:
            token = bearer(headers)
            if not token:
                refused = await guard.validate_request(
                    Request(scope), is_post=scope["method"] == "POST"
                )
                if refused is not None:
                    await refused(scope, receive, send)
                    return
                await JSONResponse(
                    {"error": "sign in: this server is a claude.ai connector (OAuth)"},
                    status_code=401,
                    headers=challenge,
                )(scope, receive, send)
                return
            who = await run_in_threadpool(store.who, token)
            if who is None:
                await JSONResponse(
                    {"error": "the access token is unknown or expired: sign in again"},
                    status_code=401,
                    headers=challenge,
                )(scope, receive, send)
                return
            user, client_id = who
        if scope["method"] == "POST":
            body = await body_of(receive)
            if user == PROBE_USER and not probe_only(body):
                await JSONResponse(
                    {"error": "the probe may only initialize and list tools"}, status_code=403
                )(scope, receive, send)
                return
            for request_id, tool, arguments in tool_calls_in(body):
                if tool not in GUARDED:
                    continue
                if not user:
                    await JSONResponse(refusal(request_id, tool))(scope, receive, send)
                    return
                await run_in_threadpool(
                    store.record_call, user, client_id, tool, GUARDED[tool], arguments
                )
            receive = replay(body, receive)
        if user:
            scope.setdefault("state", {})["studio_user"] = user
        await app(scope, receive, send)

    front.inner = app  # type: ignore[attr-defined]
    return front


# - command line -


def _store(args: argparse.Namespace, environ: Mapping[str, str]) -> ConnectorStore:
    domain = allowed_domain(environ)
    return ConnectorStore(args.db, pepper=pepper(environ, domain))


def serve(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    import uvicorn

    domain = allowed_domain(environ)
    names = load_vendor_env(environ)
    if names:
        print(f"vendor keys loaded: {', '.join(sorted(names))}", file=sys.stderr)
    app = build_app(_store(args, environ), domain=domain, trusted=trusted_proxies(environ))
    host = environ.get("STUDIO_HOST", "").strip() or LOOPBACK
    # proxy_headers off: X-Forwarded-For is read by client_of, from trusted proxies only.
    uvicorn.run(app, host=host, port=args.port, log_level="warning", proxy_headers=False)
    return 0


def new_user(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    key = secrets.token_urlsafe(32)
    _store(args, environ).add_user(args.name, key)
    print(f"user {args.name} added; the key, shown once (it is typed on the sign-in page):")
    print(key)
    return 0


def rekey_user(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    key = secrets.token_urlsafe(32)
    _store(args, environ).rekey_user(args.name, key)
    print(f"user {args.name}: the old key and its sign-ins no longer work. New key, shown once:")
    print(key)
    return 0


def disable_user(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    _store(args, environ).disable_user(args.name)
    print(f"user {args.name} disabled; every token of theirs is gone")
    return 0


def list_users(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    for name, at, disabled in _store(args, environ).users():
        print(f"{name}\t{at}\t{'disabled' if disabled else 'active'}")
    return 0


def list_calls(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    for row in _store(args, environ).calls(limit=args.limit, user=args.user):
        print(json.dumps(row, ensure_ascii=False))
    return 0


def probe(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    """The release probe, run INSIDE the container (`docker compose exec server ...`):
    mint a one-minute token for PROBE_USER, POST initialize and tools/list to the
    running server over real HTTP, then drop the token. Exit 0 = the transport answers.

    The harness keeps a probe KEY in a file for this; here the probe needs no stored
    credential at all, because it runs where the store is."""
    import http.client

    from studio.mcp import oauth

    domain = allowed_domain(environ)
    store = _store(args, environ)
    token, family = secrets.token_urlsafe(32), secrets.token_urlsafe(16)
    body = json.dumps({"scopes": [oauth.SCOPE], "resource": None})
    store.oauth_grant_put(
        oauth.ACCESS, token, "probe", PROBE_USER, family, body, oauth._expires(PROBE_TOKEN_S)
    )
    headers = {
        "Host": domain or LOOPBACK,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-11-25",
    }
    init = {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "studio-probe", "version": "1"},
    }
    try:
        answers = []
        for request_id, method, params in ((1, "initialize", init), (2, "tools/list", {})):
            conn = http.client.HTTPConnection(LOOPBACK, args.port, timeout=10)
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            conn.request("POST", "/mcp", body=json.dumps(payload), headers=headers)
            reply = conn.getresponse()
            answers.append((reply.status, reply.read()))
            conn.close()
    except OSError as exc:
        print(f"probe: the server does not answer on {LOOPBACK}:{args.port}: {exc}")
        return 1
    finally:
        store.oauth_family_drop(family)
    (s1, b1), (s2, b2) = answers
    if s1 != 200 or b'"serverInfo"' not in b1:
        print(f"probe: initialize answered {s1}")
        return 1
    if s2 != 200 or b'"model_advice"' not in b2:
        print(f"probe: tools/list answered {s2}")
        return 1
    print("probe: initialize 200 and tools/list 200 through the OAuth front")
    return 0


COMMANDS: dict[str, Callable[[argparse.Namespace, Mapping[str, str]], int]] = {
    "probe": probe,
    "serve": serve,
    "new-user": new_user,
    "rekey-user": rekey_user,
    "disable-user": disable_user,
    "users": list_users,
    "calls": list_calls,
}


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(prog="python -m studio.mcp.http_app")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, work in COMMANDS.items():
        one = sub.add_parser(name)
        one.add_argument("--db", default=environ.get("STUDIO_CONNECTOR_DB", DEFAULT_DB))
        if name in ("serve", "probe"):
            one.add_argument("--port", type=int, default=DEFAULT_PORT)
        if name in ("new-user", "rekey-user", "disable-user"):
            one.add_argument("name")
        if name == "calls":
            one.add_argument("--limit", type=int, default=50)
            one.add_argument("--user", default="")
        one.set_defaults(work=work)
    args = parser.parse_args(argv)
    try:
        return int(args.work(args, environ))
    except (ConfigError, StoreError) as exc:
        print(f"studio connector: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
