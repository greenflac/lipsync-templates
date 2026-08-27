"""Accept the e2e bench inputs: driving, client photo, style reference."""

from __future__ import annotations

import shutil
import subprocess
import time

from . import fork_looper, fork_video
from .fork_identity import FAIL, PASS, UNMEASURED


from .fork_identity import SAME_PERSON_MAX  # noqa: E402

from .fork_looper import CUT_JUMP  # noqa: E402

from .pose import MIN_VISIBILITY  # noqa: E402

from .identity_arcface import MIN_FACE_PX  # noqa: E402

MIN_SCENE_SECONDS = 3.0

#: CHOSEN 0.10 (at the intake handover 22.08, out of exactly two measured
#: points: 21% orphan wrists gave ArcFace 0.2960 at 81/99 inside the band, 0%
#: gave 0.2430 at 98/99 — about 0.05 of identity per 21%). Read linearly, 10% is
#: some 0.024, half the instrument's own noise (`fork_identity.
#: UPSCALE_DRIFT_MAX` = 0.05); below that a warning would be about noise. NOT
#: measured at 10% itself — nothing was measured between 0% and 21%, and the
#: linearity between two points is an assumption, not an observation.
ORPHAN_WRIST_WARN = 0.10

#: MEASURED at the 22.08 intake run: on `driving_selfie.mp4` ffprobe
#: -count_frames gave 305, ffmpeg without flags 307, ffmpeg with `-vsync 0`
#: exactly 305; on `driving_arms.mp4` and `driving_yogaball.mp4` all three
#: agreed (373 and 362). A healthy file disagrees by exactly zero, so there is
#: no tolerance to spend: one frame of slack would hide the very defect this
#: instrument exists to catch. Those clips are not shipped in this repository,
#: so the numbers stand as a record and cannot be re-run here.
FRAME_COUNT_EXACT = 0

#: CHOSEN 1 (by the product, out of how identity is measured): the identity axis
#: reads the LARGEST face, because `identity_arcface.face_detail` sorts by area.
#: With two people in the photo it is the instrument, not the operator, that
#: picks whose face the whole axis is about.
PHOTO_PEOPLE_EXPECTED = 1

VSYNC_ADVICE = (
    "unpack only with `-vsync 0` (in newer ffmpeg, "
    "`-fps_mode passthrough`; MEASURED: both give 305 on "
    "driving_selfie): without it ffmpeg fakes the missing "
    "frames with duplicates, snapping the stream to its own grid"
)

EXIT_BY_OUTCOME = fork_looper.EXIT_BY_OUTCOME


def read_count_frames(path) -> dict:
    """Ask ffprobe to count frames one by one. Injection point: the test replaces it wholesale."""
    if shutil.which(fork_video.FFPROBE_BIN) is None:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": (
                f"{fork_video.FFPROBE_BIN} not found: nothing to ask with. This is not 'a bad file'"
            ),
        }
    try:
        raw = subprocess.run(
            [
                fork_video.FFPROBE_BIN,
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=nb_read_frames,avg_frame_rate,duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=fork_video.DECODE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": f"{fork_video.FFPROBE_BIN} did not run to completion: {str(exc)[:120]}",
        }
    return {
        "ran": True,
        "code": raw.returncode,
        "out": raw.stdout or "",
        "err": raw.stderr or "",
        "why": "",
    }


def read_decoded_frames(path, *, vsync0: bool) -> dict:
    """Count how many frames the unpacker would emit. Injection point."""
    if shutil.which(fork_video.FFMPEG_BIN) is None:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": (
                f"{fork_video.FFMPEG_BIN} not found: nothing to count "
                f"the unpacked frames with. This is not 'a bad video'"
            ),
        }
    argv = [
        fork_video.FFMPEG_BIN,
        "-nostdin",
        "-v",
        "error",
        "-stats",
        "-i",
        str(path),
        "-an",
        "-vf",
        "scale=16:16",
    ]
    if vsync0:
        argv += ["-vsync", "0"]
    argv += ["-f", "image2", "-update", "1", "-y", "/dev/null"]
    try:
        raw = subprocess.run(
            argv, capture_output=True, text=True, timeout=fork_video.DECODE_TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": (
                f"{fork_video.FFMPEG_BIN} did not finish within "
                f"{fork_video.DECODE_TIMEOUT_S} s: how many frames "
                f"came out is unknown"
            ),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": f"{fork_video.FFMPEG_BIN} did not run to completion: {str(exc)[:120]}",
        }
    return {
        "ran": True,
        "code": raw.returncode,
        "out": raw.stdout or "",
        "err": raw.stderr or "",
        "why": "",
    }


