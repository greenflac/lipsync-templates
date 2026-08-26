"""Hybrid lexical retrieval over the prompt corpus, plus a rewrite fallback.

Reuses, never re-declares (`studio/CONTRACTS.md`, one knowledge one place):
`RRF_K`, `query_terms`, `structure_from_text` and the synonym table all come
from `studio.knowledge`. If that module retunes its fusion constant this one
retunes with it; a copy here would be a second truth that drifts in silence.

Three differences from `studio.knowledge`, each for a reason found in review:

1. The connection is opened `check_same_thread=False` and every statement runs
   under a lock. `studio/knowledge.py` opens sqlite with the default
   `check_same_thread=True` and caches one connection in a module global; the
   first `def` FastAPI route that calls it runs in a worker thread and raises
   `ProgrammingError`. That path is not wired up yet, so the bug is latent —
   this module simply does not carry it forward.
2. The index is in memory and rebuilt from records. A prompt corpus of 10^3-10^4
   rows builds in milliseconds, so there is no persisted file to go stale
   against the .jsonl.
3. A rating prior is a first-class channel. The corpus records how well each
   prompt actually did; a retriever that ignores that is ranking prompts by how
   they read rather than by how they worked.
"""

from __future__ import annotations

import math
import re
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

# mypy resolves `studio.knowledge` to the DATA DIRECTORY of that name rather
# than to `studio/knowledge.py`; at runtime the module wins, and a regression
# test in studio/tests/test_knowledge.py holds that. The ignores below are for
# the resolver, not for the imports, which are real.
# DEBT(2026-08-26): the fix is to rename one of the two, which belongs to the
# owner of studio/knowledge.py, not to this package.
from studio.knowledge import (  # type: ignore[attr-defined]
    RRF_K,
    SYNONYMS,
    query_terms,
    structure_from_text,
)
from studio.selfrag.corpus import RATING_MAX, RATING_MIN, CorpusRecord

__all__ = [
    "CHANNELS",
    "CHANNEL_WEIGHT",
    "MIN_TERM_HITS",
    "RATING_PRIOR_FLOOR",
    "REWRITE_STEPS",
    "CorpusIndex",
    "Hit",
    "build_corpus_index",
    "rewrite_query",
    "search",
]

# Which rankings are fused. Named as data so a test can drop a channel and
# watch recall move; a hard-wired call chain cannot be mutated.
CHANNELS: tuple[str, ...] = ("bm25", "phrase", "tag", "rating")

# Per-channel weight in the fusion. CHOSEN as starting values, mirroring the
# ratios `studio.knowledge` measured on its own gold set: phrase above bm25
# because this trade's jargon is multi-word, structural signals below both.
CHANNEL_WEIGHT: dict[str, float] = {
    "bm25": 1.0,
    "phrase": 1.2,
    "tag": 0.8,
    "rating": 0.5,
}

# Distinct query terms a record must carry to be admitted on the lexical
# channel. CHOSEN. Without an admission floor the retriever can never answer
# "nothing here", and a retriever that never says no is measuring nothing.
MIN_TERM_HITS = 2

# A record only rides the rating channel if the corpus actually rated it well.
# CHOSEN at the midpoint of the documented 1..10 scale, rounded up: 6.
RATING_PRIOR_FLOOR = 6

# Longest query n-gram the phrase channel looks for. Kept equal to
# `studio.knowledge.PHRASE_MAX`'s intent rather than imported, because that
# module's value is tuned for rule text and this one indexes prompts; both
# happen to be 3 today.
PHRASE_MAX = 3

# How many rewrites the fallback will try before giving up. CHOSEN: each round
# costs a full retrieval pass, and a query that survives three widenings with
# nothing to show is a query the corpus genuinely cannot answer.
REWRITE_STEPS = 3

_WORD = re.compile(r"[a-z0-9][a-z0-9'-]*")


@dataclass(frozen=True)
class Hit:
    """One retrieved record with the evidence for why it ranked."""

    record: CorpusRecord
    score: float
    channels: tuple[str, ...]
    term_hits: int


class CorpusIndex:
    """An in-memory FTS5 index over corpus records, safe to share across threads."""

    def __init__(self, records: Sequence[CorpusRecord]) -> None:
        self.records: tuple[CorpusRecord, ...] = tuple(records)
        self.by_row: dict[int, CorpusRecord] = {i: r for i, r in enumerate(self.records)}
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.execute("CREATE VIRTUAL TABLE docs USING fts5(body, tokenize='unicode61')")
        with self._conn:
            self._conn.executemany(
                "INSERT INTO docs(rowid, body) VALUES (?, ?)",
                [(i, self._body(r)) for i, r in self.by_row.items()],
            )

    @staticmethod
    def _body(record: CorpusRecord) -> str:
        """What the lexical channel sees: the prompt, its tags and its model."""
        return " ".join((record.prompt, " ".join(record.tags), record.model)).lower()

    def match(self, phrase: str) -> list[tuple[int, float]]:
        """Run one FTS5 phrase query and return (rowid, positive score) pairs."""
        escaped = phrase.replace('"', "").strip()
        if not escaped:
            return []
        with self._lock:
            try:
                rows = self._conn.execute(
                    "SELECT rowid, bm25(docs) FROM docs WHERE docs MATCH ?",
                    (f'"{escaped}"',),
                ).fetchall()
            except sqlite3.OperationalError:
                # A query FTS5 cannot parse is not a crash and not a match.
                return []
        # FTS5 bm25() is negative and more negative is better; flip it so every
        # channel in this module agrees that bigger means better.
        return [(int(rowid), -float(score)) for rowid, score in rows]

    def close(self) -> None:
        """Release the sqlite connection. Idempotent."""
        with self._lock:
            self._conn.close()

    def __len__(self) -> int:
        return len(self.records)


