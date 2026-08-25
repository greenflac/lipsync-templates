"""Session state for the studio: one row per user journey, in the same sqlite file.

A session is what the user has decided so far — the template, the selfie, the
StyleSpec the agent extracted, the last job, the stage they reached. It lives
next to the credit journal (`studio.ledger`) so a charge and the session it
paid for can be read back from one file.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Mapping

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from .ledger import DEFAULT_DB_PATH, _now, connect as _connect_ledger

STAGE_NEW = "new"

# Only these columns may be written through `update`. An unknown name is a
# typo in a caller, and a typo that silently does nothing is the expensive
# kind: the user would see the old template and nobody would know why.
SESSION_FIELDS: tuple[str, ...] = (
    "template",
    "selfie_path",
    "style_spec",
    "last_job_id",
    "stage",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    template    TEXT,
    selfie_path TEXT,
    style_spec  TEXT,
    last_job_id TEXT,
    stage       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id);
"""


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open the state database and make sure both studio schemas exist.

    Example:
        >>> connect(":memory:").execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        0
    """
    conn = _connect_ledger(db_path)
    conn.executescript(_SCHEMA)
    return conn


def _verdict(
    outcome: str,
    note: str,
    *,
    checked: int = 1,
    violations: int = 0,
    unmeasured: int = 0,
    **extra: object,
) -> dict:
    result: dict = {
        "outcome": outcome,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
        "note": note,
    }
    result.update(extra)
    return result


def _encode(field: str, value: Any) -> Any:
    """Turn a field value into something sqlite stores; StyleSpec becomes JSON."""
    if field != "style_spec" or value is None or isinstance(value, str):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return json.dumps(dataclasses.asdict(value), sort_keys=True)
    if isinstance(value, Mapping):
        return json.dumps(dict(value), sort_keys=True)
    raise TypeError(f"style_spec must be a StyleSpec, a mapping, JSON text or None, got {value!r}")


def _decode(row: sqlite3.Row) -> dict:
    """Turn a stored row into the session dict callers see."""
    session = dict(row)
    raw = session.get("style_spec")
    if isinstance(raw, str):
        try:
            session["style_spec"] = json.loads(raw)
        except json.JSONDecodeError:
            # Keep the raw text rather than lose it: a caller can still see
            # what was stored and decide what to do.
            pass
    return session


def create_session(user_id: str, *, db_path: Path | str = DEFAULT_DB_PATH) -> str:
    """Create an empty session for `user_id` and return its new session_id.

    Example:
        >>> len(create_session("u1", db_path=":memory:"))
        36
    """
    session_id = str(uuid.uuid4())
    stamp = _now()
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, stage, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, STAGE_NEW, stamp, stamp),
        )
    finally:
        conn.close()
    return session_id


def get(session_id: str, *, db_path: Path | str = DEFAULT_DB_PATH) -> dict | None:
    """Return the session as a dict, or None when there is no such session.

    Example:
        >>> get("no-such-session", db_path=":memory:") is None
        True
    """
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    finally:
        conn.close()
    return None if row is None else _decode(row)


def update(session_id: str, *, db_path: Path | str = DEFAULT_DB_PATH, **fields: Any) -> dict:
    """Write only the named fields of a session, leaving every other column alone.

    Args:
        session_id: which session to write.
        db_path: state file; tests point it at a temporary path.
        **fields: any of SESSION_FIELDS; `style_spec` accepts a StyleSpec, a
            mapping, JSON text or None.

    Returns a three-outcome dict carrying the stored session under `session`:
    FAIL for an unknown field or a missing session, UNMEASURED when the store
    is unreachable, PASS with the row that is now on disk.

    Example:
        >>> update("no-such-session", stage="styled", db_path=":memory:")["outcome"]
        'fail'
    """
    unknown = sorted(name for name in fields if name not in SESSION_FIELDS)
    if unknown:
        return _verdict(
            FAIL,
            f"unknown session fields {unknown}; known fields are {list(SESSION_FIELDS)}",
            checked=len(fields),
            violations=len(unknown),
            session=None,
        )
    if not fields:
        return _verdict(
            FAIL,
            "update called with no fields; nothing was judged and nothing written",
            checked=0,
            violations=1,
            session=None,
        )

    try:
        conn = connect(db_path)
    except sqlite3.Error as exc:
        return _verdict(
            UNMEASURED,
            f"session store unavailable at {db_path!s}: {exc}",
            checked=0,
            unmeasured=1,
            session=None,
        )

    try:
        names = sorted(fields)
        try:
            encoded = [_encode(name, fields[name]) for name in names]
        except TypeError as exc:
            return _verdict(
                FAIL,
                str(exc),
                checked=len(names),
                violations=1,
                session=None,
            )
        assignments = ", ".join(f"{name} = ?" for name in names) + ", updated_at = ?"
        values = [*encoded, _now(), session_id]
        cursor = conn.execute(f"UPDATE sessions SET {assignments} WHERE session_id = ?", values)
        if cursor.rowcount == 0:
            return _verdict(
                FAIL,
                f"no session {session_id!r}; {len(names)} field(s) were not written",
                checked=len(names),
                violations=1,
                session=None,
            )
        row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    except sqlite3.Error as exc:
        return _verdict(
            UNMEASURED,
            f"session write failed: {exc}",
            checked=0,
            unmeasured=1,
            session=None,
        )
    finally:
        conn.close()

    return _verdict(
        PASS,
        f"wrote {len(names)} field(s) of session {session_id!r}: {names}",
        checked=len(names),
        session=_decode(row),
    )
