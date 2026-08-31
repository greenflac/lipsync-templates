"""End-to-end product stand: client photo + driving + aesthetic -> clip."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from .clauses import NO_BRANDS_CLAUSE, NO_LOOK_TRANSFER_CLAUSE, ROLE_CLAUSE
from .frame import FRAME
from .fork_identity import FAIL, PASS, UNMEASURED, SAME_PERSON_MAX
from .fork_video import EXIT_BY_OUTCOME, FRAME_SUFFIXES
from . import fork_aesthetic, fork_plan, pollinations


KLING_ENDPOINT = "fal-ai/kling-video/v2.6/standard/motion-control"

KLING_FIELDS = ("video_url", "image_url", "character_orientation")

#: MEASURED by probing the endpoint with a negative control: the probe sent
#: `character_orientation: 0` and the API answered "Input should be 'image' or
#: 'video'", so the admitted pair is the vendor's own list rather than our
#: reading of a document. The probe reply was kept as `work/bake_kling26_o0.json`,
#: which no longer survives in the tree — this line is now the only record of it.
KLING_ORIENTATIONS = ("image", "video")

#: CHOSEN by the owner out of the two values the probe admitted (see
#: `KLING_ORIENTATIONS` above, which is where the choice is bounded): the
#: motion comes from the driving and the identity from the photo, so the
#: character is oriented by the video and not by the still. Every route sends
#: it as the default, and `kling_payload` refuses anything outside the measured
#: pair, so a taste change here cannot quietly become an unknown field value.
CHARACTER_ORIENTATION = "video"

KLING_PRICE_PER_SECOND_USD = 0.07

PRODUCT_SECONDS = 5.0

KLING_PRICE_USD = round(KLING_PRICE_PER_SECOND_USD * PRODUCT_SECONDS, 4)

KLING_PRO_PRICE_3S_USD = 2.6880
KLING_PRICE_3S_USD = 0.21


def kling_price(seconds: float) -> float:
    """Return the order price for a duration. Garbage raises, it is not guessed away."""
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        raise TypeError(f"duration {seconds!r}: expected a number of seconds")
    if seconds <= 0:
        raise ValueError(f"duration {seconds}: expected greater than zero")
    return round(KLING_PRICE_PER_SECOND_USD * float(seconds), 4)


KLING_LATENCY_S = (107.4, 190.0)

#: DERIVED from `KLING_LATENCY_S`: the top of the measured band, 190 s, times
#: eight. Not from a timing run of its own, and coarse on purpose — the fal
#: queue has been seen at a quarter of an hour — because the two mistakes do
#: not cost the same: waiting too long costs time, whereas giving up early
#: costs MONEY, the order having already been paid for. It bounds the poll loop
#: in `live_kling`, so lowering it abandons paid orders that were still coming.
KLING_WAIT_S = 1520

#: MEASURED by ffprobe over every Kling output still on disk, 2026-08-28.
#: The model has NO fixed output size — it follows the geometry of what it is
#: given, and this pair is a record of what we were feeding it, not a property
#: of the service:
#:
#:     2026-08-22   960x960    x4     (square references)
#:     2026-08-22   816x1104   x3     (a 768x1024 photo went in)
#:     2026-08-22   576x1024   x1
#:     2026-08-23   720x1280   x7     (after the pipeline was made vertical)
#:
#: On the seven clips of 2026-08-23, `kling_out.mp4` and `final.mp4` are the
#: same size: the crop had nothing to cut. That is why `frame.FRAME`
#: reads (720, 1280) and this reads (960, 960) without either being wrong —
#: they are two different days of input. The two were carried as
#: contradicting MEASURED claims about the same fact until the artefacts were
#: measured; the artefacts had been sitting in the retired engine's tree the
#: whole time, which is the reason a retired repository is still evidence.
#:
#: Nothing branches on this pair. It only lets the note say whether the
#: geometry is one we have seen before; the gate is `OUT_RATIO_MAX`.
KLING_OUT_SIZE = (960, 960)
#: MEASURED on those same eight orders, and unlike the size this one IS a gate:
#: the audio assembly counts frames at 30, so any other rate leaves the output
#: unjudgeable rather than bad.
KLING_OUT_FPS = 30.0

#: CHOSEN 1.0 as a CEILING ("not landscape"), deliberately not the plan ratio.
#: The first edition compared the output with `KLING_OUT_SIZE` and failed a live
#: run that came back 816x1104 — the vertical we had been chasing all day. The
#: instrument was right by the letter and wrong on the substance, which is why
#: the bar guards the PROPERTY and not the numbers. A square is admitted because
#: eight orders delivered one and it crops to 9:16, only at a higher loss.
#: Clamped on one side only, and knowingly so: a floor is a second decision and
#: is not taken here.
OUT_RATIO_MAX = 1.0

#: CHOSEN 0.5, and chosen with its cost stated rather than picked round: the
#: crop that follows takes 11.1% of the height off a 0.5 output to reach the
#: plan's 0.5625, which is the most this product will silently discard. A
#: ceiling alone is not a clamp — nothing refused a frame NARROWER than the
#: plan, so a 1:3 clip would have passed a gate written for vertical video and
#: then lost 41% of its height to the crop. MEASURED against every Kling output
#: still on disk on 2026-08-28 (1.0000 x4, 0.7391 x3, 0.5625 x8): this floor
#: refuses nothing that has ever arrived.
OUT_RATIO_MIN = 0.5

#: MEASURED against Kling's own gate, which refuses with "Video duration can
#: not less than 3s" — the message is quoted in the check so the reason travels
#: with the verdict. All three ways round it were tried and failed: rate
#: stretching returned 88 frames instead of 15, freeze padding was animated by
#: the model, and per-scene rendering meets the same gate. So this is an
#: acceptance criterion for the window, not a preference.
MIN_SCENE_S = 3.0

#: CHOSEN by the owner: the `pro` tier is excluded for good, and the exclusion
#: has to be machine-made — a line in a document does not stop an order that is
#: already paid. The price is the reason: $0.8960 per second against $0.0700.
FORBIDDEN_TIERS = ("pro",)

#: CHOSEN by the owner with his eyes on 2026-08-22, AGAINST the number. The
#: style-hit measure scored `gpt-image-2` 0.8801 against 0.8156 here — and it
#: won precisely by copying what it had no business copying: an olive belted
#: dress over the client's grey top, a hip-hand lean over a straight stance.
#: The measure is built on colour and texture, and clothing and pose are colour
#: and texture too, so it REWARDS repainting. A one-sided measure cannot say
#: "alike on these axes while differing on those", and that is the thing wanted.
STYLE_MODEL = "nanobanana-2"
STYLE_ROUTE = "pollinations.compose"
#: CHOSEN with the model above: `compose` is called with two pictures, the
#: first carrying the person and the second only the look. The count is a
#: decision because the roles are positional — a third image has no role to
#: hold, and one image cannot keep the two apart.
STYLE_IMAGES = 2

#: The size we ASK the styliser for: `frame.FRAME`, taken rather than
#: restated. The reference and the clip must share one frame or the reference is
#: padded on its way into the video model, and the frame the video model returns
#: is what the plan measured. Both sides being multiples of 16 also matters —
#: that is the grid the model MEASURABLY snaps to (asked 768x1024, it returned
#: 896x1200 = 56x16 by 75x16) — but that is a property of the frame, checked
#: where the frame is declared, not a second reason to write the number again.
STYLED_SIZE = FRAME

STYLE_HIT_REFERENCE = 0.8156
STYLE_HIT_REJECTED = 0.8801
STYLE_FLOOR_REFERENCE = 0.6409
STYLE_TEXT_ROUTE_REFERENCE = 0.6773

#: CHOSEN 0.05: above the instrument's own noise and well below its signal. On
#: the styliser comparison the REJECTED text route scored 0.6773 against a floor
#: of 0.6409, so the noise here is +0.0364, while the accepted route stood
#: +0.2392 clear. A bar at the noise floor would pass noise as style; a bar near
#: the winner would pass nothing. What this number does not know: it was taken
#: on one instrument's scale, which is why the floor is recomputed on the spot
#: by the same instrument and compared only with itself.
#: DEBT(2026-08-22): the margin is stated in fractions, not in sigmas.
STYLE_MARGIN_MIN = 0.05

#: CHOSEN by the owner: an editing cut inside a single scene is a defect of the
#: generation and not a style, so the allowance is none. The detector's own
#: threshold is `motion.JUMP_MAX` and is read from there, never copied here.
MAX_CUTS_OUT = 0

#: MEASURED with ArcFace on our own material in one run, as three rungs: the
#: same face after stylisation, the reference the owner rejected, and a known
#: stranger (the driving actor against the client photo). One ladder, one place.
LADDER_SAME = 0.0652
#: MEASURED on that run as the distance to the REJECTED reference — by then a
#: different person. Both identity checks branch on this rung and on no other:
#: between the pass bar and here the face is merely occluded, which is a "could
#: not measure" for the operator's eye rather than a swap. Eyewear carried over
#: from a style reference put ArcFace at 0.3928 on the same person, and that is
#: what the middle band exists to hold.
LADDER_REJECTED = 0.7137
LADDER_STRANGER = 1.0217

STAGES = (
    "1 intake of three inputs",
    "2 client photo stylization",
    "3 styled photo acceptance",
    "4 driving window and cutting",
    "5 upload inputs and call Kling",
    "6 output acceptance",
    "7 final assembly",
    "8 report",
)


def say(text: str, *, log=None) -> None:
    """Write the line to stderr immediately. A silent long run has already cost us a run."""
    stream = sys.stderr if log is None else log
    stream.write(text + "\n")
    flush = getattr(stream, "flush", None)
    if flush:
        flush()


def verdict(checked: int, violations: int, unmeasured: int) -> str:
    """Return one of three outcomes from three numbers. Zero checks is not a success."""
    if checked <= 0:
        return UNMEASURED
    if violations > 0:
        return FAIL
    if unmeasured > 0:
        return UNMEASURED
    return PASS


def _result(stage: str, checks: list, *, note: str = "", **extra) -> dict:
    """Build a stage from a list of checks. Each check is `(name, outcome, note)`."""
    checked = sum(1 for c in checks if c[1] in (PASS, FAIL))
    violations = sum(1 for c in checks if c[1] == FAIL)
    unmeasured = sum(1 for c in checks if c[1] == UNMEASURED)
    return {
        "stage": stage,
        "outcome": verdict(checked, violations, unmeasured),
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
        "checks": [{"name": n, "outcome": o, "note": t} for n, o, t in checks],
        "note": note,
        **extra,
    }


def line(res: dict) -> str:
    """Return the one-line stage summary: the verdict with its numbers right next to it."""
    return (
        f"[{res['outcome']:<18}] {res['stage']:<34} "
        f"checked {res['checked']}, violations {res['violations']}, "
        f"unmeasured {res['unmeasured']}" + (f" | {res['note']}" if res.get("note") else "")
    )


def soft_import(name: str):
    """Return a neighbour module or an intelligible refusal. Never let the exception escape."""
    try:
        mod = __import__(f"lipsync.{name}", fromlist=["*"])
    except ImportError as exc:
        return None, (
            f"module lipsync.{name} is missing ({exc}). This is not a "
            f"product defect: the stage was not measured. A run "
            f"parameter can substitute it"
        )
    return mod, None


def entry_point(mod, candidates):
    """Return the first existing function from the name list, or a refusal naming them all."""
    for name in candidates:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn, name, None
    return (
        None,
        None,
        (f"{mod.__name__} has none of the entry points {list(candidates)}: nothing to call"),
    )


def _call(fn, kwargs: dict, positional: tuple):
    """Call a neighbour: by keyword first, positionally on a signature mismatch."""
    try:
        return fn(**kwargs)
    except TypeError as exc:
        if "argument" not in str(exc) and "parameter" not in str(exc):
            raise
        return fn(*positional)


def outcome_of(reply, *, what: str) -> tuple:
    """Extract the verdict from a neighbour reply. No verdict means "could not measure", not "pass"."""
    if isinstance(reply, dict) and reply.get("outcome") in (PASS, FAIL, UNMEASURED):
        return reply["outcome"], str(reply.get("note") or "")
    return UNMEASURED, (
        f"{what} replied {type(reply).__name__} without an outcome field: "
        f"no verdict, nothing to judge by"
    )


def refuse_pro(endpoint: str) -> None:
    """Guard the money. The template author excluded `pro` permanently, and the ban is machine-enforced."""
    parts = str(endpoint).split("/")
    hit = [p for p in parts if p in FORBIDDEN_TIERS]
    if hit:
        pro_per_s = round(KLING_PRO_PRICE_3S_USD / 3.0, 4)
        raise ValueError(
            f"endpoint {endpoint} contains {hit}: {FORBIDDEN_TIERS} are excluded "
            f"by the template author permanently (${pro_per_s} versus "
            f"${KLING_PRICE_PER_SECOND_USD} per second, "
            f"{round(pro_per_s / KLING_PRICE_PER_SECOND_USD, 1)}x; the label "
            f"still did not survive, and the background got a painted-in animation)"
        )


PALETTE_BINS = 8
PALETTE_SIDE = 256


EXTERNAL_INSTRUMENT = "creative_eval.style.similarity (external, shipped)"
FALLBACK_ABSENT = "palette_similarity (fallback: the external package is missing)"
FALLBACK_BROKEN = (
    "palette_similarity (fallback: the external package imported but failed: {reason})"
)


def shipped_similarity(left, right) -> tuple[float | None, str]:
    """Measure the style hit and name the instrument that produced the number.

    Returns `(value, instrument)`; `value is None` means could not measure. The
    name is returned together with the number rather than resolved by a second
    call, because two independent decisions about one fact drift apart: the run
    that prompted this reported the external device while the number had come
    from the fallback. Whoever answered is the only thing that can name itself.

    Three outcomes, kept apart on purpose: the external answered, the external
    is not installed, the external is installed and broke. The last one carries
    the exception text whole — the reason a device dropped out is the half of
    the report that says what to fix, and a truncated reason has already sent
    one diagnosis the wrong way.

    >>> value, instrument = shipped_similarity("a.png", "b.png")
    >>> instrument.startswith("creative_eval") or "fallback" in instrument
    True
    """
    try:
        from creative_eval.style import similarity as _external  # noqa: PLC0415
    except ImportError:
        return palette_similarity(left, right), FALLBACK_ABSENT
    except Exception as exc:  # noqa: BLE001
        # Importable-but-throwing is a breakage, not an absence: the two get
        # different names so a broken install cannot read as a bare machine.
        return palette_similarity(left, right), FALLBACK_BROKEN.format(
            reason=f"import raised {type(exc).__name__}: {exc}"
        )
    try:
        return float(_external(str(left), str(right))), EXTERNAL_INSTRUMENT
    except Exception as exc:  # noqa: BLE001
        return palette_similarity(left, right), FALLBACK_BROKEN.format(
            reason=f"{type(exc).__name__}: {exc}"
        )


def measured_by(similarity, left, right) -> tuple[float | None, str]:
    """Run one measurement and report the device that actually answered.

    An injected device returns a bare number and is named after itself; the
    shipped one returns its own name alongside the number. Either way the name
    comes off the call that ran, never off which callable was expected.

    >>> measured_by(lambda a, b: 0.5, "a.png", "b.png")
    (0.5, 'injected: <lambda>')
    """
    outcome = similarity(left, right)
    if isinstance(outcome, tuple):
        value, name = outcome
        return (None if value is None else float(value)), str(name)
    injected = getattr(similarity, "__name__", type(similarity).__name__)
    return outcome, f"injected: {injected}"


def palette_similarity(left, right) -> float | None:
    """Measure with the fallback instrument: cosine between palettes. `None` means could not measure."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    try:
        vecs = []
        for p in (left, right):
            arr = np.asarray(
                Image.open(str(p)).convert("RGB").resize((PALETTE_SIDE, PALETTE_SIDE)),
                dtype="float64",
            ).reshape(-1, 3)
            hist, _ = np.histogramdd(arr, bins=(PALETTE_BINS,) * 3, range=((0, 255),) * 3)
            v = hist.ravel()
            norm = float(np.linalg.norm(v))
            if norm <= 0:
                return None
            vecs.append(v / norm)
    except Exception:  # noqa: BLE001
        return None
    return round(float(vecs[0] @ vecs[1]), 4)


