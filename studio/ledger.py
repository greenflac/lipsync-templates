"""Credit journal: the balance is the sum of an append-only log, never a stored column.

A stored balance and a log of operations are two places holding one truth, and
they drift the moment a write half-lands. Here there is one place: rows. A
charge appends a negative row, a refund appends a compensating positive row.
Nothing is ever updated or deleted, so every balance can be re-derived and
every movement can be explained by the row that caused it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

DEFAULT_DB_PATH = Path("studio_state.sqlite3")

# Real money moves through this table, so the uniqueness of the idempotency key
# is enforced by the database, not by a read-then-write in Python: a duplicate
# insert must be rejected even when two callers race on the same key.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT    NOT NULL,
    delta           INTEGER NOT NULL,
    reason          TEXT    NOT NULL,
    idempotency_key TEXT    NOT NULL UNIQUE,
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ledger_entries_user ON ledger_entries (user_id);
"""


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open the journal database and make sure its schema exists.

    Callers that need the session table too get it from `studio.store`; both
    modules live in one file so a charge and the session it paid for can be
    read back together.

    Example:
        >>> conn = connect(":memory:")
        >>> conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
        0
    """
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # Without foreign-key-free WAL the default rollback journal is enough here;
    # what matters is that a failed balance check leaves no partial row behind.
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _verdict(
    outcome: str,
    note: str,
    *,
    checked: int = 1,
    violations: int = 0,
    unmeasured: int = 0,
    **extra: object,
) -> dict:
    """Build the three-outcome dict every judging function in the studio returns."""
    result: dict = {
        "outcome": outcome,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
        "note": note,
    }
    result.update(extra)
    return result


def balance(user_id: str, *, db_path: Path | str = DEFAULT_DB_PATH) -> int:
    """Return the user's credit balance as the sum of their journal rows.

    Example:
        >>> balance("nobody", db_path=":memory:")
        0
    """
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(delta), 0) AS total FROM ledger_entries WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row["total"])
    finally:
        conn.close()


def entries(user_id: str, *, db_path: Path | str = DEFAULT_DB_PATH) -> list[dict]:
    """Return every journal row of the user, oldest first.

    Example:
        >>> entries("nobody", db_path=":memory:")
        []
    """
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ledger_entries WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _replay(conn: sqlite3.Connection, key: str, user_id: str) -> dict | None:
    """Return the verdict of an entry already written under `key`, or None."""
    row = conn.execute("SELECT * FROM ledger_entries WHERE idempotency_key = ?", (key,)).fetchone()
    if row is None:
        return None
    total = conn.execute(
        "SELECT COALESCE(SUM(delta), 0) AS total FROM ledger_entries WHERE user_id = ?",
        (row["user_id"],),
    ).fetchone()["total"]
    if row["user_id"] != user_id:
        # The same key under a different user is a caller bug, not a replay:
        # answering PASS here would silently credit the wrong account.
        return _verdict(
            FAIL,
            f"idempotency key {key!r} already belongs to user {row['user_id']!r}, not {user_id!r}",
            violations=1,
            balance=int(total),
            delta=0,
            key=key,
            duplicate=True,
        )
    return _verdict(
        PASS,
        f"replay of {key!r}: delta {row['delta']}, balance {int(total)}, no second row written",
        balance=int(total),
        delta=int(row["delta"]),
        key=key,
        duplicate=True,
    )


def _append(
    user_id: str,
    delta: int,
    *,
    key: str,
    reason: str,
    db_path: Path | str,
    require_funds: bool,
) -> dict:
    """Append one journal row, or replay the row a previous call left under `key`."""
    if not key:
        return _verdict(FAIL, "idempotency key is empty; refusing to move credits", violations=1)
    if delta == 0:
        return _verdict(FAIL, "delta 0 moves nothing; refusing to write a no-op row", violations=1)

    try:
        conn = connect(db_path)
    except sqlite3.Error as exc:
        # The journal is unreachable, so nothing was judged: this is neither a
        # successful charge nor an insufficient balance.
        return _verdict(
            UNMEASURED,
            f"journal unavailable at {db_path!s}: {exc}",
            checked=0,
            unmeasured=1,
            key=key,
        )

    try:
        # IMMEDIATE takes the write lock before the balance is read, so a
        # concurrent charge cannot slip between the check and the insert.
        conn.execute("BEGIN IMMEDIATE")
        replayed = _replay(conn, key, user_id)
        if replayed is not None:
            conn.execute("ROLLBACK")
            return replayed

        current = int(
            conn.execute(
                "SELECT COALESCE(SUM(delta), 0) AS total FROM ledger_entries WHERE user_id = ?",
                (user_id,),
            ).fetchone()["total"]
        )
        if require_funds and current + delta < 0:
            conn.execute("ROLLBACK")
            return _verdict(
                FAIL,
                f"insufficient credits: balance {current}, requested {-delta}, "
                f"short by {-delta - current}",
                violations=1,
                balance=current,
                delta=0,
                key=key,
                duplicate=False,
            )

        conn.execute(
            "INSERT INTO ledger_entries (user_id, delta, reason, idempotency_key, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, delta, reason, key, _now()),
        )
        conn.execute("COMMIT")
    except sqlite3.IntegrityError:
        # Another writer won the race on this key; its row is the truth.
        conn.execute("ROLLBACK")
        replayed = _replay(conn, key, user_id)
        conn.close()
        if replayed is not None:
            return replayed
        return _verdict(
            UNMEASURED,
            f"key {key!r} was rejected as duplicate but no row can be read back",
            checked=0,
            unmeasured=1,
            key=key,
        )
    except sqlite3.Error as exc:
        conn.execute("ROLLBACK")
        conn.close()
        return _verdict(
            UNMEASURED,
            f"journal write failed: {exc}",
            checked=0,
            unmeasured=1,
            key=key,
        )

    try:
        after = int(
            conn.execute(
                "SELECT COALESCE(SUM(delta), 0) AS total FROM ledger_entries WHERE user_id = ?",
                (user_id,),
            ).fetchone()["total"]
        )
    finally:
        conn.close()
    return _verdict(
        PASS,
        f"{reason}: delta {delta}, balance {after}",
        balance=after,
        delta=delta,
        key=key,
        duplicate=False,
    )


def charge(
    user_id: str,
    credits: int,
    *,
    key: str,
    reason: str,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict:
    """Take `credits` from the user by appending a negative journal row.

    Args:
        user_id: whose balance moves.
        credits: a positive number of credits to take.
        key: idempotency key; the same key never charges twice.
        reason: why the credits moved, stored with the row.
        db_path: journal file; tests point it at a temporary path.

    Returns a three-outcome dict: PASS with the new `balance`, FAIL with the
    numbers when the balance is short, UNMEASURED when the journal is
    unreachable. A short balance is an outcome, not an exception.

    Example:
        >>> charge("u1", 1, key="k1", reason="frame", db_path=":memory:")["outcome"]
        'fail'
    """
    if credits <= 0:
        return _verdict(
            FAIL,
            f"charge needs a positive amount, got {credits}; use refund to give credits back",
            violations=1,
            key=key,
        )
    return _append(user_id, -credits, key=key, reason=reason, db_path=db_path, require_funds=True)


def refund(
    user_id: str,
    credits: int,
    *,
    key: str,
    reason: str,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict:
    """Give `credits` back with a compensating positive row; the charge row stays.

    The charge is never deleted or updated: after a refund the journal holds
    both rows, which is what makes the movement auditable.

    Args:
        user_id: whose balance moves.
        credits: a positive number of credits to return.
        key: idempotency key; the same key never refunds twice.
        reason: why the credits moved, stored with the row.
        db_path: journal file; tests point it at a temporary path.

    Example:
        >>> refund("u1", 1, key="r1", reason="engine failed", db_path=":memory:")["delta"]
        1
    """
    if credits <= 0:
        return _verdict(
            FAIL,
            f"refund needs a positive amount, got {credits}; use charge to take credits",
            violations=1,
            key=key,
        )
    return _append(user_id, credits, key=key, reason=reason, db_path=db_path, require_funds=False)
