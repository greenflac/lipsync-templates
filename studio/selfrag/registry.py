"""What each generation model can be asked for, and how it wants to be asked.

EVIDENCE WARNING, and it is the important part of this file.

Every fact below was gathered on 2026-08-26 by web search. In that session
`WebFetch` was refused by the egress proxy for every primary domain tried
(docs.bfl.ai, ai.google.dev, kling.ai, help.runwayml.com, docs.byteplus.com,
alibabacloud.com, platform.openai.com, arxiv.org). Nobody read a single
vendor document; the facts come from search-result summaries OF those
documents. Per the harness rule on outside claims, every card therefore
carries `confidence` and `sources`, and the highest confidence any card is
allowed today is WEAK.

Read that as: these numbers are good enough to shape a prompt and to refuse
an impossible request, and NOT good enough to bill a customer against. The
`verify_card` hook exists so a later session with real egress can promote a
card to MEASURED without touching any other module.

Design rule: a parameter beats an adjective. Where a model exposes a real
knob for something (Seedance's `camera_fixed`, a seed, a negative prompt
field), the card records the knob, and the assembler prefers it over prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

__all__ = [
    "CONFIDENCE_LEVELS",
    "MODEL_ALIASES",
    "MODEL_CARDS",
    "STATUS_RETIRED",
    "STATUS_SHIPPING",
    "STATUS_SUNSETTING",
    "ModelCard",
    "availability",
    "card_for",
    "fits_duration",
    "known_models",
]

# How much any given card is worth. Nothing is allowed to claim MEASURED until
# somebody has actually opened the vendor's document and written the date here.
CONFIDENCE_WEAK = "weak"  # second-hand summary of a primary source
CONFIDENCE_STRONG = "strong"  # a primary document was read, with a date
CONFIDENCE_LEVELS: tuple[str, ...] = (CONFIDENCE_WEAK, CONFIDENCE_STRONG)

STATUS_SHIPPING = "shipping"
STATUS_SUNSETTING = "sunsetting"  # announced end-of-life, still answering
STATUS_RETIRED = "retired"

MEDIA_IMAGE = "image"
MEDIA_VIDEO = "video"

# The date this file's facts were gathered. Every card is stale relative to
# today by however long this is; `availability` says so out loud.
GATHERED_ON = date(2026, 8, 26)

# CHOSEN: past this many days without re-verification, a card stops being
# treated as current. The video-model field re-versioned roughly every two
# months through 2026 (Kling 3.0 in February, Seedream 5.0 Pro in July), so a
# quarter is already generous.
STALE_AFTER_DAYS = 90


@dataclass(frozen=True)
class ModelCard:
    """One generation model's limits, prompt shape and provenance."""

    model_id: str
    media: str
    status: str
    # The ordered prompt slots the vendor's own guide names, text-to-X.
    skeleton: tuple[str, ...]
    # The slots used when the call starts from a REFERENCE IMAGE — image-to-video
    # for a video model, an edit for an image one. Empty when the model has no
    # such mode. The cross-vendor rule is the same in both: describe what
    # CHANGES, never what the reference already shows.
    #
    # Named for the reference rather than for i2v because an image editor has
    # no "video" in it, and a field called i2v_skeleton on flux-2 simply got
    # left empty — so an edit prompt had nowhere to put the edit and the
    # instruction was dropped (OBSERVED 2026-08-26).
    reference_skeleton: tuple[str, ...] = ()
    max_seconds: float | None = None
    fps: int | None = None
    resolutions: tuple[str, ...] = ()
    aspect_ratios: tuple[str, ...] = ()
    audio: bool = False
    # "yes" | "no" | "unknown" — unknown is a real answer and is not "no".
    negative_prompt: str = "unknown"
    # Real knobs that override prose. name -> what it controls.
    parameters: Mapping[str, str] = field(default_factory=dict)
    # Per-card override of what a named slot is built from, when a vendor packs
    # several things into one slot. Kling's guide defines its "style" slot as
    # camera plus lighting plus mood, so a Kling prompt carries the camera
    # there and not in a slot of its own. Without this the camera text has
    # nowhere to go and is dropped. Source names are `spec` field names, or the
    # underscore-prefixed derived names in `studio.selfrag.spec`.
    slot_sources: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Working word band for the prompt body, or None when nobody published one.
    word_band: tuple[int, int] | None = None
    price_per_second_usd: tuple[float, float] | None = None
    # Documented failure modes, in the words a prompt author can act on.
    quirks: tuple[str, ...] = ()
    # ISO date the vendor turns it off, when one was announced.
    end_of_life: str = ""
    confidence: str = CONFIDENCE_WEAK
    sources: tuple[str, ...] = ()
    note: str = ""


