#!/usr/bin/env python3
"""Live smoke test of the hosted connector over REAL HTTP on the loopback.

The unit suite (studio/mcp/tests/test_connector_http.py) drives the app in
process, because the test runner forbids sockets (rule T4). This script is
the other half: it starts `python -m studio.mcp.http_app serve` as a real
uvicorn process on 127.0.0.1, with OAuth on for a made-up domain, and walks
the whole claude.ai path over TCP: discovery 401 -> metadata -> /register ->
/authorize -> the sign-in page -> /token -> initialize -> tools/list -> one
guarded call (refused by the tool itself before any request: no paid call)
-> the attribution row. It also prints how long the first `initialize` took
after the process started, which is what a cold deploy costs a client.

Nothing leaves the machine: every request goes to 127.0.0.1, the domain only
travels in the Host header.

    python scripts/connector_smoke.py            # exit 0 = every step passed
    python scripts/connector_smoke.py --warm     # with the index build running meanwhile
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "studio.smoke.test"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Http:
    def __init__(self, port: int) -> None:
        self.port = port

    def call(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        conn.request(method, path, body=body, headers={"Host": DOMAIN, **(headers or {})})
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), data


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}{(': ' + detail) if detail else ''}")
    if not ok:
        raise SystemExit(1)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="studio-connector-smoke-"))
    pepper = tmp / "pepper"
    pepper.write_text(secrets.token_urlsafe(48))
    pepper.chmod(0o600)
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "STUDIO_DOMAIN": DOMAIN,
        "STUDIO_KEY_PEPPER_FILE": str(pepper),
        "STUDIO_CONNECTOR_DB": str(tmp / "connector.sqlite3"),
        "STUDIO_MCP_WARM_INDEX": "1" if "--warm" in sys.argv[1:] else "0",
        "STUDIO_NO_JOURNAL": "1",
    }
    made = subprocess.run(
        [sys.executable, "-m", "studio.mcp.http_app", "new-user", "smoke"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    key = made.stdout.strip().splitlines()[-1]
    port = free_port()
    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "-m", "studio.mcp.http_app", "serve", "--port", str(port)],
        cwd=ROOT,
        env=env,
    )
    web = Http(port)
    try:
        for _ in range(300):
            try:
                status, _, _ = web.call("GET", "/healthz")
                if status == 200:
                    break
            except OSError:
                time.sleep(0.1)
        else:
            step("healthz", False, "the server never answered")
        accept = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        init = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "1"},
                },
            }
        ).encode()
        status, headers, _ = web.call("POST", "/mcp", init, accept)
        step(
            "keyless /mcp is 401 with a challenge",
            status == 401 and "resource_metadata" in headers.get("www-authenticate", ""),
        )
        status, _, data = web.call("GET", "/.well-known/oauth-protected-resource/mcp")
        step("resource metadata", status == 200, json.loads(data)["resource"])
        status, _, data = web.call(
            "POST",
            "/register",
            json.dumps(
                {
                    "redirect_uris": [CALLBACK],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                }
            ).encode(),
            {"Content-Type": "application/json"},
        )
        step("dynamic client registration", status == 201)
        client_id = json.loads(data)["client_id"]
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        status, headers, _ = web.call(
            "GET",
            "/authorize?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": client_id,
                    "redirect_uri": CALLBACK,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "state": "smoke",
                    "resource": f"https://{DOMAIN}/mcp",
                }
            ),
        )
        login = urlparse(headers.get("location", ""))
        step("authorize sends to the sign-in page", status == 302 and login.path == "/oauth/login")
        request = parse_qs(login.query)["request"][0]
        form = {"Content-Type": "application/x-www-form-urlencoded"}
        status, headers, _ = web.call(
            "POST", "/oauth/login", urlencode({"request": request, "key": key}).encode(), form
        )
        back = urlparse(headers.get("location", ""))
        step(
            "sign-in returns to claude.ai with a code", status == 302 and back.netloc == "claude.ai"
        )
        code = parse_qs(back.query)["code"][0]
        status, _, data = web.call(
            "POST",
            "/token",
            urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": CALLBACK,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "resource": f"https://{DOMAIN}/mcp",
                }
            ).encode(),
            form,
        )
        step("token exchange", status == 200)
        token = json.loads(data)["access_token"]
        auth = {**accept, "Authorization": f"Bearer {token}", "MCP-Protocol-Version": "2025-11-25"}
        t0 = time.monotonic()
        status, _, data = web.call("POST", "/mcp", init, auth)
        step(
            "initialize",
            status == 200,
            f"{time.monotonic() - t0:.2f} s; {time.monotonic() - started:.1f} s after process start",
        )
        status, _, data = web.call(
            "POST",
            "/mcp",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode(),
            auth,
        )
        step("tools/list", status == 200, f"{len(json.loads(data)['result']['tools'])} tools")
        status, _, data = web.call(
            "POST",
            "/mcp",
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "probe_model_limit",
                        "arguments": {
                            "url": "https://api.example.test/v1",
                            "field": "duration",
                            "absurd_value": "5",
                        },
                    },
                }
            ).encode(),
            auth,
        )
        step(
            "guarded call runs (and is refused by the tool itself)",
            status == 200 and b"absurdity floor" in data,
        )
        listed = subprocess.run(
            [sys.executable, "-m", "studio.mcp.http_app", "calls"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        row = json.loads(listed.strip().splitlines()[0])
        step("attribution row", row["user"] == "smoke" and row["tool"] == "probe_model_limit")
        probed = subprocess.run(
            [sys.executable, "-m", "studio.mcp.http_app", "probe", "--port", str(port)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        step(
            "the release probe (what release.sh runs in the container)",
            probed.returncode == 0,
            probed.stdout.strip(),
        )
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    print("connector smoke: every step passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
