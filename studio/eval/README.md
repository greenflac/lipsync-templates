# Expert evaluation set for `plan_pipeline`

`briefs.jsonl` holds 150 customer briefs (the **dev** split). Each row has the `spec` a competent
caller would write from the tool description, plus an **expert reference plan** written the way a
senior GenAI engineer would write it. `scripts/eval_plans.py` runs `plan_pipeline` in-process on
every spec, scores the answer against the reference, and prints expert-correct % per job class
and in total. `scripts/check` runs it with `--check` against `baseline.json`.

Why it exists: seven fix rounds were steered by one-off graders. Each grader re-derived "correct"
in prose, and the next round patched one finding at a time. The round-7 validator measured 64/108
plans as expert-correct and said this converges too slowly. This set fixes the definition of
"correct" so that a change is measured against all of it, not only against the finding that
prompted the change.

```
python scripts/eval_plans.py                    # dev set: table + JSON report
python scripts/eval_plans.py --only w07_drone -v  # one brief, every failed dimension
python scripts/eval_plans.py --check            # red if any class or the total regressed
python scripts/eval_plans.py --write-baseline   # after a deliberate improvement, same commit
python scripts/eval_plans.py --briefs <holdout.jsonl> --baseline <holdout_baseline.json> --check
```

## Holdout

There are 50 more briefs in the same format, the **holdout**. They are deliberately **not in the
repository**: they were written by the eval agent and are kept by the orchestrator, outside the
checkout, so fixers never see them. Holdout scores measure whether fixes generalise; dev scores
may partly reflect memorisation. The split is stratified by class: about 25% of every class is
held out, chosen by hashing the ids. Do not copy holdout briefs into this directory.

## Row format

```json
{"id": "w15_8kfilm", "class": "upscale", "source": "round7-validator", "tags": ["knowledge_gap"],
 "brief": "...customer words...", "spec": {...caller-filled spec...},
 "ref": {
   "outcome": "plan",                         // or a list of acceptable outcomes
   "steps": [{"job": "t2v", "models": {"require": {"native_res_min": 2160}}},
             {"job": "upscale_video", "models": {"any": ["seedvr2-(3b|7b)", "topaz-upscale-video.*"]}}],
   "paths": [[...], [...]],                   // instead of steps: alternative sequences, best one counts
   "ordered": true,                           // required steps must occur in this order (default)
   "optional": ["interpolate"],               // allowed but not required
   "forbidden": ["t2i"],                      // fails decomposition if present
   "price": [1.5, 30],                        // clip price band in USD (pipeline_price.за_ролик.usd)
   "notes": [{"id": "eight_k", "any": ["\\b8k\\b", "7680"]}],
   "rationale": "why an expert plans it this way",
   "facts": ["model_facts: kling-3.0-4k-t2v price_unit_second_usd $0.42/s", "..."]
 }}
```

**Job codes** are the scorer's names for the planner's operations (`STEP_JOB` in the script):
`t2v, t2v_audio, i2v, r2v, t2i, image_edit, tts, voice_clone, dub, lipsync, avatar, char_replace,
v2v_edit, upscale_video, upscale_image, restore, colorize, interpolate, bg_remove_image,
bg_remove_video, transcribe, music, sfx, turntable`. A reference may also name jobs that **no
planner operation produces today**: `face_swap, v2a, captions, 3d, ...`. That is deliberate. The
reference says what an expert requires, and such a brief stays red until the planner gains the
job. A step may give alternatives, e.g. `["face_swap", "char_replace"]` together with a face-swap
model set.

**Outcomes**, as read off the answer:

| ref value | answer |
|---|---|
| `plan` | steps present, `outcome` pass or could-not-measure (unconfirmed plan, unpriced step) |
| `plan_failed` | steps present, `outcome: fail` from the validator (never the expected value) |
| `question` | `reason` нужен_ответ_заказчика / нужна_спецификация, or people policy `question` |
| `refuse` | `reason` запрещённая_тема or people policy `refuse` |
| `gap` | `reason` работа_не_поддерживается (a recorded job gap, e.g. sign language) |
| `over_budget` | `reason` дороже_потолка or `budget.outcome: fail` |
| `assembly_only` | `reason` только_монтаж (ffmpeg / editor work only, 0 usd) |

## Rubric

A brief is **expert-correct** when every dimension its reference states passes. A dimension the
reference leaves open is not scored, for example when there is no price band, no model constraint
or no note.

1. **decomposition**: each required step is matched to a distinct plan step (in order unless
   `ordered: false`); no unmatched plan step outside `optional`; no `forbidden` job; a step's
   `shots_max` caps how many generations the plan makes there. For example, "the same host in 5
   shorts" means ONE host image (`shots_max: 1`), not five.
2. **models**: the chosen model of each matched step must satisfy the step's set. `any` is a list
   of regexes, matched in full against the lower-cased model id. `none` excludes models.
   `require` is a constraint read off the fact base through the registry:
   - `native_res_min`: the largest recorded output height (`Endpoint.resolutions`; prose such as
     "no 4K" is not read as 4K);
   - `open_weights`: self-hostable, or weights recorded as open;
   - `no_failure_on`: no `failure_mode` / `degrades_when` / `limitation` row mentions the term.

   Families named by regex are curated by hand, e.g. "Wan 2.1/2.2, not 2.5+/3.0, which are
   API-only". A model that only the registry calls open is not trusted on that flag alone.
