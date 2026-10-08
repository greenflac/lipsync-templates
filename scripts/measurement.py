#!/usr/bin/env python3
"""The operator's side of a paid measurement. A person runs this, not an agent.

    python scripts/measurement.py list                    # everything filed
    python scripts/measurement.py list --state proposed   # what waits on you
    python scripts/measurement.py show mp-1234abcd
    python scripts/measurement.py approve mp-1234abcd --by karxism
    python scripts/measurement.py decline mp-1234abcd --by karxism --note "too dear"
    python scripts/measurement.py record  mp-1234abcd \\
        --value "0.19 cosine drift" --url https://... --on 2026-08-27 \\
        --evidence "frame 1 to frame 144 ArcFace cosine 0.19" --cost 0.42

WHY APPROVAL IS A COMMAND AND NOT A TOOL

`studio/mcp/server.py` exposes `propose_measurement` and
`measurement_proposals`, and nothing else from this state machine. The agent
can file and it can look; it cannot approve. That is the whole point of the
mechanism — an agent that could approve its own proposal has not asked for
permission, it has been handed the account.

So the approval lives here, behind a shell the operator types into. It is not
a stronger guarantee than a well-behaved agent; it is a CHECKABLE one, which
is what house rule C7 asks for.

`record` is here for the same reason: the result of a paid run is entered by
whoever watched it run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import PASS  # noqa: E402

from studio.mcp import proposal  # noqa: E402


def _print(row: dict, *, full: bool = False) -> None:
    print(f"{row.get('id')}  [{row.get('state')}]  {row.get('model')}.{row.get('attribute')}")
    print(f"    задача:  {row.get('task')}")
    print(f"    цена:    ${float(row.get('cost_usd') or 0.0):.2f}  ({row.get('cost_basis')})")
    if full:
        print(f"    дыра:    {row.get('gap')}")
        print(f"    тест:    {row.get('test')}")
        print(f"    решает:  {row.get('decides')}")
        if row.get("decided_by"):
            print(f"    решил:   {row.get('decided_by')} {row.get('decided_on')}")
            if row.get("decision_note"):
                print(f"             {row.get('decision_note')}")
        if row.get("state") == proposal.STATE_RECORDED:
            print(f"    итог:    {row.get('value')!r}  {row.get('result_url')}")
            print(f"    списано: ${float(row.get('actual_cost_usd') or 0.0):.2f}")
            if row.get("overspent"):
                print("    ПЕРЕРАСХОД относительно одобренной суммы")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list")
    listing.add_argument("--state", default="", choices=("", *proposal.STATES))

    shows = sub.add_parser("show")
    shows.add_argument("id")

    for name in ("approve", "decline"):
        decision = sub.add_parser(name)
        decision.add_argument("id")
        decision.add_argument(
            "--by", required=True, help="your name; an unsigned approval is not one"
        )
        decision.add_argument("--note", default="")

    result = sub.add_parser("record")
    result.add_argument("id")
    result.add_argument("--value", required=True)
    result.add_argument("--url", required=True, help="where the result can be seen again")
    result.add_argument("--on", required=True, help="ISO date it was measured")
    result.add_argument("--evidence", required=True, help="what you actually observed")
    result.add_argument("--cost", required=True, type=float, help="what it really cost")

    args = parser.parse_args(argv)

    if args.command == "list":
        out = proposal.proposals(state=args.state)
        for row in out["proposals"]:
            _print(row)
        print(f"\n{out['note']}")
        # An empty ledger is not a failed listing; it is a listing of nothing.
        return 0

    if args.command == "show":
        out = proposal.proposals()
        for row in out["proposals"]:
            if row.get("id") == args.id:
                _print(row, full=True)
                return 0
        print(f"не смогли: нет заявки {args.id!r}")
        return 2

    if args.command in ("approve", "decline"):
        out = proposal.decide(
            args.id,
            proposal.STATE_APPROVED if args.command == "approve" else proposal.STATE_DECLINED,
            operator=args.by,
            note=args.note,
        )
    else:
        out = proposal.record_result(
            args.id,
            args.value,
            args.url,
            args.on,
            evidence=args.evidence,
            actual_cost_usd=args.cost,
        )

    print(f"{out['outcome']}: {out['note']}")
    return 0 if out["outcome"] == PASS else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
