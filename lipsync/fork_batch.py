"""Batch over the end-to-end stand: a driving x style x identity matrix."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .fork_identity import FAIL, PASS, UNMEASURED
from .fork_video import EXIT_BY_OUTCOME

from . import fork_e2e as E


OWNER_MATRIX = (5, 5, 2)

MODES = ("full", "cover")

MAX_STREAK = 3

NAME_SEP = "__"

BALANCE_ENV = "FAL_BALANCE_USD"


def live_balance() -> float | None:
    """Return the fal account balance in dollars, or `None` meaning "could not find out"."""
    import os  # noqa: PLC0415

    raw = os.environ.get(BALANCE_ENV)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def copy_clip(src, dst) -> tuple:
    """Copy the finished clip to its own tellingly named file. Return `(path, reason)`."""
    s = Path(src)
    if not s.is_file():
        return None, f"clip {s} is not on disk: nothing to collect"
    if s.stat().st_size <= 0:
        return None, f"clip {s} is empty (0 B)"
    try:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(s), str(dst))
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return str(dst), None


def cell_name(driving, style, person) -> str:
    """Return `driving__style__identity`: a clip name readable without the report."""
    return NAME_SEP.join(Path(str(p)).stem for p in (driving, style, person))


def cells(drivings, styles, persons, *, mode: str = "full") -> list:
    """List the matrix cells for a coverage mode. An unknown mode is a refusal."""
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} is unknown, have {list(MODES)}")
    axes = {"drivings": list(drivings), "styles": list(styles), "persons": list(persons)}
    empty = [k for k, v in axes.items() if not v]
    if empty:
        raise ValueError(f"empty matrix axes: {empty}; nothing to order")
    dr, st, pe = axes["drivings"], axes["styles"], axes["persons"]
    out = []
    if mode == "full":
        for d in dr:
            for s in st:
                for p in pe:
                    out.append((d, s, p))
    else:
        for i in range(max(len(dr), len(st), len(pe))):
            out.append((dr[i % len(dr)], st[i % len(st)], pe[i % len(pe)]))
    return [
        {"driving": d, "style": s, "person": p, "name": cell_name(d, s, p), "index": i + 1}
        for i, (d, s, p) in enumerate(out)
    ]


def plan_cost(n: int) -> float:
    """Return the price of n cells. The price of one call is imported from the stand."""
    return round(int(n) * E.KLING_PRICE_USD, 4)


def afford(n: int, balance) -> dict:
    """Check the money for n cells. Three outcomes, and two of them keep the batch out."""
    need = plan_cost(n)
    try:
        have = None if balance is None else float(balance)
    except (TypeError, ValueError):
        have = None
    if have is None:
        return {
            "outcome": UNMEASURED,
            "need": need,
            "have": None,
            "short": None,
            "note": (
                f"the account balance is unknown: the ${need} order "
                f"({n} cells at ${E.KLING_PRICE_USD}) was not started. "
                f"Set {BALANCE_ENV} or inject your own balance probe"
            ),
        }
    if have + 1e-9 < need:
        short = round(need - have, 4)
        return {
            "outcome": FAIL,
            "need": need,
            "have": round(have, 4),
            "short": short,
            "note": (
                f"${short} SHORT: an order of {n} cells at "
                f"${E.KLING_PRICE_USD} costs ${need}, the account holds "
                f"${round(have, 4)}. The batch was NOT started: spending "
                f"half and stalling midway is worse than not starting"
            ),
        }
    return {
        "outcome": PASS,
        "need": need,
        "have": round(have, 4),
        "short": 0.0,
        "note": (
            f"enough: the order is ${need} ({n} cells at "
            f"${E.KLING_PRICE_USD}), the account holds ${round(have, 4)}, "
            f"${round(have - need, 4)} will remain"
        ),
    }


def _cell_line(cell: dict) -> str:
    """Render the cell line: the verdict with the numbers right next to it."""
    t = cell.get("totals") or {}
    return (
        f"[{cell['outcome']:<18}] cell {cell['index']:>2} "
        f"{cell['name']:<46} checked {t.get('checked', 0)}, "
        f"violations {t.get('violations', 0)}, unmeasured "
        f"{t.get('unmeasured', 0)} | {cell.get('note', '')}"
    )


def run_batch(
    *,
    drivings,
    styles,
    persons,
    mode: str = "full",
    first: int = 0,
    last: int = 0,
    windows=None,
    out_dir="work/batch",
    balance=None,
    cell_runner=None,
    collect=None,
    max_streak: int = MAX_STREAK,
    endpoint: str | None = None,
    log=None,
    **cell_kwargs,
) -> dict:
    """Run the whole batch: money -> cells one by one -> summary. Return the digest."""
    runner = E.run if cell_runner is None else cell_runner
    take = copy_clip if collect is None else collect
    get_balance = live_balance if balance is None else balance
    where = Path(out_dir)
    clips_dir = where / "clips"
    wins = dict(windows or {})

    grid = cells(drivings, styles, persons, mode=mode)
    n = len(grid)
    full_n = len(drivings) * len(styles) * len(persons)
    E.say(
        f"batch: matrix {len(drivings)}x{len(styles)}x{len(persons)}, mode "
        f"'{mode}' -> {n} cells (the full cross would give {full_n}); price "
        f"${E.KLING_PRICE_USD} per cell, order ${plan_cost(n)}",
        log=log,
    )

    ep = E.KLING_ENDPOINT if endpoint is None else endpoint
    E.refuse_pro(ep)

    before = get_balance()
    money = afford(n, before)
    E.say(
        f"[{money['outcome']:<18}] money before start{'':<28} "
        f"need ${money['need']}, have "
        f"{'?' if money['have'] is None else '$' + str(money['have'])} | "
        f"{money['note']}",
        log=log,
    )
    if money["outcome"] != PASS:
        E.say(f"TOTAL: {money['outcome']} — batch NOT STARTED, orders 0, spent $0.0", log=log)
        return {
            "outcome": money["outcome"],
            "mode": mode,
            "planned": n,
            "attempted": 0,
            "passed": 0,
            "failed": 0,
            "unmeasured": 0,
            "money": money,
            "balance_before": money["have"],
            "balance_after": None,
            "spent_expected": 0.0,
            "spent_actual": None,
            "cells": [],
            "clips": [],
            "stopped_early": False,
            "exit_code": EXIT_BY_OUTCOME[money["outcome"]],
        }

    done, streak, stopped = [], 0, False
    for cell in grid:
        if stopped:
            cell = dict(
                cell,
                outcome=UNMEASURED,
                totals={},
                clip=None,
                launched=False,
                note=(f"not launched: the batch stopped after {max_streak} failures in a row"),
            )
            done.append(cell)
            E.say(_cell_line(cell), log=log)
            continue
        cell = dict(cell, launched=True)
        cell_dir = where / "cells" / cell["name"]
        win = wins.get(str(cell["driving"]), (first, last))
        try:
            got = runner(
                client_photo=cell["person"],
                style_ref=cell["style"],
                driving=cell["driving"],
                first=win[0],
                last=win[1],
                out_dir=str(cell_dir),
                log=log,
                **cell_kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            cell.update(
                outcome=UNMEASURED,
                totals={},
                clip=None,
                note=f"the run crashed: {type(exc).__name__}: {exc}",
            )
        else:
            reply = got if isinstance(got, dict) else {}
            outcome = reply.get("outcome")
            if outcome not in (PASS, FAIL, UNMEASURED):
                cell.update(
                    outcome=UNMEASURED,
                    totals={},
                    clip=None,
                    note=(
                        f"the run replied {type(got).__name__} with no verdict: nothing to judge by"
                    ),
                )
            else:
                note = f"stopped at '{reply.get('stopped_at', '?')}'"
                clip, why = None, None
                if outcome == PASS:
                    clip, why = take(cell_dir / "final_9x16.mp4", clips_dir / f"{cell['name']}.mp4")
                    if clip is None:
                        outcome = UNMEASURED
                        note = f"verdict '{PASS}', but the clip is missing: {why}"
                    else:
                        note = f"clip {clip}"
                cell.update(outcome=outcome, totals=reply.get("totals") or {}, clip=clip, note=note)
        done.append(cell)
        E.say(_cell_line(cell), log=log)
        streak = 0 if cell["outcome"] == PASS else streak + 1
        if streak >= max_streak:
            stopped = True
            E.say(
                f"STOP: {streak} failures in a row against the threshold {max_streak} — "
                f"this is a breakage, not just a bad pair; going on would "
                f"burn ${E.KLING_PRICE_USD} per cell",
                log=log,
            )

    attempted = sum(1 for c in done if c.get("launched"))
    passed = sum(1 for c in done if c["outcome"] == PASS)
    failed = sum(1 for c in done if c["outcome"] == FAIL)
    unmeasured = sum(1 for c in done if c["outcome"] == UNMEASURED)
    after = get_balance()
    spent_expected = plan_cost(attempted)
    spent_actual = (
        None if (before is None or after is None) else round(float(before) - float(after), 4)
    )
    outcome = E.verdict(passed + failed, failed, unmeasured)

    for c in done:
        E.say(f"      · {c['name']}: {c['outcome']} — {c.get('note', '')}", log=log)
    E.say(
        f"TOTAL: {outcome} | pass {passed}, fail {failed}, unmeasured "
        f"{unmeasured} of {len(grid)} cells (launched {attempted}) | "
        f"actually spent "
        f"{'could not measure' if spent_actual is None else '$' + str(spent_actual)}"
        f" against expected ${spent_expected} | balance "
        f"{before} -> {after} | clips "
        f"{sum(1 for c in done if c.get('clip'))}",
        log=log,
    )
    return {
        "outcome": outcome,
        "mode": mode,
        "planned": len(grid),
        "attempted": attempted,
        "passed": passed,
        "failed": failed,
        "unmeasured": unmeasured,
        "money": money,
        "balance_before": before,
        "balance_after": after,
        "spent_expected": spent_expected,
        "spent_actual": spent_actual,
        "cells": done,
        "clips": [c["clip"] for c in done if c.get("clip")],
        "stopped_early": stopped,
        "exit_code": EXIT_BY_OUTCOME[outcome],
    }


def main(argv=None) -> int:
    """Keep the entry point thin: parse the arguments and call `run_batch`."""
    import argparse  # noqa: PLC0415

    ap = argparse.ArgumentParser(description="batch over the end-to-end stand")
    ap.add_argument("--driving", action="append", required=True)
    ap.add_argument("--style", action="append", required=True)
    ap.add_argument("--person", action="append", required=True)
    ap.add_argument("--mode", default="full", choices=list(MODES))
    ap.add_argument("--window", required=True, help="first:last, e.g. 100:199")
    ap.add_argument("--out", default="work/batch")
    a = ap.parse_args(argv)
    first, last = E.parse_window(a.window)
    got = run_batch(
        drivings=a.driving,
        styles=a.style,
        persons=a.person,
        mode=a.mode,
        first=first,
        last=last,
        out_dir=a.out,
    )
    return got["exit_code"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
