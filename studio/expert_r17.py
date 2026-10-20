"""Round 17: specialist knowledge and pricing the hidden set found missing.

Every decision reads a structured spec field first and the brief's words (EN/RU) only
when the field is absent; a named field beats the words both ways (docs/MCP_AGENT.md,
"decisions read from the spec first"). Nothing here adds a spec field: the readers use
the fields rounds 15-16 already carry (`accessibility`, `delivery.platform|markets|stems`,
`domain`, `training_use`, `audience`, `people`, `inputs[].fps|source`, `fps`, `audio`,
`edit_target`, `edit`, `languages`, `conditions`).

CAVEATS (`checklist.RULES_R17`):
1. AUDIO DESCRIPTION as a production: a script written to the gaps in dialogue, a voice
   distinct from the cast, ducking, its own stem / language track (`audio_description`).
2. CODE-SWITCHING speech — two languages inside one utterance (`code_switching`).
3. PROVIDER DATA TERMS — client, personal or confidential material uploaded to a hosted
   API: retention, training, region, DPA (`provider_data_terms`).
4. HIGHLIGHT SELECTION for recaps and clips: shot detection + transcript, a human pick,
   reframing (`highlight_selection`).
5. FRAME-RATE STANDARDS CONVERSION (25 <-> 29.97 / 23.976, interlace, pulldown) read from
   `inputs[].fps` against `fps` / `delivery.markets` (`standards_conversion`).
6. STEM SEPARATION of a mixed track (`stem_separation`).
7. MATTE / DEPTH BLUR of the customer's own footage (`background_blur`).

PRICING (`recipes.apply.rewrite`, round 17):
a. an accessibility package with audio description on the customer's video: the transcript
   is made ONCE (captions and translation reuse it) and the description voice is priced for
   the GAPS it fills (`AD_GAP_SHARE` of the runtime), not for the runtime (`ad_voice_seconds`);
b. a recap / highlight cut of the customer's series with a narrator: an edit of own footage
   plus a short voice-over priced by the RECAP length, not the series (`recap_vo_seconds`);
c. a background blur (bokeh) of the customer's footage: a matte (background-removal) pass
   and the blur at assembly — never a generative video edit (`background_blur`).

DECISION CONSTANTS (mutated both ways by `scripts/mutate_round17_knowledge.py`):
`AD_GAP_SHARE`, `AD_TASKS`, `RECAP_TASKS`, `NTSC_MARKETS`, `CONVERSION_PLATFORMS`,
`CONFIDENTIAL_DOMAINS`, `UPLOAD_INPUTS`, `EDIT_BLUR_BACKGROUND`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from studio import spec_first as sf

# --- shared readers --------------------------------------------------------------------------


def _words(spec: Any, text: str = "") -> str:
    """The brief's words with the caller's conditions and input notes (lower case)."""
    части = [str(text or "")]
    части += [str(у) for у in getattr(spec, "conditions", None) or ()]
    части += [str(з.get("note") or "") for з in getattr(spec, "input_items", None) or () if isinstance(з, Mapping)]
    return " ".join(" ".join(части).lower().split())


def _inputs(spec: Any) -> set[str]:
    return set(getattr(spec, "inputs", None) or ())


def _outputs(spec: Any) -> set[str]:
    return set(getattr(spec, "outputs", None) or ())


# --- 1. audio description ------------------------------------------------------------------------

#: Audio description named in words (EN/RU) — read only when `spec.accessibility` is not named.
W_AUDIO_DESCRIPTION = re.compile(
    r"audio[- ]descri\w*|described (?:video|version)|descriptive (?:audio|video|narration)"
    r"|for (?:the )?blind|visually impaired|тифлокомментар\w*|аудиодескрипц\w*|для незрячих|для слабовидящих",
    re.I,
)
#: Tasks of an accessibility package on the customer's video (the AD voice is added to them).
AD_TASKS: frozenset[str | None] = frozenset({"captions", "transcribe"})
#: Share of the runtime that the description voice fills (the gaps between speech), priced instead of
#: the runtime. An engineering prior: dense speech (a lecture) leaves short gaps; the plan states it.
AD_GAP_SHARE = 0.15


def audio_description(spec: Any, text: str = "") -> bool:
    """Audio description is ordered: `spec.accessibility` first, then the words."""
    if not ({"video"} & (_inputs(spec) | _outputs(spec))):
        return False
    поле = sf.accessibility(spec, "audio-description")
    if поле is not None:
        return поле
    return bool(W_AUDIO_DESCRIPTION.search(_words(spec, text)))


def material_seconds(spec: Any) -> float:
    """Seconds of the customer's video material (every input x its count), else `duration_s`."""
    всего = sum(
        float(з.get("duration_s") or 0.0) * int(з.get("count") or 1)
        for з in getattr(spec, "input_items", None) or ()
        if isinstance(з, Mapping) and з.get("kind") in ("video", "audio")
    )
    return всего or float(getattr(spec, "duration_s", None) or 0.0)


