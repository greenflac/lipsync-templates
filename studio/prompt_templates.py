"""Prompt calibration: the user changes what the template declares, and nothing else.

A prompt template is a purchase decision frozen into data, the way a motion
template is (`studio/templates.py`, a SIBLING module this one does not touch).
The motion template carries a driving clip the owner proved; a prompt template
carries a prompt the owner proved. The user picks one, calibrates the elements
it declares, and the substituter changes nothing else.

    template (owner's prompt) -> user picks values for declared elements
                              -> substitute -> verify nothing else moved

There is no retrieval here and no model call. This path is deterministic and
free (`docs/PRODUCT_LOGIC.md`, settled 2026-08-26).

WHY SUBSTITUTION IS BY CHARACTER RANGE AND NEVER BY `str.replace`

`str.replace` matches text, and text repeats. Two ways it goes wrong, both
observed while building this module (2026-08-26, both reproduced as tests in
`studio/tests/test_prompt_templates.py`):

    the light element's base text is "a full moon". A user picks the subject
    "a pale grey cashmere scarf shaped like a full moon" — a real value on this
    template's allow-list. After the subject is replaced the prompt contains
    "a full moon" TWICE, and `str.replace` then rewrites the first occurrence,
    which is the one inside the user's own subject. The moon in the sky is
    left alone and the scarf is turned into a lantern.

    the base of template `winter_jacket_moonlight` contains the word "blue"
    inside "silver-blue". Any replace keyed on a short word walks into
    neighbouring words the author never offered for calibration.

A character range cannot do either: it names ONE place. Substitutions are
applied RIGHT-TO-LEFT so that every span still to be written keeps the offsets
it was measured at — a left-to-right pass shifts every later span by the length
delta of the earlier one and silently cuts words in half.

WHY `verify` IS NOT A FORMALITY

The invariant is mechanical: every character of the output that differs from
the base must lie inside a span of an element the user calibrated. `verify`
diffs the output against the base, walking the gaps BETWEEN the calibrated
spans and demanding they be byte-identical, while carrying the offset shift
each substitution introduces. It re-derives that arithmetic from the applied
values rather than trusting the numbers `calibrate` produced, so a bug in the
substituter shows up as a `fail` instead of being blessed by its own author
(harness rule И1: the verdict is not the maker's).

THREE OUTCOMES, ALWAYS

`pass` / `fail` / `could not measure`, never collapsed into two. Zero
substitutions is `could not measure`, never `pass`: a prompt nobody calibrated
has not been checked, and "unchecked" must not print the same as "clean".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

__all__ = [
    "CATALOGUE",
    "Element",
    "PromptTemplate",
    "TemplateError",
    "calibrate",
    "catalogue",
    "describe",
    "element",
    "get",
    "locate",
    "span_problems",
    "verify",
]


class TemplateError(ValueError):
    """A template that cannot be trusted to substitute correctly.

    Raised at CONSTRUCTION, not at use. A span that is out of bounds, empty or
    overlapping another is a broken template, and the contract is explicit that
    it must be reported as such rather than silently skipped: a skipped element
    is a knob the UI still shows and the substituter no longer honours.
    """


@dataclass(frozen=True)
class Element:
    """One thing in the prompt the user may change.

    :param name: the key the caller passes in `choices` ("subject", "light").
    :param label: what the UI shows a human.
    :param span: EXACT character range in the template prompt, `[start, end)`.
    :param allowed: the values this template's author permits. Not a global
        word list: the author knows which alternatives work in THIS
        composition, and a global list does not (`docs/PRODUCT_LOGIC.md`).
    """

    name: str
    label: str
    span: tuple[int, int]
    allowed: tuple[str, ...]

    def __post_init__(self) -> None:
        # Checked here rather than in PromptTemplate because these three are
        # true of an element on its own; bounds and overlap need the prompt and
        # are checked in `span_problems`.
        if not self.name:
            raise TemplateError("an element with no name cannot be chosen by anyone")
        if len(self.span) != 2:
            raise TemplateError(f"element {self.name!r}: span must be (start, end)")
        start, end = self.span
        if start < 0 or end <= start:
            raise TemplateError(
                f"element {self.name!r}: span {self.span} is empty or negative; "
                "prompt[start:end] must be non-empty text"
            )
        if not self.allowed:
            raise TemplateError(
                f"element {self.name!r}: no allowed values, so nothing a user picks "
                "could ever be accepted — that is a broken knob, not a locked one"
            )


@dataclass(frozen=True)
class PromptTemplate:
    """The owner's proven prompt plus the fixed set of elements it declares."""

    id: str
    prompt: str
    model: str
    elements: tuple[Element, ...]

    def __post_init__(self) -> None:
        problems = span_problems(self.prompt, self.elements)
        if problems:
            raise TemplateError(f"template {self.id!r}: " + "; ".join(problems))


