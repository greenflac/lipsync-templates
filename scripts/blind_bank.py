#!/usr/bin/env python3
"""Hand the bank to the readers with every trace of its origin removed.

    python scripts/blind_bank.py

Writes `work/casebank/blind/case-001.jpg …` and `BLIND_MAP.json`, which maps a
blind id back to the real case. The readers get the folder; the map stays here.

WHY THIS IS A SCRIPT AND NOT SOMETHING SOMEBODY DID ONCE

The first bank was blinded by hand, and the mapping survived only as a file
nobody could regenerate. That is the same defect as a number nobody can
re-measure: the run cannot be repeated, so a claimed sign cannot be re-tested.

WHAT THE BLINDING HAS TO REMOVE, LEARNED THE EXPENSIVE WAY

- the NAME. The first bank called its files `kv-…` and `of-…`, which handed over
  the source before a reader opened anything.
- the ORDER. Sorted by source, position alone answers the question, so the shuffle
  is seeded and therefore repeatable.
- the EXTENSION. A `.mp4` beside a `.jpg` separates video from image for free.
  Every case is shown as one `.jpg`: clips as a six-frame strip, pictures as
  themselves.
- the METADATA. Re-checked here rather than trusted from upstream: this is the
  last point at which a leak can still be caught before a reader sees it.

Three outcomes (rule R1): годно, не годно — a file still carries a carrier — and
не смогли, when there is no bank on disk to blind.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
BANK = REPO / "work" / "casebank"
BLIND = BANK / "blind"

#: Same seed as the bank build, so the whole pipeline is one repeatable run.
SEED = 20260830

#: What a JPEG may keep. Anything else is a carrier, whatever it claims to be.
ALLOWED = frozenset({"jfif", "jfif_version", "jfif_unit", "jfif_density", "dpi"})


def shown_file(case: dict) -> str:
    """What the reader is actually given: the strip for a clip, the picture itself
    for a picture. A case with neither is not showable and is reported, not skipped."""
    return str(case.get("sheet") or (case.get("path") if case.get("media") != "video" else ""))


def plan(cases: list[dict], seed: int = SEED) -> list[tuple[str, str]]:
    """(blind_id, real_case_id) in shown order. Pure, so a test can check the
    shuffle without touching a disk."""
    showable = [c for c in cases if shown_file(c)]
    order = list(showable)
    random.Random(seed).shuffle(order)
    return [(f"case-{i:03d}", c["case_id"]) for i, c in enumerate(order, start=1)]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    from PIL import Image

    truth = BANK / "TRUTH.json"
    if not truth.is_file():
        print(f"\nпроверено 0\nнарушений 0\nне смогли 1\n\n{UNMEASURED}: нет {truth}")
        return 2
    cases = json.loads(truth.read_text(encoding="utf-8"))
    by_id = {c["case_id"]: c for c in cases}
    unshowable = [c["case_id"] for c in cases if not shown_file(c)]

    if BLIND.is_dir():
        shutil.rmtree(BLIND)
    BLIND.mkdir(parents=True, exist_ok=True)

    mapping: dict[str, str] = {}
    leaks: list[str] = []
    missing: list[str] = []
    for blind_id, real_id in plan(cases):
        source_file = REPO / shown_file(by_id[real_id])
        if not source_file.is_file():
            missing.append(real_id)
            continue
        target = BLIND / f"{blind_id}.jpg"
        shutil.copyfile(source_file, target)
        with Image.open(target) as image:
            left = sorted(str(k) for k in (image.info or {}) if k not in ALLOWED)
        if left:
            leaks.append(f"{blind_id}: {left}")
            target.unlink(missing_ok=True)
            continue
        mapping[blind_id] = real_id

    (BANK / "BLIND_MAP.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    sizes = {p.suffix for p in BLIND.iterdir()}
    print(f"  разборов роздано {len(mapping)}, расширений {sorted(sizes)}")
    if unshowable:
        print(f"  нечего показать у {len(unshowable)}: {', '.join(unshowable[:5])}")
    if missing:
        print(f"  файл не найден у {len(missing)}: {', '.join(missing[:5])}")
    for leak in leaks:
        print(f"  УТЕЧКА {leak}")

    could_not = len(unshowable) + len(missing)
    print(f"\nпроверено {len(mapping)}\nнарушений {len(leaks)}\nне смогли {could_not}")
    if leaks:
        print(f"\n{FAIL}: {len(leaks)} файлов дошли бы до читателя с носителем внутри")
        outcome = FAIL
    elif not mapping:
        print(f"\n{UNMEASURED}: ни одного разбора не роздано")
        outcome = UNMEASURED
    else:
        print(f"\n{PASS}: {len(mapping)} слепых копий в {BLIND}, карта в BLIND_MAP.json")
        outcome = PASS
    if not args.check:
        return 0 if outcome is not FAIL else 1
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[outcome]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
