"""The REAL identity instrument: ArcFace face-embedding drift."""

from __future__ import annotations

from pathlib import Path

SAME_PERSON_MAX = 0.35

HARD_DRIFT_MAX = 0.6

MIN_FACE_PX = 100

MIN_COVERAGE = 0.5

_ANALYZER = None


def _analyzer():
    """Lazy singleton FaceAnalysis. Import guarded so the offline package that"""
    global _ANALYZER
    if _ANALYZER is None:
        from insightface.app import FaceAnalysis  # type: ignore

        app = FaceAnalysis(
            name="buffalo_l", allowed_modules=["detection", "recognition", "genderage"]
        )
        from .device import detect, insightface_ctx

        app.prepare(ctx_id=insightface_ctx(detect()), det_size=(640, 640))
        _ANALYZER = app
    return _ANALYZER


def cosine_distance(a, b) -> float:
    """1 - cosine similarity of two embedding vectors. Pure numpy; unit-tested."""
    import numpy as np

    a = np.asarray(a, dtype="float64")
    b = np.asarray(b, dtype="float64")
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 1.0
    sim = float(np.dot(a, b) / (na * nb))
    return round(max(0.0, 1.0 - sim), 4)


def face_detail(path: str | Path) -> dict | None:
    """The largest face in an image: embedding + how big and confident it was."""
    import numpy as np  # noqa: F401  (ensures numpy present alongside the model)

    faces = _analyzer().get(_read_bgr(path))
    if not faces:
        return None
    faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    f = faces[-1]
    x0, y0, x1, y1 = (float(v) for v in f.bbox)
    out = {
        "embedding": f.normed_embedding,
        "face_px": round(min(x1 - x0, y1 - y0)),
        "det_score": round(float(f.det_score), 3),
        "bbox": (x0, y0, x1, y1),
    }
    sex, age = getattr(f, "sex", None), getattr(f, "age", None)
    if sex is not None:
        out["sex"] = sex
    if age is not None:
        out["age"] = int(age)
    return out


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated quantile. Local so the verdict needs no scipy."""
    if not sorted_vals:
        return 1.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _read_bgr(path: str | Path):
    """Load an image as BGR for InsightFace (which expects OpenCV order)."""
    from PIL import Image
    import numpy as np

    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"))
    return rgb[:, :, ::-1].copy()
