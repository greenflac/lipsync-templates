"""The REAL identity instrument: ArcFace face-embedding drift."""

from __future__ import annotations

from pathlib import Path

SAME_PERSON_MAX = 0.35

HARD_DRIFT_MAX = 0.6

MIN_FACE_PX = 100

START_MIN_FACE_PX = 70

MIN_COVERAGE = 0.5

_ANALYZER = None


def _analyzer():
    """Lazy singleton FaceAnalysis. Import guarded so the offline package that"""
    global _ANALYZER
    if _ANALYZER is None:
        from insightface.app import FaceAnalysis  # type: ignore

        app = FaceAnalysis(name="buffalo_l",
                           allowed_modules=["detection", "recognition", "genderage"])
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
    out = {"embedding": f.normed_embedding,
           "face_px": round(min(x1 - x0, y1 - y0)),
           "det_score": round(float(f.det_score), 3),
           "bbox": (x0, y0, x1, y1)}
    sex, age = getattr(f, "sex", None), getattr(f, "age", None)
    if sex is not None:
        out["sex"] = sex
    if age is not None:
        out["age"] = int(age)
    return out


def face_embedding(path: str | Path):
    """The largest face's embedding in an image, or None if no face is found."""
    d = face_detail(path)
    return None if d is None else d["embedding"]


def face_attributes(path: str | Path) -> dict | None:
    """Apparent sex/age of the largest face, from the local estimator."""
    d = face_detail(path)
    if d is None:
        return None
    return {k: d[k] for k in ("sex", "age", "face_px") if d.get(k) is not None}


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


def arcface_drift(frame_paths, reference_path, *,
                  min_face_px: int = MIN_FACE_PX) -> dict:
    """Per-frame identity drift away from a reference face, by embedding distance."""
    ref_detail = face_detail(reference_path)
    empty = {"per_frame": {}, "face_px": {}, "worst": (None, None),
             "drifted": [], "readable": 0, "judgeable": 0, "too_small": [],
             "no_face": [], "median": None, "p90": None, "coverage": 0.0}
    if ref_detail is None:
        return {**empty,
                "note": "no face in the reference photo: cannot measure identity."}
    if ref_detail["face_px"] < min_face_px:
        return {**empty,
                "note": (f"reference face is only {ref_detail['face_px']}px "
                         f"(< {min_face_px}px): too small to identify from. "
                         f"Supply a closer photo.")}
    ref = ref_detail["embedding"]

    per_frame: dict[str, float] = {}
    face_px: dict[str, int] = {}
    drifted: list[str] = []
    too_small: list[str] = []
    no_face: list[str] = []
    total = 0
    for p in frame_paths:
        total += 1
        name = Path(p).name
        d = face_detail(p)
        if d is None:
            no_face.append(name)
            continue
        face_px[name] = d["face_px"]
        if d["face_px"] < min_face_px:
            too_small.append(name)
            continue
        dist = cosine_distance(ref, d["embedding"])
        per_frame[name] = dist
        if dist > SAME_PERSON_MAX:
            drifted.append(name)

    if not per_frame:
        why = (f"{len(too_small)} frame(s) had a face under {min_face_px}px and "
               f"{len(no_face)} had none" if total else "no frames")
        return {**empty, "face_px": face_px, "readable": total,
                "too_small": too_small, "no_face": no_face,
                "note": (f"identity NOT VERIFIABLE: {why}. The face is too small "
                         f"in this clip to identify — frame it closer.")}

    vals = sorted(per_frame.values())
    worst = max(per_frame, key=lambda n: per_frame[n])
    median = round(_quantile(vals, 0.5), 4)
    p90 = round(_quantile(vals, 0.9), 4)
    coverage = round(len(per_frame) / total, 3) if total else 0.0
    note = (f"identity via ArcFace cosine distance: median {median}, p90 {p90}, "
            f"worst {per_frame[worst]} on {len(per_frame)}/{total} judgeable "
            f"frame(s) (coverage {coverage:.0%}; {len(too_small)} face(s) under "
            f"{min_face_px}px, {len(no_face)} with no face). "
            f"{len(drifted)} judgeable frame(s) past {SAME_PERSON_MAX}.")
    return {"per_frame": per_frame, "face_px": face_px,
            "worst": (worst, per_frame[worst]), "drifted": drifted,
            "readable": total, "judgeable": len(per_frame),
            "too_small": too_small, "no_face": no_face,
            "median": median, "p90": p90, "coverage": coverage, "note": note}
