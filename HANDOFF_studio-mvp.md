# HANDOFF — branch studio/mvp

Append-only. Each agent appends its own section and edits nobody else's.

## Agent: knowledge / RAG (studio/knowledge.py) — 2026-08-25

Owned and written here: `studio/knowledge.py`, `studio/tests/test_knowledge.py`,
`studio/knowledge/core_rules.md`, `studio/knowledge/eval_set.jsonl`.
Nothing else was touched. No git command beyond reads was run.

### What exists now

- `build_index(...) -> KnowledgeIndex` over one sqlite file with FTS5.
  822 entries: core 12, ours 288, reference_card 522, gallery 0.
- `retrieve(spec_or_text, *, k=5, index=None) -> dict` — three outcomes, core
  rules in their own field, at most 2 examples per provenance, near-duplicate
  suppression inside the answer.
- `evaluate(index, eval_set, *, k=5) -> dict` — recall@k, precision@k, three
  outcomes, and two mandatory controls (an absent topic that must come back
  empty, a verbatim phrase that must come back with full recall). Either
  control failing makes the run FAIL regardless of the averages.
- Gold set: 40 records in `studio/knowledge/eval_set.jsonl`.

### Numbers (MEASURED 2026-08-25, k=5, 40 gold records, 822 entries)

| fusion | recall@5 | precision@5 | outcome |
|---|---|---|---|
| bm25 + phrase + structural + dense | 0.9737 | 0.7237 | pass |
| bm25 + phrase + structural (no weights) | 0.8947 | 0.6711 | pass |
| bm25 only (mutation) | 0.8289 | 0.7039 | fail |

Dense channel: `sentence-transformers` installed and
`sentence-transformers/all-MiniLM-L6-v2` (apache-2.0, license read from the HF
API) downloads and runs on this machine. It is OFF by default: tests must not
reach the network. Turn it on with `dense=True` or `STUDIO_KNOWLEDGE_DENSE=1`.

### Measured negative result

The structural channel buys 0 recall on this gold set and costs 0.079
precision. It is kept because it is the only channel that can rank a query
carrying no corpus vocabulary — but that case does not occur in the gold set,
so the justification is unproven rather than proven.

### Open items for whoever comes next

- `studio/knowledge/gallery_prompts.jsonl` did not exist at build time. The
  loader is written and the index builds without it; drop the file in and
  rebuild, then re-run `evaluate` before trusting any before/after comparison.
- DEBT(2026-08-25): the default persisted index lands at
  `studio/knowledge/index.sqlite3` and `.gitignore` does not cover `*.sqlite3`.
  Whoever owns `.gitignore` should add it; this agent does not.
- `studio/knowledge.py` (module) and `studio/knowledge/` (data dir) share a
  name deliberately. A regression test asserts the module still wins the
  import; do not add `studio/knowledge/__init__.py`.

### Late addition, same session

`knowledge/PROVENANCE.md` and `knowledge/NOTICE_replacement.md` appeared from
the harvester agent mid-session. `load_gallery_prompts` was aligned to the row
format documented there: the row's own `provenance` value is carried through
(`third_party_gallery`, weight 0.6, its own quota bucket) and its `rights`
marker travels into the `source` field of every retrieved example. Three tests
cover it. The file `gallery_prompts.jsonl` itself still did not exist at the
close of this session.

## 2026-08-26 — the corpus is re-scoped, and the specialist gets its instrument

Owner decisions taken today, each of them a change of course, not a detail:

1. **`ball-reel` is a retired engine.** It is not to be counted in development
   any more. Work happens in this repository.
2. **Our own 288 prompts leave the training corpus.** They were written for
   several unrelated projects and tasks. Averaged into one index they teach
   the writer the mean of jobs that share nothing. This is a rejection of the
   corpus as it was measured (822 entries, recall@5 0.9737) — that number was
   measured on a corpus that no longer exists and is void until re-measured.
