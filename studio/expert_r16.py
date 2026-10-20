"""Round 16: model expertise and pricing the hidden set found missing.

Every decision reads a structured spec field first and the brief's words (EN/RU) only
when the field is absent; a named field beats the words both ways (docs/MCP_AGENT.md,
"decisions read from the spec first").

1. OPEN WEIGHTS WITHOUT AN API ROUTE — `spec.open_weights` (no `self_host`) on a job whose
   open-weights models are only weights (Whisper / faster-whisper / Parakeet for ASR):
   the step runs them on the customer's GPU instead of returning no model
   (`open_weights_route`). Sensitive material (court, medical, confidential) carries the
   self-host caveat (`checklist.confidential_transcription`).
2. TEXT-HEAVY STILLS — a poster, packaging, signage or any picture with exact lettering
   is ranked by the RECORDED text rendering of each model (`text_heavy` adds the
   `text_legibility` condition, so a model with a "for" row outranks silence and a
   recorded failure ranks last).
3. SPATIAL AUDIO — `outputs[].spatial` (or the words) carries the ambisonics / binaural
   caveat (`spatial_audio`).
4. EDIT TIERS — a video edit takes the cheapest candidate of the SAME evidence band whose
   frame is not below the order, unless `objective: quality` (`edit_tier_applies`).
5. BATCHES — a lip-sync / talking-avatar batch of `BATCH_CLIPS_MIN`+ clips takes the
   cheapest adequate candidate when the chosen one costs more than `BATCH_CHEAP_RATIO`x
   (`batch_cheap_applies`), unless `objective: quality`.
6. SERIES — a narrated multi-shot series without characters is made from key visuals
   (`key_visual_series`: text-to-image per shot, then image-to-video); a narrator off screen
   ("за кадром", "рассказчик", `people[].on_screen: false`) is never lip-synced.
7. DRAWN DUBS — dubbing anime / cartoon footage adapts the script to the existing mouth
   flaps; visual lip sync is an OPTIONAL upgrade priced apart from the plan
   (`optional_lips`), required only when `spec.lipsync` is true.

DECISION CONSTANTS (mutated both ways by `scripts/mutate_round16_knowledge.py`):
`KEY_VISUAL_SHOTS_MIN`, `BATCH_CLIPS_MIN`, `BATCH_CHEAP_RATIO`, `EDIT_TIER_RATIO`, `EDIT_TIER_STEPS`,
`BATCH_STEPS`, `BATCH_TASKS`, `OPTIONAL_LIPS_STEP`.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

# --- 1. open weights without an API route ------------------------------------------------


def open_weights_route(hard: Any) -> Any | None:
    """`Hard` with the own-GPU route switched on when open weights were asked without `self_host`.

    None — nothing to switch (no open-weights requirement, or `self_host` already named).
    The caller asks for it only when the API-only search found NO candidate: weights that
    nobody hosts are still a route — on the customer's GPU.
    """
    if hard is None or not getattr(hard, "open_weights", False) or getattr(hard, "self_host", False):
        return None
    источники = dict(getattr(hard, "sources", ()) or ())
    источники["self_host"] = OPEN_WEIGHTS_SOURCE
    return replace(hard, self_host=True, sources=tuple(sorted(источники.items())))


#: Where the own-GPU route came from (`Hard.sources["self_host"]`).
OPEN_WEIGHTS_SOURCE = "open weights asked, no API route of the job"

#: Material whose transcript must not leave the customer's control (the words; the field is
#: `self_host` / `open_weights` / `jurisdiction`).
W_SENSITIVE = re.compile(
    r"\bcourt\b|courtroom|hearing|deposition|tribunal|legal|lawyer|attorney|privileged|litigation|evidence"
    r"|medical|clinical|patient|doctor|therap\w*|hipaa|\bphi\b|health record"
    r"|confidential|classified|\bnda\b|on[- ]?prem\w*|air[- ]?gapped|must not leave|stay on our (?:servers?|machines?)"
    r"|суд\w*|заседани\w*|адвокат\w*|юридическ\w*|допрос\w*|медицинск\w*|пациент\w*|врач\w*|приём\w* врача|прием\w* врача"
    r"|конфиденциальн\w*|секретн\w*|врачебн\w* тайн\w*|на наших серверах|не должн\w* покидать",
    re.I,
)


def sensitive_material(spec: Any, text: str = "") -> bool:
    """The material is sensitive: the own-GPU / open-weights fields, else the words."""
    if getattr(spec, "self_host", None) or getattr(spec, "open_weights", False):
        return True
    слова = " ".join((str(text or ""), *map(str, getattr(spec, "conditions", None) or ())))
    return bool(W_SENSITIVE.search(слова))


# --- 2. text-heavy stills -----------------------------------------------------------------

#: The condition a text-heavy picture is ranked by (`attrfamily.УСЛОВИЯ`).
TEXT_CONDITION = "text_legibility"
#: Pictures whose job IS lettering (EN/RU; the caller's `conditions` in any language are read
#: through `attrfamily.УСЛОВИЯ_СИНОНИМЫ` first).
W_TEXT_HEAVY = re.compile(
    r"\bposters?\b|\bflyers?\b|\bbanners?\b|billboard|signage|\bsigns?\b|storefront sign|\bmenus?\b|infographic"
    r"|packag\w*|\blabels?\b|book cover|magazine cover|album cover|\bheadline|lettering|typograph\w*|\bslogan"
    r"|wordmark|exact (?:text|wording|spelling)|with the (?:text|words|title)|says? [\"'“«]"
    r"|постер\w*|афиш\w*|плакат\w*|флаер\w*|баннер\w*|вывеск\w*|меню\b|инфографик\w*|упаковк\w*|этикетк\w*"
    r"|обложк\w*|заголов\w*|надпис\w*|слоган\w*|леттеринг\w*|типографик\w*|с текстом",
    re.I,
)
#: A quoted string in an image brief is the lettering to render — the same in any language.
QUOTED_TEXT = re.compile(r"[\"“„«「『‘][^\"”“»」』’\n]{2,80}[\"”“»」』’]|(?:^|\s)'[^'\n]{2,80}'(?=$|[\s.,!?;:])")


def text_heavy(spec: Any, text: str = "", steps: Any = ()) -> bool:
    """A still whose job is exact lettering: `conditions` first (any language), then the words."""
    if "image" not in set(getattr(spec, "outputs", ()) or ()) and "генерация_изображения" not in set(steps or ()):
        return False
    from studio.mcp import capability as cap

    понятые, _ = cap.conditions_of([str(у) for у in getattr(spec, "conditions", None) or ()])
    if TEXT_CONDITION in понятые:
        return True
    return bool(W_TEXT_HEAVY.search(text or "") or QUOTED_TEXT.search(text or ""))


# --- 3. spatial audio ---------------------------------------------------------------------

W_SPATIAL = re.compile(
    r"spatial (?:audio|sound|ambien\w*)|ambisonic\w*|binaural|\bhrtf\b|head[- ]?track\w*|dolby atmos|\batmos\b"
    r"|\b360(?:°|-degree| degree)?\s*(?:audio|sound|video|vr|ambien\w*)|\bvr\b|virtual reality|immersive (?:audio|sound)"
    r"|\bfoa\b|first[- ]order ambisonic|surround sound|\b[57]\.1(?:\.[24])? (?:surround|mix|audio)"
    r"|объёмн\w* звук\w*|объемн\w* звук\w*|пространственн\w* (?:звук|аудио)\w*|амбисони\w*|бинаурал\w*|\bвр\b|виртуальн\w* реальност\w*",
    re.I,
)
#: Outputs that are sound (`spec.outputs`).
AUDIO_OUTPUTS = frozenset({"sfx", "music", "speech"})


def spatial_audio(spec: Any, text: str = "") -> bool:
    """Spatial delivery of sound: `outputs[].spatial` decides when named, else the words."""
    if not (set(getattr(spec, "outputs", ()) or ()) & AUDIO_OUTPUTS):
        return False
    поле = getattr(spec, "spatial", None)
    if isinstance(поле, bool):
        return поле
    слова = " ".join((str(text or ""), *map(str, getattr(spec, "conditions", None) or ())))
    return bool(W_SPATIAL.search(слова))


# --- 4. edit tiers / 5. batches -------------------------------------------------------------

#: Steps whose tiers (model or resolution tier) are chosen at the cheapest adequate band.
EDIT_TIER_STEPS: frozenset[str] = frozenset({"правка_видео"})
#: Steps priced per clip in a batch where the cheapest adequate model is taken.
BATCH_STEPS: frozenset[str] = frozenset({"липсинк", "говорящий_аватар"})
#: A batch starts at this many clips.
BATCH_CLIPS_MIN = 3
#: In a batch the chosen model gives way to the cheapest adequate one when dearer by more than this.
BATCH_CHEAP_RATIO = 1.5
#: The objective that keeps the premium choice.
QUALITY = "quality"


def edit_tier_applies(step: str, objective: str) -> bool:
    """A video edit takes the cheapest adequate candidate of its band unless quality is asked."""
    return step in EDIT_TIER_STEPS and objective != QUALITY


#: A video edit gives way to a cheaper tier of its band only when that saves this much (x); a few
#: cents are not worth trading a model whose output frame is on record.
EDIT_TIER_RATIO = 1.5


def edit_tier_worth(chosen_usd: float, cheaper_usd: float) -> bool:
    """The premium tier costs more than `EDIT_TIER_RATIO` x the cheaper adequate one."""
    return cheaper_usd > 0 and chosen_usd > EDIT_TIER_RATIO * cheaper_usd


def batch_ratio_exceeded(chosen_usd: float, cheapest_usd: float) -> bool:
    """The chosen model costs more than `BATCH_CHEAP_RATIO` x the cheapest adequate one."""
    return cheapest_usd > 0 and chosen_usd > BATCH_CHEAP_RATIO * cheapest_usd


#: Tasks whose deliverable IS the talking clip — N of them is a batch of separate clips (UGC ads),
#: not the shots of one generated film (whose lip sync follows the film's own selection).
BATCH_TASKS: frozenset[str] = frozenset({"avatar", "lipsync", "sing-photo"})


def batch_cheap_applies(step: str, clips: int, objective: str, task: str | None = None) -> bool:
    """A lip-sync / avatar batch takes the cheapest adequate candidate unless quality is asked."""
    return (
        step in BATCH_STEPS
        and task in BATCH_TASKS
        and int(clips or 0) >= BATCH_CLIPS_MIN
        and objective != QUALITY
    )


#: (ru, en) why the step was re-selected (`budget_swap.reason`).
REASON_EDIT_TIER = (
    "правка без заказа премиума: самый дешёвый годный тариф той же полосы доводов",
    "an edit with no premium asked: the cheapest adequate tier of the same evidence band",
)
REASON_BATCH = (
    "пачка роликов: самый дешёвый годный кандидат на каждый ролик",
    "a batch of clips: the cheapest adequate candidate for every clip",
)

#: A candidate priced on a tier BELOW the ordered frame (`pricing`: «… ниже заказанного … — нужен апскейл»).
BELOW_FRAME_MARK = "нужен апскейл"


def adequate_frame(candidate: Any) -> bool:
    """The candidate's priced tier reaches the ordered frame (not «below — upscaling needed»)."""
    if getattr(candidate, "below_frame", False):
        return False
    стоимость = getattr(candidate, "cost", None)
    формула = str(getattr(getattr(стоимость, "default", None), "formula", "") or "")
    return BELOW_FRAME_MARK not in формула


