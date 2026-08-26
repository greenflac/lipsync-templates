"""Reuse a finished prompt, but only while it is still the right answer.

A prompt cache is easy to write and easy to get wrong in one specific way: the
key describes the REQUEST, so the cache keeps serving after the things that
shaped the ANSWER have changed. Change a model card's limits, add 400 rows to
the corpus, retune a rule, and a request-keyed cache happily replays a prompt
built against last week's world.

So the key here is the request AND a fingerprint of everything that shaped the
answer: the corpus contents, the registry, and the rule table. When any of
those move, every entry keyed to the old fingerprint stops matching. Nothing
has to be invalidated by hand, and nothing silently survives a change it should
not have survived.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from lipsync.fork_identity import PASS, UNMEASURED
from studio.selfrag.corpus import CorpusRecord
from studio.selfrag.db import connect, lock_for, state_path
from studio.selfrag.reflect import RULES
from studio.selfrag.registry import MODEL_CARDS

__all__ = ["PromptCache", "fingerprint", "spec_key"]


def fingerprint(records: Sequence[CorpusRecord]) -> str:
    """A hash of everything that shapes an answer, so a change expires the cache.

    Covers the corpus (ids and ratings — a re-rated record changes ranking),
    the registry (every card's identity and limits) and the rule table.

    >>> len(fingerprint([]))
    16
    """
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda r: r.record_id):
        digest.update(f"{record.record_id}|{record.rating}|{len(record.prompt)}\x00".encode())
    for model_id in sorted(MODEL_CARDS):
        card = MODEL_CARDS[model_id]
        digest.update(
            f"{model_id}|{card.status}|{card.max_seconds}|{card.skeleton}|"
            f"{card.i2v_skeleton}|{card.negative_prompt}|{card.word_band}\x00".encode()
        )
    for name, _ in RULES:
        digest.update(f"rule:{name}\x00".encode())
    return digest.hexdigest()[:16]


def _plain(value: Any) -> Any:
    """Make a spec JSON-comparable without depending on repr stability."""
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _plain(v) for k, v in asdict(value).items() if k != "extra"}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in sorted(value.items())}
    return value


def spec_key(spec: Any, *, fingerprint_value: str) -> str:
    """The cache key: the request, plus what shaped the answer."""
    body = json.dumps(_plain(spec), sort_keys=True, default=str)
    return hashlib.sha256(f"{fingerprint_value}\x00{body}".encode()).hexdigest()


class PromptCache:
    """Content-addressed storage for finished prompts."""

    def __init__(self, *, path: str | None = None, fingerprint_value: str = "") -> None:
        self.path = path or str(state_path())
        self._conn: sqlite3.Connection = connect(self.path)
        self._lock = lock_for(state_path() if path is None else Path(path))
        self.fingerprint = fingerprint_value

    def get(self, spec: Any) -> dict:
        """Look a spec up. Three outcomes; a miss is not a failure.

        A miss returns `could not measure`, not `fail`: the cache did not
        answer the question, it did not answer it wrongly. Counting misses as
        failures is how a cache-hit-rate metric turns into a fake error rate.
        """
        if not self.fingerprint:
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": "the cache has no fingerprint: it cannot know if an entry is stale",
                "payload": None,
            }
        key = spec_key(spec, fingerprint_value=self.fingerprint)
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, hits FROM cache WHERE key = ? AND fingerprint = ?",
                (key, self.fingerprint),
            ).fetchone()
            if row is None:
                return {
                    "outcome": UNMEASURED,
                    "checked": 1,
                    "violations": 0,
                    "unmeasured": 1,
                    "note": "cache miss",
                    "payload": None,
                }
            with self._conn:
                self._conn.execute("UPDATE cache SET hits = hits + 1 WHERE key = ?", (key,))
        return {
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "note": f"cache hit ({row['hits'] + 1} total)",
            "payload": json.loads(row["payload"]),
        }

    def put(self, spec: Any, payload: dict) -> str:
        """Store a finished result and return its key."""
        key = spec_key(spec, fingerprint_value=self.fingerprint)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache(key, model, mode, prompt, payload, fingerprint,"
                " created_at, hits) VALUES (?,?,?,?,?,?,?,COALESCE("
                "(SELECT hits FROM cache WHERE key = ?), 0))",
                (
                    key,
                    str(getattr(spec, "model", "")),
                    str(getattr(spec, "mode", "")),
                    str(payload.get("prompt") or ""),
                    json.dumps(payload, default=str),
                    self.fingerprint,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    key,
                ),
            )
        return key

    def sweep(self) -> dict:
        """Delete every entry keyed to a fingerprint other than the current one."""
        with self._lock, self._conn:
            before = self._conn.execute("SELECT COUNT(*) AS n FROM cache").fetchone()["n"]
            self._conn.execute("DELETE FROM cache WHERE fingerprint <> ?", (self.fingerprint,))
            after = self._conn.execute("SELECT COUNT(*) AS n FROM cache").fetchone()["n"]
        return {
            "outcome": PASS,
            "checked": before,
            "violations": 0,
            "unmeasured": 0,
            "note": f"dropped {before - after} stale entries, kept {after}",
            "dropped": before - after,
        }

    def stats(self) -> dict:
        """Entry count and total hits, for the monitor."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS entries, COALESCE(SUM(hits), 0) AS hits FROM cache"
            ).fetchone()
        return {"entries": int(row["entries"]), "hits": int(row["hits"])}

    def close(self) -> None:
        """Close the connection. Idempotent."""
        with self._lock:
            self._conn.close()
