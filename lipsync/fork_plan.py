"""Universal plan: one identity framing at the Kling input, always the same one."""

from __future__ import annotations

import time
from pathlib import Path

# The frame is read, not declared: the gateway needs the same number, and a
# gateway importing this module for it closed an import cycle.
from .frame import FRAME
from .fork_identity import FAIL, PASS, UNMEASURED
from . import clauses, pollinations


#: CHOSEN (by the product, out of the vertical feed's own standard): 9:16 is
#: what the feed shows. It is stated as the exact 0.5625 and not as "roughly
#: vertical" because only an exact number makes the final crop nothing at all.
#: Half the pipeline hangs off this one line — `fork_finish` reduces it to whole
#: sides, `fit_to_plan` and `exact_plan_box` reshape against it — so a second
#: copy of the ratio anywhere would be a second thing to keep in step.
PLAN_RATIO = 0.5625

#: CHOSEN. One pixel of rounding at our working heights (768..2752 px) moves the
#: ratio by under 0.0005, so this bound admits an exact crop and nothing else.
#: The measured route drift is 0.0044 — nine times this — and must not pass.
PLAN_TOLERANCE = 0.001

#: CHOSEN. The largest share of one side `fit_to_plan` may cut to reach the plan.
#: The measured drift costs 0.8% of the height; the 3:4 fossil the styliser used
#: to return would cost 24.7% of the width, which is a face and not a rounding.
#: 2% stands an order of magnitude away from both.
TRIM_MAX_SHARE = 0.02

SHOULDERS_BAND = (0.20, 0.42)

ANKLES_BAND = (0.86, 0.99)

#: CHOSEN 0.08 (by this module, out of how the generator behaves, not out of a
#: distribution): Kling scales the character onto the driving skeleton, so a
#: subject standing off-centre in the photo travels off-centre into the video.
#: Nothing in this tree measured where the bar belongs, only that it is needed.
CENTRE_TOL = 0.08

#: CHOSEN 0.72 (by this module, out of one observed failure): a subject already
#: filling the width loses the arms when they swing out, which is exactly what
#: spoiled run b4 on 88.1% of its frames. The run says "too wide"; it does not
#: say 0.72, so the share itself is a choice and not a measurement.
WIDTH_MAX = 0.72

from .fork_intake import MIN_FACE_PX  # noqa: E402

# Borrowed, in the place the second copy used to stand: the bar belongs to
# whoever reads a skeleton, and that is `pose`.
from .pose import MIN_VISIBILITY  # noqa: E402

#: MEASURED, and a record of a defect rather than of a requirement: this is what
#: the styliser returned back when the call asked for 768x1024. It is 3:4, not
#: the plan — see `FRAME` for the size we ask for now.
STYLED_SIZE_MEASURED = (896, 1200)

SHOULDER_POINTS = ("l_shoulder", "r_shoulder")
ANKLE_POINTS = ("l_ankle", "r_ankle")

#: CHOSEN, from the axes `plan_verdict` returns: these four read the pose, the
#: rest read the canvas and the face. The axes of `plan_verdict` that judge the
#: PERSON rather than the canvas or the face. A caller holding an image but no face measurement reads these four
#: and leaves the other two alone; naming them here keeps that subset from being
#: retyped at the call site, where it would drift silently.
PERSON_AXES = ("shoulders", "ankles", "centre", "width")


def tally(checked: int, violations: int, unmeasured: int) -> dict:
    """Return the numbers next to the verdict. Zero violations with zero checks is not a success."""
    if checked == 0:
        outcome = UNMEASURED
    elif violations:
        outcome = FAIL
    elif unmeasured:
        outcome = UNMEASURED
    else:
        outcome = PASS
    return {
        "outcome": outcome,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
    }


def _axis(name: str, ok: bool | None, note: str) -> dict:
    """Build one plan axis. `None` means "could not measure", and that is not "fail"."""
    if ok is None:
        return {"name": name, **tally(0, 0, 1), "note": note}
    return {"name": name, **tally(1, 0 if ok else 1, 0), "note": note}


