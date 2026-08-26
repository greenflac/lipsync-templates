# Operating the Self-RAG prompt engineer

What it does: turns a description of a look plus a target model into a prompt
shaped the way that vendor's own guide asks for, grounded in prompts from your
corpus that were actually run and rated, graded against a rule table before it
ships, and recorded so the next run knows how this one went.

What it does not do: call any generation API, spend any money, or reach the
network. Every model call is an injected callable, which is what makes the
whole pipeline testable offline.

---

## 1. Install and check

```bash
python -m pip install -r requirements-dev.txt
python -m studio.selfrag cards          # every model card, with its limits and its evidence
bash scripts/check                      # lint, types, 79 tests, and the retrieval eval
```

`scripts/check` is the single source of truth; CI runs the same script.

## 2. Point it at your corpus

The loader reads, in order:

1. every path in `$STUDIO_CORPUS_PATHS` (colon-separated),
2. `corpus/prompts.jsonl` (the path the brief names — gitignored, it is your data),
3. `studio/knowledge/gallery_prompts.jsonl`.

One JSON object per line:

```json
{"prompt": "a rain-slick rooftop at dusk, amber golden-hour light, film grain",
 "result": "out/rooftop_01.mp4",
 "model": "veo-3.1",
 "tags": ["rooftop", "dusk", "cinematic"],
 "rating": 9}
```

Only `prompt` is required. `rating` is 1–10 and **absent is not zero** — an
unrated record is unmeasured and ranks neutrally, it is not ranked badly.
`model` should be a registry id (`python -m studio.selfrag cards` lists them),
because cross-model examples are ranked below in-model ones.

**If no corpus file exists, the tool says `could not measure` and keeps
working.** That is deliberate: an empty corpus and a missing corpus need
opposite responses, and a loader that returns `[]` for both hides which you
have. Prompts still assemble; they are just backed by nothing, and every run
reports `retrieved 0`.

A 10-record demo corpus ships at `studio/selfrag/fixtures/demo_corpus.jsonl`.
`eval` falls back to it so the gate has something to measure.

## 3. Write a prompt

```bash
python -m studio.selfrag write \
  --model veo --mode t2v \
  --text "a rain-slick rooftop at dusk, amber golden-hour light, film grain, nostalgic" \
  --subject "a lone cyclist" \
  --action "rides slowly past" \
  --camera "slow dolly in, low angle" \
  --audio "distant traffic and wind" \
  --constraint "warped background" \
  --duration 8 --aspect 9:16
```

`--text` is the look in the user's own words; the four style fields are derived
from it against `studio.style`'s allow-lists. The other flags are the vendor's
own prompt slots. **You never choose the slot order** — the card does, from the
vendor's published guide, so a Veo prompt ends on its audio cue and a Kling
prompt folds the camera into its style clause.

From Python:

```python
from studio.selfrag import PromptEngineer, PromptRequest   # or studio.selfrag.pipeline

engineer = PromptEngineer()                     # build once per process
out = engineer.write(PromptRequest(
    text="emerald forest floor, low-key light, smoky, serene",
    model="veo", mode="t2v",
    subject="a deer", action="steps slowly through the ferns",
))
out["prompt"], out["outcome"], out["examples"], out["findings"]

result = await engineer.awrite(request)         # same work, off the event loop
```

## 4. Read the answer

**Exit codes are the three outcomes: `0` pass, `1` fail, `2` could not
measure.** The third is not a soft pass. It means part of what the prompt
claims to rest on was not checked, and the note says which part.

`stages` is the receipt — every step's own outcome, so you can see *where* a
run went wrong rather than only that it did:

```
availability -> cache -> retrieval -> context -> extract -> reflect
```

Findings come in four severities:

| severity | meaning | changes the verdict? |
|---|---|---|
| `violation` | the prompt is wrong (a field was dropped, a dead clause kept) | yes — `fail` |
| `risk` | a documented failure mode is invited | no — but tell the user before they pay |
| `caveat` | a standing limitation, true on every run | no |
| `unmeasured` | a check could not run on this draft | yes — `could not measure` |

The caveat/unmeasured split exists because of a real defect: while "the model
cards are second-hand" counted as unmeasured, **every run came back
unmeasurable** and the genuine ones were invisible. A signal that fires every
time carries no information about any run.

## 5. Close the loop

The corpus is worth little until results come back into it:

```bash
python -m studio.selfrag rate \
  --record-id "prompts.jsonl:7" \
  --prompt "<the prompt that was run>" \
  --model veo-3.1 --rating 8 --artifact out/rooftop_01.mp4
```

`--artifact` is the path to what was actually produced. Without it the entry
records as `could not measure`: a rating with no path to the thing rated is a
claim nobody can open later.

Feedback moves a record's ranking weight by ±0.2 per report, bounded to
[0.4, 1.6]. It takes three consistent reports to reach a bound — one report is
an anecdote — and nothing is ever removed from the corpus automatically.

## 6. Watch it

```bash
python -m studio.selfrag report
```

Illustrative shape (these numbers are made up; run it against your own journal):