def live_upload(path) -> str:
    """Upload a file and return its public fal link. UNVERIFIED in this shift (no money was spent)."""
    import fal_client  # noqa: PLC0415

    return fal_client.upload_file(Path(path))


def live_kling(
    *,
    video_url: str,
    image_url: str,
    character_orientation: str,
    out_path,
    endpoint: str = KLING_ENDPOINT,
    poll_s: int = 15,
    wait_s: int = KLING_WAIT_S,
) -> str:
    """Place the fal order and download the output. This is the paid path: exactly $0.21 per call."""
    import os  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    refuse_pro(endpoint)
    key = os.environ.get("FAL_KEY")
    if not key:
        raise RuntimeError("FAL_KEY is not set: nothing to order with")
    head = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    payload = {
        "video_url": video_url,
        "image_url": image_url,
        "character_orientation": character_orientation,
    }

    def _req(url, data=None):
        req = urllib.request.Request(url, data=data, headers=head)
        with urllib.request.urlopen(req, timeout=60) as fh:
            return json.loads(fh.read().decode() or "{}")

    app = "/".join(endpoint.split("/")[:2])
    sub = _req(f"https://queue.fal.run/{endpoint}", data=json.dumps(payload).encode())
    rid = sub["request_id"]
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(poll_s)
        st = _req(f"https://queue.fal.run/{app}/requests/{rid}/status")
        if st.get("status") in ("COMPLETED", "FAILED", "ERROR"):
            break
    res = _req(f"https://queue.fal.run/{app}/requests/{rid}")
    url = (res.get("video") or {}).get("url")
    if not url:
        raise RuntimeError(f"the reply has no video link: {str(res)}")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=600) as fh:
        Path(out_path).write_bytes(fh.read())
    return str(out_path)


