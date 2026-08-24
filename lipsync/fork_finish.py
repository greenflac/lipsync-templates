"""Assemble the final clip after Kling: crop to 9:16 plus audio return."""

from __future__ import annotations

import time

from . import fork_video
from .fork_identity import FAIL, PASS, UNMEASURED


#: CHOSEN (by the template author, from the platforms' vertical formats): 9:16 is the feed frame.
TARGET_RATIO_W, TARGET_RATIO_H = 9, 16

#: DERIVED (from how yuv420p works): chroma is halved, so both sides must be even.
DIM_MULTIPLE = 2

#: DERIVED (not our measurement: ITU-R BT.1359-1): audio ahead of the picture is noticeable from 45 ms; the narrow side is taken because the sign of the shift is unknown by construction.
LIPSYNC_AUDIO_AHEAD_MS = 45

#: CHOSEN from what was MEASURED: the best window on live material scores 1.0024 of the central one — that is noise; the bar must not go lower.
BIAS_GAIN_MIN = 1.05

#: CHOSEN: the window bias is a fraction from -1 to +1, not pixels (the output resolution has already changed once).
BIAS_LIMIT = 1.0

#: CHOSEN: CRF 18 in x264 is visually near lossless; audio goes to aac 128k, because copy keeps an extra chunk when cutting.
VIDEO_CRF = 18
VIDEO_PRESET = "veryfast"
AUDIO_BITRATE = "128k"

EXIT_BY_OUTCOME = fork_video.EXIT_BY_OUTCOME


def _even(value: int) -> int:
    """Round down to a multiple of DIM_MULTIPLE. Down, not up: up would leave the frame."""
    return int(value) - int(value) % DIM_MULTIPLE


