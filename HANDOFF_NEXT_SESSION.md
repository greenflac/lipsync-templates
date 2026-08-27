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