def person_box(points, *, min_visibility: float = MIN_VISIBILITY) -> dict:
    """Return the person's box in frame fractions plus the shoulder and ankle heights."""
    if not isinstance(points, dict) or not points:
        return {**tally(0, 0, 1), "note": "no pose: nothing to read the plan from"}
    good = {
        k: v
        for k, v in points.items()
        if isinstance(v, (tuple, list))
        and len(v) >= 3
        and v[2] is not None
        and v[2] >= min_visibility
    }
    if not good:
        return {
            **tally(0, 0, 1),
            "note": (
                f"not one point with confidence {min_visibility}: "
                f"{len(points)} joints, all below the bar"
            ),
        }

    def mid(names):
        got = [good[n][1] for n in names if n in good]
        return round(sum(got) / len(got), 4) if got else None

    xs = [v[0] for v in good.values()]
    ys = [v[1] for v in good.values()]
    x0, x1 = min(xs), max(xs)
    return {
        **tally(1, 0, 0),
        "x0": round(x0, 4),
        "x1": round(x1, 4),
        "y0": round(min(ys), 4),
        "y1": round(max(ys), 4),
        "centre": round((x0 + x1) / 2, 4),
        "width": round(x1 - x0, 4),
        "shoulders": mid(SHOULDER_POINTS),
        "ankles": mid(ANKLE_POINTS),
        "joints": len(good),
        "note": (
            f"confident joints {len(good)} of {len(points)}; "
            f"width span {x0:.3f}..{x1:.3f}, height span "
            f"{min(ys):.3f}..{max(ys):.3f}"
        ),
    }


def ratio_axis(width, height) -> dict:
    """Check the aspect ratio. There is no band: 9:16 is a number, not a mood."""
    if not width or not height:
        return _axis("canvas", None, f"sizes not taken: {width}x{height}")
    got = width / height
    ok = abs(got - PLAN_RATIO) <= PLAN_TOLERANCE
    return _axis(
        "canvas",
        ok,
        f"{width}x{height} = {got:.4f} against the plan {PLAN_RATIO} "
        f"(tolerance {PLAN_TOLERANCE} covers rounding to whole pixels and "
        f"nothing else)",
    )


def _band_axis(name, value, band, what) -> dict:
    lo, hi = band
    if value is None:
        return _axis(name, None, f"{what} not visible: nothing to judge by")
    return _axis(name, lo <= value <= hi, f"{what} at {value} against the band {lo}..{hi}")


def plan_verdict(*, width=None, height=None, points=None, face_px=None) -> dict:
    """Check whether the image fits the universal plan. Five axes, three outcomes."""
    t0 = time.perf_counter()
    axes = [ratio_axis(width, height)]

    box = person_box(points or {})
    if box["outcome"] != PASS:
        axes += [_axis(n, None, box["note"]) for n in PERSON_AXES]
    else:
        axes.append(_band_axis("shoulders", box["shoulders"], SHOULDERS_BAND, "shoulders"))
        axes.append(_band_axis("ankles", box["ankles"], ANKLES_BAND, "ankles"))
        off = abs(box["centre"] - 0.5)
        axes.append(
            _axis(
                "centre",
                off <= CENTRE_TOL,
                f"person centre {box['centre']}, offset {off:.4f} against the tolerance {CENTRE_TOL}",
            )
        )
        axes.append(
            _axis(
                "width",
                box["width"] <= WIDTH_MAX,
                f"the person takes {box['width']} of the width against the ceiling {WIDTH_MAX}",
            )
        )

    if face_px is None:
        axes.append(_axis("face", None, "the face was never asked about: size NOT MEASURED"))
    else:
        axes.append(
            _axis(
                "face",
                True,
                f"{face_px} px against the bar {MIN_FACE_PX}"
                + (
                    ""
                    if face_px >= MIN_FACE_PX
                    else "; WARNING: smaller than the bar, so the output "
                    "identity is JUDGED BY THE OPERATOR'S EYE"
                ),
            )
        )

    checked = sum(a["checked"] for a in axes)
    violations = sum(a["violations"] for a in axes)
    unmeasured = sum(a["unmeasured"] for a in axes)
    return {
        **tally(checked, violations, unmeasured),
        "axes": axes,
        "box": box,
        "seconds": round(time.perf_counter() - t0, 3),
        "note": "; ".join(f"{a['name']}: {a['note']}" for a in axes),
    }


def canvas_for(width: int, height: int) -> dict:
    """Return the 9:16 canvas the image fits into whole. Padding, not cropping."""
    _sizes_or_raise(width, height)
    if width / height > PLAN_RATIO:
        out_w, out_h = width, round(width / PLAN_RATIO)
    else:
        out_w, out_h = round(height * PLAN_RATIO), height
    out_w += out_w % 2
    out_h += out_h % 2
    return {
        "width": out_w,
        "height": out_h,
        "left": (out_w - width) // 2,
        "top": (out_h - height) // 2,
        "added_share": round(1 - (width * height) / (out_w * out_h), 4),
        "note": (
            f"{width}x{height} -> {out_w}x{out_h}: padded, "
            f"not cropped; margins {(out_w - width) // 2} at the sides and "
            f"{(out_h - height) // 2} at the top and bottom"
        ),
    }


