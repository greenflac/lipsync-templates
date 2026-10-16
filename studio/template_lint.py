"""Lint a prompt template against every value it permits, BEFORE it ships.

OWNER: agent A. Nobody else writes this file (`studio/CONTRACTS.md`, Ц2).

The question this answers is narrow and mechanical, and stating it narrowly is
what keeps it useful: **will every value this template permits still read
correctly once it is substituted in?** It is not a quality judge. It cannot say
a prompt is good. It catches damage a human author makes and does not notice.

THE DEFECT THAT MOTIVATED IT (MEASURED 2026-08-26, `studio/LINTER_CONTRACT.md`):

    base:   a tailored {subject}, folded once and left on a snowy bench
    value:  "folded ivory linen suit"
    result: a tailored FOLDED ivory linen suit, FOLDED once and left ...

The substituter is correct — every changed character stays inside the named
span — and the sentence still reads badly. Nothing else in the system looks at
the grammar a value lands in.

WHY EVERY CHECK SUBTRACTS THE BASE, AND WHY THAT IS ONE CODE PATH

A word repeated in the calibrated prompt is only news if the substitution put
it there. A word the BASE already repeats is present whatever the user picks,
so reporting it tells the author nothing they can act on and buries the one
finding that matters.

MEASURED on the shipped catalogue, 2026-08-26, 49 rendered element/value pairs,
with the repetition detector run WITHOUT its stop-word filter (the coarse
detector, kept here only as the measurement):

    raw repetitions found ............ 34
    still there after subtraction .....  2
    suppressed as already-in-base .... 32

Sixteen lies per truth. So the subtraction is not a courtesy each check pays
when it remembers: `_introduced` is the ONLY place a finding can be born, every
text check is a row in `_TEXT_CHECKS`, and the single loop in
`_lint_combination` is the single call site. A new check physically cannot skip
it without editing that loop.

The structural checks (`duplicate_value`, `identity_only`, `cross_element`)
have nothing to subtract and say so at their own definitions: they read the
template's DECLARATION, not a rendered prompt.

THREE OUTCOMES, AND THE THIRD IS WHY THE COUNTERS EXIST

`pass` needs combinations > 0. A template that rendered nothing has not been
cleared, it has been skipped (`studio/LINTER_CONTRACT.md`; harness Р1/Р2).

No network, no model, no paid call. `studio/prompt_templates.py` is read here
and never edited.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Callable, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.prompt_templates import CATALOGUE, Element, PromptTemplate, calibrate
from studio.selfrag.reflect import SEVERITY_RISK, SEVERITY_VIOLATION

__all__ = [
    "ARTICLE_ACRONYM_MIN_LETTERS",
    "CHECK_ARTICLE",
    "CHECK_CROSS_ELEMENT",
    "CHECK_DUPLICATE_VALUE",
    "CHECK_IDENTITY_ONLY",
    "CHECK_REPETITION",
    "CHECK_SEAM",
    "CROSS_ELEMENT_MIN_CHARS",
    "REPETITION_MIN_WORD_LETTERS",
    "REPETITION_WINDOW_WORDS",
    "Finding",
    "lint",
    "lint_catalogue",
    "main",
]

# --------------------------------------------------------------------------
# Check names. Held as constants because three files spell them (this one, the
# tests, agent B's control set) and a drifting string literal is the defect
# harness rule Е1 is about.
# --------------------------------------------------------------------------

CHECK_REPETITION = "repetition"
CHECK_ARTICLE = "article"
CHECK_SEAM = "seam"
CHECK_DUPLICATE_VALUE = "duplicate_value"
CHECK_IDENTITY_ONLY = "identity_only"
CHECK_CROSS_ELEMENT = "cross_element"

# --------------------------------------------------------------------------
# Constants, each carrying where its value came from (harness rule И4).
# --------------------------------------------------------------------------

# ИЗМЕРЕНО by agent A, 2026-08-26, on the shipped `CATALOGUE` (49 rendered
# element/value pairs). Two occurrences of a word are a repetition when their
# token indices differ by at most this much; distance is counted over ALL
# words, function words included, because that is how the motivating defect was
# described ("4 words apart": folded, ivory, linen, suit, folded).
#
#     window  introduced findings on the shipped catalogue
#        3      1   <- MISSES the motivating "folded" defect. The contract
#                     records this as OBSERVED 2026-08-26; reproduced here.
#        4      2   <- the motivating defect appears exactly at the boundary
#        5      2
#        6      2
#        8      2   <- the top of the flat plateau: still exactly the two real
#                     defects, so every word of reach up to here is FREE
#       12      4   <- starts reporting "a full moon ... a full moon" 13 words
#                     apart, which is a deliberate value on this catalogue's
#                     allow-list and reads as an echo, not as damage
#
# The plateau is flat from 4 to 8 and the cost of reach only appears past it,
# so the value is taken at the TOP of the plateau rather than at the point that
# just barely caught the known defect.
#
# REVISED from 5 to 8, 2026-08-26, and the reason is worth keeping because it
# is an instance of harness rule И1 (the verdict does not come from the doer):
# agent B, writing `studio/fixtures/lint_control_set.py` WITHOUT reading this
# file, planted "a folded paper lantern set down on a folded linen cloth" —
# a real defect of exactly this kind, 7 words apart. A window of 5 was blind to
# it and passed the template. The measurement above says 7 and 8 cost nothing
# on the shipped catalogue, so the narrower value was reach thrown away for
# nothing. A window tuned to exactly one known defect is a window fitted to its
# own example.
REPETITION_WINDOW_WORDS = 8

# ВЫБРАНО by agent A, 2026-08-26. Words shorter than this are noise from
# technical strings rather than content: "50mm" and "f/2.8L III USM" tokenise
# to mm, f, l, iii, usm, and "mm" repeating across two lens phrases is not a
# defect an author can fix. Three letters keeps "usm" and "iii"; those live
# inside a single lens span and cannot repeat across a substitution.
REPETITION_MIN_WORD_LETTERS = 3

# ВЫБРАНО by agent A, 2026-08-26, from the shipped catalogue's own prose. A
# function word repeating inside five words ("a ... a", "on ... on") is how
# English works, not a defect. This list is deliberately SHORT: every word on
# it is a repetition the linter can never report again, so a long list is a
# blind spot bought cheaply. `_test_stop_words_do_not_hide_a_content_word`
# guards the boundary.
REPETITION_STOP_WORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "from",
        "for", "by", "with", "into", "onto", "over", "under", "across",
        "along", "against", "off", "out", "up", "is", "it", "its", "as",
        "that", "this", "then", "once", "shot",
    }
)  # fmt: skip

# ВЫБРАНО by agent A, 2026-08-26. Spelled as vowels but pronounced with a
# consonant onset, so they take "a". Written as an explicit WORD list and not
# as prefixes on purpose: a "uni" prefix rule would misjudge "an unimaginable
# shape", which is correct English. A miss here is silence; a prefix rule here
# is a wrong accusation, and the two are not equally cheap.
ARTICLE_TAKES_A_DESPITE_VOWEL = frozenset(
    {
        "one", "once", "uniform", "uniformed", "unique", "unicorn", "unified",
        "union", "unit", "united", "universal", "universe", "university",
        "usual", "usually", "usable", "useful", "user", "used", "utensil",
        "utility", "euro", "european", "eucalyptus", "ewe", "ukulele",
        "uranium", "utopia", "utopian",
    }
)  # fmt: skip

# ВЫБРАНО by agent A, 2026-08-26. Spelled with a consonant, pronounced with a
# vowel onset, so they take "an". "herb" is deliberately ABSENT: it is "an
# herb" in American English and "a herb" in British, and a rule that cannot be
# right for both readers should not fire at all.
ARTICLE_TAKES_AN_DESPITE_CONSONANT = frozenset(
    {
        "hour", "hours", "hourly", "honest", "honestly", "honesty", "honour",
        "honours", "honourable", "honor", "honors", "honorable", "heir",
        "heirs", "heirloom",
    }
)  # fmt: skip

# ВЫБРАНО by agent A, 2026-08-26. An all-capital run of at least this many
# letters is read as an acronym, spelled out letter by letter ("a USM lens",
# because it is said "a you-ess-em"), and the article rule cannot judge it from
# spelling. It is skipped rather than guessed. Known blind spot, reported.
ARTICLE_ACRONYM_MIN_LETTERS = 2

# ВЫБРАНО by agent A, 2026-08-26. `cross_element` compares a value against
# another element's base text; below this length that text is a fragment like
# "a" or "-" and every value would "contain" it. Four characters keeps the
# catalogue's shortest real element base, "blue" (element `tint_hue`), which is
# exactly the kind of word an author would not expect to see twice.
CROSS_ELEMENT_MIN_CHARS = 4

# --------------------------------------------------------------------------
# The finding.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One thing a check noticed, and what a human should do about it.

    Exactly the five fields `studio/LINTER_CONTRACT.md` names, and no more:
    another agent is writing tests against this shape without reading this
    file, so a convenience field here would be a contract break there. The
    template id travels in `message` for the same reason.
    """

    check: str
    severity: str
    element: str
    value: str
    message: str


