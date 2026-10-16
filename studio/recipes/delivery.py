"""Delivery conditions a senior engineer reads off the order before choosing a model (round 10).

WHY. The round-10 holdout measured plans that were right in their steps and silent
about the medium they were made for: a printed book planned at the generator's
default 1 MP, a VHS transfer sent to a restoration model with its interlacing
still in it, an 8K master sold as if the upscaler recovered real detail, 240 fps
promised from interpolation without a word about what interpolation invents. Each
is a GENERAL rule about a delivery class, read from `spec` and, where the spec has
no field for it (a print size, a tape format), from the brief's own words — the
same allowance `wants_alpha` has for a transparent background.

This module only READS (spec, text) and answers small questions; the notes and
the prior that use the answers live in `table.py` / `apply.py`.

DECISION CONSTANTS (T1: mutated both ways by `scripts/mutate_round10.py`):
`PRINT_DPI`, `LARGE_FORMAT_DPI`, `LARGE_FORMAT_MIN_MM`, `PRINT_SILENT_NATIVE_MP`,
`EIGHT_K_HEIGHT`, `EXTREME_FPS`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from studio import brief_spec as bs

# --- decision constants ------------------------------------------------------------

#: Print resolution at trim size for anything read at arm's length (books, posters,
#: flyers): the prepress standard of 300 pixels per inch.
PRINT_DPI = 300
#: Large format (billboards, banners, wall prints) is seen from metres away and is
#: printed at 100-150 ppi; 150 is the conservative end.
LARGE_FORMAT_DPI = 150
#: A print whose LONG side is at least this many millimetres is large format.
LARGE_FORMAT_MIN_MM = 1000
#: When the base is SILENT about a text-to-image model's largest frame, assume it
#: renders about 2048x2048 (4.2 MP) natively: the common default of current t2i
#: endpoints is 1-4 MP. A print frame above it gets the upscale step on silence
#: (prior `print_upscale`); a recorded larger native frame always wins.
PRINT_SILENT_NATIVE_MP = 4.2
#: Output height from which a frame is "8K" (7680x4320).
EIGHT_K_HEIGHT = 4320
#: Output frame rate from which interpolation is "extreme": at 120 fps and above,
#: three of every four frames (from 30 fps) are invented.
EXTREME_FPS = 120

MM_PER_INCH = 25.4

# --- print ---------------------------------------------------------------------------

#: The order is a PRINTED deliverable. Words of the medium, not of decoration:
#: "printed at", "for print", "print-ready", a poster, a book page — and not "a
#: printed t-shirt" (a garment print is a design on the product).
PRINT = re.compile(
    r"\bfor print\b|\bprint[- ]ready\b|\bprinted (?:at|on paper|in|as)\b|\bto (?:be )?print(?:ed)?\b"
    r"|\bprint (?:run|size|resolution|shop)\b|\bposters?\b|\bflyers?\b|\bbrochures?\b|\bleaflets?\b"
    r"|\bbillboards?\b|\bwall print\b|\bcanvas print\b|\bpicture book\b|\bbook (?:cover|page|illustration)s?\b"
    r"|\bmagazine\b|\b\d{2,4}\s*dpi\b|\bdpi\b"
    r"|печат|постер|плакат|листовк|буклет|брошюр|билборд|типограф|(?<![а-яё])книг[аиуе]?\b|(?<![а-яё])журнал[аеы]?\b",
    re.I,
)

#: ISO 216 A-series and two US sizes, millimetres (short side, long side).
PAPER_MM: dict[str, tuple[float, float]] = {
    "a0": (841, 1189),
    "a1": (594, 841),
    "a2": (420, 594),
    "a3": (297, 420),
    "a4": (210, 297),
    "a5": (148, 210),
    "a6": (105, 148),
    "letter": (215.9, 279.4),
    "tabloid": (279.4, 431.8),
}

_PAPER = re.compile(r"(?<![a-z0-9])(a[0-6]|letter|tabloid)(?![a-z0-9])", re.I)
_SIZE = re.compile(
    r"(\d{1,4}(?:[.,]\d+)?)\s*(?:x|×|by|на)\s*(\d{1,4}(?:[.,]\d+)?)\s*"
    r"(mm|мм|cm|см|in(?:ch(?:es)?)?\b|\"|″|дюйм\w*|m\b|м\b)",
    re.I,
)
_UNIT_MM: dict[str, float] = {"mm": 1.0, "мм": 1.0, "cm": 10.0, "см": 10.0, "m": 1000.0, "м": 1000.0}


def _texts(spec: "bs.Spec", text: str) -> list[str]:
    return [str(у) for у in (*spec.conditions, text) if у]


def is_print(spec: "bs.Spec", text: str = "") -> bool:
    """A still made for paper: image output and the medium named in conditions or in the brief."""
    if "image" not in spec.outputs or "video" in spec.outputs:
        return False
    return any(PRINT.search(т) for т in _texts(spec, text))


def print_size_mm(spec: "bs.Spec", text: str = "") -> tuple[tuple[float, float], str] | None:
    """The trim size named in conditions or the brief, in mm (short, long), with its label; None — not named."""
    for т in _texts(spec, text):
        м = _SIZE.search(т)
        if м:
            a, b = (float(x.replace(",", ".")) for x in м.group(1, 2))
            unit = м.group(3).lower()
            k = _UNIT_MM.get(unit, MM_PER_INCH)
            if a > 0 and b > 0:
                return (min(a, b) * k, max(a, b) * k), м.group(0).strip()
        м = _PAPER.search(т)
        if м:
            return PAPER_MM[м.group(1).lower()], м.group(1).upper()
    return None


def print_dpi(size_mm: tuple[float, float]) -> int:
    """Pixels per inch the print needs: large format is seen from afar."""
    return LARGE_FORMAT_DPI if size_mm[1] >= LARGE_FORMAT_MIN_MM else PRINT_DPI


def print_frame(spec: "bs.Spec", text: str = "") -> tuple[tuple[int, int], str, int] | None:
    """The pixel frame a print needs: ((w, h), size label, dpi); None — not print, or no size named.

    Orientation follows the ordered aspect (portrait unless the aspect is wider than tall).
    """
    if not is_print(spec, text):
        return None
    found = print_size_mm(spec, text)
    if found is None:
        return None
    (short, long), label = found
    dpi = print_dpi((short, long))
    w, h = (round(short / MM_PER_INCH * dpi), round(long / MM_PER_INCH * dpi))
    if _landscape(spec.aspect):
        w, h = h, w
    return (w, h), label, dpi


def _landscape(aspect: str | None) -> bool:
    м = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[:x/]\s*(\d+(?:\.\d+)?)\s*", str(aspect or ""))
    if м is None:
        return False
    return float(м.group(1)) > float(м.group(2))


# --- interlaced tape ---------------------------------------------------------------

#: An interlaced source: analogue or DV tape, broadcast SD/HD "i" formats.
INTERLACED = re.compile(
    r"\bvhs\b|\bs-?vhs\b|\bhi-?8\b|\bvideo ?8\b|\bbetacam\b|\bbetamax\b|\bmini-?dv\b|\bdv tape\b|\bdvcam\b"
    r"|\bcamcorder tape\b|\bvideo ?tape\b|\binterlac\w*|\b(?:480|576|1080)i\b|\btelecine\b"
    r"|кассет\w*|видеокассет\w*|чересстроч\w*|\bвхс\b",
    re.I,
)


def interlaced_source(spec: "bs.Spec", text: str = "") -> bool:
    """The customer's video comes from tape or an interlaced broadcast format."""
    if "video" not in spec.inputs:
        return False
    return any(INTERLACED.search(т) for т in _texts(spec, text)) or any(
        INTERLACED.search(str(з.get("resolution") or "")) for з in spec.input_items
    )


# --- 8K and extreme frame rates ------------------------------------------------------


def eight_k(spec: "bs.Spec") -> bool:
    """The deliverable is 8K (short side of the ordered frame at least `EIGHT_K_HEIGHT`)."""
    from studio import brief_spec as bs  # cycle: brief_spec imports the recipe table

    try:
        frame = bs.frame(spec)
    except (KeyError, ValueError):
        return False
    return frame is not None and min(frame) >= EIGHT_K_HEIGHT


def extreme_fps(spec: "bs.Spec") -> bool:
    """The ordered frame rate is at or above `EXTREME_FPS`."""
    return bool(spec.fps) and float(spec.fps or 0) >= EXTREME_FPS