def build_corpus_index(records: Sequence[CorpusRecord]) -> CorpusIndex:
    """Build the searchable index. Cheap enough to do per process, not per query."""
    return CorpusIndex(records)


def _phrases(terms: Sequence[str]) -> list[str]:
    """Every contiguous n-gram of the query, longest first."""
    out: list[str] = []
    for size in range(min(PHRASE_MAX, len(terms)), 1, -1):
        for start in range(len(terms) - size + 1):
            out.append(" ".join(terms[start : start + size]))
    return out


def _channel_bm25(index: CorpusIndex, terms: Sequence[str]) -> tuple[list[int], dict[int, int]]:
    """Rank by summed BM25 over single terms; also count distinct terms hit."""
    scores: dict[int, float] = defaultdict(float)
    hits: dict[int, int] = defaultdict(int)
    for term in terms:
        matched: set[int] = set()
        for row, score in index.match(term):
            scores[row] += score
            matched.add(row)
        for row in matched:
            hits[row] += 1
    return sorted(scores, key=lambda r: (-scores[r], r)), dict(hits)


def _channel_phrase(index: CorpusIndex, terms: Sequence[str]) -> list[int]:
    """Rank by multi-word phrase matches, longer phrases counting for more."""
    scores: dict[int, float] = defaultdict(float)
    for phrase in _phrases(terms):
        weight = float(len(phrase.split()))
        for row, score in index.match(phrase):
            scores[row] += weight * score
    return sorted(scores, key=lambda r: (-scores[r], r))


def _channel_tag(
    index: CorpusIndex, structure: Mapping[str, set[str]], wanted_tags: Sequence[str]
) -> tuple[list[int], dict[int, int]]:
    """Rank by agreement on allow-list style fields and on explicit tags."""
    overlap: dict[int, int] = {}
    wanted = {t.lower() for t in wanted_tags}
    flat: set[str] = set()
    for values in structure.values():
        flat |= values
    for row, record in index.by_row.items():
        tags = set(record.tags)
        agree = len(tags & wanted) + len(tags & flat)
        if agree:
            overlap[row] = agree
    return sorted(overlap, key=lambda r: (-overlap[r], r)), overlap


def _channel_rating(index: CorpusIndex) -> list[int]:
    """Rank by the corpus's own recorded rating; unrated records do not ride."""
    rated = {
        row: record.rating
        for row, record in index.by_row.items()
        if record.rating is not None and record.rating >= RATING_PRIOR_FLOOR
    }
    return sorted(rated, key=lambda r: (-(rated[r] or 0), r))


def rewrite_query(text: str, step: int) -> str:
    """Widen a query that found nothing, deterministically and without a model.

    Step 0 is the query as given. Each later step drops one more constraint,
    so a caller can walk outwards and know exactly how far it has walked.

    * step 1 — map every word onto its allow-list synonym: the corpus speaks
      the studio's vocabulary, the user does not have to.
    * step 2 — keep only the longest three terms: rare words carry the signal,
      and a long query fails on its commonest word first.
    * step 3 — keep only the single longest term. This is the last honest
      widening; past it the query no longer means what the user typed.

    >>> rewrite_query("a navy jumper in harsh light", 1)
    'indigo jumper hard light'
    >>> rewrite_query("cinematic rooftop portrait at dusk", 3)
    'cinematic'
    """
    terms = query_terms(text)
    if step <= 0 or not terms:
        return text
    if step == 1:
        return " ".join(SYNONYMS.get(t, ("", t))[1] for t in terms)
    keep = 3 if step == 2 else 1
    ranked = sorted(terms, key=lambda t: (-len(t), terms.index(t)))[:keep]
    return " ".join(t for t in terms if t in set(ranked))