# A signal is a comparable key for "this text does this thing HERE". Two texts
# produce two sets of them and the difference is what substitution introduced.
# It is a tuple rather than a string so a key can never collide by accident
# with a message a check happens to build.
Signal = tuple[str, ...]

# Where the calibrated spans are in a piece of text: (element name, start, end).
# The seam check needs them; the others take them and ignore them, because one
# detector signature means one loop, and one loop means one subtraction.
Edges = tuple[tuple[str, int, int], ...]

Detector = Callable[[str, Edges], set[Signal]]


def _introduced(base: set[Signal], calibrated: set[Signal]) -> list[Signal]:
    """Signals the substitution ADDED. The only door a finding can come through.

    Set difference and not a count difference, deliberately. A base that
    repeats "folded" once and a calibrated prompt that repeats it twice is
    still, to an author, the same known fact about their base; counting would
    turn it into a new accusation they cannot act on. Under-reporting here is
    the cheap failure and over-reporting is the expensive one — that is the
    whole lesson of the 34-vs-2 measurement in this module's docstring.

    Example:
        >>> _introduced({("x", "a")}, {("x", "a"), ("x", "b")})
        [('x', 'b')]
    """
    return sorted(calibrated - base)


# --------------------------------------------------------------------------
# Detectors. Each maps text -> the set of things wrong WITH THAT TEXT ALONE.
# None of them knows about a base; subtraction happens above them.
# --------------------------------------------------------------------------

