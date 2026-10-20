"""Round 16: the readers of the decision fields round 15 left to EN/RU words.

The product contract: the CALLING model fills `spec` (it reads the brief in any
language) and the plan is built from spec. Round 15 moved the round 13-14
decisions to spec fields; the expert caveats of `studio/recipes/checklist.py`
and the recipe words of `studio/recipes/apply.py` stayed keyword lists, so the
same order in Spanish or German lost its caveat or step (a halftone scan with no
descreen note, passers-by anonymised with no model and no GDPR note, a witness
whose voice was dubbed instead of replaced, a no-speech short with no note).

Every reader here answers True / False when the caller NAMED the field and None
when it did not — None is the only case in which the words are read
(`checklist.SPEC_FOR_WORDS`, `apply.*`). A named field wins over the words both
ways: `delivery.platform: ["youtube"]` silences the broadcast caveat whatever
the brief says, `["broadcast"]` fires it in a brief with no English word.

The fields (`brief_spec.SPEC_FIELDS`, round 16): `anonymise`, `voiceover`,
`delivery` {platform, dynamic_range, stems, direction, format}, `domain`,
`style`, `subject`, `accessibility`, `display`, `audio_content`,
`follows_picture`, `community`; in the input records `inputs[].source`,
`inputs[].defects`, `inputs[].fps`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

#: Platforms whose caveat set is the social / short-form one (`brief_spec.SOCIAL_PLATFORMS`).
SOCIAL = ("youtube", "youtube-shorts", "tiktok", "instagram", "reels")
#: Advertising domains (`brief_spec.AD_DOMAINS`): any of them is advertising.
ADVERTISING = ("advertising", "health-advertising", "financial-advertising", "branded-content")
#: 3D formats (`brief_spec.MESH_FORMATS`).
MESH = ("glb", "gltf", "usdz", "obj", "fbx")
#: Audio defects that make a clean-up chain (`brief_spec.AUDIO_DEFECTS`).
AUDIO_DEFECTS = ("noise", "hum", "echo")
#: Styles whose faces are drawn / stylised (a photoreal face model is the wrong tool).
STYLISED_STYLES = ("stylised", "limited-animation")


def named(spec: Any, name: str) -> bool:
    """The caller named this top-level field (an empty list counts: «none of these»)."""
    return name in (getattr(spec, "source", None) or {})


def _has_any(values: Iterable[str], wanted: Iterable[str]) -> bool:
    return bool(set(values) & set(wanted))


def _list(spec: Any, name: str, *wanted: str) -> bool | None:
    """A named list field (`domain`, `subject`, …) holds one of `wanted`; None — not named."""
    if not named(spec, name):
        return None
    return _has_any(getattr(spec, name, None) or (), wanted)


def domain(spec: Any, *wanted: str) -> bool | None:
    return _list(spec, "domain", *wanted)


def advertising(spec: Any) -> bool | None:
    return domain(spec, *ADVERTISING)


def subject(spec: Any, *wanted: str) -> bool | None:
    return _list(spec, "subject", *wanted)


def audio_content(spec: Any, *wanted: str) -> bool | None:
    return _list(spec, "audio_content", *wanted)


def accessibility(spec: Any, *wanted: str) -> bool | None:
    """`spec.accessibility` names a need (any need when `wanted` is empty); None — not named."""
    if not named(spec, "accessibility"):
        return None
    нужды = set(getattr(spec, "accessibility", None) or ())
    return bool(нужды & set(wanted)) if wanted else bool(нужды)


def style(spec: Any, *wanted: str) -> bool | None:
    стиль = getattr(spec, "style", None)
    return None if стиль is None else стиль in wanted


def display_additive(spec: Any) -> bool | None:
    экран = getattr(spec, "display", None)
    return None if экран is None else экран == "additive"


def _delivery(spec: Any) -> Mapping[str, Any]:
    сдача = getattr(spec, "delivery", None)
    return сдача if isinstance(сдача, Mapping) else {}


def platform(spec: Any, *wanted: str) -> bool | None:
    """`spec.delivery.platform` holds one of `wanted`; None — no platform named."""
    площадки = _delivery(spec).get("platform")
    if not площадки:
        return None
    return _has_any(площадки, wanted)


def social(spec: Any) -> bool | None:
    return platform(spec, *SOCIAL)


def dynamic_range_hdr(spec: Any) -> bool | None:
    д = _delivery(spec).get("dynamic_range")
    return None if д is None else д == "hdr"


def stems(spec: Any) -> bool | None:
    с = _delivery(spec).get("stems")
    return с if isinstance(с, bool) else None


def outbound(spec: Any) -> bool | None:
    н = _delivery(spec).get("direction")
    return None if н is None else н == "outbound"


def mesh_format(spec: Any) -> bool | None:
    форматы = _delivery(spec).get("format")
    if not форматы:
        return None
    return _has_any(форматы, MESH)


def _input_values(spec: Any, key: str) -> list[str] | None:
    """All values of `inputs[].<key>` (None — no input record names the key)."""
    записи = [з for з in getattr(spec, "input_items", None) or () if isinstance(з, Mapping) and key in з]
    if not записи:
        return None
    return [str(в) for з in записи for в in (з.get(key) or ())]


def input_source(spec: Any, *wanted: str) -> bool | None:
    """An input record's `source` holds one of `wanted`; None — no input names its source."""
    значения = _input_values(spec, "source")
    return None if значения is None else _has_any(значения, wanted)