# ---------------------------------------------------------------- the cards

_VEO_31 = ModelCard(
    model_id="veo-3.1",
    media=MEDIA_VIDEO,
    status=STATUS_SHIPPING,
    skeleton=(
        "subject",
        "action",
        "style",
        "camera",
        "composition",
        "focus",
        "ambiance",
        "audio",
    ),
    # Veo is the only card here with audio as a first-class prompt slot.
    reference_skeleton=("action", "camera", "ambiance", "audio"),
    max_seconds=8.0,
    fps=24,
    resolutions=("720p", "1080p", "4k"),
    aspect_ratios=("16:9", "9:16"),
    audio=True,
    negative_prompt="unknown",
    parameters={
        "negativePrompt": "Vertex AI accepts it; the Gemini API's support is undocumented",
        "first_frame": "steer the opening image",
        "last_frame": "steer the closing image",
    },
    word_band=(100, 150),
    price_per_second_usd=(0.15, 0.40),
    quirks=(
        "durations are quantised to 4, 6 or 8 seconds, not free-running",
        "write negatives as nouns ('urban background'), not instructions ('no buildings')",
    ),
    confidence=CONFIDENCE_WEAK,
    sources=(
        "https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1",
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/video-gen-prompt-guide",
        "https://openrouter.ai/google/veo-3.1",
    ),
    note="4K is a premium tier on Vertex/Gemini; price band is Fast..Standard.",
)

_KLING_30 = ModelCard(
    model_id="kling-3.0",
    media=MEDIA_VIDEO,
    status=STATUS_SHIPPING,
    skeleton=("subject", "action", "context", "style"),
    # Kling's own I2V guide collapses the formula to subject + movement.
    reference_skeleton=("subject", "movement"),
    slot_sources={"style": ("camera", "_light", "_texture", "_style")},
    max_seconds=15.0,
    fps=None,
    resolutions=("720p", "1080p", "4k"),
    aspect_ratios=("16:9", "9:16", "1:1"),
    audio=True,
    negative_prompt="yes",
    parameters={
        "negative_prompt": "exposed on the create-task API",
        "character_orientation": "'image' locks likeness to the reference still",
        "ai_director": "up to 6 shots inside one 15s clip, each with its own size and angle",
    },
    word_band=None,
    price_per_second_usd=(0.126, 0.126),
    quirks=(
        "face likeness drifts under Motion Control; a reference where the face fills "
        "more of the frame, or character_orientation=image, is the documented remedy",
        "backgrounds warp and wobble; add 'static background' to the prompt and "
        "'warped background' to the negative prompt",
        "hands mangle when the reference video hides them",
        "text steers background, lighting and style but does NOT override the motion reference",
        "output can come back shorter than the reference under fast or complex motion",
    ),
    confidence=CONFIDENCE_WEAK,
    sources=(
        "https://ir.kuaishou.com/news-releases/news-release-details/kling-ai-launches-30-model-ushering-era-where-everyone-can-be",
        "https://kling.ai/quickstart/text-to-video-prompt-guide",
        "https://kling.ai/quickstart/image-to-video-guide",
    ),
    note=(
        "No evidence of a 'Kling 3.1' was found on 2026-08-26. Asking for it "
        "resolves to nothing rather than silently to 3.0."
    ),
)

