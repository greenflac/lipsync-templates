#!/usr/bin/env python3
"""Did this text pass through an image model, or was it composited?

    python scripts/measure_vae_text.py <image.jpg> <x0> <y0> <x1> <y1>

WHY THIS EXISTS

On 2026-08-29 I was shown a marketing creative and asked what stack made it. I
measured that the text was RENDERED rather than generated — correct — and then
concluded the final frame was assembled by a layout engine. Wrong. The owner
gave the ground truth: the text was drawn with Pillow and fed INTO an image
model, which is why it holds.

The measurement I made could not tell those apart, and the reason is a rule I
break at my peril: I compared the text against the ILLUSTRATION INSIDE THE SAME
PICTURE, when the answer needed a control I could build myself. A negative
control is not optional garnish (rule I5); here its absence turned a real
measurement into a wrong conclusion.

WHAT SEPARATES THEM, MEASURED

Render the same text with Pillow, save it at the JPEG quality of the suspect
file — read from its quantization tables, not guessed — and compare two numbers
at the glyph edge:

    Pillow -> JPEG q80    edge 1.57 px   overshoot before the edge   1.9%
    the creative          edge 2.36 px   overshoot before the edge  21.5%

Half again the edge width and ELEVEN TIMES the ringing, at identical
compression. Compositing cannot do that; a VAE round-trip does.

WHERE IT DOES NOT WORK, and this is the honest half: at small type the two
converge — Pillow at q80 already gives 2.16 px and 16% — so only large type
carries the signal. A verdict on body text is `could not measure`, not `clean`.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

#: Below this STROKE thickness the control and the suspect overlap, so the
#: instrument says nothing. ИЗМЕРЕНО 2026-08-29: at 26 px type
#: Pillow-through-JPEG already shows 2.16 px edges and 16% overshoot, inside the
#: range a VAE produces.
#:
#: It reads the strokes, not the box, and that correction came from the tool
#: getting it wrong on its first run: given the creative's body paragraph — a
#: 170 px tall box full of small type — it compared the BOX height against this
#: floor, sailed over it, and answered "no sign of a model" about an image we
#: KNEW had been through one. A false clean is worse than no answer, because
#: nobody re-checks a clean.
MIN_STROKE_PX = 5

#: How much wider than the control an edge must be to count. ВЫБРАНО from the
#: measured pair (1.57 control against 2.36 suspect): the midpoint, so neither
#: side sits on the line.
WIDTH_RATIO = 1.30

#: Same, for ringing. The measured pair was 1.9% against 21.5%; a factor of four
#: is far inside that gap and far outside JPEG's own contribution.
OVERSHOOT_RATIO = 4.0


def _таблица_квантования(image: Image.Image) -> "np.ndarray":
    """Таблица квантования JPEG числами.

    Атрибут есть только у JPEG-снимка, и проверке типов это неизвестно:
    `Image.open` обещает базовый класс. Сужаем явно — на PNG здесь нужен
    отказ, а не молчаливый `getattr`, иначе сравнение поедет на другом
    кодеке и никто не заметит.
    """
    tables = getattr(image, "quantization", None)
    if not tables:
        raise TypeError(f"ждали JPEG с таблицей квантования, пришло {image.format!r}")
    return np.asarray(tables[0], dtype=np.float64)


def jpeg_quality(path: Path) -> int:
    """The file's real quality, from its quantization tables.

    Guessing this is how a comparison gets rigged: pick a low quality for the
    control and the suspect looks damaged by the model rather than by the coder.
    """
    table = _таблица_квантования(Image.open(path))
    probe = Image.new("RGB", (64, 64), (128, 128, 128))
    best, best_gap = 75, None
    for candidate in range(30, 101):
        buffer = io.BytesIO()
        probe.save(buffer, "JPEG", quality=candidate)
        other = _таблица_квантования(Image.open(io.BytesIO(buffer.getvalue())))
        gap = float(np.abs(other - table).sum())
        if best_gap is None or gap < best_gap:
            best, best_gap = candidate, gap
    return best


def edge_profile(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[float, float, int]:
    """Mean edge width in pixels, share of rows overshooting, and rows seen."""
    patch = np.asarray(image.convert("L").crop(box)).astype(float)
    widths: list[np.ndarray] = []
    overshoot = 0
    for row in patch:
        if row.size < 12:
            continue
        step = np.diff(row)
        i = int(np.argmin(step))
        if i < 3 or i > len(row) - 5 or abs(step[i]) < 40:
            continue
        widths.append(row[i - 2 : i + 4])
        before = row[max(0, i - 12) : i - 3]
        if before.size and row[max(0, i - 3)] > before.max() + 2:
            overshoot += 1
    if not widths:
        return 0.0, 0.0, 0
    stack = np.array(widths)
    width = float((np.abs(np.diff(stack, axis=1)) > 15).sum(1).mean())
    return width, overshoot / len(stack), len(stack)


def stroke_thickness(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Median vertical run of dark pixels — a proxy for type size that needs no
    font metrics and no assumption about how the caller drew the box."""
    patch = np.asarray(image.convert("L").crop(box)).astype(float)
    dark = patch < (patch.max() + patch.min()) / 2
    runs: list[int] = []
    for column in dark.T:
        length = 0
        for value in column:
            if value:
                length += 1
            elif length:
                runs.append(length)
                length = 0
        if length:
            runs.append(length)
    return float(np.median(runs)) if runs else 0.0


