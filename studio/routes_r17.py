"""Round 17: the routes a fresh hidden set found missing (spec first, EN/RU words only as fallback).

The contract of rounds 15-16 holds: the CALLING model fills `spec` in any brief language, a named
field decides both ways, and the EN/RU words below are read only when the field is absent
(docs/MCP_AGENT.md, "round 17"). Each route rewrites the plan's steps in `recipes.apply.rewrite`
(`rewrite`) and is priced by the planner's own step prices; what no endpoint does is a priced
assembly line or a recorded gap — never a video model pretending to do it.

1. BURNED-IN SUBTITLES TO TRANSLATE — `inputs[].subtitles: "burned"` on the video item (words:
   `W_BURNED_SUBS`). The old text is found (a timed transcript of the speech; OCR of the burned strip
   to keep the exact wording), translated (machine translation, priced per character), REMOVED by a
   masked video edit (`edit: remove-object`, `edit_target: text`) and the new subtitles are burned in at
   assembly — or delivered as a soft track when the platform takes one (`delivery.format: srt`, or a
   platform in `SOFT_SUB_PLATFORMS`).
2. SINGER MUSIC VIDEO FROM A PERFORMER REFERENCE — performer photos (or one generated reference), one
   reference-to-video clip per performer shot, lip sync to the customer's track on THOSE shots only
   (`performer_shots`, else every shot); the other shots are key stills animated image-to-video without
   lips. `people[].on_screen` / `speaks` (or `lipsync`) decide that anybody sings on screen.
3. 3D WALKTHROUGH / TOUR — `reconstruct_3d: true` (or `delivery.format` ply / splat / spz; words
   `W_SCENE_3D`): a gaussian-splat reconstruction (capture -> COLMAP poses -> splat training ->
   rendered camera path). No orderable endpoint trains a splat: the step is a recorded gap with the
   named tools from the fact base (gsplat / nerfstudio splatfacto, Apache-2.0; the Inria original is
   non-commercial) and its compute price is a recorded gap, never a guess.
4. CONSENTED INTERNAL DEEPFAKE (security awareness) — `studio/consented_simulation.py` (the narrow
   fields-only door) and the safeguard caveat (`checklist.consented_simulation_safeguards`).
5. WHOLE-PERSON REPLACEMENT — `edit: ["replace-person"]` (words `W_WHOLE_PERSON` beside a person edit):
   the person is replaced whole (body, costume, identity) by a character-replacement model (Wan Animate
   replace class, priced per second), not a face swap, which only moves a face.
6. UGC PRODUCT BATCH — N clips about P products (`products`, else the brought product photos, else
   the words): one shared presenter reference and one packshot per product, reused by every clip —
   never a still per clip (stills <= products + 1).
7. NARRATION WITHOUT AUDIO — `voiceover: true` / `audio: voiceover` / `audio_content: ["speech"]` with
   no audio brought: the speech is an output, so the plan has a TTS step (`with_narration`).

DECISION CONSTANTS (mutated both ways by `scripts/mutate_round17_routes.py`): `SPLAT_PHOTOS_MIN`,
`TRANSLATE_USD_PER_M_CHARS`, `TRANSLATE_FREE_CHARS`, `OCR_USD_PER_MIN`, `OCR_FREE_MIN`,
`SOFT_SUB_PLATFORMS`, `UGC_CLIPS_MIN`, `SHARED_PRESENTER`, `NARRATION_TASKS`, `SUBTITLE_EDIT_TASKS`,
`PERFORMER_TASKS`, `SCENE_3D_DROPS`, `WHOLE_PERSON_FROM`.

This module imports nothing from `studio` at module level (`brief_spec` and `l10n` import it).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import replace
from typing import Any

SOURCE_DERIVED = "derived"


def _words(spec: Any, text: str = "") -> str:
    return " ".join((str(text or ""), *map(str, getattr(spec, "conditions", None) or ())))


def _named(spec: Any, name: str) -> bool:
    return name in (getattr(spec, "source", None) or {})


def _delivery(spec: Any) -> Mapping[str, Any]:
    сдача = getattr(spec, "delivery", None)
    return сдача if isinstance(сдача, Mapping) else {}


def _seconds(spec: Any) -> float:
    if getattr(spec, "duration_s", None):
        return float(spec.duration_s)
    длины = [
        float(з.get("duration_s") or 0)
        for з in getattr(spec, "input_items", None) or ()
        if isinstance(з, Mapping) and з.get("kind") in ("video", "audio")
    ]
    return max(длины, default=0.0)


# --- 7. narration named, no audio brought -------------------------------------------------------

#: Tasks whose picture gets a narration when the speech is named but no audio is brought.
NARRATION_TASKS: frozenset[str | None] = frozenset({None, "generate", "animate", "r2v", "video-edit", "turntable"})
ASSUMPTION_NARRATION = (
    "a voice-over is named (voiceover / audio / audio_content) and no audio is brought: the speech is "
    "synthesised from the script (a TTS step) and laid over the picture; pass spec.voiceover=false for none"
)


def narration_named(spec: Any) -> bool:
    """Spoken narration named by a field: `voiceover: true`, `audio: voiceover`, `audio_content: speech`."""
    if getattr(spec, "voiceover", None) is False:
        return False
    return (
        getattr(spec, "voiceover", None) is True
        or getattr(spec, "audio", None) == "voiceover"
        or "speech" in set(getattr(spec, "audio_content", None) or ())
    )


def with_narration(spec: Any) -> Any:
    """`speech` joins the outputs when narration is named and nobody brought the audio (round 17)."""
    if "speech" in set(spec.outputs) or "video" not in set(spec.outputs) or "audio" in set(spec.inputs):
        return spec
    if spec.task not in NARRATION_TASKS or spec.then_tasks or not narration_named(spec):
        return spec
    # The speech of YOUR footage (audio_content: speech on a brought video) is its own, not a narration.
    if "video" in set(spec.inputs) and spec.voiceover is not True and spec.audio != "voiceover":
        return spec
    источник = {**dict(spec.source), "outputs": spec.source.get("outputs") or SOURCE_DERIVED}
    поля: dict[str, Any] = {"outputs": (*spec.outputs, "speech"), "source": источник}
    if spec.audio is None and "video" in set(spec.inputs):
        # Over the customer's footage the voice is a voice-over (the route keeps the source sound otherwise).
        поля["audio"] = "voiceover"
        источник["audio"] = SOURCE_DERIVED
    поля["assumptions"] = tuple(dict.fromkeys((*spec.assumptions, ASSUMPTION_NARRATION)))
    return replace(spec, **поля)


# --- 1. burned-in subtitles ----------------------------------------------------------------------

#: Burned-in (hard / open) subtitles named in words (EN/RU) — read only when no video item names `subtitles`.
W_BURNED_SUBS = re.compile(
    r"burn(?:ed|t)[- ]?in (?:\w+ ){0,2}(?:sub(?:title)?s?|captions?)|hard[- ]?(?:coded|burned|burnt) (?:\w+ ){0,2}(?:sub(?:title)?s?|captions?)"
    r"|\bhard[- ]?subs?\b|\bhard (?:sub(?:title)?s|captions)\b"
    r"|hard[- ]?subbed|hardsub\w*|open captions?"
    r"|(?:sub(?:title)?s?|captions?) (?:are |is )?(?:burned|burnt|baked|embedded|printed|hard[- ]?coded) (?:in|into|on)"
    r"|(?:вшит|прожж[её]нн|прошит|встроенн|зашит|вжжен|вожжен|впечатанн)\w* (?:в (?:кадр|видео|картинку) )?субтитр\w*"
    r"|субтитр\w* (?:\w+ )?(?:вшиты|прожжены|встроены|впечатаны|зашиты) в (?:кадр|видео|картинку)|хардсаб\w*",
    re.I,
)
#: An order to ADD new burned captions ("add burned-in captions") is not footage that already has them —
#: unless the words also speak of the old ones (translate / remove / replace / existing).
W_ADD_SUBS = re.compile(
    r"\b(?:add|create|generate|make|put|burn)\w*\s+(?:[\w-]+\s+){0,3}(?:sub(?:title)?s?|captions?)\b"
    r"|(?:добав|сдела|созда|наложи|вше[йи])\w*\s+(?:[\w-]+\s+){0,2}субтитр\w*",
    re.I,
)
W_OLD_SUBS = re.compile(
    r"translat|remov|replac|existing|original|already|old (?:sub|caption)"
    r"|перев[её]д|перевод|убер|убра|замен|стары\w* субтитр|уже",
    re.I,
)
#: Platforms that take a separate subtitle track (soft subs); short-form social apps get them burned.
SOFT_SUB_PLATFORMS: frozenset[str] = frozenset({"youtube", "streaming-premium", "broadcast", "web", "internal", "editorial"})
#: Delivery formats that ARE a soft subtitle track.
SOFT_SUB_FORMATS: frozenset[str] = frozenset({"srt"})
#: Tasks an order to translate burned subtitles comes under (the route becomes the video edit).
SUBTITLE_EDIT_TASKS: frozenset[str | None] = frozenset({None, "video-edit", "edit", "captions", "face-replace", "generate"})
#: Tasks whose route has no edit step of its own: the removal of the old band is ADDED (a dub keeps its
#: dub; a recap / shorts cut keeps its cut — round-17 integration — and the removal covers its seconds).
SHORTS_TASK = "cut-to-shorts"
#: `brief_spec.EDIT_BURN_CAPTIONS` (not imported: this module stays light).
EDIT_BURN_CAPTIONS = "burn-captions"
SUBTITLE_ADD_REMOVAL_TASKS: frozenset[str] = frozenset({"dub-translate", SHORTS_TASK})
#: The "multiple languages" tag names the SOURCE's mixed speech (`expert_r17.MULTIPLE_LANGUAGES_TAG`),
#: never a translation target.
MIXED_LANGUAGE_TAG = "mul"
#: Machine translation price (Google Cloud Translation NMT, `model_facts.jsonl` google-cloud-translation,
#: READ 2026-10-20): $20 per million characters, the first 500,000 characters a month free.
TRANSLATE_USD_PER_M_CHARS = 20.0
TRANSLATE_FREE_CHARS = 500_000
TRANSLATE_SOURCE = "https://cloud.google.com/translate/pricing"
#: OCR of on-screen text (Google Video Intelligence text detection, `model_facts.jsonl`
#: google-cloud-video-intelligence, READ 2026-10-20): $0.15 per minute, the first 1,000 minutes a month free.
OCR_USD_PER_MIN = 0.15
OCR_FREE_MIN = 1000
OCR_SOURCE = "https://cloud.google.com/video-intelligence/pricing"
#: Characters per second of speech (the planner's own TTS estimate, `pricing.CHARS_PER_SECOND`).
CHARS_PER_SECOND = 15.0

ASSUMPTION_SUBTITLES = (
    "burned-in subtitles on YOUR video: the old text is removed by a masked video edit (edit remove-object, "
    "edit_target text) and the translated subtitles are added at assembly; pass inputs[].subtitles='soft' or "
    "'none' if they are not in the picture"
)


def subtitle_state(spec: Any) -> str | None:
    """`inputs[].subtitles` of the brought VIDEO: burned | soft | none; None — no video item names it."""
    значения = [
        str(з.get("subtitles"))
        for з in getattr(spec, "input_items", None) or ()
        if isinstance(з, Mapping) and з.get("kind") == "video" and з.get("subtitles")
    ]
    if not значения:
        return None
    return "burned" if "burned" in значения else значения[0]


def burned_subtitles(spec: Any, text: str = "") -> bool:
    """The brought video carries burned-in subtitles: the field first, the words when it is absent."""
    if "video" not in set(getattr(spec, "inputs", ()) or ()):
        return False
    поле = subtitle_state(spec)
    if поле is not None:
        return поле == "burned"
    # Round-17 integration: a shorts cut BURNS IN its own new captions, so "burned-in subtitles" in its
    # brief describe the output, not the source — only the field names old subtitles there.
    if getattr(spec, "task", None) == SHORTS_TASK:
        return False
    # Likewise an edit list the CALLER named with burn-captions: the burned captions are the new ones.
    if EDIT_BURN_CAPTIONS in set(getattr(spec, "edit", None) or ()) and (getattr(spec, "source", None) or {}).get("edit") == "spec":
        return False
    слова = _words(spec, text)
    if W_ADD_SUBS.search(слова) and not W_OLD_SUBS.search(слова):
        return False
    return bool(W_BURNED_SUBS.search(слова))


def soft_subtitles(spec: Any) -> bool:
    """The new subtitles go as a separate track: an srt delivery, or a platform that takes one."""
    сдача = _delivery(spec)
    if set(сдача.get("format") or ()) & SOFT_SUB_FORMATS:
        return True
    площадки = set(сдача.get("platform") or ())
    return bool(площадки) and площадки <= SOFT_SUB_PLATFORMS


def with_subtitle_edit(spec: Any, text: str = "") -> Any:
    """Burned subtitles: the edit removes the old text (remove-object on text); burning is assembly."""
    if not burned_subtitles(spec, text):
        return spec
    задача = spec.task
    if задача != "dub-translate" and задача not in SUBTITLE_EDIT_TASKS:
        return spec
    from studio import brief_spec as bs
    from studio import endpoints as ep

    правки = [п for п in spec.edit if п not in (ep.EDIT_REPLACE_TEXT, ep.EDIT_REPLACE_OBJECT, bs.EDIT_BURN_CAPTIONS)]
    правки.append(ep.EDIT_REMOVE_OBJECT)
    правки_t = tuple(dict.fromkeys(правки))
    if (
        правки_t == tuple(spec.edit)
        and spec.edit_target == "text"
        and (задача == "dub-translate" or задача == "video-edit")
    ):
        return spec
    источник = {**dict(spec.source), "edit": SOURCE_DERIVED, "edit_target": spec.source.get("edit_target") or SOURCE_DERIVED}
    поля: dict[str, Any] = {"edit": правки_t, "edit_target": "text", "source": источник}
    if задача != "dub-translate":
        поля["task"] = "video-edit"
        источник["task"] = spec.source.get("task") if задача == "video-edit" else SOURCE_DERIVED
    поля["assumptions"] = tuple(dict.fromkeys((*spec.assumptions, ASSUMPTION_SUBTITLES)))
    return replace(spec, **поля)


def _translation_line(spec: Any) -> tuple[str, str]:
    секунд = _seconds(spec)
    цели = [т for т in getattr(spec, "language_tags", ()) or () if str(т).split("-")[0].lower() != MIXED_LANGUAGE_TAG]
    языков = max(1, len(цели))
    знаков = math.ceil(секунд * CHARS_PER_SECOND) * языков
    usd = знаков * TRANSLATE_USD_PER_M_CHARS / 1_000_000
    сумма = f"≈{знаков} chars × {TRANSLATE_USD_PER_M_CHARS:g} usd per 1M = {usd:.2f} usd"
    return (
        f"перевод текста субтитров машинным переводом (Google Cloud Translation NMT: {TRANSLATE_USD_PER_M_CHARS:g} usd "
        f"за 1 млн знаков, первые {TRANSLATE_FREE_CHARS} знаков в месяц бесплатно; {сумма}) — затем вычитка "
        f"носителем языка; {TRANSLATE_SOURCE}",
        f"the subtitle text is machine-translated (Google Cloud Translation NMT: {TRANSLATE_USD_PER_M_CHARS:g} usd per "
        f"1M characters, the first {TRANSLATE_FREE_CHARS} characters a month free; {сумма}), then proofread by a "
        f"native speaker; {TRANSLATE_SOURCE}",
    )


def _ocr_line(spec: Any) -> tuple[str, str]:
    минут = math.ceil(_seconds(spec) / 60) if _seconds(spec) else 0
    usd = минут * OCR_USD_PER_MIN
    сумма = f"{минут} min × {OCR_USD_PER_MIN:g} usd = {usd:.2f} usd above the free {OCR_FREE_MIN} min a month"
    return (
        f"вшитый текст читается OCR по кадрам (точная формулировка и тайминги старых субтитров): Google Video "
        f"Intelligence text detection ({сумма}; {OCR_SOURCE}) или PaddleOCR / VideOCR на своей машине — 0 usd API",
        f"the burned text is read by OCR frame by frame (the exact wording and timing of the old subtitles): Google "
        f"Video Intelligence text detection ({сумма}; {OCR_SOURCE}) or PaddleOCR / VideOCR on your own machine — "
        "0 usd API",
    )


NOTE_SUBS_TRANSCRIPT = (
    "расшифровка речи ВАШЕГО видео с таймингами — основа новых субтитров (сверяется с OCR вшитой строки)",
    "a timed transcript of the speech of YOUR video — the basis of the new subtitles (checked against an OCR "
    "of the burned strip)",
)
NOTE_SUBS_REMOVE = (
    "старые вшитые субтитры убираются правкой по маске полосы субтитров (видео-инпейнт, трекинг по кадрам); "
    "запасной путь — плашка или кадрирование полосы при сборке, 0 usd",
    "the old burned-in subtitles are removed by a masked edit of the subtitle band (video inpaint, tracked "
    "across frames); the fallback is a box or a crop of the band at assembly, 0 usd",
)
ASSEMBLY_SUBS_BURN = (
    "новые субтитры вшиваются при сборке (ffmpeg subtitles / libass, шрифт с глифами целевого языка) — 0 usd",
    "the new subtitles are burned in at assembly (ffmpeg subtitles / libass, a font with the target script's "
    "glyphs) — 0 usd",
)
ASSEMBLY_SUBS_SOFT = (
    "новые субтитры сдаются ОТДЕЛЬНОЙ дорожкой (SRT / WebVTT, площадка их принимает) — картинка без текста, 0 usd",
    "the new subtitles are delivered as a SEPARATE track (SRT / WebVTT, the platform takes them) — a clean "
    "picture, 0 usd",
)
ASSEMBLY_SUBS_SOFT_ALT = (
    "если площадка принимает дорожку субтитров (YouTube, стриминг), их можно сдать отдельно (SRT / WebVTT) вместо вшивания",
    "if the platform takes a subtitle track (YouTube, streaming), they can be delivered separately (SRT / WebVTT) "
    "instead of burned in",
)


def _speech_heard(spec: Any) -> bool:
    """The brought video has speech to transcribe: `audio_content` named without speech says no."""
    if _named(spec, "audio_content"):
        return "speech" in set(spec.audio_content)
    return getattr(spec, "voiceover", None) is not False


# --- 2. singer music video from a performer reference ---------------------------------------------

#: Tasks of a generated music video with a singing performer.
PERFORMER_TASKS: frozenset[str | None] = frozenset({None, "generate", "r2v", "music-visualiser"})
#: The performer shots' step: with it in the plan, lip sync + image-to-video are NOT one avatar step.
PERFORMER_REF_STEP = "видео_по_референсу"
#: Steps the performer route replaces (the generated picture and the lips are rebuilt from scratch).
PERFORMER_DROPS: frozenset[str] = frozenset(
    {"генерация_изображения", "оживление", "генерация_видео", "видео_по_референсу", "липсинк", "говорящий_аватар"}
)
NOTE_PERFORMER_REF = (
    "референс исполнителя: снимок в полный рост и крупный план лица в образе клипа — один на все шоты",
    "the performer reference: a full-length still and a face close-up in the video's look — one for every shot",
)
NOTE_PERFORMER_R2V = (
    "шоты с исполнителем: каждый — видео по референсу исполнителя (одна внешность во всех сценах)",
    "the performer shots: each is reference-to-video from the performer reference (one look in every scene)",
)
NOTE_PERFORMER_LIPS = (
    "липсинк к вокалу ВАШЕГО трека — только на шотах, где исполнитель поёт в кадре (вокальный стем, demucs)",
    "lip sync to the vocals of YOUR track — only on the shots where the performer sings on camera (a vocal "
    "stem, demucs)",
)
NOTE_BROLL_STILLS = (
    "ключевые кадры шотов без исполнителя (атмосфера, детали, город) — по кадру на шот",
    "key stills of the shots without the performer (atmosphere, details, places) — one per shot",
)
NOTE_BROLL_I2V = (
    "шоты без исполнителя оживляются по ключевому кадру (image-to-video), без губ",
    "the shots without the performer are animated from their key still (image-to-video), no lips",
)
ASSEMBLY_PERFORMER = (
    "шоты кладутся под ВАШ трек по биту (монтаж, ffmpeg) — исполнительские с липсинком, остальные без — 0 usd",
    "the shots are cut to YOUR track on the beat (assembly, ffmpeg) — performer shots lip-synced, the rest "
    "without — 0 usd",
)
ASSUMPTION_PERFORMER_SHOTS = (
    "the performer sings in every one of the {n} shots (performer_shots not named) — pass spec.performer_shots "
    "for how many shots show the performer singing; the rest are animated without lips"
)


def sings_on_screen(spec: Any, text: str = "") -> bool:
    """Somebody sings the customer's track on camera: `lipsync`, then `people[].on_screen + speaks`, then words."""
    if getattr(spec, "lipsync", None) is not None:
        return bool(spec.lipsync)
    описаны = [п for п in spec.people if п.get("on_screen") is not None or п.get("speaks") is not None]
    if описаны:
        return any(п.get("on_screen") is True and п.get("speaks") is True for п in описаны)
    from studio import brief_spec as bs

    return bool(bs.SINGING.search(bs.исполнитель_словами(_words(spec, text))))