_RUNWAY_45 = ModelCard(
    model_id="runway-gen-4.5",
    media=MEDIA_VIDEO,
    status=STATUS_SHIPPING,
    skeleton=("subject", "action", "setting", "camera", "motion", "style", "constraints"),
    reference_skeleton=("motion", "camera"),
    max_seconds=10.0,
    fps=None,
    resolutions=("720p",),
    aspect_ratios=("16:9", "9:16"),
    audio=False,
    negative_prompt="no",
    parameters={},
    # Runway's guide pushes the other way from everyone else: with a strong
    # input image, a SHORTER prompt wins.
    word_band=(10, 60),
    price_per_second_usd=(0.12, 0.12),
    quirks=(
        "no negative-prompt field; the equivalent is a plain-text 'constraints' clause",
        "in image-to-video, never re-describe appearance — call the person 'the subject' "
        "or use a pronoun, and spend the prompt on motion",
        "simpler prompts beat longer ones when the input image is strong",
    ),
    confidence=CONFIDENCE_WEAK,
    sources=(
        "https://help.runwayml.com/hc/en-us/articles/39789879462419-Gen-4-Video-Prompting-Guide",
        "https://help.runwayml.com/hc/en-us/articles/48324313115155-Image-to-Video-Prompting-Guide",
        "https://openrouter.ai/runway/gen-4.5",
    ),
    note=(
        "Sources contradict each other on max resolution (720p vs a '4K' review) "
        "and on the release date (Dec 2025 vs Jul 2026). The card takes the "
        "conservative reading: a limit understated costs a nicer render, a limit "
        "overstated costs a failed paid call."
    ),
)

_WAN_26_FLASH = ModelCard(
    model_id="wan-2.6-flash",
    media=MEDIA_VIDEO,
    status=STATUS_SHIPPING,
    skeleton=("subject", "scene", "motion", "aesthetic", "stylisation"),
    reference_skeleton=("motion", "aesthetic"),
    # Wan's aesthetic-control slot is documented as light source, shot size,
    # perspective, lens and camera movement — one slot, five things.
    slot_sources={"aesthetic": ("_light", "camera")},
    max_seconds=15.0,
    fps=30,
    resolutions=("720p", "1080p"),
    aspect_ratios=("16:9", "9:16"),
    audio=True,
    negative_prompt="yes",
    parameters={"negative_prompt": "supported"},
    word_band=None,
    price_per_second_usd=(0.021, 0.069),
    quirks=(
        "the motion slot carries amplitude and rate explicitly "
        "('swaying violently', 'moving slowly'), not just a verb",
        "audio roughly doubles the price of a call",
    ),
    confidence=CONFIDENCE_WEAK,
    sources=(
        "https://www.alibabacloud.com/help/en/model-studio/text-to-video-prompt",
        "https://wavespeed.ai/models/alibaba/wan-2.6/image-to-video-flash",
        "https://evolink.ai/blog/wan-api-pricing-guide",
    ),
    note="Wan 2.7 and Wan 3 appear to exist; this card is for the version asked for.",
)

_SEEDANCE_20 = ModelCard(
    model_id="seedance-2.0",
    media=MEDIA_VIDEO,
    status=STATUS_SHIPPING,
    skeleton=("subject", "movement", "scene", "shot", "style"),
    reference_skeleton=("movement", "shot"),
    # The conservative end of a contradiction: one source says up to 12s at
    # 1080p, another cites a ByteDance report saying 4-15s at 480p/720p.
    max_seconds=12.0,
    fps=None,
    resolutions=("720p", "1080p"),
    aspect_ratios=("16:9", "9:16", "1:1", "4:3", "3:4"),
    audio=True,
    negative_prompt="unknown",
    parameters={
        "camera_fixed": "a boolean that OVERRIDES any camera language in the prompt",
    },
    word_band=None,
    price_per_second_usd=None,
    quirks=(
        "camera_fixed is a real parameter and beats every camera adjective in the prompt",
        "multi-shot work is prompted as timestamped production notes, not one paragraph",
        "reference limits reported as up to 3 videos, 9 images, 3 audio clips",
    ),
    confidence=CONFIDENCE_WEAK,
    sources=(
        "https://docs.byteplus.com/en/docs/ModelArk/1631633",
        "https://seedance2-video.com/seedance-2-0-specs",
    ),
    note=(
        "UNRESOLVED CONTRADICTION: duration 12s vs 4-15s, resolution 1080p native "
        "vs 480p/720p native, across two readings of the same vendor. Do not bill "
        "against this card. Seedance 2.5 supersedes it."
    ),
)

