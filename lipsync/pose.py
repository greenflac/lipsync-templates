"""Body pose as a measurement: did the pose survive, and is the body anatomical."""

from __future__ import annotations

from . import cure

from pathlib import Path

BODY_POINTS = {
    "l_shoulder": 11,
    "r_shoulder": 12,
    "l_elbow": 13,
    "r_elbow": 14,
    "l_wrist": 15,
    "r_wrist": 16,
    "l_hip": 23,
    "r_hip": 24,
    "l_knee": 25,
    "r_knee": 26,
    "l_ankle": 27,
    "r_ankle": 28,
}

LIMBS = (
    ("l_shoulder", "l_elbow"),
    ("l_elbow", "l_wrist"),
    ("r_shoulder", "r_elbow"),
    ("r_elbow", "r_wrist"),
    ("l_hip", "l_knee"),
    ("l_knee", "l_ankle"),
    ("r_hip", "r_knee"),
    ("r_knee", "r_ankle"),
)

MIN_VISIBILITY = 0.5


SAME_POSE_MAX = 0.15

POSE_WANDER_MAX = 0.45

WORST_JOINT_MAX = 0.40

LIMB_WOBBLE_MAX = 0.25

MODEL_ENV = "LIPSYNC_POSE_MODEL"
DEFAULT_MODEL = "~/.mediapipe/pose_landmarker_lite.task"

MODEL_ONLINE = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_lite/float16/1/"
    "pose_landmarker_lite.task"
)

SEP = "\\" if cure.WINDOWS else "/"

_POSE = None


def _model_path() -> Path:
    import os

    p = Path(os.environ.get(MODEL_ENV, DEFAULT_MODEL)).expanduser()
    if not p.exists():
        raise RuntimeError(
            f"pose model not found at {p}. Download it once:\n"
            f"  {cure.mkdir(cure.home('.mediapipe'))}\n"
            f"  {cure.download(MODEL_ONLINE, cure.home('.mediapipe') + SEP + p.name)}\n"
            f"or point {MODEL_ENV} at it. Not bundled: it is 5.5 MB of weights, "
            f"and a missing model must fail loudly rather than skip the check."
        )
    return p


def _pose_model():
    """Lazy singleton landmarker in IMAGE mode."""
    global _POSE
    if _POSE is None:
        from mediapipe.tasks.python import BaseOptions  # type: ignore
        from mediapipe.tasks.python import vision  # type: ignore

        _POSE = vision.PoseLandmarker.create_from_options(
            vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(_model_path())),
                running_mode=vision.RunningMode.IMAGE,
                min_pose_detection_confidence=0.5,
            )
        )
    return _POSE


def landmarks(path: str | Path) -> dict | None:
    """Body landmarks for one image, or None if no body is found."""
    import mediapipe as mp  # type: ignore
    import numpy as np
    from PIL import Image

    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
    result = _pose_model().detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    if not result.pose_landmarks:
        return None
    lm = result.pose_landmarks[0]
    return {
        name: (float(lm[i].x), float(lm[i].y), float(lm[i].visibility))
        for name, i in BODY_POINTS.items()
    }


def world_landmarks(path: str | Path) -> dict | None:
    """Body landmarks in METRIC 3D space, rooted at the hips — view-independent."""
    import mediapipe as mp  # type: ignore
    import numpy as np
    from PIL import Image

    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
    result = _pose_model().detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    if not result.pose_landmarks or not result.pose_world_landmarks:
        return None
    lm = result.pose_world_landmarks[0]
    vis = result.pose_landmarks[0]
    return {
        name: (float(lm[i].x), float(lm[i].y), float(lm[i].z), float(vis[i].visibility))
        for name, i in BODY_POINTS.items()
    }


