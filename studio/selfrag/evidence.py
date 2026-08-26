"""Turn retrieved precedents into words the prompt can actually use.

Until this module existed the retrieval was decorative. MEASURED 2026-08-26:
for a request about a serum bottle on volcanic stone, the retriever returned
five precedents — one of them an Apple Watch on porous volcanic stone, very
nearly the same scene — and the words those five contributed to the finished
prompt were "a", "of" and "palette". `assemble()` did not take an `examples`
argument at all. A corpus of 4601 prompts and recall@5 of 0.95 were feeding
nothing.

WHAT IS TAKEN, AND WHY THAT AND NOT MORE

The agent's own vocabulary is four allow-lists of single words: a palette
colour, a light word, a texture word, a mood word. The corpus is written in the
vocabulary of the trade — focal lengths, film stocks, the names of lighting
setups, the words for how a surface takes light. That gap is what the corpus is
for, so that is what is mined: short craft phrases, not sentences.

THE SUPPORT RULE, which does two jobs at once

A phrase is only used when it appears in at least `MIN_SUPPORT` different
precedents. That is a quality rule — a phrase two authors reached for
independently is a convention of the trade, while a phrase in one prompt is one
author's habit and may simply be wrong. It is also the licence-hygiene rule:
`gallery_prompts.jsonl` is a third party's catalogue, and a convention several
of its authors share is a fact about how this work is written, not any one
author's expression. Copying a whole clause from a single prompt would be
neither.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Sequence

from lipsync.fork_identity import PASS, UNMEASURED

__all__ = [
    "CRAFT_TOKENS",
    "MAX_PHRASES",
    "MAX_PHRASE_WORDS",
    "MIN_PHRASE_WORDS",
    "CRAFT_SHARE",
    "MIN_SUPPORT",
    "craft_phrases",
]

#: Words that mark a phrase as CRAFT — how the picture was made, rather than
#: what is in it. A phrase is only a candidate if it carries one of these.
#: Subject nouns are deliberately absent: the subject is the user's to choose,
#: and lifting one from a precedent would put somebody else's product in their
#: picture.
CRAFT_TOKENS: frozenset[str] = frozenset(
    """
    lens mm macro telephoto wide-angle fisheye anamorphic bokeh aperture
    lighting light lit backlit rim softbox key fill spill diffused directional
    shadow shadows highlight highlights specular reflection reflections glow
    film grain stock exposure contrast saturation tone tones grade graded
    depth focus focal sharp crisp soft matte glossy satin sheen texture surface
    studio editorial cinematic photographic hyperrealistic photorealistic
    composition centred centered symmetrical negative-space framing angle
    overhead top-down low-angle eye-level close-up
    daylight sunlight moonlight candlelight ambient shadowless dappled
    backlight underlit uplit chiaroscuro vignette monochrome desaturated
    high-key low-key golden blue-hour hour natural warm cool neutral
    reflective translucent transparent opaque polished brushed frosted
    velvety powdery tactile grainy smooth glossy sharpness clarity
    render rendered photograph photography shot shoot lit
    """.split()
)

#: A clause must be seen in this many DIFFERENT precedents to be used.
MIN_SUPPORT = 2

#: What share of a clause's content words must be craft words. Merely
#: CONTAINING a craft word is not enough, and the first version of this module
#: proved it: "petals softly catching the rim light" cleared a contains-check
#: on "rim" and "light" and would have put petals into a photograph of a serum
#: bottle (OBSERVED 2026-08-26). That is the same defect as the synonym map
#: turning "stone" into sand — scene content the user never asked for — only
#: arriving through the corpus instead of through a dictionary.
#:
#: CHOSEN at 0.5, then checked against the clauses this corpus actually
#: produces: it keeps "cinematic editorial product photography" and drops
#: "petals softly catching the rim light", "one square and matte ceramic",
#: "completely ignoring the lens" and "2 gm lens".
#:
#: A ratio is only as good as the list it counts against, and the first
#: version of that list was too short: "sharp natural daylight" scored 1 of 3
#: because neither "natural" nor "daylight" was in it. The list was extended
#: with vocabulary that belongs there on its own terms — light names, surface
#: finishes, the words for how a photograph was taken — rather than with
#: whatever words would have raised a coverage number.
CRAFT_SHARE = 0.5

#: Words carrying no content either way, so they neither help nor hurt the
#: share above.
_FUNCTION_WORDS: frozenset[str] = frozenset(
    "a an and the is are of on in at by with to from its it that this each one two".split()
)

#: Longest clause taken. A descriptor, not a sentence.
MAX_PHRASE_WORDS = 6

#: Shortest clause worth taking. One or two words is usually a bare noun.
MIN_PHRASE_WORDS = 3

#: Most phrases added to one prompt. The word band is the real limit; this
#: stops the evidence clause from dominating a short prompt.
MAX_PHRASES = 3

_WORD = re.compile(r"[a-z0-9][a-z0-9'-]*")

#: Prompts in this trade are written as comma-separated descriptors, so a
#: comma is where one thought ends. Splitting on n-grams instead cut phrases
#: mid-sentence and produced "view softly illuminated cinematic" — three words
#: of somebody's sentence with the grammar removed (OBSERVED 2026-08-26 on the
#: first wiring of this module). A clause is the unit the author wrote AS a
#: unit, so a clause is what gets taken.
_CLAUSE_SPLIT = re.compile(r"[,;.]|\s+--\w+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(str(text or "").lower())


def _clauses(prompt: str) -> list[str]:
    """The comma-separated descriptors of one prompt, normalised."""
    out: list[str] = []
    for piece in _CLAUSE_SPLIT.split(str(prompt or "")):
        words = _tokens(piece)
        if MIN_PHRASE_WORDS <= len(words) <= MAX_PHRASE_WORDS:
            out.append(" ".join(words))
    return out


def craft_phrases(
    examples: Sequence[Any],
    *,
    avoid: str = "",
    max_phrases: int = MAX_PHRASES,
    min_support: int = MIN_SUPPORT,
) -> dict:
    """Craft phrases several precedents agree on, minus anything already said.

    :param examples: retrieved precedents; each needs `.prompt` or a `prompt`
        key, and `.record_id` or a `record_id` key for attribution.
    :param avoid: the user's own text. A phrase they already wrote is not
        evidence, it is repetition.
    :returns: the judging dict plus `phrases` — each with its support count and
        the record ids that carried it, so any clause in a finished prompt can
        be traced back to the prompts that justified it.
    """
    rows: list[tuple[str, str]] = []
    for item in examples:
        prompt = getattr(item, "prompt", None)
        record_id = getattr(item, "record_id", None)
        if prompt is None and isinstance(item, dict):
            prompt = item.get("prompt")
            record_id = item.get("record_id") or item.get("id")
        if prompt:
            rows.append((str(record_id or ""), str(prompt)))

    if not rows:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "no precedents were retrieved: nothing to learn from",
            "phrases": [],
        }

    already = set(_tokens(avoid))
    support: Counter[str] = Counter()
    sources: dict[str, set[str]] = {}
    for record_id, prompt in rows:
        for clause in dict.fromkeys(_clauses(prompt)):
            clause_words = clause.split()
            content = [w for w in clause_words if w not in _FUNCTION_WORDS]
            craft = [w for w in content if w in CRAFT_TOKENS]
            if not content or len(craft) < CRAFT_SHARE * len(content):
                continue
            # A clause the user already wrote is repetition, not evidence.
            if all(word in already for word in clause_words):
                continue
            support[clause] += 1
            sources.setdefault(clause, set()).add(record_id)

    kept: list[dict] = []
    kept_words: list[set[str]] = []
    for clause, count in support.most_common():
        if count < min_support:
            continue
        # Two clauses sharing more than half their words say the same thing
        # twice — "soft directional studio light" and "soft directional studio
        # lighting" are one convention, and putting both in a prompt spends the
        # word band on a repetition.
        words = set(clause.split())
        if any(len(words & seen) * 2 > len(words) for seen in kept_words):
            continue
        kept_words.append(words)
        kept.append(
            {
                "phrase": clause,
                "support": count,
                "sources": sorted(sources[clause]),
            }
        )
        if len(kept) >= max_phrases:
            break

    if not kept:
        return {
            "outcome": UNMEASURED,
            "checked": len(rows),
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"{len(rows)} precedents, and no craft clause appeared in {min_support} "
                "of them. One prompt's habit is not a convention, so nothing was taken."
            ),
            "phrases": [],
        }
    return {
        "outcome": PASS,
        "checked": len(rows),
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"{len(kept)} craft phrase(s) that {min_support}+ precedents agree on, "
            f"out of {len(rows)} retrieved"
        ),
        "phrases": kept,
    }
