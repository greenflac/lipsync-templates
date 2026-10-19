"""What the hosted connector keeps: users, OAuth clients and grants, and who called what.

Adapted from green-harness (`harness/server_app/store.py`, OAuth part, and
migration `0008_oauth.sql`), where the same scheme has served the claude.ai
connector at harness.greenflac.online since 2026-10-06. Differences, on purpose:

* SQLite only. The studio connector is one process on one machine; the
  harness needed Postgres for its other tables, this does not.
* A USER, not a tenant: the studio's knowledge base is shared, so the key
  says WHO is writing to it, not whose copy they write to. A user has a name
  (`owner`, `anna`), and that name is what attribution records.

Nothing secret is stored as itself. A user key, a pending authorization, a
code, an access and a refresh token are all kept as HMAC-SHA256 under the
pepper (`STUDIO_KEY_PEPPER_FILE`), so a copied database acts for nobody. A
code and a refresh token are single use; presenting a spent one again ends
everything issued from the same sign-in (RFC 9700), as in the harness.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    key_hash TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, at TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id TEXT PRIMARY KEY, info TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_grants (
    hash TEXT PRIMARY KEY, kind TEXT NOT NULL, client_id TEXT NOT NULL,
    user TEXT NOT NULL, family TEXT NOT NULL, body TEXT NOT NULL, expires TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS oauth_grants_family ON oauth_grants (family);
CREATE INDEX IF NOT EXISTS oauth_grants_user ON oauth_grants (user);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, user TEXT NOT NULL,
    client_id TEXT NOT NULL, tool TEXT NOT NULL, kind TEXT NOT NULL,
    arguments TEXT NOT NULL, arguments_sha256 TEXT NOT NULL);
"""

#: The release probe's principal (green-harness `PROBE_OWNER`): a token minted
#: for it inside the container may only open the transport and list tools
#: (http_app.PROBE_METHODS). No user name can collide: names never hold ":".
PROBE_USER = "probe:"
#: A user name: what attribution prints, so short and plain.
USER_NAME = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,39}\Z")
#: CHOSEN (as in the harness, TENANT_KEY_MIN_CHARS): 32 random bytes, url-safe.
USER_KEY_MIN_CHARS = 40
#: The longest argument value kept verbatim in the attribution row; longer ones
#: are cut and marked. The sha256 of the whole call is kept either way.
ARGUMENT_CHARS = 2_000


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class StoreError(ValueError):
    """A refusal the CLI prints as it is."""


