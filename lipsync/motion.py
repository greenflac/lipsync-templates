"""Pixel primitives for judging movement between two frames.

Everything else this module once held — loop seams, jump reports, window and
cut choosers, an ffmpeg trim — measured a clip AFTER it had been sampled
locally, one candidate at a time. The product never sees that moment: Kling
generates the clip remotely from a driving video, and the only movement
decision left is which window of that driving video to loop. `fork_looper`
makes it, with its own three seam axes and its own three outcomes, so a second
implementation here would be a copy of knowledge with nothing to keep the two
honest.

What survives is what `fork_looper` actually borrows: the bar for "that is a
cut, not motion", and the grayscale reader it is measured on.

numpy and Pillow only — no model, no network.
"""

from __future__ import annotations

from pathlib import Path

#: A single inter-frame step this many times the median step is a
#: discontinuity, not movement — the mark of an edit, a teleport or a morph
#: rather than a body moving. A ratio and not an absolute pixel distance: a
#: calm clip and a violent one have completely different frame-to-frame
#: magnitudes, so any fixed number would be tuned to one and wrong for the
#: other. Read by `fork_looper.CUT_JUMP`, which is where it is exercised.
JUMP_MAX = 4.0


def _gray(path: str | Path, side: int = 96):
    """A small grayscale array. Downscaled so the measure tracks BODY movement
    rather than sensor noise and compression shimmer."""
    from PIL import Image
    import numpy as np

    with Image.open(path) as im:
        small = im.convert("L").resize((side, side), Image.Resampling.BILINEAR)
    return np.asarray(small, dtype="float64")
