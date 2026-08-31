#!/usr/bin/env python3
"""Does the SHAPE of the file hand over the source, without a pixel being read?

    python scripts/check_sheet_shape.py

WHY THIS EXISTS, AND WHAT IT COST TO LEARN

Twice in two days a reader answered from something that was not the picture.
First a `Lavc61.3.100` comment that only video cases carried — it named our own
tool, not the source, and still separated the two halves perfectly. Then a
watermark burned into the pixels. Both were caught, and both taught the same
lesson: a leak does not have to spell out the answer, it only has to correlate
with it.

Adding Civitai video beside Kling video reopens exactly that risk in a new
place. Kling's clips are one house format; Civitai's come from whatever the
uploader rendered — vertical, square, 480p, 720p. The contact sheet scales
width to a fixed 380 px per frame and lets height follow the aspect ratio, so
the HEIGHT OF THE STRIP is a number that travels with the source and needs no
looking. Same for the byte size of the file.

WHAT IS MEASURED, AND THE ONE DISTINCTION THAT MATTERS

For each property, how many cases carry a value that occurs in exactly one
source. Those are the cases a reader could sort without opening anything.

The comparison is made WITHIN ONE MEDIUM, and that is not a loosening to make
the number green. A reader can see that a file is a six-frame strip rather than
a single picture by looking at it — that is the content, not a leak, and no
amount of normalisation removes it. What must not be free is telling one VIDEO
source from another: Kling and Civitai are both video, and if the file's shape
sorted them the bank would be measuring house formats instead of pictures. So
each medium is judged on its own, and a medium holding a single source is
`не смогли` rather than a perfect leak.

THREE OUTCOMES (rule R1)

    годно       no property separates more than the tolerated share
    не годно    a property does, and the run says which and by how much
    не смогли   fewer than two sources, or no files — nothing to compare

The third one matters here: run this on a bank of one source and every value is
trivially "unique to one source", which would read as a catastrophic leak. That
is not a leak, it is an unanswerable question, and the instrument says so.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

BANK = Path(__file__).resolve().parents[1] / "work" / "casebank"

#: Share of cases a property may sort correctly before it counts as a leak.
#: ВЫБРАНО 0.25: below a quarter a reader gains little over the 1-in-3 it would
#: get by guessing the largest source, and above it the property is doing real
#: work. Not measured — there is no run to measure it against yet, and saying so
#: is the point of the marker.
TOLERATED_UNIQUE = 0.25


#: Byte sizes are bucketed before comparison, because raw sizes are unique to
#: each file by nature and would report a leak on any bank. ВЫБРАНО: powers of
#: two are the coarsest bucketing that still separates "small clip" from "big".
def _size_bucket(size: int) -> str:
    step = 1
    while step * 2 <= max(size, 1):
        step *= 2
    return f"~{step // 1024}КБ"


def properties(case: dict, width: int, height: int, size: int) -> dict[str, str]:
    """The things a reader could learn without decoding an image."""
    return {
        "размер полосы": f"{width}x{height}",
        "высота полосы": str(height),
        "пропорция": f"{round(width / height, 1) if height else 0}",
        "объём файла": _size_bucket(size),
        "расширение": Path(case.get("sheet") or case.get("path") or "").suffix,
    }


def _within(group: list[tuple[str, dict[str, str]]]) -> dict[str, dict]:
    """Per property, how many of these cases a value sorts by source."""
    names = sorted({name for _, props in group for name in props})
    report: dict[str, dict] = {}
    for name in names:
        holders: dict[str, set[str]] = collections.defaultdict(set)
        for source, props in group:
            if name in props:
                holders[props[name]].add(source)
        sortable = sum(1 for _, props in group if name in props and len(holders[props[name]]) == 1)
        report[name] = {
            "сортируется": sortable,
            "из": len(group),
            "доля": round(sortable / len(group), 4),
        }
    return report


def check(observations: list[tuple[str, str, dict[str, str]]]) -> dict:
    """`observations` is (source, medium, {property: value}) per case.

    Kept out of `main` on purpose (rule T5): the fork that decides годно /
    не годно has to be reachable from a test, and a fork inside an entry point
    is not.
    """
    by_medium: dict[str, list[tuple[str, dict[str, str]]]] = collections.defaultdict(list)
    for source, medium, props in observations:
        by_medium[medium].append((source, props))

    comparable = {m: g for m, g in by_medium.items() if len({s for s, _ in g}) >= 2}
    alone = sorted(m for m in by_medium if m not in comparable)
    unmeasured = sum(len(by_medium[m]) for m in alone)

    if not comparable:
        return {
            "outcome": UNMEASURED,
            "checked": len(observations),
            "violations": 0,
            "unmeasured": max(len(observations), 1),
            "worst": None,
            "протекают": [],
            "по_среде": {},
            "по_признаку": {},
            "среды_с_одним_источником": alone,
            "note": (
                "ни в одной среде нет двух источников: при одном источнике любое "
                "значение «уникально», и это вопрос без ответа, а не утечка"
            ),
        }

    per_medium = {medium: _within(group) for medium, group in sorted(comparable.items())}
    flat: dict[str, dict] = {}
    leaking: list[str] = []
    for medium, report in per_medium.items():
        for name, row in report.items():
            flat[f"{medium}: {name}"] = row
            if row["доля"] > TOLERATED_UNIQUE:
                leaking.append(f"{medium}: {name}")

    worst = max(flat, key=lambda n: flat[n]["доля"])
    return {
        "outcome": FAIL if leaking else PASS,
        "checked": sum(len(g) for g in comparable.values()),
        "violations": len(leaking),
        "unmeasured": unmeasured,
        "worst": worst,
        "протекают": sorted(leaking),
        "по_среде": per_medium,
        "по_признаку": flat,
        "среды_с_одним_источником": alone,
        "note": (
            f"«{worst}» сортирует {flat[worst]['доля']} разборов по источнику "
            f"при допуске {TOLERATED_UNIQUE}"
            + (f"; среды с одним источником не считались: {', '.join(alone)}" if alone else "")
        ),
    }


def observe() -> list[tuple[str, str, dict[str, str]]]:
    """Read the real bank. Files that are missing are skipped, not invented."""
    from PIL import Image

    truth = BANK / "TRUTH.json"
    if not truth.is_file():
        return []
    repo = BANK.parents[1]
    seen: list[tuple[str, str, dict[str, str]]] = []
    for case in json.loads(truth.read_text(encoding="utf-8")):
        shown = case.get("sheet") or case.get("path")
        path = repo / str(shown)
        if not path.is_file() or path.suffix == ".mp4":
            continue
        with Image.open(path) as image:
            width, height = image.size
        seen.append(
            (
                case["source"],
                str(case.get("media") or "?"),
                properties(case, width, height, path.stat().st_size),
            )
        )
    return seen


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    out = check(observe())
    for name, row in sorted(out["по_признаку"].items(), key=lambda kv: -kv[1]["доля"]):
        mark = "  ← ПРОТЕКАЕТ" if row["доля"] > TOLERATED_UNIQUE else ""
        print(f"  {name:28} сортирует {row['сортируется']:3}/{row['из']:3} = {row['доля']}{mark}")
    if out["среды_с_одним_источником"]:
        print(
            "  (не сравнивалось, один источник в среде: "
            + ", ".join(out["среды_с_одним_источником"])
            + ")"
        )
    print(
        f"\nпроверено {out['checked']}\nнарушений {out['violations']}\nне смогли {out['unmeasured']}"
    )
    print(f"\n{out['outcome']}: {out['note']}")
    if not args.check:
        return 0
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[out["outcome"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
