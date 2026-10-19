"""OAuth 2.0 for the claude.ai custom connector: the provider behind the SDK's routes.

Adapted from green-harness `harness/server_app/oauth.py` (the connector at
https://harness.greenflac.online/mcp, connected over this flow 2026-10-06).
claude.ai signs a connector in by OAuth 2.0 with dynamic client registration
and PKCE S256; the MCP SDK serves the protocol (metadata, /register,
/authorize, /token, /revoke) and this module is the provider on our store,
plus the one step the SDK leaves to the server: the person proves WHO they are
by typing their studio user key on our own page, and nowhere else.

Changes from the harness, each for a reason:

* `PENDING_S` is 600, not 120. The harness owner's first sign-in failed twice
  because the two-minute window ran out while he fetched a key (harness
  HANDOFF, 2026-10-06, "OAUTH_PENDING_S=120 is short").
* The failure page names no host when it has none (the same HANDOFF: "the
  failure page prints 'sent back to .' with an empty host").
* The grant carries a USER name, not a tenant hash: attribution prints it.
"""

from __future__ import annotations

import html
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from studio.mcp.connector_store import ConnectorStore

#: The one scope: a connector acts for its user as the user's key would.
SCOPE = "studio"
#: Where a registered client may send the person back, EXACTLY (harness, read
#: from claude.com connector docs 2026-09-30): the hosted Claude apps register
#: this one URI; Claude Code registers a loopback /callback on any port.
REDIRECT_EXACT = ("https://claude.ai/api/mcp/auth_callback",)
REDIRECT_LOOPBACK_HOSTS = ("localhost", "127.0.0.1")
REDIRECT_LOOPBACK_PATH = "/callback"
PENDING, CODE, ACCESS, REFRESH = "pending", "code", "access", "refresh"
LOGIN_PATH = "/oauth/login"
#: CHOSEN (see the module docstring): ten minutes to fetch a key.
PENDING_S = 600
CODE_S = 300
#: As in the harness: an hour, and a refresh token of 30 days rotated on use.
ACCESS_S = 3600
REFRESH_S = 30 * 86400
LOGIN_BODY_MAX = 4096


