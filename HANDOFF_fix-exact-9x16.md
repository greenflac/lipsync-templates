# HANDOFF fix/exact-9x16 — one frame for the whole pipeline

## 2026-08-26 — unification onto `fork_plan.FRAME` (not committed, working tree only)

Owner's decision: one frame by resolution. Gate `lipsync/tests/test_one_frame.py`
was written by someone else and was NOT edited.

- `fork_plan.FRAME = (720, 1280)` — MEASURED (six shipped clips: Kling returned
  this size, all six final videos carry it). Single declaration.
- `fork_plan.EXTEND_SIZE = FRAME` (was literal 1152x2048).
- `pollinations.PLAN_SIZE = fork_plan.FRAME` (was literal 1152x2048).
- `fork_e2e.STYLED_SIZE = fork_plan.FRAME` (was literal 720x1280).
- Layering: the gateway now imports the domain module. Deliberate — the gate
  requires `fork_plan.FRAME` to be the source, no import cycle exists
  (`fork_plan` reaches `pollinations` only from inside a function), and a
  neutral leaf module would move the declaration out of the modules the gate's
  ast check watches.

Runs: gate 7 tests OK; full suite `Ran 896 tests ... OK (skipped=12)`.

Mutations run with `python3 -B` on wiped `__pycache__`, each substitution
asserted present in the file before the run:

| mutation | gate result |
|---|---|
| `FRAME = (720, 1296)` (on grid, not 9:16) | 3 failures incl. `test_it_is_exactly_nine_by_sixteen` |
| `FRAME = (1080, 1920)` (9:16, off grid) | 2 failures incl. `test_both_sides_sit_on_the_grid_the_model_snaps_to` |
| `STYLED_SIZE = (1152, 2048)` literal | `test_no_module_repeats_a_frame_as_a_literal_pair`, `test_every_name_for_a_frame_is_the_same_frame` |
| `STYLED_SIZE = (720, 1280)` literal (same value) | `..._literal_pair`, `test_moving_the_frame_moves_every_user_of_it` |
| `PLAN_SIZE = (720, 1280)` literal (same value) | `..._literal_pair`, `test_moving_the_frame_moves_every_user_of_it` |

Open, for whoever owns `docs/`: `docs/MANUAL_ru.md` still describes
`STYLED_SIZE` as ВЫБРАНО and does not know about `FRAME`, `EXTEND_SIZE` or
`PLAN_SIZE` being derived. Not edited here (another writer's file).
