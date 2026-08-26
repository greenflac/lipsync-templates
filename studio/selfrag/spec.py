"""A media-aware generation spec, and the assembler that turns it into a prompt.

Why this exists rather than an edit to `studio/style.py`: `StyleSpec` has five
fields — palette, light, texture, mood, setting — and that is exactly right for
the studio product, where the subject comes from the client's photo and the
motion comes from the driving clip, so a prompt that named either would be a
bug. It is not enough for the stated goal here, which is prompts for Kling,
Veo, Runway and Flux. Every one of those vendors' guides asks for a subject, an
action, a camera and (for three of them) audio. A StyleSpec cannot express a
camera move, so a StyleSpec cannot write a Veo prompt.

`GenSpec` is therefore a superset: it CONTAINS a StyleSpec rather than
replacing it, so the studio's allow-lists, its refusal words and its
`build_prompt` keep being the single source of truth for the look, and this
module only adds the slots the look never had room for.

The security boundary is unchanged and is the reason the shape is a dataclass
and not a string: the model fills fields, code assembles the prompt. An
injected instruction can change a field's value; it cannot change what the
prompt is made of.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from lipsync.fork_style_prompt import subject_leak
from studio.selfrag.registry import (
    MEDIA_IMAGE,
    MEDIA_VIDEO,
    ModelCard,
    card_for,
    fits_duration,
)
from studio.style import (
    SETTING_KEEP,
    StyleSpec,
    banned_topics,
    build_prompt as build_style_prompt,
    gate_input,
)

__all__ = [
    "MEDIA_IMAGE",
    "MEDIA_VIDEO",
    "MODE_EDIT",
    "REFERENCE_MODES",
    "MODE_I2V",
    "MODE_T2I",
    "MODE_T2V",
    "SLOT_BUILDERS",
    "GenSpec",
    "assemble",
    "gate_spec",
]

MODE_T2I = "t2i"
MODE_T2V = "t2v"
MODE_I2V = "i2v"
MODE_EDIT = "edit"
MODES: tuple[str, ...] = (MODE_T2I, MODE_T2V, MODE_I2V, MODE_EDIT)

# Free-text cap for a VENDOR slot (subject, action, camera, motion, audio).
#
# This used to be studio.style's SETTING_MAX, 60 characters, inherited without
# being re-derived. That number is right for what it was chosen for — the
# studio's `setting` field, a short place description — and too tight for the
# slots a vendor skeleton asks for. An ordinary edit instruction, "the
# background becomes wet dark slate, the light turns cooler", is 61 characters
# and was refused (OBSERVED 2026-08-26, while planning a paid run).
#
# CHOSEN at 120, and the reasoning is the published length bands: Veo's own
# guide asks for 100-150 words for the WHOLE prompt, so a single slot at ~24
# words is already a quarter of the budget. The cap still bounds the field; it
# no longer refuses a sentence a person would normally write.
#
# The studio's own `setting` keeps its 60, because studio.style sanitises it.
SLOT_MAX = 120

# Only these characters survive in a free-text slot. Same rule as
# studio.style.sanitise_setting, reused rather than re-implemented.
_MULTI_WS = re.compile(r"\s+")

# The draft keys every return from `assemble` carries, whatever branch it took.
# A caller reading out["dropped"] must not have to know which branch ran; an
# early return with fewer keys is a KeyError waiting for the unhappy path.
_EMPTY_DRAFT: dict = {
    "prompt": None,
    "negative_prompt": "",
    "parameters": {},
    "slots": {},
    "dropped": [],
    "dropped_by_design": [],
    "words": 0,
    "skeleton": [],
}


@dataclass(frozen=True)
class GenSpec:
    """Everything a generation call needs, in fields rather than prose.

    `style` carries the look and is the studio's existing, gated StyleSpec.
    Everything else is what a video model asks for and a StyleSpec has no
    slot for.

    `subject_locked` is the studio product's constraint, carried explicitly
    rather than assumed: when it is True the assembled prompt must not name
    a person, their clothing or their pose, because those come from the
    client's photo and the driving clip. The engine's own `subject_leak`
    is what enforces it — one definition of the subject zone, not two.
    """

    model: str
    mode: str
    style: StyleSpec
    subject: str = ""
    action: str = ""
    camera: str = ""
    motion: str = ""
    audio: str = ""
    constraints: tuple[str, ...] = ()
    duration_seconds: float | None = None
    aspect_ratio: str = ""
    subject_locked: bool = False
    refusal: str | None = None
    extra: dict = field(default_factory=dict, compare=False)


def _slot(text: str) -> str:
    """Clean one vendor slot: the studio's character rule, and NO truncation.

    The character allow-list is imported from `studio.style`, not copied: it is
    a security rule and there is one of it.

    Length is deliberately not enforced here. `studio.style.sanitise_setting`
    cuts to 60 as part of its own contract, and calling it for a vendor slot
    inherited that cut — so after `SLOT_MAX` was raised to 120 the gate began
    ACCEPTING a 61-character instruction that the assembler then silently
    truncated to "the light turns coole" (OBSERVED 2026-08-26). Silent
    truncation is worse than the refusal it replaced: the caller is told the
    prompt is fine and never learns it means less than they wrote.

    Length now lives in one place only — `gate_spec`, which refuses out loud.
    """
    cleaned = SETTING_KEEP.sub(" ", str(text or ""))
    return _MULTI_WS.sub(" ", cleaned).strip()


# How each named vendor slot is filled from a GenSpec. Named as data so that a
# new vendor skeleton is a table entry, not a new branch in the assembler.
SLOT_BUILDERS: dict[str, str] = {
    "subject": "subject",
    "action": "_action",
    "movement": "_motion",
    "motion": "_motion",
    "camera": "camera",
    "shot": "camera",
    "audio": "audio",
    "setting": "_setting",
    "scene": "_setting",
    "context": "_setting",
    "composition": "camera",
    "focus": "camera",
    "ambiance": "_light",
    "style": "_style",
    "stylisation": "_style",
    "aesthetic": "_style",
    "lighting": "_light",
    "texture": "_texture",
    "palette": "_palette",
    "constraints": "_constraints",
}

# Which builder sources carry each GenSpec free-text field. Used to tell "the
# skeleton had no room for this" from "this went into a shared slot".
FIELD_SOURCES: dict[str, tuple[str, ...]] = {
    "subject": ("subject",),
    "action": ("_action", "_motion"),
    "motion": ("_motion", "_action"),
    "camera": ("camera",),
    "audio": ("audio",),
}

# Fields an image-to-video prompt is SUPPOSED to leave out. Several vendors
# encode this by omitting the slot from their I2V skeleton entirely rather than
# by marking it as appearance, so the drop has to be recognised by field name
# too, not only by which slot was filtered.
I2V_INTENTIONAL_FIELDS: frozenset[str] = frozenset({"subject"})

# Modes that start from a reference image. Both drop the appearance slots for
# the same reason, and only I2V used to: an edit is conditioned on a picture
# exactly as an image-to-video is, so re-describing the subject fights the
# reference in both. Leaving `edit` out made an assembled edit prompt identical
# to a naive one plus decoration (OBSERVED 2026-08-26 while designing an A/B
# run whose whole point was to test that difference).
REFERENCE_MODES: frozenset[str] = frozenset({MODE_I2V, MODE_EDIT})

# Slots that describe how the subject LOOKS. In image-to-video these are the
# single most common mistake: every vendor guide that discusses I2V says the
# same thing — the image already carries appearance, and re-describing it
# injects a conditioning signal that fights the image latent. The visible
# symptom is morphing in the opening frames.
APPEARANCE_SLOTS: frozenset[str] = frozenset(
    {"subject", "setting", "scene", "context", "palette", "texture", "composition"}
)


def _style_bits(spec: GenSpec) -> dict[str, str]:
    """The look and the movement, split into the slot names vendors use.

    `_action` and `_motion` fall back to each other. Vendors do not agree on
    which of the two words their skeleton uses — Kling says "action", Seedance
    says "movement", Wan says "motion" — and a GenSpec that filled the other
    one had its text silently dropped from the finished prompt (OBSERVED
    2026-08-26 on a kling-3.0 t2v spec whose `motion` never appeared).
    """
    style = spec.style
    palette = ", ".join(style.palette)
    return {
        "_action": _slot(spec.action or spec.motion),
        "_motion": _slot(spec.motion or spec.action),
        "_palette": f"a palette of {palette}" if palette else "",
        "_light": f"{style.light} light" if style.light else "",
        "_texture": f"{style.texture} texture" if style.texture else "",
        # Mood only. Texture has its own slot in several skeletons, and a
        # "style" clause that repeats it produced "velvet texture, dreamy mood,
        # velvet texture" in one prompt (OBSERVED 2026-08-26).
        "_style": f"{style.mood} mood" if style.mood else "",
        "_setting": style.setting or "",
        "_constraints": ", ".join(spec.constraints),
    }


def gate_spec(spec: GenSpec) -> dict:
    """Refuse a spec the vendor or the product cannot honour. Three outcomes.

    Order is deliberate and is the cheap-before-expensive rule: the banned-topic
    check and the field checks cost microseconds and run before anything that
    might cost a network call or a payment.

    :returns: the studio judging dict; `violations` counts real breaches and
        `unmeasured` counts the checks this registry could not perform.
    """
    problems: list[str] = []
    unknown: list[str] = []
    checked = 0

    if spec.refusal:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": f"the spec is marked refused: {spec.refusal}",
        }

    checked += 1
    if spec.mode not in MODES:
        problems.append(f"mode {spec.mode!r} is not one of {MODES}")

    # The look is gated by its owner's rules, not by a copy of them here.
    style_gate = gate_input(spec.style)
    checked += int(style_gate.get("checked", 0))
    if style_gate["outcome"] == FAIL:
        problems.append(f"the style spec is refused: {style_gate['note']}")
    elif style_gate["outcome"] == UNMEASURED:
        unknown.append(f"the style spec could not be judged: {style_gate['note']}")

    # Free text the user supplied, checked against the same banned lists the
    # studio already enforces. One list, one place.
    for name in ("subject", "action", "camera", "motion", "audio"):
        value = getattr(spec, name)
        if not value:
            continue
        checked += 1
        hits = banned_topics(value)
        if hits:
            problems.append(f"{name} asks for a banned topic ({', '.join(hits)})")
        if len(value) > SLOT_MAX:
            problems.append(f"{name} is {len(value)} chars, the cap is {SLOT_MAX}")

    availability_card = card_for(spec.model)
    checked += 1
    if availability_card is None:
        unknown.append(f"{spec.model!r} is not in the registry: its limits were NOT checked")
    else:
        if spec.mode in (MODE_T2V, MODE_I2V) and availability_card.media != MEDIA_VIDEO:
            problems.append(f"{availability_card.model_id} does not make video")
        if spec.mode == MODE_I2V and not availability_card.reference_skeleton:
            problems.append(f"{availability_card.model_id} has no documented image-to-video mode")
        if spec.audio and not availability_card.audio:
            problems.append(
                f"{availability_card.model_id} generates no audio; the audio slot is dead"
            )
        if spec.duration_seconds is not None:
            fit = fits_duration(spec.model, spec.duration_seconds)
            checked += int(fit["checked"])
            if fit["outcome"] == FAIL:
                problems.append(fit["note"])
            elif fit["outcome"] == UNMEASURED:
                unknown.append(fit["note"])
        if spec.aspect_ratio and availability_card.aspect_ratios:
            checked += 1
            if spec.aspect_ratio not in availability_card.aspect_ratios:
                problems.append(
                    f"{spec.aspect_ratio} is not among {availability_card.model_id}'s "
                    f"aspect ratios {availability_card.aspect_ratios}"
                )

    if problems:
        return {
            "outcome": FAIL,
            "checked": checked,
            "violations": len(problems),
            "unmeasured": len(unknown),
            "note": "; ".join(problems),
        }
    if unknown:
        return {
            "outcome": UNMEASURED,
            "checked": checked,
            "violations": 0,
            "unmeasured": len(unknown),
            "note": "; ".join(unknown),
        }
    return {
        "outcome": PASS,
        "checked": checked,
        "violations": 0,
        "unmeasured": 0,
        "note": f"{checked} checks, nothing to refuse",
    }


def assemble(spec: GenSpec, *, card: ModelCard | None = None) -> dict:
    """Build the prompt this model's own guide asks for. Three outcomes.

    The slot order comes from the card, so a Veo prompt ends with its audio
    cue and a Kling prompt ends with its style clause, because that is what
    each vendor documented. In image-to-video the appearance slots are
    dropped rather than reworded: the reference image already carries them.

    :returns: the judging dict plus `prompt`, `negative_prompt`, `parameters`
        and `slots` — the last so a reviewer can see which slot said what.
    """
    resolved = card or card_for(spec.model)
    if resolved is None:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{spec.model!r} is not in the registry: no skeleton to build against",
            **_EMPTY_DRAFT,
        }

    gate = gate_spec(spec)
    if gate["outcome"] == FAIL:
        return {**gate, **_EMPTY_DRAFT}

    skeleton = (
        resolved.reference_skeleton
        if spec.mode in REFERENCE_MODES and resolved.reference_skeleton
        else resolved.skeleton
    )
    bits = _style_bits(spec)
    slots: dict[str, str] = {}
    # Several vendor slot names read the same GenSpec field — Veo asks for
    # "camera", "composition" and "focus", and one camera description answers
    # all three. Emitting it once per slot name produced the same clause three
    # times in a row (OBSERVED 2026-08-26 on a veo-3.1 t2v spec), which is
    # noise to the model and words against a published length band. First slot
    # to claim a field keeps it.
    claimed: set[str] = set()
    for name in skeleton:
        if spec.mode in REFERENCE_MODES and name in APPEARANCE_SLOTS:
            continue
        sources = resolved.slot_sources.get(name) or (SLOT_BUILDERS.get(name),)
        pieces: list[str] = []
        for source in sources:
            if not source or source in claimed:
                continue
            value = bits[source] if source.startswith("_") else _slot(getattr(spec, source, ""))
            if value:
                claimed.add(source)
                pieces.append(value)
        if pieces:
            slots[name] = ", ".join(pieces)

    if not slots:
        return {
            "outcome": FAIL,
            "checked": len(skeleton),
            "violations": len(skeleton),
            "unmeasured": 0,
            "note": (
                f"every slot of {resolved.model_id}'s skeleton {skeleton} came back empty: "
                "an empty prompt is not a prompt"
            ),
            "prompt": None,
            "negative_prompt": "",
            "parameters": {},
            "slots": {},
        }

    # Identical clauses collapse: two slots resolving to the same words is
    # noise to the model and words against a published length band.
    seen: set[str] = set()
    clauses: list[str] = []
    for name in skeleton:
        clause = slots.get(name) or ""
        if not clause or clause.lower() in seen:
            continue
        seen.add(clause.lower())
        clauses.append(clause)
    body = ", ".join(clauses)

    # Anything the caller filled in that no slot in this skeleton could carry.
    # Silently dropping it is the failure this list exists to prevent: the user
    # asked for a camera move, paid for a render, and never learned that the
    # words went nowhere.
    #
    # Two kinds of drop, and conflating them was a real defect (OBSERVED
    # 2026-08-26: an image-to-video prompt was failed for dropping its subject,
    # which is the documented CORRECT behaviour — the reference image already
    # carries appearance). `dropped` is the bug; `dropped_by_design` is the
    # rule working, and it is reported rather than hidden so a caller can see
    # that their subject text was deliberately not used.
    dropped: list[str] = []
    dropped_by_design: list[str] = []
    reachable: set[str] = set()
    design_only: set[str] = set()
    for name in skeleton:
        for source in resolved.slot_sources.get(name) or (SLOT_BUILDERS.get(name),):
            if source is None:
                continue
            if spec.mode in REFERENCE_MODES and name in APPEARANCE_SLOTS:
                design_only.add(source)
            else:
                reachable.add(source)
    for name, sources in FIELD_SOURCES.items():
        if not getattr(spec, name):
            continue
        if any(source in claimed for source in sources):
            continue
        by_design = spec.mode in REFERENCE_MODES and name in I2V_INTENTIONAL_FIELDS
        by_design = by_design or any(
            source in design_only and source not in reachable for source in sources
        )
        (dropped_by_design if by_design else dropped).append(name)

    # Where the vendor exposes a real negative-prompt field, the constraints
    # go in the field. Where it does not, they go into the prose as the
    # vendor's own guide says to. A parameter beats an adjective.
    negative = ""
    parameters: dict[str, object] = {}
    if spec.constraints:
        if resolved.negative_prompt == "yes":
            negative = ", ".join(spec.constraints)
        elif "constraints" not in skeleton:
            body = f"{body}, {', '.join(spec.constraints)}"
    if spec.duration_seconds is not None:
        parameters["duration_seconds"] = spec.duration_seconds
    if spec.aspect_ratio:
        parameters["aspect_ratio"] = spec.aspect_ratio

    leak: list[str] = []
    if spec.subject_locked:
        leak = subject_leak(body)
        if leak:
            return {
                "outcome": FAIL,
                "checked": len(slots),
                "violations": len(leak),
                "unmeasured": 0,
                "note": (
                    f"the assembled prompt named the subject zone {leak} while the "
                    "subject is locked to the client photo: not shipped"
                ),
                **{**_EMPTY_DRAFT, "slots": slots},
            }

    words = len(body.split())
    band_note = ""
    if resolved.word_band:
        low, high = resolved.word_band
        if not low <= words <= high:
            band_note = (
                f"{words} words is outside {resolved.model_id}'s published {low}-{high} band"
            )

    unmeasured = int(gate["outcome"] == UNMEASURED)
    note = f"{len(slots)} of {len(skeleton)} slots filled, {words} words"
    for piece in (band_note, gate["note"] if unmeasured else ""):
        if piece:
            note = f"{note}; {piece}"

    if dropped:
        note = f"{note}; {len(dropped)} field(s) had nowhere to go: {', '.join(dropped)}"
    if dropped_by_design:
        note = (
            f"{note}; {', '.join(dropped_by_design)} left out on purpose: in "
            "image-to-video the reference image already carries appearance"
        )
    return {
        "outcome": UNMEASURED if unmeasured else PASS,
        "checked": len(skeleton),
        "violations": 0,
        "unmeasured": unmeasured,
        "note": note,
        "prompt": body,
        "negative_prompt": negative,
        "parameters": parameters,
        "slots": slots,
        "dropped": dropped,
        "dropped_by_design": dropped_by_design,
        "words": words,
        "skeleton": list(skeleton),
    }


def studio_prompt(spec: GenSpec) -> dict:
    """Build the studio's own prompt, through the studio's own assembler.

    When the target is the in-house pipeline the look must go through
    `studio.style.build_prompt` and nothing else — that function carries the
    no-brands clause and the subject-zone guard the product depends on. This
    wrapper exists so a caller never has to choose between two assemblers and
    guess which one carries the guard.
    """
    try:
        return {
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "note": "assembled by studio.style.build_prompt",
            "prompt": build_style_prompt(spec.style),
        }
    except ValueError as exc:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": str(exc),
            "prompt": None,
        }


def with_refusal(spec: GenSpec, reason: str) -> GenSpec:
    """Return the same spec marked refused; frozen specs are never mutated."""
    return replace(spec, refusal=reason)


def slots_for(model: str, mode: str) -> Sequence[str]:
    """The slot order this model's guide asks for in this mode."""
    card = card_for(model)
    if card is None:
        return ()
    return (
        card.reference_skeleton if mode == MODE_I2V and card.reference_skeleton else card.skeleton
    )