def performer_video(spec: Any, text: str = "") -> bool:
    """A music video to YOUR track with a singing performer on camera and several scenes."""
    if "video" not in set(spec.outputs) or "audio" not in set(spec.inputs) or "video" in set(spec.inputs):
        return False
    if spec.task not in PERFORMER_TASKS or "speech" in set(spec.outputs):
        return False
    if getattr(spec, "performer_shots", None) == 0:
        return False
    if int(spec.shots or 0) < 2:
        return False
    return sings_on_screen(spec, text)


def performer_split(spec: Any) -> tuple[int, int]:
    """(performer shots, other shots)."""
    всего = int(spec.shots or 0)
    названо = getattr(spec, "performer_shots", None)
    поёт = всего if названо is None else min(int(названо), всего)
    return поёт, всего - поёт


# --- 3. 3D walkthrough / tour (gaussian splat) ------------------------------------------------------

#: 3D scene words (EN/RU) — read only when `reconstruct_3d` and a splat `delivery.format` are absent.
W_SCENE_3D = re.compile(
    r"gaussian[- ]splat\w*|\b3dgs\b|\bsplat(?:s|ting)?\b|\bnerf\b|neural radiance|radiance field"
    r"|\b3d[- ](?:walk-?through|tour|scan|reconstruction|capture|fly-?through|twin|space|scene)"
    r"|digital twin|matterport|navigable|explorable|free[- ]viewpoint|\b6[- ]?dof\b"
    r"|гауссов\w* сплат\w*|сплат\w*|\b3d[- ]?(?:тур|скан|реконструкц\w*|облёт|облет|прогулк\w*|модел\w* помещени\w*)"
    r"|3д[- ]?(?:тур|скан|облёт|облет)|цифров\w* двойник\w*",
    re.I,
)
#: Steps the 3D route replaces: a video model does not reconstruct a place.
SCENE_3D_DROPS: frozenset[str] = frozenset(
    {"оживление", "генерация_видео", "перенос_движения", "оборот_360", "модель_3d", "видео_по_референсу", "генерация_изображения"}
)
SCENE_3D_STEP = "реконструкция_3d"
#: The step's requirement (`planner.OPERATIONS`), both answer languages.
REQUIREMENT_SCENE_3D = (
    "3D-сцена места по снимкам с перекрытием: геометрия и вид сходятся со всеми ракурсами съёмки",
    "a 3D scene of the place from overlapping photos: geometry and look agree with every capture angle",
)
#: A splat needs dozens of overlapping views (`recipes.apply.SPLAT_PHOTOS_MIN` is the same number).
SPLAT_PHOTOS_MIN = 20
SPLAT_FORMATS: tuple[str, ...] = ("ply", "splat", "spz")

