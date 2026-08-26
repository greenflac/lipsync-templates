# Research findings, 2026-08-26

## Read this first: how good this evidence is

Three research agents ran web searches on 2026-08-26. **In every one of them,
`WebFetch` was refused by this environment's egress proxy for every primary
domain attempted** — `arxiv.org`, `docs.bfl.ai`, `ai.google.dev`, `kling.ai`,
`help.runwayml.com`, `docs.byteplus.com`, `alibabacloud.com`,
`platform.openai.com`, `aclanthology.org`, `openreview.net`. No agent bypassed
the block, and none was asked to.

So **not one primary document below was read.** Every fact is a search engine's
summary *of* a document. The URLs are the canonical sources; the wording is
second-hand. Where a paper's number appears, it is a number a search snippet
attributed to that paper.

This is why every entry in `studio/selfrag/registry.py` carries
`confidence="weak"`, why `_rule_card_confidence` prints a standing caveat on
every prompt, and why `availability()` expires a card after 90 days. The
architecture treats its own facts as unverified because they are.

**To promote any of this to verified**, a session needs egress to those hosts.
That is a decision for whoever owns this environment's network policy, not
something to route around.

---

## Track 1: generation models, August 2026

| Model | Status | Max dur | Resolution | Audio | Negative prompt | Price/sec |
|---|---|---|---|---|---|---|
| FLUX.2 / Kontext | shipping | n/a | up to 4MP | no | no | not sourced |
| Kling 3.0 | shipping (5 Feb 2026) | 15 s | 720p/1080p/4K | yes | yes | ~$0.126 |
| Veo 3.1 | shipping | 8 s (4/6/8 only) | 720p/1080p, 4K premium | yes | Vertex yes, Gemini undocumented | $0.15–0.40 |
| Runway Gen-4.5 | shipping | 10 s | 720p (disputed) | no | no | $0.12 |
| Wan 2.6 Flash | shipping | 15 s | 720p/1080p @30fps | yes | yes | $0.021–0.069 |
| Seedance 2.0 | shipping (Feb 2026) | 12 s (disputed) | 720p/1080p (disputed) | yes | not sourced | not sourced |
| Sora 2 | **sunsetting** | not sourced | not sourced | yes | not sourced | $0.10–0.70 |

### Four findings that change what you build

**1. Sora 2 is going away, and the popular framing is half wrong.** The
consumer app was withdrawn on **2026-04-26**; the **API is scheduled to stop on
2026-09-24** — about a month after this research was done. "OpenAI shut down
Sora in April" is what people say and it is not what happened. The registry
encodes both dates and returns `fail` for any call after the API date, so a
paid request cannot be sent to an endpoint that has been turned off.

**2. "Kling 3.1" appears not to exist.** Searches found Kling 3.0 (launched
5 February 2026, Kuaishou investor relations) and nothing for 3.1. The registry
returns `None` for it rather than resolving it to 3.0, because a prompt built
against limits nobody checked is worse than a refusal.

**3. The version list in the original brief is roughly six months stale.**
Seedance **2.5** (30-second 4K in one pass, up to 50 references) supersedes
2.0; **Wan 2.7 and Wan 3** appear to exist; **FLUX.2** supersedes FLUX.1
Kontext. Cards were written for the versions asked for, and each says so.

**4. The leaderboards disagree wholesale and must not be merged.** Arena puts
Kling v3 first at 1934 Elo. Artificial Analysis puts Gemini Omni Flash first at
1245, with Veo 3.1 down at #11. Different scales, different prompt sets. Any
table that ranks models across both is inventing a comparison neither made.

### The one architecture fact with a named primary source

FLUX.2 is a **rectified-flow transformer** (32B) coupled to a **Mistral-3 24B
vision-language model**, with one checkpoint serving both generation and
editing. For Kling, Veo 3.1, Seedance, Wan 2.6, Runway Gen-4.5 and Sora 2, the
architecture family could not be sourced at all. Vendors mostly do not publish
it. The registry has no architecture field, because a field that is empty for
six of seven entries is a field that invites a guess.

### Unresolved contradictions, left unresolved on purpose

- **Seedance 2.0**: one reading says 1080p native up to 12 s; another cites a
  ByteDance technical report saying 4–15 s at 480p/720p native. Mutually
  exclusive on both axes. The card takes the conservative figure and prints the
  contradiction in its `note`.
- **Runway Gen-4.5**: "720p" vs a review titled "Native 4K"; release date
  "December 2025" vs "29 July 2026".