def crop_geometry(
    width, height, *, ratio_w=TARGET_RATIO_W, ratio_h=TARGET_RATIO_H, bias=0.0
) -> dict:
    """Plan the crop: where to cut which window, and how much area is lost."""
    if width is None or height is None:
        return {
            **_geom_blank(),
            "outcome": UNMEASURED,
            "note": (
                f"frame dimensions not taken (width {width}, height {height}): "
                f"nothing to cut blindly"
            ),
        }
    for name, value in (("width", width), ("height", height)):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return {
                **_geom_blank(),
                "outcome": FAIL,
                "note": f"frame {name} is meaningless: {value!r}",
            }
    if not (isinstance(ratio_w, int) and isinstance(ratio_h, int) and ratio_w > 0 and ratio_h > 0):
        return {
            **_geom_blank(),
            "outcome": FAIL,
            "note": f"the aspect ratio is meaningless: {ratio_w}:{ratio_h}",
        }
    try:
        bias = float(bias)
    except (TypeError, ValueError):
        return {**_geom_blank(), "outcome": FAIL, "note": f"the bias is not a number: {bias!r}"}
    if not -BIAS_LIMIT <= bias <= BIAS_LIMIT:
        return {
            **_geom_blank(),
            "outcome": FAIL,
            "note": (f"bias {bias:g} outside the band [{-BIAS_LIMIT:g}; {BIAS_LIMIT:g}]"),
        }

    src, want = width * ratio_h, height * ratio_w
    if src > want:
        w, h, axis = _even(height * ratio_w // ratio_h), _even(height), "along the width"
    elif src < want:
        w, h, axis = _even(width), _even(width * ratio_h // ratio_w), "along the height"
    else:
        w, h, axis = _even(width), _even(height), "cutting nothing"
    if w < DIM_MULTIPLE or h < DIM_MULTIPLE:
        return {
            **_geom_blank(),
            "outcome": FAIL,
            "note": (
                f"window {w}x{h} is degenerate: the ratio "
                f"{ratio_w}:{ratio_h} cannot be assembled from {width}x{height}"
            ),
        }

    free_x, free_y = width - w, height - h
    x = _even(round((bias + 1) / 2 * free_x))
    y = _even(round((bias + 1) / 2 * free_y)) if free_y else 0
    x, y = min(x, _even(free_x)), min(y, _even(free_y))
    kept = 100.0 * (w * h) / (width * height)
    lost = 100.0 - kept
    return {
        "outcome": PASS,
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "lost_percent": round(lost, 2),
        "kept_percent": round(kept, 2),
        "axis": axis,
        "note": (
            f"from {width}x{height} we cut {w}x{h} {axis} with bias "
            f"{bias:+.2f} (window x={x}, y={y}); {round(kept, 2):g}% of "
            f"the area remains, {round(lost, 2):g}% is lost"
        ),
    }


def _geom_blank() -> dict:
    return {
        "x": None,
        "y": None,
        "w": None,
        "h": None,
        "lost_percent": None,
        "kept_percent": None,
        "axis": None,
    }


def bias_from_columns(columns, *, ratio_w=TARGET_RATIO_W, ratio_h=TARGET_RATIO_H) -> dict:
    """Pick the window bias from a per-column motion map. An instrument with a negative control."""
    if columns is None:
        return {
            "outcome": UNMEASURED,
            "bias": 0.0,
            "gain": None,
            "note": "no motion map: nothing to bias with, taking the centre",
        }
    try:
        cols = [float(c) for c in columns]
    except (TypeError, ValueError):
        return {
            "outcome": FAIL,
            "bias": 0.0,
            "gain": None,
            "note": "the motion map does not parse into numbers",
        }
    if any(c < 0 for c in cols):
        return {
            "outcome": FAIL,
            "bias": 0.0,
            "gain": None,
            "note": "the motion map holds negative values",
        }
    width = len(cols)
    win = round(width * ratio_w / ratio_h)
    if width < 2 or win < 1 or win >= width:
        return {
            "outcome": UNMEASURED,
            "bias": 0.0,
            "gain": None,
            "note": (
                f"nothing to choose from: {width} columns, window {win} — "
                f"a bias does not exist, taking the centre"
            ),
        }
    if sum(cols) <= 0:
        return {
            "outcome": UNMEASURED,
            "bias": 0.0,
            "gain": None,
            "note": (
                f"no motion in the frame at all (map sum 0 over "
                f"{width} columns): nothing to choose by, taking the centre"
            ),
        }
    sums = [sum(cols[i : i + win]) for i in range(width - win + 1)]
    best = max(range(len(sums)), key=lambda i: sums[i])
    center = (width - win) // 2
    gain = sums[best] / sums[center] if sums[center] > 0 else float("inf")
    if gain < BIAS_GAIN_MIN:
        return {
            "outcome": UNMEASURED,
            "bias": 0.0,
            "gain": round(gain, 4),
            "note": (
                f"the motion map is flat: the best window (x={best}) "
                f"beats the central one (x={center}) by only "
                f"{round(gain, 4)}x against the threshold {BIAS_GAIN_MIN} — "
                f"that is noise, not a person standing aside. Taking the centre"
            ),
        }
    bias = (best / (width - win)) * 2 - 1
    return {
        "outcome": PASS,
        "bias": round(bias, 3),
        "gain": round(gain, 4),
        "note": (
            f"the motion sits on window x={best} of {width - win} "
            f"possible (bias {bias:+.3f}), beating the centre by "
            f"{round(gain, 4)}x against the threshold {BIAS_GAIN_MIN}"
        ),
    }


def window_frames(first, last) -> dict:
    """Count the frames in the window [first..last]. Both bounds inclusive."""
    if first is None or last is None:
        return {
            "outcome": UNMEASURED,
            "frames": None,
            "note": f"window bounds not given: [{first}..{last}]",
        }
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (first, last)):
        return {
            "outcome": FAIL,
            "frames": None,
            "note": f"window bounds are not integers: [{first!r}..{last!r}]",
        }
    if first < 0:
        return {"outcome": FAIL, "frames": None, "note": f"the window start is negative: {first}"}
    if last < first:
        return {
            "outcome": FAIL,
            "frames": None,
            "note": f"the window end {last} comes before the start {first}",
        }
    return {
        "outcome": PASS,
        "frames": last - first + 1,
        "note": f"window [{first}..{last}] inclusive — {last - first + 1} frames",
    }


def drift_tolerance_frames(fps):
    """Convert the drift tolerance into frames at this rate. The physics is in milliseconds."""
    if fps is None:
        return None
    try:
        fps = float(fps)
    except (TypeError, ValueError):
        return None
    if fps <= 0:
        return None
    return int(LIPSYNC_AUDIO_AHEAD_MS * fps / 1000)


def audio_drift(expected_frames, actual_frames, *, fps) -> dict:
    """Compare the expected window length with the actual length of the Kling output."""
    tol = drift_tolerance_frames(fps)
    blank = {
        "glue": False,
        "drift_frames": None,
        "drift_ms": None,
        "tolerance": tol,
        "expected": expected_frames,
        "actual": actual_frames,
    }
    if tol is None:
        return {
            **blank,
            "outcome": UNMEASURED,
            "note": (
                f"the rate was not taken ({fps!r}): nothing to convert "
                f"frames to milliseconds with, nothing to judge the lips by"
            ),
        }
    if expected_frames is None or actual_frames is None:
        return {
            **blank,
            "outcome": UNMEASURED,
            "note": (
                f"the duration is unreadable: window {expected_frames}, "
                f"output {actual_frames} frames"
            ),
        }
    if expected_frames <= 0 or actual_frames <= 0:
        return {
            **blank,
            "outcome": FAIL,
            "note": (f"frame counts cannot be {expected_frames} and {actual_frames}"),
        }
    drift = int(actual_frames) - int(expected_frames)
    ms = round(drift / float(fps) * 1000, 1)
    side = "longer than" if drift > 0 else "shorter than"
    common = {**blank, "drift_frames": drift, "drift_ms": ms}
    if drift == 0:
        return {
            **common,
            "outcome": PASS,
            "glue": True,
            "note": (
                f"frame for frame: window {expected_frames}, output "
                f"{actual_frames}, gap 0 — the audio glues on "
                f"as is"
            ),
        }
    if abs(drift) <= tol:
        return {
            **common,
            "outcome": PASS,
            "glue": True,
            "note": (
                f"the output is {side} the window by {abs(drift)} frame(s) "
                f"({abs(ms):g} ms): window {expected_frames}, output "
                f"{actual_frames}. Tolerance {tol} frame(s) at "
                f"{float(fps):g} fps — the audio glues on, but a lip shift "
                f"up to {abs(ms):g} ms is possible, because where exactly "
                f"Kling lost the frame is unknown"
            ),
        }
    return {
        **common,
        "outcome": FAIL,
        "glue": False,
        "note": (
            f"the output is {side} the window by {abs(drift)} frame(s) "
            f"({abs(ms):g} ms) against the tolerance {tol}: window "
            f"{expected_frames}, output {actual_frames}. The audio does "
            f"not glue on — silently drifted lips are worse than a mute clip"
        ),
    }


def mux_argv(
    kling_path, out_path, geom, *, driving_path=None, start_seconds=None, seconds=None
) -> list:
    """Build the assembly command apart from running it: its makeup is a decision."""
    argv = [fork_video.FFMPEG_BIN, "-nostdin", "-v", "error", "-y", "-i", str(kling_path)]
    with_audio = driving_path is not None
    if with_audio:
        if start_seconds is not None:
            argv += ["-ss", f"{float(start_seconds):.6f}"]
        if seconds is not None:
            argv += ["-t", f"{float(seconds):.6f}"]
        argv += ["-i", str(driving_path)]
    argv += [
        "-filter_complex",
        f"[0:v]crop={geom['w']}:{geom['h']}:{geom['x']}:{geom['y']}[v]",
        "-map",
        "[v]",
    ]
    if with_audio:
        argv += ["-map", "1:a", "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-shortest"]
    else:
        argv += ["-an"]
    argv += [
        "-c:v",
        "libx264",
        "-preset",
        VIDEO_PRESET,
        "-crf",
        str(VIDEO_CRF),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    return argv


def audio_plan(driving_path, window, kling_path, *, prober=None) -> dict:
    """Decide whether the audio can return and with what shift. No step stays silent."""
    t = time.perf_counter()
    steps: list = []
    drv = fork_video.probe(driving_path, prober=prober)
    steps.append(("probing the driving", drv["outcome"], drv["note"]))
    kln = fork_video.probe(kling_path, prober=prober)
    steps.append(("probing the Kling output", kln["outcome"], kln["note"]))
    win = window_frames(*window)
    steps.append(("window", win["outcome"], win["note"]))

    out = {
        "steps": steps,
        "glue": False,
        "drift_frames": None,
        "drift_ms": None,
        "tolerance": None,
        "expected": win["frames"],
        "actual": kln.get("frames"),
        "fps": drv.get("fps"),
        "start_seconds": None,
        "seconds": None,
        "elapsed": round(time.perf_counter() - t, 4),
    }

    if UNMEASURED in (drv["outcome"], kln["outcome"]):
        return {
            **out,
            "outcome": UNMEASURED,
            "note": "metadata not taken, nothing to judge the audio by",
        }
    if FAIL in (drv["outcome"], kln["outcome"], win["outcome"]):
        return {**out, "outcome": FAIL, "note": "the material is unfit: see the steps above"}
    if win["outcome"] == UNMEASURED:
        return {**out, "outcome": UNMEASURED, "note": win["note"]}
    if not drv.get("audio"):
        return {
            **out,
            "outcome": FAIL,
            "note": (
                f"the driving {driving_path} has no audio track — nothing "
                f"to return. This is not an assembly failure, this is the "
                f"wrong file: the window was cut from a clip with audio"
            ),
        }
    fps = drv.get("fps")
    kfps = kln.get("fps")
    # The metadata step above already returned UNMEASURED when the rate was
    # not measured, so fps cannot be None here; the assert states the invariant.
    assert fps is not None
    if kfps is not None and abs(float(kfps) - float(fps)) > fork_video.FPS_TOLERANCE:
        return {
            **out,
            "outcome": FAIL,
            "note": (
                f"the rates diverged: driving {float(fps):g} fps, "
                f"Kling output {float(kfps):g} fps. Comparing lengths "
                f"in frames at different rates is forbidden — a frame "
                f"means a different time"
            ),
        }
    if win["frames"] is not None and drv.get("frames") is not None:
        if window[1] >= drv["frames"]:
            return {
                **out,
                "outcome": FAIL,
                "note": (
                    f"the window [{window[0]}..{window[1]}] leaves the "
                    f"driving: it holds {drv['frames']} frames "
                    f"(last number {drv['frames'] - 1})"
                ),
            }
    drift = audio_drift(win["frames"], kln.get("frames"), fps=fps)
    steps.append(("length check", drift["outcome"], drift["note"]))
    return {
        **out,
        **{
            k: drift[k]
            for k in (
                "outcome",
                "glue",
                "drift_frames",
                "drift_ms",
                "tolerance",
                "expected",
                "actual",
            )
        },
        "note": drift["note"],
        "start_seconds": round(window[0] / float(fps), 6),
        "seconds": round(kln["frames"] / float(fps), 6),
        "elapsed": round(time.perf_counter() - t, 4),
    }


def finish(
    driving_path,
    kling_path,
    out_path,
    *,
    window,
    bias=0.0,
    ratio_w=TARGET_RATIO_W,
    ratio_h=TARGET_RATIO_H,
    prober=None,
    runner=None,
) -> dict:
    """Assemble the final clip: crop plus audio plus a report. No step stays silent."""
    runner = fork_video.run_decode if runner is None else runner
    t = time.perf_counter()
    steps: list = []

    def report(outcome, note, **extra):
        return {
            "outcome": outcome,
            "note": note,
            "steps": steps,
            "out": str(out_path),
            "written": False,
            "audio": False,
            "crop": None,
            "audio_plan": None,
            "argv": None,
            "elapsed": round(time.perf_counter() - t, 4),
            **extra,
        }

    kln = fork_video.probe(kling_path, prober=prober)
    steps.append(("probing the Kling output", kln["outcome"], kln["note"]))
    if kln["outcome"] != PASS:
        return report(kln["outcome"], f"the Kling output was not probed: {kln['note']}")

    geom = crop_geometry(kln["width"], kln["height"], ratio_w=ratio_w, ratio_h=ratio_h, bias=bias)
    steps.append(("crop", geom["outcome"], geom["note"]))
    if geom["outcome"] != PASS:
        return report(geom["outcome"], f"the crop was not computed: {geom['note']}", crop=geom)

    plan = audio_plan(driving_path, window, kling_path, prober=prober)
    steps.extend(plan["steps"])
    steps.append(("audio", plan["outcome"], plan["note"]))
    if plan["outcome"] == UNMEASURED:
        return report(
            UNMEASURED, f"the audio was not checked: {plan['note']}", crop=geom, audio_plan=plan
        )

    argv = mux_argv(
        kling_path,
        out_path,
        geom,
        driving_path=driving_path if plan["glue"] else None,
        start_seconds=plan["start_seconds"],
        seconds=plan["seconds"],
    )
    ran = runner(argv)
    steps.append(
        (
            "assembly",
            PASS
            if ran.get("ran") and not ran.get("code")
            else (UNMEASURED if not ran.get("ran") else FAIL),
            (
                ran.get("why")
                or f"ffmpeg returned {ran.get('code')}: {(ran.get('err') or '').strip()[:200]}"
            )
            if (not ran.get("ran") or ran.get("code"))
            else f"ffmpeg ran to completion, a command of {len(argv)} words",
        )
    )
    if not ran.get("ran"):
        return report(
            UNMEASURED,
            f"nothing to assemble with: {ran.get('why')}",
            crop=geom,
            audio_plan=plan,
            argv=argv,
        )
    if ran.get("code"):
        return report(
            FAIL,
            f"ffmpeg returned {ran['code']}: {(ran.get('err') or '').strip()[:200]}",
            crop=geom,
            audio_plan=plan,
            argv=argv,
        )

    got = fork_video.probe(out_path, prober=prober)
    steps.append(("probing the result", got["outcome"], got["note"]))
    if got["outcome"] != PASS:
        return report(
            got["outcome"] if got["outcome"] == UNMEASURED else FAIL,
            f"the file was written but not confirmed: {got['note']}",
            crop=geom,
            audio_plan=plan,
            argv=argv,
            written=True,
        )
    mismatch = []
    if (got["width"], got["height"]) != (geom["w"], geom["h"]):
        mismatch.append(
            f"size {got['width']}x{got['height']} against the planned {geom['w']}x{geom['h']}"
        )
    if bool(got.get("audio")) != bool(plan["glue"]):
        mismatch.append(
            f"audio {'present' if got.get('audio') else 'absent'} against "
            f"the planned {'present' if plan['glue'] else 'absent'}"
        )
    if mismatch:
        return report(
            FAIL,
            "the file was written but it is the wrong one: " + "; ".join(mismatch),
            crop=geom,
            audio_plan=plan,
            argv=argv,
            written=True,
            audio=bool(got.get("audio")),
        )
    outcome = PASS if plan["outcome"] == PASS else FAIL
    tail = "audio returned" if plan["glue"] else "without audio: " + plan["note"]
    return report(
        outcome,
        (
            f"{out_path}: {got['width']}x{got['height']}, "
            f"{got['frames']} frames, {got['seconds']:g} s; "
            f"{geom['lost_percent']:g}% of the frame area lost; {tail}"
        ),
        crop=geom,
        audio_plan=plan,
        argv=argv,
        written=True,
        audio=bool(got.get("audio")),
    )


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Final assembly: crop to 9:16 plus the driving audio return"
    )
    ap.add_argument("--driving", required=True, help="the source driving with audio")
    ap.add_argument("--kling", required=True, help="the Kling output, square, without audio")
    ap.add_argument("--out", required=True, help="where to put the final clip")
    ap.add_argument(
        "--from-frame",
        type=int,
        required=True,
        help="first frame of the driving window, inclusive",
    )
    ap.add_argument(
        "--to-frame", type=int, required=True, help="last frame of the driving window, inclusive"
    )
    ap.add_argument(
        "--bias",
        type=float,
        default=0.0,
        help="crop window bias: -1 left, 0 centre, +1 right",
    )
    args = ap.parse_args(argv)
    rep = finish(
        args.driving, args.kling, args.out, window=(args.from_frame, args.to_frame), bias=args.bias
    )
    for name, outcome, note in rep["steps"]:
        print(f"  [{outcome}] {name}: {note}")
    print(f"[{rep['outcome']}] {rep['note']}")
    print(f"{len(rep['steps'])} steps, in {rep['elapsed']:g} s")
    return EXIT_BY_OUTCOME[rep["outcome"]]


if __name__ == "__main__":
    raise SystemExit(main())