def span_problems(prompt: str, elements: Sequence[Element]) -> list[str]:
    """Everything wrong with these spans against this prompt, in reading order.

    One implementation, two callers (harness rule Е1: one knowledge, one
    place). `PromptTemplate.__post_init__` raises on a non-empty result;
    `calibrate` re-runs it and returns `fail`, because a frozen dataclass can
    still be conjured past `__init__` (`object.__new__`, an old pickle) and the
    contract names overlapping spans as a `fail` outcome of `calibrate`.

    Example:
        >>> span_problems("abc", (Element("x", "X", (1, 9), ("q",)),))
        ["element 'x': span (1, 9) ends past the prompt (3 characters)"]
    """
    problems: list[str] = []
    seen: set[str] = set()
    for el in elements:
        if el.name in seen:
            problems.append(f"element {el.name!r} is declared twice; a name must mean one span")
        seen.add(el.name)
        start, end = el.span
        if end > len(prompt):
            problems.append(
                f"element {el.name!r}: span {el.span} ends past the prompt "
                f"({len(prompt)} characters)"
            )
        elif not prompt[start:end]:
            problems.append(f"element {el.name!r}: span {el.span} selects no text")

    # Overlap is judged on a sorted copy so the report does not depend on the
    # order the author happened to list the elements in.
    ordered = sorted(elements, key=lambda e: e.span)
    for earlier, later in zip(ordered, ordered[1:]):
        if later.span[0] < earlier.span[1]:
            problems.append(
                f"elements {earlier.name!r} and {later.name!r} overlap: "
                f"{earlier.span} and {later.span}. One character cannot belong to two "
                "knobs; whichever is substituted second would eat the other"
            )
    return problems


def locate(prompt: str, phrase: str) -> tuple[int, int]:
    """Character range of `phrase` in `prompt`, computed — never typed by hand.

    Every span in `CATALOGUE` goes through here. A hand-counted offset is a
    defect waiting: it is right on the day it is written and wrong the first
    time anyone edits a comma earlier in the prompt, and the symptom is a
    mangled prompt rather than an exception.

    A phrase that occurs more than once raises. Which one did the author mean?
    Nobody knows, so nobody may guess (`docs/PRODUCT_LOGIC.md`: ambiguous means
    ask, never guess).

    Example:
        >>> locate("a red bench under a full moon", "a full moon")
        (18, 29)
    """
    if not phrase:
        raise TemplateError("cannot locate an empty phrase; a span must select text")
    start = prompt.find(phrase)
    if start < 0:
        raise TemplateError(f"{phrase!r} does not occur in this prompt, so it has no span")
    if prompt.find(phrase, start + 1) >= 0:
        raise TemplateError(
            f"{phrase!r} occurs {prompt.count(phrase)} times in this prompt; a span must "
            "name one place. Extend the phrase until it is unique"
        )
    return (start, start + len(phrase))


