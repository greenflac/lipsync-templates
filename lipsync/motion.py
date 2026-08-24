"""Whether the clip MOVES well: does it loop, and is the motion physical."""

from __future__ import annotations

from pathlib import Path

SEAMLESS_MAX = 0.30

JUMP_MAX = 4.0

STILL_MIN = 0.15


def _gray(path: str | Path, side: int = 96):
    """A small grayscale array. Downscaled so the measure tracks BODY movement"""
    from PIL import Image
    import numpy as np

    with Image.open(path) as im:
        small = im.convert("L").resize((side, side), Image.BILINEAR)
    return np.asarray(small, dtype="float64")


def _steps(frames: list[str]) -> list[float]:
    """Mean absolute difference between each adjacent pair of frames."""
    import numpy as np

    arrs = [_gray(f) for f in frames]
    return [float(np.abs(arrs[i + 1] - arrs[i]).mean()) for i in range(len(arrs) - 1)]


def loop_seam(frames: list[str]) -> dict:
    """How visible the cut is when the clip repeats."""
    import numpy as np

    if len(frames) < 3:
        return {
            "ratio": None,
            "seam": None,
            "typical_step": None,
            "seamless": False,
            "note": "need at least 3 frames to judge a loop.",
        }
    steps = _steps(frames)
    typical = float(np.median(steps))
    seam = float(np.abs(_gray(frames[-1]) - _gray(frames[0])).mean())
    if typical == 0:
        return {
            "ratio": None,
            "seam": round(seam, 3),
            "typical_step": 0.0,
            "seamless": False,
            "note": "the clip does not move at all.",
        }
    ratio = seam / typical
    return {
        "ratio": round(ratio, 3),
        "seam": round(seam, 3),
        "typical_step": round(typical, 3),
        "seamless": ratio <= SEAMLESS_MAX,
        "note": (
            f"loop seam {ratio:.2f}x a typical frame step "
            f"({'seamless' if ratio <= SEAMLESS_MAX else 'visible cut on repeat'}; "
            f"bar {SEAMLESS_MAX})."
        ),
    }


def motion_quality(frames: list[str]) -> dict:
    """Is the movement continuous and physical, or does it jump and morph."""
    import numpy as np

    if len(frames) < 3:
        return {
            "worst_jump": None,
            "jumps": [],
            "moving": False,
            "smooth": False,
            "activity": None,
            "note": "need at least 3 frames to judge motion.",
        }
    steps = _steps(frames)
    typical = float(np.median(steps))
    if typical == 0:
        return {
            "worst_jump": None,
            "jumps": [],
            "moving": False,
            "smooth": False,
            "activity": 0.0,
            "note": "static clip: nothing moves.",
        }
    ratios = [s / typical for s in steps]
    worst = max(ratios)
    jumps = [i for i, r in enumerate(ratios) if r > JUMP_MAX]
    activity = typical / max(float(np.mean(_gray(frames[0]))), 1.0)
    moving = activity >= STILL_MIN / 10
    return {
        "worst_jump": round(worst, 3),
        "jumps": jumps,
        "moving": moving,
        "smooth": not jumps,
        "activity": round(activity, 4),
        "note": (
            f"largest frame step {worst:.1f}x the median"
            + (
                f"; {len(jumps)} discontinuity(ies) at {jumps} — "
                f"limbs teleport or the body morphs there"
                if jumps
                else "; motion is continuous"
            )
            + "."
        ),
    }