def world_proportions(path: str | Path) -> dict | None:
    """Build as view-independent ratios, in torso lengths."""
    import numpy as np

    pts = world_landmarks(path)
    if pts is None:
        return None

    def v(name):
        return np.array(pts[name][:3])

    def seen(*names):
        return all(pts[n][3] >= MIN_VISIBILITY for n in names)

    if not seen("l_hip", "r_hip", "l_shoulder", "r_shoulder"):
        return None
    hip_c = (v("l_hip") + v("r_hip")) / 2
    sho_c = (v("l_shoulder") + v("r_shoulder")) / 2
    torso = float(np.linalg.norm(sho_c - hip_c))
    if torso < 1e-6:
        return None

    out: dict = {"torso_metres": round(torso, 4)}
    for a, b in LIMBS:
        if seen(a, b):
            out[f"{a}->{b}"] = round(float(np.linalg.norm(v(a) - v(b))) / torso, 4)
    if seen("l_shoulder", "r_shoulder"):
        out["shoulder_width"] = round(
            float(np.linalg.norm(v("l_shoulder") - v("r_shoulder"))) / torso, 4
        )
    if seen("l_hip", "r_hip"):
        out["hip_width"] = round(float(np.linalg.norm(v("l_hip") - v("r_hip"))) / torso, 4)
    if out.get("shoulder_width") and out.get("hip_width"):
        out["shoulder_to_hip"] = round(out["shoulder_width"] / out["hip_width"], 4)
    legs = [out.get("l_hip->l_knee"), out.get("l_knee->l_ankle")]
    if all(legs):
        out["leg_length"] = round(sum(legs), 4)
    return out


def _normalise(points: dict) -> dict | None:
    """Centre on the hips and scale by torso length."""
    import numpy as np

    need = ("l_hip", "r_hip", "l_shoulder", "r_shoulder")
    if any(points.get(n) is None or points[n][2] < MIN_VISIBILITY for n in need):
        return None
    hip = np.array(
        [
            (points["l_hip"][0] + points["r_hip"][0]) / 2,
            (points["l_hip"][1] + points["r_hip"][1]) / 2,
        ]
    )
    sho = np.array(
        [
            (points["l_shoulder"][0] + points["r_shoulder"][0]) / 2,
            (points["l_shoulder"][1] + points["r_shoulder"][1]) / 2,
        ]
    )
    torso = float(np.linalg.norm(sho - hip))
    if torso < 1e-6:
        return None
    return {n: ((np.array([x, y]) - hip) / torso, v) for n, (x, y, v) in points.items()}


def pose_delta(a: dict, b: dict) -> dict | None:
    """Per-joint displacement between two poses, in torso lengths."""
    import numpy as np

    if a is None or b is None:
        which = " и ".join(n for n, v in (("первой", a), ("второй", b)) if v is None)
        raise ValueError(
            f"pose_delta: в {which} позе тела не нашли (landmarks вернул None). "
            f"Сравнивать нечего. Частая причина — сравнение с УСЛОВИЕМ "
            f"ControlNet: это рисунок скелета на чёрном фоне, детектор поз на "
            f"нём ничего не находит. Сверять надо с driving-кадром "
            f"(см. manifest.json рядом с условиями)."
        )
    na, nb = _normalise(a), _normalise(b)
    if na is None or nb is None:
        return None
    shared = [n for n in na if na[n][1] >= MIN_VISIBILITY and nb[n][1] >= MIN_VISIBILITY]
    if len(shared) < 4:
        return None
    per = {n: float(np.linalg.norm(na[n][0] - nb[n][0])) for n in shared}
    worst = max(per, key=lambda n: per[n])
    return {
        "mean": round(float(np.mean(list(per.values()))), 4),
        "worst": round(per[worst], 4),
        "worst_joint": worst,
        "compared": len(per),
        "measurable": len(na),
        "coverage": round(len(per) / len(na), 3) if na else 0.0,
        "joints": {n: round(v, 4) for n, v in per.items()},
    }


def pose_distance(a: dict, b: dict) -> float | None:
    """Mean joint displacement between two poses, in torso lengths."""
    d = pose_delta(a, b)
    return None if d is None else d["mean"]