_WORD = re.compile(r"[a-z]+")

# Split on the hyphen too: "silver-blue" is two words to a reader, and the
# catalogue calibrates its two halves as separate elements.
_ARTICLE = re.compile(r"\b(an?)\s+([A-Za-z][A-Za-z'’-]*)")

# A compound splits at its hyphen or apostrophe: only the first sound decides
# which article the phrase takes.
_SEGMENT = re.compile(r"[-'’]")


def _detect_repetition(text: str, edges: Edges) -> set[Signal]:
    """Content words occurring twice within `REPETITION_WINDOW_WORDS` tokens."""
    words = _WORD.findall(text.lower())
    found: set[Signal] = set()
    for i, word in enumerate(words):
        if word in REPETITION_STOP_WORDS or len(word) < REPETITION_MIN_WORD_LETTERS:
            continue
        upper = min(i + REPETITION_WINDOW_WORDS + 1, len(words))
        for j in range(i + 1, upper):
            if words[j] == word:
                found.add((CHECK_REPETITION, word))
                break
    return found


def _wants_an(word: str) -> bool | None:
    """Should this word take "an"? `None` when spelling cannot decide.

    The exception lists are looked up on the word's FIRST segment, because only
    the first sound matters and English writes compounds with a hyphen: "a
    one-piece steel lamp" is right for the same reason "a one" is, and a lookup
    on the whole token would have missed it. OBSERVED 2026-08-26 by mutating
    "one" out of the list and watching nothing go red — the exception lists
    were never being reached by any hyphenated word.

    Example:
        >>> _wants_an("one-piece"), _wants_an("ivory"), _wants_an("USB")
        (False, True, None)
    """
    if len(word) >= ARTICLE_ACRONYM_MIN_LETTERS and word.isupper():
        return None  # acronym: said letter by letter, not readable from spelling
    head = _SEGMENT.split(word.lower())[0]
    if head in ARTICLE_TAKES_AN_DESPITE_CONSONANT:
        return True
    if head in ARTICLE_TAKES_A_DESPITE_VOWEL:
        return False
    return head[:1] in {"a", "e", "i", "o", "u"}