NOTE_SCENE_3D = (
    "3D-реконструкция места гауссовым сплатом: позы камер по снимкам (COLMAP), обучение сплата (gsplat / "
    "nerfstudio splatfacto, Apache-2.0, ~6-12 ГБ VRAM; оригинал Inria — только некоммерческий), экспорт .ply; "
    "API-эндпоинта нет — шаг на вашем GPU или в приложении (Postshot, Polycam, Luma: цена не записана)",
    "a 3D reconstruction of the place as a gaussian splat: camera poses from the photos (COLMAP), splat training "
    "(gsplat / nerfstudio splatfacto, Apache-2.0, ~6-12 GB VRAM; the Inria original is non-commercial only), "
    "export .ply; no API endpoint does it — the step runs on your GPU or in an app (Postshot, Polycam, Luma: "
    "price not recorded)",
)
ASSEMBLY_SPLAT_RENDER = (
    "облёт рендерится из сплата по пути камеры (nerfstudio ns-render / SuperSplat) — видеомодель не нужна, 0 usd",
    "the fly-through video is rendered from the splat along a camera path (nerfstudio ns-render / SuperSplat) — "
    "no video model, 0 usd",
)
ASSEMBLY_SPLAT_VIEWER = (
    "сплат сдаётся файлом .ply / .splat / .spz для веб-просмотрщика (SuperSplat, three.js GaussianSplats3D) — 0 usd",
    "the splat is delivered as a .ply / .splat / .spz file for a web viewer (SuperSplat, three.js GaussianSplats3D) "
    "— 0 usd",
)
ASSEMBLY_SPLAT_CAPTURE = (
    "съёмка для сплата: {n}+ снимков с перекрытием 60-80 % по кругу каждой комнаты, фиксированные экспозиция и "
    "баланс белого, без людей и движения; или медленный проход видео 4K и кадры ffmpeg ~2 в секунду",
    "capture for a splat: {n}+ photos overlapping 60-80 % around every room, locked exposure and white balance, "
    "no people or motion; or a slow 4K walk-through video and frames extracted by ffmpeg at ~2 per second",
)
#: The recorded gap the step carries instead of a price.
GAP_SPLAT_COMPUTE = (
    "цена обучения сплата — ПРОБЕЛ: минуты GPU на сцену не записаны ни одним читаемым источником (docs.gsplat.studio, "
    "jawset.com, poly.cam, lumalabs.ai закрыты политикой); ставка аренды GPU записана (runpod-rtx-4090)",
    "the splat training price is a GAP: GPU minutes per scene are not recorded by any readable source "
    "(docs.gsplat.studio, jawset.com, poly.cam, lumalabs.ai refused by the policy); the GPU rental rate is "
    "recorded (runpod-rtx-4090)",
)


