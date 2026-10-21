"""Round 18 (agent A, routes & decomposition): the decompositions a fresh hidden set found wrong.

The contract of rounds 15-17 holds: the CALLING model fills `spec` in any brief language, a named field
decides both ways, and the EN/RU words below are read only when the field is absent (docs/MCP_AGENT.md,
"round 18"). Every route is priced by the planner's own step prices; what no endpoint does is an
assembly line (0 usd) or a recorded gap — never a generative model pretending to do it.

1. VIRTUAL TRY-ON BATCH — garments on a model, per SKU x view (`products`, `views`, `inputs[].role`).
   No model photo brought: ONE on-model base per view is generated (t2i, one identity for every SKU, a
   shared asset), then a try-on per SKU x view. A model photo brought: no t2i.
2. RESTORATION CHAIN — archival photo / film (`task` chain, `colorize`, `resolution`, `fps`,
   `inputs[].source / defects`): restore -> face restore (photos with faces; `восстановление_лиц`) ->
   upscale to the delivery frame -> colourise when asked -> film: deflicker at assembly, frame
   interpolation only when asked.
3. SPEECH BATCH — N separate lines (game barks, IVR prompts, e-learning lines; `lines`, `variations`,
   `characters`): priced per line (characters per line, the recorded per-request minimum named), one file
   per line.
4. PODCAST -> VIDEO — audio-only speech in, video out: a static cover (generated once when none is
   brought) + a waveform + captions from a transcript at assembly; a talking avatar only when asked.
5. VERTICAL REFRAME — horizontal footage to a vertical aspect: a tracked crop at assembly (`edit:
   reframe`, derived), the recorded AI-reframe endpoint as a priced alternative; captions burned in for
   social platforms.
6. MOTION COMIC — brought panels (`inputs[].source: comic`, `inputs[].role: panel`): panel split,
   image-to-video (or 2.5D parallax) per panel, VO (TTS) and SFX — no talking avatar, no lip sync.
7. DANCE PERFORMANCE — `dance: true`: one reference per performer, motion transfer from a driving dance
   video per performer; no keyframe stills per shot.
8. RESIDUALS — a 3D tour from a photo set / walkthrough video planned (not asked) with an assumption
   line; an explainer with a script gets a voice-over with an assumption line; a UGC avatar series makes
   ONE presenter still.

DECISION CONSTANTS (mutated both ways by `scripts/mutate_round18_routes.py`): `TRY_ON_TASKS`,
`LINES_MIN`, `LINE_S_DEFAULT`, `LINE_S_BY_PLATFORM`, `RUNWAY_TTS_MIN_CHARS`, `CHARS_PER_SECOND`,
`PODCAST_TASKS`, `REFRAME_TASKS`, `SOCIAL_BURN_PLATFORMS`, `REFRAME_USD_PER_S`, `COMIC_DROPS`,
`DANCE_DROPS`, `DANCE_AVOID`, `TOUR_PHOTOS_MIN`, `EXPLAINER_TASKS`, `FACE_RESTORE_STEP`.

This module imports nothing from `studio` at module level (`brief_spec` and `l10n` import it).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import replace
from typing import Any

SOURCE_DERIVED = "derived"

#: `spec.inputs[].role` — what a brought item IS in the order (round 18).
INPUT_ROLES: tuple[str, ...] = ("model", "garment", "product", "person", "panel", "motion", "cover")
#: `spec.inputs[].source: comic` — comic / manga pages or panels (round 18).
SOURCE_COMIC = "comic"
#: Top-level fields of round 18.
SPEC_FIELDS_R18: tuple[str, ...] = ("views", "lines", "variations", "colorize", "dance")


def _words(spec: Any, text: str = "") -> str:
    return " ".join((str(text or ""), *map(str, getattr(spec, "conditions", None) or ())))


def _named(spec: Any, name: str) -> bool:
    return name in (getattr(spec, "source", None) or {})


def _delivery(spec: Any) -> Mapping[str, Any]:
    сдача = getattr(spec, "delivery", None)
    return сдача if isinstance(сдача, Mapping) else {}


def _items(spec: Any, kind: str) -> list[Mapping[str, Any]]:
    return [з for з in getattr(spec, "input_items", None) or () if isinstance(з, Mapping) and з.get("kind") == kind]


def _count(items: Sequence[Mapping[str, Any]]) -> int:
    return sum(int(з.get("count") or 1) for з in items)


def _roles(spec: Any) -> set[str]:
    return {str(з.get("role")) for з in getattr(spec, "input_items", None) or () if isinstance(з, Mapping) and з.get("role")}


def _seconds_in(spec: Any, kind: str) -> float:
    return max((float(з.get("duration_s") or 0) for з in _items(spec, kind)), default=0.0)


def _short_edge(label: str | None) -> int | None:
    """Short edge of a resolution label («4k» -> 2160, «640x480» -> 480); None when unreadable."""
    if not label:
        return None
    м = re.fullmatch(r"(\d{2,5})x(\d{2,5})", str(label))
    if м:
        return min(int(м.group(1)), int(м.group(2)))
    from studio import brief_spec as bs

    кадр = bs.RESOLUTIONS.get(str(label))
    return min(кадр) if кадр else None


def _ratio(aspect: str | None) -> float | None:
    м = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[:x/]\s*(\d+(?:\.\d+)?)\s*", str(aspect or ""))
    if not м or float(м.group(2)) == 0:
        return None
    return float(м.group(1)) / float(м.group(2))


def _assume(spec: Any, line: str, **fields: Any) -> Any:
    """`fields` set on the spec as DERIVED, with the assumption line named."""
    источник = {**dict(spec.source), **{к: SOURCE_DERIVED for к in fields if spec.source.get(к) != "spec"}}
    return replace(spec, **fields, source=источник, assumptions=tuple(dict.fromkeys((*spec.assumptions, line))))


# --- 1. virtual try-on batch ---------------------------------------------------------------------------

#: Tasks a try-on batch comes under.
TRY_ON_TASKS: frozenset[str | None] = frozenset({None, "edit", "generate"})
W_MODEL_PHOTO = re.compile(
    r"(?:our|my|own|the|their|your) (?:own )?(?:\w+ )?model'?s? (?:photo|picture|shot|image)s?"
    r"|photos? of (?:our|my|the) (?:own )?model|model photos? (?:is |are )?(?:attached|provided|supplied|included|we)"
    r"|(?:on|onto) (?:our|my) (?:own )?(?:house |in-house )?model\b"
    r"|фото\w* (?:наш\w* |сво\w* )?модел[иьей]\b|снимк\w* (?:наш\w* )?модел[иьей]\b|на (?:нашу|свою) модель|на нашей модели",
    re.I,
)
W_NO_MODEL = re.compile(
    r"\bno (?:model|human model)\b|without (?:a |any )?(?:human )?model|don'?t have (?:a )?model"
    r"|(?:ai|generated|virtual|synthetic|digital)[- ](?:fashion )?models?\b|flat[- ]?lays?|ghost[- ]mannequin|on[- ]model"
    r"|без модели|нет модели|сгенерир\w* модел\w*|ии-модел\w*|виртуальн\w* модел\w*",
    re.I,
)
W_VIEWS = re.compile(
    r"(\d{1,2})\s*(?:views?|angles?|poses?)\b|(\d{1,2})\s*ракурс\w*|(\d{1,2})\s*поз[аы]?\b",
    re.I,
)
W_GARMENTS = re.compile(
    r"(\d{1,3})\s+(?:different\s+|distinct\s+)?(?:garments?|dress(?:es)?|jackets?|shirts?|t-shirts?|tees|hoodies?|coats?"
    r"|skirts?|outfits?|looks?|pieces?|items?|skus?|products?|sweaters?|jeans|trousers|pants|swimsuits?"
    r"|плать\w*|куртк\w*|вещ\w*|издели\w*|образ\w*|товар\w*|рубаш\w*|футбол\w*|худи)",
    re.I,
)
NOTE_TRY_ON_BASE = (
    "база на модели: одна сгенерированная модель (одна внешность, один seed / референс) — по кадру на ракурс, "
    "общая для всех вещей; ваше фото модели заменяет этот шаг",
    "the on-model base: ONE generated model (one identity, one seed / reference) — a still per view, shared by "
    "every garment; a photo of your own model replaces this step",
)
NOTE_TRY_ON_SKU = (
    "примерка: каждая вещь на базе модели в каждом ракурсе — {skus} вещ. × {views} ракурс. = {n} кадров",
    "try-on: every garment on the model base in every view — {skus} SKU × {views} view(s) = {n} images",
)


def wants_try_on(spec: Any, text: str = "") -> bool:
    """Garments on a person: `subject` (garment) / `inputs[].role` garment, else the r10 words."""
    if {"garment"} & _roles(spec):
        return True
    from studio.recipes import apply as ra

    return ra.wants_try_on(spec, text)


def try_on_batch(spec: Any, text: str = "") -> bool:
    if "image" not in set(spec.outputs) or "video" in set(spec.outputs) or "photo" not in set(spec.inputs):
        return False
    return spec.task in TRY_ON_TASKS and wants_try_on(spec, text)


def model_brought(spec: Any, text: str = "") -> bool:
    """A photo of the model is among the inputs: `inputs[].role` first, then the words, then the items."""
    роли = _roles(spec)
    if роли:
        return bool(роли & {"model", "person"})
    слова = _words(spec, text)
    if W_NO_MODEL.search(слова):
        return False
    if W_MODEL_PHOTO.search(слова):
        return True
    фото = _items(spec, "photo")
    товаров = getattr(spec, "products", None)
    if товаров:
        return _count(фото) > int(товаров)
    # Two separate photo items (garment + model) — the r10 reading; one item of N photos is N garments.
    return len(фото) >= 2


def try_on_skus(spec: Any, text: str = "") -> int:
    if getattr(spec, "products", None):
        return int(spec.products)
    вещи = [з for з in _items(spec, "photo") if з.get("role") in ("garment", "product")]
    if вещи:
        return _count(вещи)
    м = W_GARMENTS.search(_words(spec, text))
    if м:
        return int(м.group(1))
    фото = _items(spec, "photo")
    if model_brought(spec, text):
        # The model photo is one of the items (the smallest one).
        return max(1, _count(фото) - min(int(з.get("count") or 1) for з in фото))
    return max(1, _count(фото))


def try_on_views(spec: Any, text: str = "", skus: int | None = None) -> int:
    if getattr(spec, "views", None):
        return int(spec.views)
    м = W_VIEWS.search(_words(spec, text))
    if м:
        return int(next(г for г in м.groups() if г))
    штук = int(spec.shots or 0)
    вещей = skus or try_on_skus(spec, text)
    if штук > вещей and штук % вещей == 0:
        return штук // вещей
    return 1


# --- 2. restoration chain ----------------------------------------------------------------------------

RESTORE_TASKS: frozenset[str] = frozenset({"restore", "colorize", "upscale"})
#: With the source's frame unknown, a delivery frame whose short edge reaches this is an upscale (4K class).
UNKNOWN_SOURCE_UPSCALE_EDGE = 2160
OLD_SOURCES: frozenset[str] = frozenset({"archival", "cine-film", "print-scan"})
RESTORE_DEFECTS: frozenset[str] = frozenset({"halftone", "noise", "scratches", "flicker", "blur"})
W_COLORIZE = re.compile(r"colou?ri[sz]\w*|colou?ri[sz]ation|in (?:full )?colou?r\b|раскрас\w*|в цвет[еу]?\b|цветн\w* верси", re.I)
W_KEEP_BW = re.compile(
    r"keep (?:it |them )?(?:in )?(?:black[- ]and[- ]white|b ?& ?w|b/w|monochrome)|stay (?:black[- ]and[- ]white|b ?& ?w)"
    r"|no colou?ri[sz]|without colou?ri[sz]|не раскраш\w*|без раскрас\w*|оставить чёрно-бел\w*|оставить черно-бел\w*",
    re.I,
)
W_UPSCALE = re.compile(r"upscal\w*|super[- ]?resolution|\b(?:4k|8k|2160p|uhd)\b|апскейл\w*|повы\w* разрешени\w*", re.I)
W_INTERP = re.compile(
    r"frame interpolation|interpolat\w*|smooth(?:er)? motion|\b(?:48|50|60)\s?fps\b|slow[- ]motion|интерполяц\w*|плавн\w* движ\w*",
    re.I,
)
W_RESTORE = re.compile(r"restor\w*|repair\w*|scratch\w*|dust|tears?\b|damaged|реставр\w*|восстанов\w*|царапин\w*|повреж\w*", re.I)
W_FACES = re.compile(
    r"\bfaces?\b|portraits?|family|grand(?:pa|ma|father|mother|parents?)|great-grand\w*|wedding|people|relatives|ancestors?"
    r"|soldiers?|class photo|лиц[оаы]?\b|портрет\w*|семейн\w*|бабушк\w*|дедушк\w*|прадед\w*|прабабушк\w*|свадеб\w*|родн\w*|люд[еи]\w*",
    re.I,
)
#: The face-restoration step (planner operation, registry job `face-restore`).
FACE_RESTORE_STEP = "восстановление_лиц"
#: The face-restoration step's requirement (`planner.OPERATIONS`), both answer languages.
REQUIREMENT_FACE_RESTORE = (
    "лица на снимке восстановлены (глаза, черты, кожа) и остались похожи на людей со снимка",
    "the faces of the photo restored (eyes, features, skin) and still looking like the people in it",
)
NOTE_FACE_RESTORE = (
    "лица на снимках восстанавливаются отдельным проходом (CodeFormer / GFPGAN) ПОСЛЕ реставрации и ДО апскейла; "
    "сила восстановления невысокая (fidelity ~0.7), иначе лицо перестаёт быть похожим",
    "the faces are restored in a pass of their own (CodeFormer / GFPGAN) AFTER the restore and BEFORE the upscale; "
    "a low strength (fidelity ~0.7), or the face stops looking like the person",
)
ASSEMBLY_FILM_FACES = (
    "лица на плёнке: покадровое восстановление лиц (CodeFormer --face_upsample на своей машине) — эндпоинта для "
    "видео не записано; лицензия CodeFormer S-Lab — только некоммерческая (GFPGAN — Apache-2.0)",
    "faces in the film: frame-by-frame face restoration (CodeFormer --face_upsample on your own machine) — no "
    "video endpoint is recorded; the CodeFormer S-Lab licence is non-commercial only (GFPGAN is Apache-2.0)",
)
ASSUMPTION_CHAIN = (
    "restoration chain completed from the spec: {links} added (restore -> faces -> upscale to the delivery frame "
    "-> colourise; interpolation only when asked) — pass spec.task as the exact chain to change it"
)


def colorize_wanted(spec: Any, text: str = "") -> bool:
    поле = getattr(spec, "colorize", None)
    if isinstance(поле, bool):
        return поле
    if "colorize" in {spec.task, *spec.then_tasks}:
        return True
    слова = _words(spec, text)
    return bool(W_COLORIZE.search(слова)) and not W_KEEP_BW.search(слова)


def _source_short(spec: Any, kind: str) -> int | None:
    края = [_short_edge(з.get("resolution")) for з in _items(spec, kind)]
    края = [к for к in края if к]
    return min(края) if края else None


def upscale_wanted(spec: Any, text: str = "") -> bool:
    """The delivery frame is above the source's: the resolution named against the source's, or the words."""
    вид = "video" if "video" in set(spec.inputs) else "photo"
    цель = _short_edge(spec.resolution) if spec.source.get("resolution") == "spec" or _named(spec, "resolution") else None
    if цель:
        исходник = _source_short(spec, вид)
        if исходник is not None:
            return цель > исходник
        старьё = any(set(з.get("source") or ()) & OLD_SOURCES for з in _items(spec, вид))
        # The source's frame unknown: a scan may already be HD — only a 4K-class delivery is an upscale.
        return цель >= UNKNOWN_SOURCE_UPSCALE_EDGE and (старьё or spec.task in ("restore", "colorize"))
    return bool(W_UPSCALE.search(_words(spec, text)))


def interpolate_wanted(spec: Any, text: str = "") -> bool:
    if "video" not in set(spec.inputs):
        return False
    if spec.fps:
        исходные = [float(з.get("fps")) for з in _items(spec, "video") if з.get("fps")]
        if исходные:
            return float(spec.fps) > max(исходные)
    return bool(W_INTERP.search(_words(spec, text)))


def restore_wanted(spec: Any, text: str = "") -> bool:
    for з in (*_items(spec, "photo"), *_items(spec, "video")):
        if set(з.get("defects") or ()) & RESTORE_DEFECTS:
            return True
    return bool(W_RESTORE.search(_words(spec, text)))


def with_restore_chain(spec: Any, text: str = "") -> Any:
    """Round 18: the links of a restoration chain the spec implies are added to `then_tasks`."""
    работы = (spec.task, *spec.then_tasks)
    if spec.task not in RESTORE_TASKS or not set(spec.inputs) & {"photo", "video"} or "video" in set(spec.outputs) - {"video"}:
        return spec
    if _named(spec, "task") and len(работы) > 1:
        return spec  # the caller named the exact chain
    новые: list[str] = []
    if "restore" not in работы and spec.task != "upscale" and restore_wanted(spec, text):
        новые.append("restore")
    if "upscale" not in работы and upscale_wanted(spec, text):
        новые.append("upscale")
    if "colorize" not in работы and colorize_wanted(spec, text):
        новые.append("colorize")
    if "interpolate" not in работы and interpolate_wanted(spec, text):
        новые.append("interpolate")
    if not новые:
        return spec
    линия = ASSUMPTION_CHAIN.format(links=", ".join(новые))
    return _assume(spec, линия, then_tasks=tuple(dict.fromkeys((*spec.then_tasks, *новые))))


def faces_present(spec: Any, text: str = "") -> bool:
    """Faces in the brought photos: `people` / `subject` (person) first, then the words."""
    if any(п.get("on_screen") is not False for п in getattr(spec, "people", None) or ()):
        return True
    if _named(spec, "subject"):
        return "person" in set(spec.subject or ())
    return bool(W_FACES.search(_words(spec, text)))


# --- 3. speech batch ---------------------------------------------------------------------------------

W_LINES = re.compile(
    r"(\d{1,4})\s+(?:[\w-]+\s+){0,2}?(?:voice ?lines?|lines?|barks?|prompts?|phrases?|utterances?|sentences?|callouts?|messages?"
    r"|строк\w*|реплик\w*|фраз\w*|подсказ\w*|промпт\w*|сообщени\w*)\b",
    re.I,
)
W_VARIATIONS = re.compile(
    r"(\d{1,2})\s*(?:variations?|variants?|takes?|versions?|alts?|alternates?|вариа\w*|дубл\w*|верси\w*)", re.I
)
#: A batch starts at this many separate lines.
LINES_MIN = 2
#: Seconds of one line when nothing names it (the platform's typical line, else this).
LINE_S_DEFAULT = 4.0
LINE_S_BY_PLATFORM: dict[str, float] = {"game-engine": 2.0, "telephony": 6.0, "voice-agent": 6.0, "web": 8.0}
#: The planner's own TTS estimate (`pricing.CHARS_PER_SECOND`).
CHARS_PER_SECOND = 15.0
#: Runway-hosted eleven_v3: 1 credit per 50 characters, minimum 1 credit (`model_facts.jsonl` eleven_v3 price,
#: docs.dev.runwayml.com/guides/pricing) — a line under 50 characters is billed as 50.
RUNWAY_TTS_MIN_CHARS = 50
RUNWAY_TTS_SOURCE = "https://docs.dev.runwayml.com/guides/pricing"
NOTE_SPEECH_BATCH = (
    "партия реплик: {takes} отдельных запросов синтеза ({lines} строк × {voices} голос. × {variations} вариант.), по "
    "~{chars} знаков на реплику — по файлу на реплику, а не один длинный ролик",
    "a batch of lines: {takes} separate TTS requests ({lines} lines × {voices} voice(s) × {variations} variation(s)), "
    "~{chars} characters a line — one file per line, never one long clip",
)
ASSEMBLY_SPEECH_FILES = (
    "сдача по файлу на реплику: <персонаж>_<id строки>_v<вариант>.wav и таблица id -> текст (CSV) — длинный рендер "
    "не режется, каждая реплика — свой запрос — 0 usd",
    "delivery is one file per line: <character>_<line id>_v<variation>.wav plus a manifest CSV (id -> text) — no "
    "long render to split, every line is its own request — 0 usd",
)


def batch_lines(spec: Any, text: str = "") -> int | None:
    if getattr(spec, "lines", None):
        return int(spec.lines)
    if spec.shots and set(spec.outputs) <= {"speech", "text"}:
        return int(spec.shots)
    м = W_LINES.search(_words(spec, text))
    return int(м.group(1)) if м else None


def batch_variations(spec: Any, text: str = "") -> int:
    if getattr(spec, "variations", None):
        return int(spec.variations)
    м = W_VARIATIONS.search(_words(spec, text))
    return int(м.group(1)) if м else 1


def speech_batch(spec: Any, text: str = "") -> bool:
    if "speech" not in set(spec.outputs) or set(spec.outputs) & {"video", "image", "music"}:
        return False
    if set(spec.inputs) & {"video", "photo"} or spec.task not in (None, "generate", "voice-clone"):
        return False
    строк = batch_lines(spec, text)
    return строк is not None and строк >= LINES_MIN


def line_seconds(spec: Any, takes: int) -> float:
    if spec.per_shot_s:
        return float(spec.per_shot_s)
    if spec.duration_s and spec.source.get("duration_s") == "spec" and takes:
        return max(0.5, float(spec.duration_s) / takes)
    for площадка in _delivery(spec).get("platform") or ():
        if площадка in LINE_S_BY_PLATFORM:
            return LINE_S_BY_PLATFORM[площадка]
    if "education" in set(getattr(spec, "domain", None) or ()):
        return LINE_S_BY_PLATFORM["web"]
    return LINE_S_DEFAULT


def _speech_batch_line(lines: int, voices: int, variations: int, chars: int) -> tuple[str, str]:
    takes = lines * voices * variations
    всего = takes * chars
    минимум = takes * max(chars, RUNWAY_TTS_MIN_CHARS)
    return (
        f"цена партии считается по репликам: {takes} × ~{chars} знаков = {всего} знаков; у Runway eleven_v3 — 1 кредит за "
        f"50 знаков, минимум 1 кредит за запрос ({RUNWAY_TTS_SOURCE}): короткая реплика оплачивается как 50 знаков — "
        f"{минимум} знаков к оплате там; минимум за запрос у ElevenLabs напрямую и у fal не записан (пробел)",
        f"the batch is priced per line: {takes} × ~{chars} characters = {всего} characters; Runway-hosted eleven_v3 bills "
        f"1 credit per 50 characters, minimum 1 credit a request ({RUNWAY_TTS_SOURCE}): a short line is billed as 50 "
        f"characters — {минимум} billable characters there; a per-request minimum at ElevenLabs direct and fal is not "
        "recorded (a gap)",
    )


# --- 4. podcast -> video ---------------------------------------------------------------------------------

PODCAST_TASKS: frozenset[str | None] = frozenset({None, "generate", "animate", "music-visualiser", "r2v"})
W_PODCAST = re.compile(
    r"podcast|episode|interview|radio show|talk show|lecture|sermon|webinar|audio ?book chapter|panel discussion"
    r"|подкаст\w*|выпуск\w*|интервью|радиошоу|лекци\w*|проповед\w*|вебинар\w*|эфир\w*",
    re.I,
)
W_AVATAR = re.compile(
    r"avatar|talking[- ]head|(?:host|hosts|speaker)s? on (?:camera|screen)|lip[- ]?sync|аватар\w*|говорящ\w* голов\w*|липсинк\w*",
    re.I,
)
W_SONG = re.compile(r"\bsong|track|single|album|lyrics|music video|песн\w*|трек\w*|клип\w*|альбом\w*", re.I)
#: Video-making steps a podcast audiogram does not need.
PODCAST_DROPS: frozenset[str] = frozenset(
    {"генерация_видео", "оживление", "видео_по_референсу", "говорящий_аватар", "липсинк", "генерация_изображения", "музыка"}
)
NOTE_PODCAST_COVER = (
    "обложка выпуска: один кадр 16:9 (название, ведущие) — фон всей аудиограммы; ваша обложка заменяет этот шаг",
    "the episode cover: one 16:9 still (title, hosts) — the background of the whole audiogram; your own cover art "
    "replaces this step",
)
NOTE_PODCAST_TRANSCRIPT = (
    "расшифровка выпуска с таймингами и метками говорящих — субтитры, главы и описание из неё",
    "a timed transcript of the episode with speaker labels — the captions, chapters and description come from it",
)
ASSEMBLY_AUDIOGRAM = (
    "видео собирается при сборке: статичная обложка + волна звука (ffmpeg showwaves / showspectrum) + полоса "
    "прогресса и титры глав — видеомодель не нужна, 0 usd",
    "the video is built at assembly: the static cover + a waveform of the audio (ffmpeg showwaves / showspectrum) + "
    "a progress bar and chapter titles — no video model, 0 usd",
)
#: Priors whose clip is made at assembly: the plan price is the clip price (no "no clip price").
ASSEMBLED_CLIP_PRIORS: frozenset[str] = frozenset({"podcast_audiogram"})
ASSEMBLY_PODCAST_AVATAR = (
    "говорящий аватар ведущих — только если его попросят (spec.lipsync / task avatar): по цене аватара за секунду "
    "всего выпуска; в план не входит",
    "a talking avatar of the hosts only if asked (spec.lipsync / task avatar): at avatar rates per second of the "
    "whole episode; not in the plan",
)
ASSEMBLY_CAPTIONS_BURN = (
    "субтитры по расшифровке вшиваются при сборке (ffmpeg subtitles, крупный шрифт в безопасной зоне) — 0 usd",
    "captions from the transcript are burned in at assembly (ffmpeg subtitles, a large font inside the safe zone) — 0 usd",
)
ASSEMBLY_CAPTIONS_SOFT = (
    "субтитры по расшифровке сдаются дорожкой (SRT / WebVTT) — площадка их принимает, 0 usd",
    "captions from the transcript are delivered as a track (SRT / WebVTT) — the platform takes them, 0 usd",
)


def avatar_asked(spec: Any, text: str = "") -> bool:
    if spec.task == "avatar" or getattr(spec, "lipsync", None) is True:
        return True
    if getattr(spec, "lipsync", None) is False:
        return False
    if any(п.get("on_screen") is True and п.get("speaks") is True for п in spec.people):
        return True
    return bool(W_AVATAR.search(_words(spec, text)))


def podcast_video(spec: Any, text: str = "") -> bool:
    """Speech audio only (a podcast, an interview), a video out: an audiogram, not a generated film."""
    if "video" not in set(spec.outputs) or "audio" not in set(spec.inputs) or "video" in set(spec.inputs):
        return False
    if spec.task not in PODCAST_TASKS or avatar_asked(spec, text):
        return False
    if getattr(spec, "animate_input", None) is True:
        return False
    if _named(spec, "audio_content"):
        return "speech" in set(spec.audio_content) and not set(spec.audio_content) & {"song"}
    if "podcast" in set(_delivery(spec).get("platform") or ()):
        return True
    слова = _words(spec, text)
    return bool(W_PODCAST.search(слова)) and not W_SONG.search(слова)


# --- 5. vertical reframe -------------------------------------------------------------------------------------

REFRAME_TASKS: frozenset[str | None] = frozenset({"video-edit", "edit"})
EDIT_REFRAME = "reframe"
#: The assembly form of a reframe not wider than the source (`brief_spec` rewrites reframe -> crop).
EDIT_CROP = "crop"
W_REFRAME = re.compile(r"reframe|vertical|portrait (?:format|version|mode)|9:16|4:5|вертикал\w*|рефрейм\w*", re.I)
#: Platforms whose viewers watch muted: captions are burned into the picture.
SOCIAL_BURN_PLATFORMS: frozenset[str] = frozenset({"tiktok", "reels", "instagram", "youtube-shorts"})
#: The recorded AI reframe endpoint (`model_facts.jsonl` ltx-2.3-reframe, fal.ai page): $0.10/s at 720p,
#: $0.20/s at 1080p, billed on the input's duration.
REFRAME_MODEL = "ltx-2.3-reframe"
REFRAME_USD_PER_S: dict[str, float] = {"720p": 0.10, "1080p": 0.20}
REFRAME_SOURCE = "https://fal.ai/models/fal-ai/ltx-2.3/reframe"
ASSUMPTION_REFRAME = (
    "a vertical aspect from horizontal footage: a tracked crop at assembly (edit reframe), not a generative "
    "video edit — pass spec.edit to name another edit"
)
NOTE_REFRAME_TRANSCRIPT = (
    "расшифровка речи для субтитров — на вертикальных площадках смотрят без звука",
    "a transcript of the speech for the captions — vertical platforms are watched muted",
)


def vertical_target(spec: Any) -> bool:
    r = _ratio(spec.aspect)
    return r is not None and r < 1


def source_vertical(spec: Any) -> bool | None:
    for з in _items(spec, "video"):
        м = re.fullmatch(r"(\d{2,5})x(\d{2,5})", str(з.get("resolution") or ""))
        if м:
            return int(м.group(1)) < int(м.group(2))
    return None


def with_reframe(spec: Any, text: str = "") -> Any:
    """Horizontal footage ordered vertical, no edit named: the edit IS a reframe (a tracked crop)."""
    if "video" not in set(spec.inputs) or "video" not in set(spec.outputs) or spec.task not in REFRAME_TASKS:
        return spec
    if spec.then_tasks or spec.edit or spec.edit_target or not vertical_target(spec):
        return spec
    if source_vertical(spec) is True:
        return spec
    return _assume(spec, ASSUMPTION_REFRAME, edit=(EDIT_REFRAME,))


def social_burn(spec: Any) -> bool:
    return bool(set(_delivery(spec).get("platform") or ()) & SOCIAL_BURN_PLATFORMS)


def _reframe_alt_line(seconds: float) -> tuple[str, str]:
    цены = ", ".join(f"{к} {в:g} usd/s → {seconds * в:.2f} usd" for к, в in REFRAME_USD_PER_S.items())
    return (
        f"запасной путь, если кроп теряет второго говорящего: эндпоинт ИИ-рефрейма {REFRAME_MODEL} (перекомпоновка / "
        f"дорисовка краёв), {seconds:g} с: {цены}; {REFRAME_SOURCE}",
        f"the fallback when a crop loses the second speaker: the AI reframe endpoint {REFRAME_MODEL} (recomposes / "
        f"outpaints the edges), {seconds:g} s: {цены}; {REFRAME_SOURCE}",
    )


# --- 6. motion comic -----------------------------------------------------------------------------------------

W_COMIC = re.compile(
    r"\bcomic|manga|manhwa|manhua|webtoon|graphic novel|\bpanels?\b|motion comic|комикс\w*|манг[аиу]\b|манхв\w*|вебтун\w*|панел\w* комикс",
    re.I,
)
W_NARRATION = re.compile(r"narrat\w*|voice[- ]?over|\bvo\b|voiced|dialogue|voice acting|озвуч\w*|закадр\w*|диалог\w*|голос\w*", re.I)
#: Steps a motion comic does not use: no talking avatar, no lip sync, no stills (the panels are brought).
COMIC_DROPS: frozenset[str] = frozenset(
    {"говорящий_аватар", "липсинк", "генерация_видео", "видео_по_референсу", "генерация_изображения", "перенос_движения"}
)
NOTE_COMIC_I2V = (
    "каждая панель оживляется отдельно (image-to-video, мягкое движение: ветер, свет, моргание, камера) — {n} панел. "
    "по ~{s} с; без губ",
    "every panel is animated on its own (image-to-video, gentle motion: wind, light, blinks, a camera drift) — {n} "
    "panel(s) of ~{s} s; no lips",
)
NOTE_COMIC_VO = (
    "озвучка текста панелей (рассказчик и реплики персонажей — по голосу на персонажа)",
    "a voice-over of the panels' text (the narrator and the characters' lines — one voice per character)",
)
NOTE_COMIC_SFX = (
    "звуковые эффекты и фон панелей (удары, шаги, город) — по сцене",
    "sound effects and ambience of the panels (hits, steps, the city) — per scene",
)
ASSEMBLY_COMIC_SPLIT = (
    "страницы режутся на панели при сборке (кроп по рамкам, kumiko / вручную), пузыри текста чистятся или "
    "остаются по замыслу — 0 usd",
    "the pages are split into panels at assembly (a crop along the borders, kumiko / by hand), the speech bubbles "
    "are cleaned or kept by design — 0 usd",
)
ASSEMBLY_COMIC_PARALLAX = (
    "дешёвая альтернатива оживлению: 2.5D-параллакс по слоям панели (карта глубины Depth Anything + DepthFlow / "
    "After Effects) на своей машине — 0 usd API, рисунок не перерисовывается",
    "the cheap alternative to image-to-video: a 2.5D parallax of the panel's layers (a Depth Anything depth map + "
    "DepthFlow / After Effects) on your own machine — 0 usd API, the art is never redrawn",
)
ASSEMBLY_COMIC_EDIT = (
    "панели монтируются под озвучку (тайминг по репликам, переходы между панелями), эффекты кладутся по кадрам — 0 usd",
    "the panels are cut to the voice-over (timed to the lines, transitions between panels), effects laid to the "
    "frames — 0 usd",
)
#: Integration (round 18): a motion comic released in several markets — the lettering is part of the art, so a
#: textless master needs the panels without it (`expert_r18.textless_needed`).
ASSEMBLY_COMIC_LETTERING = (
    "версии для нескольких рынков: текст пузырей — часть рисунка, поэтому для мастера без титров нужны панели без "
    "леттеринга (рисунок до леттеринга или леттеринг отдельным слоем); каждый рынок летерится заново поверх "
    "чистых панелей, зачистка пузырей дорисовкой — дорогой запасной путь — 0 usd",
    "versions for several markets: the balloon text is part of the art, so the textless master needs the panels "
    "without lettering (the art before lettering, or the lettering on its own layer); each market is re-lettered "
    "over the clean panels, cleaning balloons by inpainting is the expensive fallback — 0 usd",
)


def motion_comic(spec: Any, text: str = "") -> bool:
    """Brought comic panels made to move: `inputs[].source: comic` / `role: panel`, else the words."""
    if "video" not in set(spec.outputs) or "photo" not in set(spec.inputs) or "video" in set(spec.inputs):
        return False
    фото = _items(spec, "photo")
    if any(SOURCE_COMIC in set(з.get("source") or ()) or з.get("role") == "panel" for з in фото):
        return True
    if any(з.get("source") or з.get("role") for з in фото):
        return False
    return bool(W_COMIC.search(_words(spec, text)))


def comic_panels(spec: Any) -> int:
    панели = [з for з in _items(spec, "photo") if з.get("role") in (None, "panel")]
    return max(1, _count(панели) if панели else int(spec.shots or 1))


# --- 7. dance performance -----------------------------------------------------------------------------------

W_DANCE = re.compile(
    r"\bdanc\w*|choreograph\w*|(?:k-?pop|idol)\s+(?:\w+\s+)?(?:performance|stage|routine)|танц\w*|хореограф\w*|пляс\w*",
    re.I,
)
DANCE_TASKS: frozenset[str | None] = frozenset({None, "generate", "animate", "r2v", "music-visualiser"})
#: Steps a dance performance replaces: motion transfer carries the whole body from a driving dance video.
DANCE_DROPS: frozenset[str] = frozenset(
    {"оживление", "генерация_видео", "видео_по_референсу", "говорящий_аватар", "генерация_изображения"}
)
#: Motion-transfer endpoints ranked last for a dance: fal names the standard Kling v3 mode "for portraits and
#: simple animations" (`model_facts.jsonl` kling-video-v3-standard-motion-control best_for); Wan Animate move
#: renders 15 fps in standard mode and has no price recorded (`wan-2.2-animate-move` max_seconds row); Runway
#: Act-Two records its price in credits only, which the step budget cannot compare with usd per second.
DANCE_AVOID = r"standard-motion-control|animate-move|act-two"
NOTE_DANCE_REF = (
    "референс исполнителя в полный рост (весь корпус, руки и ноги видны, ровный фон) — по одному на исполнителя, "
    "не кадр на шот; ваше фото заменяет этот шаг",
    "a full-length reference of each performer (whole body, hands and feet visible, a plain background) — ONE per "
    "performer, never a still per shot; your own photo replaces this step",
)
NOTE_DANCE_MOTION = (
    "перенос движения: танец из ведущего видео переносится на референс каждого исполнителя ({n} исп. × {s} с) — "
    "движение всего тела, а не догадка видеомодели",
    "motion transfer: the dance of the driving video is carried onto each performer's reference ({n} performer(s) × "
    "{s} s) — whole-body motion, not a video model's guess",
)
ASSEMBLY_DANCE_DRIVER = (
    "ведущее видео танца: один танцор исполняет хореографию на статичной камере, в полный рост, дубли 3-30 с (или "
    "лицензированный клип хореографии) — съёмка своими силами 0 usd; без него перенос движения не запускается",
    "the driving dance video: one dancer performs the choreography on a static camera, full body, 3-30 s takes (or "
    "a licensed choreography clip) — filmed in-house for 0 usd; motion transfer does not run without it",
)
ASSEMBLY_DANCE_OWN_DRIVER = (
    "ведущее видео — ВАШЕ видео танца: дубли режутся по 3-30 с, по одному танцору в кадре — 0 usd",
    "the driving video is YOUR dance video: cut into 3-30 s takes, one dancer in frame each — 0 usd",
)
ASSEMBLY_DANCE_COMPOSITE = (
    "исполнители генерируются по одному и сводятся в кадр при сборке (раскладка / ключ по маске), трек кладётся "
    "под танец по биту — 0 usd",
    "the performers are generated one at a time and composited into the frame at assembly (a layout / a matte key), "
    "the track laid under the dance on the beat — 0 usd",
)


def dance(spec: Any, text: str = "") -> bool:
    поле = getattr(spec, "dance", None)
    if isinstance(поле, bool):
        return поле
    return bool(W_DANCE.search(_words(spec, text)))


def dance_video(spec: Any, text: str = "") -> bool:
    if "video" not in set(spec.outputs) or spec.task not in DANCE_TASKS:
        return False
    return dance(spec, text)


def performers(spec: Any) -> int:
    if spec.characters:
        return int(spec.characters)
    люди = [п for п in spec.people if п.get("on_screen") is not False]
    if люди:
        return len(люди)
    фото = [з for з in _items(spec, "photo") if з.get("role") in (None, "person", "model")]
    return max(1, _count(фото)) if фото else 1


# --- 8. residuals ------------------------------------------------------------------------------------------

#: A photo SET for a 3D tour starts here (`routes_r17.SPLAT_PHOTOS_MIN`).
TOUR_PHOTOS_MIN = 20
#: A navigable / 3D tour named in words (EN/RU): with a photo SET it is the reconstruction route.
W_TOUR_3D = re.compile(
    r"virtual tour|\b3d\b|360[- ]?(?:tour|walk\w*|view)|navigable|explorable|dollhouse|matterport"
    r"|explore the (?:space|flat|house|apartment|property)"
    r"|виртуальн\w* (?:тур|прогулк\w*|экскурси\w*)|\b3[dд]\b|3[dд]-|360",
    re.I,
)
#: A tour / walk-through in general (EN/RU): over a walk-through VIDEO it is the reconstruction route; over a
#: few photos it stays the round-12 camera-path video.
W_TOUR = re.compile(
    r"walk-?through|fly-?through|\btour\b|прогулк\w* по|тур по|облёт|облет|экскурси\w*",
    re.I,
)
ASSUMPTION_TOUR = (
    "a tour of a real place from a photo set / a walk-through video: planned as a 3D reconstruction (gaussian "
    "splat) — pass spec.reconstruct_3d=false for flat camera moves over the photos"
)
#: Tasks an explainer with a script gets its voice-over in.
EXPLAINER_TASKS: frozenset[str | None] = frozenset({None, "generate", "animate"})
ASSUMPTION_EXPLAINER_VO = (
    "a script is brought and no voice-over was named: the script is read as a voice-over (a TTS step) — pass "
    "spec.voiceover=false for a silent / text-only piece"
)


def tour_3d(spec: Any, text: str = "") -> bool:
    """A tour intent over a photo SET or a walk-through video, with `reconstruct_3d` not named."""
    if getattr(spec, "reconstruct_3d", None) is not None or not set(spec.inputs) & {"photo", "video"}:
        return False
    if "video" not in set(spec.outputs) and not set(_delivery(spec).get("format") or ()) & {"ply", "splat", "spz"}:
        return False
    if any(п.get("real") for п in spec.people):
        return False
    слова = _words(spec, text)
    if _count(_items(spec, "photo")) >= TOUR_PHOTOS_MIN and W_TOUR_3D.search(слова):
        return True
    # A walk-through VIDEO of the place (no photos beside it) is the capture itself.
    обход = "video" in set(spec.inputs) and "photo" not in set(spec.inputs)
    return обход and bool(W_TOUR_3D.search(слова) or W_TOUR.search(слова))


def with_tour(spec: Any, text: str = "") -> Any:
    if not tour_3d(spec, text):
        return spec
    return _assume(spec, ASSUMPTION_TOUR, reconstruct_3d=True)


def with_explainer_vo(spec: Any, text: str = "") -> Any:
    """A script brought for a generated video, nothing said of a voice: it is read as a voice-over."""
    if "script" not in set(spec.inputs) or set(spec.outputs) != {"video"} or set(spec.inputs) & {"audio", "video"}:
        return spec
    if spec.task not in EXPLAINER_TASKS or spec.then_tasks:
        return spec
    if spec.voiceover is not None or spec.audio is not None or _named(spec, "audio_content"):
        return spec
    if getattr(spec, "lipsync", None) is not None or any(п.get("speaks") is not None for п in spec.people):
        return spec
    return _assume(spec, ASSUMPTION_EXPLAINER_VO, voiceover=True)


def derived_task(spec: Any, text: str = "") -> str | None:
    """A task the inputs and outputs decide when the caller left it out (a plan, not a question)."""
    if spec.task is not None or not spec.outputs:
        return None
    if tour_3d(spec, text) or getattr(spec, "reconstruct_3d", None) is True:
        return "generate"
    probe = replace(spec, task="generate")
    if speech_batch(probe, text) or podcast_video(probe, text):
        return "generate"
    if motion_comic(probe, text) or dance_video(probe, text):
        return "animate"
    return None


ASSUMPTION_TASK = "spec.task not named — '{task}' read from the inputs and outputs ({why}); pass spec.task to change it"


def task_reason(spec: Any, text: str = "") -> str:
    probe = replace(spec, task="generate")
    if tour_3d(spec, text) or getattr(spec, "reconstruct_3d", None) is True:
        return "a 3D tour of a real place"
    if speech_batch(probe, text):
        return "a batch of separate speech lines"
    if podcast_video(probe, text):
        return "speech audio to a video: an audiogram"
    if motion_comic(probe, text):
        return "brought comic panels made to move"
    return "a dance performance"


def spec_transform(spec: Any, text: str = "") -> Any:
    """All round-18 spec transforms, in order (called from `brief_spec.with_defaults`)."""
    задача = derived_task(spec, text)
    if задача:
        spec = _assume(spec, ASSUMPTION_TASK.format(task=задача, why=task_reason(spec, text)), task=задача)
    spec = with_restore_chain(spec, text)
    spec = with_reframe(spec, text)
    spec = with_tour(spec, text)
    spec = with_explainer_vo(spec, text)
    return spec


# --- notes, localisation -------------------------------------------------------------------------------------

NOTE_PAIRS: tuple[tuple[str, str], ...] = (
    NOTE_TRY_ON_BASE, NOTE_FACE_RESTORE, REQUIREMENT_FACE_RESTORE, ASSEMBLY_FILM_FACES, ASSEMBLY_SPEECH_FILES,
    NOTE_PODCAST_COVER, NOTE_PODCAST_TRANSCRIPT, ASSEMBLY_AUDIOGRAM, ASSEMBLY_PODCAST_AVATAR, ASSEMBLY_CAPTIONS_BURN,
    ASSEMBLY_CAPTIONS_SOFT, NOTE_REFRAME_TRANSCRIPT, NOTE_COMIC_VO, NOTE_COMIC_SFX, ASSEMBLY_COMIC_SPLIT,
    ASSEMBLY_COMIC_PARALLAX, ASSEMBLY_COMIC_EDIT, NOTE_DANCE_REF, ASSEMBLY_DANCE_DRIVER, ASSEMBLY_DANCE_OWN_DRIVER,
    ASSEMBLY_DANCE_COMPOSITE, ASSEMBLY_COMIC_LETTERING,
)  # fmt: skip
#: Templated pairs: ({name} -> a number) in both languages.
TEMPLATE_PAIRS: tuple[tuple[str, str], ...] = (NOTE_TRY_ON_SKU, NOTE_SPEECH_BATCH, NOTE_COMIC_I2V, NOTE_DANCE_MOTION)


def l10n_pairs() -> tuple[tuple[str, str], ...]:
    """(ru regex, en) rows for `studio/l10n.py`, the templated lines included."""
    ряды = [(re.escape(ru), en) for ru, en in NOTE_PAIRS]
    for ru, en in TEMPLATE_PAIRS:
        имена = re.findall(r"\{(\w+)\}", ru)
        образец = re.escape(ru)
        for имя in имена:
            образец = образец.replace(re.escape("{" + имя + "}"), rf"(?P<{имя}>[\d.,]+)", 1)
        ряды.append((образец, re.sub(r"\{(\w+)\}", r"\\g<\1>", en)))
    return tuple(ряды)


def made_inputs(step: str, priors: Sequence[str], video_artefact: str) -> set[str]:
    """A dance's motion transfer is fed by the driving dance video the customer films (an assembly line)."""
    if step == "перенос_движения" and "dance_motion_transfer" in priors:
        return {video_artefact}
    return set()