The rule applied throughout: **a limit understated costs a nicer render; a
limit overstated costs a failed paid call.** Cards take the conservative side.

---

## Track 1b: artifacts, and what the metrics cannot see

The taxonomy that shaped the rule table in `studio/selfrag/reflect.py`:

| Artifact | Cause | Prompt-level mitigation |
|---|---|---|
| Temporal flicker | imperfect local high-frequency temporal consistency | fix the seed first, so it is reproducible before it is "fixed" |
| Tile/seam bands | VAE block-wise decode overlap distortion | not a prompt problem — do not try to prompt around it |
| Chunk-boundary seam | autoregressive error accumulation over chunks | shorter clips; cut rather than extend |
| Identity drift | errors accumulate, features pulled toward the average face | reference conditioning; Kling's `character_orientation=image` |
| Object permanence failure | no persistent state for an occluded object | keep the subject in frame, or cut between shots |
| Hand malformation | occlusion-heavy training data, no structural prior | keep hands occupied or out of frame |
| Text garbling | **character-blind text encoder** — a tokenizer problem, not a resolution one | do not ask for on-screen text; composite in post |
| Physics violation | no dynamics prior; joint caption-and-physics satisfaction is low | one causal action per clip |
| Oversaturation | off-manifold trajectory at high guidance | lower CFG — a parameter, not an adjective |

**Three rules `reflect.py` implements directly from this:**
`_rule_on_screen_text` (text is a tokenizer limit no polish removes),
`_rule_occlusion` (object permanence), `_rule_action_count` (physics falls off
with each chained causal step).

**What the metrics miss**, which is why nothing here reports a single score:

- **FVD is blind to motion.** It rises only slightly under large temporal
  corruption, and a carefully sampled set of near-motionless clips scores well.
- **CLIP-SIM is insensitive to word order, negation, spatial relations, object
  count and attribute binding.** Right objects, wrong arrangement scores high.
- **Warp error is near-perfect on a frozen video.** It must always be reported
  beside a motion/dynamic-degree number or it rewards doing nothing.
- **ArcFace cosine degrades under large pose** and can pass a drifted face at
  an extreme angle.
- **LSE-D can score blurry lips well**; it says nothing about visual quality.

Every one of these is a two-outcome instrument being read as three.

---

## Track 1c: how the vendors actually want to be asked

All five converge on **subject → action → scene → camera → lighting/style**,
with local naming. This is the `skeleton` field of each card:

| Model | Skeleton | I2V change |
|---|---|---|
| Veo 3.x | subject → action → style → camera → composition → focus → ambiance → **audio** | image sets the scene; prompt carries motion and audio |
| Kling | subject → action → context → style *(style = camera + lighting + mood)* | collapses to **subject + movement** |
| Runway Gen-4 | subject → action → setting → camera → motion → style → constraints | motion only; call the person "the subject" |
| Wan 2.x | subject → scene → motion *(with amplitude and rate)* → aesthetic → stylisation | scene and subject slots dropped |
| Seedance | subject → movement → scene → shot → style | same, plus `camera_fixed` |

**The strongest cross-vendor rule found:** in image-to-video, do not re-describe
what the image already shows. Re-describing appearance injects a conditioning
signal that fights the image latent, and the visible symptom is morphing in the
opening frames. `assemble()` drops appearance slots in `i2v` mode and reports
the drop as `dropped_by_design`.

**The second-strongest, and it became a design rule:** where a parameter and a
prompt phrase control the same thing — Seedance's `camera_fixed`, a seed,
motion strength — **the parameter wins and is measurable; the phrase is the
fallback, not the control surface.** `_rule_parameter_beats_prose` flags a
prose clause competing with a real knob as a *violation*, and `auto_reviser`
mechanically converts it.

**Length:** the only published band found is Veo's ~3–6 sentences / 100–150
words. Runway pushes the opposite way for I2V — shorter is better with a strong
image. Nobody has published a controlled length sweep against a quality metric.
Cards carry `word_band=None` where nothing was published, and the rule reports
`unmeasured` rather than inventing a target.

---

## Track 2: RAG, and where the request's premise does not survive contact

### Self-RAG as published is not reachable here, and this is the important finding

Self-RAG (Asai et al., ICLR 2024, arXiv:2310.11511) extends the **generator's
vocabulary** with reflection tokens (`Retrieve`, `ISREL`, `ISSUP`, `ISUSE`),
trains that generator on data annotated by a separate critic model, and runs
segment-level beam search interpolating critique-token probabilities at
inference. **It requires a fine-tuned generator.** There is no version of that
which runs on a CPU against a corpus of a few thousand records.

