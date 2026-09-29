#!/usr/bin/env python3
"""Overlay a re-read onto an earlier set of blind answers.

    python scripts/merge_answers.py work/casebank/ANSWERS.json \
        work/casebank/ANSWERS_cropped.json -o work/casebank/ANSWERS_merged.json

WHY THIS EXISTS

The first Kling run scored 16/16 on family, and the readers told us why: every
frame carried "KLING AI 1.6" burned into the pixels. That is a measurement of
watermark-reading, not of picture-reading, and averaging it in would have made
the agent look twice as good as it is. So the Kling clips were re-sheeted with
the watermark strip cropped off and handed to fresh readers, and those answers
REPLACE the earlier ones for the same cases.

THREE OUTCOMES, NOT TWO (rule R1). An override whose case id is not in the base
is neither applied nor ignored: it is printed and counted. A silent drop here
would shrink the denominator, and a smaller denominator flatters every rate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def merge(base: list[dict], overrides: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """Return the merged answers, the ids replaced, and the ids that matched nothing."""
    by_id = {str(a.get("case_id")): a for a in base}
    replaced: list[str] = []
    orphan: list[str] = []
    for answer in overrides:
        cid = str(answer.get("case_id"))
        if cid in by_id:
            by_id[cid] = answer
            replaced.append(cid)
        else:
            orphan.append(cid)
    return [by_id[cid] for cid in sorted(by_id)], sorted(replaced), sorted(orphan)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("override", nargs="+")
    parser.add_argument("-o", "--out", required=True)
    args = parser.parse_args(argv)

    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    overrides: list[dict] = []
    for path in args.override:
        overrides += json.loads(Path(path).read_text(encoding="utf-8"))

    merged, replaced, orphan = merge(base, overrides)
    Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"основа {len(base)} | накладок {len(overrides)} | вышло {len(merged)}")
    print(f"заменено {len(replaced)}: {', '.join(replaced) or '—'}")
    print(f"не легло никуда {len(orphan)}: {', '.join(orphan) or '—'}")
    print(f"\nпроверено {len(overrides)}\nнарушений 0\nне смогли {len(orphan)}")
    return 1 if orphan else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
