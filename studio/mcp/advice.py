"""Answer "can this model do that", and let the web refresh the answer.

WHAT THIS ADDS TO WHAT ALREADY EXISTED

`registry.py` holds one conservative answer per attribute, because a prompt
assembler needs one number. `facts.py` holds every answer anybody gave, with
its tier and its date, and reports `fail` when they disagree instead of
voting. Neither is reachable from a conversation, and neither can be updated
without a commit. This module joins them into one answer and opens the one
door that lets the base grow: `record`.

THE REFRESH PATH, AND THE MEASUREMENT THAT FORCED IT

This process cannot fetch the web. MEASURED 2026-08-27 on this machine:
`docs.bfl.ai`, `arxiv.org` and `kling.ai` all answer CONNECT 403 through the
egress proxy, and going around a policy-closed host is forbidden (Ц3). What is
NOT refused is the assistant's own search tool, in the conversation where the
owner is already standing.

So the refresh is a two-step the assistant performs in the open: search the
web, then call `record` with the value, the URL, the tier and the date the
source stated it. Nothing is written without those four. A claim with no URL
cannot be checked later, and a claim with no date cannot go stale — and a
claim that cannot go stale is the one that quietly rots.

WHAT THIS REFUSES TO DO

It never resolves a contradiction. When two sources disagree the answer is
`fail` with both sides shown, because the flattening is the bug: asked how
long one Kling 3.0 generation runs, the sources say 15s and 10s and "3
minutes", and a third-party summary of those same sources confidently reported
"up to 5 minutes", which matches none of them.

It never promotes a claim by repetition. Ten blogs quoting each other are one
source, and `facts.py` enforces that; this module only reports it.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.selfrag import registry
from studio.selfrag.facts import (
    DEFAULT_FACTS_PATH,
    STALE_AFTER_DAYS,
    TIER_BENCHMARK,
    TIER_BLOG,
    TIER_PAPER,
    TIER_VENDOR,
    FactStore,
    load_facts,
)

__all__ = ["advise", "record", "stale", "TIERS", "store_for"]

TIERS = (TIER_VENDOR, TIER_BENCHMARK, TIER_PAPER, TIER_BLOG)


def store_for(path: Path | None = None) -> FactStore:
    """A fact store read fresh from disk, so a `record` is visible immediately."""
    return FactStore(load_facts(path or DEFAULT_FACTS_PATH))


def advise(model: str, attribute: str = "", *, path: Path | None = None) -> dict:
    """What is known about one model, and how much of it is worth believing.

    :param attribute: one attribute to focus on (`max_seconds`, `resolution`,
        ...). Empty means "everything recorded about this model".
    :returns: the house judging dict plus `availability` (the registry's
        conservative answer), `claims` (every recorded value with its source),
        `failure_modes` (known ways it breaks, each with its fix) and
        `contested` (the attributes whose sources disagree).

    Three outcomes, and the middle one is the point: an unknown model is
    `could not measure`, never `fail`. Not knowing is a gap in this base, not
    a defect in the model, and the two must never print the same.
    """
    name = str(model or "").strip()
    if not name:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "no model was named, so nothing was looked up",
            "availability": None,
            "claims": {},
            "failure_modes": [],
            "contested": [],
        }

    store = store_for(path)
    live = registry.availability(name)
    known_here = name.lower() in {m.lower() for m in store.models()}

    attributes = [attribute] if attribute else store.attributes(name)
    claims: dict[str, dict] = {}
    contested: list[str] = []
    for attr in attributes:
        verdict = store.claims(name, attr)
        claims[attr] = verdict
        if verdict["outcome"] == FAIL:
            contested.append(attr)

    failures = [
        {
            "value": fact.value,
            "fix": fact.fix,
            "source_url": fact.source_url,
            "tier": fact.tier,
            "stated_on": fact.stated_on,
        }
        for fact in store.failure_modes(name)
    ]

    if live["card"] is None and not known_here:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"{name!r} is in neither the registry nor the fact base. Nothing "
                "was checked, which is not the same as nothing being wrong. "
                "Search the web and call `record` to put it there."
            ),
            "availability": live,
            "claims": {},
            "failure_modes": [],
            "contested": [],
        }

    checked = len(claims) + (1 if live["card"] is not None else 0)
    if live["outcome"] == FAIL:
        return {
            "outcome": FAIL,
            "checked": checked,
            "violations": 1,
            "unmeasured": len(contested),
            "note": f"the model itself is unusable: {live['note']}",
            "availability": live,
            "claims": claims,
            "failure_modes": failures,
            "contested": contested,
        }

    if contested:
        return {
            "outcome": FAIL,
            "checked": checked,
            "violations": len(contested),
            "unmeasured": 0,
            "note": (
                f"sources disagree on {', '.join(contested)}. Every side is "
                "returned with its URL and its date; nothing here votes, "
                "averages or takes the newest."
            ),
            "availability": live,
            "claims": claims,
            "failure_modes": failures,
            "contested": contested,
        }

    if not claims:
        return {
            "outcome": UNMEASURED,
            "checked": checked,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"the registry has a card for {name!r} but the fact base holds no "
                "claim about it, so there is nothing to cite. " + str(live["note"])
            ),
            "availability": live,
            "claims": {},
            "failure_modes": failures,
            "contested": [],
        }

    unmeasured = sum(1 for v in claims.values() if v["outcome"] == UNMEASURED)
    if live["outcome"] == UNMEASURED or unmeasured == len(claims):
        return {
            "outcome": UNMEASURED,
            "checked": checked,
            "violations": 0,
            "unmeasured": max(unmeasured, 1),
            "note": (
                f"{unmeasured} of {len(claims)} attribute(s) rest on blog-tier or "
                f"stale sources. {live['note']}"
            ),
            "availability": live,
            "claims": claims,
            "failure_modes": failures,
            "contested": [],
        }

    return {
        "outcome": PASS,
        "checked": checked,
        "violations": 0,
        "unmeasured": unmeasured,
        "note": (
            f"{len(claims)} attribute(s) answered, {unmeasured} of them only weakly. {live['note']}"
        ),
        "availability": live,
        "claims": claims,
        "failure_modes": failures,
        "contested": [],
    }


def record(
    model: str,
    attribute: str,
    value: str,
    source_url: str,
    tier: str,
    stated_on: str,
    *,
    note: str = "",
    fix: str = "",
    path: Path | None = None,
) -> dict:
    """Write one web finding into the fact base, with who said it and when.

    Every argument up to `stated_on` is required and none may be blank. A claim
    without a URL cannot be re-checked; a claim without a date cannot go stale;
    a claim without a tier would let a blog outrank a vendor document.

    :param tier: one of `TIERS`. `vendor` means the vendor's own document or
        release, `paper` a venue or arXiv, `benchmark` an evaluation with a
        published method, `blog` everything else including good aggregators.
    :param stated_on: ISO date the SOURCE stated it, not today's date. Writing
        today's date for an old article is how a stale claim looks fresh.

    :returns: three outcomes. A rejected claim is `fail` and is not written.
    """
    fields = {
        "model": str(model or "").strip(),
        "attribute": str(attribute or "").strip(),
        "value": str(value or "").strip(),
        "source_url": str(source_url or "").strip(),
        "tier": str(tier or "").strip().lower(),
        "stated_on": str(stated_on or "").strip(),
    }
    missing = [name for name, text in fields.items() if not text]
    if missing:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": len(missing),
            "unmeasured": 0,
            "note": (
                "nothing was written: " + ", ".join(missing) + " is required. "
                "A claim missing any of these cannot be re-checked later."
            ),
            "written": None,
        }

    if fields["tier"] not in TIERS:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": f"tier {fields['tier']!r} is not one of {', '.join(TIERS)}",
            "written": None,
        }

    if not fields["source_url"].startswith(("http://", "https://")):
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": f"source_url {fields['source_url']!r} is not a URL",
            "written": None,
        }

    try:
        stated = date.fromisoformat(fields["stated_on"])
    except ValueError:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": f"stated_on {fields['stated_on']!r} is not an ISO date (YYYY-MM-DD)",
            "written": None,
        }
    if stated > date.today():
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": f"stated_on {fields['stated_on']} is in the future",
            "written": None,
        }

    row = {**fields, "note": str(note or ""), "fix": str(fix or "")}
    target = path or DEFAULT_FACTS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    after = store_for(target).claims(row["model"], row["attribute"])
    return {
        "outcome": PASS,
        "checked": len(fields),
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"written. {row['model']}.{row['attribute']} now stands at "
            f"{after['outcome']!r} across {after.get('checked', 0)} source(s)."
        ),
        "written": row,
        "claims_now": after,
    }


def stale(*, days: int = STALE_AFTER_DAYS, path: Path | None = None) -> dict:
    """Which claims are old enough to need a fresh look on the web.

    A claim with no date is counted as unmeasured, not as fresh. That is the
    whole reason `record` insists on a date.
    """
    facts = load_facts(path or DEFAULT_FACTS_PATH)
    if not facts:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "the fact base is empty: there is nothing to age",
            "stale": [],
            "undated": [],
        }

    old: list[dict] = []
    undated: list[dict] = []
    for fact in facts:
        age = fact.age_days
        row = {
            "model": fact.model,
            "attribute": fact.attribute,
            "value": fact.value,
            "source_url": fact.source_url,
            "tier": fact.tier,
            "stated_on": fact.stated_on,
            "age_days": age,
        }
        if age is None:
            undated.append(row)
        elif age > days:
            old.append(row)

    old.sort(key=lambda row: -(row["age_days"] or 0))
    if old or undated:
        return {
            "outcome": FAIL,
            "checked": len(facts),
            "violations": len(old),
            "unmeasured": len(undated),
            "note": (
                f"{len(old)} claim(s) older than {days} days and {len(undated)} "
                f"with no date at all, out of {len(facts)} checked. Search the "
                "web for these and call `record` with what you find."
            ),
            "stale": old,
            "undated": undated,
        }

    return {
        "outcome": PASS,
        "checked": len(facts),
        "violations": 0,
        "unmeasured": 0,
        "note": f"all {len(facts)} claim(s) are within {days} days",
        "stale": [],
        "undated": [],
    }
