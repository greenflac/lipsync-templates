"""Publish a built draft into the product base.

The write is irreversible — an aesthetic in the base is one a client order can
pick — so every check runs BEFORE the first byte is written, and a refusal is a
report with numbers rather than a traceback in the operator's face.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

from . import fork_aesthetic
from .fork_identity import FAIL, PASS, UNMEASURED
from .fork_video import EXIT_BY_OUTCOME
from .frame import FRAME

#: The draft layout, named once here so the builder writes what this reads.
#: The two clips cannot both be `<id>_<gender>.mp4` the way they are in the
#: base, so inside a draft they are told apart by name and not by extension.
DRAFT_MANIFEST = "aesthetic.json"
DRAFT_DEMO = "demo.png"
DRAFT_DRIVING = "driving.mp4"
DRAFT_TRIAL = "trial.mp4"

#: CHOSEN (contract 01.09, stage 7 of the build): the four files without which
#: there is nothing to publish. The trial is in this tuple and not in a softer
#: check because decision 5 says an aesthetic that was never run through a paid
#: clip is not fit, and a missing file is the only honest evidence of that.
DRAFT_FILES = (DRAFT_MANIFEST, DRAFT_DEMO, DRAFT_DRIVING, DRAFT_TRIAL)

#: What the builder must put in the manifest. `driving` and `trial` are absent
#: on purpose: their paths in the base are decided HERE, by where the files are
#: copied to, so that the stored path can never disagree with the file.
MANIFEST_FIELDS = ("id", "name", "kind", "prompt", "demo", "window", "card")

#: CHOSEN: the id becomes a file name in three directories and a key an
#: operator types on the command line, so it is held to the narrow alphabet
#: every filesystem and shell agrees on. A dot or a slash here would write
#: outside the directories this module believes it writes into.
ID_ALLOWED = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

#: DERIVED from `fork_aesthetic.BASE_PATH`: the repository root is where that
#: base lives, two directories up. Every destination is built under a `root` so
#: a test can publish into a temporary tree and never touch the real assets.
REPO_ROOT = fork_aesthetic.BASE_PATH.parent.parent
BASE_RELATIVE = fork_aesthetic.BASE_PATH.relative_to(REPO_ROOT)


def base_path_under(root=None) -> Path:
    """Return the aesthetics base inside `root`, defaulting to the repository's own."""
    return fork_aesthetic.BASE_PATH if root is None else Path(root) / BASE_RELATIVE


def destinations(aesthetic_id: str, gender: str, *, root=None) -> dict:
    """Return where each part of the draft lands, as repository-relative paths and absolute ones.

    >>> destinations("ramp", "f")["driving"]["relative"]
    'assets/drivings/ramp_f.mp4'
    """
    base = Path(root) if root is not None else REPO_ROOT
    stem = f"{aesthetic_id}_{gender}"
    parts = {
        "demo": fork_aesthetic.AESTHETIC_DIR / f"{stem}.png",
        "driving": fork_aesthetic.DRIVING_DIR / f"{stem}.mp4",
        "trial": fork_aesthetic.TRIAL_DIR / f"{stem}.mp4",
    }
    return {
        name: {"relative": rel.as_posix(), "absolute": base / rel} for name, rel in parts.items()
    }


def _default_sizer(path):
    """Return the picture's (width, height). Injection point: the test replaces it wholesale."""
    from PIL import Image  # noqa: PLC0415

    with Image.open(path) as im:
        return im.size


def _unreadable(note: str) -> dict:
    """Return the third outcome: nothing was checked, and that is not permission to publish."""
    return {
        "outcome": UNMEASURED,
        "checked": 0,
        "violations": 0,
        "unmeasured": 1,
        "problems": [],
        "element": None,
        "note": f"NOTHING was checked: {note}. This is NOT permission to publish",
    }


def _read_manifest(draft: Path) -> tuple[dict | None, str | None]:
    """Return the parsed manifest, or the reason it could not be read."""
    if not draft.is_dir():
        return None, f"the draft {str(draft)!r} is not a directory"
    manifest = draft / DRAFT_MANIFEST
    if not manifest.is_file():
        return None, (
            f"the draft {str(draft)!r} has no {DRAFT_MANIFEST}; a draft holds "
            f"{', '.join(DRAFT_FILES)}, and this one holds "
            f"{', '.join(sorted(p.name for p in draft.iterdir())) or 'nothing'}"
        )
    try:
        got = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{manifest} could not be read: {type(exc).__name__}: {exc}"
    if not isinstance(got, dict):
        return None, f"{manifest} holds {type(got).__name__}, not one aesthetic"
    return got, None