def read_faces(path) -> dict:
    """Return every face in the frame, not only the largest one. Injection point."""
    try:
        from . import identity_arcface

        faces = identity_arcface._analyzer().get(identity_arcface._read_bgr(path))
        out = []
        for f in faces:
            x0, y0, x1, y1 = (float(v) for v in f.bbox)
            out.append(
                {"face_px": round(min(x1 - x0, y1 - y0)), "det_score": round(float(f.det_score), 3)}
            )
        out.sort(key=lambda d: d["face_px"], reverse=True)
        return {"faces": out, "why": ""}
    except Exception as exc:  # noqa: BLE001 — many ways for "nothing to ask with" to happen
        return {"faces": None, "why": f"{type(exc).__name__}: {str(exc)[:200]}"}


def read_style_card(path) -> dict:
    """Read the style card. Injection point, and also the only entrance."""
    try:
        from creative_eval.style import style_card  # noqa: PLC0415

        return {"card": style_card(str(path)), "why": ""}
    except Exception as exc:  # noqa: BLE001
        return {"card": None, "why": f"{type(exc).__name__}: {str(exc)[:200]}"}


def tally(checked: int, violations: int, unmeasured: int) -> dict:
    """Put three numbers beside the verdict, with the verdict derived from them."""
    out: dict = {
        "checked": int(checked),
        "violations": int(violations),
        "unmeasured": int(unmeasured),
    }
    if checked == 0:
        out["outcome"] = UNMEASURED
    elif violations > 0:
        out["outcome"] = FAIL
    elif unmeasured > 0:
        out["outcome"] = UNMEASURED
    else:
        out["outcome"] = PASS
    return out


def parse_count_frames(text: str) -> dict:
    """Turn a `ffprobe -count_frames` answer into a frame count. The test feeds a literal."""
    import json

    try:
        data = json.loads(text or "")
    except (ValueError, TypeError):
        return {
            "ok": False,
            "frames": None,
            "fps": None,
            "seconds": None,
            "why": (f"the ffprobe answer did not parse as JSON: {(text or '')[:120]!r}"),
        }
    streams = (data or {}).get("streams") or []
    if not streams:
        return {
            "ok": False,
            "frames": None,
            "fps": None,
            "seconds": None,
            "why": "no video stream in the answer: nothing to count",
        }
    s = streams[0]
    raw = s.get("nb_read_frames")
    try:
        frames = int(raw)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "frames": None,
            "fps": None,
            "seconds": None,
            "why": (
                f"nb_read_frames = {raw!r}: ffprobe did not count the frames. "
                f"This is not 'there are no frames'"
            ),
        }
    if frames <= 0:
        return {
            "ok": False,
            "frames": None,
            "fps": None,
            "seconds": None,
            "why": f"ffprobe counted {frames} frames: nothing to count",
        }
    fps = fork_video._ratio(s.get("avg_frame_rate"))
    try:
        seconds = float(s.get("duration"))
    except (TypeError, ValueError):
        seconds = None
    return {"ok": True, "frames": frames, "fps": fps, "seconds": seconds, "why": ""}


def parse_decoded_frames(text: str) -> dict:
    """Turn an ffmpeg `-stats` line into the number of frames it emitted. The test feeds a literal."""
    import re

    hits = re.findall(r"frame=\s*(\d+)", text or "")
    if not hits:
        return {
            "ok": False,
            "frames": None,
            "why": (
                f"not a single `frame=` in the ffmpeg answer: how many "
                f"frames came out is unknown. Tail: "
                f"{(text or '')[-120:]!r}"
            ),
        }
    return {"ok": True, "frames": int(hits[-1]), "why": ""}


