#!/usr/bin/env python3
"""Collect prompt-and-result pairs from Civitai into the knowledge base.

    python scripts/collect_civitai.py --pages 5 --versions 100
    python scripts/collect_civitai.py --summary          # what is held already

The walk and every decision in it live in `studio/mcp/civitai.py`; this is the
handle. It exists so a collection run is a command with a record rather than a
snippet somebody pasted into a shell once.

RATE AND SCALE

Requests go out no faster than one per second by default and `--versions` is a
hard ceiling, so a mistyped page count cannot become a thousand calls against
somebody else's API. Raise them deliberately.

RIGHTS

`--rights` is stamped on every row and defaults to the basis recorded in
`studio/knowledge/PROVENANCE.md`. It is not decoration: it is what makes an
exact removal possible if it is ever asked for, and a row cannot be written
without it. If the basis changes, change it here and in PROVENANCE.md together.

The output file is in `.gitignore`. That is deliberate and explained there.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import PASS  # noqa: E402

from studio.mcp import civitai  # noqa: E402

#: The basis these rows stand on, from PROVENANCE.md. Stamped per row.
DEFAULT_RIGHTS = "owner_authorisation_2026-08-27"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=1, help="model listing pages to walk")
    parser.add_argument("--per-page", type=int, default=20, help="models per listing page")
    parser.add_argument("--versions", type=int, default=25, help="hard ceiling on version requests")
    parser.add_argument("--sort", default="Most Downloaded")
    parser.add_argument("--delay", type=float, default=civitai.DEFAULT_DELAY_SECONDS)
    parser.add_argument("--rights", default=DEFAULT_RIGHTS)
    parser.add_argument(
        "--summary", action="store_true", help="report what is held, collect nothing"
    )
    args = parser.parse_args(argv)

    path = civitai.DEFAULT_OUTPUT_PATH
    if args.summary:
        rows = []
        if path.is_file():
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        held = civitai.summarise(rows)
        print(f"{held['outcome']}: {held['note']}")
        for provenance, count in sorted(held["by_provenance"].items(), key=lambda kv: -kv[1]):
            print(f"  {count:>5}  {provenance}")
        return 0 if held["outcome"] == PASS else 1

    out = civitai.collect(
        harvested=date.today().isoformat(),
        rights=args.rights,
        pages=args.pages,
        per_page=args.per_page,
        sort=args.sort,
        max_versions=args.versions,
        delay_seconds=args.delay,
    )
    print(f"{out['outcome']}: {out['note']}")
    # Three outcomes reach the exit code as three states, not two: an API that
    # answered and gave nothing is not a success and is not a crash either, and
    # a caller in a pipeline needs to tell them apart.
    return {PASS: 0}.get(str(out["outcome"]), 2 if out["outcome"] != "fail" else 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