def ad_voice_seconds(runtime_s: float) -> float:
    """Seconds of description voice for a runtime: only the gaps it fills."""
    return round(max(0.0, float(runtime_s or 0.0)) * AD_GAP_SHARE, 1)


def ad_package(spec: Any, text: str = "") -> bool:
    """An accessibility package on the customer's video (captions / transcript) that orders AD."""
    return getattr(spec, "task", None) in AD_TASKS and "video" in _inputs(spec) and audio_description(spec, text)


# --- 2. code-switching --------------------------------------------------------------------------

#: Two languages inside one utterance (EN/RU words; the caller's `conditions` are read too).
W_CODE_SWITCH = re.compile(
    r"code[- ]?switch\w*|code[- ]?mix\w*|spanglish|hinglish|taglish|franglais|denglisch|singlish|manglish"
    r"|switch\w* (?:between )?languages|mix\w* (?:of )?languages|languages mixed|mixed[- ]languages?|mid[- ]sentence"
    r"|in the same sentence"
    r"|смешени\w* языков|смешива\w* (?:\w+ )?язык\w*|вперемешку|переключ\w* (?:\w+ ){0,2}язык\w*|суржик\w*|в одной фразе",
    re.I,
)
#: The BCP-47 / ISO 639 tag for "multiple languages" — a field naming a mixed-language track.
MULTIPLE_LANGUAGES_TAG = "mul"


def code_switching(spec: Any, text: str = "") -> bool:
    """Speech that switches language inside utterances: the `mul` language tag, else the words / conditions."""
    теги = {str(т).split("-")[0].lower() for т in getattr(spec, "language_tags", None) or ()}
    if MULTIPLE_LANGUAGES_TAG in теги:
        return True
    return bool(W_CODE_SWITCH.search(_words(spec, text)))


# --- 3. provider data terms ------------------------------------------------------------------------

#: Media the customer uploads to a hosted model (spec.inputs internal names).
UPLOAD_INPUTS: frozenset[str] = frozenset({"video", "audio", "photo"})
#: Domains whose material is the client's or confidential (`spec.domain`).
CONFIDENTIAL_DOMAINS: tuple[str, ...] = ("corporate", "health-advertising", "financial-advertising")
#: Client, personal or confidential material named in words (EN/RU).
W_CLIENT_DATA = re.compile(
    r"clients?'?s? (?:footage|material|video|recordings?|files?|data|interview|event)|for a client\b"
    r"|\bnda\b|confidential|internal[- ]only|unreleased|under embargo|embargoed|not (?:yet )?public|personal data"
    r"|\bgdpr\b|\bpii\b|biometric|patients?\b|employees?'? (?:faces?|voices?|data)"
    r"|клиентск\w*|для клиента|заказчик\w* клиент\w*|конфиденциальн\w*|под nda|персональн\w* данн\w*"
    r"|внутренн\w* (?:видео|материал\w*|запис\w*)|неопубликованн\w*|до релиза|пациент\w*|биометри\w*",
    re.I,
)


def provider_data_terms(spec: Any, text: str = "") -> bool:
    """Client / personal / confidential media goes to a hosted API: the fields first, then the words.

    Not when the job runs on the customer's own GPU (`self_host`): nothing is uploaded.
    """
    sh = getattr(spec, "self_host", None) or {}
    if sh and (not isinstance(sh, Mapping) or sh.get("enabled", True) is not False):
        return False
    if not (_inputs(spec) & UPLOAD_INPUTS):
        return False
    if getattr(spec, "training_use", None) is True:
        return True
    if any(isinstance(п, Mapping) and п.get("minor") is True and п.get("real") is not False for п in spec.people):
        return True
    область = sf.domain(spec, *CONFIDENTIAL_DOMAINS)
    if область:
        return True
    return bool(W_CLIENT_DATA.search(_words(spec, text)))