# --- 6. series ----------------------------------------------------------------------------

#: A generated narrated piece of this many shots is built from key visuals.
KEY_VISUAL_SHOTS_MIN = 4
#: Words of a series or an explainer (EN/RU) — read only when `spec.consistency` is not named.
W_SERIES_EXPLAINER = re.compile(
    r"\bseries\b|\bepisodes?\b|explainer\w*|\bexplains?\b|how[- ]to video|tutorial\w*|product tour"
    r"|сериал\w*|\bсери[яиюей]\b|эпизод\w*|объясн\w*|обучающ\w*|туториал\w*",
    re.I,
)


def key_visual_series(spec: Any) -> bool:
    """A generated video of designed shots with one look: key visuals first (t2i per shot), then i2v."""
    if getattr(spec, "task", None) not in (None, "generate") or "video" not in set(spec.outputs):
        return False
    if set(spec.inputs) & {"photo", "video"} or (spec.characters or 0) >= 1:
        return False
    if int(spec.shots or 0) < KEY_VISUAL_SHOTS_MIN:
        return False
    if any(п.get("on_screen") is True and п.get("speaks") is True for п in spec.people):
        return False
    return "style" in {str(к).lower() for к in (getattr(spec, "consistency", None) or ())}


def key_visual_words(spec: Any, text: str = "") -> bool:
    """The words call a narrated multi-shot piece a series / an explainer (field `consistency` absent)."""
    if "consistency" in dict(getattr(spec, "source", {}) or {}):
        return False
    if "speech" not in set(spec.outputs):
        return False
    return bool(W_SERIES_EXPLAINER.search(" ".join((str(text or ""), *map(str, spec.conditions)))))


