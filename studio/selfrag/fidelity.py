"""Does the finished prompt say anything the user did not?

The product rule, stated by the owner: the user cannot write a good prompt, the
agent writes one FROM THEIR INTENT, and it **invents nothing** — it only
optimises for the model.

"Invents nothing" is the half that can be checked mechanically, so it is
checked on every run rather than promised in a docstring.

WHY THIS IS THE RULE THAT MATTERS

The one randomised trial in this field measured what invention costs. N=1,891,
300,000+ images: automatic GPT-4 rewriting of DALL-E 3 prompts **erased 58% of
the model's improvement**, and the stated cause was that rewrites "added extra
details or changed the meaning" (https://arxiv.org/abs/2407.14333, Information
Systems Research; read via search summary — this environment cannot open
arxiv). Meanwhile prompt length correlates with quality at about -0.07
(https://arxiv.org/pdf/2403.11821). Longer is not better. Faithful is better.

This project has already produced the failure twice in one day, before any of
that was known here:

    the user wrote "porous volcanic stone" — a material, naming the podium.
    A synonym map read it as the palette colour "sand". The prompt asked for a
    sand palette. The generator put literal sand under the bottle.

    nobody mentioned texture. A default supplied "matte". A glossy glass bottle
    came back matte.

Both would have been caught here, before a single credit was spent.

WHAT COUNTS AS INVENTION, AND WHAT DOES NOT

    INVENTED   a content word naming something in the scene that the user
               never named: an object, a material, a place, a colour, a
               creature. This is a VIOLATION.

    NOT INVENTED
        - anything the user wrote, in any inflection
        - the model's own idiom and format: slot punctuation, flags like --ar,
          the vendor's required vocabulary
        - words on `CRAFT_TOKENS` — how the picture is made rather than what
          is in it. These are how the prompt is "optimised for the model", and
          they are reported separately so a reader can still see them.

The line is deliberately drawn at WHAT versus HOW. Rearranging the user's
subject into Veo's slot order is optimisation. Adding a swan is not.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.evidence import CRAFT_TOKENS, _FUNCTION_WORDS

__all__ = [
    "FORMAT_WORDS",
    "audit",
    "invented",
]

#: Words that are the model's format rather than anybody's content: the
#: connective tissue of a prompt, and vendor flag names.
FORMAT_WORDS: frozenset[str] = frozenset(
    """
    ar v sref cref stylize style raw niji seed fps aspect ratio resolution
    duration seconds shot mode image video prompt negative no none
    """.split()
    # The assembler's own scaffolding. "a palette of teal" names a CATEGORY,
    # the way "of" does; the colour after it is the content and IS checked.
    # Without these every assembled prompt reported an invention that was
    # really a template word (OBSERVED 2026-08-26).
    + ["palette", "mood"]
)

_WORD = re.compile(r"[a-z0-9][a-z0-9'-]*")

#: A number carrying a unit: "50mm", "24fps", "8k", "f2.8". These are camera
#: settings — HOW the picture is taken, never WHAT is in it — so they are
#: format, not invention. Without this, "shot on a 50mm lens" was reported as
#: inventing "50mm" (OBSERVED 2026-08-26).
_MEASUREMENT = re.compile(r"^\d+(\.\d+)?(mm|cm|m|k|fps|s|x|f)?$|^f\d|^\d+:\d+$")

#: Crude English suffix stripping, so "reflections" matches "reflection" and
#: "lit" does not have to be spelled twice. Deliberately not a real stemmer: a
#: stemmer that over-merges would HIDE inventions, which is the one direction
#: this module must never fail in.
_SUFFIXES = ("'s", "es", "s", "ing", "ed", "ly")


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _content(text: str) -> list[str]:
    """Content words of a text, lowercased."""
    return [
        w
        for w in _WORD.findall(str(text or "").lower())
        if w not in _FUNCTION_WORDS and not w.isdigit()
    ]


def _vocabulary(sources: Iterable[str]) -> set[str]:
    """Every word the user gave, plus its stem, in one set."""
    out: set[str] = set()
    for text in sources:
        for word in _content(text):
            out.add(word)
            out.add(_stem(word))
    return out


def invented(
    prompt: str, sources: Sequence[str], *, extra_allowed: Sequence[str] = ()
) -> list[str]:
    """Content words in `prompt` that no source accounts for, in order.

    Craft and format words are not returned: they are how, not what.
    """
    allowed = _vocabulary(sources) | _vocabulary(extra_allowed)
    seen: list[str] = []
    for word in _content(prompt):
        stem = _stem(word)
        if word in allowed or stem in allowed:
            continue
        if word in CRAFT_TOKENS or stem in CRAFT_TOKENS:
            continue
        if word in FORMAT_WORDS or stem in FORMAT_WORDS:
            continue
        if _MEASUREMENT.match(word):
            continue
        if word not in seen:
            seen.append(word)
    return seen


def audit(
    prompt: str,
    sources: Sequence[str],
    *,
    extra_allowed: Sequence[str] = (),
) -> dict:
    """Three outcomes on the invention question.

    * `fail` — the prompt names something the user did not.
    * `pass` — every content word traces to the user, to craft vocabulary or
      to the model's format.
    * `could not measure` — there is no prompt, or no source text to check it
      against. An unchecked prompt is NOT a faithful one, and saying so is the
      point: the two must never print the same.

    :param sources: everything the user supplied — their free text and every
        slot they filled.
    :param extra_allowed: words a caller has decided are legitimate here, such
        as corpus phrases the operator switched on deliberately. Passing them
        is a decision that gets recorded, not a way to silence the rule.
    """
    text = str(prompt or "").strip()
    supplied = [s for s in sources if str(s or "").strip()]
    if not text:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "no prompt to audit",
            "invented": [],
        }
    if not supplied:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                "no source text: every word of this prompt is unaccounted for, and "
                "that is not the same as every word being faithful"
            ),
            "invented": [],
        }

    words = _content(text)
    found = invented(text, supplied, extra_allowed=extra_allowed)
    if found:
        return {
            "outcome": FAIL,
            "checked": len(words),
            "violations": len(found),
            "unmeasured": 0,
            "note": (
                f"the prompt names {len(found)} thing(s) the user did not: "
                f"{', '.join(found)}. Invented detail is the documented way this "
                "kind of tool destroys the gain it was built to deliver"
            ),
            "invented": found,
        }
    return {
        "outcome": PASS,
        "checked": len(words),
        "violations": 0,
        "unmeasured": 0,
        "note": f"all {len(words)} content words trace to the request, craft vocabulary or format",
        "invented": [],
    }