def element(
    prompt: str,
    name: str,
    label: str,
    phrase: str,
    alternatives: Iterable[str],
) -> Element:
    """Build one element by MEASURING `phrase` in `prompt`.

    The base phrase is placed first on the allow-list automatically: keeping
    the value the owner proved must always be a legal choice, and writing it
    twice (once as the phrase, once in the list) is the kind of duplicate that
    drifts apart (harness rule Е1).
    """
    allowed = [phrase] + [a for a in alternatives if a != phrase]
    return Element(name=name, label=label, span=locate(prompt, phrase), allowed=tuple(allowed))


# ---------------------------------------------------------------------------
# The catalogue: three prompts, and every span in them MEASURED by `locate`.
# ---------------------------------------------------------------------------

# ВЫБРАНО — the prompts themselves are WRITTEN BY agent A, 2026-08-26, and that
# is a licence decision, not a stylistic one. Ц5, checked before anything was
# embedded:
#
#   `studio/knowledge/gallery_prompts.jsonl` (4,601 rows, MEASURED by `wc -l`,
#   2026-08-26) holds prompt wording harvested from a third party's commercial
#   gallery. `.gitignore` keeps that file out of this repository ON PURPOSE,
#   and the reason is written next to the rule: this repository is public and
#   its LICENCE clause 2(d) claims "the prompts, prompt fragments, directive
#   strings ... contained here" as the substance of the work. Pasting the
#   gallery's sentences into a committed source file would publish somebody
#   else's wording AND drag it under that claim — the exact outcome the ignore
#   rule exists to prevent (see `studio/knowledge/PROVENANCE.md` and
#   `NOTICE_replacement.md`).
#
# So the corpus was read for REGISTER and not for text. Three of its rows were
# used as models for length, comma rhythm, and the habit of naming a light and
# a lens: 000e2e1cad896387, 167b0499bb600934, 0de6b15623ad1dd3. The sentences
# below are this project's own. If the owner decides the literal corpus wording
# should ship here, that is the same kind of explicit decision they took on
# 2026-08-25 about collecting it at all, and it needs the same paperwork.
#
# HONEST STATUS OF EVERY VALUE HERE: nothing below has been generated. These
# are not yet "proven bases" in the sense `docs/PRODUCT_LOGIC.md` means — the
# owner has not run them. The module therefore never claims a calibrated prompt
# is a GOOD prompt; it claims only that the output differs from its base
# exactly where the template said it may, which is a fact about text and needs
# no generation to be true.

_WINTER = (
    "a tailored deep burgundy velvet dinner jacket, folded once and left on a snowy bench "
    "under a full moon, frost creeping along the slats, silver-blue light and long soft "
    "shadows, shot on a 50mm Summilux lens, fine film grain, --ar 3:4 --style raw "
    "--stylize 300 --v 6.1"
)

_APPLIANCE = (
    "product photo of an unbranded washing machine in a bare studio, its door standing "
    "open, various fragrant flowers spilling out across the floor, clean minimal styling, "
    "high detail, shot on a Canon EF 16-35mm f/2.8L III USM lens, soft studio lighting"
)

_ABSTRACT = (
    "close-up of a small abstract object with a granular, sandy texture, built from "
    "crumpled fabric-like layers, muted colours running from dark grey to olive green with "
    "accents of orange, soft, diffused studio lighting raking across the surface, set "
    "against a dark, plain backdrop"
)