def live_stylize(
    *, person, style, prompt: str, out_path, model: str = STYLE_MODEL, size=STYLED_SIZE
) -> str:
    """Stylize with two images through the measured winner. Goes to the network."""
    urls = [pollinations.upload(person), pollinations.upload(style)]
    if len(urls) != STYLE_IMAGES:
        raise RuntimeError(f"expected exactly {STYLE_IMAGES} links, got {len(urls)}")
    width, height = size
    return pollinations.compose(
        prompt, urls, out_path, model=model, width=int(width), height=int(height)
    )


def file_fact(path, what: str) -> tuple:
    """Run the cheap check before the expensive one: the file exists and is not empty."""
    p = Path(path)
    if not p.exists():
        return (what, FAIL, f"{p} is missing on disk")
    size = p.stat().st_size
    if size == 0:
        return (what, FAIL, f"{p} is empty (0 B)")
    return (what, PASS, f"{p} — {size} B")


INTAKE_TRIO = ("photo_intake", "style_intake", "driving_intake")


def _numbers_of(reply) -> str:
    """Return the neighbour's numbers next to its verdict. No numbers — say so."""
    if not isinstance(reply, dict):
        return ""
    if any(k not in reply for k in ("checked", "violations", "unmeasured")):
        return ""
    return (
        f"checked {reply['checked']}, violations {reply['violations']}, "
        f"unmeasured {reply['unmeasured']}; "
    )


def stage_intake(
    *, client_photo, style_ref, driving, intake=None, driving_frames=None, card_reader=None
) -> dict:
    """Check the three inputs are in place and the `fork_intake` neighbour accepted them."""
    checks = [
        file_fact(client_photo, "client photo"),
        file_fact(style_ref, "style reference"),
        file_fact(driving, "driving"),
    ]
    note = ""
    if intake is None:
        mod, why = soft_import("fork_intake")
        if mod is None:
            checks.append(("intake by the neighbour module", UNMEASURED, why))
            return _result(STAGES[0], checks, note=why)
        trio = [getattr(mod, n, None) for n in INTAKE_TRIO]
        if all(callable(f) for f in trio):
            photo, style, drive = trio
            # `callable` above rules None out; mypy cannot see through all().
            assert photo is not None and style is not None and drive is not None
            calls: tuple = (
                ("client photo intake", photo, (str(client_photo),), {}),
                (
                    "style reference intake",
                    style,
                    (str(style_ref),),
                    {} if card_reader is None else {"card_reader": card_reader},
                ),
                ("driving intake", drive, (str(driving), driving_frames), {}),
            )
            for name, fn, args, extra in calls:
                try:
                    reply = fn(*args, **extra)
                except Exception as exc:  # noqa: BLE001
                    checks.append((name, UNMEASURED, f"{type(exc).__name__}: {exc}"))
                    continue
                out, why = outcome_of(reply, what=f"fork_intake.{fn.__name__}")
                checks.append((name, out, _numbers_of(reply) + why))
            return _result(STAGES[0], checks, note="fork_intake: " + ", ".join(INTAKE_TRIO))
        intake, name, why = entry_point(mod, ("accept", "intake", "take", "check", "run"))
        if intake is None:
            checks.append(("intake by the neighbour module", UNMEASURED, why))
            return _result(STAGES[0], checks, note=why)
        note = f"fork_intake.{name}"
    try:
        reply = _call(
            intake,
            {
                "client_photo": str(client_photo),
                "style_ref": str(style_ref),
                "driving": str(driving),
            },
            (str(client_photo), str(style_ref), str(driving)),
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            ("intake by the neighbour module", UNMEASURED, f"{type(exc).__name__}: {exc}")
        )
        return _result(STAGES[0], checks, note='the neighbour crashed: this is not "fail"')
    out, why = outcome_of(reply, what="fork_intake")
    checks.append(("intake by the neighbour module", out, why))
    return _result(STAGES[0], checks, note=note or why)


def style_prompt(style_ref, *, card_reader=None) -> dict:
    """Build the stylization prompt: roles, style in words (when readable) and the brand ban."""
    from . import fork_style_prompt  # noqa: PLC0415

    card = fork_style_prompt.from_image(style_ref, reader=card_reader)
    words = card.get("prompt")
    parts = [ROLE_CLAUSE] + ([words] if words else []) + [NO_LOOK_TRANSFER_CLAUSE, NO_BRANDS_CLAUSE]
    return {
        "prompt": ", ".join(parts),
        "card_outcome": card.get("outcome"),
        "card_note": card.get("note"),
        "words": words,
    }


def _default_aesthetic():
    """Return the aesthetic neighbour, the one this stand calls when none is injected."""
    return fork_aesthetic


def _default_plan():
    """Return the plan neighbour. Same reasoning as above."""
    return fork_plan


def _size_pair(value):
    """Return `(width, height)` of whole positive pixels, or `None` when the value is not a size."""
    if isinstance(value, dict):
        value = (value.get("width"), value.get("height"))
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    try:
        width, height = int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def frame_size(path, *, sizer=None) -> tuple:
    """Read the pixel size of an image file.

    :param path: the image to measure.
    :param sizer: injection point returning `(width, height)`; PIL is used
        when it is omitted, so a test never needs a real decodable file.
    :returns: `((width, height) or None, note)` — the note says why the size
        is missing, because "not measured" has to be told apart from "wrong".

    >>> frame_size("x.png", sizer=lambda p: (720, 1280))[0]
    (720, 1280)
    """
    if sizer is None:

        def sizer(image_path):
            from PIL import Image  # noqa: PLC0415

            with Image.open(image_path) as im:
                return im.size

    try:
        raw = sizer(str(path))
    except Exception as exc:  # noqa: BLE001 - any reader failure is "not measured"
        return (None, f"the size of {path} was not taken: {type(exc).__name__}: {exc}")
    got = _size_pair(raw)
    if got is None:
        return (None, f"the size reader answered {raw!r}, which is not a pixel size")
    return (got, f"{got[0]}x{got[1]}")


def styliser_kept_the_plan(*, asked, got) -> dict:
    """Judge the styliser's answer against the size that was asked for.

    The name of this check promises a comparison with the request, so the
    request is compared — not the ratio band. A frame that is vertical, or
    even exactly 9:16, but is not the size that was ordered is still a route
    that ignored the order, and that fact must survive into the report on its
    own line.

    :param asked: the ordered size, `(width, height)` or a `{"width", "height"}` mapping.
    :param got: the returned size, in the same shapes; `None` when it was never measured.
    :returns: `outcome` plus `checked` / `violations` / `unmeasured`, the
        `asked` and `got` sizes as data, and a note carrying both numbers.

    >>> styliser_kept_the_plan(asked=(720, 1280), got=(768, 1376))["outcome"]
    'fail'
    """
    want = _size_pair(asked)
    have = _size_pair(got)
    if want is None:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "asked": None,
            "got": have,
            "note": f"the asked size is not a size: {asked!r}; nothing to compare against",
        }
    if have is None:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "asked": want,
            "got": None,
            "note": (
                f"asked for {want[0]}x{want[1]}, and the returned size was "
                f"never measured ({got!r}): NOT MEASURED, which is not a pass"
            ),
        }
    same = have == want
    return {
        "outcome": PASS if same else FAIL,
        "checked": 1,
        "violations": 0 if same else 1,
        "unmeasured": 0,
        "asked": want,
        "got": have,
        "note": (
            f"asked for {want[0]}x{want[1]} = {want[0] / want[1]:.4f}, "
            f"returned {have[0]}x{have[1]} = {have[0] / have[1]:.4f}"
            + (
                ""
                if same
                else "; the route answered with a size nobody ordered, so the "
                "frame is not the plan by construction"
            )
        ),
    }


def _default_cropper(source, out_path, box) -> None:
    """Cut the box out of the image and write it. Kept separate so a test never needs PIL."""
    from PIL import Image  # noqa: PLC0415

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as im:
        rgb = im.convert("RGB")
    left, top = int(box["left"]), int(box["top"])
    rgb.crop((left, top, left + int(box["width"]), top + int(box["height"]))).save(str(out_path))


