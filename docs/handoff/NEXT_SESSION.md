# Next session starts here: the debt comes first

Written at the close of the session that ended at HEAD `0a997e6` on
`fix/exact-9x16`. Everything below is either measured in this tree or marked
as someone else's claim.

## 1. The debt, and it is one question with three answers

Nothing in this branch has been run against a live pipeline. The whole 9:16
fix rests on tests and on reading the code. Three questions, one paid run
answers all three:

1. Does the image route honour a requested size? `compose` used to default to
   768x1024 (3:4) while its siblings were vertical, and that mismatch — not the
   prompt — was why styled references came back letterboxed. The default is now
   derived from one place, but no live call has confirmed the gateway obeys it.
2. Is the first frame free of bands **by eye at full resolution**? Not by
   metric. Four separate bar detectors were built in this project and all four
   were confidently wrong: uniformity missed blurred padding, sharpness flagged
   smooth sky, a wall, a ceiling and grass. Only eyes settled it.
3. What size does Kling actually return? See the contradiction in §2 — this run
   is what settles it.

`--live` is required for any model call; without it every route is a no-op.
Keys come from the environment. Print variable NAMES, never values.

## 2. The contradiction that must be settled by that same run

Two constants in this branch both claim MEASURED about the same fact:

    fork_e2e.KLING_OUT_SIZE = (960, 960)   # eight shipped orders, all square
    fork_plan.FRAME = (720, 1280)          # "Kling returned exactly this size
                                           #  on every one of six shipped clips"

They cannot both be right and the arithmetic reconciles neither way: 960x960
cropped to 9:16 is 540x960, not 720x1280. A third observation exists — a live
order returned 816x1104 after a 768x1024 photo went in, which suggests the
model inherits the reference's proportions rather than having a fixed output.
If that is so, both constants are descriptions of past inputs, not properties
of the model, and both marks are wrong in kind rather than in value.

One live order decides it. Until then neither number may be quoted as a
property of Kling.

## 3. Open, ordered by what would embarrass us first

- `OUT_RATIO_MAX` is a ceiling with no floor: a square passes the gate for
  vertical video. `FINDINGS.md` proposes `OUT_RATIO_MIN = 0.5`. Product call.
- `FRAME_SUFFIXES` lives twice (`fork_e2e` as a set, `fork_looper` as a
  tuple); `MIN_VISIBILITY` lives twice (`pose`, `fork_plan`). Both are real
  duplicates by the test that matters: change one and the other must change,
  and will not.
- The provenance gate sees only constants a branch compares against directly.
  Constants passed into a helper that compares inside — `SHOULDERS_BAND`,
  `ANKLES_BAND` — are not demanded. Known gap; measure it before widening.
- MediaPipe's licence is not established: no file, no README line, only an
  extra in `pyproject.toml` and a weights URL. It may be non-free. Nobody has
  looked outside the tree, and the proxy policy is not to be worked around.
- `test_device.py` imports helpers from `test_fork_finish.py`, and both
  duplicate logic that now lives in the gate.

## 4. What is safe to show

`fix/exact-9x16` at `0a997e6`: `scripts/check` exits 0 — ruff clean, mypy
clean on 39 files, `Ran 1000 tests in 114.551s / OK (skipped=12)`. The 12
skips are one class, the one that needs ArcFace weights that are not shipped;
a skip is not a pass and it is named here rather than after being asked.

## 5. Other branches, as of this close

- `studio/prompt-layer` (lipsync-templates): the prompt layer plus the
  discovery fix. `Ran 1016 tests / OK (skipped=12)`. Not merged anywhere.
- `claude/instories-orchestrator-k5fy4h` (cyclerunner): merged with the 14
  commits another session had pushed, counters re-derived. Three errors remain
  there, all from one f-string that needs Python 3.12 while that repo's README
  claims 3.11+ — the floor is stated twice and the two disagree.
- `docs/course/` is deliberately NOT in any repository and is in .gitignore by
  name. It was handed over as files. Do not commit it back.

## 6. Final audit: 39 checked, 14 violations, 3 unmeasurable

Run by an agent that took no part in the work, on throwaway copies, with
every substitution grepped back off disk before the run. It reproduced the
headline figures exactly (`Ran 1000 tests in 116.970s / OK (skipped=12)`,
`SCRIPTS_CHECK_EXIT=0`, 39 source files clean), confirmed the gate was
committed red and never edited by the writers who greened it, and found no
secret in any of the 630 objects in the repository's history.

Four findings are new. They are listed first because nothing else in this
handoff is unknown.

### 6.1 A repair that hides a breakage — CLOSED, see the note at the end