def best_loop_window_pose(points: list, *, size: int, stride: int = 1) -> dict:
    """Замкнутость окна ПО СКЕЛЕТУ, без порога. Лучше пиксельной по двум причинам."""
    span = (size - 1) * stride + 1
    if size < 3 or stride < 1 or len(points) < span:
        return {
            "start": 0,
            "hidden": None,
            "seam": None,
            "note": (f"поз {len(points)}, а окно требует {span} — выбирать не из чего"),
        }
    from .pose import pose_delta

    def gap(i: int, j: int):
        if not points[i] or not points[j]:
            return None
        got = pose_delta(points[i], points[j])
        return got["mean"] if got else None

    rows = []
    for s in range(len(points) - span + 1):
        seam = gap(s, s + span - 1)
        if seam is None:
            continue
        steps = [
            x
            for x in (gap(i, i + stride) for i in range(s, s + span - stride, stride))
            if x is not None
        ]
        if len(steps) < 2:
            continue
        hidden = sum(1 for x in steps if x >= seam) / len(steps)
        rows.append(
            {
                "start": s,
                "seam": round(seam, 4),
                "hidden": round(hidden, 3),
                "steps": len(steps),
                "local_median": round(sorted(steps)[len(steps) // 2], 4),
            }
        )
    if not rows:
        return {
            "start": 0,
            "hidden": None,
            "seam": None,
            "note": "скелет не найден на нужных кадрах — судить нечем",
        }
    best = max(rows, key=lambda r: (r["hidden"], -r["seam"]))
    return {
        **best,
        "candidates": len(rows),
        "note": (
            f"лучшее окно {best['start']}..{best['start'] + span - 1} "
            f"из {len(rows)}: стык {best['seam']} при локальной "
            f"медиане {best['local_median']}, то есть мельче "
            f"{round(best['hidden'] * best['steps'])} рядовых шагов "
            f"из {best['steps']}. Порога здесь НЕТ намеренно: облака "
            f"перекрылись, и сравнение идёт с самим материалом"
        ),
    }


def best_loop_window(frames: list[str], *, size: int, stride: int = 1) -> dict:
    """Какое ОКНО исходника замыкается лучше всех. Выбор до генерации, не после."""
    import numpy as np

    span = (size - 1) * stride + 1
    if size < 2 or stride < 1 or len(frames) < span:
        return {
            "start": 0,
            "ratio": None,
            "seamless": False,
            "note": (f"кадров {len(frames)}, а окно требует {span} — выбирать не из чего"),
        }
    arrs = [_gray(f) for f in frames]
    steps = [float(np.abs(arrs[i + 1] - arrs[i]).mean()) for i in range(len(arrs) - 1)]
    typical = float(np.median(steps)) or 1.0
    scored = [
        (float(np.abs(arrs[s + span - 1] - arrs[s]).mean()) / typical, s)
        for s in range(len(frames) - span + 1)
    ]
    ratio, start = min(scored)
    worst = max(scored)[0]
    return {
        "start": start,
        "ratio": round(ratio, 3),
        "seamless": ratio <= SEAMLESS_MAX,
        "worst_ratio": round(worst, 3),
        "candidates": len(scored),
        "note": (
            f"лучшее окно {start}..{start + span - 1} из "
            f"{len(scored)} возможных: стык {ratio:.3f} при баре "
            f"{SEAMLESS_MAX} (худшее окно дало бы {worst:.3f})"
            + (
                ""
                if ratio <= SEAMLESS_MAX
                else " — бар не взят: движение исходника нециклично, и "
                "выбор окна это улучшает, а не чинит"
            )
        ),
    }


def best_loop_cut(frames: list[str], *, min_keep: float = 0.5) -> dict:
    """Find where to cut so the clip loops, without generating anything new."""
    import numpy as np

    if len(frames) < 4:
        return {
            "cut_at": len(frames) - 1,
            "ratio": None,
            "seamless": False,
            "note": "too few frames to search for a loop point.",
        }
    arrs = [_gray(f) for f in frames]
    steps = [float(np.abs(arrs[i + 1] - arrs[i]).mean()) for i in range(len(arrs) - 1)]
    typical = float(np.median(steps)) or 1.0
    first = int(len(frames) * min_keep)
    scores = {
        i: float(np.abs(arrs[i] - arrs[0]).mean()) / typical
        for i in range(max(first, 2), len(frames))
    }
    cut = min(scores, key=lambda i: scores[i])
    ratio = round(scores[cut], 3)
    kept = (cut + 1) / len(frames)
    return {
        "cut_at": cut,
        "ratio": ratio,
        "seamless": ratio <= SEAMLESS_MAX,
        "kept_fraction": round(kept, 3),
        "note": (
            f"best loop point is frame {cut}/{len(frames) - 1} "
            f"(seam {ratio:.2f}x a typical step, keeps {kept:.0%} of the "
            f"clip){'' if ratio <= SEAMLESS_MAX else ' — still visible'}."
        ),
    }


def trim_to_loop(mp4_path: str | Path, frames: list[str], out_mp4: str | Path, *, fps: int) -> dict:
    """Cut an mp4 at its best loop point with ffmpeg. Returns the cut report."""
    import subprocess

    cut = best_loop_cut(frames)
    if cut["ratio"] is None:
        return cut
    duration = (cut["cut_at"] + 1) / float(fps)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(mp4_path),
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(out_mp4),
        ],
        check=True,
        capture_output=True,
    )
    return {**cut, "out": str(out_mp4), "duration": round(duration, 3)}


PHYSICAL_MOTION = (
    "The ball compresses under their weight and rebounds, driving the bounce. "
    "Their feet stay in contact with the ball, knees absorb the landing, arms "
    "counterbalance. Real weight and momentum, continuous single take, no cuts, "
    "no camera move."
)

LOOP_MOTION = (
    "One complete bounce cycle that ends exactly where it began, so the clip "
    "repeats seamlessly. Keep moving through the final frame — do not slow to a "
    "stop, freeze or fade."
)