def _detect_article(text: str, edges: Edges) -> set[Signal]:
    """ "a" before a vowel sound, or "an" before a consonant sound."""
    found: set[Signal] = set()
    for match in _ARTICLE.finditer(text):
        article, word = match.group(1).lower(), match.group(2)
        wants_an = _wants_an(word)
        if wants_an is None:
            continue
        if (article == "an") != wants_an:
            found.add((CHECK_ARTICLE, article, word.lower()))
    return found


_SEAM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("doubled comma", re.compile(r",[ \t]*,")),
    ("doubled space", re.compile(r"[ \t]{2,}")),
    # A non-comma before the space keeps this from firing a second time on the
    # ", ," that "doubled comma" already reported. One defect, one finding.
    ("space before a comma", re.compile(r"[^,\s][ \t]+,")),
)


def _context(text: str, start: int, end: int) -> tuple[str, str]:
    """The nearest word on each side of a span, lower-cased, for a signal key.

    A seam signal keyed on its KIND alone would let a doubled space introduced
    at the end of a prompt hide behind a doubled space the base already had at
    the front. Keying on the neighbouring words makes each seam its own fact.
    """
    before = _WORD.findall(text[:start].lower())
    after = _WORD.findall(text[end:].lower())
    return (before[-1] if before else "^", after[0] if after else "$")


def _detect_seam(text: str, edges: Edges) -> set[Signal]:
    """Punctuation and spacing damage, plus a span edge that glued two words."""
    found: set[Signal] = set()
    for kind, pattern in _SEAM_PATTERNS:
        for match in pattern.finditer(text):
            left, right = _context(text, match.start(), match.end())
            found.add((CHECK_SEAM, kind, left, right))

    # The missing separator: an author's span that starts or ends one character
    # inside the neighbouring word, so the value arrives welded to it
    # ("...tailoredfolded ivory..."). Only visible at the edges, which is why
    # detectors are handed them.
    for name, start, end in edges:
        if 0 < start < len(text) and text[start - 1].isalnum() and text[start].isalnum():
            found.add((CHECK_SEAM, "missing separator", name, "start"))
        if 0 < end < len(text) and text[end - 1].isalnum() and text[end].isalnum():
            found.add((CHECK_SEAM, "missing separator", name, "end"))
    return found


@dataclass(frozen=True)
class _TextCheck:
    """One check that reads a rendered prompt. Severity lives with the check."""

    name: str
    severity: str
    detect: Detector
    explain: Callable[[Signal], str]


def _explain_repetition(signal: Signal) -> str:
    word = signal[1]
    return (
        f"the word {word!r} now appears twice within {REPETITION_WINDOW_WORDS} words, "
        "and does not in the base. Reword the value, or move the element"
    )


def _explain_article(signal: Signal) -> str:
    article, word = signal[1], signal[2]
    wanted = "an" if article == "a" else "a"
    return (
        f"{article!r} lands before {word!r}, which reads as {wanted!r} {word}. The article "
        "is outside the calibrated span, so no value can fix it: move the span to include "
        "the article, or drop this value"
    )


def _explain_seam(signal: Signal) -> str:
    kind = signal[1]
    if kind == "missing separator":
        name, edge = signal[2], signal[3]
        return (
            f"missing separator: the {edge} edge of element {name!r} welds the value to the "
            f"neighbouring word. The span is one character short at the {edge}"
        )
    left, right = signal[2], signal[3]
    return f"{kind} introduced between {left!r} and {right!r}; the base does not have it"


# The whole table. A check that is not in here does not run, and a check that
# IS in here cannot bypass `_introduced` — `_lint_combination` is its only
# caller and it subtracts before it builds anything.
_TEXT_CHECKS: tuple[_TextCheck, ...] = (
    _TextCheck(CHECK_REPETITION, SEVERITY_VIOLATION, _detect_repetition, _explain_repetition),
    _TextCheck(CHECK_ARTICLE, SEVERITY_VIOLATION, _detect_article, _explain_article),
    _TextCheck(CHECK_SEAM, SEVERITY_VIOLATION, _detect_seam, _explain_seam),
)