def input_defect(spec: Any, *wanted: str) -> bool | None:
    значения = _input_values(spec, "defects")
    return None if значения is None else _has_any(значения, wanted)


def halftone(spec: Any) -> bool | None:
    """A print scan with a halftone screen: `inputs[].defects` first, then `inputs[].source` = print-scan."""
    дефект = input_defect(spec, "halftone")
    if дефект is not None:
        return дефект
    return input_source(spec, "print-scan")


def noisy_audio(spec: Any) -> bool | None:
    return input_defect(spec, *AUDIO_DEFECTS)


def blurred(spec: Any) -> bool | None:
    return input_defect(spec, "blur")


def input_fps(spec: Any) -> float | None:
    """The lowest `inputs[].fps` named (cine film at 16-18 fps), or None."""
    частоты = [float(з["fps"]) for з in getattr(spec, "input_items", None) or () if isinstance(з, Mapping) and з.get("fps")]
    return min(частоты) if частоты else None


def flag(spec: Any, name: str) -> bool | None:
    """A boolean top-level field (`voiceover`, `follows_picture`, `community`): as named, or None."""
    значение = getattr(spec, name, None)
    return значение if isinstance(значение, bool) else None


# --- anonymisation -------------------------------------------------------------------------


def anonymise(spec: Any) -> Mapping[str, Any] | None:
    """`spec.anonymise` as parsed ({faces, voice, method}); None — not named."""
    анон = getattr(spec, "anonymise", None)
    return анон if isinstance(анон, Mapping) else None


def anonymise_faces(spec: Any) -> str | None | bool:
    """The face method named ('swap' | 'blur' | 'pixelate'); False — named, no faces; None — not named."""
    анон = anonymise(spec)
    if анон is None:
        return None
    return str(анон.get("method") or "swap") if анон.get("faces") else False


def anonymise_voice(spec: Any) -> bool | None:
    анон = anonymise(spec)
    return None if анон is None else bool(анон.get("voice"))


def anonymise_any(spec: Any) -> bool | None:
    анон = anonymise(spec)
    return None if анон is None else bool(анон.get("faces") or анон.get("voice"))


# --- speech in the deliverable ---------------------------------------------------------------


def no_speech(spec: Any) -> bool | None:
    """The deliverable carries NO spoken words — by the fields; None — the fields do not say.

    `voiceover` first (false = no narration, no voice-over, nobody speaks), then `audio_content` (named
    without speech), then `people[].speaks` (all false). Structure alone (a cut from the customer's own
    footage, no speech output) does NOT decide: a vlog cut keeps the vlogger's voice.
    """
    голос = flag(spec, "voiceover")
    if голос is not None:
        return not голос
    звук = audio_content(spec, "speech")
    if звук is not None:
        return not звук
    говорят = [п.get("speaks") for п in getattr(spec, "people", None) or () if isinstance(п, Mapping) and п.get("speaks") is not None]
    if говорят:
        return all(г is False for г in говорят)
    return None
