# Contract for the rewriter — read before writing any of it

Parallel agents share this EXACTLY. Copy names verbatim; do not invent synonyms.

## The product rule, and it is not negotiable

The user cannot write a good prompt. The agent writes one FROM THEIR INTENT.
It **invents nothing** — it only optimises for the target model.

The evidence this rests on: in the one randomised trial in this field
(N=1,891, 300,000+ images, https://arxiv.org/abs/2407.14333), automatic
rewriting **erased 58% of the model's gain**, because rewrites "added extra
details or changed the meaning". Prompt length correlates with quality at
about -0.07. **Longer is not better. Faithful is better.**

## What "optimise for the model" is allowed to mean

ALLOWED — this is the whole job:
- reorder the user's content into the card's `skeleton` slot order
- drop what the card says the model ignores, and say so in `dropped`
- move a prose instruction into a real parameter (`camera_fixed`, `--ar 3:4`)
- restate the user's own words in the vendor's idiom, same referent
- for a model whose card says `expands_internally: yes`, SHORTEN

FORBIDDEN:
- naming any object, material, place, colour or creature the user did not
- adding a quality booster ("8k", "award-winning", "masterpiece") — folklore,
  see docs/SELFRAG_RESEARCH_AGENTS.md §5
- lengthening for its own sake

## The signature

```python
# studio/selfrag/rewriter.py            OWNER: agent A. Nobody else writes it.
def rewrite(
    intent: str,
    *,
    card: ModelCard,
    examples: Sequence[CorpusRecord] = (),
    model: Callable[[str], str] | None = None,
) -> dict:
    """Turn intent into a prompt for `card`'s model. Three outcomes.

    `model=None` means no network and no cost: a deterministic reorganisation
    that cannot invent by construction. A callable means few-shot rewriting,
    whose output is then put through `fidelity.audit` and REJECTED if it
    invented anything — the gate is not advisory.
    """
```

Returns the studio judging dict plus:

    prompt: str | None      the rewritten prompt, None when refused
    dropped: list[str]      user content the card has no slot for
    invented: list[str]     what the audit caught; non-empty means outcome FAIL
    source: str             "deterministic" | "model" | "model_rejected"
    rounds: int             model attempts made

## The three outcomes

- `pass` — a prompt exists and `fidelity.audit` returned `pass`.
- `fail` — the model invented, and after `MAX_ROUNDS` it still invented. Return
  the DETERMINISTIC prompt as a fallback and set `source="model_rejected"`.
  A refusal that leaves the user with nothing is worse than a plain prompt.
- `could not measure` — no intent given, no card, or the model was asked and
  did not answer.

## Rules that hold

- `lipsync/**` is FROZEN. Do not edit it. The model callable is injected.
- Tests never touch the network; the runner enforces it.
- No paid call happens without `model=` being passed explicitly.
- Every constant marked `ИЗМЕРЕНО` / `РАСЧЁТ` / `ВЫБРАНО`.
- English module, comments explain WHY.

## The control set — OWNER: agent B, who must NOT read rewriter.py

`studio/selfrag/fixtures/rewriter_control_set.jsonl`, one JSON object per line:

```json
{"id": "...", "intent": "...", "model": "flux-2",
 "expect": "unchanged" | "reordered" | "shortened" | "refused",
 "must_not_contain": ["swan", "..."],
 "must_contain": ["..."],
 "why": "what this case is testing"}
```

Required coverage, and a set missing any of these is not a control set:
1. **unchanged** — an already-good prompt. The correct behaviour is to leave
   it alone. This is the most important case in the file.
2. **invention bait** — an intent whose obvious "improvement" is to add scene
   detail. `must_not_contain` names what a careless rewriter would add.
3. **a model that expands internally** — expect `shortened`.
4. **empty / nonsense intent** — expect `refused`.
5. Cases at both ends and the middle of intent length.
