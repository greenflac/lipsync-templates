"""What shipped, how it scored, and how that changes the next ranking.

The corpus already carries a `rating` field, and until now nothing read it
back into retrieval: the ranking was blind to whether a prompt had ever
worked. This module closes that loop.

Two things it deliberately does NOT do:

* It does not train anything. A learned re-ranker over a few hundred feedback
  rows would fit the noise; a multiplier that a human can read and mutate is
  the honest instrument at this size.
* It does not let one bad result bury a record. A single negative report moves
  a record by a bounded amount, and `FEEDBACK_FLOOR` is the furthest anything
  can fall. The alternative — an unbounded penalty — turns one angry afternoon
  into a permanently unreachable corpus entry.

The distinction between "rated badly" and "never rated" is preserved all the
way through. An unrated record gets a multiplier of exactly 1.0, not 0.5.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.corpus import RATING_MAX, RATING_MIN, CorpusRecord
from studio.selfrag.db import connect, lock_for, state_path

__all__ = [
    "FEEDBACK_CEILING",
    "FEEDBACK_FLOOR",
    "FEEDBACK_STEP",
    "ReplayBuffer",
]

# The furthest feedback can move one record's ranking weight. CHOSEN, and
# bounded on purpose: a record at the floor is demoted, not deleted, because a
# deletion is a decision no automatic signal here is good enough to make.
FEEDBACK_FLOOR = 0.4
FEEDBACK_CEILING = 1.6

# How far one report moves the multiplier. CHOSEN so that it takes three
# consistent reports to reach either bound: one report is an anecdote.
FEEDBACK_STEP = 0.2

# A rating at or above this counts as a good outcome, at or below the other as
# a bad one, and the gap between them counts as neither. Three outcomes again:
# a 5/10 is not evidence for or against, and averaging it in pretends it is.
GOOD_RATING = 7
BAD_RATING = 4


class ReplayBuffer:
    """The journal of shipped prompts and their reported outcomes."""

    def __init__(self, *, path: str | None = None) -> None:
        self.path = path or str(state_path())
        self._conn: sqlite3.Connection = connect(self.path)
        self._lock = lock_for(state_path() if path is None else Path(path))

    def record(
        self,
        *,
        record_id: str,
        prompt: str,
        model: str,
        outcome: str,
        rating: int | None = None,
        note: str = "",
        artifact: str = "",
    ) -> dict:
        """Log one shipped prompt and what came back. Three outcomes.

        `artifact` is the path to what was actually produced. The house rule is
        that a result nobody opened is not a result, and a report with no path
        in it cannot be opened later — so an empty `artifact` is recorded as
        `could not measure`, not as a success.
        """
        if not record_id or not prompt:
            return {
                "outcome": FAIL,
                "checked": 1,
                "violations": 1,
                "unmeasured": 0,
                "note": "a replay entry needs both a record id and a prompt",
            }
        if rating is not None and not RATING_MIN <= rating <= RATING_MAX:
            return {
                "outcome": FAIL,
                "checked": 1,
                "violations": 1,
                "unmeasured": 0,
                "note": f"rating {rating} is outside {RATING_MIN}..{RATING_MAX}",
            }
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO replay(record_id, prompt, model, rating, outcome, note,"
                " artifact, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    record_id,
                    prompt,
                    model,
                    rating,
                    outcome,
                    note,
                    artifact,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
        if not artifact:
            return {
                "outcome": UNMEASURED,
                "checked": 1,
                "violations": 0,
                "unmeasured": 1,
                "note": (
                    "recorded, but with no artifact path: nobody can open what this "
                    "produced, so the rating is a claim rather than an observation"
                ),
            }
        return {
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "note": f"recorded {record_id} -> {artifact}",
        }

    def tally(self) -> dict[str, tuple[int, int, int]]:
        """Per record id: (good reports, bad reports, reports with no rating)."""
        out: dict[str, tuple[int, int, int]] = {}
        with self._lock:
            rows = self._conn.execute("SELECT record_id, rating FROM replay ORDER BY id").fetchall()
        for row in rows:
            good, bad, unrated = out.get(row["record_id"], (0, 0, 0))
            rating = row["rating"]
            if rating is None:
                unrated += 1
            elif rating >= GOOD_RATING:
                good += 1
            elif rating <= BAD_RATING:
                bad += 1
            else:
                # Deliberately counted nowhere: a middling rating is not
                # evidence, and folding it into either bucket would invent some.
                pass
            out[row["record_id"]] = (good, bad, unrated)
        return out

    def boost(self) -> Callable[[CorpusRecord], float]:
        """A ranking multiplier per corpus record, built from reported outcomes.

        Returns a callable suitable for `retrieval.search(boost=...)`. It reads
        the tally once, so a long retrieval run does not re-query per candidate.

        >>> buf = ReplayBuffer(path=":memory:")
        >>> f = buf.boost()
        >>> f(CorpusRecord(record_id="x", prompt="p"))
        1.0
        """
        counts = self.tally()

        def multiplier(record: CorpusRecord) -> float:
            good, bad, _unrated = counts.get(record.record_id, (0, 0, 0))
            if good == 0 and bad == 0:
                return 1.0
            value = 1.0 + FEEDBACK_STEP * (good - bad)
            return round(max(FEEDBACK_FLOOR, min(FEEDBACK_CEILING, value)), 4)

        return multiplier

    def stats(self) -> dict:
        """Counts for the monitor: entries, rated, good, bad, artifacts present."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS entries,"
                " SUM(CASE WHEN rating IS NOT NULL THEN 1 ELSE 0 END) AS rated,"
                f" SUM(CASE WHEN rating >= {GOOD_RATING} THEN 1 ELSE 0 END) AS good,"
                f" SUM(CASE WHEN rating <= {BAD_RATING} AND rating IS NOT NULL"
                " THEN 1 ELSE 0 END) AS bad,"
                " SUM(CASE WHEN artifact <> '' THEN 1 ELSE 0 END) AS with_artifact"
                " FROM replay"
            ).fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}

    def close(self) -> None:
        """Close the connection. Idempotent."""
        with self._lock:
            self._conn.close()