def _even_down(value: float) -> int:
    """Round down to a whole even number: h264 refuses odd sides, and a crop may only shrink."""
    whole = int(value)
    return whole - whole % 2


def _sizes_or_raise(width, height) -> None:
    if not isinstance(width, int) or not isinstance(height, int):
        raise TypeError(f"sizes {width!r}x{height!r}: expected integers")
    if width <= 0 or height <= 0:
        raise ValueError(f"sizes {width}x{height}: expected above zero")


def fit_to_plan(width: int, height: int) -> dict:
    """Decide how a frame reaches the plan: leave it, trim it, or refuse it.

    Three outcomes, because "off the plan" is two different states. A frame
    within `PLAN_TOLERANCE` is already the plan ("none"). A frame off the plan
    by no more than `TRIM_MAX_SHARE` of one side lost the plan to the model's
    size grid, and that margin is cut off ("crop"). Anything further away is a
    different framing rather than a rounding, and it is reported as "pad" with
    one violation: the padded canvas is 9:16 by arithmetic and blurred bars by
    eye, which the acceptance criterion of 2026-08-26 forbids in every case.
    The padded geometry is still returned, so the caller can outpaint those
    bands into scene and measure the result — but it is a refusal to ship, not
    a repair, and the numbers say so.

    :param width: frame width in whole pixels, above zero.
    :param height: frame height in whole pixels, above zero.
    :returns: `action` ("none" | "crop" | "pad"), the resulting `width` and
        `height`, `left` and `top` offsets, `trimmed_share`, and the
        three-outcome numbers, where "pad" carries `violations` 1.

    >>> fit_to_plan(768, 1376)["action"]
    'crop'
    >>> fit_to_plan(896, 1200)["violations"]
    1
    """
    _sizes_or_raise(width, height)
    got = width / height
    if abs(got - PLAN_RATIO) <= PLAN_TOLERANCE:
        return {
            **tally(1, 0, 0),
            "action": "none",
            "width": width,
            "height": height,
            "left": 0,
            "top": 0,
            "trimmed_share": 0.0,
            "note": (
                f"{width}x{height} = {got:.4f} is the plan {PLAN_RATIO} "
                f"within {PLAN_TOLERANCE}: nothing to do"
            ),
        }

    if got > PLAN_RATIO:
        out_w, out_h = _even_down(height * PLAN_RATIO), height
        trimmed = 1 - out_w / width
        side = "width"
    else:
        out_w, out_h = width, _even_down(width / PLAN_RATIO)
        trimmed = 1 - out_h / height
        side = "height"

    # The crop is offered only when it actually lands on the plan: even-ing the
    # side down moves the ratio too, and on a small frame that move can be
    # bigger than the tolerance the crop is supposed to satisfy.
    exact = out_w > 0 and out_h > 0 and abs(out_w / out_h - PLAN_RATIO) <= PLAN_TOLERANCE
    if exact and trimmed <= TRIM_MAX_SHARE:
        return {
            **tally(1, 0, 0),
            "action": "crop",
            "width": out_w,
            "height": out_h,
            "left": (width - out_w) // 2,
            "top": (height - out_h) // 2,
            "trimmed_share": round(trimmed, 4),
            "note": (
                f"{width}x{height} = {got:.4f} -> {out_w}x{out_h} = "
                f"{out_w / out_h:.4f}: {trimmed:.4f} of the {side} trimmed "
                f"against the budget {TRIM_MAX_SHARE}"
            ),
        }

    plan = canvas_for(width, height)
    why = (
        f"the trim would cost {trimmed:.4f} of the {side} against the budget {TRIM_MAX_SHARE}"
        if trimmed > TRIM_MAX_SHARE
        else (
            f"the deepest legal trim, {out_w}x{out_h}, still misses the plan "
            f"by more than {PLAN_TOLERANCE}"
        )
    )
    # One violation, not zero: the owner's criterion of 2026-08-26 is 9:16 with
    # no padding in 100% of cases, so a frame that only arithmetic can call the
    # plan is a defect. Reporting it clean is how 0.5581 reached the shipped
    # templates and was then fed back into the same pipeline as an input.
    return {
        **tally(1, 1, 0),
        "action": "pad",
        "width": plan["width"],
        "height": plan["height"],
        "left": plan["left"],
        "top": plan["top"],
        "trimmed_share": 0.0,
        "canvas": plan,
        "note": (
            f"{width}x{height} = {got:.4f} was NOT brought to the plan: "
            f"{why}, and a cut that deep takes the subject and not a margin. "
            f"The {plan['width']}x{plan['height']} padding is a refusal and "
            f"not a repair: blurred bands are 9:16 only by arithmetic, and "
            f"nothing padded may ship"
        ),
    }


