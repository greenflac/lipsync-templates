"""Provide the output length arithmetic: seconds in, frames out."""

from __future__ import annotations

LENGTH_STEP = 4
#: DERIVED from the sampler wrapper this arithmetic was lifted out of verbatim:
#: its node reference gives a step of 4 over a minimum length of 1. The wrapper's
#: prose said "length is a multiple of 4" and was dropped as the weaker source —
#: the wrapper's own stock length of 77 is not a multiple of 4, so the prose read
#: literally would have condemned the stack's standard geometry.
LENGTH_BASE = 1

WRAP_FPS = 30

SECONDS_MIN = 5.0
SECONDS_MAX = 10.0


def snap_frames(requested: int) -> int:
    """Return how many frames the wrapper will actually produce for the requested count."""
    if not isinstance(requested, int) or isinstance(requested, bool):
        raise TypeError(f"frame count must be an integer, got {requested!r}")
    if requested < LENGTH_BASE:
        raise ValueError(f"{requested} frame(s), minimum is {LENGTH_BASE}")
    return ((requested - LENGTH_BASE) // LENGTH_STEP) * LENGTH_STEP + LENGTH_BASE