def fit_frame_to_plan(src, dst, *, plan, sizer=None, cropper=None) -> dict:
    """Bring one frame onto the plan on disk, and say in numbers what that cost.

    The decision is the plan neighbour's (`fit_to_plan`); this only carries it
    out and reports it. Three outcomes: the frame is on the plan, the frame
    could not be brought there, or nothing could be measured at all.

    :param src: the frame as it arrived from the route.
    :param dst: where a trimmed or padded frame is written; an untouched frame stays at `src`.
    :param plan: the plan neighbour, injected so the stage can be tested without it.
    :param sizer: size reader, see `frame_size`.
    :param cropper: `(source, out_path, box)` writer; PIL is used when omitted.
    :returns: `action`, `path`, `arrived`, `shipped`, `trimmed_share` and the
        three-outcome numbers.

    >>> fit_frame_to_plan("a.png", "b.png", plan=None, sizer=lambda p: None)["outcome"]
    'unmeasured'
    """
    arrived, why = frame_size(src, sizer=sizer)
    base = {
        "action": "none",
        "path": str(src),
        "arrived": arrived,
        "shipped": None,
        "trimmed_share": 0.0,
    }
    if arrived is None:
        return {
            **base,
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{why}; the frame was neither judged nor repaired",
        }

    try:
        fit = plan.fit_to_plan(*arrived)
    except Exception as exc:  # noqa: BLE001
        return {
            **base,
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"arrived {arrived[0]}x{arrived[1]}; the plan neighbour could not "
                f"decide: {type(exc).__name__}: {exc}"
            ),
        }

    action = fit.get("action")
    shipped = _size_pair(fit)
    head = f"arrived {arrived[0]}x{arrived[1]} = {arrived[0] / arrived[1]:.4f}"

    if action == "none":
        return {
            **base,
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "shipped": arrived,
            "note": f"{head}; trimmed 0 px; leaving {arrived[0]}x{arrived[1]} untouched",
        }

    if action == "crop":
        cut = _default_cropper if cropper is None else cropper
        try:
            cut(str(src), str(dst), fit)
        except Exception as exc:  # noqa: BLE001
            return {
                **base,
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": (
                    f"{head}; the trim to {shipped} was decided but not carried out: "
                    f"{type(exc).__name__}: {exc}"
                ),
            }
        return {
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "action": "crop",
            "path": str(dst),
            "arrived": arrived,
            "shipped": shipped,
            "trimmed_share": fit.get("trimmed_share", 0.0),
            "note": (
                f"{head}; trimmed {fit.get('trimmed_share')} of one side; "
                f"leaving {shipped[0]}x{shipped[1]} = {shipped[0] / shipped[1]:.4f}"
            ),
        }

    # Too far from the plan to trim: `fit_to_plan` chose padding, which the plan
    # neighbour already knows how to write, bands and all.
    try:
        laid = plan.to_plan(str(src), str(dst))
    except Exception as exc:  # noqa: BLE001
        return {
            **base,
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{head}; the padding was not written: {type(exc).__name__}: {exc}",
        }
    padded = _size_pair(laid.get("plan") or {}) or shipped
    written = laid.get("outcome") == PASS
    return {
        # A padded frame is 9:16 by arithmetic and blurred bars by eye. The
        # owner's criterion, 2026-08-26, is 9:16 with no padding in 100% of
        # cases, so this is a violation and not a repair — it is written all
        # the same, because the outpaint downstream is what may still save it.
        "outcome": FAIL if written else laid.get("outcome", UNMEASURED),
        "checked": 1 if written else int(laid.get("checked", 0)),
        "violations": 1 if written else int(laid.get("violations", 0)),
        "unmeasured": 0 if written else int(laid.get("unmeasured", 1)),
        "action": "pad",
        "path": str(laid.get("path") or dst),
        "arrived": arrived,
        "shipped": padded,
        "trimmed_share": 0.0,
        "added_share": (laid.get("plan") or {}).get("added_share"),
        "note": (
            f"{head}; trimmed 0 px because a cut this deep would take the "
            f"subject; padded to {padded[0]}x{padded[1]} instead, "
            f"{(laid.get('plan') or {}).get('added_share')} of the area added "
            f"as bands — and a padded frame is a VIOLATION, not a repair: it "
            f"only reaches the plan if the outpaint below turns the bands into scene"
        ),
    }


#: CHOSEN, and chosen rather than measured: the cost of reading 24 poses has
#: never been timed, so this number is a judgement and may be moved. How many
#: driving frames the composition card is measured over. The card is a set of
#: medians with a measured spread, so it needs enough frames to have a middle,
#: and few enough that reading poses stays cheap next to the one paid call.
#: The frames are taken evenly across the whole directory rather than
#: from the front, which would describe the opening pose and call it the clip.
CARD_SAMPLE_FRAMES = 24


def _read_pose(path) -> dict:
    """Read the pose points of one image. The one reader every card and check uses."""
    from . import pose  # noqa: PLC0415

    return (pose.read_pose(str(path)) or {}).get("points") or {}