def timestamp_verdict(probed: int | None, plain: int | None, fixed: int | None) -> dict:
    """Judge holes in the timestamps. Three outcomes, and advice instead of a guess."""
    known = [v for v in (probed, plain, fixed) if v is not None]
    if len(known) < 3:
        missing = [
            n
            for n, v in (("ffprobe", probed), ("ffmpeg", plain), ("ffmpeg -vsync 0", fixed))
            if v is None
        ]
        return {
            **tally(0, 0, 1),
            "probed": probed,
            "plain": plain,
            "fixed": fixed,
            "gap": None,
            "advice": VSYNC_ADVICE,
            "note": (
                f"counters not taken: {', '.join(missing)}. This is neither "
                f"'the frames are in place' nor 'the file is broken'"
            ),
        }
    assert probed is not None and plain is not None  # narrowed by the guard above
    gap = plain - probed
    if abs(gap) <= FRAME_COUNT_EXACT:
        return {
            **tally(1, 0, 0),
            "probed": probed,
            "plain": plain,
            "fixed": fixed,
            "gap": gap,
            "advice": "",
            "note": (
                f"ffprobe {probed}, ffmpeg {plain}, ffmpeg -vsync 0 "
                f"{fixed}: gap {gap}, no visible holes in the "
                f"timestamps"
            ),
        }
    healed = fixed == probed
    return {
        **tally(1, 1, 0),
        "probed": probed,
        "plain": plain,
        "fixed": fixed,
        "gap": gap,
        "advice": VSYNC_ADVICE,
        "note": (
            f"ffprobe {probed}, ffmpeg with no flags {plain} "
            f"(gap {gap:+d}), with -vsync 0 {fixed}. The file has "
            f"dropped frames, and a plain unpack fakes them with "
            f"duplicates"
            + (
                f"; {VSYNC_ADVICE}"
                if healed
                else f"; and `-vsync 0` does not heal it ({fixed} versus {probed}) — "
                f"do not take this material into work"
            )
        ),
    }


def scenes(n_frames: int, cut_list) -> list:
    """Split into scenes at the seams. Pure arithmetic, the test feeds literals."""
    if n_frames <= 0:
        return []
    marks = sorted({int(c) for c in (cut_list or []) if 0 <= int(c) < n_frames - 1})
    out, start = [], 0
    for k in marks:
        out.append({"start": start, "end": k, "frames": k - start + 1})
        start = k + 1
    out.append({"start": start, "end": n_frames - 1, "frames": n_frames - 1 - start + 1})
    return out


def scene_length_verdict(
    scene_list, fps: float | None, *, min_seconds: float | None = None
) -> dict:
    """Check that every scene clears the bar. An acceptance criterion, not a wish."""
    bar = MIN_SCENE_SECONDS if min_seconds is None else min_seconds
    if not scene_list:
        return {
            **tally(0, 0, 1),
            "bar_seconds": bar,
            "short": [],
            "seconds": [],
            "note": "no scenes: the markup was not taken, nothing to measure the length of",
        }
    if not fps or fps <= 0:
        return {
            **tally(0, 0, len(scene_list)),
            "bar_seconds": bar,
            "short": [],
            "seconds": [],
            "note": (
                f"the rate was not taken: {len(scene_list)} scenes exist, "
                f"but there is nothing to convert frames to seconds with. "
                f"This is neither 'the scenes are short' nor 'the scenes are long'"
            ),
        }
    secs = [round(s["frames"] / fps, 3) for s in scene_list]
    short = [i for i, v in enumerate(secs) if v < bar]
    return {
        **tally(len(scene_list), len(short), 0),
        "bar_seconds": bar,
        "short": short,
        "seconds": secs,
        "note": (
            f"scenes {len(scene_list)}, bar {bar} s, below the bar "
            f"{len(short)}"
            + (
                f": indices {short[:10]}, lengths {[secs[i] for i in short[:10]]}"
                if short
                else f"; shortest {min(secs)} s, longest {max(secs)} s"
            )
        ),
    }


def is_orphan_wrist(points) -> bool | None:
    """Tell whether one frame carries an orphan wrist. The definition lives here and only here."""
    if not points:
        return None

    def seen(name):
        p = points.get(name)
        if p is None or len(p) < 3:
            return False
        x, y, vis = float(p[0]), float(p[1]), float(p[2])
        return vis >= MIN_VISIBILITY and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0

    for side in ("l", "r"):
        if seen(f"{side}_wrist") and not (seen(f"{side}_elbow") and seen(f"{side}_shoulder")):
            return True
    return False


