"""Decode video: mp4 -> PNG frames."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import time
from pathlib import Path

from . import framemath
from .fork_identity import FAIL, PASS, UNMEASURED

FFPROBE_BIN = "ffprobe"
FFMPEG_BIN = "ffmpeg"

PROBE_TIMEOUT_S = 20

DECODE_TIMEOUT_S = 600

NAME_DIGITS = 5

FRAME_SUFFIX = ".png"

FRAME_COUNT_TOLERANCE = 1

FPS_TOLERANCE = 0.01

AS_IS, DROP, REFUSE = "as is", "drop", "refuse"

EXIT_BY_OUTCOME = {PASS: 0, FAIL: 1, UNMEASURED: 2}


def read_probe(path) -> dict:
    """Ask ffprobe for metadata. Injection point: the test replaces it wholesale."""
    if shutil.which(FFPROBE_BIN) is None:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": (
                f"{FFPROBE_BIN} not found: nothing to ask with. This is not "
                f"'a bad file' — the tool ships in the ffmpeg package"
            ),
        }
    try:
        raw = subprocess.run(
            [
                FFPROBE_BIN,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": f"{FFPROBE_BIN} did not run to completion: {str(exc)[:120]}",
        }
    return {
        "ran": True,
        "code": raw.returncode,
        "out": raw.stdout or "",
        "err": raw.stderr or "",
        "why": "",
    }


def run_decode(argv) -> dict:
    """Decode. Injection point: the test replaces it wholesale."""
    if shutil.which(FFMPEG_BIN) is None:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": (f"{FFMPEG_BIN} not found: nothing to decode with. This is not 'a bad video'"),
        }
    try:
        raw = subprocess.run(argv, capture_output=True, text=True, timeout=DECODE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": (
                f"{FFMPEG_BIN} did not finish within {DECODE_TIMEOUT_S} s and "
                f"was killed: how much was decoded is unknown"
            ),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": f"{FFMPEG_BIN} did not run to completion: {str(exc)[:120]}",
        }
    return {
        "ran": True,
        "code": raw.returncode,
        "out": raw.stdout or "",
        "err": raw.stderr or "",
        "why": "",
    }


def frame_name(index: int) -> str:
    """Name a frame. The field width is a constant, not a literal in two places."""
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ValueError(f"frame number {index!r}: expected an integer from zero")
    return f"{index:0{NAME_DIGITS}d}{FRAME_SUFFIX}"


def _ratio(raw) -> float | None:
    """Turn `30000/1001` into 29.97003. Broken or zero gives `None`, not a guess."""
    if raw is None:
        return None
    try:
        num, _, den = str(raw).partition("/")
        value = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def parse_probe(text: str) -> dict:
    """Parse ffprobe JSON into our fields. Pure function, the test feeds a literal."""
    try:
        data = json.loads(text or "")
    except (ValueError, TypeError):
        return {
            "ok": False,
            "why": f"the ffprobe answer did not parse as JSON: {(text or '')[:120]!r}",
        }
    if not isinstance(data, dict):
        return {"ok": False, "why": f"expected an object, got {type(data).__name__}"}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = any(s.get("codec_type") == "audio" for s in streams)
    if video is None:
        return {
            "ok": False,
            "audio": audio,
            "why": (
                f"no video stream in the file ({len(streams)} streams "
                f"total, audio {'present' if audio else 'absent'})"
            ),
        }
    fps = _ratio(video.get("avg_frame_rate")) or _ratio(video.get("r_frame_rate"))
    try:
        seconds = float(video.get("duration") or (data.get("format") or {}).get("duration") or "")
    except (TypeError, ValueError):
        seconds = None
    nb = video.get("nb_frames")
    frames = frames_from = None
    try:
        if nb is not None and int(nb) > 0:
            frames, frames_from = int(nb), "nb_frames"
    except (TypeError, ValueError):
        frames = None
    if frames is None and fps and seconds:
        frames, frames_from = int(round(seconds * fps)), "duration x rate"
    return {
        "ok": True,
        "why": "",
        "fps": fps,
        "frames": frames,
        "frames_from": frames_from,
        "seconds": seconds,
        "width": video.get("width"),
        "height": video.get("height"),
        "audio": audio,
        "codec": video.get("codec_name"),
    }


def fps_plan(source_fps, *, want=None) -> dict:
    """Decide what to do with the rate. Three branches, and silent conforming is not among them."""
    if source_fps is None:
        return {
            "outcome": UNMEASURED,
            "mode": REFUSE,
            "fps": None,
            "note": (
                "the source rate was not taken — there is nothing to decide "
                "the conversion from. This is not 'take it as is': as is "
                "is also a decision, and it requires knowing what is"
            ),
        }
    if want is None:
        return {
            "outcome": PASS,
            "mode": AS_IS,
            "fps": source_fps,
            "note": (
                f"source rate {source_fps:g} fps, every frame is taken, "
                f"no conforming. The frame count equals the frame count "
                f"in the file"
            ),
        }
    if (
        not isinstance(want, (int, float))
        or isinstance(want, bool)
        or not math.isfinite(want)
        or want <= 0
    ):
        return {
            "outcome": FAIL,
            "mode": REFUSE,
            "fps": None,
            "note": f"rate {want!r}: expected a positive finite number",
        }
    if abs(want - source_fps) <= FPS_TOLERANCE:
        return {
            "outcome": PASS,
            "mode": AS_IS,
            "fps": source_fps,
            "note": (
                f"requested {want:g} fps against source {source_fps:g} — "
                f"the same thing within the tolerance "
                f"{FPS_TOLERANCE}, touching nothing"
            ),
        }
    if want > source_fps:
        return {
            "outcome": FAIL,
            "mode": REFUSE,
            "fps": None,
            "note": (
                f"requested {want:g} fps against source {source_fps:g}: "
                f"we do not conform upward. There is no interpolation by "
                f"the template author's decision ({want:g} - {source_fps:g} = "
                f"{want - source_fps:g} fps would have to be invented), and "
                f"an invented frame in a driving is an invented "
                f"movement. Shooting the driving at no less than "
                f"{framemath.WRAP_FPS} fps is a filming requirement"
            ),
        }
    return {
        "outcome": PASS,
        "mode": DROP,
        "fps": float(want),
        "note": (
            f"dropping {source_fps:g} -> {want:g} fps. The length in "
            f"frames changes: a second yields {want:g} frames "
            f"instead of {source_fps:g}, and the sampler window count is "
            f"computed from the new number"
        ),
    }


def expected_frames(source_frames, *, source_fps=None, out_fps=None, limit=None) -> int | None:
    """Compute how many frames must land on disk. `None` when there is nothing to compute from."""
    if source_frames is None:
        return None
    n = int(source_frames)
    if out_fps is not None and source_fps and abs(out_fps - source_fps) > FPS_TOLERANCE:
        n = int(round(n * out_fps / source_fps))
    if limit is not None:
        n = min(n, int(limit))
    return max(n, 0)


def count_outcome(expected, written: int) -> dict:
    """Judge the frame counts. Pure function — the test feeds it literals."""
    if written < 0:
        raise ValueError(f"written {written}: negative frame counts do not exist")
    if written == 0:
        return {
            "outcome": FAIL,
            "note": (
                "0 frames written — this is not success but an absence of "
                "result: nothing to judge and nothing to animate"
            ),
        }
    if expected is None:
        return {
            "outcome": UNMEASURED,
            "note": (
                f"{written} frames written, but the metadata did not say how "
                f"many are in the file — nothing to confirm completeness with"
            ),
        }
    diff = abs(written - int(expected))
    if diff <= FRAME_COUNT_TOLERANCE:
        return {
            "outcome": PASS,
            "note": (
                f"expected {expected}, written {written} "
                f"(gap {diff}, tolerance {FRAME_COUNT_TOLERANCE} "
                f"— that is rounding, not loss)"
            ),
        }
    return {
        "outcome": UNMEASURED,
        "note": (
            f"expected {expected}, written {written}: the gap "
            f"{diff} exceeds the tolerance {FRAME_COUNT_TOLERANCE}. "
            f"Something was decoded, but the metadata does not confirm "
            f"what exactly. This is not 'pass'"
        ),
    }


def decode_argv(video_path, out_dir, *, out_fps=None, limit=None) -> list:
    """Build the decode command apart from running it — its makeup is a decision."""
    argv = [FFMPEG_BIN, "-nostdin", "-v", "error", "-i", str(video_path)]
    if out_fps is not None:
        argv += ["-vf", f"fps={out_fps:g}"]
    argv += ["-fps_mode", "passthrough", "-start_number", "0"]
    if limit is not None:
        argv += ["-frames:v", str(int(limit))]
    argv.append(str(Path(out_dir) / f"%0{NAME_DIGITS}d{FRAME_SUFFIX}"))
    return argv


def probe(video_path, *, prober=None) -> dict:
    """Take the video metadata. Three outcomes, numbers beside the verdict."""
    prober = read_probe if prober is None else prober
    t = time.perf_counter()
    p = Path(video_path)
    if not p.exists():
        return _probe_report(FAIL, f"file does not exist: {p}", t)
    if p.is_dir():
        return _probe_report(
            FAIL,
            f"{p} is a directory, not a video file. Frames in a directory "
            f"need no decoding: feed them as they are",
            t,
        )
    size = p.stat().st_size
    if size == 0:
        return _probe_report(FAIL, f"{p}: the file is empty, 0 bytes", t)

    raw = prober(p)
    if not raw.get("ran"):
        return _probe_report(UNMEASURED, raw.get("why") or "nothing to ask with", t)
    if raw.get("code"):
        return _probe_report(
            FAIL,
            f"{FFPROBE_BIN} returned {raw['code']}: "
            f"{(raw.get('err') or '').strip()[:200] or 'no explanation'}",
            t,
        )
    parsed = parse_probe(raw.get("out") or "")
    if not parsed.get("ok"):
        return _probe_report(
            FAIL,
            parsed.get("why", "the answer was not parsed"),
            t,
            **({"audio": parsed["audio"]} if "audio" in parsed else {}),
        )
    rep = _probe_report(
        PASS,
        (
            f"{parsed['width']}x{parsed['height']}, {parsed['fps']:g} fps, "
            f"frames {parsed['frames']} (from '{parsed['frames_from']}'), "
            f"{parsed['seconds']:g} s, audio "
            f"{'present' if parsed['audio'] else 'absent'}, codec {parsed['codec']}"
        )
        if parsed.get("fps") and parsed.get("seconds") is not None
        else (
            f"the metadata parsed only partially: rate {parsed.get('fps')}, "
            f"frames {parsed.get('frames')}, duration {parsed.get('seconds')}"
        ),
        t,
        **{
            k: parsed[k]
            for k in (
                "fps",
                "frames",
                "frames_from",
                "seconds",
                "width",
                "height",
                "audio",
                "codec",
            )
        },
    )
    if rep["fps"] is None or rep["frames"] is None:
        rep["outcome"] = UNMEASURED
    rep["bytes"] = size
    return rep


def _probe_report(outcome: str, note: str, t0: float, **extra) -> dict:
    rep = {
        "outcome": outcome,
        "note": note,
        "fps": None,
        "frames": None,
        "frames_from": None,
        "seconds": None,
        "width": None,
        "height": None,
        "audio": None,
        "codec": None,
        "bytes": None,
        "elapsed": round(time.perf_counter() - t0, 4),
    }
    rep.update(extra)
    return rep


def fps_prober(path):
    """Return the source rate as one number. Drop-in replacement for `_ffprobe_fps`."""
    rep = probe(path)
    return rep["fps"] if rep["outcome"] == PASS else None


def plan_for_seconds(seconds, *, fps=None) -> dict:
    """Compute how many driving frames a clip of this length needs."""
    return framemath.frames_for_seconds(seconds, fps=fps)


def frames(
    video_path, out_dir, *, fps=None, limit=None, overwrite=False, prober=None, decoder=None
) -> dict:
    """Decode the video into PNG. Three outcomes, numbers beside the verdict."""
    prober = read_probe if prober is None else prober
    decoder = run_decode if decoder is None else decoder
    t = time.perf_counter()
    steps: list = []

    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            return _frames_report(FAIL, f"limit={limit!r}: expected an integer from 1", t, steps)

    meta = probe(video_path, prober=prober)
    steps.append(("metadata", meta["outcome"], meta["note"], meta["elapsed"]))
    if meta["outcome"] != PASS:
        return _frames_report(meta["outcome"], meta["note"], t, steps, meta=meta)

    plan = fps_plan(meta["fps"], want=fps)
    steps.append(("rate", plan["outcome"], plan["note"], 0.0))
    if plan["outcome"] != PASS:
        return _frames_report(plan["outcome"], plan["note"], t, steps, meta=meta, plan=plan)

    want = plan["fps"] if plan["mode"] == DROP else None
    expected = expected_frames(meta["frames"], source_fps=meta["fps"], out_fps=want, limit=limit)

    out = Path(out_dir)
    if out.exists() and not out.is_dir():
        return _frames_report(
            FAIL, f"{out} is not a directory", t, steps, meta=meta, plan=plan, expected=expected
        )
    already = sorted(out.glob(f"*{FRAME_SUFFIX}")) if out.is_dir() else []
    present = len(already)
    present_bytes = sum(f.stat().st_size for f in already)
    if already and not overwrite:
        note = (
            f"{out} already holds frames: {present} (first "
            f"{already[0].name}, last {already[-1].name}, bytes "
            f"{present_bytes}). We do not write over them silently: decoding "
            f"60 frames over 320 would have produced a directory of 260 "
            f"foreign frames and 60 of ours — sorted and plausible. We wrote "
            f"not a single frame: these {present} are foreign. Pass "
            f"overwrite=True or another directory"
        )
        steps.append(("directory", UNMEASURED, note, 0.0))
        return _frames_report(
            UNMEASURED,
            note,
            t,
            steps,
            meta=meta,
            plan=plan,
            expected=expected,
            present=present,
            present_bytes=present_bytes,
        )
    if already and overwrite:
        for f in already:
            f.unlink()
    out.mkdir(parents=True, exist_ok=True)

    argv = decode_argv(video_path, out, out_fps=want, limit=limit)
    t_dec = time.perf_counter()
    got = decoder(argv)
    dec_elapsed = round(time.perf_counter() - t_dec, 4)
    written_paths = sorted(out.glob(f"*{FRAME_SUFFIX}"))
    written = len(written_paths)
    size = sum(p.stat().st_size for p in written_paths)

    if not got.get("ran"):
        note = (
            f"{got.get('why') or 'nothing to decode with'}. Frames that made "
            f"it to disk: {written}, expected {expected}"
        )
        steps.append(("decode", UNMEASURED, note, dec_elapsed))
        return _frames_report(
            UNMEASURED,
            note,
            t,
            steps,
            meta=meta,
            plan=plan,
            expected=expected,
            written=written,
            nbytes=size,
            paths=written_paths,
            present=present,
            present_bytes=present_bytes,
        )
    if got.get("code"):
        note = (
            f"{FFMPEG_BIN} returned {got['code']}: "
            f"{(got.get('err') or '').strip()[:200] or 'no explanation'}. "
            f"Frames written {written}, expected {expected}"
        )
        steps.append(("decode", FAIL, note, dec_elapsed))
        return _frames_report(
            FAIL,
            note,
            t,
            steps,
            meta=meta,
            plan=plan,
            expected=expected,
            written=written,
            nbytes=size,
            paths=written_paths,
            present=present,
            present_bytes=present_bytes,
        )
    steps.append(("decode", PASS, f"{FFMPEG_BIN} ran to completion, code 0", dec_elapsed))

    verdict = count_outcome(expected, written)
    steps.append(("frames", verdict["outcome"], verdict["note"], 0.0))
    return _frames_report(
        verdict["outcome"],
        verdict["note"],
        t,
        steps,
        meta=meta,
        plan=plan,
        expected=expected,
        written=written,
        nbytes=size,
        paths=written_paths,
        present=present,
        present_bytes=present_bytes,
    )


DIR_UNSEEN = "the destination directory was not examined"
DIR_EMPTY = "the destination directory was empty"


def _dir_fact(present, present_bytes) -> str:
    """Phrase the destination directory fact. Derived from what actually happened."""
    if present is None:
        return DIR_UNSEEN
    if present == 0:
        return DIR_EMPTY
    return (
        f"the directory already held {present} frames, "
        f"{0 if present_bytes is None else present_bytes} bytes"
    )


def _frames_report(
    outcome: str,
    note: str,
    t0: float,
    steps,
    *,
    meta=None,
    plan=None,
    expected=None,
    written=0,
    nbytes=0,
    paths=None,
    present=None,
    present_bytes=None,
) -> dict:
    """Build one report for every outcome."""
    elapsed = round(time.perf_counter() - t0, 4)
    paths = list(paths or [])
    return {
        "outcome": outcome,
        "expected": expected,
        "written": written,
        "bytes": nbytes,
        "present": present,
        "present_bytes": present_bytes,
        "elapsed": elapsed,
        "fps_in": (meta or {}).get("fps"),
        "fps_out": (plan or {}).get("fps"),
        "mode": (plan or {}).get("mode"),
        "paths": paths,
        "steps": [
            {"step": s, "outcome": o, "note": n, "seconds": round(e, 4)} for s, o, n, e in steps
        ],
        "note": (
            f"{outcome}: {note}. Expected frames "
            f"{'unknown' if expected is None else expected}, written by us "
            f"{written}, bytes {nbytes}, "
            f"{_dir_fact(present, present_bytes)}, in {elapsed} s"
        ),
    }


def main(argv=None) -> int:
    """`python3 -m lipsync.fork_video probe|frames ...`."""
    import argparse

    ap = argparse.ArgumentParser(prog="fork_video", description="video decoder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("probe", help="video metadata")
    p1.add_argument("video")
    p2 = sub.add_parser("frames", help="decode into PNG")
    p2.add_argument("video")
    p2.add_argument("out_dir")
    p2.add_argument(
        "--fps",
        type=float,
        default=None,
        help="conform the rate downward; without it the source rate is taken as is",
    )
    p2.add_argument("--limit", type=int, default=None)
    p2.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "probe":
        rep = probe(args.video)
        print(f"{rep['outcome']:20s} {rep['note']}")
    else:
        rep = frames(
            args.video, args.out_dir, fps=args.fps, limit=args.limit, overwrite=args.overwrite
        )
        for s in rep["steps"]:
            print(f"{s['outcome']:20s} {s['step']:15s} {s['seconds']:7.3f} s  {s['note']}")
        print(rep["note"])
    return EXIT_BY_OUTCOME[rep["outcome"]]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
