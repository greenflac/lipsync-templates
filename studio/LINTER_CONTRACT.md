# Contract for the template linter — read before writing any of it

Parallel agents share this EXACTLY. The product logic is `docs/PRODUCT_LOGIC.md`.

## Who this is for

The OWNER writes the templates by hand. This tool is for them, before a
template ships. It answers one question: **will every value this template
permits still read correctly once it is substituted in?**

It is not a quality judge. It cannot say a prompt is good. It catches
mechanical damage a human author makes and does not notice.

## Why it exists — the defect that motivated it, MEASURED 2026-08-26

    base:   a tailored {subject}, folded once and left on a snowy bench
    value:  "folded ivory linen suit"
    result: a tailored FOLDED ivory linen suit, FOLDED once and left ...

The substituter is correct — the change stays inside the span — and the
sentence reads badly. Nothing in the system checks that a value fits the
grammar it lands in.

**The discipline that makes this a tool and not noise:** sweeping all 42
value/element combinations of the shipped catalogue found 12 word repetitions,
and **10 of them were words already repeated in the base**, present whatever
the user picks. A check that does not subtract what the base already does
reports 6 lies for every truth. Every check here compares the calibrated
prompt against the BASE, and reports only what substitution introduced.

## The signature

```python
# studio/template_lint.py                OWNER: agent A. Nobody else writes it.

@dataclass(frozen=True)
class Finding:
    check: str        # "repetition", "article", "seam", "duplicate_value", ...
    severity: str     # SEVERITY_VIOLATION | SEVERITY_RISK
    element: str      # which element
    value: str        # which allowed value provokes it
    message: str      # what a human should do about it

def lint(template: PromptTemplate) -> dict: ...
def lint_catalogue(templates: Sequence[PromptTemplate] = CATALOGUE) -> dict: ...
```

Return the studio judging dict plus `findings: list[Finding]` and
`combinations: int` — how many element/value pairs were actually rendered.
Import `SEVERITY_VIOLATION` / `SEVERITY_RISK` from `studio.selfrag.reflect`;
do not re-declare them.

## The checks, and each one only fires on what substitution INTRODUCED

1. **repetition** — a content word appears twice within a window in the
   calibrated prompt, and not in the base. VIOLATION.
2. **article** — `a` before a vowel-initial word, or `an` before a consonant,
   created by the substitution. VIOLATION.
3. **seam** — doubled commas, doubled spaces, space before a comma, or a
   missing separator at a span edge, created by the substitution. VIOLATION.
4. **duplicate_value** — the same value listed twice in one element's
   `allowed`. RISK.
5. **identity_only** — an element whose `allowed` has one entry, so nothing can
   be calibrated. RISK.
6. **cross_element** — a value that contains the base text of ANOTHER element.
   RISK: it is legal and the substituter handles it, but the author probably
   did not mean the same words to appear twice.

Every window, threshold or word list is a constant carrying ИЗМЕРЕНО / РАСЧЁТ /
ВЫБРАНО. The repetition window in particular: a window of 3 words MISSED the
motivating defect, which sits 4 words apart (OBSERVED 2026-08-26). State the
chosen value and what it was checked against.

## The three outcomes

- `pass` — every combination rendered, no VIOLATION found.
- `fail` — at least one VIOLATION.
- `could not measure` — no template, no elements, or no allowed values, so
  nothing could be rendered. **`combinations == 0` is never `pass`.**

RISK findings are reported and do NOT change a `pass`.

## Rules that hold

- No network, no model, no paid call.
- `lipsync/**` is frozen; `studio/prompt_templates.py` belongs to someone else
  — read it, do not edit it.
- A CLI so the owner can run it: `python -m studio.template_lint`, exit 0 pass,
  1 fail, 2 could not measure.
- English module, comments explain WHY.

## The control set — OWNER: agent B, who must NOT read template_lint.py

`studio/fixtures/lint_control_set.py` — templates built to the
`PromptTemplate`/`Element` shape, with spans located by `str.find`, never typed.

Two halves, and BOTH are required:

**Planted defects.** At least two templates per check above, each planting
exactly one defect, with the expected `check` name and the element/value that
should be blamed. A linter that misses a planted defect is broken.

**Clean templates.** At least four templates that are correct, where the linter
must report NOTHING. A linter that flags everything is as useless as one that
flags nothing, and this half is the one people forget.

Include the hardest case explicitly: **a template whose BASE already repeats a
word**, where no value makes it worse. The linter must stay silent — that is
the 10-lies-in-12 case that motivated the whole subtraction rule.