3. **The aidsgn gallery cards are the training material.** Rights to them are
   ours; the owner confirmed this on 2026-08-26, and it is recorded as a
   `RIGHTS:` line in `studio/knowledge/PROVENANCE.md` rather than in anybody's
   memory. A gate fails if that line disappears.
4. **The product is a turnkey prompt-engineering layer**: the agent talks to
   the client and shapes the prompt that drives generation. Not a library, not
   a research artefact.
5. **The interview is short: three to five questions**, one per spec slot.
6. **The agent's output is the frame-generation prompt text.** Motion prompt,
   template choice and negative prompt are out of this slice.
7. **Acceptance is a blind comparison against a human.** Same briefs, agent
   prompt against hand-written prompt, judge blind to authorship.

### The contradiction that has to stay visible

The aidsgn cards, as extracted today, carry **no prompt wording**. Measured,
not recalled: a card holds `card` (colours, saturation, texture, value_key),
`card_measurement` (grain_residual), `skeleton` (chars, words, clauses, and
the parameters ar/style/cref/sref) and `source`. Nowhere in those 522 files is
there a sentence a human wrote to a generator.

So the corpus as it stands teaches **what a good picture looks like** and not
**how a prompt is said**. For a specialist whose entire output is wording,
that is the wrong half. The owner chose the harvest as the fix, and will run
the collection himself — this environment's classifier blocks it, and that
block was not worked around.

Until the harvest lands, `build_index` must report `wording_examples: 0` and
raise `unmeasured`, so that no run can report a clean pass on a corpus with no
worked examples in it. That is gated, not agreed.

### Gates written before any implementation

- `studio/tests/test_knowledge_corpus.py` — corpus composition, rights on
  record, and a recorded retrieval measurement that names the corpus size it
  was taken on, so a corpus change invalidates a stale number visibly.
- `studio/tests/test_intake_gate.py` — questions live in code, the interview
  asks only what it does not know, and an unfinished interview says so instead
  of filling gaps with defaults.
- `studio/tests/test_blind_gate.py` — the judge payload carries no authorship,
  the leak check can say no, the A/B assignment is reproducible but not
  constant, and a sample below the floor is unmeasured rather than a tie.

Every gate was run before its writer started, and every one was red.
Gate A red on six failures and two errors, each naming a real fact to fix.
Gates B and C red on a missing import, which is the weakest kind of red:
it proves the gate runs, not that it discriminates. They are only proved
as instruments once their modules exist and the thresholds are mutated.
None of the three is edited by its writer.

### What the research found (2026-08-26)

Marked UNVERIFIED where the primary source could not be opened. Every official
Kling domain — `fal.ai`, `klingai.com`, `kling.ai` — and every paper host —
`arxiv.org`, `aclanthology.org`, `dl.acm.org`, `openreview.net` — is closed by
the proxy here. None of them was worked around. Only `huggingface.co/papers`,
`raw.githubusercontent.com` and GitHub code search were reachable, and every
number below was read there in person.

**1. A small corpus with a good retriever beats a large one. Measured.**
Bertsch et al. (HF papers 2405.00200): on Banking-77, choosing the examples
with BM25 is worth **+51.5 points at 1-shot and +4.9 at 1500-shot**. The gain
from *selection* is an order of magnitude larger than the gain from *volume*.
Agarwal et al. (2404.11018): plateaus arrive early — 125 examples on MATH,
degradation past 50 on summarisation, ~25 for reinforced ICL.

This is the evidence for the owner's instruction "not big, effective". It also
retires the instinct to grow the corpus: our budget belongs in retrieval.

**2. Examples and rules teach different things, so the choice is not either/or.**
Min et al. (2202.12837): randomising the *answers* inside demonstrations costs
0–5%, but removing the input-label *format* wipes out nearly the whole gain.
Examples carry format, vocabulary and distribution; rules carry the "why" and
the "never", which no example shows. Keep both, and measure each one's
contribution rather than assuming it.

