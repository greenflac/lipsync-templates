# HANDOFF — branch claude/multiagent-prompt-engineer-orchestrator-7yamj4

Append-only. Each agent appends its own section and edits nobody else's.

## Agent: orchestrator — 2026-08-26

### Task as received

A multi-track research + code-review + build request: research the 2026 state of
image/video generation models and of Self-RAG architectures, review "my initial
architecture", and deliver a production Self-RAG prompt-engineering pipeline plus
a Claude Code skill, operating instructions and prompt-quality monitoring.

### Two facts the request got wrong, resolved before starting

1. The request says the initial architecture was "presented above". It was not
   included in the message. The architecture that exists is this repository's
   `studio/` package — `studio/knowledge.py` (hybrid retrieval, three outcomes,
   `evaluate`) and `studio/style.py` (StyleSpec extraction, prompt assembly).
   That is what the code review targets.
2. The request says the corpus lives at `./corpus/prompts.jsonl` with fields
   `prompt / result / model / tags / rating`. That path does NOT exist in this
   repo (`ls corpus` -> No such file or directory, MEASURED 2026-08-26). The real
   corpus is `studio/knowledge/` (core_rules.md, eval_set.jsonl, and a
   gallery_prompts.jsonl that also does not exist yet). The new loader accepts
   BOTH shapes so the stated corpus works the day it is dropped in.

### Ownership under CONTRACTS.md

`studio/knowledge.py` and `studio/style.py` have other owners (Ц2). This agent
does NOT edit them. All new work lands in new files under `studio/selfrag/`
plus new docs. Anything the review finds in the owned modules is written up as
a finding for their owner, not patched here.

### What was built

`studio/selfrag/` — a new, additive package. It imports `studio/knowledge.py`
and `studio/style.py` and edits neither.

| module | responsibility |
|---|---|
| `corpus.py` | load the prompt+result corpus portably; a missing corpus is `could not measure`, never an empty success |
| `registry.py` | model cards: skeleton, limits, quirks, sources, confidence, end-of-life |
| `spec.py` | `GenSpec` — a media-aware superset of `StyleSpec`; the assembler |
| `retrieval.py` | hybrid lexical search + the deterministic rewrite ladder |
| `reflect.py` | the grading rules; violation / risk / caveat / unmeasured |
| `cache.py` | keyed on the request AND on what shaped the answer |
| `replay.py` | shipped-prompt feedback folded back into ranking, bounded |
| `monitor.py` | run journal and a report that prints its denominators |
| `pipeline.py` | orchestration, sync and async |
| `evaluate.py` | recall/precision with MANDATORY negative controls |
| `cli.py` | `python -m studio.selfrag write\|eval\|report\|rate\|cards` |

Plus `.claude/skills/prompt-engineer/SKILL.md`, `docs/SELFRAG.md`,
`docs/SELFRAG_REVIEW.md`, `docs/SELFRAG_RESEARCH.md`.

### Numbers (MEASURED 2026-08-26)

`bash scripts/check` — green, exit 0. 770 lipsync tests, 79 selfrag tests,
ruff clean, mypy clean, retrieval eval passing.

Retrieval, on the 10-record demo corpus and the 15-row gold set, k=5:

| channels | recall@5 | precision@5 | abstention |
|---|---|---|---|
| bm25 + phrase + tag + rating | 1.0 | 0.7083 | 3/3 |
| bm25 + phrase + tag | 1.0 | 0.7083 | 3/3 |
| bm25 + phrase | 1.0 | 0.7083 | 3/3 |
| bm25 alone | 1.0 | 0.7083 | 3/3 |
| tag alone | 0.9167 | 0.7917 | 3/3 |
| rating alone | 0.0 | 0.0 | 3/3 |

### MEASURED NEGATIVE RESULT — read before trusting the fusion

**BM25 alone scores identically to the four-channel fusion on this fixture.**
The demo gold set is saturated: it cannot discriminate between channel sets. It
proves the retriever works and the abstention floor holds; it proves nothing
about whether the phrase, tag or rating channels earn their keep. Do not cite
the fusion as justified until a gold set built against a real corpus says so.

The one informative row is `rating alone` at 0.0: that channel deliberately
never nominates a record, it only reorders ones another channel found.

### Defects found by running the code, and fixed here

1. Veo's `camera`/`composition`/`focus` slots all read one field, so the camera
   clause was emitted three times in one prompt.