CATALOGUE: tuple[PromptTemplate, ...] = (
    PromptTemplate(
        id="winter_jacket_moonlight",
        prompt=_WINTER,
        model="midjourney",
        elements=(
            element(
                _WINTER,
                "subject",
                "What is on the bench",
                "deep burgundy velvet dinner jacket",
                (
                    # This value is on the list ON PURPOSE and it is the trap
                    # the whole module is shaped around: it CONTAINS the light
                    # element's base text "a full moon" verbatim. Substituting
                    # it with `str.replace` and then replacing the light leaves
                    # the sky untouched and rewrites the scarf.
                    "pale grey cashmere scarf shaped like a full moon",
                    "worn brown leather satchel",
                    "folded ivory linen suit",
                ),
            ),
            element(
                _WINTER,
                "surface",
                "What it is draped over",
                "a snowy bench",
                ("a weathered oak bench", "a slab of dark granite", "a drift of fresh snow"),
            ),
            element(
                _WINTER,
                "light",
                "The light source above it",
                "a full moon",
                ("a low winter sun", "a string of paper lanterns", "a single street lamp"),
            ),
            # These two tile the hyphenated colour "silver-blue" with no
            # separator between them, so end(tint_shade) == start(tint_hue).
            # Adjacent spans are where an off-by-one substituter shows itself:
            # one character of slack in either direction and the hyphen is
            # doubled or eaten. Declared deliberately so that case is testable
            # on a real prompt rather than only on a fixture.
            element(
                _WINTER,
                "tint_shade",
                "Light tint, first half (keep the hyphen)",
                "silver-",
                ("amber-", "rose-", "steel-"),
            ),
            element(
                _WINTER,
                "tint_hue",
                "Light tint, second half",
                "blue",
                ("green", "grey", "gold"),
            ),
            element(
                _WINTER,
                "lens",
                "Lens it was shot on",
                "50mm Summilux",
                ("35mm Summicron", "75mm Noctilux", "90mm Elmarit"),
            ),
        ),
    ),
    PromptTemplate(
        id="appliance_studio",
        prompt=_APPLIANCE,
        model="generic",
        elements=(
            element(
                _APPLIANCE,
                "subject",
                "The product",
                "unbranded washing machine",
                ("unbranded espresso machine", "unbranded chest freezer", "unbranded oven"),
            ),
            element(
                _APPLIANCE,
                "spill",
                "What comes out of it",
                "various fragrant flowers",
                ("drifting soap bubbles", "folded white linen", "a spill of ripe citrus"),
            ),
            element(
                _APPLIANCE,
                "light",
                "Studio light",
                "soft studio lighting",
                ("hard directional lighting", "cool overcast daylight", "warm rim lighting"),
            ),
            element(
                _APPLIANCE,
                "lens",
                "Lens it was shot on",
                "Canon EF 16-35mm f/2.8L III USM",
                ("Canon EF 24-70mm f/2.8L II USM", "Canon RF 50mm f/1.2L USM"),
            ),
        ),
    ),
    PromptTemplate(
        id="abstract_object_backdrop",
        prompt=_ABSTRACT,
        model="generic",
        elements=(
            element(
                _ABSTRACT,
                "texture",
                "Surface texture of the object",
                "granular, sandy",
                # "porous volcanic" is here because of the defect this project
                # already paid for once: a user wrote "porous volcanic stone",
                # a synonym map read it as the palette colour "sand", and the
                # generator put literal sand under the bottle
                # (`studio/selfrag/fidelity.py`, OBSERVED 2026-08-26). Under
                # calibration the phrase is a value on a list; nothing reads it.
                ("porous volcanic", "brushed, metallic", "soft, felted"),
            ),
            element(
                _ABSTRACT,
                "light",
                "How it is lit",
                "soft, diffused studio lighting",
                ("hard, raking studio lighting", "low, warm tungsten lighting"),
            ),
            element(
                _ABSTRACT,
                "backdrop",
                "What is behind it",
                "a dark, plain backdrop",
                ("a pale, plain backdrop", "a deep green velvet backdrop"),
            ),
        ),
    ),
)


def catalogue() -> list[dict]:
    """List every prompt template the studio offers, shaped for the UI."""
    return [describe(t) for t in CATALOGUE]


def describe(template: PromptTemplate) -> dict:
    """One template as data: what a human picks from, spans included.

    Spans are exposed rather than hidden because they are what makes the
    invariant checkable; a UI that wants to highlight the calibrated words in
    the prompt needs exactly these numbers.
    """
    return {
        "id": template.id,
        "model": template.model,
        "prompt": template.prompt,
        "elements": [
            {
                "name": el.name,
                "label": el.label,
                "span": list(el.span),
                "current": template.prompt[el.span[0] : el.span[1]],
                "allowed": list(el.allowed),
            }
            for el in template.elements
        ],
    }