# --- 4. highlight selection --------------------------------------------------------------------------

#: Tasks whose deliverable is picked moments of the customer's long material.
RECAP_TASKS: frozenset[str] = frozenset({"cut-to-shorts"})
#: A recap / highlight cut named in words (EN/RU).
W_RECAP = re.compile(
    r"\brecaps?\b|\bhighlights\b|highlight (?:reel|video|cut|clips?)|best moments|best bits|supercut|sizzle reel|previously on"
    r"|\bteasers?\b|\btrailers?\b|clips? from (?:our|the|my) (?:\w+ )?(?:series|episodes?|show|stream|webinar|podcast)"
    r"|нарезк\w*|лучши\w* момент\w*|хайлайт\w*|кратк\w* пересказ\w*|содержание предыдущ\w*|ранее в сериал\w*|тизер\w*|трейлер\w*",
    re.I,
)


def highlight_selection(spec: Any, text: str = "") -> bool:
    """Moments picked from the customer's long video: `task` cut-to-shorts, else the words over own video."""
    if "video" not in _inputs(spec):
        return False
    if getattr(spec, "task", None) in RECAP_TASKS:
        return True
    return bool(W_RECAP.search(_words(spec, text)))


#: A narrator named in words (EN/RU) — read only when `spec.audio` and a script input are silent.
W_NARRATION = re.compile(
    r"voice[- ]?over|narrat\w*|\bvo\b|announcer|закадров\w*|диктор\w*|рассказчик\w*|голос за кадром",
    re.I,
)


def recap_edit(spec: Any, text: str = "") -> bool:
    """A recap ordered as a video edit with nothing named to change: `edit` / `edit_target` silent, recap words."""
    if getattr(spec, "task", None) not in ("video-edit", "edit") or "video" not in _inputs(spec):
        return False
    if getattr(spec, "edit", None) or getattr(spec, "edit_target", None) is not None:
        return False
    return bool(W_RECAP.search(_words(spec, text)))


def recap_narration(spec: Any, text: str = "") -> bool:
    """A NEW narrator over a recap of own footage: `audio: voiceover` / a script, else the words."""
    if "video" not in _inputs(spec):
        return False
    if getattr(spec, "task", None) not in RECAP_TASKS and not recap_edit(spec, text):
        return False
    звук = getattr(spec, "audio", None)
    if звук is not None:
        return звук == "voiceover"
    if "script" in _inputs(spec) and "speech" in _outputs(spec):
        return True
    if sf.flag(spec, "voiceover") is False:
        return False
    return bool(W_NARRATION.search(_words(spec, text)))


def recap_vo_seconds(spec: Any) -> float | None:
    """The narrator is priced for the RECAP's length (duration_s, or shots x per_shot_s), not the series."""
    if getattr(spec, "source", {}).get("duration_s") == "spec" and spec.duration_s:
        return float(spec.duration_s)
    if spec.shots and spec.per_shot_s:
        return float(spec.shots) * float(spec.per_shot_s)
    return None


# --- 5. frame-rate standards conversion ----------------------------------------------------------------

#: Markets broadcasting at 29.97 / 59.94 (60 Hz mains); any other named market is 25 / 50.
NTSC_MARKETS: frozenset[str] = frozenset(
    {"US", "CA", "MX", "BR", "JP", "KR", "TW", "PH", "CO", "PE", "CL", "VE", "EC", "BO", "GT", "SV", "HN", "NI",
     "CR", "PA", "DO", "PR"}
)  # fmt: skip
#: Platforms delivered at the market's broadcast rate (a web or social upload keeps its native rate).
CONVERSION_PLATFORMS: tuple[str, ...] = ("broadcast", "cinema", "streaming-premium")
#: Frame-rate families: a change of family is a standards conversion.
FAMILY_FILM = "film"
FAMILY_PAL = "pal"
FAMILY_NTSC = "ntsc"


def fps_family(fps: float | None) -> str | None:
    """23.976 / 24 -> film, 25 / 50 -> pal, 29.97 / 30 / 59.94 / 60 -> ntsc; anything else -> None."""
    if fps is None:
        return None
    f = float(fps)
    if 23.9 <= f <= 24.01:
        return FAMILY_FILM
    if f in (25.0, 50.0):
        return FAMILY_PAL
    if 29.9 <= f <= 30.01 or 59.9 <= f <= 60.01:
        return FAMILY_NTSC
    return None


