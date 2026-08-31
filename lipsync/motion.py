"""Pixel primitives for judging movement between two frames.

Everything else this module once held — loop seams, jump reports, window and
cut choosers, an ffmpeg trim — measured a clip AFTER it had been sampled
locally, one candidate at a time. The product never sees that moment: Kling
generates the clip remotely from a driving video, and the operator names the
window of that driving video by hand, with `--window`. The loop finder that
used to choose it for him was deleted on 2026-08-31 as a tool the product does
not run.

What survives is the pixel side of that finder, which two production paths do
run: the intake asks this module where the driving is edited, and the output
acceptance asks it whether Kling put a cut inside a single scene.

numpy and Pillow only — no model, no network.
"""

from __future__ import annotations

import time
from pathlib import Path

from .fork_identity import PASS, UNMEASURED

#: A single inter-frame step this many times the median step is a
#: discontinuity, not movement — the mark of an edit, a teleport or a morph
#: rather than a body moving. A ratio and not an absolute pixel distance: a
#: calm clip and a violent one have completely different frame-to-frame
#: magnitudes, so any fixed number would be tuned to one and wrong for the
#: other. It is the bar `cuts` below stands on, and the only one.
JUMP_MAX = 4.0

#: CHOSEN: the side, in pixels, the frame is squashed to before the difference
#: is taken. No measurement stands behind the number itself; what it encodes is
#: the reason in `_gray` — small enough that sensor noise and compression
#: shimmer average away, large enough that a body moving still shows.
CUT_SIDE = 96


def _gray(path: str | Path, side: int = CUT_SIDE):
    """A small grayscale array. Downscaled so the measure tracks BODY movement
    rather than sensor noise and compression shimmer."""
    from PIL import Image
    import numpy as np

    with Image.open(path) as im:
        small = im.convert("L").resize((side, side), Image.Resampling.BILINEAR)
    return np.asarray(small, dtype="float64")


def read_gray(path):
    """Return a downscaled gray frame. Injection point: the test replaces it wholesale."""
    return _gray(path, CUT_SIDE)


def cuts(paths, *, gray=None, jump=None) -> dict:
    """Find editing cuts in the clip. Cheap, pixel-based, BEFORE capturing poses."""
    import numpy as np

    gray = read_gray if gray is None else gray
    jump = JUMP_MAX if jump is None else jump
    t = time.perf_counter()
    steps, prev = [], None
    for p in paths:
        cur = gray(str(p))
        if prev is not None:
            steps.append(float(np.abs(cur - prev).mean()))
        prev = cur
    elapsed = round(time.perf_counter() - t, 4)
    if not steps:
        return {
            "outcome": UNMEASURED,
            "cuts": [],
            "steps": 0,
            "median": None,
            "worst": None,
            "elapsed": elapsed,
            "note": "fewer than two frames: nothing to look for cuts in",
        }
    med = float(np.median(steps))
    if med <= 0:
        return {
            "outcome": UNMEASURED,
            "cuts": [],
            "steps": len(steps),
            "median": 0.0,
            "worst": round(max(steps), 4),
            "elapsed": elapsed,
            "note": (
                "the typical inter-frame jump is zero: nothing to compare "
                "against, cuts were NOT SEARCHED for. This is not 'no cuts'"
            ),
        }
    found = [k for k, v in enumerate(steps) if v / med > jump]
    worst = max(steps) / med
    # A sample, not the list: the note says how many of how many it shows.
    # CHOSEN: ten frame numbers keep the note to one line; "cuts" carries all.
    shown = found[:10]
    return {
        "outcome": PASS,
        "cuts": found,
        "steps": len(steps),
        "median": round(med, 4),
        "worst": round(worst, 2),
        "elapsed": elapsed,
        "note": (
            f"cuts found {len(found)} across {len(steps)} transitions "
            f"(bar {jump}x the typical jump, sharpest transition "
            f"{worst:.2f}x)"
            + (f"; seam frames, first {len(shown)} of {len(found)}: {shown}" if found else "")
        ),
    }
