"""One sqlite file for everything this package remembers, opened one way.

Three tables share a connection because they are read together in the report
and written together in a run: splitting them into three files would buy
nothing and cost a transaction boundary.

The connection is opened `check_same_thread=False` and every statement runs
under a module lock. This is deliberate and is the fix for a defect found in
review: `studio/knowledge.py` caches one default-mode sqlite connection in a
module global, so the first `def` FastAPI route to touch it from a worker
thread raises `ProgrammingError`. Nothing calls that path yet, so it has never
fired — which is exactly why it is worth not repeating.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

__all__ = ["DEFAULT_STATE_PATH", "STATE_ENV", "SCHEMA", "connect", "state_path"]

STATE_ENV = "STUDIO_SELFRAG_STATE"
DEFAULT_STATE_PATH = Path(__file__).with_name("state.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    mode        TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    payload     TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    hits        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS replay (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id   TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    model       TEXT NOT NULL,
    rating      INTEGER,
    outcome     TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    artifact    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS replay_record ON replay(record_id);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    model       TEXT NOT NULL,
    mode        TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    checked     INTEGER NOT NULL DEFAULT 0,
    violations  INTEGER NOT NULL DEFAULT 0,
    unmeasured  INTEGER NOT NULL DEFAULT 0,
    rounds      INTEGER NOT NULL DEFAULT 0,
    cached      INTEGER NOT NULL DEFAULT 0,
    retrieved   INTEGER NOT NULL DEFAULT 0,
    rewrite_step INTEGER NOT NULL DEFAULT 0,
    confidence  REAL NOT NULL DEFAULT 0.0,
    latency_ms  REAL NOT NULL DEFAULT 0.0,
    rules       TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_created ON runs(created_at);
"""

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def state_path() -> Path:
    """Where this package keeps its state. Environment first, then the default."""
    override = os.environ.get(STATE_ENV, "").strip()
    return Path(override).expanduser() if override else DEFAULT_STATE_PATH


def lock_for(path: Path) -> threading.Lock:
    """The lock guarding one state file, created once per path."""
    key = str(path)
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.Lock()
        return _LOCKS[key]


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open (and migrate) the state database. `":memory:"` is honoured for tests."""
    target = Path(path) if path is not None else state_path()
    if str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.executescript(SCHEMA)
    return conn
