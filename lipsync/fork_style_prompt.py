"""Style adapter: photo reference -> card -> a working prompt over the skeleton."""

from __future__ import annotations

import re

from .fork_identity import FAIL, PASS, UNMEASURED


WORDS_TARGET = 24

WORDS_MIN = 9
WORDS_MAX = 67

CLAUSES_TARGET = 5
CLAUSES_MIN = 1
CLAUSES_MAX = 13
CLAUSES_MOST_COMMON = 7

SUBJECT_WORDS = (
    "person",
    "man",
    "woman",
    "girl",
    "boy",
    "face",
    "hair",
    "body",
    "wearing",
    "dress",
    "shirt",
    "pose",
    "posing",
    "dancing",
    "smiling",
)


VALUE_WORDS = {
    "light": "bright high-key lighting",
    "mid": "even balanced lighting",
    "dark": "low-key shadowed lighting",
}

SATURATION_WORDS = {
    "muted": "desaturated restrained colour",
    "moderate": "natural colour balance",
    "saturated": "rich saturated colour",
}

CLOSING = "photographic look"

PALETTE_WIDTH = 3


def _words(text: str) -> int:
    """Count the words in the prompt, in one single way for the whole module."""
    return len(re.findall(r"[A-Za-z][A-Za-z'-]*", text))


def _clauses(text: str) -> int:
    """Count the clauses in the prompt: comma-separated pieces. Empty ones do not count."""
    return len([c for c in text.split(",") if c.strip()])


def subject_leak(text: str) -> list:
    """List the forbidden words found in the prompt. An empty list means clean."""
    low = text.lower()
    return [w for w in SUBJECT_WORDS if re.search(r"\b" + re.escape(w) + r"\b", low)]


def compose(card: dict) -> dict:
    """Turn a style card into a prompt. Three outcomes, not two."""
    empty = {
        "outcome": UNMEASURED,
        "prompt": None,
        "words": 0,
        "clauses": 0,
        "leak": [],
        "card": card,
    }
    if not isinstance(card, dict):
        return {**empty, "note": "the card is not a dict: the style was NOT READ"}

    colours = card.get("colours") or []
    value = card.get("value_key")
    sat = card.get("saturation")
    tex = card.get("texture")

    missing = [
        name
        for name, v in (
            ("colours", colours),
            ("value_key", value),
            ("saturation", sat),
            ("texture", tex),
        )
        if not v
    ]
    if missing:
        return {
            **empty,
            "note": (
                "the card is missing the fields "
                + ", ".join(missing)
                + ": the style was NOT READ, which is not 'there is no style'"
            ),
        }
    if value not in VALUE_WORDS:
        return {
            **empty,
            "note": (
                f"value key {value!r} is not in the dictionary {sorted(VALUE_WORDS)}: NOT READ"
            ),
        }
    if sat not in SATURATION_WORDS:
        return {
            **empty,
            "note": (
                f"saturation {sat!r} is not in the dictionary {sorted(SATURATION_WORDS)}: NOT READ"
            ),
        }

    taken = list(colours)[:PALETTE_WIDTH]
    if len(taken) > 1:
        palette = "a palette of " + ", ".join(taken[:-1]) + " and " + taken[-1]
    else:
        palette = "a palette of " + taken[0]

    parts = [palette, VALUE_WORDS[value], SATURATION_WORDS[sat], tex, CLOSING]
    prompt = ", ".join(parts)

    w, c = _words(prompt), _clauses(prompt)
    leak = subject_leak(prompt)
    if leak:
        outcome = FAIL
        note = (
            f"the prompt touched the forbidden zone {leak}: style must "
            f"describe the look, not the subject — the subject comes from "
            f"the photo and the driving"
        )
    elif not (WORDS_MIN <= w <= WORDS_MAX):
        outcome = FAIL
        note = f"words {w}, corpus band {WORDS_MIN}..{WORDS_MAX} (median {WORDS_TARGET})"
    elif not (CLAUSES_MIN <= c <= CLAUSES_MAX):
        outcome = FAIL
        note = f"clauses {c}, corpus band {CLAUSES_MIN}..{CLAUSES_MAX} (median {CLAUSES_TARGET})"
    else:
        outcome = PASS
        note = (
            f"words {w} against the corpus median {WORDS_TARGET} "
            f"(band {WORDS_MIN}..{WORDS_MAX}), clauses {c} against the "
            f"median {CLAUSES_TARGET} and band {CLAUSES_MIN}..{CLAUSES_MAX}; "
            f"forbidden words 0"
        )
    return {
        "outcome": outcome,
        "prompt": prompt,
        "words": w,
        "clauses": c,
        "leak": leak,
        "card": card,
        "note": note,
    }


def from_image(path, *, reader=None) -> dict:
    """Turn an image into a prompt. `reader` is an injection point."""
    if reader is None:

        def reader(p):
            from creative_eval.style import style_card  # noqa: PLC0415

            return style_card(p)

    try:
        card = reader(str(path))
    except Exception as exc:  # noqa: BLE001
        return {
            "outcome": UNMEASURED,
            "prompt": None,
            "words": 0,
            "clauses": 0,
            "leak": [],
            "card": None,
            "note": (f"the card could not be read: {type(exc).__name__}: {exc}"),
        }
    out = compose(card)
    out["source"] = str(path)
    return out


def differ(left: dict, right: dict) -> dict:
    """Check that two cards give different prompts. The adapter's negative control."""
    a, b = compose(left), compose(right)
    if a["outcome"] == UNMEASURED or b["outcome"] == UNMEASURED:
        return {
            "outcome": UNMEASURED,
            "same": None,
            "note": "at least one card did not read: nothing to compare",
        }
    same = a["prompt"] == b["prompt"]
    return {
        "outcome": FAIL if same else PASS,
        "same": same,
        "left": a["prompt"],
        "right": b["prompt"],
        "note": (
            "the prompts MATCHED on different cards: the adapter does not discriminate"
            if same
            else "the prompts differ, the adapter discriminates"
        ),
    }


def report_text(out: dict) -> str:
    """Render the human report: verdict, numbers, prompt. The numbers sit next to the verdict."""
    head = f"[{out['outcome']:<18}] style prompt"
    body = f"  {out['note']}"
    tail = f"  prompt: {out['prompt']}" if out.get("prompt") else "  no prompt"
    return "\n".join([head, body, tail])