def orphan_verdict(share: float | None, checked: int, unmeasured: int) -> dict:
    """Report the soft axis: orphan share and a warning. It never sinks the verdict."""
    if share is None or checked == 0:
        return {
            **tally(0, 0, max(1, unmeasured)),
            "share": None,
            "warn": False,
            "bar": ORPHAN_WRIST_WARN,
            "note": (
                "the pose could not be taken on a single frame: the orphan "
                "share is not measured. This is not 'there are no orphans'"
            ),
        }
    warn = share >= ORPHAN_WRIST_WARN
    base = tally(checked, 0, unmeasured)
    return {
        **base,
        "share": round(share, 4),
        "warn": warn,
        "bar": ORPHAN_WRIST_WARN,
        "note": (
            f"orphan wrists {round(share * 100, 1)}% "
            f"({checked} frames with a pose, {unmeasured} without)"
            + (
                f". Warning: the share is not below "
                f"{round(ORPHAN_WRIST_WARN * 100)}%. This is a correction "
                f"to the identity expectation, not a refusal: MEASURED that 21% "
                f"of orphans gave ArcFace 0.2960 (81/99 within the bar "
                f"{SAME_PERSON_MAX}) versus 0.2430 (98/99) at 0%, that "
                f"is about 0.05 on identity. The template author looked at "
                f"the output with 21% and called the wrists correct"
                if warn
                else f"; below the warning bar {round(ORPHAN_WRIST_WARN * 100)}%"
            )
        ),
    }


def face_size_verdict(
    sizes: list, no_face: int, unmeasured: int, *, min_face_px: int | None = None
) -> dict:
    """Check the face has enough pixels for identity to be measurable at all."""
    bar = MIN_FACE_PX if min_face_px is None else min_face_px
    checked = len(sizes) + no_face
    if checked == 0:
        return {
            **tally(0, 0, max(1, unmeasured)),
            "bar_px": bar,
            "small": 0,
            "no_face": no_face,
            "min": None,
            "max": None,
            "note": (
                "the face was not asked for on a single frame: the size is "
                "not measured. This is not 'there is no face'"
            ),
        }
    small = [v for v in sizes if v < bar]
    hurt = len(small) + no_face
    warn = (
        (
            f"; warning: {hurt} of {checked} frames are unusable for "
            f"ArcFace — identity on the output is judged by the operator's "
            f"eyes, the instrument is not the judge here"
        )
        if hurt
        else ""
    )
    return {
        **tally(checked, 0, unmeasured),
        "bar_px": bar,
        "small": len(small),
        "no_face": no_face,
        "hurt": hurt,
        "min": min(sizes) if sizes else None,
        "max": max(sizes) if sizes else None,
        "note": (
            f"bar {bar}px: frames {checked}, face found on "
            f"{len(sizes)}, below the bar {len(small)}, without a face "
            f"{no_face}"
            + (f"; range {min(sizes)}..{max(sizes)} px" if sizes else "")
            + (f", not asked {unmeasured}" if unmeasured else "")
            + warn
        ),
    }


def window(scene_list, product_seconds: float, fps: float | None) -> dict:
    """Pick the window bounds in frame numbers. Cutting by time is forbidden."""
    if not scene_list:
        return {
            **tally(0, 0, 1),
            "start": None,
            "end": None,
            "frames": None,
            "scene": None,
            "note": "no scene markup: nothing to pick a window from",
        }
    if not fps or fps <= 0:
        return {
            **tally(0, 0, len(scene_list)),
            "start": None,
            "end": None,
            "frames": None,
            "scene": None,
            "note": (
                "the rate was not taken: nothing to convert the product "
                "length into frames with. We do not substitute a guess of 30"
            ),
        }
    need = int(round(product_seconds * fps))
    if need <= 0:
        return {
            **tally(0, 0, 1),
            "start": None,
            "end": None,
            "frames": None,
            "scene": None,
            "note": (
                f"product length {product_seconds} s at {fps} fps is {need} frames: nothing to cut"
            ),
        }
    best = max(range(len(scene_list)), key=lambda i: scene_list[i]["frames"])
    have = scene_list[best]["frames"]
    if have < need:
        return {
            **tally(len(scene_list), 1, 0),
            "start": None,
            "end": None,
            "frames": None,
            "scene": None,
            "note": (
                f"{need} frames needed ({product_seconds} s at {fps} "
                f"fps), the longest scene has {have} frames "
                f"({round(have / fps, 3)} s): the window does not fit"
            ),
        }
    pad = (have - need) // 2
    start = scene_list[best]["start"] + pad
    end = start + need - 1
    return {
        **tally(len(scene_list), 0, 0),
        "start": start,
        "end": end,
        "frames": need,
        "scene": best,
        "note": (
            f"window {start}..{end} ({need} frames, "
            f"{round(need / fps, 3)} s) from scene {best} "
            f"({scene_list[best]['start']}..{scene_list[best]['end']}, "
            f"{have} frames), margins of {pad} frames on each side"
        ),
    }