def _input_rates(spec: Any) -> list[float]:
    return [
        float(з["fps"]) for з in getattr(spec, "input_items", None) or () if isinstance(з, Mapping) and з.get("fps")
    ]


def target_family(spec: Any) -> str | None:
    """The delivery rate family: `fps` first, then `delivery.markets` (on a broadcast-class platform or none)."""
    if getattr(spec, "fps", None):
        return fps_family(spec.fps)
    рынки = sf._delivery(spec).get("markets") or ()
    if not рынки:
        return None
    площадка = sf.platform(spec, *CONVERSION_PLATFORMS)
    if площадка is False:
        return None
    return FAMILY_NTSC if {str(р).upper() for р in рынки} & NTSC_MARKETS else FAMILY_PAL


#: A standards conversion named in words (EN/RU).
W_STANDARDS = re.compile(
    r"\bpal\b|\bntsc\b|pull[- ]?down|telecine|standards? conver\w*|frame[- ]rate conver\w*|interlac\w*"
    r"|\b(?:50|59\.94|60)i\b|(?:25|29\.97|23\.976|23\.98|30|50|59\.94)\s?(?:fps|p)?\s?(?:to|->|→|в)\s?(?:25|29\.97|23\.976|23\.98|30|50|59\.94)\s?(?:fps|p)\b"
    r"|чересстроч\w*|\bпал\b|\bнтсц\b|конверси\w* частот\w*|перевод\w* частот\w* кадр\w*",
    re.I,
)


def standards_conversion(spec: Any, text: str = "") -> bool:
    """The customer's footage changes frame-rate family on delivery: fields first, then the words."""
    if "video" not in _inputs(spec):
        return False
    вход = {fps_family(ч) for ч in _input_rates(spec)} - {None}
    цель = target_family(spec)
    if вход and цель is not None:
        return цель not in вход or len(вход) > 1
    return bool(W_STANDARDS.search(_words(spec, text)))


# --- 6. stem separation ------------------------------------------------------------------------------

#: Separating a mixed track named in words (EN/RU).
W_STEM_SEPARATION = re.compile(
    r"karaoke|instrumental version|backing track|a ?cappella|acapella|stem (?:separation|split\w*)|split (?:\w+ )?into stems"
    r"|separate (?:the )?stems|vocal remov\w*|(?:isolat|extract|remov|strip|split)\w* (?:the )?(?:\w+ )?"
    r"(?:vocals?|dialogue|music|singing)\b|separat\w* (?:the )?(?:vocals?|voice|dialogue|music) from"
    r"|караоке|минусовк\w*|(?:отдел|убра|удал|выдел|выреза)\w* (?:\w+ )?(?:вокал|музык|диалог)\w*"
    r"|разделить на (?:стемы|дорожки)|\bстем(?:ы|ам|ах|ов)?\b",
    re.I,
)


def stem_separation(spec: Any, text: str = "") -> bool:
    """A mixed track must be split into stems: `delivery.stems` on brought audio first, then the words."""
    if not (_inputs(spec) & {"audio", "video"}):
        return False
    поле = sf.stems(spec)
    if поле is not None:
        return поле
    return bool(W_STEM_SEPARATION.search(_words(spec, text)))


# --- 7. matte / depth blur -----------------------------------------------------------------------------

#: The `spec.edit` value for a background blur (bokeh) of the customer's footage (`brief_spec.EDIT_VALUES`).
EDIT_BLUR_BACKGROUND = "blur-background"
#: A background blur named in words (EN/RU).
W_BACKGROUND_BLUR = re.compile(
    r"bokeh|depth[- ]of[- ]field|shallow (?:depth|focus|dof)|\bdof\b|defocus\w*|(?:blur|soften)\w* (?:out )?(?:the )?"
    r"(?:\w+ )?(?:background|backdrop|behind)|background (?:blur|out of focus|soft)|portrait mode|cinematic mode"
    r"|боке|размы\w* (?:\w+ )?(?:фон|задн\w* план)\w*|(?:фон|задн\w* план)\w* (?:\w+ )?(?:размыт|в расфокус)\w*|глубин\w* резкост\w*|расфокус\w*",
    re.I,
)