# --------------------------------------------------------------------------
# Running the text checks over one rendered combination.
# --------------------------------------------------------------------------


def _base_edges(template: PromptTemplate) -> Edges:
    """Every declared span, as the base itself carries them."""
    return tuple((el.name, el.span[0], el.span[1]) for el in template.elements)


def _lint_combination(
    base: str,
    base_edges: Edges,
    rendered: str,
    rendered_edges: Edges,
    element_name: str,
    value: str,
) -> list[Finding]:
    """Every text check, on one substituted prompt, subtracted against the base.

    THE ONE LOOP. Both texts go through the same detector, and only the
    difference becomes a `Finding`. Nothing else in this module builds a text
    finding, so no check can be written that forgets the base.
    """
    findings: list[Finding] = []
    for check in _TEXT_CHECKS:
        before = check.detect(base, base_edges)
        after = check.detect(rendered, rendered_edges)
        for signal in _introduced(before, after):
            findings.append(
                Finding(
                    check=check.name,
                    severity=check.severity,
                    element=element_name,
                    value=value,
                    message=check.explain(signal),
                )
            )
    return findings


# --------------------------------------------------------------------------
# The structural checks: they read the DECLARATION, not a rendered prompt.
# There is nothing to subtract, and saying so is the point of this comment —
# `duplicate_value` and `identity_only` are facts about the allow-list, true
# before any substitution happens. `cross_element` subtracts the one case that
# is not introduced: a value that is simply the base text back again.
# --------------------------------------------------------------------------


def _check_duplicate_value(element: Element) -> list[Finding]:
    """The same value listed twice in one element's `allowed`. RISK."""
    findings: list[Finding] = []
    seen: set[str] = set()
    reported: set[str] = set()
    for value in element.allowed:
        if value in seen and value not in reported:
            reported.add(value)
            findings.append(
                Finding(
                    check=CHECK_DUPLICATE_VALUE,
                    severity=SEVERITY_RISK,
                    element=element.name,
                    value=value,
                    message=(
                        f"{value!r} is listed {element.allowed.count(value)} times for "
                        f"{element.name!r}. The UI will show it twice and the second one "
                        "does nothing"
                    ),
                )
            )
        seen.add(value)
    return findings


def _check_identity_only(element: Element) -> list[Finding]:
    """An element with one allowed value: a knob that cannot turn. RISK."""
    if len(element.allowed) != 1:
        return []
    return [
        Finding(
            check=CHECK_IDENTITY_ONLY,
            severity=SEVERITY_RISK,
            element=element.name,
            value=element.allowed[0],
            message=(
                f"{element.name!r} permits only {element.allowed[0]!r}, which is the text "
                "already there. Nothing can be calibrated: give it alternatives or stop "
                "showing it as a choice"
            ),
        )
    ]


def _check_cross_element(template: PromptTemplate, element: Element, value: str) -> list[Finding]:
    """A value carrying another element's base text verbatim. RISK, not a fault.

    Legal, and the substituter handles it correctly by construction — spans
    name one place, so the copy inside the value is never mistaken for the
    other element (`studio/prompt_templates.py` documents that trap). The
    author still probably did not mean the same words to appear twice.

    The subtraction: a value that IS the element's own base text changes
    nothing, so it can introduce nothing.
    """
    base_text = template.prompt[element.span[0] : element.span[1]]
    if value == base_text:
        return []
    findings: list[Finding] = []
    lowered = value.lower()
    for other in template.elements:
        if other.name == element.name:
            continue
        other_text = template.prompt[other.span[0] : other.span[1]]
        if len(other_text) < CROSS_ELEMENT_MIN_CHARS:
            continue
        if other_text.lower() in lowered:
            findings.append(
                Finding(
                    check=CHECK_CROSS_ELEMENT,
                    severity=SEVERITY_RISK,
                    element=element.name,
                    value=value,
                    message=(
                        f"this value contains {other_text!r}, which is the base text of "
                        f"element {other.name!r}. The substitution is still correct, but the "
                        "phrase will appear twice in the prompt"
                    ),
                )
            )
    return findings


# --------------------------------------------------------------------------
# The public surface.
# --------------------------------------------------------------------------


