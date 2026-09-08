---
name: prompt-engineer
description: Write a generation prompt for a named image or video model (Flux, Kling, Veo, Runway, Wan, Seedance), grounded in a prompt corpus that is collected LOCALLY and deliberately NOT committed (licensing: the prompts are other people's work) — so on a fresh clone there is no corpus at all, and none of it has been run or rated by us. Use when the user asks for a prompt, asks to improve a prompt, asks which model can do something, asks why a generation came out wrong, or asks to record how a generated result turned out. Do NOT use for the studio product's own styling path, which goes through studio.style.
---

# Prompt engineer

A prompt written from memory is a guess about a vendor's limits. This skill
writes prompts from two things that can be checked instead: a registry of what
each model actually accepts, and this repository's corpus of prompts harvested
from vendor galleries and Civitai.

ЧТО В КОРПУСЕ НА САМОМ ДЕЛЕ. Прежняя редакция этого абзаца обещала промпты,
«которые прогнали и оценили». Две правки 2026-09-04, обе — про одно и то же
враньё в разных его видах:

1. ИЗМЕРЕНО на машине, где корпус собран: 13 316 записей, оценённых НОЛЬ,
   прогонов в журнале ноль. Обещание держалось на том, что петля оценки
   написана и пуста.
2. НА СВЕЖЕМ КЛОНЕ КОРПУСА НЕТ ВООБЩЕ. Он не коммитится намеренно (лицензия:
   промпты — чужая работа, см. `.gitignore` и `studio/knowledge/PROVENANCE.md`),
   и число «13 316» верно там, где я стою, и неверно там, где стоит читатель.
   Поймано на том, что CI покраснел на моём же тесте: в чистом клоне записей 0.

Поэтому здесь не обещается ни оценок, ни самого корпуса: он собирается локально,
и первое действие навыка — проверить, есть ли он вообще.

## Before anything else

Run this. It is fast and it tells you whether the corpus exists at all:

```bash
python -m studio.selfrag cards
```

If the corpus is missing, every prompt below still assembles but no precedent
informs it, and the tool says so on every run. Do not paper over that in your
summary to the user — a run with `retrieved 0` is a run with no evidence
behind it.

## Writing a prompt

```bash
python -m studio.selfrag write \
  --model veo \
  --mode t2v \
  --text "a rain-slick rooftop at dusk, amber golden-hour light, film grain, nostalgic" \
  --subject "a lone cyclist" \
  --action "rides slowly past" \
  --camera "slow dolly in, low angle" \
  --audio "distant traffic and wind" \
  --constraint "warped background" \
  --duration 8 --aspect 9:16
```

`--text` is the LOOK, in the user's own words. `--subject`, `--action`,
`--camera`, `--motion` and `--audio` are the vendor's own slots. You do not
choose the slot order — the model's card does, from its published guide.

Modes: `t2v`, `i2v`, `t2i`, `edit`. In `i2v` do not pass `--subject`; the
reference image already carries appearance, and every vendor guide that
discusses image-to-video says re-describing it fights the image latent. The
tool drops it for you and reports the drop, but passing it wastes the slot.

## Reading the answer

The exit code is the verdict: **0 pass, 1 fail, 2 could not measure**. The
third is not a soft pass. Treat it as "this prompt is not backed by what it
claims to be backed by" and say which part was unmeasured.

`findings` come in four severities and they mean different things:

| severity | what it means | what you do |
|---|---|---|
| `violation` | the prompt is wrong — a field was dropped, a dead clause was kept | do not ship it; fix or report |
| `risk` | a documented failure mode is invited (on-screen text, occlusion, a chained action) | tell the user before they pay for the render |
| `caveat` | a standing limitation, true on every run | mention once, do not repeat per prompt |
| `unmeasured` | a check could not run on this draft | say which check |

## When there is no precedent

The retriever widens the query up to three times, then abstains. Abstaining is
the correct answer and the run reports `rewrite_step` so you can see how far it
walked. Do not fill the gap by inventing an example prompt and presenting it as
if it came from the corpus. Say the corpus has nothing for this and write the
prompt from the card alone.

## Recording how it actually went

This is the half people skip, and the corpus is worthless without it:

```bash
python -m studio.selfrag rate \
  --record-id "prompts.jsonl:7" \
  --prompt "<the prompt that was run>" \
  --model veo-3.1 --rating 8 --artifact out/rooftop_01.mp4
```

`--artifact` is required for the entry to count as an observation. A rating
with no path to what was produced is a claim nobody can open later, and the
tool records it as `could not measure`.

## Checking the system itself

```bash
python -m studio.selfrag report                        # the run journal
python -m studio.selfrag eval                          # recall/precision + controls
python -m studio.selfrag eval --channels bm25          # a mutation: drop a channel
```

## Facts to hold onto

- **Sora 2's API is scheduled to stop on 2026-09-24**; its app went on
  2026-04-26. The registry refuses it after that date rather than letting a
  paid call 404.
- **There is no evidence "Kling 3.1" exists.** `card_for("kling-3.1")` returns
  nothing on purpose. Do not resolve it to 3.0.
- **Every model card is second-hand.** They were assembled from search
  summaries because the vendor documentation was unreachable. They are good
  enough to shape a prompt and refuse an impossible request, and not good
  enough to bill a customer against.

## What this skill is not for

The studio product's own path — client selfie plus motion template — goes
through `studio.style.build_prompt`, which carries the no-brands clause and the
subject-zone guard that path depends on. Use `studio.selfrag.spec.studio_prompt`
if you need it from here, and never hand-assemble that prompt.