def reconstruct_3d(spec: Any, text: str = "") -> bool:
    """A 3D reconstruction of a real place: the field, then a splat delivery format, then the words."""
    if not set(spec.inputs) & {"photo", "video"}:
        return False
    поле = getattr(spec, "reconstruct_3d", None)
    if isinstance(поле, bool):
        return поле
    форматы = set(_delivery(spec).get("format") or ())
    if форматы & set(SPLAT_FORMATS):
        return True
    return bool(W_SCENE_3D.search(_words(spec, text)))


# --- 5. whole-person replacement ---------------------------------------------------------------------

EDIT_REPLACE_PERSON = "replace-person"
#: Whole-person replacement in words (EN/RU) — read only when `spec.edit` does not name it.
W_WHOLE_PERSON = re.compile(
    r"whole (?:body|person|figure|character)|full[- ]body|entire (?:body|person|figure)|head to toe"
    r"|(?:body|costume|outfit|clothes|clothing|identity) (?:and|&) (?:the )?face|face (?:and|&) (?:the )?(?:body|costume|outfit)"
    r"|(?:replace|swap) (?:the |our |my )?(?:actor|actress|person|man|woman|performer|presenter|host)\w* (?:entirely|completely|whole)"
    r"|different (?:person|actor|actress) entirely|character replacement|person replacement"
    r"|цел(?:иком|ую фигуру|ого человека)|в полный рост|вс(?:ю|его) фигур\w*|(?:тело|костюм|одежд\w*) и лицо|лицо и (?:тело|костюм|одежд\w*)"
    r"|замен\w* (?:актёра|актера|человека|ведущ\w*|героя) целиком",
    re.I,
)
#: Steps a whole-person replacement takes over (a face swap or a generic edit of the person).
WHOLE_PERSON_FROM: frozenset[str] = frozenset({"замена_персонажа", "правка_видео"})
NOTE_WHOLE_PERSON = (
    "человек в ВАШЕМ видео заменяется ЦЕЛИКОМ (тело, костюм, лицо, движение исходника) моделью замены персонажа "
    "(класс Wan Animate replace, цена за секунду) — это не замена лица, которая переносит только лицо",
    "the person in YOUR video is replaced WHOLE (body, costume, face, the source motion) by a character-replacement "
    "model (Wan Animate replace class, priced per second) — not a face swap, which only moves a face",
)
NOTE_WHOLE_PERSON_REF = (
    "референс нового персонажа: снимок в полный рост в нужном костюме (ваше фото согласного человека заменяет этот шаг)",
    "the new character's reference: a full-length still in the wanted costume (a photo of a consenting person "
    "replaces this step)",
)


