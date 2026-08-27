# Findings about the CLASS, and why they are not in the fact base

`class_findings_2026-08-27.jsonl` holds 158 statements harvested on 2026-08-27
whose `model` is `"*"` — they are true of a technique or of a whole generation
of models, not of one model somebody can look up. "Subject-consistency scores
are maximised by a video that does not move" is a fact about the METRIC.
"Six iterative edits is where re-encoding artifacts become visible" is a fact
about iterative editing.

## Why they are kept out of `model_facts.jsonl`

The fact base is keyed on `(model, attribute, value, source_url)` and every
question put to it starts with a model name. A row whose model is `"*"` would
either be invisible to every query, or — if `"*"` were treated as a model —
create one pseudo-model holding 158 unrelated claims that contradict each
other by construction. That is precisely the flattening the base exists to
prevent, so the boundary is: one model, one row; the class goes here.

## What is UNVERIFIED about this file, stated up front (Ц4)

The adversarial pass returned its rejections as `model.attribute` keys. For a
named model that is exact. For these, every rejection reads `*.failure_mode`,
`*.metric_blind_spot` and so on — one refuted claim and forty untouched ones
share a key, and the report does not say which was meant.

MEASURED: taking those keys literally would reject 156 of the 158 rows; taking
them as one-claim-each would reject at most 6. Neither reading is supportable
from what the refuters returned, so **no row here has been through a
verdict**. That is the third outcome — не смогли проверить — and it is why
these are a document rather than facts.

To promote any single row: read its `source_url`, check the quotation in
`evidence`, and record it against the specific model it turns out to bind to.

## The four that changed how the rest of this work is read

1. **Subject consistency, background consistency, temporal flickering and
   motion smoothness are all maximised by a static video.** VBench's own
   authors say so. Every one of those four is near-saturated across current
   models, so a model that "wins" them has not been shown to hold a face.
2. **The number that does measure identity is VBench-2.0's Human Identity,
   and the best model measured scores 78.57%** — the axis nobody quotes is
   the one that is not saturated.
3. **A published win can belong to a version nobody can download.**
   HunyuanVideo's beat over Gen-3 and Luma was measured on an unreleased
   high-quality build, disclosed in one sentence in the comparisons paragraph.
4. **Preference leaderboards select for the look, not for directability.**
   A leaderboard position is evidence about what people pick from a pair, and
   that is a different claim from "it will do what the prompt says".

## The structural finding, which is itself the most useful thing here

Of the open-weight video model cards read in this pass, only Stable Video
Diffusion, Mochi 1 and LTX-Video carry an explicit LIMITATIONS section.
CogVideoX, HunyuanVideo, HunyuanVideo-Avatar and the whole Wan 2.2 family
carry none at all — HunyuanVideo-Avatar, the most lipsync-relevant card of
them, is abstract plus run commands. On the image side FLUX.2 [dev],
FLUX.1 Kontext [dev], Qwen-Image, Z-Image-Turbo, HunyuanImage-3.0,
HiDream-I1-Full and Lumina-Image-2.0 have no limitations section either.

So for most open-weight models the answer to "what does it get wrong" is not
"nothing" and not "unknown" — it is **the vendor has not said**, and any
answer has to come from a paper, an issue tracker, or a measurement somebody
pays for. That is the gap `propose_measurement` exists to put in front of the
operator.