def _result(
    outcome: str,
    *,
    checked: int,
    violations: int,
    unmeasured: int,
    note: str,
    findings: Sequence[Finding],
    combinations: int,
    **extra: object,
) -> dict:
    """One shape for every return, unhappy branches included.

    Same reason as `studio/prompt_templates._result`: a judging dict whose
    early returns are missing keys is a `KeyError` waiting on the path nobody
    exercises.
    """
    out: dict = {
        "outcome": outcome,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
        "note": note,
        "findings": list(findings),
        "combinations": combinations,
        "risks": sum(1 for f in findings if f.severity == SEVERITY_RISK),
    }
    out.update(extra)
    return out


def _verdict(violations: int, unmeasured: int, combinations: int) -> str:
    """The three outcomes, in the one place they are decided.

    Order matters and is the contract's: nothing rendered is never `pass`; a
    violation outranks an unmeasured pair, because a defect that WAS seen does
    not become less true when another pair could not be rendered.
    """
    if combinations == 0:
        return UNMEASURED
    if violations:
        return FAIL
    if unmeasured:
        return UNMEASURED
    return PASS


def lint(template: PromptTemplate | None) -> dict:
    """Render every value this template permits and report what substitution broke.

    Three outcomes:

    * `pass` — at least one combination rendered and no VIOLATION was found.
      RISK findings are reported and do not change it.
    * `fail` — at least one VIOLATION.
    * `could not measure` — no template, no elements, no allowed values, or a
      combination the substituter refused. **`combinations == 0` is never
      `pass`**: a template that rendered nothing has been skipped, not cleared.

    :returns: the studio judging dict plus `findings: list[Finding]` and
        `combinations: int` — element/value pairs actually rendered.

    Example:
        >>> from studio.prompt_templates import get
        >>> report = lint(get("winter_jacket_moonlight"))
        >>> report["outcome"], report["combinations"]
        ('fail', 24)
    """
    if template is None:
        return _result(
            UNMEASURED,
            checked=0,
            violations=0,
            unmeasured=1,
            note="no template was given, so nothing could be rendered or checked",
            findings=[],
            combinations=0,
            template=None,
        )
    if not template.elements:
        return _result(
            UNMEASURED,
            checked=0,
            violations=0,
            unmeasured=1,
            note=(
                f"template {template.id!r} declares no calibratable elements: there is no "
                "substitution to lint, which is not the same as a template that is clean"
            ),
            findings=[],
            combinations=0,
            template=template.id,
        )

    base = template.prompt
    base_edges = _base_edges(template)
    findings: list[Finding] = []
    combinations = 0
    checked = 0
    unrendered = 0
    refusals: list[str] = []

    for element in template.elements:
        # `Element.__post_init__` already refuses an empty allow-list, but a
        # frozen dataclass can be rebuilt past its own constructor, and an
        # element nobody can calibrate must reach the third outcome, not slip
        # through as a clean pass.
        if not element.allowed:
            unrendered += 1
            refusals.append(f"{element.name!r} permits no values, so nothing was rendered for it")
            continue

        checked += 2  # duplicate_value and identity_only, once per element
        findings.extend(_check_duplicate_value(element))
        findings.extend(_check_identity_only(element))

        for value in element.allowed:
            checked += 1  # cross_element, once per value
            findings.extend(_check_cross_element(template, element, value))

            result = calibrate(template, {element.name: value})
            if result["outcome"] != PASS:
                unrendered += 1
                refusals.append(f"{element.name}={value!r}: {result['note']}")
                continue
            combinations += 1
            checked += len(_TEXT_CHECKS)
            rendered_edges = tuple(
                (element.name, start, end) for start, end in result["changed_spans"]
            )
            findings.extend(
                _lint_combination(
                    base,
                    base_edges,
                    str(result["prompt"]),
                    rendered_edges,
                    element.name,
                    value,
                )
            )

    violations = [f for f in findings if f.severity == SEVERITY_VIOLATION]
    risks = [f for f in findings if f.severity == SEVERITY_RISK]
    outcome = _verdict(len(violations), unrendered, combinations)

    if combinations == 0:
        note = (
            f"template {template.id!r}: no element/value pair could be rendered, so no check "
            "ran. " + "; ".join(refusals)
        )
    else:
        note = (
            f"template {template.id!r}: {combinations} combination(s) rendered, "
            f"{checked} check(s) run, {len(violations)} violation(s), {len(risks)} risk(s), "
            f"{unrendered} pair(s) could not be rendered"
        )
        if violations:
            note += ". " + "; ".join(
                f"{f.check} [{f.element}={f.value!r}] {f.message}" for f in violations
            )
        if refusals:
            note += ". Not rendered: " + "; ".join(refusals)

    return _result(
        outcome,
        checked=checked,
        violations=len(violations),
        unmeasured=unrendered,
        note=note,
        findings=findings,
        combinations=combinations,
        template=template.id,
    )


