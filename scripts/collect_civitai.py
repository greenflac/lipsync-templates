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

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

from studio.mcp import civitai  # noqa: E402

#: The basis these rows stand on, from PROVENANCE.md. Stamped per row.
DEFAULT_RIGHTS = "owner_authorisation_2026-08-27"


def exit_code(outcomes: list[str], written: int) -> int:
    """Три состояния в коде возврата, посчитанные ПО СВИДЕТЕЛЬСТВУ.

    Прежняя версия строила исход из одного числа `written`, поэтому получалось
    только два состояния: ветка `1` была недостижима, и жёсткий отказ API
    выходил с нулём, если хоть одно другое семейство что-то записало. Значение
    выводится из того, что исполнилось, а не из намерения (правило Е2).

    Вынесено из `main` (Т5): развилка внутри точки входа тестом недостижима.
    """
    if any(o == FAIL for o in outcomes):
        return 1
    if written:
        return 0
    return 2


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=1, help="model listing pages to walk")
    parser.add_argument("--per-page", type=int, default=20, help="models per listing page")
    parser.add_argument("--versions", type=int, default=25, help="hard ceiling on version requests")
    parser.add_argument("--sort", default="Most Downloaded")
    parser.add_argument(
        "--base-model",
        action="append",
        default=[],
        metavar="FAMILY",
        help=(
            "a Civitai base-model family to restrict the harvest to, e.g. 'Flux.1 D', "
            "'Flux.1 S', 'Wan Video 14B t2v', 'Qwen'. Repeatable; one API call per "
            "family, because the API honours only the first baseModels parameter. "
            "CASE-SENSITIVE, and an unrecognised name collects nothing without "
            "erroring. Omit it and the harvest is whatever the sort surfaces, which "
            "MEASURED is the Stable Diffusion checkpoint ecosystem and nothing this "
            "project targets."
        ),
    )
    parser.add_argument("--delay", type=float, default=civitai.DEFAULT_DELAY_SECONDS)
    parser.add_argument("--rights", default=DEFAULT_RIGHTS)
    parser.add_argument(
        "--safe-models-only",
        action="store_true",
        help=(
            "skip checkpoints that publish above PG-13 themselves, not just images "
            "that do. Every collected image is at PG or PG-13 either way; this is "
            "about whose checkpoint the wording came from. The count is printed "
            "whether or not this is set, so the decision can be made from a number."
        ),
    )
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

    families: list[str] = args.base_model or [""]
    outcomes = []
    for family in families:
        out = civitai.collect(
            harvested=date.today().isoformat(),
            rights=args.rights,
            pages=args.pages,
            per_page=args.per_page,
            sort=args.sort,
            base_model=family,
            safe_models_only=args.safe_models_only,
            max_versions=args.versions,
            delay_seconds=args.delay,
        )
        label = family or "(unfiltered)"
        print(f"{out['outcome']:<18} {label}: {out['note']}")
        outcomes.append(out)

    # One family collecting nothing does not make the run a success, and does
    # not make it a failure either. The counts go out beside the verdict so a
    # reader sees the denominator (house rule P2).
    got = sum(int(o["written"]) for o in outcomes)
    broke = [f for f, o in zip(families, outcomes) if o["outcome"] == FAIL]
    empty = [f for f, o in zip(families, outcomes) if o["outcome"] == UNMEASURED]
    print(
        f"\nсемейств {len(families)}\nзаписей {got}\n"
        f"сломалось {len(broke)}\nбез результата {len(empty)}"
    )
    for label, names in (("сломалось на", broke), ("ничего не дало", empty)):
        if names:
            print(f"  {label}: " + ", ".join(f or "(unfiltered)" for f in names))
    return exit_code([o["outcome"] for o in outcomes], got)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