```
outcome: pass — 47 of 52 runs passed

runs                52
  passed            47
  failed            2
  not measurable    3

cache hits          18/52 (34.6%)
abstained           4/52 (7.7%)   <- no usable precedent found
query widened       9/52
mean reflect rounds 1.2
mean confidence     0.61
latency ms p50/p95  2.4 / 11.8

rules fired (most often first):
  card_confidence          52
  word_band                31
  motion_rate              7
```

Every rate is printed with its denominator, and unmeasurable runs are their own
line. A week where the corpus went missing and a week where everything was
refused look identical in a two-column report and need opposite responses.

**What to watch, and what it means:**

- **abstention climbing** — the corpus has stopped covering what people ask
  for. Add records; do not lower the floor.
- **`query widened` climbing** — users' vocabulary is drifting from the
  corpus's. Consider a synonym entry, in `studio.knowledge.SYNONYMS`, where one
  place holds that knowledge.
- **`not measurable` above `passed`** — the report says so itself: the
  instrument is the problem, not the prompts. Usually the corpus is missing.
- **one rule dominating `rule_hits`** — either a real systematic problem, or a
  rule that fires on everything and is therefore measuring nothing.

## 7. Keep the retriever honest

```bash
python -m studio.selfrag eval                    # recall, precision, negative controls
python -m studio.selfrag eval --channels bm25    # a mutation: drop channels, watch it move
```

`eval` **refuses to report any average** if the gold set has no `abstain` rows.
A retriever that never says "nothing here" cannot be told from one that always
answers, so the number would be the number a machine that always answers gets.

Write your own gold set at `studio/selfrag/fixtures/eval_set.jsonl`:

```json
{"id": "g01", "query": "...", "model": "veo-3.1", "expect": "hit", "must_retrieve": ["cyclist"]}
{"id": "n01", "query": "quarterly VAT reconciliation", "model": "veo-3.1", "expect": "abstain", "must_retrieve": []}
```

Include queries from **both ends of the difficulty range and the middle**, and
at least three negative controls. Ten easy queries measure one thing ten times.

### What the shipped fixture actually measures

MEASURED 2026-08-26, 10 records, 15 gold rows, k=5:

| channels | recall@5 | precision@5 | abstention |
|---|---|---|---|
| bm25 + phrase + tag + rating | 1.0 | 0.7083 | 3/3 |
| bm25 + phrase + tag | 1.0 | 0.7083 | 3/3 |
| bm25 + phrase | 1.0 | 0.7083 | 3/3 |
| **bm25 alone** | **1.0** | **0.7083** | 3/3 |
| tag alone | 0.9167 | 0.7917 | 3/3 |
| rating alone | 0.0 | 0.0 | 3/3 |

**Read this honestly: BM25 alone scores identically to the full fusion.** The
demo gold set is saturated — it cannot discriminate between channel sets, so it
proves the retriever works and proves nothing about whether the fusion earns
its keep. That matches the wider evidence that BM25 is hard to beat on an
out-of-domain corpus. Build a gold set against your real corpus before treating
the fusion as justified. The rating-alone row is the one informative line: it
scores zero because the rating channel deliberately never *nominates* a record,
it only reorders ones another channel found.

## 8. Adding a model

One entry in `studio/selfrag/registry.py`:

```python
_MY_MODEL = ModelCard(
    model_id="vendor-x-1.0",
    media=MEDIA_VIDEO,
    status=STATUS_SHIPPING,
    skeleton=("subject", "action", "scene", "camera"),   # the vendor's own order
    i2v_skeleton=("motion", "camera"),
    max_seconds=10.0,
    audio=False,
    negative_prompt="yes",                               # "yes" | "no" | "unknown"
    parameters={"seed": "..."},                          # real knobs beat adjectives
    slot_sources={"camera": ("camera", "_light")},       # only if one slot packs several things
    quirks=("...",),
    confidence=CONFIDENCE_WEAK,
    sources=("https://...",),                            # a card with no source is unfalsifiable
)
```

Then add it to `MODEL_CARDS` and any short names to `MODEL_ALIASES`. A test
asserts every card cites at least one source. Set
`confidence=CONFIDENCE_STRONG` only after somebody has actually opened the
vendor's document.

## 9. Things that will bite

- **Cards expire.** After `STALE_AFTER_DAYS` (90) `availability()` returns
  `could not measure`. The video field re-versioned roughly every two months
  through 2026; a quarter is already generous. Re-verify and update
  `GATHERED_ON`.
- **The cache expires itself.** Its key covers the corpus, the registry and the
  rule table. Change any of them and old entries stop matching — no manual
  invalidation, and no silently serving a prompt built against last week's
  world. `PromptCache.sweep()` reclaims the space.
- **`--subject-locked` is for the studio product only.** It enforces
  `lipsync.fork_style_prompt.subject_leak`: the person, the clothing and the
  pose come from the client photo and the driving clip, so a prompt naming them
  is refused. Leave it off for general prompt writing.
- **Sora 2's API is scheduled to stop on 2026-09-24.** The registry returns
  `fail` after that date.
- **Every card is second-hand.** No vendor document was read — the egress proxy
  blocked all of them. Good enough to shape a prompt and refuse an impossible
  request; not good enough to bill a customer against. See
  `docs/SELFRAG_RESEARCH.md`.