def pose_drift(
    frame_paths,
    reference_path,
    *,
    max_pose_distance: float = SAME_POSE_MAX,
    max_worst_joint: float = WORST_JOINT_MAX,
) -> dict:
    """How far the frames drift from the reference's pose."""
    import numpy as np

    ref = landmarks(reference_path)
    empty = {
        "per_frame": {},
        "median": None,
        "worst": (None, None),
        "worst_joint": None,
        "coverage": 0.0,
        "measured": 0,
        "frames": 0,
        "held": False,
    }
    if ref is None or _normalise(ref) is None:
        return {
            **empty,
            "note": "no usable body in the pose reference (hips and shoulders must be visible).",
        }
    per_frame: dict[str, float] = {}
    per_joint: dict[str, float] = {}
    total = 0
    for p in frame_paths:
        total += 1
        got = landmarks(p)
        if got is None:
            continue
        d = pose_delta(ref, got)
        if d is not None:
            per_frame[Path(p).name] = d["mean"]
            per_joint[Path(p).name] = d["worst"]
    if not per_frame:
        return {
            **empty,
            "frames": total,
            "note": f"pose NOT VERIFIABLE: no body measurable in {total} frame(s).",
        }
    vals = sorted(per_frame.values())
    median = round(float(np.median(vals)), 4)
    worst = max(per_frame, key=lambda n: per_frame[n])
    coverage = round(len(per_frame) / total, 3)
    worst_joint = round(float(np.median(sorted(per_joint.values()))), 4)
    held = median <= max_pose_distance and worst_joint <= max_worst_joint
    return {
        "per_frame": per_frame,
        "median": median,
        "worst_joint": worst_joint,
        "worst": (worst, per_frame[worst]),
        "coverage": coverage,
        "measured": len(per_frame),
        "frames": total,
        "held": held,
        "note": (
            f"pose distance median {median} torso-lengths from the "
            f"reference, worst single joint {worst_joint}, over "
            f"{len(per_frame)}/{total} measurable frame(s); "
            f"{'held' if held else 'DRIFTED'} against "
            f"{max_pose_distance}/{max_worst_joint}."
        ),
    }


def limb_consistency(frame_paths, *, max_wobble: float = LIMB_WOBBLE_MAX) -> dict:
    """Do the limbs keep their length across the clip — is this a real body."""
    import numpy as np

    lengths: dict[str, list[float]] = {f"{a}->{b}": [] for a, b in LIMBS}
    measured = 0
    for p in frame_paths:
        got = landmarks(p)
        if got is None:
            continue
        norm = _normalise(got)
        if norm is None:
            continue
        measured += 1
        for a, b in LIMBS:
            if norm[a][1] < MIN_VISIBILITY or norm[b][1] < MIN_VISIBILITY:
                continue
            lengths[f"{a}->{b}"].append(float(np.linalg.norm(norm[a][0] - norm[b][0])))
    wobble = {}
    for name, vals in lengths.items():
        if len(vals) < 3:
            continue
        mean = float(np.mean(vals))
        if mean > 1e-6:
            wobble[name] = round(float(np.std(vals)) / mean, 4)
    if not wobble:
        return {
            "wobble": {},
            "worst": (None, None),
            "anatomical": False,
            "measured": measured,
            "note": "limb consistency NOT VERIFIABLE: no limb tracked across enough frames.",
        }
    worst = max(wobble, key=lambda n: wobble[n])
    bad = [n for n, v in wobble.items() if v > max_wobble]
    verdict = (
        "anatomically stable"
        if not bad
        else f"{len(bad)} limb(s) past {max_wobble:.0%} — the body is stretching"
    )
    return {
        "wobble": wobble,
        "worst": (worst, wobble[worst]),
        "anatomical": not bad,
        "measured": measured,
        "unstable": bad,
        "note": (
            f"limb length varies most on {worst} "
            f"({wobble[worst]:.0%} of its own length) over {measured} "
            f"frame(s); {verdict}."
        ),
    }