2. Kling's `motion` text was silently dropped: its skeleton says "action", the
   spec filled "motion", and nothing connected them. Now `_action`/`_motion`
   fall back to each other, and `_rule_dropped_field` makes any remaining drop
   a violation rather than silence.
3. The style clause repeated the texture that already had its own slot.
4. `card_confidence` as an UNMEASURED finding made **every** run unmeasurable —
   it is true on every run forever. Split into a `caveat` severity that prints
   but does not change a verdict.
5. `dropped_field` fired on image-to-video prompts that correctly omit the
   subject. Split into `dropped` (a bug) and `dropped_by_design` (the rule
   working).
6. `assemble()`'s early returns carried fewer keys than its success return — a
   `KeyError` waiting on the unhappy path. All branches now share `_EMPTY_DRAFT`.
7. The journal recorded the alias the caller typed, so "veo", "veo3" and
   "veo-3.1" were three rows that could not be summed. Now resolved first.
8. Retrieval filtered on the alias too, pushing genuinely in-model examples
   into the cross-model penalty band.

### Findings for OTHER owners — not fixed here, per one-writer-per-module

Detail and measured output in `docs/SELFRAG_REVIEW.md`.

- **CRITICAL, `studio/knowledge.py`**: `OUR_PROMPTS_DIR` and
  `REFERENCE_CARDS_DIR` are absolute paths to `/home/user/cyclerunner/...`,
  which does not exist here. On a fresh clone the index holds 12 entries, not
  822; `retrieve` answers "could not measure" for everything; `evaluate` cannot
  run. The recall@5 0.9737 in `HANDOFF_studio-mvp.md` is not reproducible from
  this repository. The two tests that would catch it SKIP.
- **`studio/knowledge.py`**: sqlite opened with default `check_same_thread=True`
  and cached in a module global. The first `def` FastAPI route that calls
  `retrieve()` from a threadpool worker will raise `ProgrammingError`. Latent
  today — nothing in `app.py` calls it yet.
- **`studio/knowledge.py`**: `default_index()` never invalidates; a new corpus
  file is not picked up until restart.
- **`studio/knowledge.py`**: `retrieve` reports below-floor candidates as
  `violations`, conflating "the floor worked" with "a breach".
- **`requirements-dev.txt`**: `httpx2` is not pinned, and
  `studio/tests/test_app.py` cannot even be collected without it.
- **`scripts/check` / CI**: no studio test ran in CI at all. This branch adds
  `studio/selfrag` only — adding the rest is blocked on the `httpx2` pin above.
- **`studio/tests/`**: no `__init__.py`, so `unittest discover` cannot load it.
- **DEBT(2026-08-26)**: `studio/knowledge.py` (module) and `studio/knowledge/`
  (directory) share a name, so mypy resolves imports to the directory. Every
  typed import from it needs `# type: ignore[attr-defined]`;
  `studio/selfrag/retrieval.py` carries one with this marker.

### Ц4 — external claims, all UNVERIFIED

Every model fact in `registry.py` and `docs/SELFRAG_RESEARCH.md` is
second-hand. `WebFetch` was refused by the egress proxy for every primary
domain (arxiv.org, docs.bfl.ai, ai.google.dev, kling.ai, help.runwayml.com,
docs.byteplus.com, alibabacloud.com, platform.openai.com, openreview.net). No
bypass was attempted. Only `WebSearch` summaries were available, so no vendor
or paper document was read by anyone in this session.

To promote any card to `CONFIDENCE_STRONG`, a session needs egress to those
hosts. That is the environment owner's decision.

### Ц9 — stop condition for the next person

If by the time the corpus reaches 200 real records a gold set built against it
does not show the fusion beating BM25 alone on recall, delete the phrase, tag
and rating channels and ship BM25 with the abstention floor. Record the numbers
either way.

### Ц8 — deliberate departures

- `DEBT(2026-08-26)`: no cross-encoder reranker. The research says it is the
  highest-leverage remaining component and that its score is the natural
  abstention signal, but a 0.3–0.6B reranker over 50 candidates is estimated at
  seconds on CPU and that estimate is arithmetic, not a measurement. Measure it
  before adding it.
- `DEBT(2026-08-26)`: `evaluate` scores retrieval only. There is no offline
  measure of whether the assembled prompt is any *good* — only whether it obeys
  the rules. Doing that honestly needs generated results rated by someone who
  did not write the prompt, which is what the replay buffer is for and what
  nobody has fed it yet.