def to_plan(src, dst, *, opener=None, filler=None) -> dict:
    """Lay the image into the plan canvas. The injection points keep the test off the disk."""
    if opener is None:
        from PIL import Image  # noqa: PLC0415

        def opener(path):
            return Image.open(path).convert("RGB")

    try:
        im = opener(str(src))
    except Exception as exc:  # noqa: BLE001
        return {
            **tally(0, 0, 1),
            "path": None,
            "note": f"the image did not open: {type(exc).__name__}: {exc}",
        }

    w, h = im.size
    plan = canvas_for(int(w), int(h))
    if filler is None:
        from PIL import Image, ImageFilter  # noqa: PLC0415

        def filler(image, box):
            back = image.resize((box["width"], box["height"]))
            return back.filter(ImageFilter.GaussianBlur(radius=24))

    out = filler(im, plan)
    out.paste(im, (plan["left"], plan["top"]))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    out.save(str(dst))
    return {
        **tally(1, 0, 0),
        "path": str(dst),
        "plan": plan,
        # What came IN, so the caller can judge the styliser without decoding the
        # file a second time. `plan` describes the canvas we made, not the source.
        "source": {"width": int(w), "height": int(h)},
        "note": plan["note"],
    }


CARD_TOL_MIN = 0.05

CARD_TOL_MAX = 0.20


def _spread(values):
    """Return half the spread between the 10th and 90th percentiles, with the edges dropped."""
    got = sorted(v for v in values if v is not None)
    if len(got) < 3:
        return None
    lo = got[int(0.10 * (len(got) - 1))]
    hi = got[int(0.90 * (len(got) - 1))]
    return round((hi - lo) / 2, 4)