def driving_intake(
    video_path,
    frame_paths=None,
    *,
    product_seconds=None,
    prober=None,
    decoder=None,
    gray=None,
    pose_reader=None,
    face_prober=None,
) -> dict:
    """Run the driving intake: six axes, four hard and two soft."""
    t0 = time.perf_counter()
    prober = read_count_frames if prober is None else prober
    decoder = read_decoded_frames if decoder is None else decoder
    gray = fork_looper.read_gray if gray is None else gray
    pose_reader = fork_looper.read_pose if pose_reader is None else pose_reader
    if face_prober is None:

        def face_prober(p):
            from . import identity_arcface

            return identity_arcface.face_detail(p)

    axes, steps = {}, {}

    t = time.perf_counter()
    raw = prober(video_path)
    probed = (
        parse_count_frames(raw.get("out", ""))
        if raw.get("ran")
        else {"ok": False, "frames": None, "fps": None, "seconds": None, "why": raw.get("why", "")}
    )
    plain = decoder(video_path, vsync0=False)
    fixed = decoder(video_path, vsync0=True)
    p_n = (
        parse_decoded_frames(plain.get("err", ""))
        if plain.get("ran")
        else {"ok": False, "frames": None, "why": plain.get("why", "")}
    )
    f_n = (
        parse_decoded_frames(fixed.get("err", ""))
        if fixed.get("ran")
        else {"ok": False, "frames": None, "why": fixed.get("why", "")}
    )
    axes["timestamps"] = timestamp_verdict(
        probed.get("frames"), p_n.get("frames"), f_n.get("frames")
    )
    axes["timestamps"]["why"] = "; ".join(
        w for w in (probed.get("why"), p_n.get("why"), f_n.get("why")) if w
    )
    steps["timestamps"] = round(time.perf_counter() - t, 3)
    fps = probed.get("fps")
    seconds = probed.get("seconds")

    paths = list(frame_paths or [])
    n = len(paths)

    t = time.perf_counter()
    if not paths:
        axes["cuts"] = {
            **tally(0, 0, 1),
            "cuts": [],
            "bar": CUT_JUMP,
            "note": (
                "no frames given: nothing to look for seams in. This is not 'there are no seams'"
            ),
        }
        marks: list = []
    else:
        c = fork_looper.cuts(paths, gray=gray)
        marks = c.get("cuts") or []
        axes["cuts"] = {
            **(tally(len(paths) - 1, 0, 0) if c.get("outcome") != UNMEASURED else tally(0, 0, 1)),
            "cuts": marks,
            "bar": CUT_JUMP,
            "note": c.get("note", ""),
        }
    steps["cuts"] = round(time.perf_counter() - t, 3)

    scene_list = scenes(n, marks) if n else []
    axes["scenes"] = scene_length_verdict(scene_list, fps)

    t = time.perf_counter()
    orphans = seen_poses = pose_blind = 0
    sizes, no_face, face_blind = [], 0, 0
    for p in paths:
        r = pose_reader(str(p))
        if r.get("why"):
            pose_blind += 1
        else:
            verdict = is_orphan_wrist(r.get("points"))
            if verdict is None:
                pose_blind += 1
            else:
                seen_poses += 1
                orphans += 1 if verdict else 0
        try:
            d = face_prober(str(p))
        except Exception:  # noqa: BLE001 — "nothing to ask with" on this frame
            face_blind += 1
        else:
            if d is None:
                no_face += 1
            else:
                sizes.append(int(d["face_px"]))
    axes["orphan_wrists"] = orphan_verdict(
        (orphans / seen_poses) if seen_poses else None, seen_poses, pose_blind
    )
    axes["face_size"] = face_size_verdict(sizes, no_face, face_blind)
    steps["pose_and_face"] = round(time.perf_counter() - t, 3)

    axes["window"] = (
        window(scene_list, product_seconds, fps)
        if product_seconds is not None
        else {
            **tally(0, 0, 1),
            "start": None,
            "end": None,
            "frames": None,
            "scene": None,
            "note": "product length not given: the window was not chosen",
        }
    )

    return _report(
        "driving",
        video_path,
        axes,
        steps,
        t0,
        soft=("orphan_wrists", "window"),
        extra={"fps": fps, "seconds": seconds, "frames": n, "scenes": scene_list},
    )


