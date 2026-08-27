"""Provide the output window arithmetic: frames, seconds, sampler windows."""

from __future__ import annotations

LENGTH_STEP = 4
LENGTH_BASE = 1

WRAP_FPS = 30

WRAP_WINDOW = 77

SECONDS_MIN = 5.0
SECONDS_MAX = 10.0


def snap_frames(requested: int) -> int:
    """Return how many frames the wrapper will actually produce for the requested count."""
    if not isinstance(requested, int) or isinstance(requested, bool):
        raise TypeError(f"frame count must be an integer, got {requested!r}")
    if requested < LENGTH_BASE:
        raise ValueError(f"{requested} frame(s), minimum is {LENGTH_BASE}")
    return ((requested - LENGTH_BASE) // LENGTH_STEP) * LENGTH_STEP + LENGTH_BASE


def frames_for_seconds(seconds: float, *, fps: int | None = None, bench: bool = False) -> dict:
    """Return the clip length in frames, with the honest gap between "asked for" and "will come out"."""
    fps = WRAP_FPS if fps is None else fps
    floor = 0 if bench else SECONDS_MIN
    if not floor < seconds <= SECONDS_MAX if bench else not SECONDS_MIN <= seconds <= SECONDS_MAX:
        raise ValueError(
            f"length {seconds} s is outside the band "
            f"{'>0' if bench else SECONDS_MIN}-{SECONDS_MAX} s "
            f'(the template author\'s decision, section "Output format")'
            + (" — only the lower bound is relaxed for a bench run" if bench else "")
        )
    requested = int(round(seconds * fps))
    frames = snap_frames(requested)
    return {
        "seconds_requested": seconds,
        "fps": fps,
        "frames_requested": requested,
        "frames": frames,
        "snapped_away": requested - frames,
        "seconds_actual": round(frames / fps, 4),
        "note": (
            f"{seconds} s at {fps} fps = {requested} frames, the wrapper "
            f"will snap it to {frames} (step {LENGTH_STEP} from {LENGTH_BASE}); "
            f"frames silently lost: {requested - frames}"
            + (
                ""
                if not bench or seconds >= SECONDS_MIN
                else f". Below the {SECONDS_MIN} s floor — a bench run; it does "
                f"not verify the product claim about length"
            )
        ),
    }


def window_plan(frames: int, *, window: int | None = None) -> dict:
    """Return how many windows the sampler will run and how many frames it generates in vain."""
    window = WRAP_WINDOW if window is None else window
    if frames < 1 or window < 1:
        raise ValueError(f"{frames} frame(s), window {window} — both must be at least 1")
    if frames <= window:
        return {
            "windows": 1,
            "generated": frames,
            "discarded": 0,
            "window": window,
            "note": f"{frames} frame(s) fit into a single window of {window}",
        }
    step = window - 1
    windows = -(-(frames - 1) // step)
    generated = windows * step + 1
    return {
        "windows": windows,
        "generated": generated,
        "discarded": generated - frames,
        "window": window,
        "note": (
            f"{frames} frames in windows of {window}: {windows} window(s), "
            f"{generated} will be generated, {generated - frames} "
            f"discarded"
        ),
    }