def get(template_id: str) -> PromptTemplate | None:
    """Return one template by id, or `None` when the id is not in the catalogue."""
    for template in CATALOGUE:
        if template.id == template_id:
            return template
    return None


# ---------------------------------------------------------------------------
# Verification: the invariant, checked rather than promised.
# ---------------------------------------------------------------------------


def _first_difference(a: str, b: str) -> int:
    """Index of the first character where two strings part, or the shorter length."""
    limit = min(len(a), len(b))
    for i in range(limit):
        if a[i] != b[i]:
            return i
    return limit


def _result(
    outcome: str,
    *,
    checked: int,
    violations: int,
    unmeasured: int,
    note: str,
    **extra: object,
) -> dict:
    """One shape for every return of this module.

    All branches carry the same keys, including the unhappy ones. A judging
    dict whose early returns are missing keys is a `KeyError` waiting on the
    path nobody exercises — that exact defect was found in this repository's
    assembler on 2026-08-26 and is not being reproduced here.
    """
    out: dict = {
        "outcome": outcome,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
        "note": note,
    }
    out.update(extra)
    return out


def verify(
    base: str,
    out: str,
    elements: Sequence[Element],
    applied: Mapping[str, str],
) -> dict:
    """Prove every character of `out` that differs from `base` lies in a calibrated span.

    The walk: for each calibrated span in ascending order, the GAP of base text
    before it must appear byte-identical in the output at the shifted position,
    and the span itself must carry exactly the value that was applied. The
    shift is re-derived here from the lengths of the applied values, not taken
    from `calibrate` — a check that trusts the arithmetic it is checking is not
    a check.

    Three outcomes:

    * `pass` — every gap matched and every span carries its chosen value.
    * `fail` — a character outside a calibrated span moved, or a span does not
      carry what was applied to it.
    * `could not measure` — no base, nothing applied, or a span cannot be
      located for something that was applied. Zero substitutions is never
      `pass`: an unchanged prompt has not been verified, it has been skipped.

    Example:
        >>> els = (Element("a", "A", (0, 3), ("red", "sky")),)
        >>> verify("red bench", "sky bench", els, {"a": "sky"})["outcome"]
        'pass'
        >>> verify("red bench", "sky stool", els, {"a": "sky"})["outcome"]
        'fail'
    """
    if not base:
        return _result(
            UNMEASURED,
            checked=0,
            violations=0,
            unmeasured=1,
            note="no base prompt to diff against",
            first_difference=None,
        )
    if not applied:
        return _result(
            UNMEASURED,
            checked=0,
            violations=0,
            unmeasured=1,
            note=(
                "nothing was calibrated, so nothing was verified. An output that equals "
                "the base is not a checked output"
            ),
            first_difference=None,
        )

    by_name = {el.name: el for el in elements}
    missing = sorted(n for n in applied if n not in by_name)
    if missing:
        return _result(
            UNMEASURED,
            checked=0,
            violations=0,
            unmeasured=len(missing),
            note=(
                f"no span is declared for {', '.join(repr(m) for m in missing)}, so where "
                "those characters were allowed to move is unknown"
            ),
            first_difference=None,
        )

    calibrated = [by_name[name] for name in applied]
    problems = span_problems(base, calibrated)
    if problems:
        return _result(
            UNMEASURED,
            checked=0,
            violations=0,
            unmeasured=len(problems),
            note="the spans themselves are unusable, so the diff proves nothing: "
            + "; ".join(problems),
            first_difference=None,
        )

    ordered = sorted(calibrated, key=lambda e: e.span)
    base_at = 0
    out_at = 0
    gap_chars = 0
    for el in ordered:
        start, end = el.span
        gap = base[base_at:start]
        got = out[out_at : out_at + len(gap)]
        if got != gap:
            where = out_at + _first_difference(gap, got)
            return _result(
                FAIL,
                checked=gap_chars + len(gap),
                violations=1,
                unmeasured=0,
                note=(
                    f"the output differs from the base at character {where}, which is "
                    f"OUTSIDE every calibrated span (the next span is {el.name!r} at "
                    f"{el.span}). Base has {gap[:40]!r}, output has {got[:40]!r}"
                ),
                first_difference=where,
            )
        gap_chars += len(gap)
        out_at += len(gap)

        value = applied[el.name]
        carried = out[out_at : out_at + len(value)]
        if carried != value:
            return _result(
                FAIL,
                checked=gap_chars,
                violations=1,
                unmeasured=0,
                note=(
                    f"the span of {el.name!r} at {el.span} carries {carried[:40]!r} in the "
                    f"output, not the chosen {value[:40]!r}: the substitution landed "
                    "somewhere else"
                ),
                first_difference=out_at,
            )
        base_at = end
        out_at += len(value)

    tail = base[base_at:]
    if out[out_at:] != tail:
        where = out_at + _first_difference(tail, out[out_at:])
        return _result(
            FAIL,
            checked=gap_chars,
            violations=1,
            unmeasured=0,
            note=(
                f"the output differs from the base at character {where}, after the last "
                f"calibrated span: base ends {tail[:40]!r}, output ends {out[out_at:][:40]!r}"
            ),
            first_difference=where,
        )
    gap_chars += len(tail)
    return _result(
        PASS,
        checked=gap_chars,
        violations=0,
        unmeasured=0,
        note=(
            f"{gap_chars} of the base's {len(base)} characters lie outside the "
            f"{len(ordered)} calibrated span(s) and every one of them is byte-identical "
            "in the output"
        ),
        first_difference=None,
    )