**3. On short records, BM25 is the baseline to beat, not the one to skip.**
BEIR (2104.08663), verbatim: *"BM25 is a robust baseline"* — dense models that
beat it by 7–18 points in-domain lose to it across 18 zero-shot datasets. A
style corpus written in our own invented vocabulary is exactly the
out-of-domain case. DAT (2503.23013): *"fixed weighting schemes fail to adjust
to different queries"*, +7.5% P@1 from adapting the weight per query.

Our own measurement disagrees in our favour and outranks the general claim:
bm25-only 0.8289 against the full fusion 0.9737 on our eval set. It is still
void until re-measured on the new corpus.

**4. Kling's practical prompt ceiling is 500 characters, not 2500. UNVERIFIED
by an official source.** Read in `Comfy-Org/ComfyUI`, whose request models are
generated from Kling's OpenAPI spec: the schema says `prompt max_length=2500`,
while `nodes_kling.py` enforces `MAX_PROMPT_LENGTH_I2V = 500` and
`MAX_PROMPT_LENGTH_IMAGE_GEN = 500`. Both numbers were read in the source; the
discrepancy could not be settled because Kling's own documentation is behind a
closed domain. Until the owner opens `fal.ai` or `klingai.com`, we generate to
the 500-character bound as the safe edge and carry the note UNVERIFIED.

Also read from the same generated models, and worth keeping: `negative_prompt`
is a separate field, `cfg_scale` is 0.0–1.0 with default 0.5 and *higher means
less freedom*, and camera control is six axes each bounded −10…10.

### The contradiction between the research and today's decision

The research's first recommendation is: **do not build an N-step interview**.
The only mature open implementation in this exact domain (`Hao0321/ai-media-
generator`, 227 stars) extracts nine slots from a single client sentence,
fills the rest with defaults, and confirms once — with an explicit rule
against asking what the system can decide for itself. On the question of how
many questions are optimal, the research verdict is **could not measure**: all
the studies with numbers sit behind closed domains, and their figures are in
the UNVERIFIED block, unusable.

The owner decided a short intake of three to five questions. That decision
stands, and the gate is written to it. The gap is narrower than it looks: our
`plan()` asks **only about slots the brief left empty**, so a rich brief
produces zero questions — which is the research's design. What we deliberately
keep is the refusal to fill a gap with a default: an unfilled slot is reported
as unfilled and the run is `could not measure`. That is a methodology choice
paid for five times over on this project, and it is not up for trade against
a convention from one repository.

What the research does change: the ceiling of five is `CHOSEN`, not
`MEASURED`, and there is no external number that could make it measured. It
becomes measured only by our own run.

### The experiment this makes worth doing

Four arms on the same briefs — rules only / k examples only / both / neither
(the negative control, and the arm that proves the instrument can say "no") —
sweeping k to find *our* plateau instead of importing someone's. Until that
run, "three to five questions" and "two to five examples" are both `CHOSEN`.

## studio/blind.py — the blind comparison instrument (append-only, writer: blind agent)

Built before there is anything to measure (P1). Public surface: `make_pair`,
`judge_payload`, `leak_check`, `score`. Gate `studio/tests/test_blind_gate.py`
was NOT edited; own tests are `studio/tests/test_blind.py` (38 tests green
together with the gate).

Decision constants, all in `studio/blind.py`:
- `SAMPLE_MIN = 20` — CHOSEN, matches the gate's own floor. Below it the run is
  UNMEASURED, never a tie.
- `DECISIVE_MIN = 5` — CALCULATED from a one-sided sign test (0.5**5 = 0.031 <
  0.05, 0.5**4 = 0.063). Ties clear SAMPLE_MIN while carrying no direction.
- `WIN_SHARE_MIN = 0.55` — CHOSEN by this writer, NOT confirmed by the owner.
  Open question for the owner: what share of decisive pairs counts as "beats
  the human"?

Semantics that other modules must not re-invent: `unmeasured` = unjudged pairs
+ violations + the shortfall to the floors; a tie is a measured equality and
never stands in for missing data.