CRAG (arXiv:2401.15884) fares little better for this use: its largest reported
gains route through **web search** as the corrective action. Offline you keep
the T5-large evaluator's latency and lose the mechanism that earned the
numbers.

Adaptive-RAG (arXiv:2403.14403) routes queries by complexity through a
T5-Large classifier. The *idea* generalises; the classifier is overkill at this
size and is better written as a rule.

**So what got built is Self-RAG in shape, not in method, and the module says so
in its first paragraph.** The same three questions are asked, by code that can
actually answer them:

```
ISREL   is the retrieved set relevant?      grade_context   deterministic
ISSUP   is the draft supported and legal?   grade_draft     deterministic rules
ISUSE   is the draft any good?              judge           optional, injected
```

Claiming otherwise would put a paper's reported numbers behind a system that
cannot produce them.

### Retrieval, at 10³–10⁴ records on a CPU

- **BM25 is a strong baseline and often is not beaten out-of-domain.** Your
  corpus is by definition out-of-domain for any off-the-shelf embedder — it is
  your own prompt/result pairs — which is precisely the regime where BM25 holds
  up.
- **RRF's k=60** comes from Cormack, Clarke & Büttcher (SIGIR 2009). The
  optimum is reported flat across k ∈ [20,100]. Ship 60 and do not spend a
  session tuning it. `studio/selfrag/retrieval.py` imports `RRF_K` from
  `studio.knowledge` rather than re-declaring it.
- **No vector database.** 10k × 384 float32 is ~15 MB; a query is one matvec.
  An ANN index buys a speedup below perception and costs a service, a memory
  floor, a build step and a test dependency. This was the clearest cargo-cult
  item on the list. **Now measured rather than argued: 5.85 ms per search over
  4593 real records** (2026-08-26, single core, FTS5 plus in-process scans). An
  ANN index would shave milliseconds off something nobody can perceive.
- **Cross-encoder reranking is the highest-leverage remaining component**, and
  its real value is not accuracy — it is that its score is a usable
  *abstention* signal, which BM25 and cosine scores are not. Not implemented
  here: on CPU a 0.3–0.6B reranker over 50 candidates is estimated at seconds,
  which is not interactive. Recorded in "not built" below rather than shipped
  unmeasured.

### Fallback, and the finding that shaped the abstention design

Two papers agree on the half that matters: **feeding top-ranked-but-irrelevant
context is worse than feeding none.** ("The Power of Noise", SIGIR 2024, found
near-miss distractors actively hurt; a 2026 follow-up disputes the
random-noise-helps half but not this half.)

That is a direct argument for a score threshold plus abstention, and it is why
`grade_context` **drops** a weak set rather than passing it along at reduced
weight. HyDE and learned query rewriting were both skipped: each prepends a
full generation to every retrieval, and both were validated against
weak or web-search baselines. The rewrite ladder here is deterministic and
free.

### Evaluation

- **Negative controls are mandatory.** `evaluate()` returns `could not measure`
  and reports **no averages at all** if the gold set has no `abstain` rows. A
  number from an instrument with no negative control is worse than no number,
  because it will be quoted.
- **RAGAS is not a CI gate.** It needs an LLM call per evaluation, which breaks
  offline determinism, and it is reported unstable exactly under wrong
  retrieval — the failure mode you care about.
- **LLM-as-judge carries position bias and self-preference bias.** If the same
  model generates and judges, the judgment is contaminated. `judge()` refuses
  to run when the judge callable is the writer callable.

---

## What was deliberately not built, and why

| Not built | Why |
|---|---|
| Self-RAG with reflection tokens | needs a fine-tuned generator; not reachable on this hardware |
| CRAG's corrective web search | offline requirement; the mechanism that earned its numbers is unavailable |
| Cross-encoder reranker | estimated seconds per query on CPU. Worth adding **with a measured latency number**, not before |
| A vector database | 15 MB of vectors. An ANN index is a speedup below perception |
| HyDE / learned query rewriting | a full generation before every retrieval, validated against weak baselines |
| RAGAS in CI | LLM calls in tests; unstable in the failure mode that matters |
| Tuning RRF's k | reported flat across [20,100] |
| A learned re-ranker over feedback | a few hundred rows would fit noise. A bounded multiplier a human can read and mutate is the honest instrument at this size |
