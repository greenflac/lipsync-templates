# Product logic — settled 2026-08-26

This document exists because the absence of it was the real problem. Every
architectural argument in this project until now was an argument about a
product nobody had written down.

## The product

The user cannot write a good prompt. **We do not ask them to.**

A template is a purchase decision frozen into data — it already carries a
driving clip AND a prompt that is known to work. The user picks a template by
looking at it, then **calibrates** a fixed set of its elements. The agent
substitutes what they chose and changes nothing else.

    template (proven prompt)  ->  user calibrates listed elements  ->  substitute

## The four decisions, and they are decisions, not deductions

| question | decided |
|---|---|
| where does the base prompt come from? | **the template carries its own**, chosen by the owner |
| what can the user calibrate? | **a fixed set of elements** the template declares |
| can the user ADD something not in the template? | **no — substitution only** |
| what happens on an ambiguous request? | **ask the user** |

Owner's call, 2026-08-26. Each was the conservative option.

## Why this shape and not the one we were building

We spent this session building a system that turned a user's intent into a
prompt from scratch. The evidence says that is the losing design:

- In the only randomised trial in the field (N=1,891, 300,000+ images), a
  model rewriting a user's prompt **erased 58% of the gain**, because rewrites
  "added extra details or changed the meaning"
  (https://arxiv.org/abs/2407.14333).
- Prompt length correlates with quality at about **-0.07**
  (https://arxiv.org/pdf/2403.11821). Longer is not better.
- Our own blind A/B, 2026-08-26: the agent's assembled prompt lost both pairs
  to the user's own untouched sentence.

Calibration sidesteps all of it. Nothing is invented because the base is
already good and the user's words replace parts of it. The 58% finding does
not apply to a design that never expands.

## The invariant, and it is mechanical

**Every changed character in the output must fall inside an element the user
calibrated.** Not "mostly unchanged", not "faithful in spirit" — a diff against
the base, checked at element level, with any change outside a named span being
a defect.

Demonstrated on a real corpus prompt, 2026-08-26: swapping the subject and the
light left **75% of the base byte-identical** and touched exactly the two named
elements.

This replaces the fidelity audit's word-level heuristic with an exact check.
The audit stays as a second line for the day free text is allowed in.

## What this demotes, and it is most of what was built this session

Said plainly, because defending work that is off the product path costs more
than deleting it:

| module | status under this logic |
|---|---|
| `rewriter.py` model path | **not needed.** Fixed knobs mean no free text to interpret, so no LLM and **no paid call per prompt** |
| `rewriter.py` clause classification | **not needed.** The template declares its own element spans; nothing has to be guessed from cue words |
| `evidence.py` (corpus clause splicing) | **not needed.** The base is already a good prompt; borrowing clauses into it adds the very detail this design avoids |
| `quality.py` as a ranker | **not needed at runtime.** The base is owner-approved, so there is nothing to score |
| `fidelity.py` | **kept, demoted to a backstop** behind the exact diff check |
| `facts.py`, `registry.py` | **kept.** Which model, what it can do, what it refuses — still needed to send the prompt anywhere |

## Where RAG goes, and this is the honest answer

Under these decisions **RAG leaves the user-facing path.** If the template
carries its own prompt and the user picks a template by looking at it, nothing
at runtime needs retrieval.

RAG becomes an **authoring tool for the owner**: 4,601 prompts to mine when
deciding which templates to build and what a good prompt for a scene looks
like. That is a real job and the corpus is the right thing for it. It is just
not the mechanism the user touches.

This should be said out loud because it reverses several days of assumption,
including in this session's own documents.

## What a template must now carry

```python
@dataclass(frozen=True)
class PromptTemplate:
    id: str
    prompt: str                      # the proven base, owner-approved
    model: str                       # what it was proven against
    elements: tuple[Element, ...]    # what may be calibrated

@dataclass(frozen=True)
class Element:
    name: str                        # "subject", "surface", "backdrop", "light"
    span: tuple[int, int]            # exact character range in `prompt`
    allowed: tuple[str, ...]         # values a user may choose, or () for free
```

`span` is what makes the invariant checkable. An element without one is a
promise; an element with one is a fact.

## The three outcomes here

- `pass` — every changed character lies inside a calibrated element's span.
- `fail` — the output differs from the base outside a named span.
- `could not measure` — the template declares no elements, the requested
  element does not exist in it, or the request is ambiguous. **Ambiguous means
  ask, never guess.**

## The rest, settled the same day

**The owner writes the templates.** The prompting in the main branch was done
by hand, so the shipped style templates already carry the owner's own creative
vision. That is also the real argument for where RAG belongs: the corpus is a
record of that vision, which makes it an excellent instrument for the owner and
their colleagues to author with, and the wrong thing to put between a customer
and a picture.

**Allowed values come from the template itself**, not from `studio/style.py`.
The template's author knows which alternatives actually work in that
composition; a global word list does not.

**There is no "no template fits" case, and asking about it was a mistake in the
framing.** The user does not describe a need. They pick a template — the
driving clip inside it is fixed and not negotiable — and they style it to their
own vision *using what is already in the prompt*. Nothing is searched for,
because nothing is being looked for.

That last point is worth keeping because it is the sentence that makes the
whole design safe: **the user never asks for something the system has to
invent.**

## What is still open

- How many templates before this is a product.
- Whether an element may be calibrated to a value the template did not list.
