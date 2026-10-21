"""How close a candidate prompt is to the corpus of prompts that were worth keeping.

The corpus has two possible jobs and this project had only been using the
wrong one. As a supply of words it is a crutch — `evidence.py` splices clauses
because there is no generator to write them. As a STANDARD it is the thing
nothing else in this system provides: an answer to "is this any good", asked
against prompts somebody actually shipped rather than against a rule table.

`reflect.py` grades COMPLIANCE — is the word count in band, is a banned topic
named, does a dead phrase promise something the model ignores. A prompt can
pass every one of those rules and still read nothing like the prompts that
work, and on 2026-08-26 one did: it passed ten rules, went to flux, and lost a
blind comparison to the user's own untouched sentence.

WHAT IS MEASURED, AND WHY THESE

Only properties a person could act on, and only ones a corpus can settle:

    clauses          how many comma-separated descriptors it carries
    words            total length
    craft_density    share of content words naming HOW the picture is made
    craft_clauses    share of clauses carrying any craft word
    specificity      share of clauses with a number, a proper noun or a unit
                     ("50mm", "Leica", "3:4") — the difference between "nice
                     light" and something a camera could be set to

Each is scored as a PERCENTILE against the corpus, not against a threshold
somebody chose. The corpus decides what normal looks like; this module only
reports where a candidate falls in it.

WHAT THIS IS NOT, AND THE LITERATURE IS BLUNT ABOUT IT

Every reference-free score has a known spurious correlate — length, fluency or
typicality — and "in-distribution" is NOT "good". MAUVE's low scores have been
attributed to length discrepancy rather than quality; generative-perplexity
scoring rewards cliché by construction. The survey position is that these
belong as GUARD-RAILS — flagging an output far outside the corpus — and not as
a ranking of near-in-distribution candidates.
(https://arxiv.org/abs/2501.12011, https://arxiv.org/pdf/2102.01454,
https://arxiv.org/html/2606.08417 — read via search summaries, not opened:
this environment's proxy blocks arxiv.)

So: `score()` is an out-of-distribution detector. Read `outcome` and
`weakest`; treat `score` as a rough position, never as a quality ordering.

One check worth keeping, because it cuts the other way. On the three prompts
from the 2026-08-26 A/B, the ranking agreed with the owner's blind verdict —
and the agreement came from `craft_clauses` (spread 0.425), while `words` and
`clauses` ran in the OPPOSITE direction: the prompt that LOST was the longest
of the three. So in that one case the length artefact was not what produced the
agreement. Three prompts and one judge is not a validation of anything; it is
one observation that happens to survive the obvious objection.

THE CONTROLS ARE NOT OPTIONAL

`calibrate` refuses to return a usable scorer unless a held-out corpus prompt
scores well AND a piece of non-prompt prose scores badly. A scorer that likes
everything is not measuring anything, and this project has already been bitten
by a metric that could not tell two very different inputs apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.evidence import CRAFT_TOKENS, _FUNCTION_WORDS

__all__ = [
    "FEATURES",
    "GOOD_PERCENTILE",
    "MIN_CORPUS",
    "QualityModel",
    "calibrate",
    "features_of",
    "score",
]

#: Fewer corpus prompts than this and a percentile means nothing.
MIN_CORPUS = 50

#: A candidate at or above this percentile on a feature is "normal for this
#: corpus". CHOSEN low on purpose: the corpus's own tenth percentile is still a
#: prompt somebody shipped, and the aim is to catch prompts unlike anything in
#: it, not to demand the median.
#:
#: Being BELOW it on `words` says the prompt is shorter than almost anything in
#: this corpus. It does NOT say a longer prompt would produce a better picture —
#: that is a claim about generation, and nothing here measures generation.
GOOD_PERCENTILE = 0.10

FEATURES: tuple[str, ...] = ("clauses", "words", "craft_density", "craft_clauses", "specificity")

_WORD = re.compile(r"[a-z0-9][a-z0-9'-]*")
_CLAUSE_SPLIT = re.compile(r"[,;.]|\s+--\w+")
#: A number, a unit, a model name — anything a camera could be set to.
_SPECIFIC = re.compile(r"\d|[A-Z][a-z]+[A-Z]|\b[A-Z]{2,}\b")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(str(text or "").lower())


def features_of(prompt: str) -> dict[str, float]:
    """The five measurable properties of one prompt."""
    raw_clauses = [c.strip() for c in _CLAUSE_SPLIT.split(str(prompt or "")) if c.strip()]
    tokens = _tokens(prompt)
    content = [w for w in tokens if w not in _FUNCTION_WORDS]
    craft = [w for w in content if w in CRAFT_TOKENS]
    with_craft = sum(1 for c in raw_clauses if any(w in CRAFT_TOKENS for w in _tokens(c)))
    specific = sum(1 for c in raw_clauses if _SPECIFIC.search(c))
    n = len(raw_clauses) or 1
    return {
        "clauses": float(len(raw_clauses)),
        "words": float(len(tokens)),
        "craft_density": len(craft) / len(content) if content else 0.0,
        "craft_clauses": with_craft / n,
        "specificity": specific / n,
    }


@dataclass(frozen=True)
class QualityModel:
    """The corpus's own distribution over each feature, sorted for percentiles."""

    distributions: dict[str, tuple[float, ...]]
    size: int

    def percentile(self, feature: str, value: float) -> float:
        """Share of corpus prompts this value is at least as large as."""
        values = self.distributions.get(feature) or ()
        if not values:
            return 0.0
        below = sum(1 for v in values if v <= value)
        return below / len(values)


