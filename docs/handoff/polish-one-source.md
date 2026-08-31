# polish/one-source — the package has one direction and one place per fact

Landing of the gate `lipsync/tests/test_one_source.py` (commit d1b8e42). Nothing
committed by this session; the tree is left dirty on purpose.

## What moved and why

Two new leaf modules, neither of which imports anything of ours:

* `lipsync/clauses.py` — `NO_BRANDS_CLAUSE`, `ROLE_CLAUSE`,
  `NO_LOOK_TRANSFER_CLAUSE`. They were declared in the stand (`fork_e2e`) and
  needed below it, so `fork_plan` and `fork_aesthetic` imported the stand back
  from inside functions. Both now hold the module (`from . import clauses`) and
  read the name through it, so a swap of the declaration reaches them.
* `lipsync/frame.py` — `FRAME = (720, 1280)`. It was declared in `fork_plan`
  and the gateway `pollinations` reached up for it; the plan reaches down to
  the gateway to outpaint, and that pair was the cycle. `fork_plan`,
  `fork_e2e` and `pollinations` all read it from below now, and `fork_plan`
  keeps offering the name `FRAME` for external callers.

Duplicates:

* `FRAME_SUFFIXES` — kept in `fork_looper` (tuple), the module that reads frame
  directories at the low level; `fork_e2e` borrows it, as `fork_intake` already
  borrows `CUT_JUMP` from the same module. The stand's set spelling is gone; it
  is used only for `in` and `sorted()`, both of which read the tuple the same.
* `MIN_VISIBILITY` — kept in `pose`, which owns the landmark visibility bar and
  already lent it to `fork_intake`; `fork_plan` borrows it in the place its own
  copy stood.

The deferred imports that were holding cycles are gone, and the ones that
remain are the ordinary lazy kind (third-party, argparse in entry points).
`fork_plan` now imports `pollinations` at module level, and `fork_e2e` imports
`fork_aesthetic`, `fork_plan` and `pollinations` at module level.

## Tests that had to follow the move

* `test_fork_aesthetic`, `test_fork_plan`: the brand-ban negative control now
  swaps `clauses.NO_BRANDS_CLAUSE` instead of `fork_e2e.NO_BRANDS_CLAUSE`.
  Swapping the stand would no longer prove anything, since the stand is a
  reader.
* `test_one_frame`: the "one edit moves them all" control patches
  `frame.FRAME` and now reloads `fork_plan` as well as the two other readers,
  so the re-exported `fork_plan.FRAME` is itself under the control.
* `test_ratio_chain`: dropped `mock.patch.object(P, "pollinations",
  create=True)`. With the gateway imported at module level that patch replaces
  the module the call goes through and swallows the call it is measuring.
* `README.md`: the quoted run was 1049 tests in 20 files; the gate commit added
  eight tests and a file without moving it. Now 1057 in 22, run of 2026-08-28.

## Left for whoever comes next

`fork_e2e.NO_BRANDS_CLAUSE` and `fork_plan.FRAME` are re-exports kept because
callers and tests use those names. They are read-only aliases: a swap of the
alias moves that module and nothing else. If a name is ever assigned there
again rather than imported, the gate will say so.