# ---------------------------------------------------------------------------
# Calibration.
# ---------------------------------------------------------------------------


def _empty(outcome: str, note: str, prompt: str | None, *, unmeasured: int = 1) -> dict:
    """A result where nothing was substituted. Shared so every key is present."""
    return _result(
        outcome,
        checked=0,
        violations=0 if outcome != FAIL else 1,
        unmeasured=unmeasured if outcome == UNMEASURED else 0,
        note=note,
        prompt=prompt,
        applied={},
        rejected={},
        changed_spans=[],
        verify=None,
    )


def calibrate(template: PromptTemplate | None, choices: Mapping[str, str]) -> dict:
    """Substitute the chosen values into the template's prompt. Three outcomes.

    * `pass` — every requested element exists, every value was allowed, the
      substitution happened, and `verify` agrees nothing else moved.
    * `fail` — a requested element does not exist, a value is not on that
      element's allow-list, the spans are unusable, or `verify` finds a change
      outside a named span. **The untouched base prompt comes back**: the user
      is better off with the template as the owner wrote it than with nothing.
    * `could not measure` — no template, no elements declared, or no choices.

    Returns the judging dict plus `prompt`, `applied`, `rejected` and
    `changed_spans` (ranges in the OUTPUT, already shifted).

    `prompt` is `None` only when there is no base to hand back at all. On
    `fail` it is the base, because the contract says the base comes back, and a
    `None` there would leave the caller holding nothing.

    Rejections are ALL-OR-NOTHING. One bad value refuses the whole request
    rather than substituting the rest: a half-calibrated prompt is a prompt the
    user never asked for, and it would arrive looking exactly like one they
    did.

    Example:
        >>> t = get("winter_jacket_moonlight")
        >>> r = calibrate(t, {"light": "a low winter sun"})
        >>> r["outcome"], r["applied"]
        ('pass', {'light': 'a low winter sun'})
        >>> "a low winter sun" in r["prompt"], "a full moon" in r["prompt"]
        (True, False)
    """
    if template is None:
        return _empty(UNMEASURED, "no template was given, so there is no prompt to calibrate", None)
    base = template.prompt
    if not base.strip():
        return _empty(
            UNMEASURED, f"template {template.id!r} carries no prompt text to calibrate", None
        )

    # Defensive: `__post_init__` already refused a template like this, but a
    # frozen dataclass can be rebuilt past its own constructor, and the
    # contract names overlapping spans as a `fail` of THIS function.
    problems = span_problems(base, template.elements)
    if problems:
        return _result(
            FAIL,
            checked=0,
            violations=len(problems),
            unmeasured=0,
            note=f"template {template.id!r} is broken and nothing was substituted: "
            + "; ".join(problems),
            prompt=base,
            applied={},
            rejected={},
            changed_spans=[],
            verify=None,
        )

    if not template.elements:
        return _empty(
            UNMEASURED,
            f"template {template.id!r} declares no calibratable elements: there is nothing "
            "the user is permitted to change here",
            base,
        )
    if not choices:
        return _empty(
            UNMEASURED,
            "no choices were given, so nothing was substituted and nothing was checked. "
            "The owner's prompt is returned exactly as written",
            base,
        )

    by_name = {el.name: el for el in template.elements}
    applied: dict[str, str] = {}
    rejected: dict[str, str] = {}
    for name, value in choices.items():
        el = by_name.get(name)
        if el is None:
            rejected[name] = (
                f"template {template.id!r} declares no element named {name!r}; it declares "
                f"{', '.join(repr(n) for n in by_name)}. Nothing may be ADDED to a prompt "
                "here, only substituted"
            )
        elif not isinstance(value, str) or not value:
            rejected[name] = f"the value for {name!r} is empty; a span must carry text"
        elif value not in el.allowed:
            rejected[name] = (
                f"{value!r} is not one of the values this template's author permits for "
                f"{name!r}: {', '.join(repr(a) for a in el.allowed)}"
            )
        else:
            applied[name] = value

    if rejected:
        return _result(
            FAIL,
            checked=len(choices),
            violations=len(rejected),
            unmeasured=0,
            note=(
                f"{len(rejected)} of {len(choices)} choice(s) were refused, so NONE were "
                "substituted and the owner's prompt is returned untouched: "
                + "; ".join(f"{k}: {v}" for k, v in rejected.items())
            ),
            prompt=base,
            applied={},
            rejected=rejected,
            changed_spans=[],
            verify=None,
        )

    # RIGHT-TO-LEFT. Every span still to be written lies entirely to the left
    # of the one just written, so its measured offsets are still exact. Going
    # the other way, each substitution shifts every later span by its own
    # length delta and the next write lands off the mark — silently, because
    # the result is still a plausible-looking prompt.
    ordered = sorted(applied, key=lambda n: by_name[n].span[0], reverse=True)
    out = base
    for name in ordered:
        start, end = by_name[name].span
        out = out[:start] + applied[name] + out[end:]

    # The same spans as they land in the OUTPUT, carrying the running shift.
    changed_spans: list[tuple[int, int]] = []
    shift = 0
    for name in reversed(ordered):
        start, end = by_name[name].span
        value = applied[name]
        out_start = start + shift
        changed_spans.append((out_start, out_start + len(value)))
        shift += len(value) - (end - start)

    checked = verify(base, out, template.elements, applied)
    if checked["outcome"] == FAIL:
        return _result(
            FAIL,
            checked=len(applied),
            violations=1,
            unmeasured=0,
            note=(
                "the substitution changed something outside a calibrated span, so it was "
                "thrown away and the owner's prompt is returned untouched: " + str(checked["note"])
            ),
            prompt=base,
            applied={},
            rejected={},
            changed_spans=[],
            verify=checked,
        )
    if checked["outcome"] != PASS:
        return _result(
            UNMEASURED,
            checked=len(applied),
            violations=0,
            unmeasured=1,
            note=(
                "the substitution could not be verified, so it was not shipped and the "
                "owner's prompt is returned untouched: " + str(checked["note"])
            ),
            prompt=base,
            applied={},
            rejected={},
            changed_spans=[],
            verify=checked,
        )

    return _result(
        PASS,
        checked=len(applied),
        violations=0,
        unmeasured=0,
        note=(
            f"{len(applied)} of {len(template.elements)} element(s) calibrated; "
            + str(checked["note"])
        ),
        prompt=out,
        applied=applied,
        rejected={},
        changed_spans=changed_spans,
        verify=checked,
    )
