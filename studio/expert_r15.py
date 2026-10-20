"""Round 15: expert decisions the hidden set found missing in steps, models and prices.

Every decision reads a structured spec field first and the brief's words only as a
fallback. The fields come from the parallel round-15 spec work (`edit.target`,
`outputs[].loop`, ...): until it is merged they are read through `spec_value` /
`checklist.output_flag`, which tolerate their absence (marker R15-SPEC).

1. OBJECT EDIT — placing / replacing a product or an object in the customer's shot
   is a video edit; a character-replacement endpoint (Wan Animate replace) is a
   candidate only when a PERSON is the target of the edit (`person_edit`).
2. TRANSCRIPTION — the plan prices ALL the material (every file x its length), and
   a plan that needs speaker labels names whether the chosen ASR diarises by record
   (price included) or a separate diarisation pass adds its cost (`diarisation_line`).
3. LONG AMBIENT — hours of ambience are one loopable segment generated once and
   repeated at assembly (`ambient_segment_s`).

DECISION CONSTANTS (mutated both ways by `scripts/mutate_round15_knowledge.py`):
`PERSON_TARGETS`, `AMBIENT_AUDIO_SEGMENT_S`, `AMBIENT_VIDEO_SEGMENT_S`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from studio import edit_intent as ei
from studio.recipes import checklist as cl

#: `edit.target` values that make a person the object of the edit (R15-SPEC).
PERSON_TARGETS: frozenset[str] = frozenset({"person", "face", "character", "body", "actor", "presenter"})
#: Tasks whose target is a person by definition.
PERSON_TASKS: frozenset[str] = frozenset({"face-replace"})

#: One loopable AUDIO segment of a long ambient piece: a few minutes, inside one music-model run
#: (`checklist.MUSIC_RUN_MAX_S`), crossfaded into itself at assembly.
AMBIENT_AUDIO_SEGMENT_S = 180
#: One loopable VIDEO segment of a long ambient piece (fireplace, rain on a window): one generator run.
AMBIENT_VIDEO_SEGMENT_S = 10


def spec_value(spec: Any, name: str) -> Any:
    """A spec attribute that may not exist yet (R15-SPEC)."""
    return getattr(spec, name, None)


def edit_target(spec: Any) -> str:
    """`spec.edit.target` (R15-SPEC: `edit_target` attribute, or a mapping in `spec.edit`)."""
    v = spec_value(spec, "edit_target")
    if v:
        return str(v).lower()
    правки = spec_value(spec, "edit")
    if isinstance(правки, dict) and правки.get("target"):
        return str(правки["target"]).lower()
    return ""


def person_edit(spec: Any, text: str = "") -> bool:
    """Is a PERSON (a face, a character) the object of the edit? Field first, then the task, then the words."""
    цель = edit_target(spec)
    if цель:
        return цель in PERSON_TARGETS
    if str(spec_value(spec, "task") or "") in PERSON_TASKS:
        return True
    return bool(ei.PERSON_EDIT.search(" ".join((str(text or ""), *map(str, spec_value(spec, "conditions") or ())))))


# --- transcription ------------------------------------------------------------------------

#: Tasks whose step runs on the customer's whole material.
TRANSCRIBE_STEP = "расшифровка"


def material_seconds(spec: Any) -> float | None:
    """All of the brought audio / video: every item's length times its count (None — no length named)."""
    всего = 0.0
    for з in spec_value(spec, "input_items") or ():
        if з.get("kind") in ("video", "audio") and з.get("duration_s"):
            всего += float(з["duration_s"]) * max(1, int(з.get("count") or 1))
    return всего or None


#: A fact row says the model labels speakers (diarisation) — read in the value, not the model name.
DIARISES = re.compile(r"diari[sz]|speaker (?:labels?|separation|identification)|who (?:is speaking|speaks)|разметк\w* говорящ", re.I)
#: A fact row says diarisation costs extra (an add-on).
DIARISATION_ADDON = re.compile(r"diari[sz]\w*[^.;]{0,40}add-?on|add-?on[^.;]{0,40}diari[sz]", re.I)


def diarises(model_key: str, facts: Iterable[Any], fold: Any) -> bool:
    """The model's own fact rows record speaker diarisation."""
    return any(fold(f.model) == model_key and DIARISES.search(f"{f.attribute} {f.value}") for f in facts)


