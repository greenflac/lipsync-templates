# How specialist agents are actually built — and the finding that reverses our plan

Three parallel research tracks, 2026-08-26, run before wiring a generator.

**Read the channel caveat first (Ц4).** This environment's egress proxy blocked
`arxiv.org`, `aclanthology.org`, `dspy.ai`, `databricks.com`, `dl.acm.org`,
`cdn.openai.com` and most vendor docs. Across all three tracks exactly **five
pages were opened directly**: the DSPy optimizer docs, the GEPA paper mirror on
HuggingFace, the RAFT mirror, the Wan2.2 README with its `prompt_extend.py`,
and the Hunyuan PromptEnhancer README. Everything else is a search engine's
summary of a source, and is marked WEAK. Numbers below may be misattributed.

---

## 1. The finding that reverses the plan

**Jahani et al., *As Generative Models Improve, We Must Adapt Our Prompts***
([arXiv 2407.14333](https://arxiv.org/abs/2407.14333), published in
*Information Systems Research*,
[DOI 10.1287/isre.2025.2029](https://pubsonline.informs.org/doi/10.1287/isre.2025.2029)).
Randomised, N=1,891 participants, 18,000+ prompts, 300,000+ images, blind,
incentive-paid, target-reproduction task. Three arms: DALL·E 2, DALL·E 3, and
DALL·E 3 with automatic GPT-4 rewriting.

- Users given the better model spontaneously wrote **24% longer** prompts, and
  roughly **half the total gain came from that adaptation** rather than from
  the model.
- **The automatic-rewriting arm erased 58% of the improvement.** The stated
  cause: rewrites "added extra details or changed the meaning".

That third arm is, structurally, the thing this project was about to build: an
external expander in front of a generation model.

Alongside it, [a survey of T2I quality metrics](https://arxiv.org/pdf/2403.11821)
reports prompt length correlating with quality at about **−0.07** — no
relationship — with prompts under ~200 characters scoring highest.

**The reconciliation, and it is the design rule:** longer helps when the added
words carry *the user's* intent, and hurts when a model invents them. Length is
a proxy, and a weak one.

### What this retroactively says about today

Two fixes made earlier today removed exactly this failure. The synonym map had
turned the user's word "stone" into a "sand" palette and the generator drew
sand; `DEFAULTS` had put "matte" onto a glossy glass bottle. Both were details
the user never asked for, invented by the machine. The literature says that is
not a bug we happened to have — it is *the* documented failure mode of this
entire product category, and it cost 58% of a model generation's worth of gain
in a controlled trial.

**The threat model is intent drift, not insufficient length.** Every claim in
`quality.py` about our prompts being "five times too short" must be read in
that light: it says how the corpus writes, not what generates better pictures.

### Two more datapoints pointing the same way

- **Midjourney shipped `/shorten`, not an expander** — it scores each token's
  impact 0–1 and strikes the low ones. The vendor with the most prompt
  telemetry in the industry built a trimmer. (WEAK: Midjourney's own docs were
  unreachable; third-party writeups only.)
- **DALL·E 3's rewriter cannot be disabled**
  ([OpenAI cookbook](https://cookbook.openai.com/articles/what_is_new_with_dalle_3)).
  An external expander there is stacked on a mandatory internal one — literally
  the losing arm.
- **Wan ships an expander behind `--use_prompt_extend`**, rewriting to ~80–100
  words, and *recommends enabling it while publishing no measured gain*
  ([Wan2.2 README](https://github.com/Wan-Video/Wan2.2), read directly). No
  vendor document was found for a Seedance or Kling expander — earlier claims
  that these exist are UNVERIFIED.

Recorded as facts in `studio/knowledge/model_facts.jsonl` under
`expands_internally`, so the writer can refuse to double-expand.

---

## 2. The closest prior art, and how its grounding differs from ours

**RAPO** ([CVPR 2025](https://github.com/Vchitect/RAPO), arXiv 2504.11739) is
the only retrieval-grounded prompt optimiser with published gains. It mines
modifiers into a relation graph, retrieves relevant ones, and runs that branch
in parallel with a plain LLM rewrite, then selects.

Its load-bearing choice: **RAPO retrieves from the generator's TRAINING prompt
distribution**, not from a gallery of prompts humans liked. The mechanism that
works is "phrase this the way the model was trained to hear it" — which is also
DALL·E 3's and Wan's stated rationale.

Ours is grounded differently, and it is worth being clear-eyed: a curated
gallery is a weaker signal than a training distribution. What we have that the
public corpora do not is **outcome ratings per model** — DiffusionDB (14M),
JourneyDB (4.4M) and the CivitAI dumps are prompts that were *run*, not prompts
that *worked*. That is the genuine differentiator, and it is exactly what the
replay buffer collects and currently has zero rows of.

The other warning from this literature:
[*No Longer Trending on Artstation*](https://arxiv.org/abs/2401.14425) (3M+
prompts) finds prompting converges on "surface aesthetics, reinforcing cultural
norms and popular conventional representations". A corpus of popular prompts
encodes convergence — retrieval from it will make outputs more alike.

---

## 3. Where the industry puts its optimisation, and what it means for us

**DSPy** ([optimizer docs](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/learn/optimization/optimizers.md),
read directly) is the mature answer to "I have a corpus and a metric". Its
stated data requirements:

| optimizer | examples needed |
|---|---|
| `BootstrapFewShot` | ~10 |
| `BootstrapFewShotWithRandomSearch` | ≥50 |
| `MIPROv2` (full) | **≥200**, to avoid overfitting |

Every optimizer needs a callable `metric(example, prediction) -> score`. We have
one — `quality.py` — and `KNNFewShot` already implements dynamic few-shot
natively, which is the pattern we were about to hand-roll.

**GEPA** ([paper mirror](https://huggingface.co/papers/2507.19457),
[code](https://github.com/gepa-ai/gepa), Jul 2025) is the current strongest
optimiser: reflective prompt evolution over a Pareto frontier, consuming
*textual* feedback rather than a scalar. Reported +10% average over GRPO with
up to **35× fewer rollouts**, and >10% over MIPROv2.

The honest caveat on adopting it: our metric would be `quality.py`, and the
evaluation research says a reference-free distributional score is an
out-of-distribution guard-rail, **not** a ranking. Optimising directly against
it would be optimising a proxy with a known length artefact. **An optimizer is
only as good as its metric, and ours is not yet good enough to optimise
against.** That, not the tooling, is the blocker.

**Nothing else closes the loop.** Neither LangGraph, the OpenAI Agents SDK,
Pydantic AI nor the Claude Agent SDK ships an optimizer that ingests production
outcomes and emits an improved artifact; they ship tracing and stop. The
closing is done by DSPy/GEPA, by ACE
([arXiv 2510.04618](https://arxiv.org/abs/2510.04618)), or by hand.

---

## 4. What this changes about the generator we were about to build

| was going to build | build instead |
|---|---|
| an expander: short request → long prompt | an **intent-preserving rewriter** whose default is to add nothing |
| success = closer to corpus length | success = **intent preserved**, measured with a negative control where adding nothing is correct |
| same treatment for every model | check `expands_internally` first; for a model that expands, **shorten and sharpen** |
| judge with whatever model is handy | never the writer's own model; pairwise with the order swapped; disagreement is `could not measure` |
| 2-pair A/B | ~188 non-tie comparisons for a 60% win rate; below ~0.75 a 20-item A/B establishes nothing |

The negative control this needs is one we do not have: **a request where the
correct output is the user's own sentence, unchanged.** If the agent cannot
leave a good prompt alone, everything else it does is downside.

---

## What could not be verified

- Every number in §1 and §2. The 58%, the 24%, the −0.07 and RAPO's gains are
  all search-engine summaries; `arxiv.org` was blocked throughout. **Before
  betting the design on the 58%, somebody must read arXiv 2407.14333.**
- Whether Seedance or Kling expand internally. No vendor document found.
- Any vendor-published measured gain from a prompt expander, anywhere. Wan
  recommends one with zero numbers; nobody else publishes an ablation.
- DSPy's claimed production users. The README names none.
- Licences for DiffusionDB, JourneyDB, the CivitAI dumps and Hunyuan
  PromptEnhancer — Ц5 applies before any is embedded.
