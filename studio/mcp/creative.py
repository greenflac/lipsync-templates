"""Analyse a creative the owner dropped in by hand: what it looks like, what moves.

WHY THE CHAT AGENT NEEDED THIS

The studio product already accepts an upload and runs the engine's own
acceptance on it (`studio/app.py` -> `lipsync.fork_intake.photo_intake`). The
chat agent had nothing: eleven tools and not one of them took a file. So the
owner could ask "write me a prompt" but not "here is a creative I like, what is
it doing" — which is the question that comes first in real work.

WHAT IT REPORTS, AND WHAT IT REFUSES TO GUESS

The look is reported in the SAME vocabulary `studio/style.py` uses to build a
prompt — `PALETTE_WORDS`, `LIGHT_WORDS` — imported from there, never restated,
so an answer here can be handed straight to `write_lipsync_prompt`.

But only two of that module's four axes are honestly readable off pixels:

    palette    measurable   the dominant colours, named against the allow-list
    saturation measurable   the mean chroma decides it outright: the prompt
                            card's three buckets cover the whole range, so
                            unlike lighting there is no honest "neither"
    light      partly       high-key and low-key follow from the luminance
                            histogram. `golden-hour`, `neon`, `backlit` and the
                            rest do NOT, and are never named from a number
    texture   partly        grain is a real high-frequency statistic and it is
                            REPORTED as a number; no word is claimed from it
    mood      no            nothing in a histogram says `melancholic`. This
                            axis is always `could not measure`

That last line is the whole discipline. A mood word guessed from brightness
would be indistinguishable, in the output, from one somebody measured — and
this package has already paid for a metric that returned confident numbers
while measuring nothing.

WHAT RUNS HERE, MEASURED 2026-08-27

`numpy` and `Pillow` are present, so the look measurements and the engine's
`motion` instruments run. `insightface`, `mediapipe` and `ffmpeg` are NOT, so
every face axis, every pose axis and any mp4 decoding cannot run at all. Those
come back as `could not measure` with the missing dependency NAMED, and they
are counted in `unmeasured` — never quietly skipped, because zero violations
out of zero checks is not a clean creative.

The engine's modules are imported, never reimplemented, and never edited:
`lipsync/**` is frozen by `studio/CONTRACTS.md`.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.mcp.lipsync_prompt import SATURATION_CUES
from studio.style import LIGHT_WORDS, PALETTE_WORDS

__all__ = [
    "DOMINANT_COLOURS",
    "GRAIN_SAMPLE",
    "HIGH_KEY_MEAN",
    "LOW_KEY_MEAN",
    "MUTED_CHROMA",
    "NAMED_COLOURS",
    "SATURATED_CHROMA",
    "analyse",
    "look",
    "motion_of",
]

#: CHOSEN by me, 2026-08-27, not measured and not taken from anywhere: an RGB
#: anchor for each of `style.PALETTE_WORDS`, so a dominant colour can be given
#: the name the prompt writer already understands. They are eyeballed sRGB
#: values for the twelve words, and a different reader would pick slightly
#: different ones — which is exactly why this says CHOSEN. What must NOT drift
#: is the KEY SET: it is asserted against `PALETTE_WORDS` at import, because a
#: word added there and forgotten here would silently become unnameable.
NAMED_COLOURS: dict[str, tuple[int, int, int]] = {
    "amber": (255, 176, 0),
    "charcoal": (54, 57, 61),
    "copper": (184, 115, 51),
    "crimson": (220, 20, 60),
    "emerald": (0, 155, 119),
    "gold": (212, 175, 55),
    "indigo": (75, 0, 130),
    "ivory": (255, 250, 232),
    "rose": (226, 136, 152),
    "sand": (214, 190, 148),
    "slate": (112, 128, 144),
    "teal": (0, 128, 128),
}

# One knowledge, one place. If `style.py` grows a palette word, this fails at
# import rather than quietly naming twelve of thirteen colours.
_MISSING = set(PALETTE_WORDS) - set(NAMED_COLOURS)
if _MISSING:  # pragma: no cover - a guard against a future edit, not a branch
    raise AssertionError(f"no RGB anchor for palette word(s): {sorted(_MISSING)}")

#: How many dominant colours to name. CHOSEN: three is what a `StyleSpec`
#: palette holds, so naming more would produce an answer nobody can use.
DOMINANT_COLOURS = 3

#: CHOSEN, on a 0-255 luminance mean. High-key and low-key are the two lighting
#: words a histogram can actually carry: an image whose light sits high is
#: high-key, one whose light sits low is low-key, and everything between is
#: NEITHER — reported as no lighting word rather than as the nearer of the two.
#: A mid-grey frame must come back unnamed, and there is a test that says so;
#: without it this would name a lighting word for every image ever passed in,
#: which is how an instrument comes to measure nothing.
HIGH_KEY_MEAN = 170.0
LOW_KEY_MEAN = 85.0

#: CHOSEN, on mean chroma (max channel minus min, 0-255). Three buckets,
#: matching `lipsync_prompt.SATURATION_CUES`, whose keys are imported rather
#: than restated. Greyscale is 0 and a pure primary is 255, so unlike the
#: lighting bars these cover the range and every image gets a word — which is
#: only safe because the control is three-point: a grey frame must come back
#: `muted`, a primary `saturated`, and something between `moderate`. An
#: instrument that always answers needs both ends pinned, not just one.
MUTED_CHROMA = 40.0
SATURATED_CHROMA = 120.0

#: The longest side an image is reduced to before the statistics are taken.
#: CHOSEN for speed; the measurements are means and ratios, which survive it.
#: Grain is measured on the FULL image instead — resampling is exactly what
#: destroys high-frequency detail, so measuring grain on a thumbnail would
#: return the resampler's smoothness rather than the creative's.
SAMPLE_SIDE = 256
GRAIN_SAMPLE = 512


def _house(outcome: str, checked: int, violations: int, unmeasured: int, note: str) -> dict:
    return {
        "outcome": outcome,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
        "note": note,
    }


def _nearest_word(rgb: Sequence[float]) -> str:
    """The palette word closest to one colour, by plain RGB distance."""
    r, g, b = (float(rgb[0]), float(rgb[1]), float(rgb[2]))
    best = ""
    best_d = float("inf")
    for word, (wr, wg, wb) in NAMED_COLOURS.items():
        d = (r - wr) ** 2 + (g - wg) ** 2 + (b - wb) ** 2
        if d < best_d:
            best_d, best = d, word
    return best


def look(path: str | Path) -> dict:
    """What one still frame looks like, in the prompt writer's own vocabulary.

    Three outcomes. A file that cannot be opened is `could not measure` and
    names the reason — it is not a creative that failed a check.

    :returns: the house dict plus `palette` (up to `DOMINANT_COLOURS` words),
        `light` (a word, or "" when the histogram supports neither), `mood`
        (always None — see the module docstring), and the raw numbers the
        words came from, so a reader can disagree with the naming.
    """
    target = Path(str(path))
    if not target.is_file():
        return {
            **_house(UNMEASURED, 0, 0, 1, f"{target} is not a file, so nothing was opened"),
            "palette": [],
            "light": "",
            "saturation": "",
            "mood": None,
            "measurements": {},
        }
    try:
        import numpy as np
        from PIL import Image
    except ImportError as error:  # pragma: no cover - both are pinned
        return {
            **_house(UNMEASURED, 0, 0, 1, f"nothing to measure with: {error}"),
            "palette": [],
            "light": "",
            "saturation": "",
            "mood": None,
            "measurements": {},
        }

    try:
        with Image.open(target) as handle:
            full = handle.convert("RGB")
            width, height = full.size
            grain_source = full.copy()
            grain_source.thumbnail((GRAIN_SAMPLE, GRAIN_SAMPLE), Image.Resampling.LANCZOS)
            small = full.copy()
            small.thumbnail((SAMPLE_SIDE, SAMPLE_SIDE), Image.Resampling.LANCZOS)
    except Exception as error:  # noqa: BLE001 - any unreadable file is one answer
        return {
            **_house(
                UNMEASURED, 0, 0, 1, f"{target.name} could not be decoded as an image: {error}"
            ),
            "palette": [],
            "light": "",
            "saturation": "",
            "mood": None,
            "measurements": {},
        }

    pixels = np.asarray(small, dtype=float).reshape(-1, 3)
    luma = pixels @ np.array([0.2126, 0.7152, 0.0722])
    mean = float(luma.mean())
    spread = float(luma.std())

    # Saturation as the max-minus-min of the channels, which is the HSV
    # definition and needs no colour-space conversion.
    chroma = float((pixels.max(axis=1) - pixels.min(axis=1)).mean())

    # Grain: the mean absolute difference between neighbouring pixels of the
    # luminance plane. On a clean render this is near zero; film grain and
    # sensor noise raise it. Reported, never named.
    gl = np.asarray(grain_source.convert("L"), dtype=float)
    grain = float(np.abs(np.diff(gl, axis=1)).mean()) if gl.shape[1] > 1 else 0.0

    # The dominant colours: Pillow's own quantiser, then each cluster named.
    # Duplicates collapse — two dark clusters both nearest to `charcoal` are
    # one palette word, not two.
    words: list[str] = []
    quantised = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = quantised.getpalette() or []
    # `getcolors` on a quantised image returns (count, palette index) pairs.
    # Typed loosely by Pillow, so the index is narrowed here rather than
    # trusted — an index that is not an int would slice the palette wrongly
    # and name a colour nobody has.
    counts = sorted(quantised.getcolors() or [], key=lambda pair: -int(pair[0]))
    for _count, raw_index in counts:
        index = int(raw_index)  # type: ignore[call-overload]
        rgb = palette[index * 3 : index * 3 + 3]
        if len(rgb) < 3:
            continue
        word = _nearest_word(rgb)
        if word not in words:
            words.append(word)
        if len(words) >= DOMINANT_COLOURS:
            break

    if chroma <= MUTED_CHROMA:
        saturation = "muted"
    elif chroma >= SATURATED_CHROMA:
        saturation = "saturated"
    else:
        saturation = "moderate"
    # The card's own words, so an answer here can be handed straight to
    # `write_lipsync_prompt` without translation.
    assert saturation in SATURATION_CUES

    if mean >= HIGH_KEY_MEAN:
        light = "high-key"
    elif mean <= LOW_KEY_MEAN:
        light = "low-key"
    else:
        light = ""

    # Both words come from `style.LIGHT_WORDS`; asserted rather than assumed,
    # because a rename there must not silently produce a word the prompt gate
    # will later refuse.
    assert not light or light in LIGHT_WORDS

    named = len(words) + (1 if light else 0) + 1  # saturation always resolves
    return {
        **_house(
            PASS if named else UNMEASURED,
            named,
            0,
            # mood is never measurable here, and the light axis counts as
            # unmeasured when the histogram supports neither word.
            1 + (0 if light else 1),
            (
                f"{width}x{height}; palette {', '.join(words) or 'unnamed'}; "
                + (f"lighting {light}" if light else "lighting neither high- nor low-key")
                + f"; saturation {saturation}; mood NOT measurable from pixels; "
                f"grain {grain:.2f}, chroma {chroma:.1f} (muted at {MUTED_CHROMA}, "
                f"saturated at {SATURATED_CHROMA}), luminance mean {mean:.1f} "
                f"(high-key at {HIGH_KEY_MEAN}, low-key at {LOW_KEY_MEAN})"
            ),
        ),
        "palette": words,
        "light": light,
        "saturation": saturation,
        "mood": None,
        "measurements": {
            "width": width,
            "height": height,
            "aspect": round(width / height, 4) if height else None,
            "luminance_mean": round(mean, 2),
            "luminance_spread": round(spread, 2),
            "saturation": round(chroma, 2),
            "grain": round(grain, 3),
        },
    }


def motion_of(frames: Sequence[str]) -> dict:
    """Does the clip loop and does it move physically. Delegates to the engine.

    `lipsync.motion` is imported, never reimplemented: it is the instrument the
    engine already judges clips with, and a second copy here would be a second
    answer to the same question. It is also frozen, so a defect found in it is
    reported rather than patched.

    Its functions do not return the house dict — they predate it — so this
    wraps them into one, and a dependency it cannot import becomes
    `could not measure` rather than an exception.
    """
    paths = [str(f) for f in frames]
    if len(paths) < 3:
        return {
            **_house(
                UNMEASURED,
                0,
                0,
                1,
                f"{len(paths)} frame(s): the engine needs at least 3 to judge a loop",
            ),
            "loop": None,
            "quality": None,
        }
    try:
        from lipsync import motion
    except ImportError as error:
        return {
            **_house(UNMEASURED, 0, 0, 1, f"nothing to measure with: {error}"),
            "loop": None,
            "quality": None,
        }
    try:
        seam = motion.loop_seam(paths)
        quality = motion.motion_quality(paths)
    except Exception as error:  # noqa: BLE001 - a missing dependency is an answer
        return {
            **_house(
                UNMEASURED, 0, 0, 1, f"the engine's motion instruments could not run: {error}"
            ),
            "loop": None,
            "quality": None,
        }
    violations = int(not seam.get("seamless", False))
    return {
        **_house(
            FAIL if violations else PASS,
            2,
            violations,
            0,
            f"{seam.get('note', '')} {quality.get('note', '')}".strip(),
        ),
        "loop": seam,
        "quality": quality,
    }


def intake_of(path: str | Path) -> dict:
    """The engine's own acceptance for a photo, with its reasons brought up.

    `photo_intake` reports per-axis and carries no top-level note, so a caller
    that prints `report["note"]` prints nothing while a perfectly good reason
    sits one level down. That is a finding for the engine's owner and the
    engine is frozen, so this lifts the axis notes instead of patching it.
    """
    try:
        from lipsync.fork_intake import photo_intake
    except ImportError as error:
        return {**_house(UNMEASURED, 0, 0, 1, f"nothing to measure with: {error}"), "axes": {}}
    try:
        report = photo_intake(str(path))
    except Exception as error:  # noqa: BLE001
        return {
            **_house(UNMEASURED, 0, 0, 1, f"the engine's intake could not run: {error}"),
            "axes": {},
        }
    axes = report.get("axes") or {}
    reasons = "; ".join(
        f"{name}: {axis.get('note', '')}"
        for name, axis in axes.items()
        if str(axis.get("outcome")) != PASS
    )
    return {
        **_house(
            str(report.get("outcome", UNMEASURED)),
            int(report.get("checked", 0) or 0),
            int(report.get("violations", 0) or 0),
            int(report.get("unmeasured", 0) or 0),
            reasons or "every intake axis passed",
        ),
        "axes": axes,
    }


#: Расширения, которые разбираются как ВИДЕО, а не как картинка.
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"})

#: Сколько кадров вынимать из ролика. ВЫБРАНО 6: столько же, сколько берёт
#: раскадровка стенда-валидатора, и по той же причине — шести хватает, чтобы
#: увидеть движение и дрейф, и каждый кадр остаётся достаточно крупным, чтобы
#: по нему мерили текстуру.
VIDEO_FRAMES = 6


def frames_from_video(path: str | Path, into: Path, *, count: int = VIDEO_FRAMES) -> dict:
    """Вынуть `count` кадров из ролика, равномерно по всей его длине.

    ЗАЧЕМ ЭТА ФУНКЦИЯ ПОЯВИЛАСЬ. Докстроки `analyse` и MCP-инструмента
    утверждали: «An mp4 cannot be decoded here (no ffmpeg, MEASURED)», и звали
    оператора декодировать ролик где-то ещё. ИЗМЕРЕНО 2026-08-31: ffmpeg 7.0.2
    лежит в окружении, ставится вместе с `imageio-ffmpeg`, и этим же ffmpeg
    весь стенд-валидатор режет раскадровки. Утверждение было верным когда-то и
    устарело молча — ровно тот класс расхождения «документ обещает одно, код
    делает другое», который разбирался в этот день пять раз.

    Три исхода (Р1): кадры вынуты, ролик не читается, ffmpeg недоступен. Третий
    существует не для симметрии: `imageio-ffmpeg` — необязательная зависимость,
    и «его нет» обязано отличаться от «файл битый».
    """
    into.mkdir(parents=True, exist_ok=True)
    try:
        import imageio_ffmpeg
    except Exception as exc:  # noqa: BLE001 - отсутствие пакета это измерение
        return {
            **_house(
                UNMEASURED,
                0,
                0,
                1,
                f"imageio-ffmpeg недоступен ({type(exc).__name__}), декодировать ролик нечем",
            ),
            "frames": [],
        }

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    seconds = _video_seconds(exe, path)
    if seconds is None:
        return {
            **_house(
                UNMEASURED, 0, 0, 1, f"ffmpeg не смог прочитать длительность {Path(path).name}"
            ),
            "frames": [],
        }
    step = max(seconds / count, 0.04)
    done = subprocess.run(
        [
            exe,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            f"fps=1/{step:.4f}",
            "-frames:v",
            str(count),
            str(into / "frame_%03d.jpg"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    got = sorted(str(f) for f in into.glob("frame_*.jpg"))
    if not got:
        return {
            **_house(
                UNMEASURED,
                0,
                0,
                1,
                f"ffmpeg не выдал ни одного кадра: {(done.stderr or '').strip()[:160]}",
            ),
            "frames": [],
        }
    return {
        **_house(PASS, len(got), 0, 0, f"{len(got)} кадр(ов) из {seconds:.1f} с, шаг {step:.2f} с"),
        "frames": got,
    }


def _video_seconds(exe: str, path: str | Path) -> float | None:
    """Длительность ролика по выводу ffmpeg, или None если её там нет."""
    done = subprocess.run(
        [exe, "-hide_banner", "-i", str(path)], capture_output=True, text=True, check=False
    )
    for line in done.stderr.splitlines():
        if "Duration:" in line:
            stamp = line.split("Duration:")[1].split(",")[0].strip()
            try:
                hours, minutes, secs = stamp.split(":")
                return int(hours) * 3600 + int(minutes) * 60 + float(secs)
            except ValueError:
                return None
    return None


def analyse(path: str | Path, *, frames: Sequence[str] | None = None) -> dict:
    """Everything measurable about one creative, and everything that was not.

    :param path: a still image, OR a video — `.mp4`, `.mov`, `.webm` and the
        rest of `VIDEO_SUFFIXES`. A video is decoded here into six frames; the
        look is measured on the middle one, and the motion instruments get the
        whole sequence.
    :param frames: a frame sequence you extracted yourself. Given, it wins over
        anything decoded from `path` — a caller who already has the frames
        should not pay for a second decode.

    Three outcomes over the whole creative, and `could_not_run` names every
    instrument that did not run and why. That list is the point: an answer with
    no violations and four silent instruments is not a clean creative, and the
    counts say so — `unmeasured` carries them.

    Cheap before expensive (house rule P2): the look is milliseconds of numpy,
    the engine's intake loads a face model or discovers it cannot. The order is
    fixed here so a missing package is found before a decode is attempted.
    """
    # Ролик приводится к кадрам ПЕРЕД замерами, и кадры остаются на диске на
    # время разбора: `look` меряет один кадр, `motion_of` — всю последовательность.
    still = Path(path)
    decoded: dict | None = None
    temp: tempfile.TemporaryDirectory | None = None
    if frames is None and still.suffix.lower() in VIDEO_SUFFIXES:
        temp = tempfile.TemporaryDirectory()
        decoded = frames_from_video(still, Path(temp.name))
        got = list(decoded.get("frames") or [])
        if got:
            frames = got
            # Середина, а не первый кадр: первый у ролика часто титульный или
            # ещё не разогнавшийся, и мерить по нему текстуру значит мерить не то.
            still = Path(got[len(got) // 2])

    try:
        parts = {
            "look": look(still),
            "intake": intake_of(still),
        }
        if frames is not None:
            parts["motion"] = motion_of(frames)
        if decoded is not None and str(decoded.get("outcome")) == UNMEASURED:
            parts["video_decode"] = decoded
        return _finish(path, parts)
    finally:
        if temp is not None:
            temp.cleanup()


def _finish(path: str | Path, parts: dict) -> dict:
    """Свести замеры в один вердикт. Вынесено, чтобы кадры удалялись гарантированно."""

    could_not_run = [
        {"instrument": name, "why": str(part.get("note", ""))}
        for name, part in parts.items()
        if str(part.get("outcome")) == UNMEASURED
    ]
    checked = sum(int(part.get("checked", 0) or 0) for part in parts.values())
    violations = sum(int(part.get("violations", 0) or 0) for part in parts.values())
    unmeasured = sum(int(part.get("unmeasured", 0) or 0) for part in parts.values())

    if violations:
        outcome = FAIL
    elif checked:
        outcome = PASS
    else:
        outcome = UNMEASURED

    return {
        **_house(
            outcome,
            checked,
            violations,
            unmeasured,
            (
                f"{checked} thing(s) measured, {violations} against the engine's bars, "
                f"{unmeasured} not measurable"
                + (
                    "; NOT RUN: " + ", ".join(item["instrument"] for item in could_not_run)
                    if could_not_run
                    else ""
                )
            ),
        ),
        "parts": parts,
        "could_not_run": could_not_run,
    }