def diarisation_line(model: str | None, facts: Sequence[Any], fold: Any, en: bool) -> str:
    """What diarisation costs on the chosen ASR, by record."""
    if not model:
        return ""
    ключ = fold(model)
    свои = [f for f in facts if fold(f.model) == ключ]
    if any(DIARISATION_ADDON.search(str(f.value)) for f in свои):
        return (
            f"speaker labels: {model} records diarisation as a paid add-on — it is added to the per-minute ASR price"
            if en
            else f"метки говорящих: у {model} записана разметка говорящих как платное дополнение — оно прибавляется к цене минуты"
        )
    if diarises(ключ, свои, fold):
        return (
            f"speaker labels: {model} diarises by record (speaker labels in the same call), so the per-minute price "
            "already covers them; keyterms (names, jargon) add their recorded premium"
            if en
            else f"метки говорящих: {model} размечает говорящих по записи (в том же вызове), цена минуты их уже "
            "включает; ключевые слова (имена, жаргон) добавляют записанную надбавку"
        )
    return (
        f"speaker labels: {model} records NO diarisation — a separate diarisation pass (pyannote speaker-diarization "
        "3.1 on your GPU, or a diarisation-capable ASR) adds its cost, which is not priced here"
        if en
        else f"метки говорящих: у {model} разметка говорящих НЕ записана — отдельный проход разметки (pyannote "
        "speaker-diarization 3.1 на своём GPU или распознавание с разметкой) добавляет свою цену, она здесь не посчитана"
    )


def needs_diarisation(spec: Any, text: str = "") -> bool:
    """Speaker labels are part of the order: two or more speakers, or the words."""
    люди = len(spec_value(spec, "people") or ())
    if max(люди, int(spec_value(spec, "characters") or 0)) >= cl.MULTI_VOICE_MIN:
        return True
    return bool(cl.W_INTERVIEW.search(text or "") or re.search(
        r"who (?:says|said|speaks|spoke)|speaker (?:labels?|names?|tags?)|diari[sz]|кто (?:что )?(?:говорит|сказал)|по (?:говорящим|спикерам)",
        text or "", re.I))


# --- long ambient --------------------------------------------------------------------------


def ambient_segment_s(spec: Any, text: str, audio: bool) -> float | None:
    """Seconds of ONE loopable segment for a long ambient deliverable; None — not one."""
    секунды = float(spec_value(spec, "duration_s") or 0)
    if секунды < cl.AMBIENT_LOOP_MIN_S:
        return None
    слова = " ".join((str(text or ""), *map(str, spec_value(spec, "conditions") or ())))
    if not (cl.output_flag(spec, "loop") or cl.W_LOOP.search(слова) or cl.W_AMBIENT.search(слова)):
        return None
    return float(AMBIENT_AUDIO_SEGMENT_S if audio else AMBIENT_VIDEO_SEGMENT_S)


#: (ru, en) lines this module adds to plans (localised through `studio/l10n.py`).
NOTE_AMBIENT_VIDEO = (
    "длинный фоновый ролик: генерируется ОДИН зацикливаемый отрезок {n} с, длину даёт повтор при сборке",
    "a long ambient video: ONE loopable segment of {n} s is generated, the length comes from repeating it at assembly",
)
NOTE_AMBIENT_AUDIO = (
    "длинный фоновый звук: генерируется ОДИН зацикливаемый отрезок {n} с, длину даёт повтор при сборке",
    "long ambient audio: ONE loopable segment of {n} s is generated, the length comes from repeating it at assembly",
)
ASSEMBLY_AMBIENT = (
    "отрезок повторяется до заказанной длины с наплывом на стыке (ffmpeg -stream_loop, acrossfade / xfade), точка петли проверяется на слух и глазами — 0 usd",
    "the segment is repeated to the ordered length with a crossfade at the join (ffmpeg -stream_loop, acrossfade / xfade), and the loop point is checked by ear and eye — 0 usd",
)

# --- anonymising bystanders -------------------------------------------------------------------

#: Identifier links that name a WHOLE-character replacement (Wan Animate replace / mix).
PERSON_REPLACE_LINKS = r"animate-replace|character-replace|animate-mix"
#: The method is a swap to a synthetic face (pseudonymisation unless the raw footage is destroyed).
SWAP_WORDS = re.compile(
    r"\bswap\w*|face[- ]?swap|replac\w* (?:the |their |all )?faces?|synthetic (?:face|people|person)|fake faces|ai faces|generated faces"
    r"|замен\w* лиц\w*|подмен\w* лиц\w*|синтетическ\w* лиц\w*|сгенерированн\w* лиц\w*|чуж\w* лиц\w*",
    re.I,
)
#: The method is a blur / pixelation / box (irreversible when strong enough).
BLUR_WORDS = re.compile(
    r"\bblur\w*|pixelat\w*|\bmosaic\b|black (?:box|bar)s?|\bmask (?:the |all )?faces|размы\w*|пиксел\w*|мозаик\w*|замаз\w*|плашк\w*",
    re.I,
)