def search(
    text: str,
    *,
    index: CorpusIndex,
    k: int = 5,
    tags: Sequence[str] = (),
    model: str = "",
    boost: Callable[[CorpusRecord], float] | None = None,
    channels: Sequence[str] = CHANNELS,
) -> dict:
    """Retrieve up to `k` corpus records for a request. Three outcomes.

    :param text: the user's free text, or a rewritten widening of it.
    :param index: the corpus index to search.
    :param k: how many records to return.
    :param tags: explicit tags the caller already knows it wants.
    :param model: when set, records for other target models are ranked but
        pushed below same-model records — a Kling prompt is weak evidence for
        a Flux request, not no evidence.
    :param boost: optional per-record multiplier, e.g. the replay buffer's.
    :param channels: which channels to fuse; mutate this in tests.
    :returns: the studio judging dict plus `hits` and `terms`.
    """
    if len(index) == 0:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "the corpus index holds no records: nothing was searched",
            "hits": [],
            "terms": [],
            "channels": [],
        }

    terms = query_terms(text)
    structure = structure_from_text(text)
    rankings: dict[str, list[int]] = {}
    admitted: set[int] = set()
    off = 0

    if "bm25" in channels:
        ranking, hits = _channel_bm25(index, terms)
        rankings["bm25"] = ranking
        floor = min(MIN_TERM_HITS, max(1, len(terms)))
        admitted |= {r for r in ranking if hits.get(r, 0) >= floor}
    else:
        off += 1
        hits = {}

    if "phrase" in channels:
        ranking = _channel_phrase(index, terms)
        if ranking:
            rankings["phrase"] = ranking
            admitted |= set(ranking)
    else:
        off += 1

    if "tag" in channels:
        ranking, overlap = _channel_tag(index, structure, tags)
        if ranking:
            rankings["tag"] = ranking
            admitted |= set(ranking)
    else:
        off += 1

    if "rating" in channels:
        ranking = _channel_rating(index)
        if ranking:
            rankings["rating"] = ranking
            # Deliberately NOT admitting on this channel: a well-rated record
            # that matches nothing in the query is a popular answer to a
            # different question. The rating orders candidates, it never
            # nominates them.
    else:
        off += 1

    fused: dict[int, float] = defaultdict(float)
    for channel, ranking in rankings.items():
        weight = CHANNEL_WEIGHT.get(channel, 1.0)
        for position, row in enumerate(ranking, start=1):
            fused[row] += weight / (RRF_K + position)

    for row in list(fused):
        record = index.by_row[row]
        if model and record.model and record.model != model.lower():
            # CHOSEN: a cross-model example is worth about a third of an
            # in-model one. Not measured — mutate it and watch the ordering.
            fused[row] *= 0.33
        if boost is not None:
            fused[row] *= max(0.0, boost(record))

    ordered = sorted((r for r in fused if r in admitted), key=lambda r: (-fused[r], r))
    rejected = len(fused) - len(ordered)

    picked = [
        Hit(
            record=index.by_row[row],
            score=round(fused[row], 8),
            channels=tuple(c for c, ranking in rankings.items() if row in set(ranking)),
            term_hits=hits.get(row, 0),
        )
        for row in ordered[:k]
    ]

    outcome = PASS if picked else FAIL
    note = (
        f"{len(picked)} records above the floor"
        if picked
        else "no record in the corpus clears the admission floor"
    )
    return {
        "outcome": outcome,
        "checked": len(index),
        "violations": rejected,
        "unmeasured": off,
        "note": note,
        "hits": picked,
        "terms": terms,
        "channels": sorted(rankings),
    }


def search_with_fallback(
    text: str,
    *,
    index: CorpusIndex,
    k: int = 5,
    steps: int = REWRITE_STEPS,
    **kwargs: object,
) -> dict:
    """Search, and on an empty answer widen the query up to `steps` times.

    The point of the ladder is that the caller learns HOW FAR it had to walk.
    A hit found at step 3 is a hit for a query that no longer says what the
    user said, and the reflection stage downgrades it accordingly. Collapsing
    that into a plain "found something" is how a retriever launders a miss
    into a confident wrong answer.

    :returns: the `search` dict plus `rewrite_step` and `query_used`.
    """
    last: dict = {}
    for step in range(0, max(0, steps) + 1):
        query = rewrite_query(text, step)
        out = dict(search(query, index=index, k=k, **kwargs))  # type: ignore[arg-type]
        out["rewrite_step"] = step
        out["query_used"] = query
        last = out
        if out["outcome"] == PASS or out["outcome"] == UNMEASURED:
            return out
    return last


def confidence(hits: Sequence[Hit], *, rewrite_step: int = 0) -> float:
    """A 0..1 self-report on how well the corpus answered, for the reflector.

    Built from three things the retriever actually knows: how many distinct
    query terms the top hit carried, how many channels agreed on it, and how
    far the query had to be widened to find it. It is a heuristic and is
    labelled one — it is not a calibrated probability, and no threshold in
    this package treats it as one.
    """
    if not hits:
        return 0.0
    top = hits[0]
    term_part = min(1.0, top.term_hits / 3.0)
    channel_part = min(1.0, len(top.channels) / 3.0)
    # Each widening halves the claim the answer has on the original question.
    decay = 0.5 ** max(0, rewrite_step)
    return round((0.5 * term_part + 0.5 * channel_part) * decay, 4)


def rating_prior(record: CorpusRecord) -> float:
    """Map a 1..10 corpus rating onto a multiplier around 1.0; None is neutral."""
    if record.rating is None:
        return 1.0
    span = RATING_MAX - RATING_MIN
    # Linear from 0.5 at the worst rating to 1.5 at the best. CHOSEN.
    return 0.5 + (record.rating - RATING_MIN) / span


def _unused_math_guard() -> float:  # pragma: no cover - keeps the import honest
    return math.inf