# --- 7. drawn dubs --------------------------------------------------------------------------

#: The step that becomes an optional upgrade on a drawn dub.
OPTIONAL_LIPS_STEP = "липсинк"


def optional_lips(spec: Any, drawn: bool) -> bool:
    """Drawn footage dub: visual lip sync is an OPTIONAL upgrade unless `spec.lipsync` is true."""
    return getattr(spec, "task", None) == "dub-translate" and drawn and getattr(spec, "lipsync", None) is not True


#: (ru, en) lines this module adds to plans (localised through `studio/l10n.py`).
NOTE_DRAWN_ADAPT = (
    "рисованный ролик: дубляж ведётся адаптацией текста под существующие рты (длина реплик и открытые гласные "
    "под артикуляцию, как в студиях дубляжа аниме), губы не перерисовываются; визуальный липсинк — "
    "НЕОБЯЗАТЕЛЬНОЕ улучшение, его цена указана отдельно и в цену плана не входит",
    "drawn footage: the dub adapts the script to the existing mouth flaps (line length and open vowels matched "
    "to the articulation, as anime dubbing studios do) and the mouths are not redrawn; visual lip sync is an "
    "OPTIONAL upgrade priced separately, not in the plan price",
)
NOTE_OPTIONAL_STEP = (
    "НЕОБЯЗАТЕЛЬНО: улучшение по желанию — в цену ролика и вердикт бюджета не входит",
    "OPTIONAL: an upgrade on request — not in the clip price or the budget verdict",
)
NOTE_KEY_VISUALS = (
    "ключевые кадры серии: по картинке на шот в одном стиле (утверждаются до видео), затем каждый оживляется",
    "key visuals of the series: one still per shot in one look (approved before any video), then each is animated",
)
ASSUMPTION_KEY_VISUALS = (
    "a narrated series / explainer of {n} shots: one look across the shots is assumed (consistency=['style']) — "
    "key visuals first, then image-to-video; pass spec.consistency to override"
)
NOTE_OPEN_WEIGHTS_GPU = (
    "открытые веса без API-маршрута: шаг идёт на вашем GPU (API 0 usd), время GPU — отдельной оценкой",
    "open weights with no API route: the step runs on your GPU (API 0 usd), GPU time is a separate estimate",
)

NOTE_PAIRS: tuple[tuple[str, str], ...] = (NOTE_DRAWN_ADAPT, NOTE_OPTIONAL_STEP, NOTE_KEY_VISUALS, NOTE_OPEN_WEIGHTS_GPU)