def dropped_assembly(priors: Sequence[str]) -> tuple[str, ...]:
    """Route assembly lines a round-18 route no longer describes (the visualiser's under a podcast audiogram)."""
    if "podcast_audiogram" not in priors:
        return ()
    from studio import brief_spec as bs

    return (bs.NOTE_VISUALISER, bs.NOTE_VISUALISER_SYNC, bs.NOTE_VISUALISER_NO_TRACK)


# --- the rewrite (called from `recipes.apply.rewrite`) ---------------------------------------------------------


def rewrite(
    spec: Any,
    steps: list[str],
    notes: MutableMapping[str, str],
    counts: MutableMapping[str, int],
    step_seconds: MutableMapping[str, tuple[float, float]],
    acc: Any,
    text: str = "",
    avoid: MutableMapping[str, str] | None = None,
    shared: list[str] | None = None,
) -> list[str]:
    """Apply the round-18 routes to a route's steps; returns the new step list (notes / counts in place)."""
    steps = list(steps)
    # The recipes see the parsed spec; the round-18 transforms (`spec_transform`) decide here too.
    spec = spec_transform(spec, text)
    avoid = avoid if avoid is not None else {}
    shared = shared if shared is not None else []
    # 1. virtual try-on batch
    if try_on_batch(spec, text) and acc.prior("virtual_try_on_batch", "try_on_shared_model"):
        вещей = try_on_skus(spec, text)
        ракурсов = try_on_views(spec, text, вещей)
        своя = model_brought(spec, text)
        steps = [s for s in steps if s not in ("редактирование_изображения", "генерация_изображения", "примерка")]
        новые = ["примерка"]
        if not своя:
            новые = ["генерация_изображения", *новые]
            counts["генерация_изображения"] = ракурсов
            notes["генерация_изображения"] = NOTE_TRY_ON_BASE[0]
            shared.append("генерация_изображения")
        else:
            notes.pop("генерация_изображения", None)
        counts["примерка"] = вещей * ракурсов
        notes["примерка"] = NOTE_TRY_ON_SKU[0].format(skus=вещей, views=ракурсов, n=вещей * ракурсов)
        steps = [*новые, *steps]
    # 2. restoration chain: faces of the brought photos get their own pass
    if (
        "реставрация_изображения" in steps
        and FACE_RESTORE_STEP not in steps
        and faces_present(spec, text)
        and acc.prior("restoration_chain", "restore_faces_upscale_colour")
    ):
        i = steps.index("реставрация_изображения")
        steps = [*steps[: i + 1], FACE_RESTORE_STEP, *steps[i + 1 :]]
        notes[FACE_RESTORE_STEP] = NOTE_FACE_RESTORE[0]
        if "реставрация_изображения" in counts:
            counts[FACE_RESTORE_STEP] = counts["реставрация_изображения"]
    # Film: the deflicker / true-speed line is the round-8 one (`film_damage_not_blur`); faces get a line.
    if "реставрация" in steps and "video" in set(spec.inputs) and faces_present(spec, text):
        if acc.prior("restoration_chain", "restore_faces_upscale_colour"):
            acc.assembly.append(ASSEMBLY_FILM_FACES)
    # 3. speech batch
    if speech_batch(spec, text) and "озвучка" in steps or speech_batch(spec, text) and "клонирование_голоса" in steps:
        if acc.prior("speech_batch", "speech_lines_per_file"):
            строк = batch_lines(spec, text) or 1
            голосов = max(1, int(spec.characters or 0) or len([п for п in spec.people if п.get("speaks") is not False]) or 1)
            вариантов = batch_variations(spec, text)
            дублей = строк * голосов * вариантов
            реплика = line_seconds(spec, дублей)
            знаков = math.ceil(реплика * CHARS_PER_SECOND)
            шаг = "озвучка" if "озвучка" in steps else "клонирование_голоса"
            step_seconds[шаг] = (round(дублей * реплика, 3), реплика)
            counts[шаг] = дублей
            notes[шаг] = NOTE_SPEECH_BATCH[0].format(
                takes=дублей, lines=строк, voices=голосов, variations=вариантов, chars=знаков
            )
            acc.assembly.append(_speech_batch_line(строк, голосов, вариантов, знаков))
            acc.assembly.append(ASSEMBLY_SPEECH_FILES)
    # 4. podcast -> video
    if podcast_video(spec, text) and acc.prior("podcast_video", "podcast_audiogram"):
        from studio import routes_r17 as r17

        секунд = float(spec.duration_s or 0) or _seconds_in(spec, "audio")
        for s in PODCAST_DROPS:
            notes.pop(s, None)
        steps = [s for s in steps if s not in PODCAST_DROPS]
        новые = []
        if "photo" not in set(spec.inputs):
            новые.append("генерация_изображения")
            counts["генерация_изображения"] = 1
            notes["генерация_изображения"] = NOTE_PODCAST_COVER[0]
        новые.append("расшифровка")
        notes["расшифровка"] = NOTE_PODCAST_TRANSCRIPT[0]
        if секунд:
            step_seconds["расшифровка"] = (секунд, секунд)
        steps = [*новые, *(s for s in steps if s not in новые)]
        # The visualiser's loop / beat lines no longer describe the plan.
        acc.assembly[:] = [а for а in acc.assembly if not re.search(r"loop|beat|reactiv|петл|бит|реактив", а[1] + а[0], re.I)]
        acc.assembly.append(ASSEMBLY_AUDIOGRAM)
        acc.assembly.append(ASSEMBLY_CAPTIONS_SOFT if r17.soft_subtitles(spec) and not social_burn(spec) else ASSEMBLY_CAPTIONS_BURN)
        acc.assembly.append(ASSEMBLY_PODCAST_AVATAR)
    # 5. vertical reframe: captions for social
    if set(spec.edit) & {EDIT_REFRAME, EDIT_CROP} and "video" in set(spec.inputs) and vertical_target(spec):
        from studio import routes_r17 as r17

        if acc.prior("vertical_reframe", "reframe_tracked_crop"):
            секунд = float(spec.duration_s or 0) or _seconds_in(spec, "video")
            if social_burn(spec) and r17._speech_heard(spec):
                if "расшифровка" not in steps:
                    steps = ["расшифровка", *steps]
                notes["расшифровка"] = NOTE_REFRAME_TRANSCRIPT[0]
                if секунд:
                    step_seconds["расшифровка"] = (секунд, секунд)
                acc.assembly.append(ASSEMBLY_CAPTIONS_BURN)
            if секунд:
                acc.assembly.append(_reframe_alt_line(секунд))
    # 6. motion comic
    if motion_comic(spec, text) and acc.prior("motion_comic", "comic_panel_motion"):
        панелей = comic_panels(spec)
        секунд = float(spec.duration_s or 0) or панелей * 6.0
        на_панель = round(секунд / панелей, 2)
        for s in COMIC_DROPS:
            notes.pop(s, None)
        steps = [s for s in steps if s not in COMIC_DROPS]
        if "оживление" not in steps:
            steps = ["оживление", *steps]
        counts["оживление"] = панелей
        step_seconds["оживление"] = (секунд, на_панель)
        notes["оживление"] = NOTE_COMIC_I2V[0].format(n=панелей, s=f"{на_панель:g}")
        голос = spec.voiceover is not False and (
            spec.voiceover is True or "script" in set(spec.inputs) or "speech" in set(spec.outputs)
            or bool(W_NARRATION.search(_words(spec, text)))
        )
        if голос and "audio" not in set(spec.inputs):
            if "озвучка" not in steps:
                steps.append("озвучка")
            notes["озвучка"] = NOTE_COMIC_VO[0]
            step_seconds.setdefault("озвучка", (секунд, секунд))
        # A motion comic is sound-designed: effects unless the piece is named silent (`audio: none`).
        if spec.audio != "none":
            if "звук_фон" not in steps:
                steps.append("звук_фон")
            notes["звук_фон"] = NOTE_COMIC_SFX[0]
        acc.assembly[:] = [а for а in acc.assembly if а not in (ASSEMBLY_COMIC_SPLIT,)]
        acc.assembly += [ASSEMBLY_COMIC_SPLIT, ASSEMBLY_COMIC_PARALLAX, ASSEMBLY_COMIC_EDIT]
        from studio import expert_r18 as x18

        if x18.textless_needed(spec, text):
            acc.assembly.append(ASSEMBLY_COMIC_LETTERING)
    # 7. dance performance
    if dance_video(spec, text) and acc.prior("dance_performance", "dance_motion_transfer"):
        исполнителей = performers(spec)
        фото = _count([з for з in _items(spec, "photo") if з.get("role") in (None, "person", "model")])
        секунд = float(spec.duration_s or 0) or _seconds_in(spec, "audio") or 15.0
        for s in DANCE_DROPS:
            notes.pop(s, None)
        steps = [s for s in steps if s not in DANCE_DROPS and s != "липсинк"]
        новые = []
        стиллов = max(0, исполнителей - фото)
        if стиллов:
            новые.append("генерация_изображения")
            counts["генерация_изображения"] = стиллов
            notes["генерация_изображения"] = NOTE_DANCE_REF[0]
            shared.append("генерация_изображения")
        новые.append("перенос_движения")
        counts["перенос_движения"] = исполнителей
        step_seconds["перенос_движения"] = (исполнителей * секунд, min(секунд, 30.0))
        notes["перенос_движения"] = NOTE_DANCE_MOTION[0].format(n=исполнителей, s=f"{секунд:g}")
        avoid["перенос_движения"] = DANCE_AVOID
        from studio import routes_r17 as r17

        if r17.sings_on_screen(spec, text) and getattr(spec, "lipsync", None) is not False and "audio" in set(spec.inputs):
            новые.append("липсинк")
            step_seconds["липсинк"] = (исполнителей * секунд, секунд)
        steps = [*новые, *(s for s in steps if s not in новые)]
        driver = "video" in set(spec.inputs) or "motion" in _roles(spec)
        acc.assembly.append(ASSEMBLY_DANCE_OWN_DRIVER if driver else ASSEMBLY_DANCE_DRIVER)
        if исполнителей > 1 or "audio" in set(spec.inputs):
            acc.assembly.append(ASSEMBLY_DANCE_COMPOSITE)
    # 8. a UGC / avatar series with one presenter: ONE presenter still
    if (
        spec.task == "avatar"
        and set(steps) & {"генерация_изображения", "говорящий_аватар"}
        and not set(spec.inputs) & {"photo", "video"}
        and int(spec.shots or 0) >= 2
        and int(spec.characters or 1) <= 1
        and len(spec.people) <= 1
        and "ugc_shared_references" not in acc.priors
        and counts.get("генерация_изображения", 0) != 1
    ):
        if acc.prior("single_host_series", "single_reference"):
            if "генерация_изображения" not in steps:
                steps = ["генерация_изображения", *steps]
            counts["генерация_изображения"] = 1
            shared.append("генерация_изображения")
    return list(dict.fromkeys(steps))