def anonymise_method(spec: Any, text: str = "") -> str | None:
    """'swap' | 'blur' for an order to anonymise bystanders' faces; None — no such order.

    R15-SPEC: `edit.target` = 'bystander-faces' (or 'faces' with an anonymise / blur / swap word)
    decides first; the words (`checklist.W_ANONYMISE`) are the fallback.
    """
    слова = " ".join((str(text or ""), *map(str, spec_value(spec, "conditions") or ())))
    цель = edit_target(spec)
    if not (цель in {"bystander-faces", "bystanders", "passers-by"} or cl.W_ANONYMISE.search(слова)):
        return None
    if not (цель or re.search(
        r"anonymi|de-?identif|blur|pixel|hide|mask|obscure|gdpr|dsgvo|rgpd|swap|replac|анонимиз|обезлич|размы|скры|замаз|пиксел|замен|подмен",
        слова, re.I,
    )):
        return None
    if SWAP_WORDS.search(слова):
        return "swap"
    return "blur" if BLUR_WORDS.search(слова) else "swap"


NOTE_SYNTHETIC_FACE = (
    "одно СИНТЕТИЧЕСКОЕ лицо, не похожее ни на кого (без фото реальных людей), — на него меняются лица прохожих",
    "one SYNTHETIC face that resembles nobody (no photo of a real person) — the bystanders' faces are swapped to it",
)
NOTE_ANON_SWAP = (
    "лицо каждого прохожего меняется на синтетическое (замена лица в видео, не замена фигуры); исходник с "
    "настоящими лицами — персональные данные: храните зашифрованным с датой удаления",
    "every bystander's face is swapped to the synthetic one (a video face swap, not a whole-figure replacement); "
    "the raw footage with real faces is personal data: keep it encrypted with a deletion date",
)
ASSEMBLY_ANON_BLUR_ALT = (
    "необратимая альтернатива: найденные лица размываются при сборке (deface / ffmpeg boxblur по трекингу) — 0 usd",
    "the irreversible alternative: detected faces are blurred at assembly (deface / ffmpeg boxblur over tracked boxes) "
    "— 0 usd",
)
ASSEMBLY_ANON_BLUR = (
    "лица прохожих находятся в каждом кадре и размываются или закрываются плашкой (deface / ffmpeg boxblur по "
    "трекингу) — необратимая анонимизация без генеративной модели, 0 usd",
    "the bystanders' faces are detected in every frame and blurred or boxed (deface / ffmpeg boxblur over tracked "
    "boxes) — irreversible anonymisation with no generative model, 0 usd",
)


def _register_assembly() -> None:
    """The blur route is assembly work: its reason joins `brief_spec.ASSEMBLY_REASONS` under its Russian line."""
    from studio import brief_spec as bs

    bs.ASSEMBLY_REASONS.setdefault(ASSEMBLY_ANON_BLUR[0], ASSEMBLY_ANON_BLUR)
    for ru, en in (NOTE_SYNTHETIC_FACE, NOTE_ANON_SWAP):
        bs.NOTES_EN.setdefault(ru, en)


_register_assembly()

NOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ASSEMBLY_AMBIENT,
    NOTE_SYNTHETIC_FACE,
    NOTE_ANON_SWAP,
    ASSEMBLY_ANON_BLUR_ALT,
    ASSEMBLY_ANON_BLUR,
)
#: Templated lines ({n} — seconds of the segment).
NOTE_TEMPLATES: tuple[tuple[str, str], ...] = (NOTE_AMBIENT_VIDEO, NOTE_AMBIENT_AUDIO)


#: Steps whose required still can be MADE by an earlier image-generation step of the same plan
#: (the synthetic face of an anonymisation swap).
IMAGE_FED_STEPS: frozenset[str] = frozenset({"замена_персонажа"})


def made_inputs(step: str, plan_steps: Sequence[str], image_artefact: str) -> set[str]:
    """Artefacts an earlier step of the plan makes for `step` (a generated image for a face swap)."""
    if step in IMAGE_FED_STEPS and "генерация_изображения" in plan_steps:
        return {image_artefact}
    return set()
