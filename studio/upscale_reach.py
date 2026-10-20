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

REACH_YES = "reaches the ordered frame by record"
REACH_UNKNOWN = "output ceiling not recorded"
REACH_BELOW = "recorded output ceiling below the ordered frame"
#: Order before price: reaching by record, then silence, then below.
REACH_ORDER: dict[str, int] = {REACH_YES: 0, REACH_UNKNOWN: 1, REACH_BELOW: 2}

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


def reach_state(rows: Sequence[Any], target_short: int, source_short: int | None) -> tuple[str, str]:
    """(state, note) of one candidate against the ordered short side."""
    прочитано: list[tuple[float, str, str]] = []
    не_решили = 0
    for f in rows:
        if f.attribute not in CAP_ATTRIBUTES | FACTOR_ATTRIBUTES:
            continue
        до, как = row_reach(f.attribute, f.value, source_short)
        if до is None:
            не_решили += 1
            continue
        прочитано.append((до, как, f.source_url))
    for до, как, url in прочитано:
        if до >= target_short:
            return REACH_YES, f"{как} reaches {target_short}p ({url})"
    if прочитано and not не_решили:
        до, как, url = max(прочитано)
        return REACH_BELOW, f"{как} < {target_short}p ({url})"
    return REACH_UNKNOWN, (
        f"{не_решили} row(s) about the output ceiling decide nothing without the source frame"
        if не_решили
        else "no row about the output ceiling"
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