def photo_intake(photo_path, *, faces_prober=None) -> dict:
    """Run the client photo intake: face found, size in px, one person."""
    t0 = time.perf_counter()
    faces_prober = read_faces if faces_prober is None else faces_prober
    r = faces_prober(str(photo_path))
    axes = {}
    if r.get("why") or r.get("faces") is None:
        blind = {
            **tally(0, 0, 1),
            "note": (
                f"nothing to ask with: {r.get('why') or 'the detector is silent'}. "
                f"This is not 'there is no face'"
            ),
        }
        axes = {"face_found": dict(blind), "face_size": dict(blind), "one_person": dict(blind)}
        return _report("client photo", photo_path, axes, {}, t0, soft=())

    faces = r["faces"]
    axes["face_found"] = {
        **tally(1, 0 if faces else 1, 0),
        "faces": len(faces),
        "note": (
            f"faces found {len(faces)}"
            if faces
            else "no face found: nothing to take the identity anchor from"
        ),
    }
    if faces:
        biggest = faces[0]["face_px"]
        axes["face_size"] = {
            **tally(1, 0 if biggest >= MIN_FACE_PX else 1, 0),
            "face_px": biggest,
            "bar_px": MIN_FACE_PX,
            "note": (f"largest face {biggest} px against the bar {MIN_FACE_PX} px"),
        }
    else:
        axes["face_size"] = {
            **tally(0, 0, 1),
            "face_px": None,
            "bar_px": MIN_FACE_PX,
            "note": "no face: nothing to measure the size of",
        }
    axes["one_person"] = {
        **tally(1, 0 if len(faces) == PHOTO_PEOPLE_EXPECTED else 1, 0),
        "faces": len(faces),
        "expected": PHOTO_PEOPLE_EXPECTED,
        "note": (
            f"people in the frame {len(faces)}, expected {PHOTO_PEOPLE_EXPECTED}"
            + (
                ""
                if len(faces) == PHOTO_PEOPLE_EXPECTED
                else ". Identity is measured on the largest face, so the "
                "instrument picks it, not a person"
            )
        ),
    }
    return _report("client photo", photo_path, axes, {}, t0, soft=())


def style_intake(ref_path, *, card_reader=None) -> dict:
    """Run the style reference intake: whether the style card is readable."""
    t0 = time.perf_counter()
    card_reader = read_style_card if card_reader is None else card_reader
    r = card_reader(str(ref_path))
    card = r.get("card")
    if r.get("why") or card is None:
        axes = {
            "card_readable": {
                **tally(0, 0, 1),
                "card": None,
                "note": (
                    f"nothing to read the card with: {r.get('why') or 'no answer'}. "
                    f"This is not 'the style is bad'"
                ),
            }
        }
        return _report("style reference", ref_path, axes, {}, t0, soft=())

    need = ("colours", "value_key", "saturation", "texture")
    if not isinstance(card, dict):
        missing = list(need)
    else:
        missing = [k for k in need if not card.get(k)]
    axes = {
        "card_readable": {
            **tally(len(need), len(missing), 0),
            "card": card,
            "missing": missing,
            "note": (
                f"card fields {len(need) - len(missing)} of {len(need)}"
                + (
                    f", empty: {missing}"
                    if missing
                    else f"; palette {list(card.get('colours') or [])}, "
                    f"value key {card.get('value_key')!r}, saturation "
                    f"{card.get('saturation')!r}, texture {card.get('texture')!r}"
                )
            ),
        }
    }
    return _report("style reference", ref_path, axes, {}, t0, soft=())


def _report(
    kind, source, axes: dict, steps: dict, t0: float, *, soft=(), extra: dict | None = None
) -> dict:
    """Fold the axes into one verdict. Soft axes are not part of it."""
    hard = {k: v for k, v in axes.items() if k not in soft}
    checked = sum(v.get("checked", 0) for v in hard.values())
    violations = sum(v.get("violations", 0) for v in hard.values())
    unmeasured = sum(v.get("unmeasured", 0) for v in hard.values())
    total = tally(checked, violations, unmeasured)
    outcomes = [v.get("outcome") for v in hard.values()]
    if FAIL in outcomes:
        total["outcome"] = FAIL
    elif UNMEASURED in outcomes:
        total["outcome"] = UNMEASURED
    warns = [k for k, v in axes.items() if v.get("warn")]
    return {
        "kind": kind,
        "source": str(source),
        "axes": axes,
        "outcome": total["outcome"],
        "checked": total["checked"],
        "violations": total["violations"],
        "unmeasured": total["unmeasured"],
        "soft": list(soft),
        "warnings": warns,
        "steps": steps,
        "elapsed": round(time.perf_counter() - t0, 3),
        **(extra or {}),
    }
