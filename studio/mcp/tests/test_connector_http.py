"""The hosted connector: OAuth sign-in, /mcp behind it, guarded tools, a cheap start.

Everything runs IN PROCESS through Starlette's TestClient (an ASGI transport,
no socket), so the runner's network ban (rule T4) holds. The live loopback
run over real HTTP is `scripts/connector_smoke.py`, outside this suite.

No paid call is made: the only guarded tool that RUNS here is
`probe_model_limit` with a non-absurd value, which it refuses before
building any request.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from starlette.testclient import TestClient

from studio.mcp import connector_store, http_app, oauth
from studio.mcp.connector_store import PROBE_USER, USER_NAME, ConnectorStore, StoreError
from studio.mcp.lazy import lazy, loaded

ROOT = Path(__file__).resolve().parents[3]
DOMAIN = "studio.example.org"
BASE = f"https://{DOMAIN}"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
KEY = "k" * 48
QUIET_ENV = {"STUDIO_MCP_WARM_INDEX": "0", "STUDIO_NO_JOURNAL": "1"}
ACCEPT = "application/json, text/event-stream"


def later(seconds: int):
    """The store's clock moved `seconds` ahead: what a grant's expiry is checked against."""
    from datetime import UTC, datetime, timedelta

    at = (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(timespec="seconds")
    return mock.patch.object(connector_store, "now", return_value=at)


VERSION = "2025-11-25"


def rpc(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def initialize() -> dict:
    return rpc(
        "initialize",
        {
            "protocolVersion": VERSION,
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"},
        },
    )


#: Refused before any request is built: 5 is below the absurdity floor.
HARMLESS_PROBE = {
    "name": "probe_model_limit",
    "arguments": {"url": "https://api.example.test/v1", "field": "duration", "absurd_value": "5"},
}


class _Connector(unittest.TestCase):
    domain = DOMAIN

    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, QUIET_ENV)
        env.start()
        self.addCleanup(env.stop)
        for name in ("httpx", "mcp", "uvicorn"):
            quiet = mock.patch.object(logging.getLogger(name), "disabled", True)
            quiet.start()
            self.addCleanup(quiet.stop)
        self.store = ConnectorStore(":memory:", pepper="p" * 40)
        self.store.add_user("owner", KEY)
        self.client = TestClient(
            http_app.build_app(self.store, domain=self.domain, warm=False), base_url=BASE
        )
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    # - the OAuth dance claude.ai performs -

    def register(self, redirect: str = CALLBACK) -> str:
        r = self.client.post(
            "/register",
            json={
                "redirect_uris": [redirect],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        self.assertEqual(r.status_code, 201, r.text)
        return str(r.json()["client_id"])

    def sign_in(self, key: str = KEY) -> tuple[str, dict]:
        client_id, code, verifier = self.code_for(key)
        r = self.token_for(client_id, code, verifier)
        self.assertEqual(r.status_code, 200, r.text)
        return client_id, r.json()

    def pending_request(self, client_id: str, challenge: str) -> str:
        """/authorize up to the sign-in page: the pending request id it links to."""
        r = self.client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": CALLBACK,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "s-1",
                "resource": f"{BASE}/mcp",
            },
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302, r.text)
        return parse_qs(urlparse(r.headers["location"]).query)["request"][0]

    def token_for(self, client_id: str, code: str, verifier: str):
        return self.client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CALLBACK,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": f"{BASE}/mcp",
            },
        )

    def code_for(self, key: str = KEY) -> tuple[str, str, str]:
        """Register, authorize and sign in: (client_id, code, PKCE verifier)."""
        client_id = self.register()
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        r = self.client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": CALLBACK,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "s-1",
                "resource": f"{BASE}/mcp",
            },
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302, r.text)
        login = urlparse(r.headers["location"])
        self.assertEqual((login.netloc, login.path), (DOMAIN, oauth.LOGIN_PATH))
        request = parse_qs(login.query)["request"][0]
        page = self.client.get(oauth.LOGIN_PATH, params={"request": request})
        self.assertEqual(page.status_code, 200)
        self.assertIn('name="key"', page.text)
        self.assertIn("claude.ai", page.text)
        r = self.client.post(
            oauth.LOGIN_PATH, data={"request": request, "key": key}, follow_redirects=False
        )
        self.assertEqual(r.status_code, 302, r.text)
        back = urlparse(r.headers["location"])
        self.assertEqual(f"{back.scheme}://{back.netloc}{back.path}", CALLBACK)
        query = parse_qs(back.query)
        self.assertEqual(query["state"], ["s-1"])
        return client_id, query["code"][0], verifier

    def mcp(self, body: dict, token: str = "", **headers: str):
        sent = {"Accept": ACCEPT, "MCP-Protocol-Version": VERSION, **headers}
        if token:
            sent["Authorization"] = f"Bearer {token}"
        return self.client.post("/mcp", json=body, headers=sent)


class OAuthFlow(_Connector):
    def test_metadata_names_this_server_as_its_own_authorization_server(self) -> None:
        r = self.client.get("/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["resource"], f"{BASE}/mcp")
        self.assertEqual(r.json()["authorization_servers"], [f"{BASE}/"])
        meta = self.client.get("/.well-known/oauth-authorization-server").json()
        self.assertEqual(meta["registration_endpoint"], f"{BASE}/register")
        self.assertIn("S256", meta["code_challenge_methods_supported"])

    def test_registration_refuses_a_stranger_callback(self) -> None:
        r = self.client.post(
            "/register",
            json={
                "redirect_uris": ["https://evil.example/cb"],
                "token_endpoint_auth_method": "none",
            },
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("invalid_redirect_uri", r.text)

    def test_the_whole_flow_ends_in_a_working_access_token(self) -> None:
        _, tokens = self.sign_in()
        self.assertEqual(tokens["token_type"], "Bearer")
        self.assertEqual(tokens["scope"], oauth.SCOPE)
        r = self.mcp(initialize(), tokens["access_token"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["result"]["serverInfo"]["name"], "lipsync-studio")
        r = self.mcp(rpc("tools/list", request_id=2), tokens["access_token"])
        names = {t["name"] for t in r.json()["result"]["tools"]}
        self.assertIn("model_advice", names)

    def test_a_wrong_key_signs_nobody_in(self) -> None:
        client_id = self.register()
        r = self.client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": CALLBACK,
                "code_challenge": "x" * 43,
                "code_challenge_method": "S256",
                "state": "s",
            },
            follow_redirects=False,
        )
        request = parse_qs(urlparse(r.headers["location"]).query)["request"][0]
        r = self.client.post(
            oauth.LOGIN_PATH, data={"request": request, "key": "w" * 48}, follow_redirects=False
        )
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("location", r.headers)

    def test_refresh_rotates_and_a_replay_ends_the_family(self) -> None:
        client_id, tokens = self.sign_in()
        r = self.client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": client_id,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        fresh = r.json()
        self.assertNotEqual(fresh["refresh_token"], tokens["refresh_token"])
        self.assertEqual(self.mcp(initialize(), fresh["access_token"]).status_code, 200)
        replay = self.client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": client_id,
            },
        )
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(self.mcp(initialize(), fresh["access_token"]).status_code, 401)

    def test_a_disabled_user_loses_every_token(self) -> None:
        _, tokens = self.sign_in()
        self.store.disable_user("owner")
        self.assertEqual(self.mcp(initialize(), tokens["access_token"]).status_code, 401)

    def test_pkce_is_required_and_checked(self) -> None:
        client_id = self.register()
        r = self.client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": CALLBACK,
                "state": "s",
            },
            follow_redirects=False,
        )
        self.assertNotIn(oauth.LOGIN_PATH, r.headers.get("location", ""))
        client_id, code, _ = self.code_for()
        r = self.token_for(client_id, code, secrets.token_urlsafe(48))
        self.assertEqual(r.status_code, 400)
        self.assertIn("code_verifier", r.text)


class Lifetimes(_Connector):
    """Each grant lives exactly as long as chosen: a minute either side flips the answer."""

    def test_the_sign_in_link_lives_ten_minutes(self) -> None:
        request = self.pending_request(self.register(), "x" * 43)
        with later(oauth.PENDING_S - 60):
            self.assertEqual(
                self.client.get(oauth.LOGIN_PATH, params={"request": request}).status_code, 200
            )
        with later(oauth.PENDING_S + 60):
            self.assertEqual(
                self.client.get(oauth.LOGIN_PATH, params={"request": request}).status_code, 400
            )
        self.assertEqual(oauth.PENDING_S, 600)

    def test_a_code_lives_five_minutes(self) -> None:
        client_id, code, verifier = self.code_for()
        with later(oauth.CODE_S + 60):
            self.assertEqual(self.token_for(client_id, code, verifier).status_code, 400)
        client_id, code, verifier = self.code_for()
        with later(oauth.CODE_S - 60):
            self.assertEqual(self.token_for(client_id, code, verifier).status_code, 200)
        self.assertEqual(oauth.CODE_S, 300)

    def test_an_access_token_lives_an_hour(self) -> None:
        _, tokens = self.sign_in()
        self.assertEqual(tokens["expires_in"], 3600)
        with later(3600 - 60):
            self.assertEqual(self.mcp(initialize(), tokens["access_token"]).status_code, 200)
        with later(3600 + 60):
            self.assertEqual(self.mcp(initialize(), tokens["access_token"]).status_code, 401)

    def test_a_refresh_token_lives_thirty_days(self) -> None:
        def refresh(client_id: str, token: str):
            return self.client.post(
                "/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": token,
                    "client_id": client_id,
                },
            )

        client_id, tokens = self.sign_in()
        with later(30 * 86400 + 3600):
            self.assertEqual(refresh(client_id, tokens["refresh_token"]).status_code, 400)
        client_id, tokens = self.sign_in()
        with later(30 * 86400 - 3600):
            self.assertEqual(refresh(client_id, tokens["refresh_token"]).status_code, 200)


class FailedSignInsAreLimited(_Connector):
    def test_ten_wrong_keys_then_the_address_waits(self) -> None:
        request = self.pending_request(self.register(), "x" * 43)
        for _ in range(10):
            r = self.client.post(
                oauth.LOGIN_PATH, data={"request": request, "key": "w" * 48}, follow_redirects=False
            )
            self.assertEqual(r.status_code, 401)
        r = self.client.post(
            oauth.LOGIN_PATH, data={"request": request, "key": KEY}, follow_redirects=False
        )
        self.assertEqual(r.status_code, 429)


class McpNeedsAUser(_Connector):
    def test_no_token_is_401_with_the_resource_metadata_challenge(self) -> None:
        r = self.mcp(initialize())
        self.assertEqual(r.status_code, 401)
        self.assertEqual(
            r.headers["www-authenticate"],
            f'Bearer resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp"',
        )

    def test_a_raw_user_key_is_not_a_bearer(self) -> None:
        self.assertEqual(self.mcp(initialize(), KEY).status_code, 401)

    def test_an_unknown_token_is_401(self) -> None:
        self.assertEqual(self.mcp(initialize(), "nope").status_code, 401)

    def test_a_foreign_host_is_refused_before_the_challenge(self) -> None:
        r = self.mcp(initialize(), Host="evil.example")
        self.assertEqual(r.status_code, 421)

    def test_the_probe_token_opens_the_transport_and_nothing_else(self) -> None:
        self.store.oauth_grant_put(
            oauth.ACCESS,
            "probe-token",
            "probe",
            PROBE_USER,
            "fam",
            '{"scopes": ["studio"], "resource": null}',
            oauth._expires(60),
        )
        self.assertEqual(self.mcp(initialize(), "probe-token").status_code, 200)
        self.assertEqual(self.mcp(rpc("tools/list"), "probe-token").status_code, 200)
        r = self.mcp(rpc("tools/call", HARMLESS_PROBE), "probe-token")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.store.calls(), [])

    def test_healthz_answers_without_a_token(self) -> None:
        r = self.client.get("/healthz")
        self.assertEqual((r.status_code, r.json()), (200, {"status": "ok"}))


class GuardedToolsAreAttributed(_Connector):
    def test_a_guarded_call_is_recorded_under_the_signed_in_user(self) -> None:
        client_id, tokens = self.sign_in()
        r = self.mcp(rpc("tools/call", HARMLESS_PROBE, request_id=7), tokens["access_token"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("absurdity floor", r.text)
        calls = self.store.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["user"], "owner")
        self.assertEqual(calls[0]["client_id"], client_id)
        self.assertEqual(calls[0]["tool"], "probe_model_limit")
        self.assertIn('"absurd_value": "5"', calls[0]["arguments"])

    def test_the_row_is_written_before_the_tool_runs(self) -> None:
        _, tokens = self.sign_in()
        seen: list[int] = []

        def tool(*_args: object, **_kwargs: object) -> dict:
            seen.append(len(self.store.calls()))
            return {"outcome": "fail", "note": "stub: nothing sent"}

        with mock.patch("studio.mcp.probe.probe_limit", side_effect=tool):
            r = self.mcp(rpc("tools/call", HARMLESS_PROBE), tokens["access_token"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(seen, [1])

    def test_a_reading_tool_leaves_no_attribution_row(self) -> None:
        _, tokens = self.sign_in()
        r = self.mcp(
            rpc("tools/call", {"name": "check_lipsync_prompt", "arguments": {"prompt": "x"}}),
            tokens["access_token"],
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.store.calls(), [])

    def test_every_guarded_name_is_a_live_tool(self) -> None:
        """A renamed tool would fall out of the guard silently; this keeps it red."""
        _, tokens = self.sign_in()
        r = self.mcp(rpc("tools/list"), tokens["access_token"])
        names = {t["name"] for t in r.json()["result"]["tools"]}
        self.assertEqual(set(http_app.GUARDED) - names, set())

    def test_the_guard_covers_the_knowledge_writers_and_the_paid_tools(self) -> None:
        self.assertEqual(
            set(http_app.GUARDED),
            {
                "record_model_fact",
                "withdraw_model_fact",
                "propose_measurement",
                "search_web",
                "probe_model_limit",
            },
        )


class WithoutOAuthNobodyMayWrite(_Connector):
    """No domain = no OAuth = loopback dev mode: reads work, guarded tools are refused."""

    domain = ""

    def test_reads_work_and_guarded_tools_are_refused_unrecorded(self) -> None:
        r = self.client.post(
            "/mcp", json=initialize(), headers={"Accept": ACCEPT, "Host": "127.0.0.1:8770"}
        )
        self.assertEqual(r.status_code, 200, r.text)
        for tool in sorted(http_app.GUARDED):
            r = self.client.post(
                "/mcp",
                json=rpc("tools/call", {"name": tool, "arguments": {}}, request_id=9),
                headers={"Accept": ACCEPT, "MCP-Protocol-Version": VERSION, "Host": "127.0.0.1"},
            )
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(r.json()["result"]["isError"], tool)
            self.assertIn("signed-in user", r.text)
        self.assertEqual(self.store.calls(), [])

    def test_there_are_no_oauth_routes(self) -> None:
        r = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(r.status_code, 404)


class Redirects(unittest.TestCase):
    def test_only_claude_ai_and_the_loopback_callback(self) -> None:
        self.assertTrue(oauth.redirect_allowed(CALLBACK))
        self.assertTrue(oauth.redirect_allowed("http://localhost:4312/callback"))
        self.assertTrue(oauth.redirect_allowed("http://127.0.0.1/callback"))
        for bad in (
            "https://claude.ai.evil.example/api/mcp/auth_callback",
            "https://claude.ai/api/mcp/auth_callback/x",
            "http://localhost/callback?x=1",
            "https://localhost/callback",
            "http://evil.example/callback",
            "http://localhost/callback/evil",
            "http://localhost/callback#x",
            "http://user@localhost/callback",
            "http://user:pw@127.0.0.1/callback",
        ):
            self.assertFalse(oauth.redirect_allowed(bad), bad)


class Store(unittest.TestCase):
    def test_keys_are_stored_as_hmac_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.sqlite3"
            store = ConnectorStore(path, pepper="p" * 40)
            store.add_user("anna", KEY)
            self.assertEqual(store.user_of_key(KEY), "anna")
            on_disk = b"".join(f.read_bytes() for f in Path(tmp).iterdir())
            self.assertNotIn(KEY.encode(), on_disk)

    def test_names_and_short_keys_are_refused(self) -> None:
        store = ConnectorStore(":memory:")
        with self.assertRaises(StoreError):
            store.add_user("Has Space", KEY)
        with self.assertRaises(StoreError):
            store.add_user("bob", "short")
        store.add_user("bob", KEY)
        with self.assertRaises(StoreError):
            store.add_user("bob", "x" * 48)

    def test_a_copied_database_acts_for_nobody(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.sqlite3"
            ConnectorStore(path, pepper="p" * 40).add_user("anna", KEY)
            self.assertEqual(ConnectorStore(path, pepper="p" * 40).user_of_key(KEY), "anna")
            self.assertIsNone(ConnectorStore(path, pepper="q" * 40).user_of_key(KEY))
            self.assertIsNone(ConnectorStore(path).user_of_key(KEY))

    def test_without_a_pepper_the_key_is_still_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.sqlite3"
            store = ConnectorStore(path)
            store.add_user("anna", KEY)
            store.oauth_grant_put("access", "t" * 43, "c", "anna", "f", "{}", "9999-01-01")
            self.assertEqual(store.user_of_key(KEY), "anna")
            # WAL: fresh rows sit in c.sqlite3-wal, so every file of the database is read.
            on_disk = b"".join(f.read_bytes() for f in Path(tmp).iterdir())
            self.assertNotIn(KEY.encode(), on_disk)
            self.assertNotIn(b"t" * 43, on_disk)

    def test_key_length_and_name_length_at_the_boundary(self) -> None:
        store = ConnectorStore(":memory:")
        with self.assertRaises(StoreError):
            store.add_user("short", "k" * 39)
        store.add_user("exact", "k" * 40)
        with self.assertRaises(StoreError):
            store.add_user("a" * 41, KEY)
        store.add_user("a" * 40, "m" * 48)

    def test_no_user_name_can_be_the_probe(self) -> None:
        self.assertIsNone(USER_NAME.match(PROBE_USER))

    def test_a_long_argument_is_cut_and_the_hash_keeps_the_whole(self) -> None:
        store = ConnectorStore(":memory:")
        store.record_call("anna", "c", "search_web", "w", {"q": "a" * 2000, "long": "b" * 2001})
        kept = json.loads(store.calls()[0]["arguments"])
        self.assertEqual(kept["q"], "a" * 2000)
        self.assertEqual(kept["long"], "b" * 2000 + " [cut]")

    def test_rekey_drops_the_old_key(self) -> None:
        store = ConnectorStore(":memory:")
        store.add_user("bob", KEY)
        store.rekey_user("bob", "n" * 48)
        self.assertIsNone(store.user_of_key(KEY))
        self.assertEqual(store.user_of_key("n" * 48), "bob")


class Config(unittest.TestCase):
    def test_a_secret_in_a_variable_is_refused(self) -> None:
        with self.assertRaises(http_app.ConfigError):
            http_app.secret({"STUDIO_KEY_PEPPER": "x" * 40}, "STUDIO_KEY_PEPPER")

    def test_a_domain_needs_a_pepper(self) -> None:
        with self.assertRaises(http_app.ConfigError):
            http_app.pepper({}, DOMAIN)
        self.assertEqual(http_app.pepper({}, ""), "")

    def test_a_pepper_needs_thirty_two_characters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pepper"
            path.write_text("p" * 31)
            with self.assertRaises(http_app.ConfigError):
                http_app.pepper({"STUDIO_KEY_PEPPER_FILE": str(path)}, DOMAIN)
            path.write_text("p" * 32)
            self.assertEqual(
                http_app.pepper({"STUDIO_KEY_PEPPER_FILE": str(path)}, DOMAIN), "p" * 32
            )

    def test_a_domain_is_a_plain_host_name(self) -> None:
        self.assertEqual(
            http_app.allowed_domain({"STUDIO_DOMAIN": "Studio.Greenflac.Online"}),
            "studio.greenflac.online",
        )
        for bad in ("https://x.org", "x.org:443", "*.x.org", "x.org/mcp"):
            with self.assertRaises(http_app.ConfigError, msg=bad):
                http_app.allowed_domain({"STUDIO_DOMAIN": bad})

    def test_vendor_keys_load_into_the_process_and_never_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vendor.env"
            path.write_text("# comment\nGEMINI_API_KEY=abc\nSERPER_API_KEY='def'\n\n")
            target = {"SERPER_API_KEY": "kept"}
            names = http_app.load_vendor_env({"STUDIO_VENDOR_ENV_FILE": str(path)}, target)
            self.assertEqual(names, ["GEMINI_API_KEY"])
            self.assertEqual(target, {"SERPER_API_KEY": "kept", "GEMINI_API_KEY": "abc"})
            path.write_text("not a pair with sk-secret\n")
            with self.assertRaises(http_app.ConfigError) as caught:
                http_app.load_vendor_env({"STUDIO_VENDOR_ENV_FILE": str(path)}, {})
            self.assertNotIn("sk-secret", str(caught.exception))

    def test_the_cli_issues_a_key_once_and_lists_users(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "c.sqlite3")
            with mock.patch("sys.stdout") as out:
                self.assertEqual(http_app.main(["new-user", "owner", "--db", db], {}), 0)
            printed = "".join(c.args[0] for c in out.write.call_args_list)
            key = printed.strip().splitlines()[-1]
            self.assertEqual(ConnectorStore(db).user_of_key(key), "owner")
            with mock.patch("sys.stderr"):
                self.assertEqual(http_app.main(["new-user", "owner", "--db", db], {}), 2)


class ColdStart(unittest.TestCase):
    """`initialize` and `tools/list` must not pay for the planner and its kin."""

    HEAVY = (
        "studio.planner",
        "studio.endpoints",
        "studio.recipes",
        "studio.factindex",
        "studio.pricing",
        "studio.mcp.capability",
    )

    def test_handshake_and_tool_list_do_not_import_the_heavy_modules(self) -> None:
        script = (
            "import sys\n"
            "from starlette.testclient import TestClient\n"
            "from studio.mcp import http_app\n"
            "from studio.mcp.connector_store import ConnectorStore\n"
            "app = http_app.build_app(ConnectorStore(':memory:'), warm=False)\n"
            "h = {'Accept': 'application/json, text/event-stream', 'Host': '127.0.0.1'}\n"
            "with TestClient(app, base_url='http://127.0.0.1') as c:\n"
            "    init = {'protocolVersion': '2025-11-25', 'capabilities': {},\n"
            "            'clientInfo': {'name': 't', 'version': '1'}}\n"
            "    a = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',\n"
            "                             'params': init}, headers=h)\n"
            "    b = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},\n"
            "               headers={**h, 'MCP-Protocol-Version': '2025-11-25'})\n"
            "print(a.status_code, b.status_code)\n"
            f"print(sorted(m for m in {self.HEAVY!r} if m in sys.modules))\n"
        )
        env = {**os.environ, **QUIET_ENV, "PYTHONPATH": str(ROOT)}
        done = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        lines = done.stdout.strip().splitlines()
        self.assertEqual(lines[-2], "200 200")
        self.assertEqual(lines[-1], "[]")


class Lazy(unittest.TestCase):
    def test_imports_on_first_read_and_forwards_writes(self) -> None:
        module = lazy("json")
        self.assertFalse(loaded(module))
        self.assertEqual(module.dumps([1]), "[1]")
        self.assertTrue(loaded(module))
        import json

        with mock.patch.object(module, "dumps", return_value="patched"):
            self.assertEqual(json.dumps([1]), "patched")
        self.assertEqual(json.dumps([1]), "[1]")


if __name__ == "__main__":
    unittest.main()