def inspect(draft, *, root=None, sizer=None) -> dict:
    """Check a draft against everything publishing demands, without writing anything.

    Returns the three outcomes with their numbers: a pass carrying the element
    that would be appended, a fail listing every problem found, or
    `could not measure` when the draft could not be read at all.

    `draft` is the directory the build wrote; `root` is the tree to publish
    into, defaulting to this repository; `sizer` returns a picture's size.
    """
    draft = Path(draft)
    manifest, why = _read_manifest(draft)
    if manifest is None:
        return _unreadable(str(why))

    sizer = _default_sizer if sizer is None else sizer
    problems: list[str] = []
    unmeasured: list[str] = []
    checked = 0

    checked += 1
    absent = [
        n for n in DRAFT_FILES if not (draft / n).is_file() or (draft / n).stat().st_size == 0
    ]
    if absent:
        problems.append(
            f"the draft is missing or has empty {absent}; without "
            f"{DRAFT_TRIAL} the aesthetic was never run through a paid clip "
            f"and by decision 5 it is not fit"
        )

    checked += 1
    short = [f for f in MANIFEST_FIELDS if manifest.get(f) in (None, "", [], {}, ())]
    if short:
        problems.append(
            f"{DRAFT_MANIFEST} carries none of {short}, of {len(MANIFEST_FIELDS)} required"
        )

    aesthetic_id = str(manifest.get("id") or "")
    checked += 1
    if not ID_ALLOWED.match(aesthetic_id):
        problems.append(
            f"the id {aesthetic_id!r} is not a name this may write to disk; "
            f"allowed is {ID_ALLOWED.pattern}"
        )

    checked += 1
    gender = str(manifest.get("demo") or "").strip().lower()
    if gender not in fork_aesthetic.GENDERS:
        problems.append(
            f"the manifest names the gender {manifest.get('demo')!r}, and the "
            f"project knows {fork_aesthetic.GENDERS}"
        )

    base = base_path_under(root)
    checked += 1
    try:
        taken = fork_aesthetic.ids(base)
    except (OSError, ValueError) as exc:
        checked -= 1
        unmeasured.append(f"the base {base} could not be read: {type(exc).__name__}: {exc}")
    else:
        if aesthetic_id in taken:
            problems.append(
                f"the id {aesthetic_id!r} is already in the base, which holds "
                f"{len(taken)}: {', '.join(taken)}. Publishing is not an edit"
            )

    where = (
        destinations(aesthetic_id, gender, root=root)
        if ID_ALLOWED.match(aesthetic_id) and gender in fork_aesthetic.GENDERS
        else None
    )
    checked += 1
    if where is None:
        checked -= 1
        unmeasured.append("the destinations were not built: the id or the gender is unusable")
    else:
        clash = [w["relative"] for w in where.values() if w["absolute"].exists()]
        if clash:
            problems.append(f"{len(clash)} destination files already exist: {clash}")

    checked += 1
    try:
        width, height = sizer(str(draft / DRAFT_DEMO))
    except Exception as exc:  # noqa: BLE001
        checked -= 1
        unmeasured.append(f"the demo frame size was not taken: {type(exc).__name__}: {exc}")
    else:
        if (width, height) != FRAME:
            problems.append(
                f"the demo frame is {width}x{height} and the product frame is "
                f"{FRAME[0]}x{FRAME[1]}: a frame off the delivery size travels "
                f"into every order this aesthetic takes"
            )

    element = None
    checked += 1
    if where is None:
        checked -= 1
        unmeasured.append("readiness was not judged: the destinations are unknown")
    else:
        element = {
            **{f: manifest[f] for f in MANIFEST_FIELDS if f in manifest},
            **({"demo_why": manifest["demo_why"]} if manifest.get("demo_why") else {}),
            "driving": where["driving"]["relative"],
            "trial": where["trial"]["relative"],
        }
        ready = fork_aesthetic.order_ready(element)
        if ready["outcome"] != PASS:
            problems.append(f"the aesthetic would not be ready for an order: {ready['note']}")
            element = None

    checked += 1
    if element is None or where is None:
        checked -= 1
        unmeasured.append("the element was not read back: it was never built")
    else:
        unreadable = _readable_by_the_accessors(element, where)
        if unreadable:
            problems.append(f"the published aesthetic would not read back: {unreadable}")
            element = None

    if checked == 0:
        return _unreadable("; ".join(unmeasured) or "no check could run")
    outcome = FAIL if problems else (UNMEASURED if unmeasured else PASS)
    return {
        "outcome": outcome,
        "checked": checked,
        "violations": len(problems),
        "unmeasured": len(unmeasured),
        "problems": problems + unmeasured,
        "element": element if outcome == PASS else None,
        "where": where,
        "note": (
            f"checked {checked}, violations {len(problems)}, could not check "
            f"{len(unmeasured)}"
            + (f": {'; '.join(problems + unmeasured)}" if problems or unmeasured else "")
        ),
    }