def calibrate(prompts: Sequence[str], *, control_bad: str = "", control_good: str = "") -> dict:
    """Build the scorer from the corpus, and REFUSE to hand back one that
    cannot tell a shipped prompt from a paragraph of unrelated prose.

    :param control_bad: text that must score badly. Defaults to a paragraph of
        ordinary prose about something else entirely.
    :param control_good: a prompt that must score well. Defaults to the
        corpus's own median-length member, held out of nothing — it is a
        sanity check that the scorer likes what it was built from.
    """
    usable = [p for p in prompts if p and len(_tokens(p)) >= 3]
    if len(usable) < MIN_CORPUS:
        return {
            "outcome": UNMEASURED,
            "checked": len(usable),
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"{len(usable)} usable prompts, and a percentile needs at least "
                f"{MIN_CORPUS}. A distribution over a handful of rows is not a standard."
            ),
            "model": None,
        }

    table = [features_of(p) for p in usable]
    model = QualityModel(
        distributions={name: tuple(sorted(row[name] for row in table)) for name in FEATURES},
        size=len(usable),
    )

    bad = control_bad or (
        "The quarterly filing deadline falls on the last working day of the month. "
        "Submit the return through the portal and keep the confirmation number for "
        "your records, as the office does not accept a screenshot as proof."
    )
    good = control_good or usable[len(usable) // 2]
    bad_score = score(bad, model=model)
    good_score = score(good, model=model)
    if bad_score["outcome"] == PASS:
        return {
            "outcome": FAIL,
            "checked": len(usable),
            "violations": 1,
            "unmeasured": 0,
            "note": (
                "the negative control PASSED: this scorer accepts a paragraph of "
                "unrelated prose, so it is not measuring prompt quality"
            ),
            "model": None,
        }
    if good_score["outcome"] != PASS:
        return {
            "outcome": FAIL,
            "checked": len(usable),
            "violations": 1,
            "unmeasured": 0,
            "note": (
                "the positive control FAILED: this scorer rejects a prompt from the "
                "very corpus it was built from, so its bar is not the corpus's"
            ),
            "model": None,
        }
    return {
        "outcome": PASS,
        "checked": len(usable),
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"calibrated on {len(usable)} prompts; negative control scored "
            f"{bad_score['score']}, positive control {good_score['score']}"
        ),
        "model": model,
        "controls": {"negative": bad_score["score"], "positive": good_score["score"]},
    }


def score(prompt: str, *, model: QualityModel) -> dict:
    """Where this prompt falls in the corpus's distribution. Three outcomes.

    :returns: the judging dict plus `score` (mean percentile), `percentiles`
        per feature, and `weakest` — the feature a writer should fix first.
    """
    if not prompt or len(_tokens(prompt)) < 3:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "nothing to score",
            "score": 0.0,
            "percentiles": {},
            "weakest": None,
        }
    values = features_of(prompt)
    percentiles = {name: round(model.percentile(name, values[name]), 3) for name in FEATURES}
    weakest = min(percentiles, key=lambda name: percentiles[name])
    mean = round(sum(percentiles.values()) / len(percentiles), 3)
    below = [name for name, p in percentiles.items() if p < GOOD_PERCENTILE]
    if below:
        return {
            "outcome": FAIL,
            "checked": len(FEATURES),
            "violations": len(below),
            "unmeasured": 0,
            "note": (
                f"below the corpus's {int(GOOD_PERCENTILE * 100)}th percentile on "
                f"{', '.join(below)}; weakest is {weakest} at {percentiles[weakest]}"
            ),
            "score": mean,
            "percentiles": percentiles,
            "weakest": weakest,
            "values": values,
        }
    return {
        "outcome": PASS,
        "checked": len(FEATURES),
        "violations": 0,
        "unmeasured": 0,
        "note": f"inside the corpus's range on every feature; mean percentile {mean}",
        "score": mean,
        "percentiles": percentiles,
        "weakest": weakest,
        "values": values,
    }


def compare(candidates: dict[str, str], *, model: QualityModel) -> dict:
    """Score several prompts side by side. Useful for an A/B before spending."""
    scored = {name: score(text, model=model) for name, text in candidates.items()}
    ranked = sorted(scored.items(), key=lambda kv: -kv[1]["score"])
    return {
        "outcome": PASS if scored else UNMEASURED,
        "checked": len(scored),
        "violations": 0,
        "unmeasured": 0,
        "note": " > ".join(f"{name} {r['score']}" for name, r in ranked),
        "ranked": [name for name, _ in ranked],
        "scores": {name: r["score"] for name, r in scored.items()},
        "detail": scored,
    }