_FLUX_2 = ModelCard(
    model_id="flux-2",
    media=MEDIA_IMAGE,
    status=STATUS_SHIPPING,
    skeleton=("subject", "composition", "lighting", "texture", "palette", "style"),
    # An edit says what changes and how it should look. Everything the picture
    # already shows is deliberately absent.
    reference_skeleton=("action", "lighting", "style"),
    max_seconds=None,
    fps=None,
    resolutions=("up to 4MP",),
    aspect_ratios=("16:9", "9:16", "1:1", "4:3", "3:4"),
    audio=False,
    negative_prompt="no",
    parameters={
        "steps": "FLUX.2 [flex] exposes it; trades latency against text rendering",
        "guidance": "exposed on [flex]; the dominant artifact knob",
        "references": "up to 10 reference images combined into one output",
    },
    word_band=(30, 120),
    price_per_second_usd=None,
    quirks=(
        "editing takes quoted literals: \"Replace 'old text' with 'new text'\"",
        "preserve identity by saying so: 'while maintaining the same facial features'",
        "decompose a drastic edit into sequential smaller edits",
    ),
    confidence=CONFIDENCE_WEAK,
    sources=(
        "https://bfl.ai/blog/flux-2",
        "https://docs.bfl.ai/kontext/kontext_image_editing",
        "https://github.com/black-forest-labs/flux2",
    ),
    note=(
        "The one architecture claim in this file with a named primary source: a "
        "rectified-flow transformer (32B) coupled to a Mistral-3 24B VLM, one "
        "checkpoint for both generation and editing. Still second-hand."
    ),
)

_SORA_2 = ModelCard(
    model_id="sora-2",
    media=MEDIA_VIDEO,
    status=STATUS_SUNSETTING,
    skeleton=("subject", "action", "setting", "camera", "style"),
    reference_skeleton=(),
    max_seconds=None,
    fps=None,
    resolutions=(),
    aspect_ratios=(),
    audio=True,
    negative_prompt="unknown",
    parameters={},
    word_band=None,
    price_per_second_usd=(0.10, 0.70),
    quirks=("the consumer app was withdrawn on 2026-04-26; only the API remained",),
    end_of_life="2026-09-24",
    confidence=CONFIDENCE_WEAK,
    sources=(
        "https://help.openai.com/en/articles/20001152-what-to-know-about-the-sora-discontinuation",
        "https://the-decoder.com/openai-sets-two-stage-sora-shutdown-with-app-closing-april-2026-and-api-following-in-september/",
    ),
    note=(
        "The popular framing 'OpenAI shut down Sora in April' is half right: the "
        "app went on 2026-04-26, the API is scheduled to go on 2026-09-24. Its "
        "duration, resolution and fps limits could not be sourced at all — the "
        "primary page is partly withdrawn."
    ),
)

MODEL_CARDS: dict[str, ModelCard] = {
    card.model_id: card
    for card in (_VEO_31, _KLING_30, _RUNWAY_45, _WAN_26_FLASH, _SEEDANCE_20, _FLUX_2, _SORA_2)
}

# Short names people actually type. A name NOT in this table and not a card id
# resolves to nothing — it never falls back to "something similar", because a
# prompt built to the wrong model's limits fails at the vendor, after payment.
MODEL_ALIASES: dict[str, str] = {
    "veo": "veo-3.1",
    "veo3": "veo-3.1",
    "veo-3": "veo-3.1",
    "kling": "kling-3.0",
    "kling-3": "kling-3.0",
    "kling3": "kling-3.0",
    "runway": "runway-gen-4.5",
    "gen-4.5": "runway-gen-4.5",
    "gen4.5": "runway-gen-4.5",
    "wan": "wan-2.6-flash",
    "wan-2.6": "wan-2.6-flash",
    "seedance": "seedance-2.0",
    "flux": "flux-2",
    "flux-kontext": "flux-2",
    "sora": "sora-2",
}


