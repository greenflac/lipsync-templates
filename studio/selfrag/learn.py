"""Learning from what the agent actually produced — and being honest about which
kind of learning is available at which sample size.

There are four things people mean by "the agent learns", and they cost four
different amounts. This module implements the first two and prepares the third.

    1. FEEDBACK WEIGHTING  — ratings move which precedents get retrieved.
       Already live in `replay.ReplayBuffer.boost`. Works from the first rating.

    2. MEASURED EFFECTS    — which choices correlate with a better result, as
       plain numbers a person can read and argue with. `effects()` below.
       Honest from a few dozen rated runs; noise below that, and it says so.

    3. SUPERVISED TUNING   — fine-tune a generator on (asked -> produced ->
       scored) triples. `export_pairs()` writes exactly that file. Needs a GPU,
       needs hundreds of labelled rows, and needs the licence question below
       answered first. Not implemented here, because the data to do it with
       does not exist yet.

    4. SELF-RAG PROPER     — reflection tokens in the generator's vocabulary,
       trained against a critic. Furthest away; see docs/SELFRAG_RESEARCH.md.

WHY NOT A LEARNED MODEL OVER THE FEEDBACK. At a few hundred rows a learned
re-ranker fits the noise, and worse, it fits it invisibly: nobody can look at
its weights and say "that one is wrong". `effects()` reports counts and
differences, so a person can see that a claim rests on nine runs and discount
it. A number a human can reject is worth more than a model a human cannot read.

THE LICENCE QUESTION, before anyone trains on the corpus. Training a model on
`gallery_prompts.jsonl` means training on a third party's commercial catalogue.
This repository's own LICENCE names "training data for a machine learning
model" as a prohibited use of ITS material; the same consideration applies to
material it does not own. Two different trainings are worth separating:

    - on the corpus TEXT (4593 unlabelled prompts) a model learns FORM — the
      vocabulary and shape of prompts in this trade. Licence question live.
    - on RATED runs (our own outputs, our own scores) a model learns QUALITY.
      That material is ours, and there are currently zero rows of it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.corpus import RATING_MAX, RATING_MIN

__all__ = [
    "MIN_PER_ARM",
    "TRUSTWORTHY_ROWS",
    "effects",
    "export_pairs",
    "features",
    "preference_pairs",
]

# Rated runs needed on BOTH sides of a comparison before it is reported at all.
# CHOSEN. Below this an effect is a coin landing the same way twice.
MIN_PER_ARM = 8

# Rated rows below which the whole report is labelled untrustworthy, however
# many arms clear MIN_PER_ARM. CHOSEN, and deliberately far above it: a table
# of individually-defensible comparisons over 30 runs is still a table nobody
# should retune a system from.
TRUSTWORTHY_ROWS = 100


def features(row: Mapping[str, Any]) -> dict[str, str]:
    """The choices a run made, as flat categorical features.

    Deliberately coarse and readable. Every feature here is something a person
    could decide to do differently tomorrow — there is no point measuring the
    effect of something nobody can change.
    """
    fields = row.get("fields") or {}
    style = row.get("style") or {}
    findings = row.get("findings") or []
    precedents = row.get("precedents") or []
    words = len(str(row.get("prompt") or "").split())
    out = {
        "model": str(row.get("model") or "?"),
        "mode": str(row.get("mode") or "?"),
        "has_camera": str(bool(fields.get("camera"))),
        "has_audio": str(bool(fields.get("audio"))),
        "has_motion": str(bool(fields.get("motion"))),
        "has_subject": str(bool(fields.get("subject"))),
        "has_setting": str(bool(style.get("setting"))),
        "has_negative": str(bool(row.get("negative"))),
        "palette_size": str(len(style.get("palette") or [])),
        "precedents_used": "0" if not precedents else ("1-2" if len(precedents) <= 2 else "3+"),
        "prompt_length": "short" if words < 25 else ("medium" if words < 60 else "long"),
        "light": str(style.get("light") or "?"),
        "texture": str(style.get("texture") or "?"),
        "mood": str(style.get("mood") or "?"),
    }
    for rule in sorted({str(r) for r in findings}):
        out[f"rule:{rule}"] = "True"
    return out


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def effects(rows: Sequence[Mapping[str, Any]], *, min_per_arm: int = MIN_PER_ARM) -> dict:
    """Which choices went with a better rating. Three outcomes, and counts always.

    Every reported effect carries the sample size behind each arm, because a
    difference of 1.2 rating points over nine runs and over nine hundred are
    different claims and must not print the same.

    :returns: the judging dict plus `effects` (sorted by absolute difference)
        and `skipped` (comparisons that had too little data to make).
    """
    rated = [r for r in rows if r.get("rating") is not None]
    if not rated:
        return {
            "outcome": UNMEASURED,
            "checked": len(rows),
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"{len(rows)} stored runs, none rated. Nothing can be learned from "
                "output nobody has looked at: the ratings are the whole signal."
            ),
            "effects": [],
            "skipped": [],
            "rated": 0,
        }

    buckets: dict[tuple[str, str], list[float]] = {}
    for row in rated:
        rating = float(row["rating"])
        for name, value in features(row).items():
            buckets.setdefault((name, value), []).append(rating)

    overall = _mean([float(r["rating"]) for r in rated])
    found: list[dict] = []
    skipped: list[str] = []
    for (name, value), ratings in sorted(buckets.items()):
        others = [float(r["rating"]) for r in rated if features(r).get(name) != value]
        if len(ratings) < min_per_arm or len(others) < min_per_arm:
            skipped.append(f"{name}={value} ({len(ratings)} vs {len(others)})")
            continue
        found.append(
            {
                "feature": name,
                "value": value,
                "n_with": len(ratings),
                "n_without": len(others),
                "mean_with": _mean(ratings),
                "mean_without": _mean(others),
                "difference": round(_mean(ratings) - _mean(others), 3),
            }
        )
    found.sort(key=lambda e: -abs(e["difference"]))

    trustworthy = len(rated) >= TRUSTWORTHY_ROWS
    if not found:
        return {
            "outcome": UNMEASURED,
            "checked": len(rows),
            "violations": 0,
            "unmeasured": len(skipped),
            "note": (
                f"{len(rated)} rated runs, and no comparison had {min_per_arm} on both "
                f"sides. {len(skipped)} were skipped rather than reported thin."
            ),
            "effects": [],
            "skipped": skipped[:20],
            "rated": len(rated),
        }
    return {
        "outcome": PASS if trustworthy else UNMEASURED,
        "checked": len(rows),
        "violations": 0,
        "unmeasured": 0 if trustworthy else 1,
        "note": (
            f"{len(found)} effects over {len(rated)} rated runs, mean rating {overall}"
            + (
                ""
                if trustworthy
                else f". FEWER THAN {TRUSTWORTHY_ROWS} RATED RUNS: read these as "
                "directions to investigate, not as findings to retune from."
            )
        ),
        "effects": found,
        "skipped": skipped[:20],
        "rated": len(rated),
        "mean_rating": overall,
    }


def export_pairs(rows: Sequence[Mapping[str, Any]], path: str | Path) -> dict:
    """Write (asked -> produced -> scored) triples as JSONL for supervised tuning.

    This is the file a fine-tune consumes. It is written even when it is far too
    small to tune on, because the count in the note is the honest answer to
    "can we train yet" and an absent file is not.
    """
    rated = [r for r in rows if r.get("rating") is not None]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in rated:
            handle.write(
                json.dumps(
                    {
                        "run_id": row.get("run_id"),
                        "model": row.get("model"),
                        "mode": row.get("mode"),
                        "request": row.get("request"),
                        "fields": row.get("fields"),
                        "style": row.get("style"),
                        "prompt": row.get("prompt"),
                        "negative": row.get("negative"),
                        "rating": row.get("rating"),
                        "artifact": row.get("artifact"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    if not rated:
        return {
            "outcome": UNMEASURED,
            "checked": len(rows),
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"wrote an empty file to {target}: {len(rows)} runs are stored and none "
                "is rated. Supervised tuning needs labels, and nobody has looked at a "
                "single output yet."
            ),
            "written": 0,
            "path": str(target),
        }
    return {
        "outcome": PASS,
        "checked": len(rows),
        "violations": 0,
        "unmeasured": 0,
        "note": f"wrote {len(rated)} rated pairs to {target}",
        "written": len(rated),
        "path": str(target),
    }


def preference_pairs(rows: Sequence[Mapping[str, Any]], *, margin: int = 3) -> dict:
    """Build (better, worse) pairs over the same request, for preference tuning.

    Only pairs where the same request produced two prompts whose ratings differ
    by at least `margin`. A pair from two ratings one point apart teaches a
    preference nobody actually holds.
    """
    if not RATING_MIN <= margin <= RATING_MAX:
        return {
            "outcome": FAIL,
            "checked": 0,
            "violations": 1,
            "unmeasured": 0,
            "note": f"margin {margin} is outside the {RATING_MIN}..{RATING_MAX} scale",
            "pairs": [],
        }
    by_request: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if row.get("rating") is None:
            continue
        by_request.setdefault(str(row.get("request") or ""), []).append(row)

    pairs: list[dict] = []
    for request, group in sorted(by_request.items()):
        ranked = sorted(group, key=lambda r: int(r["rating"]))
        for worse in ranked:
            for better in ranked:
                if int(better["rating"]) - int(worse["rating"]) >= margin:
                    pairs.append(
                        {
                            "request": request,
                            "chosen": better.get("prompt"),
                            "rejected": worse.get("prompt"),
                            "chosen_rating": better.get("rating"),
                            "rejected_rating": worse.get("rating"),
                        }
                    )
    if not pairs:
        return {
            "outcome": UNMEASURED,
            "checked": len(rows),
            "violations": 0,
            "unmeasured": 1,
            "note": (
                "no request has two rated prompts at least "
                f"{margin} points apart. Preference tuning needs the same question "
                "answered twice and judged differently; asking each question once "
                "produces no preferences at all."
            ),
            "pairs": [],
        }
    return {
        "outcome": PASS,
        "checked": len(rows),
        "violations": 0,
        "unmeasured": 0,
        "note": f"{len(pairs)} preference pairs at margin {margin}",
        "pairs": pairs,
    }


def render(report: Mapping[str, Any]) -> str:
    """The effects report as a person reads it."""
    lines = [f"outcome: {report['outcome']} — {report['note']}", ""]
    if report.get("effects"):
        lines.append(
            f"{'feature':<26} {'value':<14} {'n':>6} {'with':>7} {'without':>8} {'diff':>7}"
        )
        for e in report["effects"]:
            lines.append(
                f"{e['feature']:<26} {e['value']:<14} "
                f"{e['n_with']:>3}/{e['n_without']:<3} "
                f"{e['mean_with']:>7} {e['mean_without']:>8} {e['difference']:>+7}"
            )
    if report.get("skipped"):
        lines += ["", f"too little data to compare ({len(report['skipped'])} shown):"]
        lines += [f"  {s}" for s in report["skipped"]]
    return "\n".join(lines) + "\n"


def _iter_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return list(rows)