def whole_person(spec: Any, text: str = "") -> bool:
    """The edit replaces the whole person: `edit: replace-person`, else the words beside a person edit."""
    if "video" not in set(spec.inputs):
        return False
    if EDIT_REPLACE_PERSON in set(spec.edit):
        return True
    if spec.task not in ("face-replace", "video-edit", "edit") or (spec.edit_target not in (None, "person")):
        return False
    if _named(spec, "edit") and spec.edit:
        return False
    return bool(W_WHOLE_PERSON.search(_words(spec, text)))


# --- 6. UGC product batch -------------------------------------------------------------------------------

#: A batch starts at this many clips (`expert_r16.BATCH_CLIPS_MIN` is the same number).
UGC_CLIPS_MIN = 3
#: One presenter reference shared by every clip.
SHARED_PRESENTER = 1
W_UGC = re.compile(
    r"\bugc\b|tiktok[- ]?shop|amazon (?:listing|influencer)|product (?:clips?|videos?|ads?) for|user[- ]generated"
    r"|юджиси|ugc-ролик\w*|ролик\w* (?:для|про) товар\w*|тикток[- ]?шоп",
    re.I,
)
W_PRODUCTS = re.compile(
    r"(\d{1,3})\s+(?:different\s+|distinct\s+)?(?:products|items|skus|товар\w*|продукт\w*|позици\w*)", re.I
)
NOTE_UGC_STILLS = (
    "общие референсы пачки: один ведущий на все ролики и по кадру товара (packshot) на товар — не кадр на каждый ролик",
    "the batch's shared references: one presenter for every clip and one packshot per product — never a still per clip",
)
ASSUMPTION_UGC_PRODUCTS = (
    "a UGC batch of {clips} clips about {products} products: one shared presenter reference and one packshot per "
    "product are made once and reused by every clip — pass spec.products to change the count"
)