def known_models() -> tuple[str, ...]:
    """Every model id this registry can build a prompt for."""
    return tuple(sorted(MODEL_CARDS))


def card_for(name: str) -> ModelCard | None:
    """Resolve a model name to its card, or None.

    None is the honest answer for a name nobody verified exists — 'kling-3.1'
    is the live example. Guessing the nearest card would build a prompt against
    limits that were never checked.

    >>> card_for("KLING").model_id
    'kling-3.0'
    >>> card_for("kling-3.1") is None
    True
    """
    key = (name or "").strip().lower()
    if key in MODEL_CARDS:
        return MODEL_CARDS[key]
    alias = MODEL_ALIASES.get(key)
    return MODEL_CARDS.get(alias) if alias else None


def availability(name: str, *, today: date | None = None) -> dict:
    """Say whether this model can be called today, and how stale the card is.

    Three outcomes:

    * `fail` — the model is retired, or its announced end-of-life has passed.
      Spending money on this call is spending it on a 404.
    * `could not measure` — the name is unknown, or the card is older than
      `STALE_AFTER_DAYS`. An unknown name is NOT a failure of the request; it
      is a failure of this registry to know, and those are different bills.
    * `pass` — callable, with the caveats in `note`.

    >>> availability("sora-2", today=date(2026, 12, 1))["outcome"]
    'fail'
    >>> availability("kling-3.1")["outcome"]
    'could not measure'
    """
    now = today or date.today()
    card = card_for(name)
    if card is None:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"{name!r} is not in the registry. Known: {', '.join(known_models())}. "
                "Nothing was checked, which is not the same as nothing being wrong."
            ),
            "card": None,
        }

    age_days = (now - GATHERED_ON).days
    stale = age_days > STALE_AFTER_DAYS
    warnings: list[str] = []
    if card.confidence == CONFIDENCE_WEAK:
        warnings.append("card is second-hand: no vendor document was read")
    if stale:
        warnings.append(f"card is {age_days} days old, past the {STALE_AFTER_DAYS}-day limit")
    if card.note:
        warnings.append(card.note)

    if card.status == STATUS_RETIRED:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": f"{card.model_id} is retired; " + "; ".join(warnings),
            "card": card,
        }
    if card.end_of_life:
        eol = date.fromisoformat(card.end_of_life)
        if now >= eol:
            return {
                "outcome": FAIL,
                "checked": 1,
                "violations": 1,
                "unmeasured": 0,
                "note": f"{card.model_id} reached end of life on {card.end_of_life}",
                "card": card,
            }
        warnings.insert(0, f"end of life {card.end_of_life}, {(eol - now).days} days away")
    if stale:
        return {
            "outcome": UNMEASURED,
            "checked": 1,
            "violations": 0,
            "unmeasured": 1,
            "note": "; ".join(warnings),
            "card": card,
        }
    return {
        "outcome": PASS,
        "checked": 1,
        "violations": 0,
        "unmeasured": 0,
        "note": "; ".join(warnings) or "callable",
        "card": card,
    }


def fits_duration(name: str, seconds: float) -> dict:
    """Check a requested clip length against the card. Three outcomes.

    A card with no published maximum returns `could not measure` — the request
    is not approved and not refused, and the caller is told which.
    """
    card = card_for(name)
    if card is None:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{name!r} is not in the registry",
        }
    if card.media != MEDIA_VIDEO:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": f"{card.model_id} makes {card.media}s; a duration does not apply",
        }
    if card.max_seconds is None:
        return {
            "outcome": UNMEASURED,
            "checked": 1,
            "violations": 0,
            "unmeasured": 1,
            "note": f"no maximum duration could be sourced for {card.model_id}",
        }
    if seconds > card.max_seconds:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": f"{seconds}s exceeds {card.model_id}'s {card.max_seconds}s limit",
        }
    return {
        "outcome": PASS,
        "checked": 1,
        "violations": 0,
        "unmeasured": 0,
        "note": f"{seconds}s fits {card.model_id}'s {card.max_seconds}s limit",
    }