`fork_e2e.similarity_source()` — since removed — named the instrument by
whether it *imported*,
not by which branch actually ran. The auditor planted a `creative_eval` that
imports and then throws: the report named
`creative_eval.style.similarity (external, shipped)` while the number came
from `palette_similarity`, the coarser fallback — and the exception text
(`model weights corrupt: checksum mismatch on style.bin`) was discarded whole
by two bare `except Exception`. The tests cover "absent" and "present"; they
do not cover "present and broken", which is the case that ships.

This quietly corrupts every future style measurement, and it is the exact
mechanism rule S13 exists for: the repair masks the breakage, and when the
repair itself fails the defect reaches the client.

### 6.2 The truncation sweep was never run across the repository

`fork_e2e.py` is clean. The same form is alive in 16 places elsewhere:
`fork_intake.py` x6, `fork_video.py` x5, `fork_looper.py` x3,
`fork_aesthetic.py` x1. Rule I7 asks for the grep before the fix; the fix was
made in one file and the grep was not done. Do the sweep, then fix, and put
the count in the commit.

### 6.3 A duplicate introduced by this session's own work

`PROVENANCE_MARKS` is now declared twice — `test_fork_finish.py:137` and
`test_product_shape.py:282` — with two independent block extractors beside it
(`provenance_block` by regex, `_provenance_block` by lineno). Add a fourth
mark to one and the other goes blind. This is the rule the session spent the
day enforcing, broken while enforcing it.

### 6.4 CI has never run on this branch

`.github/workflows/ci.yml` triggers on `push: branches: [main]` and on
pull_request. This branch is pushed and has no PR, so not one CI run exists:
every green figure here comes from one developer machine. K7 asks that the
local check and CI be one source of truth; right now only half of it is
observable.

### 6.5 Two more, measured rather than asserted

- The provenance gate's blind spot has a number: 176 top-level constants, 46
  demanded, 42 passed into a call and therefore not demanded, **37 of those
  unmarked** — `SHOULDERS_BAND`, `ANKLES_BAND`, `CARD_TOL_MIN/MAX`,
  `PROBE_TIMEOUT_S`, `NAME_DIGITS` and the rest.
- `test_fork_identity.py:654` carries a guard that says "A skip is not a
  pass" — and it sits *inside* the class the skip disables, so the same
  condition switches off both the tests and their watchman. Twelve skips
  currently pass through `scripts/check` with exit 0.

### 6.6 What the audit confirmed as sound

Nine untouched thresholds were mutated both ways, 18 runs: all nine clamped
on both sides. Forty-nine provenance marks were stripped one at a time: 47
reddened on exactly their own constant, the other two being private caches the
gate does not demand. Three commit bodies were checked against their diffs and
matched. Nineteen commits, zero non-conventional. No source-text test remains.

### 6.7 Drift, named rather than hidden

The branch is called `fix/exact-9x16` and its last three commits have nothing
to do with the frame ratio: they close an external audit and mark provenance
on 39 constants across 12 modules. The reason is written down in this file, so
the drift is explained rather than silent — but a branch named for a frame
format now carries 463 lines about where constants came from. Worth splitting
if it ever goes to review as a unit.

## 7. The showcase in the README is pre-fix material — do not ship it

Measured on 2026-08-28 by opening the files, not by a metric.

`docs/img/family.png` is the six-template strip the README shows on every
branch including main. Enlarged 2x and looked at: roughly four of its six
panels carry the blurred band at top and bottom — the same defect this branch
exists to remove, and the same "four out of six" the owner reported when the
investigation started. The README's own showcase advertises the bug.

The source is worse than the strip. The six shipped clips live in the retired
engine's tree, `ball-reel/work/six/<name>/final.mp4`, six files, 720x1280, 300
frames, made 2026-08-23 — before the fix. Cropping 150px off the top and the
bottom of `midcentury`, `fisheye` and `country` at original resolution and
looking at the result: every one of the six strips is a blurred smear, not
image content. A contact sheet built from their first frames shows the same
thing at a glance.

So there is no clean demo material anywhere. The fix is in the code and has
never been run against the service, which means the live run in §1 is not only
how the three questions get answered — it is also the only way to produce a
showcase that does not display the defect.

Until then: `family.png` stays as it is rather than being cropped or retouched
(a retouched showcase of a fixed bug is a different kind of lie), and no new
demo media goes into the repository. The six clips are 26 MB in total and exist
in exactly one copy, on an ephemeral container; they were handed to the owner
as files.

Note on where the evidence was: all of it sat in `ball-reel`, the engine
declared retired. It was excluded from an evidence search once before and that
cost a wrong correction; this time it held the artefacts that settled the
`KLING_OUT_SIZE` / `FRAME` contradiction as well.
