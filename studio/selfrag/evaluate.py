"""Score the retriever against a gold set, and refuse to score it dishonestly.

Two things make this different from counting recall.

First, negative controls are mandatory, not optional. A gold set with no query
whose right answer is "nothing here" cannot tell a retriever from a machine
that returns its five favourite records for every input. If the set has no
`abstain` rows, `evaluate` returns `could not measure` and reports no averages
at all — a number produced by an instrument with no negative control is worse
than no number, because it will be quoted.

Second, the three outcomes are counted separately all the way through. A query
the retriever could not answer because the index was empty is not a miss; it
is an unmeasured query, and averaging it in as a zero manufactures a failure
rate out of a configuration problem.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.corpus import CorpusRecord
from studio.selfrag.retrieval import CorpusIndex, search_with_fallback

__all__ = [
    "ABSTENTION_FLOOR",
    "DEFAULT_EVAL_PATH",
    "GALLERY_EVAL_PATH",
    "PRECISION_FLOOR",
    "RECALL_FLOOR",
    "evaluate",
    "load_gold",
]

DEFAULT_EVAL_PATH = Path(__file__).with_name("fixtures") / "eval_set.jsonl"
DEMO_CORPUS_PATH = Path(__file__).with_name("fixtures") / "demo_corpus.jsonl"

# Floors below which the retriever is called not good enough. CHOSEN, and they
# are the constants to mutate when checking that these tests bite: move
# RECALL_FLOOR to 0.99 and the suite must go red, move it to 0.0 and the
# mutation test that removes a channel must stop being caught.
RECALL_FLOOR = 0.75
PRECISION_FLOOR = 0.30

# Fraction of the negative controls that must come back empty. CHOSEN at 1.0:
# a retriever that answers one of three unanswerable questions is a retriever
# that will answer an unanswerable question in production.
ABSTENTION_FLOOR = 1.0


GALLERY_EVAL_PATH = Path(__file__).with_name("fixtures") / "gallery_eval_set.jsonl"


def load_gold(path: Path = DEFAULT_EVAL_PATH) -> list[dict]:
    """Read the gold set. A missing file returns an empty list, never a guess."""
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            rows.append(json.loads(line))
    return rows


def _haystack(record: CorpusRecord) -> str:
    """The text a `must_retrieve` phrase is looked for in."""
    return " ".join((record.prompt, " ".join(record.tags), record.result)).lower()


def evaluate(
    index: CorpusIndex,
    gold: Sequence[Mapping[str, Any]],
    *,
    k: int = 5,
    channels: Sequence[str] | None = None,
) -> dict:
    """Score `index` against `gold`. Three outcomes.

    :param channels: which retrieval channels to fuse. Pass a subset to run a
        mutation: dropping a channel must move recall, or that channel is
        decoration nobody is measuring.
    :returns: the judging dict plus recall@k, precision@k, abstention numbers
        and a per-query breakdown.
    """
    if len(index) == 0:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "the index is empty: nothing could be scored",
        }
    if not gold:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "the gold set is empty: nothing could be scored",
        }

    positives = [row for row in gold if row.get("expect", "hit") == "hit"]
    negatives = [row for row in gold if row.get("expect") == "abstain"]
    if not negatives:
        return {
            "outcome": UNMEASURED,
            "checked": len(gold),
            "violations": 0,
            "unmeasured": len(gold),
            "note": (
                "the gold set has no negative controls: a retriever that never says "
                "'nothing here' cannot be told from one that always answers, so no "
                "recall or precision number is reported"
            ),
        }

    kwargs: dict[str, Any] = {"k": k}
    if channels is not None:
        kwargs["channels"] = channels

    recalls: list[float] = []
    precisions: list[float] = []
    per_query: list[dict] = []
    unmeasurable = 0

    for row in positives:
        out = search_with_fallback(str(row["query"]), index=index, **kwargs)
        if out["outcome"] == UNMEASURED:
            unmeasurable += 1
            per_query.append({"id": row.get("id"), "outcome": UNMEASURED, "note": out["note"]})
            continue
        category = str(row.get("must_category") or "").lower()
        if category:
            # Ground truth is membership of a section the SOURCE filed the
            # record under, not a phrase we chose. A grouping somebody else
            # made is what keeps this from measuring our own taste: with
            # phrases we picked, we would be grading the retriever against
            # the records we already had in mind.
            marks = [1 if category in hit.record.tags else 0 for hit in out["hits"]]
            recall = 1.0 if any(marks) else 0.0
            precision = sum(marks) / len(marks) if marks else 0.0
        else:
            wanted = [str(w).lower() for w in (row.get("must_retrieve") or [])]
            texts = [_haystack(hit.record) for hit in out["hits"]]
            found = [w for w in wanted if any(w in text for text in texts)]
            recall = len(found) / len(wanted) if wanted else 0.0
            hit_count = sum(1 for text in texts if any(w in text for w in wanted))
            precision = hit_count / len(texts) if texts else 0.0
        recalls.append(recall)
        precisions.append(precision)
        per_query.append(
            {
                "id": row.get("id"),
                "outcome": PASS if recall >= 1.0 else FAIL,
                "recall": round(recall, 4),
                "precision": round(precision, 4),
                "rewrite_step": out.get("rewrite_step", 0),
                "returned": len(out["hits"]),
            }
        )

    abstained = 0
    for row in negatives:
        out = search_with_fallback(str(row["query"]), index=index, **kwargs)
        empty = not out["hits"]
        abstained += int(empty)
        per_query.append(
            {
                "id": row.get("id"),
                "outcome": PASS if empty else FAIL,
                "control": "negative",
                "returned": len(out["hits"]),
                "note": "" if empty else "answered a question the corpus cannot answer",
            }
        )

    recall_at_k = round(sum(recalls) / len(recalls), 4) if recalls else 0.0
    precision_at_k = round(sum(precisions) / len(precisions), 4) if precisions else 0.0
    abstention = round(abstained / len(negatives), 4)

    failures: list[str] = []
    if recall_at_k < RECALL_FLOOR:
        failures.append(f"recall@{k} {recall_at_k} is under the {RECALL_FLOOR} floor")
    if precision_at_k < PRECISION_FLOOR:
        failures.append(f"precision@{k} {precision_at_k} is under the {PRECISION_FLOOR} floor")
    if abstention < ABSTENTION_FLOOR:
        failures.append(
            f"the retriever answered {len(negatives) - abstained} of {len(negatives)} "
            "unanswerable control queries"
        )

    if unmeasurable and unmeasurable >= len(positives):
        outcome = UNMEASURED
        note = f"all {unmeasurable} positive queries were unmeasurable: nothing was scored"
    elif failures:
        outcome = FAIL
        note = "; ".join(failures)
    else:
        outcome = PASS
        note = (
            f"recall@{k} {recall_at_k}, precision@{k} {precision_at_k}, "
            f"abstained on {abstained}/{len(negatives)} controls"
        )

    return {
        "outcome": outcome,
        "checked": len(gold),
        "violations": len(failures),
        "unmeasured": unmeasurable,
        "note": note,
        "recall_at_k": recall_at_k,
        "precision_at_k": precision_at_k,
        "abstention_rate": abstention,
        "positives": len(positives),
        "negatives": len(negatives),
        "k": k,
        "channels": list(channels) if channels is not None else "default",
        "per_query": per_query,
    }
