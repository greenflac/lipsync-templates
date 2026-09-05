#!/usr/bin/env python3
"""Does the same patch repeat across unrelated cases? Then it is an overlay.

    python scripts/check_burned_marks.py --check

WHY THIS EXISTS

MEASURED 2026-08-30, and the blind readers found it before I did: Kling burns
"KLING AI 1.6" into the bottom-right of every frame — the model AND the version,
in words. Sixteen cases were therefore answerable by reading a caption instead
of the picture, and the score over them would have been a flattering number
about nothing.

Metadata stripping cannot touch this. The giveaway is in the pixels.

HOW IT IS CAUGHT WITHOUT READING THE TEXT

An overlay is the same pixels in the same place on pictures that share nothing
else. So: take the same corner from cases that are otherwise unrelated and
measure how alike they are. Real content in a corner varies wildly between
scenes; a logo does not. No OCR, no model, no list of known watermarks — and
therefore it catches a mark nobody has seen before, which a list never would.

IT DOES NOT WORK, AND THAT IS THE POINT OF THIS DOCSTRING

Recorded rather than quietly deleted (rule I6), because the idea is obvious
enough that somebody will have it again.

MEASURED 2026-08-30 on the very bank whose contamination is KNOWN — sixteen
Kling clips all carrying the same burned-in mark:

    только Kling, угол всей полосы   медиана 0.13  макс 0.58  доля>0.8  0.0%
    угол последнего кадра, patch 0.28 медиана 0.13  макс 0.47  доля>0.7  0.0%
    OpenFake, тот же замер            медиана 0.22  макс 0.78  доля>0.7  2.9%

The contaminated group scores LOWER than the clean one. Correlation over a patch
cannot see a small semi-transparent logo sitting on content that changes
completely between cases: the varying pixels dominate the statistic and the
constant ones are a rounding error in it.

So this is NOT wired into `scripts/check`. Shipping it as a gate would print
`pass` over a bank known to be contaminated, which is the false clean this
package keeps a rule against — worse than no check, because nobody re-examines
a clean.

WHAT WOULD PROBABLY WORK, for whoever picks this up: subtract the per-group
MEDIAN image and look at what survives, rather than correlating raw patches. A
constant overlay is exactly what a median across differing scenes preserves.
That is a bigger job than the twenty minutes this had, and it was not started
rather than half-started.

WHAT IS USED INSTEAD, today: the strip is cropped before the reader sees it
(`WATERMARK_STRIP` in `scripts/contact_sheets.py`) and the crop is checked by a
person looking at it. Cheaper, and it removes the giveaway rather than reporting
it.
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

BANK = Path(__file__).resolve().parents[1] / "work" / "casebank"

#: Which corner. ВЫБРАНО from where the mark was found; all four are checked, so
#: this is the reporting order rather than an assumption about where to look.
CORNERS = ("низ-право", "низ-лево", "верх-право", "верх-лево")

#: Fraction of width and height a corner patch covers.
PATCH = 0.18

#: Above this, a corner is judged an overlay rather than content. ВЫБРАНО.
SUSPICIOUS_SIMILARITY = 0.80

#: Fewer than this and one coincidence looks like a pattern.
MIN_PAIRS = 6


def _corner(path: Path, which: str) -> np.ndarray | None:
    from PIL import Image

    try:
        image = Image.open(path).convert("L")
    except OSError:
        return None
    w, h = image.size
    pw, ph = max(int(w * PATCH), 8), max(int(h * PATCH), 8)
    box = {
        "низ-право": (w - pw, h - ph, w, h),
        "низ-лево": (0, h - ph, pw, h),
        "верх-право": (w - pw, 0, w, ph),
        "верх-лево": (0, 0, pw, ph),
    }[which]
    patch = np.asarray(image.crop(box).resize((48, 48))).astype(np.float32)
    return patch


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Correlation of two patches, 0 when either is flat."""
    x, y = a.ravel() - a.mean(), b.ravel() - b.mean()
    denom = float(np.linalg.norm(x) * np.linalg.norm(y))
    return 0.0 if denom < 1e-6 else float(abs(x @ y) / denom)


def scan(paths: list[Path]) -> dict:
    if len(paths) < 3:
        return {
            "outcome": UNMEASURED,
            "checked": len(paths),
            "violations": 0,
            "unmeasured": 1,
            "note": "меньше трёх разборов: одно совпадение неотличимо от закономерности",
        }
    findings: list[str] = []
    scores: dict[str, float] = {}
    for corner in CORNERS:
        patches = [p for p in (_corner(path, corner) for path in paths) if p is not None]
        pairs = list(itertools.combinations(range(len(patches)), 2))
        if len(pairs) < MIN_PAIRS:
            continue
        values = [similarity(patches[i], patches[j]) for i, j in pairs]
        median = float(np.median(values))
        scores[corner] = round(median, 3)
        if median >= SUSPICIOUS_SIMILARITY:
            findings.append(
                f"{corner}: медианная схожесть {median:.3f} по {len(pairs)} парам — "
                "в этом углу у не связанных между собой разборов одно и то же, "
                "то есть наложение, а не содержание"
            )
    return {
        "outcome": FAIL if findings else PASS,
        "checked": len(paths),
        "violations": len(findings),
        "unmeasured": 0,
        "по_углам": scores,
        "note": "; ".join(findings)
        if findings
        else f"ни один угол не повторяется: максимум {max(scores.values(), default=0)}",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(BANK / "blind"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    folder = Path(args.dir)
    paths = sorted(folder.glob("*.jpg")) if folder.is_dir() else []
    out = scan(paths)
    print(f"углы: {out.get('по_углам')}")
    print(
        f"\nпроверено {out['checked']}\nнарушений {out['violations']}\nне смогли {out['unmeasured']}"
    )
    print(f"\n{out['outcome']}: {out['note']}")
    if not args.check:
        return 0
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[out["outcome"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