def products_count(spec: Any, text: str = "") -> int | None:
    """How many distinct products: the field, then the brought product photos, then the words."""
    if getattr(spec, "products", None):
        return int(spec.products)
    from studio import spec_first as sf

    фото = sum(int(з.get("count") or 1) for з in spec.input_items if isinstance(з, Mapping) and з.get("kind") == "photo")
    if фото and sf.subject(spec, "product", "cosmetic"):
        return фото
    м = W_PRODUCTS.search(_words(spec, text))
    return int(м.group(1)) if м else None


def ugc_batch(spec: Any, text: str = "") -> bool:
    """N product clips: `products` named, or a product subject / UGC words with a batch of clips."""
    if "video" not in set(spec.outputs) or "video" in set(spec.inputs):
        return False
    if spec.task not in (None, "generate", "avatar", "r2v", "animate"):
        return False
    if int(spec.shots or 0) < UGC_CLIPS_MIN:
        return False
    if getattr(spec, "products", None):
        return True
    from studio import spec_first as sf

    предмет = sf.subject(spec, "product", "cosmetic")
    if предмет is False:
        return False
    return bool(предмет or W_UGC.search(_words(spec, text))) and products_count(spec, text) is not None


def ugc_stills(spec: Any, text: str = "") -> int:
    """Stills the batch makes: the shared presenter (unless brought) + a packshot per product (unless brought)."""
    товаров = products_count(spec, text) or 0
    from studio import spec_first as sf

    фото = sum(int(з.get("count") or 1) for з in spec.input_items if isinstance(з, Mapping) and з.get("kind") == "photo")
    packshots_brought = bool(фото) and (sf.subject(spec, "product", "cosmetic") is not False)
    ведущий = SHARED_PRESENTER if (any(п.get("on_screen") is not False for п in spec.people) or (spec.characters or 0) >= 1) else 0
    if spec.task == "avatar" and not ведущий:
        ведущий = SHARED_PRESENTER
    return ведущий + (0 if packshots_brought else товаров)