def lint_catalogue(templates: Sequence[PromptTemplate] = CATALOGUE) -> dict:
    """Lint every template. Same three outcomes, summed.

    Per-template reports are kept under `templates`, keyed by id. The flat
    `findings` list prefixes each message with its template id, because
    `Finding` carries exactly the five fields the contract names and adding a
    sixth would break a test written against that contract by someone who has
    not read this file.

    Example:
        >>> lint_catalogue([])["outcome"]
        'could not measure'
    """
    if not templates:
        return _result(
            UNMEASURED,
            checked=0,
            violations=0,
            unmeasured=1,
            note="no templates were given, so nothing was linted",
            findings=[],
            combinations=0,
            templates={},
        )

    reports: dict[str, dict] = {}
    findings: list[Finding] = []
    checked = combinations = violations = unmeasured = 0
    for template in templates:
        report = lint(template)
        reports[template.id] = report
        checked += int(report["checked"])
        combinations += int(report["combinations"])
        violations += int(report["violations"])
        unmeasured += int(report["unmeasured"])
        for finding in report["findings"]:
            findings.append(
                Finding(
                    check=finding.check,
                    severity=finding.severity,
                    element=finding.element,
                    value=finding.value,
                    message=f"{template.id}: {finding.message}",
                )
            )

    outcome = _verdict(violations, unmeasured, combinations)
    note = (
        f"{len(templates)} template(s), {combinations} combination(s) rendered, "
        f"{checked} check(s) run, {violations} violation(s), "
        f"{sum(1 for f in findings if f.severity == SEVERITY_RISK)} risk(s), "
        f"{unmeasured} pair(s) could not be rendered"
    )
    return _result(
        outcome,
        checked=checked,
        violations=violations,
        unmeasured=unmeasured,
        note=note,
        findings=findings,
        combinations=combinations,
        templates=reports,
    )


# --------------------------------------------------------------------------
# CLI: the owner runs this before a template ships.
# --------------------------------------------------------------------------

_EXIT = {PASS: 0, FAIL: 1, UNMEASURED: 2}


def _render(report: dict) -> str:
    """The report a human reads. Counts first, because Р2 says so."""
    lines = [
        f"outcome: {report['outcome']}",
        (
            f"rendered {report['combinations']} combination(s), ran {report['checked']} check(s), "
            f"{report['violations']} violation(s), {report['risks']} risk(s), "
            f"{report['unmeasured']} could not be measured"
        ),
    ]
    for finding in report["findings"]:
        lines.append(
            f"  [{finding.severity}] {finding.check} {finding.element}="
            f"{finding.value!r}: {finding.message}"
        )
    lines.append(str(report["note"]))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m studio.template_lint [template_id ...]`. 0 pass, 1 fail, 2 unmeasured.

    The exit code carries the third outcome as its own value. Collapsing "could
    not measure" into either 0 or 1 is the mistake this repository has paid for
    in five separate places (harness rule Р1).
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        wanted = {t.id: t for t in CATALOGUE}
        missing = [a for a in args if a not in wanted]
        if missing:
            print(
                f"no template with id {', '.join(repr(m) for m in missing)}; the catalogue has "
                f"{', '.join(repr(t) for t in wanted)}",
                file=sys.stderr,
            )
            return _EXIT[UNMEASURED]
        chosen: Sequence[PromptTemplate] = [wanted[a] for a in args]
    else:
        chosen = CATALOGUE
    report = lint_catalogue(chosen)
    print(_render(report))
    return _EXIT[str(report["outcome"])]


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI test via main()
    raise SystemExit(main())
