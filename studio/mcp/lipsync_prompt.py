"""Write a lipsync prompt out of the corpus, and never out of thin air.

THE METHOD THAT WAS TRIED FIRST, AND WHY IT WAS THROWN AWAY

The obvious way to "lean on the corpus" is to splice clauses out of prompts
that worked. It was built and run on 2026-08-27, and it passed the contract
gate — no forbidden subject word, both bands respected. Then the output was
read rather than measured:

    "...faint frost forming on its surface, smooth gradients and elegant
     shadows. faces and visual details exactly as provided. Behind the
     laptop hangs a full wall of luxurious floor-to-ceiling velvet curtains"

A laptop, a sleigh and somebody's snow, in a prompt asked to describe burgundy
velvet under moonlight. Splicing a clause imports the SCENE that clause was
written for, and the gate cannot see it: a foreign scene breaks no rule in
`fork_style_prompt`, it just makes the prompt worthless. A number passed and a
reader would have thrown it out in a second, which is the whole reason the
house rule says to open what you produced with your eyes.

WHAT IS DONE INSTEAD

The corpus is read for the only thing that generalises across scenes: which
LOOK ATTRIBUTES the prompts that worked actually commit to, and which of them
occur together. `knowledge.structure_from_text` already extracts them against
fixed allow-lists — palette, light, texture, mood. Those attributes carry no
scene with them, so nobody's laptop can ride along.

The attributes then go into the engine's own card, and the engine's own
`fork_style_prompt.compose()` builds the sentence over its frozen skeleton.
This package does not write the sentence at all. That is deliberate: the
skeleton is the thing that has been measured against the corpus bands, and a
prompt built over it cannot break the contract by construction — which is why
the gate is still run afterwards, to catch the day that stops being true.

WHO WINS WHEN THE OWNER AND THE CORPUS DISAGREE

The owner. A value they named is taken as given; the corpus only fills the
slots they left silent, and every filled slot comes back with the record ids
that voted for it. Where the owner said nothing and the corpus does not agree
either, the slot is reported UNRESOLVED and the run returns `could not
measure` with a question to ask. It does not pick. Picking silently is how a
tool starts producing prompts its owner never chose.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from lipsync.fork_style_prompt import PALETTE_WIDTH, SATURATION_WORDS, compose

# `studio/knowledge.py` and the directory `studio/knowledge/` share a name. At
# run time the module wins, because the directory has no `__init__.py` and is
# only a namespace package — VERIFIED 2026-08-27, `studio.knowledge.__file__`
# resolves to the .py file. mypy resolves the other way and cannot see these
# names, hence the ignore. The collision predates this package and belongs to
# whoever owns those two paths; it is reported, not worked around.
from studio.knowledge import (  # type: ignore[attr-defined]
    CARD_VALUE_KEY_LIGHT,
    LIGHT_WORDS,
    MOOD_WORDS,
    PALETTE_WORDS,
    TEXTURE_WORDS,
    structure_from_text,
)
from studio.mcp.contract import gate

__all__ = ["write", "read_intent", "vote", "DEFAULT_K", "MIN_SUPPORT"]

# CHOSEN by the owner's assistant: how many precedents to pull before voting.
DEFAULT_K = 12

# CHOSEN, and it is the load-bearing constant of this module. One corpus prompt
# that happens to say "teal" is not evidence that teal belongs here; two
# independent prompts agreeing is the weakest thing that is not a coincidence.
# Raising it makes the tool refuse more often; lowering it to 1 turns a single
# stray precedent into a decision.
MIN_SUPPORT = 2

# The three light words the engine already maps, INVERTED from its own table
# rather than retyped — retyping it is how the two quietly disagree.
LIGHT_TO_VALUE_KEY: dict[str, str] = {light: key for key, light in CARD_VALUE_KEY_LIGHT.items()}

# CHOSEN by the owner's assistant: the remaining light words the engine's table
# does not name. The corpus speaks in ten light words and the engine takes
# three value keys, so somebody has to place the other seven; this is that
# decision, written where it can be argued with.
LIGHT_TO_VALUE_KEY.update(
    {
        "candlelit": "dark",
        "neon": "dark",
        "backlit": "dark",
        "studio": "light",
        "golden-hour": "mid",
        "hard": "mid",
        "overcast": "mid",
    }
)

# CHOSEN: the words an owner uses for saturation, which no corpus field carries.
SATURATION_CUES: dict[str, tuple[str, ...]] = {
    "muted": ("muted", "desaturated", "washed", "pastel", "subdued", "restrained"),
    "saturated": ("saturated", "vivid", "rich", "bold", "punchy", "intense"),
    "moderate": ("natural", "balanced", "neutral", "moderate"),
}

_FIELD_WORDS: dict[str, tuple[str, ...]] = {
    "palette": tuple(PALETTE_WORDS),
    "light": tuple(LIGHT_WORDS),
    "texture": tuple(TEXTURE_WORDS),
    "mood": tuple(MOOD_WORDS),
}


def read_intent(intent: str) -> dict:
    """What the owner named outright, in the engine's own vocabulary.

    >>> read_intent("muted ivory, low-key light, matte")["saturation"]
    'muted'
    >>> read_intent("muted ivory, low-key light, matte")["palette"]
    ['ivory']
    """
    text = str(intent or "").lower()
    found = structure_from_text(text)

    saturation = ""
    for key, cues in SATURATION_CUES.items():
        if any(re.search(r"\b" + re.escape(cue), text) for cue in cues):
            saturation = key
            break

    return {
        "palette": sorted(found["palette"]),
        "light": sorted(found["light"]),
        "texture": sorted(found["texture"]),
        "mood": sorted(found["mood"]),
        "saturation": saturation,
    }


def _entry_fields(item: Any) -> tuple[str, str]:
    """(prompt text, record id) out of whatever shape the retriever returned."""
    if isinstance(item, dict):
        text = item.get("text") or item.get("prompt") or ""
        source = item.get("source") or item.get("record_id") or item.get("id") or ""
    else:
        text = getattr(item, "text", None) or getattr(item, "prompt", "") or ""
        source = (
            getattr(item, "source", None)
            or getattr(item, "record_id", None)
            or getattr(item, "id", "")
            or ""
        )
    return str(text), str(source).split(" ")[0]


def vote(examples: Sequence[Any]) -> dict:
    """Which look attributes the retrieved precedents agree on, and who voted.

    :returns: `{field: [{"value": str, "support": int, "record_ids": [...]}]}`,
        each field's list ordered by support. Values below `MIN_SUPPORT` are
        kept in the result so a caller can show what was seen and rejected.
    """
    tally: dict[str, dict[str, list[str]]] = {field: defaultdict(list) for field in _FIELD_WORDS}
    for item in examples:
        text, source = _entry_fields(item)
        if not text:
            continue
        found = structure_from_text(text)
        for field in _FIELD_WORDS:
            for value in found.get(field, ()):  # type: ignore[call-overload]
                tally[field][value].append(source)

    out: dict[str, list[dict]] = {}
    for field, values in tally.items():
        ranked = sorted(
            ((value, sorted(set(ids))) for value, ids in values.items()),
            key=lambda pair: (-len(pair[1]), pair[0]),
        )
        out[field] = [
            {"value": value, "support": len(ids), "record_ids": ids} for value, ids in ranked
        ]
    return out


def _supported(rows: Sequence[dict], limit: int = 1) -> list[dict]:
    """The rows that cleared the support floor, most-supported first."""
    return [row for row in rows if row["support"] >= MIN_SUPPORT][:limit]


def write(intent: str, examples: Sequence[Any]) -> dict:
    """Build a contract-clean lipsync prompt from the owner's words plus the corpus.

    :param intent: the owner's own words for the look they want.
    :param examples: precedents from `studio.knowledge.retrieve`.
    :returns: the house judging dict plus `prompt`, `card` (what was sent to the
        engine), `chosen` (where every card value came from) and `unresolved`
        (the slots nobody could fill, each with the question to ask).

    Three outcomes. `could not measure` when a required slot is unresolved: the
    engine could be handed a guess instead, and a guess is what this refuses.
    """
    # An empty intent is NOT short-circuited. It used to be, and a blind control
    # set caught what that cost on 2026-08-27: `write("", [])` returned "could
    # not measure" with an empty `unresolved`, so the one caller most in need of
    # the four questions — somebody who said nothing at all — got none of them.
    # Falling through means every unfilled slot produces its question by the
    # same path, whatever the intent was.
    said = str(intent or "").strip()

    named = read_intent(said)
    votes = vote(examples)

    chosen: dict[str, dict] = {}

    # Palette. If the owner named ANY colour, that is the palette — the corpus
    # does not top it up to the engine's width.
    #
    # It used to. A blind control set caught it on 2026-08-27: asked for "muted
    # teal and slate", with three precedents shouting crimson, the tool built
    # "a palette of slate, teal and crimson". Nothing the owner said was
    # overruled, so every override test stayed green — a colour was simply
    # ADDED, which the product rule forbids outright. Two named colours mean a
    # two-colour palette, not a vacancy.
    colours = list(named["palette"])
    palette_sources: list[str] = []
    if colours:
        chosen["palette"] = {"value": colours, "from": "owner", "record_ids": []}
    else:
        for row in _supported(votes["palette"], limit=PALETTE_WIDTH):
            colours.append(row["value"])
            palette_sources.extend(row["record_ids"])
        if colours:
            chosen["palette"] = {
                "value": colours,
                "from": "corpus",
                "record_ids": sorted(set(palette_sources)),
            }

    # Light -> the engine's three-way value key.
    light_word = named["light"][0] if named["light"] else ""
    light_sources: list[str] = []
    if not light_word:
        top = _supported(votes["light"])
        if top:
            light_word = top[0]["value"]
            light_sources = top[0]["record_ids"]
    value_key = LIGHT_TO_VALUE_KEY.get(light_word, "")
    if value_key:
        chosen["value_key"] = {
            "value": value_key,
            "via": light_word,
            "from": "owner" if named["light"] else "corpus",
            "record_ids": light_sources,
        }

    # Texture.
    texture = named["texture"][0] if named["texture"] else ""
    texture_sources: list[str] = []
    if not texture:
        top = _supported(votes["texture"])
        if top:
            texture = top[0]["value"]
            texture_sources = top[0]["record_ids"]
    if texture:
        chosen["texture"] = {
            "value": texture,
            "from": "owner" if named["texture"] else "corpus",
            "record_ids": texture_sources,
        }

    # Saturation. No corpus FIELD carries it, but corpus PROMPTS say "muted",
    # "desaturated", "vivid" in plain words, and `read_intent` already knows how
    # to read them. So it is corroborated the same way as light and texture:
    # two distinct records or nothing.
    #
    # This module used to refuse saturation from the corpus outright, on the
    # grounds that no field carried it. A blind control set caught the
    # inconsistency on 2026-08-27: two independent records both saying
    # "muted desaturated restrained colour" filled light and texture and left
    # saturation unresolved, so a request fully covered by evidence still came
    # back as "could not measure". Refusing evidence is not conservatism, it is
    # a different rule for one slot.
    saturation = named["saturation"]
    saturation_sources: list[str] = []
    if saturation:
        chosen["saturation"] = {"value": saturation, "from": "owner", "record_ids": []}
    else:
        cues: dict[str, list[str]] = defaultdict(list)
        for item in examples:
            text, source = _entry_fields(item)
            seen = read_intent(text)["saturation"]
            if seen:
                cues[seen].append(source)
        ranked = sorted(
            ((value, sorted(set(ids))) for value, ids in cues.items()),
            key=lambda pair: (-len(pair[1]), pair[0]),
        )
        if ranked and len(ranked[0][1]) >= MIN_SUPPORT:
            saturation, saturation_sources = ranked[0][0], ranked[0][1]
            chosen["saturation"] = {
                "value": saturation,
                "from": "corpus",
                "record_ids": saturation_sources,
            }

    unresolved: list[dict] = []
    if len(named["palette"]) > PALETTE_WIDTH:
        # The engine truncates a wider palette silently (`colours[:PALETTE_WIDTH]`),
        # so a colour the owner named would vanish from the prompt without anyone
        # being told. Asking costs one message; a dropped colour costs a render.
        unresolved.append(
            {
                "slot": "palette",
                "ask": (
                    f"You named {len(named['palette'])} colours "
                    f"({', '.join(named['palette'])}) and the engine takes "
                    f"{PALETTE_WIDTH}. Which {PALETTE_WIDTH}?"
                ),
            }
        )
    elif not colours:
        unresolved.append(
            {
                "slot": "palette",
                "ask": ("Which colours? Name one to three of: " + ", ".join(PALETTE_WORDS)),
            }
        )
    if not value_key:
        unresolved.append(
            {
                "slot": "value_key",
                "ask": "How lit — light, mid or dark?",
            }
        )
    if not texture:
        unresolved.append(
            {
                "slot": "texture",
                "ask": "Which surface? One of: " + ", ".join(TEXTURE_WORDS),
            }
        )
    if not saturation:
        unresolved.append(
            {
                "slot": "saturation",
                "ask": "How much colour — " + ", ".join(SATURATION_WORDS) + "?",
            }
        )

    if unresolved:
        return {
            "outcome": UNMEASURED,
            "checked": 4,
            "violations": 0,
            "unmeasured": len(unresolved),
            "note": (
                f"{4 - len(unresolved)} of 4 card slots were filled; "
                + "; ".join(row["slot"] for row in unresolved)
                + " could not be, and a guess is not a prompt. Ask, then run again."
            ),
            "prompt": None,
            "card": None,
            "chosen": chosen,
            "unresolved": unresolved,
            "gate": gate(""),
        }

    card = {
        "colours": colours,
        "value_key": value_key,
        "saturation": saturation,
        "texture": texture,
    }
    built = compose(card)
    verdict = gate(built.get("prompt") or "")

    if built["outcome"] != PASS or verdict["outcome"] != PASS:
        return {
            "outcome": FAIL,
            "checked": verdict["checked"] or 1,
            "violations": max(verdict["violations"], 1),
            "unmeasured": 0,
            "note": (
                "the engine built a prompt that breaks its own contract, and it is "
                f"returned unrepaired: engine said {built.get('note')!r}; gate said "
                f"{verdict['note']!r}"
            ),
            "prompt": built.get("prompt"),
            "card": card,
            "chosen": chosen,
            "unresolved": [],
            "gate": verdict,
        }

    from_corpus = sorted({rid for row in chosen.values() for rid in row.get("record_ids", ())})
    return {
        "outcome": PASS,
        "checked": verdict["checked"],
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"4 of 4 card slots filled, {len(from_corpus)} corpus record(s) "
            f"consulted; {verdict['note']}"
        ),
        "prompt": built["prompt"],
        "card": card,
        "chosen": chosen,
        "unresolved": [],
        "gate": verdict,
    }