# --- 4. consented internal deepfake (security awareness) ------------------------------------------------

W_SECURITY_TRAINING = re.compile(
    r"security[- ]awareness|phishing (?:simulation|test|drill|training|exercise)|vishing|smishing"
    r"|social[- ]engineering (?:test|drill|training|exercise|simulation)|red[- ]team\w*|ceo fraud|\bbec\b"
    r"|deepfake (?:awareness|training|drill|simulation)|spot (?:a |the )?deepfakes?"
    r"|учени\w* по (?:фишинг\w*|безопасност\w*|социальн\w*)|фишинг\w* (?:учени\w*|тренинг\w*|симуляц\w*)"
    r"|обучени\w* (?:по )?(?:информационной |кибер)?безопасност\w*|распознава\w* дипфейк\w*",
    re.I,
)
ASSEMBLY_SIM_WATERMARK = (
    "видимый водяной знак СИМУЛЯЦИЯ (создано ИИ) в каждом кадре (ffmpeg drawtext) и C2PA; ролик выкладывается "
    "только во внутренний LMS / интранет за логином — 0 usd",
    "a visible SIMULATION (AI-generated) watermark in every frame (ffmpeg drawtext) and C2PA credentials; the "
    "clip goes only to the internal LMS / intranet behind a login — 0 usd",
)


def security_training(spec: Any, text: str = "") -> bool:
    """A security-awareness drill: `domain` named decides, the words only when it is absent."""
    if _named(spec, "domain"):
        return "security-awareness" in set(getattr(spec, "domain", None) or ())
    return bool(W_SECURITY_TRAINING.search(_words(spec, text)))


def consented_drill(spec: Any, text: str = "") -> bool:
    """A real person's likeness made for a security-awareness drill (the safeguard caveat)."""
    return security_training(spec, text) and any(п.get("real") is True for п in getattr(spec, "people", None) or ())


# --- notes, localisation -------------------------------------------------------------------------------

NOTE_PAIRS: tuple[tuple[str, str], ...] = (
    NOTE_SUBS_TRANSCRIPT, NOTE_SUBS_REMOVE, ASSEMBLY_SUBS_BURN, ASSEMBLY_SUBS_SOFT, ASSEMBLY_SUBS_SOFT_ALT,
    NOTE_PERFORMER_REF, NOTE_PERFORMER_R2V, NOTE_PERFORMER_LIPS, NOTE_BROLL_STILLS, NOTE_BROLL_I2V, ASSEMBLY_PERFORMER,
    NOTE_SCENE_3D, REQUIREMENT_SCENE_3D, ASSEMBLY_SPLAT_RENDER, ASSEMBLY_SPLAT_VIEWER, GAP_SPLAT_COMPUTE,
    NOTE_WHOLE_PERSON, NOTE_WHOLE_PERSON_REF, NOTE_UGC_STILLS, ASSEMBLY_SIM_WATERMARK,
)  # fmt: skip


def l10n_pairs() -> tuple[tuple[str, str], ...]:
    """(ru regex, en) rows for `studio/l10n.py`, the templated assembly lines included."""
    ряды = [(re.escape(ru), en) for ru, en in NOTE_PAIRS]
    # The whole-character step's bilingual requirement (`planner.OPERATIONS`), now on the whole-person route too.
    ряды.append((
        re.escape("персонаж заменён целиком: фигура, силуэт и движение исходного кадра, свет и цвет сцены сохранены; "
                  "whole-character replacement preserving motion, lighting and colour"),
        "whole-character replacement preserving the figure, silhouette and motion of the source shot, and the "
        "scene's light and colour",
    ))
    шаблон_ru, шаблон_en = ASSEMBLY_SPLAT_CAPTURE
    ряды.append((re.escape(шаблон_ru).replace(re.escape("{n}"), r"(\d+)"), шаблон_en.replace("{n}", r"\1")))
    return tuple(ряды)


def made_inputs(step: str, plan_steps: Sequence[str], image_artefact: str) -> set[str]:
    """A whole-person replacement fed by the plan's own generated character reference."""
    if step == "замена_фигуры" and "генерация_изображения" in plan_steps:
        return {image_artefact}
    return set()


# --- the rewrite (called from `recipes.apply.rewrite`) -----------------------------------------------------