def _render(quality: int, cap_px: int) -> Image.Image:
    canvas = Image.new("L", (900, 200), 245)
    draw = ImageDraw.Draw(canvas)
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", cap_px)
    except OSError:  # pragma: no cover - depends on the machine's fonts
        font = ImageFont.load_default()
    draw.text((20, 40), "Mi inginocchio e sento", font=font, fill=17)
    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, "JPEG", quality=quality)
    return Image.open(io.BytesIO(buffer.getvalue()))


def _control(quality: int, stroke: float) -> tuple[float, float, int]:
    """The DIRTIEST clean render whose strokes match the suspect's.

    Two corrections live in this function, and both came from the instrument
    being wrong before they did.

    MATCH THE STROKE, NOT THE BOX. Comparing a suspect against a control set by
    box height compares different type sizes, which is not a comparison.

    TAKE THE WORST, NOT THE NEAREST. MEASURED 2026-08-29, the same clean text
    through the same q80 coder: 40 px type gives 1.90 px edges and 20.5%
    ringing, 65 px gives 1.42 px and 0.0%. A reference that swings that far with
    size is not a reference. So every size whose stroke matches within a pixel
    is rendered, and the control is the worst of them — a verdict of "went
    through a model" then means the suspect beat even the dirtiest clean render
    it could be confused with.
    """
    band = [
        (width, over)
        for cap in range(20, 121, 4)
        for image in (_render(quality, cap),)
        if abs(stroke_thickness(image, (0, 35, 900, 170)) - stroke) <= 1.0
        for width, over, rows in (edge_profile(image, (0, 35, 900, 170)),)
        if rows
    ]
    if not band:
        return 0.0, 0.0, 0
    return max(w for w, _ in band), max(o for _, o in band), len(band)


def judge(path: Path, box: tuple[int, int, int, int]) -> dict:
    suspect_image = Image.open(path)
    stroke = stroke_thickness(suspect_image, box)
    if stroke < MIN_STROKE_PX:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "stroke": round(stroke, 1),
            "note": (
                f"толщина штриха {stroke:.1f}px ниже порога {MIN_STROKE_PX}: на мелком "
                "кегле контроль и подозреваемый смыкаются, и прибор не различает их. "
                "Это НЕ «чисто» — это отказ судить"
            ),
        }
    quality = jpeg_quality(path)
    c_width, c_over, sizes = _control(quality, stroke)
    if sizes == 0:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "stroke": round(stroke, 1),
            "note": (
                f"не удалось отрисовать контроль с толщиной штриха {stroke:.1f}px: "
                "сравнивать не с чем"
            ),
        }
    s_width, s_over, rows = edge_profile(suspect_image, box)
    if rows == 0 or c_width == 0:
        return {
            "outcome": UNMEASURED,
            "checked": rows,
            "violations": 0,
            "unmeasured": 1,
            "note": "ни одного пригодного края: судить не о чем",
        }
    wide = s_width >= c_width * WIDTH_RATIO
    rings = s_over >= max(c_over, 0.02) * OVERSHOOT_RATIO
    # TWO ANSWERS, NOT THREE, AND `pass` IS NOT ONE OF THEM.
    #
    # Nothing an edge can show establishes that text did NOT go through a model:
    # a model that reproduces its input faithfully leaves an edge indistinguish-
    # able from a composite. So the honest pair is "beyond the dirtiest clean
    # control" and "could not tell" — and the second is what this instrument
    # returns on the one case whose answer is KNOWN.
    #
    # MEASURED 2026-08-29 on a creative the owner confirmed was Pillow text fed
    # into an image model: control 2.16 px / 15.4% ringing, suspect 2.36 / 21.5%
    # — a ratio of 1.09 and 1.40 against thresholds of 1.30 and 4.0. It does not
    # clear. Returning `pass` there would print "no sign of a model" over an
    # image that went through one, which is the false clean this file exists to
    # avoid.
    return {
        "outcome": FAIL if (wide and rings) else UNMEASURED,
        "checked": rows,
        "violations": int(wide and rings),
        "unmeasured": 0 if (wide and rings) else 1,
        "quality": quality,
        "stroke": round(stroke, 1),
        "control": {"width": round(c_width, 2), "overshoot": round(c_over, 3)},
        "suspect": {"width": round(s_width, 2), "overshoot": round(s_over, 3)},
        "note": (
            "текст прошёл через модель: край шире и звенит сильнее, чем у "
            "контрольного набора при том же сжатии"
            if (wide and rings)
            else (
                f"не смогли: край ({s_width:.2f}px, звон {100 * s_over:.1f}%) лежит "
                f"внутри разброса чистого контроля ({c_width:.2f}px, {100 * c_over:.1f}%). "
                "Это НЕ доказательство чистоты — признака просто не хватает"
            )
        ),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__)
        return 2
    path = Path(argv[0])
    box = tuple(int(v) for v in argv[1:5])  # type: ignore[assignment]
    out = judge(path, box)  # type: ignore[arg-type]
    for key in ("quality", "stroke", "control", "suspect"):
        if key in out:
            print(f"{key:10} {out[key]}")
    print(
        f"\nпроверено {out['checked']}\nнарушений {out['violations']}\nне смогли {out['unmeasured']}"
    )
    print(f"\n{out['outcome']}: {out['note']}")
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[out["outcome"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