def _expires(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def redirect_allowed(uri: str) -> bool:
    """claude.ai's callback exactly, or the loopback's /callback on any port; nothing else."""
    if uri in REDIRECT_EXACT:
        return True
    parts = urlparse(uri)
    return (
        parts.scheme == "http"
        and (parts.hostname or "") in REDIRECT_LOOPBACK_HOSTS
        and parts.path == REDIRECT_LOOPBACK_PATH
        and not parts.query
        and not parts.fragment
        and not parts.username
        and not parts.password
    )


async def _thread(fn: Any, *args: Any) -> Any:
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(fn, *args)


class StudioOAuth:
    """The SDK's OAuthAuthorizationServerProvider, on the connector store."""

    def __init__(self, store: ConnectorStore, issuer: str) -> None:
        self.store = store
        self.issuer = issuer.rstrip("/")

    # - clients -

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        info = await _thread(self.store.oauth_client, client_id)
        return OAuthClientInformationFull.model_validate_json(info) if info else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in (client_info.redirect_uris or [])]
        if not uris or not all(redirect_allowed(u) for u in uris):
            raise RegistrationError(
                error="invalid_redirect_uri",
                error_description="a redirect URI must be "
                + " or ".join(REDIRECT_EXACT)
                + ", or http://localhost or 127.0.0.1 /callback",
            )
        await _thread(
            self.store.oauth_client_save, client_info.client_id or "", client_info.model_dump_json()
        )

    # - the authorization: the person types their user key on our page -

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        request = secrets.token_urlsafe(32)
        body = json.dumps(
            {
                "state": params.state,
                "scopes": params.scopes or [SCOPE],
                "code_challenge": params.code_challenge,
                "redirect_uri": str(params.redirect_uri),
                "explicit": params.redirect_uri_provided_explicitly,
                "resource": params.resource,
            }
        )
        await _thread(
            self.store.oauth_grant_put,
            PENDING,
            request,
            client.client_id or "",
            "",
            "",
            body,
            _expires(PENDING_S),
        )
        return f"{self.issuer}{LOGIN_PATH}?request={request}"

    def approve(self, request: str, key: str) -> str:
        """The login step (sync): the redirect back with a code, or "" for an unknown key
        or a pending authorization that is gone. The code starts a new family."""
        user = self.store.user_of_key(key)
        if user is None:
            return ""
        pending = self.store.oauth_grant(PENDING, request, take=True)
        if pending is None:
            return ""
        client_id, _, raw, _ = pending
        body = json.loads(raw)
        code, family = secrets.token_urlsafe(32), secrets.token_urlsafe(16)
        self.store.oauth_grant_put(CODE, code, client_id, user, family, raw, _expires(CODE_S))
        return construct_redirect_uri(body["redirect_uri"], code=code, state=body["state"])

    # - codes and tokens -

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        grant = await _thread(self.store.oauth_grant, CODE, authorization_code)
        if grant is None:
            # A spent code presented again: spending it again ends its family.
            await _thread(self.store.oauth_spend, CODE, authorization_code)
            return None
        if grant[0] != client.client_id:
            return None
        body = json.loads(grant[2])
        return AuthorizationCode(
            code=authorization_code,
            scopes=body["scopes"],
            expires_at=time.time() + CODE_S,
            client_id=grant[0],
            code_challenge=body["code_challenge"],
            redirect_uri=body["redirect_uri"],
            redirect_uri_provided_explicitly=body["explicit"],
            resource=body["resource"],
        )

    def _issue(
        self, client_id: str, user: str, family: str, scopes: list[str], resource: str | None
    ) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        body = json.dumps({"scopes": scopes, "resource": resource})
        self.store.oauth_grant_put(
            ACCESS, access, client_id, user, family, body, _expires(ACCESS_S)
        )
        self.store.oauth_grant_put(
            REFRESH, refresh, client_id, user, family, body, _expires(REFRESH_S)
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_S,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    def _spend(self, kind: str, value: str, client_id: str | None) -> tuple[str, str, str, str]:
        state, grant = self.store.oauth_spend(kind, value)
        if state != "ok" or grant is None or grant[0] != client_id:
            raise TokenError(
                error="invalid_grant",
                error_description="the grant is spent, replayed or unknown; a replay ends "
                "everything issued from it",
            )
        return grant

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        def work() -> OAuthToken:
            grant = self._spend(CODE, authorization_code.code, client.client_id)
            return self._issue(
                grant[0], grant[1], grant[3], authorization_code.scopes, authorization_code.resource
            )

        return await _thread(work)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        grant = await _thread(self.store.oauth_grant, REFRESH, refresh_token)
        if grant is None:
            await _thread(self.store.oauth_spend, REFRESH, refresh_token)
            return None
        if grant[0] != client.client_id:
            return None
        body = json.loads(grant[2])
        # mcp 2.1.1's RefreshToken has no `resource` (the harness runs 2.2): the
        # resource stays in the stored grant and is read back at the exchange.
        return RefreshToken(token=refresh_token, client_id=grant[0], scopes=body["scopes"])

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        def work() -> OAuthToken:
            grant = self._spend(REFRESH, refresh_token.token, client.client_id)
            resource = json.loads(grant[2]).get("resource")
            return self._issue(
                grant[0], grant[1], grant[3], scopes or refresh_token.scopes, resource
            )

        return await _thread(work)

    async def load_access_token(self, token: str) -> AccessToken | None:
        grant = await _thread(self.store.oauth_grant, ACCESS, token)
        if grant is None:
            return None
        body = json.loads(grant[2])
        return AccessToken(
            token=token, client_id=grant[0], scopes=body["scopes"], resource=body["resource"]
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """RFC 7009: revoking either token ends its whole family."""

        def work() -> None:
            for kind in (ACCESS, REFRESH):
                grant = self.store.oauth_grant(kind, token.token)
                if grant is not None:
                    self.store.oauth_family_drop(grant[3])

        await _thread(work)

    async def exchange_identity_assertion(self, *args: Any, **kwargs: Any) -> OAuthToken:
        raise NotImplementedError("identity assertion is not offered")


def login_page(request_id: str, redirect_uri: str, failed: bool) -> str:
    """The page that asks for the user key. No script and no style: the CSP allows
    neither. It never shows the name a client registered itself with: anyone can
    register, so that name is an attacker's choice (harness independent review)."""
    host = urlparse(redirect_uri).hostname or ""
    note = (
        "<p><strong>That key is unknown, or this sign-in expired. Start the sign-in again "
        "from the application.</strong></p>"
        if failed
        else ""
    )
    back = (
        f"<p>After you sign in, you are sent back to <strong>{html.escape(host)}</strong>.</p>"
        if host
        else ""
    )
    form = (
        f'<form method="post" action="{LOGIN_PATH}">'
        f'<input type="hidden" name="request" value="{html.escape(request_id)}">'
        '<label>Studio key <input type="password" name="key" autocomplete="off" required>'
        '</label> <button type="submit">Sign in</button></form>'
        if request_id
        else ""
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>Lipsync studio sign-in</title></head><body>"
        "<h1>Sign in to the lipsync studio</h1>"
        "<p><strong>Continue only if you just clicked Connect for this studio yourself, in "
        "claude.ai or in Claude Code.</strong> If someone sent you this link, close the page: "
        "signing in here lets the application that started it act as you.</p>"
        + back
        + note
        + form
        + "<p>Type your key only here, on this address. The key is checked and not stored."
        "</p></body></html>"
    )


def form_fields(body: bytes) -> dict[str, str]:
    """An application/x-www-form-urlencoded body, one value per name."""
    parsed = parse_qs(body.decode("utf-8", "replace"), max_num_fields=8)
    return {name: values[0] for name, values in parsed.items() if values}