def rewrite(
    spec: Any,
    steps: list[str],
    notes: MutableMapping[str, str],
    counts: MutableMapping[str, int],
    step_seconds: MutableMapping[str, tuple[float, float]],
    acc: Any,
    text: str = "",
) -> list[str]:
    """Apply the round-17 routes to a route's steps; returns the new step list (notes / counts in place)."""
    steps = list(steps)
    # 1. burned-in subtitles
    if burned_subtitles(spec, text) and (spec.task in SUBTITLE_ADD_REMOVAL_TASKS or "правка_видео" in steps):
        if acc.prior("burned_subtitles", "burned_subtitles_replace"):
            if spec.task in SUBTITLE_ADD_REMOVAL_TASKS:
                steps = [*steps, "правка_видео"] if "правка_видео" not in steps else steps
            if spec.task == SHORTS_TASK and spec.duration_s:
                # Round-17 integration: only the cut's own seconds carry the old band, not the series.
                штук = max(1, int(getattr(spec, "shots", None) or 1))
                step_seconds["правка_видео"] = (float(spec.duration_s), float(spec.duration_s) / штук)
            if spec.task != "dub-translate" and _speech_heard(spec) and "расшифровка" not in steps:
                steps = ["расшифровка", *steps]
                notes["расшифровка"] = NOTE_SUBS_TRANSCRIPT[0]
            notes["правка_видео"] = NOTE_SUBS_REMOVE[0]
            acc.assembly.append(_ocr_line(spec))
            acc.assembly.append(_translation_line(spec))
            if soft_subtitles(spec):
                acc.assembly.append(ASSEMBLY_SUBS_SOFT)
            else:
                acc.assembly.append(ASSEMBLY_SUBS_BURN)
                acc.assembly.append(ASSEMBLY_SUBS_SOFT_ALT)
    # 2. singer music video
    if performer_video(spec, text) and set(steps) & PERFORMER_DROPS:
        if acc.prior("performer_music_video", "performer_reference_lips"):
            поёт, прочие = performer_split(spec)
            шот = float(_seconds(spec) or 0) / max(1, int(spec.shots or 1))
            свои_фото = "photo" in set(spec.inputs)
            новые: list[str] = []
            стиллов = (0 if свои_фото else 1) + прочие
            if стиллов:
                новые.append("генерация_изображения")
                counts["генерация_изображения"] = стиллов
                notes["генерация_изображения"] = (NOTE_PERFORMER_REF if not свои_фото else NOTE_BROLL_STILLS)[0]
            if поёт:
                новые += ["видео_по_референсу", "липсинк"]
                notes["видео_по_референсу"] = NOTE_PERFORMER_R2V[0]
                notes["липсинк"] = NOTE_PERFORMER_LIPS[0]
                counts["липсинк"] = поёт
                counts["видео_по_референсу"] = поёт
                if шот:
                    step_seconds["видео_по_референсу"] = (поёт * шот, шот)
                    step_seconds["липсинк"] = (поёт * шот, шот)
            if прочие:
                новые.append("оживление")
                notes["оживление"] = NOTE_BROLL_I2V[0]
                counts["оживление"] = прочие
                if шот:
                    step_seconds["оживление"] = (прочие * шот, шот)
            for s in PERFORMER_DROPS - set(новые):
                notes.pop(s, None)
            steps = [*новые, *(s for s in steps if s not in PERFORMER_DROPS)]
            acc.assembly.append(ASSEMBLY_PERFORMER)
    # 3. 3D reconstruction of a place
    if reconstruct_3d(spec, text) and (set(steps) & SCENE_3D_DROPS or not steps):
        if acc.prior("scene_3d", "gaussian_splat_scene"):
            from studio.recipes import apply as ra

            for s in SCENE_3D_DROPS:
                notes.pop(s, None)
            steps = [SCENE_3D_STEP, *(s for s in steps if s not in SCENE_3D_DROPS)]
            notes[SCENE_3D_STEP] = NOTE_SCENE_3D[0]
            acc.assembly[:] = [a for a in acc.assembly if a not in (ra.ASSEMBLY_WALKTHROUGH, ra.ASSEMBLY_SPLAT)]
            шаблон_ru, шаблон_en = ASSEMBLY_SPLAT_CAPTURE
            acc.assembly.append((шаблон_ru.format(n=SPLAT_PHOTOS_MIN), шаблон_en.format(n=SPLAT_PHOTOS_MIN)))
            acc.assembly.append(GAP_SPLAT_COMPUTE)
            if "video" in set(spec.outputs):
                acc.assembly.append(ASSEMBLY_SPLAT_RENDER)
            if set(_delivery(spec).get("format") or ()) & set(SPLAT_FORMATS) or "video" not in set(spec.outputs):
                acc.assembly.append(ASSEMBLY_SPLAT_VIEWER)
    # 5. whole-person replacement
    if whole_person(spec, text) and set(steps) & WHOLE_PERSON_FROM and "anonymise_bystanders" not in acc.recipes:
        if acc.prior("whole_person_replacement", "whole_person_replace"):
            steps = [s for s in steps if s not in WHOLE_PERSON_FROM]
            for s in WHOLE_PERSON_FROM:
                notes.pop(s, None)
            новые = ["замена_фигуры"]
            if "photo" not in set(spec.inputs):
                новые = ["генерация_изображения", *новые]
                counts["генерация_изображения"] = 1
                notes["генерация_изображения"] = NOTE_WHOLE_PERSON_REF[0]
            notes["замена_фигуры"] = NOTE_WHOLE_PERSON[0]
            steps = [*новые, *steps]
    # 4. consented internal drill: the watermark is assembly work, 0 usd
    if consented_drill(spec, text) and steps:
        acc.assembly.append(ASSEMBLY_SIM_WATERMARK)
    # 6. UGC product batch
    if ugc_batch(spec, text):
        стиллов = ugc_stills(spec, text)
        if стиллов and acc.prior("ugc_product_batch", "ugc_shared_references"):
            if "генерация_изображения" not in steps:
                steps = ["генерация_изображения", *steps]
            counts["генерация_изображения"] = стиллов
            notes["генерация_изображения"] = NOTE_UGC_STILLS[0]
    return list(dict.fromkeys(steps))