def composition_card(poses, *, min_visibility: float = MIN_VISIBILITY) -> dict:
    """Report where the person stands on the driving: medians plus the measured spread."""
    boxes = [person_box(p, min_visibility=min_visibility) for p in (poses or [])]
    good = [b for b in boxes if b["outcome"] == PASS]
    if not good:
        return {**tally(0, 0, 1), "note": (f"the pose was read on none of the {len(boxes)} frames")}

    def med(key):
        got = sorted(b[key] for b in good if b.get(key) is not None)
        return round(got[len(got) // 2], 4) if got else None

    def tol(key):
        got = _spread([b.get(key) for b in good])
        if got is None:
            return CARD_TOL_MIN
        return round(min(max(got, CARD_TOL_MIN), CARD_TOL_MAX), 4)

    card = {
        "shoulders": med("shoulders"),
        "ankles": med("ankles"),
        "centre": med("centre"),
        "width": med("width"),
        "tol_shoulders": tol("shoulders"),
        "tol_ankles": tol("ankles"),
        "tol_centre": tol("centre"),
        "tol_width": tol("width"),
        "frames": len(good),
        "of": len(boxes),
    }
    return {
        **tally(len(good), 0, len(boxes) - len(good)),
        **card,
        "note": (
            f"over {len(good)} frames of {len(boxes)}: shoulders "
            f"{card['shoulders']}+-{card['tol_shoulders']}, ankles "
            f"{card['ankles']}+-{card['tol_ankles']}, centre "
            f"{card['centre']}+-{card['tol_centre']}, width "
            f"{card['width']}+-{card['tol_width']}"
        ),
    }


def _height_words(top, bottom) -> str:
    """Turn numbers into photographic language, which the model understands better than coordinates."""
    span = None if (top is None or bottom is None) else bottom - top
    if span is None:
        return "full-length framing, the whole person inside the frame"
    if span >= 0.55:
        return (
            "a full-length shot: the person occupies most of the frame "
            "height, the whole body inside the frame"
        )
    if span >= 0.38:
        return (
            "a full-length shot with air: the whole person is in frame "
            "with some space above and below"
        )
    return (
        "a wider shot: the person is small in the frame, the whole body "
        "visible with generous space around"
    )


def framing_clause(card) -> str:
    """Turn the composition card into a prompt line, assembled separately from the call."""
    if not isinstance(card, dict) or card.get("outcome") != PASS:
        return ""
    parts = [_height_words(card.get("shoulders"), card.get("ankles"))]
    off = abs((card.get("centre") or 0.5) - 0.5)
    parts.append(
        "the person centred horizontally"
        if off <= 0.08
        else (
            "the person placed left of centre"
            if card["centre"] < 0.5
            else "the person placed right of centre"
        )
    )
    parts.append(
        "shot on a normal lens with no perspective distortion, the "
        "camera at chest height and far enough back to keep the whole "
        "body in frame"
    )
    return "FRAMING, this outranks any framing described above: " + "; ".join(parts)


def in_card(points, card, *, min_visibility: float = MIN_VISIBILITY) -> dict:
    """Check the pose on the image against the driving card, not against the global bands."""
    if not isinstance(card, dict) or card.get("outcome") != PASS:
        return {**tally(0, 0, 1), "note": "no composition card: nothing to compare against"}
    box = person_box(points, min_visibility=min_visibility)
    if box["outcome"] != PASS:
        return {**tally(0, 0, 1), "note": str(box.get("note"))}
    bad, seen = [], 0
    for key, label in (("centre", "centre"), ("width", "width")):
        want, tol, got = card.get(key), card.get(f"tol_{key}"), box.get(key)
        if want is None or got is None:
            continue
        seen += 1
        if abs(got - want) > tol:
            bad.append(f"{label} {got} against {want}+-{tol}")
    if not seen:
        return {**tally(0, 0, 1), "note": "not one axis could be compared"}
    return {
        **tally(seen, len(bad), 0),
        "box": box,
        "note": (
            "; ".join(bad) + "; Kling scales the character to the "
            "driving skeleton, and a reference off the composition "
            "slides off the frame edge"
            if bad
            else f"composition matches on {seen} axes: centre {box['centre']}, "
            f"width {box['width']} (shoulders {box['shoulders']} and "
            f"ankles {box['ankles']} are measured but NOT JUDGED)"
        ),
    }


EXTEND_CLAUSE = (
    "extend this image so it fills the whole vertical frame edge to edge: the "
    "blurred bands at the top and bottom must become a natural continuation of "
    "the same scene — same background, same lighting, same perspective, same "
    "colour grade — as if the photograph had always been this tall"
)

KEEP_SUBJECT_CLAUSE = (
    "do not move, rescale, recrop or alter the person in any way; keep the "
    "same face and the same composition of the subject"
)


def extend_prompt(*, extra: str = "") -> str:
    """Build the margin-outpainting prompt plus the lettering ban."""
    parts = [EXTEND_CLAUSE, KEEP_SUBJECT_CLAUSE, no_brands_clause()]
    if extra:
        parts.append(extra.strip())
    return ". ".join(parts)


#: The size the outpainter is asked for: `FRAME`, not a size of its own. The
#: outpaint feeds the same delivery frame as everything else, so a second point
#: here would only be a second thing to keep in step. The canvas asked for is
#: smaller than the 1152x2048 this used to name; the outpainter is asked to
#: continue the scene into the margins, and the margins are a share of the
#: frame, not a pixel count. The route may still answer with another size; that
#: is what the ratio axis above is for.
EXTEND_SIZE = FRAME


def extend_to_plan(src, dst, *, extender=None, sizer=None, size=EXTEND_SIZE) -> dict:
    """Turn the plan margins into a continuation of the scene."""
    want_w, want_h = int(size[0]), int(size[1])
    if extender is None:

        def extender(prompt, source, out_path):
            return pollinations.images_edit(
                prompt,
                source,
                out_path,
                model="nanobanana-2",
                width=want_w,
                height=want_h,
            )

    prompt = extend_prompt()
    try:
        extender(prompt, str(src), str(dst))
    except Exception as exc:  # noqa: BLE001
        return {
            **tally(0, 0, 1),
            "path": str(src),
            "extended": False,
            "note": (
                f"the outpainter did not answer: {type(exc).__name__}: {exc}. "
                f"Going on with the padded image: it is worse, but it "
                f"exists"
            ),
        }
    if sizer is None:

        def sizer(path):
            from PIL import Image  # noqa: PLC0415

            return Image.open(path).size

    try:
        w, h = sizer(str(dst))
    except Exception as exc:  # noqa: BLE001
        return {
            **tally(0, 0, 1),
            "path": str(dst),
            "extended": True,
            "note": f"the outpainted size was not taken: {type(exc).__name__}: {exc}",
        }
    got = ratio_axis(w, h)
    return {
        **tally(1, got["violations"], 0),
        "path": str(dst),
        "extended": True,
        "width": w,
        "height": h,
        "asked": (want_w, want_h),
        "note": f"asked for {want_w}x{want_h}, outpainted to {w}x{h}; {got['note']}",
    }


def no_brands_clause() -> str:
    """Return the brand ban from its single source per project."""
    return clauses.NO_BRANDS_CLAUSE