3. **price**: `pipeline_price.за_ролик.usd` must lie inside `[lo, hi]`. An unpriced plan fails a
   band. The bands are market bands built from fact-base unit prices (cited in `facts`). They are
   roughly 0.4× the cheapest reasonable route to 2.5× the premium route, and they are meant to
   catch order-of-magnitude errors: $48 of t2v for a visualiser, an 8K upscale billed at the
   $0.0072/s 1080p tier, $720 of t2v for a DJ set. They are not meant to referee cent-level
   rounding. For a non-USD budget the band's upper edge is the converted budget.
4. **notes**: each required note must be matched by one of its regexes **in the prose of the
   answer**: string values only, excluding the caller's echo (`brief`, `understood_as`,
   `stated_conditions`, `spec_needed`) and quoted evidence or per-candidate bookkeeping
   (`evidence`, `alternatives`, `*_note`, `registry`, `requirement`). The negative control below
   is why.
5. **outcome**: the observed outcome is in the reference's accepted list.

The set exercises these dimensions:

| dimension | dev briefs that state it |
|---|---|
| models | 68 |
| notes | 44 |
| price | 110 |

**`knowledge_gap`** (13 dev briefs) marks references that depend on facts the base does not yet
hold. Examples: which video upscalers reach 8K, MPS support for local lipsync, scratch removal for
film, ≤$0.01/image t2i prices, real-time avatars, profile-angle lipsync failures. In these briefs
the reference states what an expert would require. They measure the knowledge base as much as the
planner.

## How the references were validated

- **Second pass, adversarial: 20 briefs re-derived from the fact base.** The sample was w15, w23,
  n30, x05, x07, x08, x17, x36, w09, n28, sh04, sh01, e02, b06, d04, i03 and b02, plus 3 holdout
  briefs whose ids are withheld here. Each reference was re-derived by re-reading
  `model_facts.jsonl`, with the aim of breaking it. Items 1–7 and 9 below are disagreements, each
  fixed in the reference. Items 8 and 10 are confirmations:
  1. The fal `seedvr2-upscale-video` endpoint caps at 2160p (`max_resolution`). The 8K upscaler
     set is now self-hosted SeedVR2 or Topaz. The ByteDance upscaler's tiers stop at 4K.
  2. The shared list of English-only TTS models wrongly included `chatterbox`: a vendor
     `languages` row lists 23 languages for it.
  3. LTX-2.5 is open weights under the LTX-2.x community licence (vendor row). The registry flag
     on the `ltx-2.5-t2v-fast` endpoint said otherwise. Curated open-family regexes replaced the
     registry `open_weights` flag.
  4. `pyannote-speaker-diarization-3.1` is diarization without ASR, so it is not an acceptable
     transcription step.
  5. The fal `latentsync` endpoint has probe-tier failures: the mouth keeps 14% of its sharpness
     and the clip is truncated. It is excluded from "cheapest" and from the self-hosted lipsync
     sets. LatentSync 1.6, retrained at 512 px, stays.
  6. x08: the old rationale claimed an MPS failure that no row records. It was rewritten to cite
     the probe failure.
  7. MMAudio v2 *is* in the base ($0.001/s, video+text in), so the V2A briefs are a planner
     registry gap, not a knowledge gap. The tags were removed.
  8. Eleven v3's vendor list includes kk, sw, yo, bn and th, which confirmed w09.
  9. b02: the base's cheapest priced t2i is $0.02/image, so 1000 images under $10 rests on
     knowledge the base lacks. The brief is tagged `knowledge_gap`.
  10. e02 was confirmed: `wan-2.7-edit-video` is a 2–10 s edit model, not an extender.

  w15 and w23 were also confirmed. ByteDance stops at 4K. `topaz-restore-image`'s Dust-Scratch
  model is image-only, so scratch removal for video stays a knowledge gap. n28, d04, i03, b06,
  x36, sh01 and x05 were confirmed as well, some with no fact row either way. Fixes 3 and 5
  also changed briefs outside the sample that use the same model sets.
- **Negative control on notes.** Every note regex was run over the answers whose reference does
  not ask for it. On the first draft, which searched the serialised JSON, key names satisfied
  notes on 131–134 of 150 unrelated answers. Examples: `step_label` read as a labelling remark,
  `vram_gb`, `licence_blocked_count`, `hosting_jurisdiction: null`, "video **from scratch**" for
  scratches, "22.**39** usd" for 2.39:1. After the change to prose-only matching and tighter
  regexes, the remaining false fires are on topically related answers, for example interpolation
  wording on other fps briefs.
- **Agreement with the round-7 grader on the 108 shared briefs: 96/108 (89%).** All 25 of its N
  verdicts are also wrong here. 7 of its partial verdicts score correct here. 5 of its Y verdicts
  score wrong here, because this rubric is stricter in stated ways:
  - n17 and x11: captions were asked for, and the answer never says they are burned at assembly.
  - w30: 2.39:1 is never mentioned as a crop or letterbox.
  - n23 and x07: the licence terms for commercial use are never named.

## Baseline (eeff44c)

| split | expert-correct |
|---|---|
| dev | 89 / 150 (59.3%) |
| holdout | 29 / 50 (58.0%) |

Per class: `baseline.json`. Failed dimensions on dev: models 27, notes 27, decomposition 15,
price 11, outcome 10.

## Updating

- **A fix that raises a class:** run `--write-baseline` and commit `baseline.json` with the fix.
  The gate then holds the new level.
- **A reference that is wrong:** fix the row, say why in the commit, and re-run the baseline. A
  reference is changed for being wrong, never to make a plan pass.
- **References that read the fact base** (`require`) move when the base moves. That is intended:
  the claim "this model renders 4K" lives in one place.