class ConnectorStore:
    """One SQLite file; every method is one short transaction under a lock."""

    def __init__(self, path: Path | str, pepper: str = "") -> None:
        self.path = str(path)
        self.pepper = pepper
        self._lock = threading.Lock()
        on_disk = self.path != ":memory:"
        if on_disk:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        if on_disk:
            self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    # - plumbing -

    def digest(self, value: str) -> str:
        """HMAC-SHA256 under the pepper, or plain sha256 without one (local runs, tests)."""
        if self.pepper:
            return hmac.new(self.pepper.encode(), value.encode(), hashlib.sha256).hexdigest()
        return hashlib.sha256(value.encode()).hexdigest()

    def _tx(self, work: Any) -> Any:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                result = work(self._db)
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")
            return result

    def health(self) -> bool:
        try:
            return self._tx(lambda db: db.execute("SELECT 1").fetchone()[0] == 1)
        except sqlite3.Error:
            return False

    # - users -

    def add_user(self, name: str, key: str) -> None:
        if not USER_NAME.match(name):
            raise StoreError(f"user name {name!r}: lowercase letters, digits, . _ -; at most 40")
        if len(key) < USER_KEY_MIN_CHARS:
            raise StoreError(f"a user key needs at least {USER_KEY_MIN_CHARS} characters")

        def work(db: sqlite3.Connection) -> None:
            if db.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone():
                raise StoreError(f"user {name!r} exists: `rekey-user` issues a new key")
            db.execute(
                "INSERT INTO users (key_hash, name, at) VALUES (?, ?, ?)",
                (self.digest(f"user:{key}"), name, now()),
            )

        self._tx(work)

    def rekey_user(self, name: str, key: str) -> None:
        """A new key for `name`; the old key and every token it signed in stop working."""

        def work(db: sqlite3.Connection) -> None:
            cur = db.execute(
                "UPDATE users SET key_hash = ?, disabled = 0 WHERE name = ?",
                (self.digest(f"user:{key}"), name),
            )
            if cur.rowcount != 1:
                raise StoreError(f"no user {name!r}")
            db.execute("DELETE FROM oauth_grants WHERE user = ?", (name,))

        self._tx(work)

    def disable_user(self, name: str) -> None:
        def work(db: sqlite3.Connection) -> None:
            cur = db.execute("UPDATE users SET disabled = 1 WHERE name = ?", (name,))
            if cur.rowcount != 1:
                raise StoreError(f"no user {name!r}")
            db.execute("DELETE FROM oauth_grants WHERE user = ?", (name,))

        self._tx(work)

    def users(self) -> list[tuple[str, str, bool]]:
        rows = self._tx(
            lambda db: db.execute("SELECT name, at, disabled FROM users ORDER BY name").fetchall()
        )
        return [(str(n), str(a), bool(d)) for n, a, d in rows]

    def user_of_key(self, key: str) -> str | None:
        """The user a key belongs to; None for an unknown or disabled key."""
        if not key:
            return None
        row = self._tx(
            lambda db: db.execute(
                "SELECT name FROM users WHERE key_hash = ? AND disabled = 0",
                (self.digest(f"user:{key}"),),
            ).fetchone()
        )
        return str(row[0]) if row else None

    # - OAuth (harness migration 0008, renamed tenant -> user) -

    def oauth_client_save(self, client_id: str, info: str) -> None:
        self._tx(
            lambda db: db.execute(
                "INSERT INTO oauth_clients (client_id, info, at) VALUES (?, ?, ?)"
                " ON CONFLICT (client_id) DO NOTHING",
                (client_id, info, now()),
            )
        )

    def oauth_client(self, client_id: str) -> str | None:
        row = self._tx(
            lambda db: db.execute(
                "SELECT info FROM oauth_clients WHERE client_id = ?", (client_id,)
            ).fetchone()
        )
        return str(row[0]) if row else None

    def oauth_grant_put(
        self, kind: str, value: str, client_id: str, user: str, family: str, body: str, expires: str
    ) -> None:
        def work(db: sqlite3.Connection) -> None:
            db.execute("DELETE FROM oauth_grants WHERE expires < ?", (now(),))
            db.execute(
                "INSERT INTO oauth_grants (hash, kind, client_id, user, family, body, expires)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.digest(f"{kind}:{value}"), kind, client_id, user, family, body, expires),
            )

        self._tx(work)

    def oauth_grant(
        self, kind: str, value: str, take: bool = False
    ) -> tuple[str, str, str, str] | None:
        """(client_id, user, body, family) of a live grant; `take` spends it in the same tx."""
        name = self.digest(f"{kind}:{value}")

        def work(db: sqlite3.Connection) -> tuple[str, str, str, str] | None:
            row = db.execute(
                "SELECT client_id, user, body, family FROM oauth_grants"
                " WHERE hash = ? AND kind = ? AND expires >= ?",
                (name, kind, now()),
            ).fetchone()
            if not row:
                return None
            if take:
                db.execute("DELETE FROM oauth_grants WHERE hash = ?", (name,))
            return str(row[0]), str(row[1]), str(row[2]), str(row[3])

        return self._tx(work)

    def oauth_spend(self, kind: str, value: str) -> tuple[str, tuple[str, str, str, str] | None]:
        """("ok", grant) the first time; ("replayed", None) after, and the family is gone."""
        name = self.digest(f"{kind}:{value}")

        def work(db: sqlite3.Connection) -> tuple[str, tuple[str, str, str, str] | None]:
            row = db.execute(
                "SELECT client_id, user, body, family, kind FROM oauth_grants"
                " WHERE hash = ? AND expires >= ?",
                (name, now()),
            ).fetchone()
            if not row:
                return "none", None
            client_id, user, body, family, found = (str(v) for v in row)
            if found == f"spent-{kind}":
                db.execute("DELETE FROM oauth_grants WHERE family = ?", (family,))
                return "replayed", None
            if found != kind:
                return "none", None
            db.execute("UPDATE oauth_grants SET kind = ? WHERE hash = ?", (f"spent-{kind}", name))
            return "ok", (client_id, user, body, family)

        return self._tx(work)

    def oauth_family_drop(self, family: str) -> None:
        if family:
            self._tx(lambda db: db.execute("DELETE FROM oauth_grants WHERE family = ?", (family,)))

    def who(self, access_token: str) -> tuple[str, str] | None:
        """(user, client_id) behind a live access token, or None.

        A raw user key is NOT a bearer here, unlike the harness: the key is
        typed on the sign-in page and nowhere else, so a key that leaks into a
        config file cannot be replayed at /mcp by itself.
        """
        if not access_token:
            return None
        grant = self.oauth_grant("access", access_token)
        if grant is None:
            return None
        user = grant[1]
        if user == PROBE_USER:
            return user, grant[0]
        live = self._tx(
            lambda db: db.execute(
                "SELECT 1 FROM users WHERE name = ? AND disabled = 0", (user,)
            ).fetchone()
        )
        return (user, grant[0]) if live else None

    # - attribution -

    def record_call(self, user: str, client_id: str, tool: str, kind: str, arguments: Any) -> int:
        """One row per guarded tool call, written BEFORE the tool runs."""
        whole = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
        kept = {
            k: (v if len(str(v)) <= ARGUMENT_CHARS else str(v)[:ARGUMENT_CHARS] + " [cut]")
            for k, v in (arguments.items() if isinstance(arguments, dict) else [])
        }
        row = (
            now(),
            user,
            client_id,
            tool,
            kind,
            json.dumps(kept, ensure_ascii=False, sort_keys=True, default=str),
            hashlib.sha256(whole.encode()).hexdigest(),
        )
        return int(
            self._tx(
                lambda db: (
                    db.execute(
                        "INSERT INTO tool_calls (at, user, client_id, tool, kind, arguments,"
                        " arguments_sha256) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        row,
                    ).lastrowid
                )
            )
        )

    def calls(self, limit: int = 50, user: str = "") -> list[dict[str, Any]]:
        def work(db: sqlite3.Connection) -> list[Any]:
            sql = "SELECT id, at, user, client_id, tool, kind, arguments FROM tool_calls"
            args: tuple[Any, ...] = ()
            if user:
                sql += " WHERE user = ?"
                args = (user,)
            return db.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()

        keys = ("id", "at", "user", "client_id", "tool", "kind", "arguments")
        return [dict(zip(keys, row)) for row in self._tx(work)]
