# Contract for prompt calibration — read before writing any of it

Parallel agents share this EXACTLY. Copy names verbatim; do not invent synonyms.
The product logic behind it is `docs/PRODUCT_LOGIC.md`, settled 2026-08-26.

## What is being built

The user picks a template. The template carries a prompt the owner wrote by
hand and knows works. The user changes only the elements that template declares
changeable, choosing only from values that template lists.

    template (owner's prompt) -> user picks values for declared elements
                              -> substitute -> verify nothing else moved

**The user never describes a need and the system never invents.** There is no
retrieval here and no model call. This path is deterministic and free.

## The shapes

```python
# studio/prompt_templates.py           OWNER: agent A. Nobody else writes it.

@dataclass(frozen=True)
class Element:
    """One thing in the prompt the user may change."""

    name: str                    # "subject", "surface", "backdrop", "light"
    label: str                   # what the UI shows a human
    span: tuple[int, int]        # EXACT character range in the template prompt
    allowed: tuple[str, ...]     # the values this template's author permits

@dataclass(frozen=True)
class PromptTemplate:
    id: str
    prompt: str                  # the owner's proven base
    model: str                   # what it was proven against
    elements: tuple[Element, ...]

def calibrate(template: PromptTemplate, choices: Mapping[str, str]) -> dict:
    """Substitute the chosen values. Three outcomes."""
```

`calibrate` returns the studio judging dict plus:

    prompt: str | None      the calibrated prompt, None when refused
    applied: dict[str, str] element name -> value actually substituted
    rejected: dict[str, str] element name -> why that choice was refused
    changed_spans: list[tuple[int, int]]   ranges in the OUTPUT that moved

## The invariant, and it is the whole point

**Every character of the output that differs from the template's prompt must
lie inside a span of an element the user calibrated.**

Not "mostly unchanged". A diff against the base, and any changed character
outside a named span is a `fail` — a bug in the substituter, not a style
choice. Provide `verify(base, out, elements, applied)` returning three
outcomes, and make `calibrate` call it on its own output before returning.

Spans must be validated at construction: non-overlapping, inside the prompt,
and `prompt[start:end]` must be non-empty. An element whose span is wrong is a
broken template, and it must be reported as such rather than silently skipped.

## The three outcomes

- `pass` — every requested element exists, every value was allowed, the
  substitution happened, and `verify` agrees nothing else moved.
- `fail` — a requested element does not exist in this template, a value is not
  in that element's `allowed`, spans overlap, or `verify` finds a change
  outside a named span. **Return the untouched base prompt**: the user is
  better off with the template as the owner wrote it than with nothing.
- `could not measure` — no template, no elements declared, or no choices given.
  Zero substitutions is never `pass`.

## Rules that hold

- No network, no model, no paid call anywhere in this module.
- `lipsync/**` is frozen. `studio/templates.py` (motion templates) belongs to
  someone else — do not edit it; a prompt template is a SIBLING concept.
- Every constant marked ИЗМЕРЕНО / РАСЧЁТ / ВЫБРАНО.
- English module, comments explain WHY.

## The control set — OWNER: agent B, who must NOT read prompt_templates.py

`studio/fixtures/calibration_control_set.jsonl`, one JSON object per line:

```json
{"id": "...", "template_id": "...", "choices": {"subject": "..."},
 "expect": "pass" | "fail" | "could not measure",
 "must_keep": ["a phrase from the base that MUST survive verbatim"],
 "must_change": ["a phrase that must be gone"],
 "why": "what this case is testing"}
```

Required coverage, and a set missing any of these is not a control set:
1. **no choices at all** — the base must come back untouched. The commonest
   real case: a user who likes the template as-is.
2. **one element changed** — everything else byte-identical.
3. **every element changed at once.**
4. **a value not in `allowed`** — refused, base returned.
5. **an element name the template does not declare** — refused.
6. **adjacent spans**, to catch off-by-one substitution.
7. **a substituted value that CONTAINS text from another span** — the trap that
   breaks naive `str.replace`.