def background_blur(spec: Any, text: str = "") -> bool:
    """A bokeh / background blur of the customer's video: `edit` / `edit_target` first, then the words."""
    if "video" not in _inputs(spec) or getattr(spec, "task", None) not in ("video-edit", "edit"):
        return False
    правки = tuple(getattr(spec, "edit", None) or ())
    if EDIT_BLUR_BACKGROUND in правки:
        return True
    цель = getattr(spec, "edit_target", None)
    if цель is not None and цель != "background":
        return False
    if правки and getattr(spec, "source", {}).get("edit") == "spec":
        return False
    return bool(W_BACKGROUND_BLUR.search(_words(spec, text)))


#: (ru, en) lines this module adds to plans (localised through `studio/l10n.py`).
NOTE_AD_VOICE = (
    "голос тифлокомментария: ДРУГОЙ стоковый голос (не голос лектора или актёров) читает описание, "
    "написанное в паузы речи; цена — за секунды пауз (около {share} % длины, {n} с), а не за весь хронометраж",
    "audio description voice: a DIFFERENT stock voice (not the lecturer's or the cast's) reads the description "
    "written into the gaps in speech; priced for the gap seconds (about {share} % of the runtime, {n} s), not the runtime",
)
NOTE_AD_TRANSCRIPT = (
    "расшифровка делается ОДИН раз: из неё же субтитры, текстовая расшифровка, перевод и поиск пауз для тифлокомментария",
    "the transcript is made ONCE: the captions, the text transcript, the translation and the gaps for the audio "
    "description all come from it",
)
NOTE_RECAP_VO = (
    "закадровый голос пересказа: короткий текст по выбранным моментам, цена — по длине пересказа ({n} с), а не всего сериала",
    "recap voice-over: a short script over the picked moments, priced by the recap's length ({n} s), not the series",
)
NOTE_MATTE_BLUR = (
    "маска человека по ВАШЕМУ ролику (удаление фона видео, альфа-канал) — фон размывается под маской при сборке; "
    "генеративная правка видео не нужна",
    "a person matte over YOUR footage (video background removal, alpha channel) — the background is blurred under "
    "it at assembly; no generative video edit",
)
ASSEMBLY_AD_MIX = (
    "тифлокомментарий кладётся в паузы речи с приглушением программы под ним и сдаётся ОТДЕЛЬНОЙ дорожкой "
    "(стем и звуковая дорожка-язык), плюс сведённая версия — 0 usd",
    "the description is laid into the speech gaps with the programme ducked under it and delivered as a SEPARATE "
    "track (a stem and an audio language track) plus a mixed described version — 0 usd",
)
ASSEMBLY_RECAP = (
    "моменты выбираются по сменам планов и расшифровке, человек утверждает выбор, затем вырезка, перекадрирование "
    "и склейка под закадровый голос (ffmpeg / монтажная программа) — 0 usd",
    "the moments are picked from shot changes and the transcript, a person approves the pick, then they are cut, "
    "reframed and joined under the voice-over (ffmpeg / an editor) — 0 usd",
)
ASSEMBLY_BLUR = (
    "размытие фона по маске (или по карте глубины) при сборке — ffmpeg boxblur / gblur под альфой, DaVinci Resolve / "
    "After Effects Lens Blur; края волос проверяются в 100 % — 0 usd",
    "the background is blurred under the matte (or a depth map) at assembly — ffmpeg boxblur / gblur under the alpha, "
    "DaVinci Resolve / After Effects Lens Blur; hair edges checked at 100 % — 0 usd",
)

#: Recipes whose steps run in the route's order (the transcript first, then the voice).
ROUTE_ORDER_RECIPES: frozenset[str] = frozenset({"accessibility_package", "series_recap"})

NOTE_PAIRS: tuple[tuple[str, str], ...] = (
    NOTE_AD_TRANSCRIPT,
    NOTE_MATTE_BLUR,
    ASSEMBLY_AD_MIX,
    ASSEMBLY_RECAP,
    ASSEMBLY_BLUR,
)
#: Pairs with a number filled in (`{n}`, `{share}`): l10n carries them as patterns.
NOTE_PATTERN_PAIRS: tuple[tuple[str, str], ...] = (NOTE_AD_VOICE, NOTE_RECAP_VO)
