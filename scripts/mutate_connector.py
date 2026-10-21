#!/usr/bin/env python3
"""Mutating the HOSTED CONNECTOR's decision constants, both ways.

    python scripts/mutate_connector.py          # every mutant
    python scripts/mutate_connector.py 0 6      # mutants 0..5 (a run in parts)

What is mutated: where OAuth may send the person back (claude.ai's callback
exactly, the loopback /callback only), how long a sign-in link, a code, an
access and a refresh token live, PKCE, how keys and tokens are hashed, the
key/name/pepper floors, a replayed grant ending its family, the 401 on /mcp,
which tools need a signed-in user, the attribution row written BEFORE a
guarded tool runs, the probe's methods and the failed-sign-in limit.

Built like `scripts/mutate_round10.py`: the file is edited on disk, the suite
runs under `python -B` with `__pycache__` removed, and the file is PUT BACK as
it was. The first line is the HEALTHY run.

THREE OUTCOMES (Р1): pass — healthy green and every mutant red; fail — healthy
red or a mutant stayed quiet; could not measure — a mutant's target is not in
its file.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.mcp.tests.test_connector_http", "studio.mcp.tests.test_connector_deploy")

OA = "studio/mcp/oauth.py"
CS = "studio/mcp/connector_store.py"
HA = "studio/mcp/http_app.py"

_RECORD = (
    "                await run_in_threadpool(\n"
    "                    store.record_call, user, client_id, tool, GUARDED[tool], arguments\n"
    "                )\n"
)
_RUN = "        await app(scope, receive, send)\n\n    front.inner = app"

#: (file, was, becomes, what breaks).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # where the person is sent back
    (OA, 'REDIRECT_EXACT = ("https://claude.ai/api/mcp/auth_callback",)',
     'REDIRECT_EXACT = ("https://claude.ai/api/mcp/auth_callback", "https://evil.example/cb")',
     "a stranger callback registers"),
    (OA, 'REDIRECT_EXACT = ("https://claude.ai/api/mcp/auth_callback",)',
     'REDIRECT_EXACT = ("https://claude.ai/api/mcp/auth_callbackНЕТ",)',
     "claude.ai cannot register"),
    (OA, 'REDIRECT_LOOPBACK_HOSTS = ("localhost", "127.0.0.1")',
     'REDIRECT_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "evil.example")',
     "a remote host counts as the loopback"),
    (OA, 'REDIRECT_LOOPBACK_HOSTS = ("localhost", "127.0.0.1")',
     'REDIRECT_LOOPBACK_HOSTS = ("localhost",)', "127.0.0.1 /callback refused"),
    (OA, "        and parts.path == REDIRECT_LOOPBACK_PATH\n",
     "        and parts.path.startswith(REDIRECT_LOOPBACK_PATH)\n",
     "any path under /callback allowed"),
    (OA, 'REDIRECT_LOOPBACK_PATH = "/callback"', 'REDIRECT_LOOPBACK_PATH = "/cb"',
     "Claude Code's /callback refused"),
    (OA, '        parts.scheme == "http"\n', '        parts.scheme in ("http", "https")\n',
     "https loopback allowed"),
    (OA, "        and not parts.fragment\n", "", "a fragment on the loopback allowed"),
    (OA, "        and not parts.username\n", "", "userinfo on the loopback allowed"),
    # lifetimes
    (OA, "PENDING_S = 600", "PENDING_S = 120", "sign-in link back to two minutes"),
    (OA, "PENDING_S = 600", "PENDING_S = 86400", "sign-in link lives a day"),
    (OA, "CODE_S = 300", "CODE_S = 60", "a code dies before it is exchanged"),
    (OA, "CODE_S = 300", "CODE_S = 3600", "a code lives an hour"),
    (OA, "ACCESS_S = 3600", "ACCESS_S = 600", "access token dies in ten minutes"),
    (OA, "ACCESS_S = 3600", "ACCESS_S = 86400", "access token lives a day"),
    (OA, "REFRESH_S = 30 * 86400", "REFRESH_S = 7 * 86400", "refresh token dies in a week"),
    (OA, "REFRESH_S = 30 * 86400", "REFRESH_S = 365 * 86400", "refresh token lives a year"),
    (CS, '                " WHERE hash = ? AND kind = ? AND expires >= ?",\n',
     '                " WHERE hash = ? AND kind = ? AND expires >= ? OR 1",\n',
     "an expired grant still answers"),
    # PKCE
    (OA, '                "code_challenge": params.code_challenge,\n',
     '                "code_challenge": params.state,\n',
     "the stored challenge is not the one sent"),
    # hashing and floors
    (CS, "        if self.pepper:\n            return hmac", "        if False:\n            return hmac",
     "the pepper is ignored: a copied database acts"),
    (CS, "        return hashlib.sha256(value.encode()).hexdigest()\n\n    def _tx",
     "        return value\n\n    def _tx", "without a pepper secrets are stored as themselves"),
    (CS, "USER_KEY_MIN_CHARS = 40", "USER_KEY_MIN_CHARS = 39", "a 39-character key accepted"),
    (CS, "USER_KEY_MIN_CHARS = 40", "USER_KEY_MIN_CHARS = 41", "a 40-character key refused"),
    (CS, r'USER_NAME = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,39}\Z")',
     r'USER_NAME = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,40}\Z")', "a 41-character name accepted"),
    (CS, r'USER_NAME = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,39}\Z")',
     r'USER_NAME = re.compile(r"\A[a-z0-9][a-z0-9._:-]{0,39}\Z")', "a user name can be the probe"),
    (CS, 'PROBE_USER = "probe:"', 'PROBE_USER = "probe"', "the probe collides with a user name"),
    (CS, "ARGUMENT_CHARS = 2_000", "ARGUMENT_CHARS = 1_999", "a 2000-character argument cut"),
    (CS, "ARGUMENT_CHARS = 2_000", "ARGUMENT_CHARS = 2_001", "a 2001-character argument kept"),
    (HA, "PEPPER_MIN_CHARS = 32", "PEPPER_MIN_CHARS = 31", "a 31-character pepper accepted"),
    (HA, "PEPPER_MIN_CHARS = 32", "PEPPER_MIN_CHARS = 33", "a 32-character pepper refused"),
    (CS, '                db.execute("DELETE FROM oauth_grants WHERE family = ?", (family,))\n'
     '                return "replayed", None\n',
     '                db.execute("SELECT 1")\n                return "replayed", None\n',
     "a replayed refresh leaves the family alive"),
    # /mcp and the guard
    (HA, "        if domain:\n            token = bearer(headers)",
     "        if False:\n            token = bearer(headers)", "/mcp open without a token"),
    (HA, "            if who is None:\n", "            if who is None and False:\n",
     "an unknown token passes"),
    (HA, '    "search_web": "spends the owner\'s search API key",\n', "",
     "search_web unguarded"),
    (HA, '    "probe_model_limit": "calls a vendor API with the owner\'s key",\n',
     '    "probe_model_limit": "calls a vendor API with the owner\'s key",\n'
     '    "check_lipsync_prompt": "reads",\n', "a reading tool guarded and recorded"),
    (HA, "                if not user:\n                    await JSONResponse(refusal",
     "                if False:\n                    await JSONResponse(refusal",
     "a guarded tool runs with nobody signed in"),
    (HA, _RECORD, "", "a guarded call leaves no row"),
    (HA, _RUN,
     "        await app(scope, receive, send)\n"
     '        if scope["method"] == "POST" and user:\n'
     "            for _id, tool, arguments in tool_calls_in(body):\n"
     "                if tool in GUARDED:\n"
     "                    await run_in_threadpool(\n"
     "                        store.record_call, user, client_id, tool, GUARDED[tool], arguments\n"
     "                    )\n\n    front.inner = app",
     "attribution written AFTER the tool ran"),
    (HA, 'PROBE_METHODS = ("initialize", "notifications/initialized", "tools/list", "ping")',
     'PROBE_METHODS = ("initialize", "notifications/initialized", "tools/list", "ping", "tools/call")',
     "the probe may call tools"),
    (HA, 'PROBE_METHODS = ("initialize", "notifications/initialized", "tools/list", "ping")',
     'PROBE_METHODS = ("initialize", "notifications/initialized", "ping")',
     "the probe cannot list tools"),
    (HA, "LOGIN_CAPACITY, LOGIN_REFILL_PER_S = 10, 1 / 30",
     "LOGIN_CAPACITY, LOGIN_REFILL_PER_S = 100, 1 / 30", "a hundred wrong keys per address"),
    (HA, "LOGIN_CAPACITY, LOGIN_REFILL_PER_S = 10, 1 / 30",
     "LOGIN_CAPACITY, LOGIN_REFILL_PER_S = 5, 1 / 30", "five typos lock the owner out"),
)


def clean() -> None:
    for p in ROOT.rglob("__pycache__"):
        if ".claude" not in p.parts:
            shutil.rmtree(p, ignore_errors=True)


def run() -> int:
    clean()
    return subprocess.run(
        [sys.executable, "-B", "-m", "unittest", *НАБОРЫ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).returncode


def main(argv: list[str]) -> int:
    с, по = (int(argv[0]), int(argv[1])) if len(argv) == 2 else (0, len(MUTANTS))
    здоровый = run()
    print(f"ЗДОРОВЫЙ | тесты rc={здоровый}")
    if здоровый != 0:
        print("не годно: здоровое дерево красное — таблица мутаций ничего не значит")
        return 1
    промолчали: list[str] = []
    нет_цели: list[str] = []
    for файл, было, стало, что in MUTANTS[с:по]:
        путь = ROOT / файл
        исходный = путь.read_text()
        if исходный.count(было) != 1:
            нет_цели.append(f"{файл}: {что} (цель найдена {исходный.count(было)} раз)")
            print(f"НЕТ ЦЕЛИ | {что}")
            continue
        try:
            путь.write_text(исходный.replace(было, стало))
            rc = run()
        finally:
            путь.write_text(исходный)
        print(f"{'покраснел' if rc else 'ПРОМОЛЧАЛ'} | {что}", flush=True)
        if rc == 0:
            промолчали.append(что)
    clean()
    print(f"мутантов {по - с}, промолчали {len(промолчали)}, без цели {len(нет_цели)}")
    if нет_цели:
        print("не смогли: " + "; ".join(нет_цели))
        return 2
    if промолчали:
        print("не годно: " + "; ".join(промолчали))
        return 1
    print("годно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