Mutation results (both directions, each turned a named test red) and the two
negative controls are in the session report.

NOTE for whoever runs mutation testing here: rewriting a module twice within
the same second reuses a stale `__pycache__` .pyc (mtime+size invalidation),
which silently reports the previous mutation's failures. Run mutations with
`python3 -B` — measured on this machine, it produced three false mutation
results before it was caught.

## studio/intake.py — the client interview (writer: intake agent, 2026-08-26)

New module `studio/intake.py` plus own tests `studio/tests/test_intake.py`.
Gate `studio/tests/test_intake_gate.py` NOT edited. Nothing committed or pushed.

Public: `QUESTIONS` (slot -> fixed question text, keyed off `SPEC_FIELDS`),
`MAX_QUESTIONS`, `plan(brief, *, answers=None, model=None)` -> `{ask, known,
note}`, `conduct(brief, *, answers)` -> the studio judging dict plus `spec`
and `unfilled`. Helpers `read_brief` / `read_answer` are public so callers can
read one slot without running an interview.

Reused, never copied: `SPEC_FIELDS`, `StyleSpec`, `PALETTE_MAX`, `SETTING_MAX`,
the four allow-lists, `banned_topics`, `sanitise_setting`, `setting_violations`,
`refusal_spec`, `gate_input` (structural verdict is style.py's, not the
interview's), `PASS/FAIL/UNMEASURED`, and the brand list via
`lipsync.fork_aesthetic.brand_conflict` — the LIST is reused, the verdict is
not: branded aesthetics are allowed there, a client naming a third-party brand
is refused here.

`extract()` is deliberately NOT called: it needs a model, and planning must not.
Slot reading is pure allow-list word matching, space-bounded, hyphen-insensitive
("film grain" reads as `film-grain`, "golden-hour" never reads as `gold`).

Constants: `MAX_QUESTIONS = 5` CHOSEN (owner, 2026-08-26; not derived from
`len(SPEC_FIELDS)` — a sixth slot must go unasked rather than stretch the
interview). `SETTING_MIN = 3` CHOSEN. `SETTING_MARKERS` CHOSEN from the brief
phrasing in CONTRACTS.md.

KNOWN LIMIT, not a defect to be silently fixed: the planner is English
word-matching only. A non-English brief ("un salon calme, ambre et ivoire")
closes zero slots, so the client is asked all five questions — UNMEASURED, never
a wrong spec. If the product wants multilingual intake, it needs the model, and
then the "planning calls no model" rule has to be re-decided by the owner.

## knowledge.py — corpus recomposed, retrieval re-measured (2026-08-26)

Owner decision: our 288 fixture prompts leave the default corpus. `build_index`
now takes `our_prompts=None` by default and reports the exclusion under
`build_report["excluded"]` with the reason, so an exclusion can never be read as
a source that broke. `load_our_prompts` is untouched; passing a directory puts
them back for a deliberate experiment.

`build_report` gained `wording_examples` (entries whose kind is in
`WORDING_KINDS`). It is 0 today and `unmeasured` is raised to at least 1, as the
gate requires. Verified by reading the cards, not recalled: a reference card
holds colours, saturation, texture, value_key, a grain residual and a wordless
skeleton — no sentence anyone typed at a generator.

RE-MEASURED, and this is the cost of the decision. Default corpus is now 534
entries (12 core + 522 cards). On the same 40-record gold set, k=5, dense on
all-MiniLM-L6-v2:

    bm25 + phrase + structural + dense  recall@5 0.4474  precision@5 0.4737  FAIL
    bm25 + phrase + structural          recall@5 0.4474  precision@5 0.4737  FAIL
    bm25 + phrase                       recall@5 0.4211  precision@5 0.4474  FAIL
    bm25 only                           recall@5 0.4342  precision@5 0.4474  FAIL

Was 0.9737 / 0.8947 / 0.8947 / 0.8289 on 822 entries. Re-running the old four
configurations on 822 entries today reproduced those numbers exactly, so the
drop is the corpus and not the instrument. Negative controls 2/2 ok, positive
controls 0/2. The gold set was written against the corpus that held our
prompts; most of its expected phrases lived only there. It has to be rewritten
against the corpus the writer will actually read from.

Two constants are declared but NOT guarded (mutated both ways, gate stayed
green, DEBT in the source): `WORDING_KINDS` and the `unmeasured >= 1` bump —
both are invisible while `wording_examples` is 0 under every reading. They
become testable when the gallery harvest lands.

`studio/tests/test_knowledge.py::ShippedIndex` now passes `our_prompts=` 
explicitly (two call sites, one comment). Without it both tests skipped with a
reason that was false — the fixtures ARE on this machine, they are excluded.
Nothing currently guards retrieval quality over the new default corpus.

### The retrieval number after the corpus change — and why it is not a verdict

Re-measured on the new default corpus of **534 entries** (12 core + 522 cards):
recall@5 **0.4474**, down from 0.9737. The rig was verified before the number
was believed: re-running the same four channel configurations on the old
822-entry corpus reproduced 0.9737 / 0.8947 / 0.8947 / 0.8289 exactly. So the
drop is the corpus, not the instrument.

But the drop is not a verdict on the retriever, and calling it one would be
the same mistake the three-outcome rule exists to prevent. Measured
independently rather than taken on the writer's word: of the **43** distinct
`must_retrieve` terms in the gold set, **17** occur anywhere in the aidsgn
cards and **33** occur in our own prompts. The terms that live only in our
prompts are our own invented phrases — `amber cream premium palette`,
`golden hour bloom`, `graphite teal focus palette`, `low key diffuse nocturne`.

The gold set was written against the corpus we have just removed. It is now
asking the index for phrases that are not in it. Two of the two positive
controls fail, which says the instrument is broken, not that the index is bad.

**Verdict: could not measure.** Not `fail`. The next piece of work is a gold
set written against the corpus the writer will actually read from, and until
that exists no retrieval number from this repository means anything.

### Three unguarded thresholds, found by the writer's own mutation run

The writer mutated four thresholds and reported that three of them left the
gate green — that is, the gate did not guard them. Reported rather than
quietly fixed, which is the correct move: the writer does not edit the gate.

Two are now guarded, proved by mutation in this session:
- counting style cards as prompt wordings — 2 failures;
- defining "wording" as nothing at all — 2 failures.

The third is a different animal. Removing the `max(unmeasured, 1)` bump on a
wordless corpus changes no number, because an absent harvest already raises
`unmeasured` by one, and planting an empty harvest does not help either: a
source that yields no records counts as missing too. The bump is **redundant
by construction** while the harvest is absent — the same shape as the mode
share threshold that turned out to be implied by the entropy threshold on the
judge. No contrived test was written to guard a line that does nothing. What
is guarded instead is the *declaration*: a wordless corpus must say so in its
note, and removing that sentence reddens the gate.

### Environment traps worth carrying forward

1. A stale `.pyc` silently returns the previous mutation's result, because
   invalidation is by mtime plus size and `= 19` and `= 21` are the same size
   in the same second. Two writers hit this independently. Mutations are run
   with `python3 -B` and no `__pycache__`, or they are fiction.
2. The shared scratchpad contains a stray `ctypes.py` from a chromadb install
   that shadows the stdlib module. Any script run with that directory on
   `sys.path` reports the dense channel as unavailable and would have produced
   a confident, wrong "dense buys nothing" measurement.
3. `discover -s studio/tests` does not run at all — `studio` is a namespace
   package with no `__init__.py` in tests. The suite is run by naming modules.
   A command that errors instead of running is not a green suite.

### Gap that outranks the rest: nothing in CI runs `studio/`

`scripts/check` and the CI workflow cover `lipsync/` only. All 246 studio
tests, every gate written today included, run only when somebody runs them by
hand. Ц7: what must always happen is a hook, a test or CI, not a line in a
document.