def driving_card(frames, *, pose=None, plan=None) -> dict:
    """Measure where the person stands on the driving, as a composition card.

    `frames` are the unpacked driving frames in order. Returns the reply of
    `fork_plan.composition_card`: medians and tolerances when the pose reads,
    "could not measure" when it does not — never a guessed card.

    Example:
        >>> card = driving_card(["000.png", "001.png"], pose=lambda p: {})
        >>> card["outcome"]
        'could not measure'
    """
    P = fork_plan if plan is None else plan
    if not frames:
        return {
            **P.tally(0, 0, 1),
            "note": (
                "the driving was not unpacked into frames: the composition "
                "card is NOT MEASURED and the framing is left to the template"
            ),
        }
    reader = _read_pose if pose is None else pose
    picked = list(frames)
    available = len(picked)
    step = max(1, available // CARD_SAMPLE_FRAMES)
    picked = picked[::step][:CARD_SAMPLE_FRAMES]
    poses, broke = [], []
    for frame in picked:
        try:
            poses.append(reader(str(frame)))
        except Exception as exc:  # noqa: BLE001
            broke.append(f"{type(exc).__name__}: {exc}")
    if not poses:
        return {
            **P.tally(0, 0, 1),
            "note": (
                f"the pose reader answered on none of the {len(picked)} "
                f"frames sampled from {available}: "
                # Every reason, not the first: the frames fail for different
                # causes, and the one that explains the run may be any of them.
                f"{'; '.join(broke) if broke else 'no reply'}"
            ),
        }
    got = P.composition_card(poses)
    if len(picked) < available:
        # `composition_card` counts the frames it was handed, and that is the
        # sample. Without both numbers a card read off 24 frames of 300 reads
        # as a card read off the clip.
        got = dict(got, note=f"{got['note']}; sampled {len(picked)} of {available} frames")
    if broke:
        got = dict(got, note=f"{got['note']}; {len(broke)} frames threw: {'; '.join(broke)}")
    return got


def _person_in_plan(image, *, plan, pose=None, card=None) -> tuple:
    """Check whether the person in the image fits the plan bands. Three outcomes."""
    if pose is None:
        pose = _read_pose

    try:
        points = pose(str(image))
    except Exception as exc:  # noqa: BLE001
        return (
            "person in plan",
            UNMEASURED,
            f"the pose was not captured: {type(exc).__name__}: {exc}",
        )
    # A card OBJECT is not a card: `driving_card` always answers, and its answer
    # is "could not measure" whenever the driving poses did not read. Branching
    # on existence would swap the plan bands for a check that can only say
    # "no card", which is how a run loses its person check without going red.
    if card and card.get("outcome") == PASS:
        got = plan.in_card(points, card)
        return ("person in the driving card", got["outcome"], str(got.get("note")))
    # The four bands are the plan's decision and `plan_verdict` is where it is
    # made. This function used to compare against `SHOULDERS_BAND` and its three
    # neighbours itself, which meant one plan judged in two implementations:
    # moving a band in `fork_plan` left this copy agreeing by coincidence, and
    # nothing would have gone red the day the coincidence ended. Only the person
    # axes are read — the canvas is checked by the caller and the face is not
    # measured on this image at all.
    axes = [a for a in plan.plan_verdict(points=points)["axes"] if a["name"] in plan.PERSON_AXES]
    unread = [str(a["note"]) for a in axes if a["unmeasured"]]
    if unread:
        # `axes[0]` is not the axis that failed to read: under a "could not
        # measure" verdict it handed back a note from an axis that had in fact
        # read, naming the wrong axis as the reason and hiding the others.
        return ("person in plan", UNMEASURED, "; ".join(unread))
    bad = [a["note"] for a in axes if a["violations"]]
    tail = "; ".join(a["note"] for a in axes)
    if bad:
        return (
            "person in plan",
            FAIL,
            "; ".join(bad) + ". Kling scales the character to the driving "
            "skeleton: a reference outside the plan will drift past the "
            "frame edge",
        )
    return ("person in plan", PASS, tail)


def stage_stylize(
    *,
    client_photo,
    style_ref,
    out_path,
    stylize=None,
    card_reader=None,
    prompt=None,
    aesthetic=None,
    client_gender=None,
    plan=None,
    aesthetic_mod=None,
    extend=None,
    pose=None,
    card=None,
    sizer=None,
    cropper=None,
    operator_ok_styliser_size: bool = False,
) -> dict:
    """Turn the client photo and the style reference into a styled photo on the plan."""
    A = _default_aesthetic() if aesthetic_mod is None else aesthetic_mod
    checks_pre = []
    # The card decides the framing clause in the prompt and which question the
    # person check asks, so the stage carries it as a fact rather than implying
    # it: a run framed by the driving and a run framed by the template produce
    # the same-looking output and are not the same run. It is reported and not
    # counted as an axis — the absence of a card is a narrower run, not a
    # defect of the stylization this stage is about.
    card_fact = {
        "outcome": (card or {}).get("outcome", UNMEASURED),
        "note": str((card or {}).get("note", "no composition card was built for this run")),
    }
    if aesthetic is not None:
        gender = A.gender_of(aesthetic)
        pair = A.pair_check(client_gender=client_gender, aesthetic_gender=gender)
        checks_pre.append(("client and template gender", pair["outcome"], pair["note"]))
        if pair["outcome"] != PASS:
            return _result(
                STAGES[1],
                checks_pre,
                driving_card=card_fact,
                note="gender mismatch: generation was not started",
            )
        style_ref = str(A.aesthetic_file(aesthetic))
        prompt = f"{A.compose(aesthetic, card=card)['prompt']}. {A.assemble_prompt(card=card)}"

    built = (
        {"prompt": prompt, "card_note": "prompt supplied externally"}
        if prompt is not None
        else style_prompt(style_ref, card_reader=card_reader)
    )
    prompt = built["prompt"]
    checks = list(checks_pre) + [
        (
            "brand ban in the prompt",
            PASS if NO_BRANDS_CLAUSE in prompt else FAIL,
            NO_BRANDS_CLAUSE
            if NO_BRANDS_CLAUSE in prompt
            else "the ban was removed from the prompt: brands will ride into the frame",
        )
    ]
    stylize = live_stylize if stylize is None else stylize
    t0 = time.perf_counter()
    try:
        got = stylize(
            person=str(client_photo), style=str(style_ref), prompt=prompt, out_path=str(out_path)
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("stylization", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(
            STAGES[1],
            checks,
            prompt=prompt,
            driving_card=card_fact,
            note="the styliser did not answer: nothing to measure",
        )
    checks.append(
        (
            "stylization",
            PASS,
            f"{STYLE_ROUTE}/{STYLE_MODEL}, {STYLE_IMAGES} images, "
            f"{round(time.perf_counter() - t0, 1)} s",
        )
    )
    checks.append(file_fact(got or out_path, "styled photo"))
    made = str(got or out_path)

    P = _default_plan() if plan is None else plan
    planned = Path(str(out_path)).with_name(Path(str(out_path)).stem + "_9x16.png")

    fitted = fit_frame_to_plan(made, planned, plan=P, sizer=sizer, cropper=cropper)

    # Two separate facts about the same frame, and they are never merged: what
    # the route was ordered to return, and what the frame is after the repair.
    # Folding the first into the second is exactly how 0.5581 shipped as "pass".
    kept = styliser_kept_the_plan(asked=STYLED_SIZE, got=fitted.get("arrived"))
    kept_outcome, kept_note = kept["outcome"], kept["note"]
    # The admission is offered ONLY on a frame that reached the plan cleanly,
    # which — since `fit_frame_to_plan` counts padding as a violation — means a
    # trimmed one. A frame padded with blurred bands is 9:16 by arithmetic and
    # a different photograph by eye: the 3:4 fossil goes down that branch and
    # stays red whatever the operator says.
    if kept_outcome == FAIL and fitted["outcome"] == PASS:
        repair = (
            f"; repaired by {fitted['action']} to {fitted['shipped'][0]}x{fitted['shipped'][1]}"
        )
        if operator_ok_styliser_size:
            kept_outcome = PASS
            kept_note += repair + ", and the OPERATOR ADMITTED that repaired frame by eye"
        else:
            kept_note += repair + (
                ", which is the plan — but the route still ignored the order, "
                "so the run stops here; pass --operator-ok-styliser-size once "
                "the repaired frame has been looked at"
            )
    checks.append(("styliser returned the plan", kept_outcome, kept_note))
    checks.append(("9:16 frame", fitted["outcome"], str(fitted.get("note"))))

    if fitted["outcome"] != UNMEASURED:
        # A padded frame is a violation and still a file: the outpaint below is
        # the only thing that can turn it back into the plan, so it runs.
        made = fitted["path"]

        if fitted["action"] != "pad":
            checks.append(
                (
                    "margin outpaint",
                    PASS,
                    f"not called: the frame reached the plan by '{fitted['action']}' "
                    f"({fitted['trimmed_share']} of one side trimmed), so nothing "
                    f"was padded. A call here would cost a generation and could "
                    f"repaint the person for no gain",
                )
            )
        else:
            added = fitted.get("added_share")
            grown = Path(made).with_name(Path(made).stem + "_full.png")
            ext = P.extend_to_plan(made, grown, extender=extend)
            checks.append(
                (
                    "margin outpaint",
                    ext["outcome"],
                    f"repairing a padded reference ({added} of the area added "
                    f"as bands); {str(ext.get('note'))}",
                )
            )
            if ext["outcome"] == PASS:
                # The outpainter answers on its own size grid too, so its own
                # answer goes through the same trim before anything is paid for.
                exact = Path(ext["path"]).with_name(Path(ext["path"]).stem + "_exact.png")
                refit = fit_frame_to_plan(ext["path"], exact, plan=P, sizer=sizer, cropper=cropper)
                checks.append(
                    ("9:16 frame after the outpaint", refit["outcome"], str(refit["note"]))
                )
                if refit["outcome"] == PASS:
                    made = refit["path"]

        shipped, why = frame_size(made, sizer=sizer)
        if shipped is None:
            checks.append(("frame going to the paid call", UNMEASURED, why))
        else:
            axis = P.ratio_axis(*shipped)
            checks.append(
                (
                    "frame going to the paid call",
                    axis["outcome"],
                    f"{Path(made).name} is {shipped[0]}x{shipped[1]}; {axis['note']}",
                )
            )

        checks.append(_person_in_plan(made, plan=P, pose=pose, card=card))

    return _result(
        STAGES[1],
        checks,
        styled=made,
        prompt=prompt,
        driving_card=card_fact,
        note=str(built["card_note"] or ""),
    )


def stage_style_acceptance(
    *, styled, style_ref, client_photo, operator_ok_identity=False, similarity=None, distances=None
) -> dict:
    """Check the style hit (against the floor) and that identity survived (against the bar)."""
    similarity = shipped_similarity if similarity is None else similarity
    checks, numbers = [], {}  # type: list, dict

    # A style verdict that does not name the device that produced it cannot be
    # compared with yesterday's, so the name is taken from each measurement that
    # ran. The two calls are named separately because a device can answer one
    # and drop out on the other, and averaging that away would hide a breakage.
    floor, floor_by = measured_by(similarity, style_ref, client_photo)
    hit, hit_by = measured_by(similarity, style_ref, styled)
    instrument = floor_by if floor_by == hit_by else f"floor by {floor_by}; hit by {hit_by}"
    numbers["style_instrument"] = instrument
    numbers["floor"] = floor
    numbers["hit"] = hit
    if floor is None or hit is None:
        checks.append(
            (
                "style hit",
                UNMEASURED,
                f"the style instrument gave no number: floor={floor}, "
                f"hit={hit}; measured by {instrument}",
            )
        )
    else:
        margin = round(hit - floor, 4)
        numbers["margin"] = margin
        ok = margin >= STYLE_MARGIN_MIN
        checks.append(
            (
                "style hit",
                PASS if ok else FAIL,
                f"hit {hit} with floor {floor} (floor = style against the "
                f"unstyled photo), margin {margin} with bar "
                f"{STYLE_MARGIN_MIN}; measured by {instrument}",
            )
        )

    distances = _default_distances() if distances is None else distances
    try:
        d = distances([str(styled)], str(client_photo))
    except Exception as exc:  # noqa: BLE001
        checks.append(("identity on the styled photo", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[2], checks, numbers=numbers)
    numbers["identity_median"] = d.get("median")
    numbers["identity_bar"] = SAME_PERSON_MAX
    if d.get("outcome") == UNMEASURED:
        checks.append(("identity on the styled photo", UNMEASURED, str(d.get("note"))))
    else:
        med = d.get("median")
        if med is None:
            checks.append(
                ("identity on the styled photo", UNMEASURED, "no median: nothing to judge by")
            )
        elif med <= SAME_PERSON_MAX:
            checks.append(
                (
                    "identity on the styled photo",
                    PASS,
                    f"median {med} with bar {SAME_PERSON_MAX} "
                    f"(ladder: {LADDER_SAME} same, "
                    f"{LADDER_REJECTED} other, {LADDER_STRANGER} stranger)",
                )
            )
        elif med < LADDER_REJECTED:
            band = (
                f"median {med} between the bar {SAME_PERSON_MAX} and the "
                f'"other person" rung {LADDER_REJECTED}: the face is partially '
                f"occluded or altered by an accessory — ArcFace is not the judge here"
            )
            if operator_ok_identity:
                checks.append(
                    (
                        "identity on the styled photo",
                        PASS,
                        band + "; admitted by the operator via an explicit flag",
                    )
                )
            else:
                checks.append(
                    (
                        "identity on the styled photo",
                        UNMEASURED,
                        band + ", the operator judges by eye",
                    )
                )
        else:
            checks.append(
                (
                    "identity on the styled photo",
                    FAIL,
                    f'median {med} above the "other person" rung '
                    f"{LADDER_REJECTED}: this is an identity swap, not an "
                    f"accessory (ladder: {LADDER_SAME} same, "
                    f"{LADDER_STRANGER} stranger)",
                )
            )
    return _result(STAGES[2], checks, numbers=numbers)


def _default_distances():
    from . import fork_identity  # noqa: PLC0415

    return fork_identity.distances


def cut_argv(src, dst, *, first: int, last: int, fps: float, exe: str) -> list:
    """Build the cut command: start by time, length in frames."""
    return [
        exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{first / fps:.6f}",
        "-i",
        str(src),
        "-frames:v",
        str(last - first + 1),
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(dst),
    ]


def _decoded_frames(path, exe: str):
    out = subprocess.run(
        [exe, "-hide_banner", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    for row in reversed(out.stderr.splitlines()):
        if "frame=" in row:
            try:
                return int(row.split("frame=")[1].split()[0])
            except (IndexError, ValueError):
                return None
    return None


def stage_window(*, driving, first: int, last: int, out_path, probe=None, cutter=None) -> dict:
    """Pick the window by frame numbers, check its length and cut with a frame recount."""
    checks: list = []
    numbers: dict = {"first": first, "last": last}
    probe = _default_probe() if probe is None else probe
    info = probe(str(driving))
    fps = info.get("fps")
    total = info.get("frames")
    numbers["fps"] = fps
    numbers["source_frames"] = total
    if not fps or not total:
        checks.append(("driving probe", UNMEASURED, str(info.get("note"))))
        return _result(STAGES[3], checks, numbers=numbers)
    checks.append(("driving probe", PASS, str(info.get("note"))))

    want = last - first + 1
    numbers["want_frames"] = want
    inside = 0 <= first <= last < total
    checks.append(
        (
            "window inside the driving",
            PASS if inside else FAIL,
            f"frames {first}..{last} with {total} frames in the clip",
        )
    )
    seconds = round(want / fps, 3)
    numbers["seconds"] = seconds
    long_enough = seconds >= MIN_SCENE_S
    checks.append(
        (
            "scene not shorter than the threshold",
            PASS if long_enough else FAIL,
            f"{seconds} s with threshold {MIN_SCENE_S} s (Kling gate: "
            f'"Video duration can not less than 3s")',
        )
    )
    if not (inside and long_enough):
        return _result(STAGES[3], checks, numbers=numbers)

    if cutter is None:
        import shutil  # noqa: PLC0415

        exe = shutil.which("ffmpeg")
        if not exe:
            checks.append(("cut", UNMEASURED, "ffmpeg not found: nothing to cut with"))
            return _result(STAGES[3], checks, numbers=numbers)

        def cutter(src, dst, first=first, last=last, fps=fps, exe=exe):
            run = subprocess.run(
                cut_argv(src, dst, first=first, last=last, fps=fps, exe=exe),
                capture_output=True,
                text=True,
            )
            if run.returncode != 0:
                # Whole, not a tail: ffmpeg names the offending option in the
                # banner at the front and the failure near the end, and a cut
                # that did not happen leaves no other account of why.
                raise RuntimeError(f"ffmpeg returned {run.returncode}: {run.stderr}")
            return {"path": str(dst), "frames": _decoded_frames(dst, exe)}

    try:
        got = cutter(str(driving), str(out_path))
    except Exception as exc:  # noqa: BLE001
        checks.append(("cut", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[3], checks, numbers=numbers)
    got = got if isinstance(got, dict) else {"path": str(out_path), "frames": None}
    numbers["cut_frames"] = got.get("frames")
    if got.get("frames") is None:
        checks.append(
            (
                "frames in the piece",
                UNMEASURED,
                "could not recount the frames: the cut is not confirmed",
            )
        )
    else:
        checks.append(
            (
                "frames in the piece",
                PASS if got["frames"] == want else FAIL,
                f"{got['frames']} with {want} ordered",
            )
        )
    checks.append(file_fact(got.get("path") or out_path, "driving piece"))
    return _result(STAGES[3], checks, numbers=numbers, window=str(got.get("path") or out_path))


def _default_probe():
    from . import fork_video  # noqa: PLC0415

    return fork_video.probe


def kling_payload(
    *, video_url: str, image_url: str, character_orientation: str = CHARACTER_ORIENTATION
) -> dict:
    """Build exactly three fields and not one more. The orientation value comes from the measured ones."""
    if character_orientation not in KLING_ORIENTATIONS:
        raise ValueError(
            f"character_orientation={character_orientation!r}: the "
            f"endpoint has exactly {list(KLING_ORIENTATIONS)} "
            f"(MEASURED with a probe)"
        )
    return {
        "video_url": video_url,
        "image_url": image_url,
        "character_orientation": character_orientation,
    }


def _window_seconds(window, *, prober=None) -> float | None:
    """Return the driving piece length in seconds, or None. No guess is substituted."""
    prober = _default_probe() if prober is None else prober
    try:
        info = prober(str(window))
    except Exception:  # noqa: BLE001
        return None
    frames, fps = info.get("frames"), info.get("fps")
    if not frames or not fps:
        return None
    return round(frames / fps, 3)


def stage_kling(
    *,
    styled,
    window,
    out_path,
    upload=None,
    kling=None,
    probe=None,
    endpoint: str = KLING_ENDPOINT,
    orientation: str = CHARACTER_ORIENTATION,
) -> dict:
    """Run two uploads and one paid call. Any refusal is "could not measure", not "fail"."""
    seconds = _window_seconds(window, prober=probe)
    price = KLING_PRICE_USD if seconds is None else kling_price(seconds)
    checks, numbers = [], {"endpoint": endpoint, "price_usd": price, "seconds": seconds}
    try:
        refuse_pro(endpoint)
        checks.append(("pro guard", PASS, f"{endpoint}: no {list(FORBIDDEN_TIERS)} tiers"))
    except ValueError as exc:
        checks.append(("pro guard", FAIL, str(exc)))
        return _result(STAGES[4], checks, numbers=numbers)

    upload = live_upload if upload is None else upload
    kling = live_kling if kling is None else kling
    try:
        video_url = upload(str(window))
        image_url = upload(str(styled))
    except Exception as exc:  # noqa: BLE001
        checks.append(("input upload", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(
            STAGES[4],
            checks,
            numbers=numbers,
            note="the inputs did not go out: no order was made, no money spent",
        )
    checks.append(("input upload", PASS, "video_url and image_url received"))

    try:
        payload = kling_payload(
            video_url=video_url, image_url=image_url, character_orientation=orientation
        )
    except ValueError as exc:
        checks.append(("request composition", FAIL, str(exc)))
        return _result(STAGES[4], checks, numbers=numbers)
    extra = sorted(set(payload) - set(KLING_FIELDS))
    missing = sorted(set(KLING_FIELDS) - set(payload))
    checks.append(
        (
            "request composition",
            PASS if not (extra or missing) else FAIL,
            f"fields {sorted(payload)} against the measured {sorted(KLING_FIELDS)}"
            + (f", extra {extra}" if extra else "")
            + (f", missing {missing}" if missing else ""),
        )
    )
    if extra or missing:
        return _result(STAGES[4], checks, numbers=numbers)

    t0 = time.perf_counter()
    try:
        got = kling(
            video_url=payload["video_url"],
            image_url=payload["image_url"],
            character_orientation=payload["character_orientation"],
            out_path=str(out_path),
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("Kling call", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(
            STAGES[4], checks, numbers=numbers, note="the order did not happen: nothing to measure"
        )
    spent = round(time.perf_counter() - t0, 1)
    numbers["latency_s"] = spent
    lo, hi = KLING_LATENCY_S
    checks.append(("Kling call", PASS, f"{spent} s (measured band {lo}..{hi} s), ${price}"))
    checks.append(file_fact(got or out_path, "Kling output"))
    return _result(STAGES[4], checks, numbers=numbers, produced=str(got or out_path))


def stage_output_acceptance(
    *,
    produced,
    client_photo,
    frames_dir,
    probe=None,
    decode=None,
    distances=None,
    cuts=None,
    operator_ok_identity=False,
) -> dict:
    """Check geometry, identity and editorial cuts on the Kling output."""
    checks, numbers = [], {}  # type: list, dict
    probe = _default_probe() if probe is None else probe
    info = probe(str(produced))
    numbers["width"] = info.get("width")
    numbers["height"] = info.get("height")
    numbers["fps"] = info.get("fps")
    numbers["frames"] = info.get("frames")
    if not info.get("width"):
        checks.append(("output geometry", UNMEASURED, str(info.get("note"))))
    else:
        w, h = info.get("width"), info.get("height")
        ratio = w / h
        numbers["ratio"] = round(ratio, 4)
        known = (w, h) == KLING_OUT_SIZE
        fps_ok = info.get("fps") == KLING_OUT_FPS
        if ratio > OUT_RATIO_MAX:
            checks.append(
                (
                    "output geometry",
                    FAIL,
                    f"{w}x{h}, ratio {ratio:.4f} > "
                    f"{OUT_RATIO_MAX}: landscape, a defect for a vertical "
                    f"product",
                )
            )
        elif ratio < OUT_RATIO_MIN:
            checks.append(
                (
                    "output geometry",
                    FAIL,
                    f"{w}x{h}, ratio {ratio:.4f} < "
                    f"{OUT_RATIO_MIN}: narrower than the plan by more than the "
                    f"crop may take, a defect for a vertical product",
                )
            )
        elif not fps_ok:
            checks.append(
                (
                    "output geometry",
                    UNMEASURED,
                    f"{w}x{h} at {info.get('fps')} fps instead of "
                    f"{KLING_OUT_FPS}: wrong frame rate, the audio assembly "
                    f"counts frames at 30 — nothing to judge by",
                )
            )
        else:
            was = (
                "as on previous orders"
                if known
                else (
                    f"new geometry, the previous eight gave {KLING_OUT_SIZE[0]}x{KLING_OUT_SIZE[1]}"
                )
            )
            checks.append(
                (
                    "output geometry",
                    PASS,
                    f"{w}x{h}, ratio {ratio:.4f} inside the band "
                    f"[{OUT_RATIO_MIN}; {OUT_RATIO_MAX}] — vertical or square; {was}",
                )
            )

    decode = _default_decode() if decode is None else decode
    try:
        got = decode(str(produced), str(frames_dir))
    except Exception as exc:  # noqa: BLE001
        checks.append(("frame layout", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[5], checks, numbers=numbers)
    paths = list(got.get("paths") or [])
    numbers["decoded"] = len(paths)
    if not paths:
        checks.append(("frame layout", UNMEASURED, f"no frames came out: {str(got.get('note'))}"))
        return _result(STAGES[5], checks, numbers=numbers)
    checks.append(("frame layout", PASS, f"frames {len(paths)}"))

    distances = _default_distances() if distances is None else distances
    try:
        d = distances(paths, str(client_photo))
    except Exception as exc:  # noqa: BLE001
        d = {"outcome": UNMEASURED, "note": f"{type(exc).__name__}: {exc}"}
    numbers["identity_median"] = d.get("median")
    numbers["identity_inside"] = d.get("inside")
    numbers["identity_judged"] = d.get("judged")
    if d.get("outcome") == UNMEASURED:
        checks.append(("identity on the output", UNMEASURED, str(d.get("note"))))
    else:
        med = d.get("median")
        tail = (
            f"inside the bar {d.get('inside')} of {d.get('judged')} judged "
            f"(ladder: {LADDER_SAME} same, {LADDER_REJECTED} other, "
            f"{LADDER_STRANGER} stranger)"
        )
        if med is None:
            checks.append(("identity on the output", UNMEASURED, "no median: nothing to judge by"))
        elif med <= SAME_PERSON_MAX:
            checks.append(
                (
                    "identity on the output",
                    PASS,
                    f"median {med} with bar {SAME_PERSON_MAX}, {tail}",
                )
            )
        elif med < LADDER_REJECTED:
            band = (
                f"median {med} between the bar {SAME_PERSON_MAX} and the "
                f'"other person" rung {LADDER_REJECTED}: the face is partially '
                f"occluded, ArcFace is not the judge here; {tail}"
            )
            if operator_ok_identity:
                checks.append(
                    (
                        "identity on the output",
                        PASS,
                        band + "; admitted by the operator via an explicit flag",
                    )
                )
            else:
                checks.append(
                    ("identity on the output", UNMEASURED, band + ", the operator judges by eye")
                )
        else:
            checks.append(
                (
                    "identity on the output",
                    FAIL,
                    f'median {med} above the "other person" rung '
                    f"{LADDER_REJECTED}: an identity swap; {tail}",
                )
            )

    cuts = _default_cuts() if cuts is None else cuts
    try:
        c = cuts(paths)
    except Exception as exc:  # noqa: BLE001
        c = {"outcome": UNMEASURED, "note": f"{type(exc).__name__}: {exc}"}
    numbers["cuts"] = None if c.get("outcome") == UNMEASURED else len(c.get("cuts") or [])
    if c.get("outcome") == UNMEASURED:
        checks.append(("editorial cuts", UNMEASURED, str(c.get("note"))))
    else:
        found = len(c.get("cuts") or [])
        checks.append(
            (
                "editorial cuts",
                PASS if found <= MAX_CUTS_OUT else FAIL,
                f"cuts {found} with allowance {MAX_CUTS_OUT}; {str(c.get('note'))}",
            )
        )
    return _result(STAGES[5], checks, numbers=numbers)


def _default_decode():
    from . import fork_video  # noqa: PLC0415

    def decode(video, out_dir):
        return fork_video.frames(video, out_dir, overwrite=True)

    return decode


def _default_cuts():
    from . import motion  # noqa: PLC0415

    return motion.cuts


def stage_finish(*, produced, driving, out_path, window=None, finish=None) -> dict:
    """Crop to 9:16 and return the audio. Lives in `fork_finish`, called softly."""
    checks = []
    note = ""
    if finish is None:
        mod, why = soft_import("fork_finish")
        if mod is None:
            checks.append(("final assembly", UNMEASURED, why))
            return _result(STAGES[6], checks, note=why)
        finish, name, why = entry_point(mod, ("finish", "assemble", "build", "compose", "run"))
        if finish is None:
            checks.append(("final assembly", UNMEASURED, why))
            return _result(STAGES[6], checks, note=why)
        note = f"fork_finish.{name}"
    try:
        reply = _call(
            finish,
            {
                "driving_path": str(driving),
                "kling_path": str(produced),
                "out_path": str(out_path),
                "window": window,
            },
            (str(driving), str(produced), str(out_path)),
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("final assembly", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[6], checks, note='the neighbour crashed: this is not "fail"')
    out, why = outcome_of(reply, what="fork_finish")
    checks.append(("final assembly", out, why))
    if out == PASS:
        target = (reply.get("path") if isinstance(reply, dict) else None) or out_path
        checks.append(file_fact(target, "final clip"))
    return _result(STAGES[6], checks, note=note or why)


def stage_report(stages: list, *, out_path=None) -> dict:
    """Summarize the stages. A partial result is numbers, not a flag."""
    checked = sum(s["checked"] for s in stages)
    violations = sum(s["violations"] for s in stages)
    unmeasured = sum(s["unmeasured"] for s in stages)
    done = sum(1 for s in stages if s["outcome"] == PASS)
    checks = [
        (
            "stage summary",
            PASS,
            f"stages passed {done} of {len(STAGES) - 1} before the report; "
            f"checks {checked}, violations {violations}, "
            f"unmeasured {unmeasured}",
        )
    ]
    if out_path is not None:
        try:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(
                json.dumps(
                    {
                        "stages": stages,
                        "checked": checked,
                        "violations": violations,
                        "unmeasured": unmeasured,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            checks.append(("report to disk", PASS, str(out_path)))
        except OSError as exc:
            checks.append(("report to disk", UNMEASURED, f"{type(exc).__name__}: {exc}"))
    return _result(
        STAGES[7],
        checks,
        totals={
            "checked": checked,
            "violations": violations,
            "unmeasured": unmeasured,
            "stages_passed": done,
        },
    )


def run(
    *,
    client_photo,
    style_ref,
    driving,
    first: int,
    last: int,
    out_dir="work/e2e",
    intake=None,
    stylize=None,
    similarity=None,
    distances=None,
    probe=None,
    cutter=None,
    decode=None,
    cuts=None,
    upload=None,
    kling=None,
    finish=None,
    card_reader=None,
    driving_frames=None,
    operator_ok_identity: bool = False,
    operator_ok_styliser_size: bool = False,
    aesthetic=None,
    client_gender=None,
    plan=None,
    sizer=None,
    cropper=None,
    aesthetic_mod=None,
    extend=None,
    pose=None,
    card=None,
    orientation: str = CHARACTER_ORIENTATION,
    endpoint: str = KLING_ENDPOINT,
    log=None,
) -> dict:
    """Walk the whole path stage by stage. Print each one immediately and stop at the first "fail"."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    say(
        f"stand: {len(STAGES)} stages, stop at the first '{FAIL}'; "
        f"exactly one paid call (${KLING_PRICE_USD} for "
        f"{PRODUCT_SECONDS:g} s, {KLING_PRICE_PER_SECOND_USD}/s)",
        log=log,
    )

    styled = out / "styled.png"
    window = out / "window.mp4"
    produced = out / "kling_out.mp4"
    final = out / "final_9x16.mp4"

    stages, stopped = [], None

    def step(fn):
        nonlocal stopped
        t0 = time.perf_counter()
        res = fn()
        res["elapsed"] = round(time.perf_counter() - t0, 2)
        stages.append(res)
        say(line(res) + f" | {res['elapsed']} s", log=log)
        for c in res["checks"]:
            say(f"      · {c['name']}: {c['outcome']} — {c['note']}", log=log)
        if res["outcome"] != PASS and stopped is None:
            stopped = res
        return res

    r1 = step(
        lambda: stage_intake(
            client_photo=client_photo,
            style_ref=style_ref,
            driving=driving,
            intake=intake,
            driving_frames=driving_frames,
            card_reader=card_reader,
        )
    )
    if r1["outcome"] == PASS:
        # Nothing in the shipped run used to produce this card, so `framing_clause`
        # and `in_card` — both already wired to consume it — were dead in every
        # run that did not hand one in by hand. The driving is the only thing that
        # knows where the person stands, and it is on disk by now, so the card is
        # measured from it rather than left for an operator to remember.
        if card is None:
            card = driving_card(driving_frames, pose=pose, plan=plan)
            say(f"      · driving card: {card['outcome']} — {card['note']}", log=log)
        r2 = step(
            lambda: stage_stylize(
                client_photo=client_photo,
                style_ref=style_ref,
                out_path=styled,
                stylize=stylize,
                card_reader=card_reader,
                aesthetic=aesthetic,
                client_gender=client_gender,
                plan=plan,
                aesthetic_mod=aesthetic_mod,
                extend=extend,
                pose=pose,
                card=card,
                sizer=sizer,
                cropper=cropper,
                operator_ok_styliser_size=operator_ok_styliser_size,
            )
        )
        if r2["outcome"] == PASS:
            r3 = step(
                lambda: stage_style_acceptance(
                    styled=r2.get("styled", styled),
                    style_ref=style_ref,
                    client_photo=client_photo,
                    similarity=similarity,
                    distances=distances,
                    operator_ok_identity=operator_ok_identity,
                )
            )
            if r3["outcome"] == PASS:
                r4 = step(
                    lambda: stage_window(
                        driving=driving,
                        first=first,
                        last=last,
                        out_path=window,
                        probe=probe,
                        cutter=cutter,
                    )
                )
                if r4["outcome"] == PASS:
                    r5 = step(
                        lambda: stage_kling(
                            styled=r2.get("styled", styled),
                            window=r4.get("window", window),
                            out_path=produced,
                            upload=upload,
                            kling=kling,
                            probe=probe,
                            endpoint=endpoint,
                            orientation=orientation,
                        )
                    )
                    if r5["outcome"] == PASS:
                        r6 = step(
                            lambda: stage_output_acceptance(
                                produced=r5.get("produced", produced),
                                client_photo=client_photo,
                                frames_dir=out / "out_frames",
                                probe=probe,
                                decode=decode,
                                distances=distances,
                                cuts=cuts,
                                operator_ok_identity=operator_ok_identity,
                            )
                        )
                        if r6["outcome"] != FAIL:
                            step(
                                lambda: stage_finish(
                                    produced=r5.get("produced", produced),
                                    driving=driving,
                                    out_path=final,
                                    window=(first, last),
                                    finish=finish,
                                )
                            )

    report = stage_report(stages, out_path=out / "e2e_report.json")
    stages_before_report = list(stages)
    stages.append(report)
    say(line(report), log=log)

    outcome = stopped["outcome"] if stopped is not None else report["outcome"]
    where = f"{stopped['stage']}" if stopped is not None else "all stages"
    totals = report["totals"]
    say(
        f"TOTAL: {outcome} at stage '{where}' | stages passed "
        f"{totals['stages_passed']} of {len(STAGES) - 1} | checks "
        f"{totals['checked']}, violations {totals['violations']}, unmeasured "
        f"{totals['unmeasured']}",
        log=log,
    )
    return {
        "outcome": outcome,
        "stopped_at": where,
        "stopped_index": (stages_before_report.index(stopped) + 1 if stopped is not None else None),
        "stages": stages,
        "totals": totals,
        "exit_code": EXIT_BY_OUTCOME[outcome],
        "report": str(out / "e2e_report.json"),
    }


def parse_window(text: str) -> tuple:
    """Parse `first:last` into a pair of numbers. Garbage raises, it is not guessed away."""
    parts = str(text).split(":")
    if len(parts) != 2 or not all(p.strip().lstrip("-").isdigit() for p in parts):
        raise ValueError(f"window {text!r} is not of the form 'first:last', for example 100:199")
    first, last = int(parts[0]), int(parts[1])
    if first > last:
        raise ValueError(f"window {text!r}: the first frame is after the last")
    return first, last


def frame_paths(directory) -> list | None:
    """Return the directory frames in order. An empty directory raises rather than staying silent."""
    if directory is None:
        return None
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"frames directory {directory!r} does not exist")
    got = sorted(str(p) for p in root.iterdir() if p.suffix.lower() in FRAME_SUFFIXES)
    if not got:
        raise ValueError(
            f"frames directory {directory!r} is empty: expected files "
            f"{', '.join(sorted(FRAME_SUFFIXES))}"
        )
    return got


def main(argv=None) -> int:
    """Parse the arguments and call `run` from a thin entry point."""
    import argparse  # noqa: PLC0415

    ap = argparse.ArgumentParser(description="end-to-end product stand")
    ap.add_argument("--client", required=True)
    ap.add_argument("--style", default=None, help="style reference; not needed with --aesthetic")
    ap.add_argument("--driving", required=True)
    ap.add_argument("--window", required=True, help="first:last, e.g. 100:199")
    ap.add_argument("--out", default="work/e2e")
    ap.add_argument(
        "--aesthetic", default=None, help="aesthetic name from assets/fork_aesthetics.json"
    )
    ap.add_argument(
        "--client-gender",
        default=None,
        choices=("m", "f"),
        help="client gender; required together with --aesthetic",
    )
    ap.add_argument("--frames", default=None, help="directory with already unpacked driving frames")
    ap.add_argument(
        "--operator-ok-identity",
        action="store_true",
        help="the operator looked by eye and admitted the identity",
    )
    ap.add_argument(
        "--operator-ok-styliser-size",
        action="store_true",
        help=(
            "the operator looked by eye and admitted the frame the route "
            "returned off the asked size and we trimmed back onto the plan"
        ),
    )
    a = ap.parse_args(argv)
    if a.aesthetic is None and a.style is None:
        ap.error("either --style or --aesthetic is required")
    if a.aesthetic is not None and a.client_gender is None:
        ap.error("--aesthetic requires --client-gender")
    first, last = parse_window(a.window)
    got = run(
        client_photo=a.client,
        style_ref=a.style,
        driving=a.driving,
        first=first,
        last=last,
        out_dir=a.out,
        driving_frames=frame_paths(a.frames),
        aesthetic=a.aesthetic,
        client_gender=a.client_gender,
        operator_ok_identity=a.operator_ok_identity,
        operator_ok_styliser_size=a.operator_ok_styliser_size,
    )
    return got["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
