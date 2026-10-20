"""How large a frame an UPSCALER records it can make — a hard filter on upscale steps (round 13).

WHY. The upscale step ranked its candidates by evidence and price only, and the
recorded output ceiling of an upscaler was read by nobody: an 8K delivery chose
whatever ranked first, and an endpoint whose schema stops at 2160p
(`target_resolution` enum 720p..2160p, a page that prices 1080p/2K/4K only)
could be the plan's 8K step. An upscaler that cannot write the ordered frame is
not a cheaper option — it is the wrong model.

WHAT IS READ. Two kinds of rows about the candidate itself (never its family:
the family's 10x factor mode is not the cap of a target-resolution endpoint):

* a CAP — `max_resolution` / `max_output_resolution` ("2160p target", "4K
  (2160p)", "output capped at 13.75 MP/frame", "any output resolution");
* a FACTOR — `upscale_factor_max` ("10 in factor mode", "4 (schema ...)"):
  reach = the SOURCE frame's short side x the factor, so it needs the source
  frame the customer named (`spec.inputs[].resolution`); unnamed, a factor row
  decides nothing.

A model's rows describe different MODES (a target-resolution enum next to a
factor mode), and the rule is the one `planner.fit_stance` uses for the input
frame: ONE row that reaches the target is enough (`REACH_YES`); every row read
and every one below is `REACH_BELOW`; anything else is `REACH_UNKNOWN`.

DECISION. Below by record is EXCLUDED when at least one candidate of the step
is not below (reaches, or is unknown); when every candidate is below, nobody is
excluded and the plan says the frame is reached in TWO passes
(`chain_note`). Reaching by record ranks above silence (`REACH_ORDER`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any

from studio import resolution

#: Steps this applies to (planner operation names).
UPSCALE_OPS: frozenset[str] = frozenset({"апскейл", "апскейл_изображения"})

#: Attributes that state an absolute output cap.
CAP_ATTRIBUTES: frozenset[str] = frozenset({"max_resolution", "max_output_resolution", "output_resolution_max"})
#: Attributes that state the largest upscale factor of a mode.
FACTOR_ATTRIBUTES: frozenset[str] = frozenset({"upscale_factor_max", "max_upscale_factor"})

#: Round 14: attributes that state the largest frame a model was TESTED (paper / benchmark / probe) to
#: write well — not a cap of the endpoint: the schema may allow more, nobody showed the quality there.
TESTED_ATTRIBUTES: frozenset[str] = frozenset({"tested_output_ceiling"})

REACH_YES = "reaches the ordered frame by record"
REACH_UNTESTED = "reaches the ordered frame by schema only; its quality is tested below it"
REACH_UNKNOWN = "output ceiling not recorded"
REACH_BELOW = "recorded output ceiling below the ordered frame"
#: Order before price: reaching by record, then reaching by schema beyond the tested frame, then
#: silence, then below (round 14: an 8K LED wall prefers the upscaler its own paper does not stop short of).
REACH_ORDER: dict[str, int] = {REACH_YES: 0, REACH_UNTESTED: 1, REACH_UNKNOWN: 2, REACH_BELOW: 3}

#: Round 14: an upscaler made for TRANSPARENT assets (alpha preserved, PNG) — the wrong tool for an
#: opaque frame (a product hero shot, a zoom): read from what the model is for, or its endpoint name.
ALPHA_ROW_ATTRIBUTES: frozenset[str] = frozenset({"best_for", "positioning", "alpha_output"})
ALPHA_SPECIALISED = re.compile(r"alpha channel|transparen|with alpha|alpha output|альфа|прозрачн", re.I)
ALPHA_NAME = re.compile(r"transparen|[-_]alpha\b|rgba", re.I)

#: Round 14: an IMAGE upscaler run on each frame of a video (no temporal model) reaches the frame but not
#: the quality of a video upscaler — it ranks with the schema-only reach (`REACH_UNTESTED`).
PER_FRAME_ATTRIBUTES: frozenset[str] = frozenset({"architecture", "positioning"})
PER_FRAME = re.compile(r"\beach frame\b|\bper[- ]frame\b|\bframe[- ]by[- ]frame\b|покадров", re.I)

#: A row that says the output is not capped (self-hosted node, any size).
UNCAPPED = re.compile(r"\bany output resolution\b|\barbitrary (?:output )?(?:scale|resolution)\b|\bno output cap\b", re.I)
#: "output capped at 13.75 MP/frame" — a pixel-count cap (read before the
#: frame pairs: the same row may name the INPUT pair "up to 2560x1440").
MP_CAP = re.compile(r"output[^;.]{0,40}?(\d+(?:\.\d+)?)\s*MP", re.I)
#: The factor of a factor row: its leading number, or "4x" / "x4".
FACTOR = re.compile(r"^\s*(\d{1,2}(?:\.\d+)?)\b|(?<![\w.])(\d{1,2}(?:\.\d+)?)\s*[x×]\b|\bx(\d{1,2})\b", re.I)


def _short_of_mp(mp: float) -> int:
    """Short side of a 16:9 frame of `mp` megapixels."""
    return int(math.sqrt(mp * 1e6 * 9 / 16))


def row_reach(attribute: str, value: str, source_short: int | None) -> tuple[float | None, str]:
    """Largest short side one row says the model can write; None — the row decides nothing."""
    текст = str(value or "")
    if attribute in CAP_ATTRIBUTES:
        if UNCAPPED.search(текст):
            return math.inf, "no output cap"
        if m := MP_CAP.search(текст):
            return float(_short_of_mp(float(m.group(1)))), f"output cap {m.group(1)} MP/frame"
        предел = resolution.разобрать(текст)
        if предел.outcome != "годно":
            return None, "cap not parsed"
        короткая = предел.короткая or (round(предел.длинная * 9 / 16) if предел.длинная else None)
        return (float(короткая), f"output cap {короткая}p") if короткая else (None, "cap not parsed")
    if attribute in FACTOR_ATTRIBUTES:
        m = FACTOR.search(текст)
        if not m:
            return None, "factor not parsed"
        множитель = float(next(g for g in m.groups() if g))
        if not source_short:
            return None, f"factor {множитель:g}x, source frame not named"
        return source_short * множитель, f"factor {множитель:g}x of the {source_short}p source"
    return None, ""


def per_frame(rows: Sequence[Any]) -> str:
    """The row that says the model upscales each frame as an image ("" — none)."""
    for f in rows:
        if f.attribute in PER_FRAME_ATTRIBUTES and PER_FRAME.search(str(f.value or "")):
            return str(f.source_url or "")
    return ""


def reach_state(
    rows: Sequence[Any], target_short: int, source_short: int | None, video: bool = False
) -> tuple[str, str]:
    """(state, note) of one candidate against the ordered short side.

    :param video: the step upscales a VIDEO — a per-frame image upscaler reaches it only as
        `REACH_UNTESTED` (round 14).
    """
    прочитано: list[tuple[float, str, str]] = []
    не_решили = 0
    проверено: list[tuple[float, str]] = []
    for f in rows:
        if f.attribute in TESTED_ATTRIBUTES:
            до_проверки, _ = row_reach("max_resolution", f.value, source_short)
            if до_проверки is not None:
                проверено.append((до_проверки, f.source_url))
            continue
        if f.attribute not in CAP_ATTRIBUTES | FACTOR_ATTRIBUTES:
            continue
        до, как = row_reach(f.attribute, f.value, source_short)
        if до is None:
            не_решили += 1
            continue
        прочитано.append((до, как, f.source_url))
    for до, как, url in прочитано:
        if до >= target_short:
            ниже = [(т, у) for т, у in проверено if т < target_short]
            if ниже:
                т, у = max(ниже)
                return REACH_UNTESTED, (
                    f"{как} reaches {target_short}p ({url}), but its quality is tested only up to {int(т)}p ({у})"
                )
            if video and (кадрами := per_frame(rows)):
                return REACH_UNTESTED, (
                    f"{как} reaches {target_short}p ({url}), but it upscales each frame as an image, with no "
                    f"temporal model ({кадрами}) — flicker between frames is not ruled out"
                )
            return REACH_YES, f"{как} reaches {target_short}p ({url})"
    if прочитано and not не_решили:
        до, как, url = max(прочитано)
        return REACH_BELOW, f"{как} < {target_short}p ({url})"
    return REACH_UNKNOWN, (
        f"{не_решили} row(s) about the output ceiling decide nothing without the source frame"
        if не_решили
        else "no row about the output ceiling"
    )


def alpha_specialised(model: str, rows: Sequence[Any]) -> bool:
    """An upscaler made for transparent assets: its name, or what its rows say it is for."""
    if ALPHA_NAME.search(str(model or "")):
        return True
    return any(f.attribute in ALPHA_ROW_ATTRIBUTES and ALPHA_SPECIALISED.search(str(f.value or "")) for f in rows)


def alpha_exclusion_note(en: bool = True) -> str:
    return (
        "made for transparent assets (alpha channel, PNG) — the frame ordered is opaque, so an upscaler for "
        "ordinary frames is the right tool"
        if en
        else "сделан для прозрачных ассетов (альфа-канал, PNG) — заказан непрозрачный кадр, нужен обычный апскейлер"
    )


def best_below(rows: Sequence[Any], source_short: int | None) -> int | None:
    """The largest short side recorded for a model that is below the target (for the chain note)."""
    вершины = [row_reach(f.attribute, f.value, source_short)[0] for f in rows]
    числа = [int(v) for v in вершины if v is not None and v != math.inf]
    return max(числа) if числа else None


def exclusion_note(note: str, en: bool = True) -> str:
    return (
        f"upscale output ceiling: {note} — an upscaler that cannot write the ordered frame is not a candidate"
        if en
        else f"предел выхода апскейлера: {note} — апскейлер, который не пишет заказанный кадр, не кандидат"
    )


def chain_note(model: str, cap: int | None, target_short: int) -> str:
    """Every candidate is below the ordered frame: two passes, said aloud."""
    до = f"{cap}p" if cap else "its recorded ceiling"
    return (
        f"no upscaler here records a {target_short}p output: two passes — {model} up to {до}, then a second "
        f"pass of the same (or a factor-mode upscaler) from {до} to {target_short}p; check seams and "
        "over-sharpening after the second pass, or pick an upscaler that records the frame"
    )
