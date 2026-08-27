"""What is known about each model, who said it, when, and where they disagree.

`registry.py` holds ONE answer per attribute, because the assembler needs one
number to build a prompt against. This module holds ALL the answers anybody has
given, and that difference is the point.

The failure this exists to prevent is specific and was measured. Asked how long
a single Kling 3.0 generation can be, the available sources say 15 seconds, and
10 seconds, and "3 minutes" (which turns out to mean several renders joined by
an Extend feature, not one generation). A third-party summary of those same
sources confidently reported "up to 5 minutes in a single generation", which
matches none of them. That is what happens when a pile of secondary sources is
flattened into one confident sentence: the flattening invents an answer nobody
gave.

So contradiction is a FIRST-CLASS OUTCOME here. `claims()` returns `fail` when
sources disagree, and it returns every side with its URL, its tier and its
date. It never votes, never averages, and never picks the newest. A caller that
wants one number goes to `registry.py` and gets the conservative one; a caller
that wants the truth gets told that the truth is contested.

TIERS, and why a blog can never promote a fact:

    vendor     the model vendor's own page: documentation, release, or repo
    probe      the vendor's own API, asked and refused: the running system
               rather than a document about it. Below `vendor` because one
               probe sees one account at one moment, and a limit it reports
               may belong to a billing plan rather than to the model.
    paper      arXiv or a venue, with a method somebody can check
    benchmark  an independent leaderboard or evaluation with a method
    portal     a platform that RUNS the model or hosts what people made with
               it — what its own API accepts, or the prompts and results
               themselves. A statement about a running system, so above a
               blog; below the vendor, because a platform exposes its own
               configuration and its ceiling may be its plan.
    blog       everything else, including the well-written aggregators

The first, sixth and fifth rungs are decided by WHOSE PAGE IT IS, from the
table in `source_hosts.py`, not by how the page reads. `probe`, `paper` and
`benchmark` are decided by HOW THE FACT WAS OBTAINED, which no URL can tell
you — those are declared by whoever records the fact.

A fact carried only by `blog` sources stays weak however many blogs repeat it,
because ten blogs quoting each other is one source. This is not snobbery about
writing quality: it is that a blog states a number without stating how it was
obtained, so a reader cannot tell a measurement from a guess.

BEING THE VENDOR'S PAGE AND HAVING BEEN READ ARE DIFFERENT QUESTIONS

Most vendor hosts are refused by this environment's egress policy, so a fact
citing `kling.ai` may be known only through somebody else's summary of it.
The tier says whose page it is; `read_directly` says whether anyone opened it.
Three states, because "nobody recorded it" is not "nobody read it":

    True   somebody opened the page or the API answered us
    False  it was not opened — the host is refused, or the note says summary
    None   not recorded

Collapsing None into False would invent evidence; collapsing it into True
would launder a summary into a reading. Neither is allowed.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

__all__ = [
    "DEFAULT_FACTS_PATH",
    "MULTI_VALUED",
    "STALE_AFTER_DAYS",
    "TIERS",
    "TIER_BLOG",
    "TIER_BENCHMARK",
    "TIER_PORTAL",
    "TIER_PAPER",
    "TIER_PROBE",
    "TIER_VENDOR",
    "UNKNOWN_TIER_RANK",
    "Fact",
    "FactStore",
    "claims",
    "load_facts",
]

TIER_VENDOR = "vendor"
TIER_PROBE = "probe"
TIER_BENCHMARK = "benchmark"
TIER_PORTAL = "portal"
TIER_BLOG = "blog"
TIER_PAPER = "paper"

#: Strongest first. Order is the only ranking; there are deliberately no
#: numeric weights, because a weight invites averaging and averaging a vendor
#: doc with three blogs produces a number nobody published.
#:
#: `probe` is a fact obtained by asking the vendor's own API and reading its
#: refusal — the running system rather than a document about it. It sits below
#: `vendor` and above everything else, and the reason it is not first is a real
#: confound: a probe observes ONE account, ONE region and ONE moment, so a
#: limit it reports may belong to a billing plan rather than to the model. A
#: vendor's general statement outranks a single observation of a special case;
#: everything written from the outside does not.
#:
#: `portal` was inserted directly above `blog` on 2026-08-27, on the owner's
#: ladder: vendor page, then specialised platforms, then everything else. It
#: goes above `blog` because a platform documents an endpoint that answers, and
#: below `benchmark` because it documents its OWN endpoint and has no published
#: method. Nothing else moved.
TIERS: tuple[str, ...] = (
    TIER_VENDOR,
    TIER_PROBE,
    TIER_PAPER,
    TIER_BENCHMARK,
    TIER_PORTAL,
    TIER_BLOG,
)

#: Ranked below every named tier. A tier nobody declared cannot corroborate
#: anything, and until 2026-08-27 it silently did: an unrecognised tier sorted
#: to position 99 — worse than `blog` — but the "is this only blogs" check
#: compared against `blog` by NAME, so a typo'd tier sailed past it and the
#: claim was reported as `pass`. Ranking and judging must agree, so the check
#: now asks whether the best tier is blog OR unknown.
UNKNOWN_TIER_RANK = 99

#: Past this, a fact is reported as stale rather than current. CHOSEN: the
#: video field re-versioned roughly every two months through 2026.
STALE_AFTER_DAYS = 90

#: Attributes where several different values are a LIST, not a disagreement.
#: A model has many failure modes; it has one maximum duration. Treating the
#: two the same made every failure-mode entry read as a contradiction between
#: sources (OBSERVED 2026-08-26: 7 "contested" attributes, 4 of them merely
#: lists). The distinction is about the attribute, not about the sources.
MULTI_VALUED: frozenset[str] = frozenset(
    {
        "failure_mode",
        "metric_blind_spot",
        "best_for",
        "artifact_taxonomy",
        "override_parameter",
        "long_video_method",
        # Three findings that read as a contradiction and are not one. Longer
        # prompts helped when the USER wrote the extra words (+24% length, half
        # the measured gain); machine rewriting HURT (-58% of the gain); and
        # length alone barely correlates with quality (r about -0.07). The
        # reconciliation is in who adds the words, not in which source is
        # wrong, so these belong in a list rather than in a dispute.
        "expander_evidence",
        "retrieval_grounding",
        "expands_internally",
    }
)

DEFAULT_FACTS_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "model_facts.jsonl"


@dataclass(frozen=True)
class Fact:
    """One claim about one model, with who made it and when."""

    model: str
    attribute: str
    value: str
    source_url: str
    tier: str
    stated_on: str = ""
    note: str = ""
    fix: str = ""

    #: Did anybody open this page? See the module docstring: three states, and
    #: None means nobody recorded it rather than nobody read it.
    read_directly: bool | None = None

    @property
    def age_days(self) -> int | None:
        """Days since the source stated it; None when the source gave no date."""
        if not self.stated_on:
            return None
        try:
            return (date.today() - date.fromisoformat(self.stated_on)).days
        except ValueError:
            return None


def load_facts(path: Path = DEFAULT_FACTS_PATH) -> list[Fact]:
    """Read the fact file. A missing file returns nothing, and says nothing."""
    if not path.is_file():
        return []
    facts: list[Fact] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not row.get("model") or not row.get("attribute"):
            continue
        facts.append(
            Fact(
                model=str(row["model"]),
                attribute=str(row["attribute"]),
                value=str(row.get("value", "")),
                source_url=str(row.get("source_url", "")),
                tier=str(row.get("tier", TIER_BLOG)),
                stated_on=str(row.get("stated_on", "")),
                note=str(row.get("note", "")),
                fix=str(row.get("fix", "")),
                # Absent stays None. A row written before the field existed
                # recorded nothing about reading, and that is what it says.
                read_directly=(
                    None if row.get("read_directly") is None else bool(row["read_directly"])
                ),
            )
        )
    return facts


class FactStore:
    """Every claim anybody has made, indexed by (model, attribute)."""

    def __init__(self, facts: Sequence[Fact] | None = None) -> None:
        self.facts: list[Fact] = list(facts) if facts is not None else load_facts()
        self._index: dict[tuple[str, str], list[Fact]] = defaultdict(list)
        for fact in self.facts:
            self._index[(fact.model.lower(), fact.attribute.lower())].append(fact)

    def attributes(self, model: str) -> list[str]:
        """Every attribute anybody has stated for this model."""
        low = model.lower()
        return sorted({a for (m, a) in self._index if m == low})

    def models(self) -> list[str]:
        """Every model anybody has stated anything about."""
        return sorted({m for (m, _) in self._index})

    def claims(self, model: str, attribute: str) -> dict:
        """Everything said about one attribute. Three outcomes, and no voting.

        * `pass` — every source that spoke agrees, and at least one is above
          blog tier.
        * `fail` — the sources contradict each other. Both sides are returned.
          This is not an error in this module; it is the state of the world,
          and hiding it is how an agent becomes confidently wrong.
        * `could not measure` — nobody has said anything, or everything said
          comes from blog tier alone, which cannot establish a fact.
        """
        found = self._index.get((model.lower(), attribute.lower()), [])
        if not found:
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": f"nothing recorded about {model}.{attribute}",
                "claims": [],
                "values": [],
            }

        by_value: dict[str, list[Fact]] = defaultdict(list)
        for fact in found:
            by_value[fact.value].append(fact)
        rows = [
            {
                "value": value,
                "sources": [
                    {
                        "url": f.source_url,
                        "tier": f.tier,
                        "stated_on": f.stated_on,
                        "age_days": f.age_days,
                        "note": f.note,
                        # None means nobody recorded it, and prints as such.
                        "read_directly": f.read_directly,
                    }
                    for f in sorted(
                        facts,
                        key=lambda f: TIERS.index(f.tier) if f.tier in TIERS else UNKNOWN_TIER_RANK,
                    )
                ],
                "best_tier": min(
                    (f.tier for f in facts),
                    key=lambda t: TIERS.index(t) if t in TIERS else UNKNOWN_TIER_RANK,
                ),
            }
            for value, facts in sorted(by_value.items())
        ]

        stale = [f for f in found if (f.age_days or 0) > STALE_AFTER_DAYS]
        multi = attribute.lower() in MULTI_VALUED
        if len(by_value) > 1 and not multi:
            summary = "; ".join(f"{r['value']!r} ({r['best_tier']})" for r in rows)
            return {
                "outcome": FAIL,
                "checked": len(found),
                "violations": len(by_value),
                "unmeasured": 0,
                "note": (
                    f"sources disagree on {model}.{attribute}: {summary}. "
                    "Reported as contested rather than resolved: picking one would "
                    "invent a confidence nobody published."
                ),
                "claims": rows,
                "values": sorted(by_value),
            }

        best = min(
            (r["best_tier"] for r in rows),
            key=lambda t: TIERS.index(t) if t in TIERS else UNKNOWN_TIER_RANK,
        )
        if best == TIER_BLOG or best not in TIERS:
            return {
                "outcome": UNMEASURED,
                "checked": len(found),
                "violations": 0,
                "unmeasured": len(found),
                "note": (
                    f"{model}.{attribute}: {len(rows)} value(s) recorded, but every "
                    f"source is blog tier ({len(found)} of them). Repetition is not "
                    "corroboration: blogs quoting each other are one source."
                ),
                "claims": rows,
                "values": sorted(by_value),
            }
        shape = f"{len(rows)} value(s)" if multi else f"{rows[0]['value']!r}"
        note = f"{model}.{attribute}: {shape}, from {len(found)} source(s), best tier {best}"
        if stale:
            note += f"; {len(stale)} source(s) older than {STALE_AFTER_DAYS} days"
        # Counted and printed, never folded into the verdict: the ladder says
        # whose page it is and the owner set that ladder. But a `vendor` line
        # with nobody behind it reads as "the vendor says so", and 10 of the
        # 47 facts here cite a vendor page this environment cannot open. The
        # count goes out so a caller can gate on it; the policy is not
        # invented here.
        unread = [f for f in found if f.read_directly is False]
        unrecorded = [f for f in found if f.read_directly is None]
        if unread:
            note += (
                f"; {len(unread)} of {len(found)} source(s) were NOT read — known "
                "through somebody else's summary, not the page itself"
            )
        if unrecorded:
            note += f"; {len(unrecorded)} source(s) have no reading recorded either way"
        return {
            "outcome": PASS,
            "checked": len(found),
            "violations": 0,
            "unmeasured": len(stale),
            "note": note,
            "sources_not_read": len(unread),
            "sources_reading_unrecorded": len(unrecorded),
            "claims": rows,
            "values": sorted(by_value),
        }

    def failure_modes(self, model: str) -> list[Fact]:
        """Known ways this model breaks, each with its fix and its source."""
        low = model.lower()
        return [
            f
            for (m, a), facts in self._index.items()
            if m == low and a == "failure_mode"
            for f in facts
        ]

    def contested(self) -> list[tuple[str, str]]:
        """Every (model, attribute) the sources do not agree on."""
        out: list[tuple[str, str]] = []
        for model, attribute in sorted(self._index):
            if self.claims(model, attribute)["outcome"] == FAIL:
                out.append((model, attribute))
        return out

    def audit(self) -> dict:
        """How trustworthy the whole fact base is. Three outcomes.

        A fact base built entirely from blogs reports `could not measure`,
        however large it is. Volume is not evidence.
        """
        if not self.facts:
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": "the fact base is empty: the agent knows nothing it can cite",
            }
        tiers: dict[str, int] = defaultdict(int)
        for fact in self.facts:
            tiers[fact.tier] += 1
        contested = self.contested()
        above_blog = sum(n for t, n in tiers.items() if t != TIER_BLOG)
        note = (
            f"{len(self.facts)} facts over {len(self.models())} models; "
            f"by tier {dict(sorted(tiers.items()))}; {len(contested)} contested"
        )
        if above_blog == 0:
            return {
                "outcome": UNMEASURED,
                "checked": len(self.facts),
                "violations": len(contested),
                "unmeasured": len(self.facts),
                "note": note + ". Every fact is blog tier: nothing here is established.",
            }
        return {
            "outcome": FAIL if contested else PASS,
            "checked": len(self.facts),
            "violations": len(contested),
            "unmeasured": tiers[TIER_BLOG],
            "note": note,
            "contested": [f"{m}.{a}" for m, a in contested],
        }


def claims(model: str, attribute: str, *, store: FactStore | None = None) -> dict:
    """Convenience wrapper over a process-wide store."""
    return (store or _default_store()).claims(model, attribute)


_STORE: FactStore | None = None


def _default_store() -> FactStore:
    global _STORE
    if _STORE is None:
        _STORE = FactStore()
    return _STORE