def _readable_by_the_accessors(element: dict, where: dict) -> str | None:
    """Return why a reader could not use this element, or None.

    Every reader reaches an aesthetic through the accessors, so the element is
    put through them HERE, before the irreversible write, instead of after an
    order falls over on it. It also catches the two halves drifting apart: the
    path stored in the element and the path the file is copied to are built by
    different code, and a stored path that points nowhere is exactly the defect
    that survives every check made on the draft alone.
    """
    try:
        driving = fork_aesthetic.driving_of(element)
        trial = fork_aesthetic.trial_of(element)
        first, last = fork_aesthetic.window_of(element)
        card = fork_aesthetic.card_of(element)
    except (KeyError, TypeError, ValueError) as exc:
        return f"a reader could not use it: {type(exc).__name__}: {exc}"
    if sorted(card["tolerances"]) != sorted(fork_aesthetic.CARD_AXES):
        return f"the card reads back with the axes {sorted(card['tolerances'])}"
    for name, got in (("driving", driving), ("trial", trial)):
        if got.as_posix() != where[name]["relative"]:
            return (
                f"the stored {name} {got.as_posix()} is not where the file is "
                f"copied to ({where[name]['relative']})"
            )
    if (first, last) != tuple(element["window"]):
        return f"the window reads back as {first}:{last}, not {element['window']}"
    return None


def _append_to_base(base: Path, element: dict) -> None:
    """Append the element to the base through a temporary file, so a half-written base cannot exist."""
    doc = json.loads(base.read_text(encoding="utf-8"))
    doc["aesthetics"] = list(doc["aesthetics"]) + [element]
    tmp = base.with_suffix(base.suffix + ".publishing")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, base)


def publish(draft, *, root=None, sizer=None) -> dict:
    """Move a draft into the product base, after every check has passed.

    Nothing is written unless `inspect` returns a pass, and a failure part way
    through the copying puts back what was there before, so a refused publish
    and a fallen publish leave the same tree: the one that was there.

    `draft` is the directory the build wrote; `root` is the tree to publish
    into, defaulting to this repository; `sizer` returns a picture's size.
    """
    report = inspect(draft, root=root, sizer=sizer)
    if report["outcome"] != PASS:
        return {**report, "written": [], "note": f"NOTHING WAS WRITTEN. {report['note']}"}

    draft = Path(draft)
    base = base_path_under(root)
    was = base.read_bytes()
    written: list[Path] = []
    try:
        for name, source in (
            ("demo", DRAFT_DEMO),
            ("driving", DRAFT_DRIVING),
            ("trial", DRAFT_TRIAL),
        ):
            dst = report["where"][name]["absolute"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(draft / source, dst)
            written.append(dst)
        _append_to_base(base, report["element"])
    except Exception as exc:  # noqa: BLE001
        for path in written:
            path.unlink(missing_ok=True)
        base.write_bytes(was)
        return {
            **report,
            "outcome": UNMEASURED,
            "violations": 0,
            "unmeasured": report["unmeasured"] + 1,
            "written": [],
            "note": (
                f"the publish fell part way through and was ROLLED BACK, "
                f"{len(written)} files removed and the base restored: "
                f"{type(exc).__name__}: {exc}"
            ),
        }

    return {
        **report,
        "written": [str(p) for p in written] + [str(base)],
        "note": (
            f"published {report['element']['id']!r}: {len(written)} files "
            f"copied and 1 element appended to the base, which now holds "
            f"{len(fork_aesthetic.ids(base))}. {report['note']}"
        ),
    }


def main(argv=None) -> int:
    """Run the publish from the command line and return the exit code for its outcome."""
    ap = argparse.ArgumentParser(
        prog="python3 -m lipsync.fork_aesthetic_publish",
        description="Move a built aesthetic draft into the product base.",
    )
    ap.add_argument("draft", help=f"the draft directory, holding {', '.join(DRAFT_FILES)}")
    ap.add_argument(
        "--root", default=None, help="the tree to publish into (default: this repository)"
    )
    ap.add_argument("--dry-run", action="store_true", help="run every check and write nothing")
    a = ap.parse_args(argv)

    report = inspect(a.draft, root=a.root) if a.dry_run else publish(a.draft, root=a.root)
    print(f"{report['outcome'].upper()}: {report['note']}")
    for problem in report.get("problems") or []:
        print(f"  - {problem}")
    for path in report.get("written") or []:
        print(f"  wrote {path}")
    return EXIT_BY_OUTCOME[report["outcome"]]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
