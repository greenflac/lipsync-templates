"""Body landmarks as a measurement: read a skeleton, compare two of them."""

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

#: CHOSEN 0.5, the midpoint of MediaPipe's 0..1 visibility score: under it a
#: point is the model's guess rather than something it saw. No run in this tree
#: measured where the guessing starts. It is declared here alone — the intake and
#: the loop finder import this bar — so that every reading of a skeleton in the
#: product discards the same points.
MIN_VISIBILITY = 0.5

#: Declared instruments: public here, called by no production path on purpose.
#:
#: `pose_delta` is the reference implementation of the quantity the product
#: actually runs, `fork_looper.pose_gap`. The two are not a duplicate: this one
#: takes RAW landmark points and normalises them afresh on every call, which is
#: the obvious way to compute it and the wrong way to compute it hundreds of
#: thousands of times; `pose_gap` normalises once per frame and reuses the
#: result across pairs. Keeping the slow, obvious version is what makes the fast
#: one checkable — `test_pose_gap_is_the_same_number_as_pose_delta` asserts the
#: two numbers agree on a fixture. Delete this and the product's own instrument
#: has nothing to be wrong against.
INSTRUMENTS = ("pose_delta",)

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
        which = " and ".join(n for n, v in (("first", a), ("second", b)) if v is None)
        raise ValueError(
            f"pose_delta: no body found in the {which} pose (landmarks returned None). "
            f"There is nothing to compare. The frequent cause is a frame with no torso "
            f"in it — a head-and-shoulders crop of the client photo, or a driving frame "
            f"the subject has walked out of. Compare two frames that both show a body."
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
