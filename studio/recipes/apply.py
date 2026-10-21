"""How the planner consumes the recipe table (`studio/recipes/table.py`).

Three entry points, one per place the planner decides:

* `rewrite(spec, route)` — BEFORE selection: the route built from the spec is
  rewritten by the job class (voice sample -> clone, own video -> lip sync on it,
  logo image -> end card, one host -> one reference, visualiser -> short loops,
  archive -> no deblur), and the free tools of the class go to assembly.
* `frame_prior` / `fps_prior` — AFTER selection, where the base is SILENT about
  the chosen model's frame or frame rate: the class prior fills the silence
  (upscale / interpolation step) instead of a note «not added on silence». A
  recorded fact about the model is decided by the planner before these are asked
  and always wins.
* `order(names)` — order of operations: voice clone first; restore -> colourise
  -> upscale -> interpolate.

Every applied prior is returned by id so the plan states it (with its tag and
sources) as an assumption; `spec.priors = {"<id>": false}` switches it off, and
the plan then lists it as overridden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Callable, Mapping, Sequence

from studio import brief_spec as bs
from studio import spec_first as sf
from studio import expert_r16 as x16
from studio.recipes import checklist, delivery
from studio.recipes.table import (
    ASPECT_TOLERANCE,
    FAILURES,
    LONG_FORM_S,
    NATIVE_ASPECTS,
    NOTES,
    Note,
    PRIORS,
    RECIPES,
    SINGLE_HOST_REFERENCES,
    TAG_RU,
    T2I_NATIVE_MAX_MP,
    T2V_NATIVE_FPS_MAX,
    T2V_NATIVE_MAX_MP,
    TOOLS,
    VISUALISER_LOOP_CLIP_S,
    VISUALISER_LOOP_CLIPS,
    LOOP_CLIP_S,
    Prior,
)

#: Planner operations that MAKE a still / a clip (not a pass over a brought one).
IMAGE_GENERATORS: frozenset[str] = frozenset({"генерация_изображения", "редактирование_изображения"})
VIDEO_GENERATORS: frozenset[str] = frozenset({"генерация_видео", "оживление", "видео_по_референсу", "говорящий_аватар"})
#: Steps that consume speech.
SPEECH_CONSUMERS: frozenset[str] = frozenset({"говорящий_аватар", "липсинк"})
#: Order of operations over footage (rank; lower first). Upscale of a still ranks with video upscale.
CHAIN_RANK: dict[str, float] = {
    "реставрация": 1,
    "реставрация_изображения": 1,
    # Round 18 (`studio/routes_r18.py`): faces after the restore, before the upscale.
    "восстановление_лиц": 1.5,
    "раскраска": 2,
    "раскраска_изображения": 2,
    "апскейл": 3,
    "апскейл_изображения": 3,
    "интерполяция_кадров": 4,
}
#: Steps placed before everything: they need only the customer's sample.
FIRST_STEPS: tuple[str, ...] = ("клонирование_голоса",)
#: A logo / wordmark named in `spec.conditions`.
LOGO = re.compile(r"\blogo|wordmark|brand[ -]?mark|логотип", re.I)
#: Tasks where a logo condition means «the brand mark is composited»: the piece is made here.
LOGO_TASKS: frozenset[str | None] = frozenset({None, "generate", "animate"})
#: A music video of distinct scenes named in `spec.conditions`: not a loop visualiser.
SCENES = re.compile(r"scene|story|narrative|music video|сцен|сюжет|клип", re.I)
#: Blur named by the caller: then a deblur model IS the tool.
BLUR = re.compile(r"blur|расфокус|размыт|смаз", re.I)
#: Restoration models ranked last on archive film unless blur is named.
DEBLUR_MODELS = r"deblur|sharpen"
#: The planner's name of the video artefact (`planner.ARTEFACT_VIDEO`).
ARTEFACT_VIDEO = "видео"
#: A transparent background asked for — in `spec.conditions` or, as a delivery
#: format, in the brief's own words (the format is not a spec field: «transparent
#: background for our website» is what the customer says, and a caller filling
#: the spec has nowhere else to put it).
ALPHA = re.compile(
    # Round 14: "transparent" about the OBJECT (a glass bottle) or the DISPLAY (a transparent LED / OLED
    # screen, where black is see-through) is not a transparent background.
    r"transparen(?:t|cy)(?!\s+(?:led|oled|lcd|screens?|displays?|film|glass\w*|bottles?|jars?|plastic|liquid|objects?"
    r"|products?|packag\w*|vases?|cups?|perfume|flacons?|crystal|acrylic|resin|water|ice|window|case|lid|cap))"
    r"|\balpha[- ]?channel|\bwith alpha\b|\bwebm\b|prores ?4444"
    r"|прозрачн(?!\w*\s+(?:led|oled|lcd|экран|дисплей|панел|плёнк|пленк|стекл|флакон|бутылк|банк|упаковк|пластик|жидкост"
    r"|вод|лёд|лед|акрил|смол|витрин|корпус|крышк))|альфа-?канал",
    re.I,
)
#: Explicit alpha (a channel, a format that carries one) — stands even on a hologram display.
ALPHA_EXPLICIT = re.compile(r"\balpha[- ]?channel|\bwith alpha\b|prores ?4444|альфа-?канал", re.I)
#: A 3D deliverable named — in `spec.conditions` or, as a delivery format, in the brief's words.
MESH = re.compile(r"\bglb\b|\bgltf\b|\busdz\b|\b3d[- ]?(?:model|mesh|asset)|\bmesh\b|3d-модел|3d модел|\bсетк", re.I)
#: The customer asks to animate the brought art itself (a visualiser, not an audiogram).
ANIMATE_ART = re.compile(r"animat|motion|move|оживи|оживл|анимир|движени", re.I)
#: Exact text named in `spec.conditions` (besides a logo): a wordmark, a headline, lettering.
TEXT_EXACT = re.compile(r"\btext\b|lettering|typograph|headline|wordmark|надпис|текст", re.I)
#: Round 10: a NON-HUMAN character stands in the replacement — a mascot, a costumed
#: character, a cartoon or an animal. Read in `spec.people[].name` of a person with
#: `real: false`, in `spec.conditions`, and in the brief's words.
CHARACTER = re.compile(
    r"mascot|costume|\b\w+ suit\b|plush|cartoon|animated character|anime character|creature|robot|\bfox\b|\bbear\b"
    r"|bunny|rabbit|penguin|маскот|талисман|ростов\w*|костюм\w*|мульт\w*|кукл\w*|зверь|медвед\w*|лис[аы]?\b|заяц|кролик",
    re.I,
)
#: Words that keep it a FACE swap even when the line above fires ("business suit" is a person's clothes).
FACE_ONLY = re.compile(r"\bface\b|лицо|лица\b|business suit|деловой костюм", re.I)
#: Round 10: a garment put on a person — a virtual try-on.
TRY_ON = re.compile(
    r"try-?on|virtual fitting|\bworn by\b|\bwearing\b|\bwears?\b|\bdressed in\b|\bon (?:a|an|the|our) (?:generated |ai |virtual )?"
    r"(?:fashion )?model\b|примерк\w*|надет\w*|наден\w*|надень\w*|на (?:сгенерированн\w+ |виртуальн\w+ )?модел\w*",
    re.I,
)
#: A garment named — what the try-on puts on.
GARMENT = re.compile(
    r"dress|shirt|t-?shirt|tee\b|jacket|coat|hoodie|sweater|jeans|trousers|pants|skirt|blouse|suit|garment|apparel"
    r"|clothing|outfit|sneakers|shoes|плать\w*|рубаш\w*|футболк\w*|куртк\w*|пальто|худи|свитер\w*|джинс\w*|брюк\w*"
    r"|юбк\w*|блуз\w*|одежд\w*|обув\w*|кроссовк\w*|пиджак\w*",
    re.I,
)


#: Round 12: a walkthrough / tour of a property made from its photos (a camera moves
#: through still rooms — not a person copying a driving video's motion).
WALKTHROUGH = re.compile(
    r"walk-?through|walk through|virtual tour|(?:house|home|property|apartment|room) tour|room[- ]by[- ]room"
    r"|fly-?through|real[- ]estate|\blisting\b|видеотур\w*|виртуальн\w* тур\w*|тур по (?:дому|квартир\w*|дом\w*|комнат\w*)"
    r"|обход\w* (?:дома|квартир\w*)|прогулк\w* по (?:дому|квартир\w*)|по комнатам|недвижимост\w*",
    re.I,
)
#: Round 12: so many photos of one place that a 3D reconstruction (gaussian splat)
#: is a real alternative to per-photo camera moves. DECISION CONSTANT (T1): a
#: splat needs dozens of overlapping views; at 20 a listing set usually has them.
SPLAT_PHOTOS_MIN = 20
#: Motion-control endpoints: they need a DRIVING video of a performer; a walkthrough has none.
MOTION_CONTROL_MODELS = r"motion-control|motion-transfer|animate-move|act-two"
#: TTS builds published without the cloning head: they do not read in a sample's voice.
NO_CLONE_MODELS = r"without-voice-clon|no-voice-clon"
#: Round 12: drawn (2D / anime / cartoon) footage — photoreal lip sync is the wrong tool for it.
DRAWN = re.compile(
    r"\banime\b|\bcartoons?\b|\bcartoony\b|\banimated (?:series|show|film|movie|episode|short)|\bmanga\b"
    r"|\b2d[- ]animat\w*|\bhand[- ]drawn|аниме|мультфильм\w*|мультсериал\w*|мультик\w*|рисованн\w*|анимационн\w*",
    re.I,
)
#: Round 12: everything must run on the customer's machine (no hosted API).
LOCAL_ONLY = re.compile(
    r"local[- ]only|\blocally\b|\boffline\b|on[- ]prem\w*|air[- ]?gapped|no cloud|without (?:the |any )?cloud"
    r"|own (?:gpu|machine|server|hardware)|локально|офлайн|оффлайн|без облак\w*|без интернет\w*"
    r"|на (?:своём|своем|моём|моем) (?:компьютере|сервере|железе|gpu|видеокарте)",
    re.I,
)


#: Round 13: a seamless loop asked for (one clip that repeats) — a shared asset of every version.
LOOP = re.compile(
    r"\bloop(?:s|ed|ing|able)?\b|seamless(?:ly)? repeat\w*|cinemagraph\w*|зацикл\w*|\bлуп\w*|бесшовн\w* (?:петл|повтор)\w*"
    r"|\bпетл[яеюи]\w*",
    re.I,
)
#: The loop's own length named next to it: «a 6-second loop», «loop of 5 s», «петля на 5 секунд».
LOOP_LENGTH = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*-?\s*(?:s|sec|secs|seconds?|сек\w*|с)\b(?:[\s-]+[\w-]+){0,3}?[\s-]+(?:loop|зацикл|петл|луп|цикл)"
    r"|(?:loop\w*|петл\w*|луп\w*|цикл\w*|зацикл\w*)(?:\s+[\w-]+){0,4}?\s+(?:of|на|в|длиной)\s*(\d+(?:[.,]\d+)?)\s*-?\s*"
    r"(?:s|sec|secs|seconds?|сек\w*|с)\b",
    re.I,
)
#: Loop steps: generators of a clip (a talking avatar is not a loop).
LOOP_MAKERS: tuple[str, ...] = ("генерация_видео", "оживление", "видео_по_референсу")


#: Round 15: steps a long ambient piece is made with (one loopable segment each).
AMBIENT_AUDIO_MAKERS: tuple[str, ...] = ("музыка", "звук_фон")
AMBIENT_MAKERS: tuple[str, ...] = (*AMBIENT_AUDIO_MAKERS, "генерация_видео", "оживление", "видео_со_звуком")
#: Round 15: the route steps an anonymisation order lands on before the recipe (edit / character swap).
ANONYMISE_ROUTES: frozenset[str] = frozenset({"правка_видео", "замена_персонажа", "замена_фигуры"})
#: Round-16 integration: the route step kept when the edit names a target other than the person.
ANONYMISE_KEEPS_EDIT: frozenset[str] = frozenset({"правка_видео"})


def loop_seconds(spec: "bs.Spec", text: str = "") -> float | None:
    """A loop is asked for: its own length (named, or `LOOP_CLIP_S`); None — no loop.

    Round 15 — SPEC FIRST: `spec.outputs[].loop` decides whether a loop is asked for (any brief
    language); the loop words are read only when it is absent.
    """
    said = [str(у) for у in (*spec.conditions, text) if у]
    петля = getattr(spec, "loop", None)
    if петля is False:
        return None
    if петля is None and not any(LOOP.search(у) for у in said):
        return None
    for у in said:
        m = LOOP_LENGTH.search(у)
        if m:
            return float((m.group(1) or m.group(2)).replace(",", "."))
    return float(LOOP_CLIP_S)


#: Round 13: sound asked to follow the brought picture (a soundtrack synced to the action).
FOLLOWS_PICTURE = re.compile(
    r"\bsync\w*|follow\w* (?:the |its |their )?(?:action|picture|motion|movement|cuts?|edit|footage|video|clip)"
    r"|(?:match|fit|react)\w* (?:to )?(?:the |its )?(?:action|picture|motion|movement|cuts?|footage|video|clip)"
    r"|to (?:the |its )?(?:action|picture|motion|movement|cuts)\b|on[- ]screen action|video[- ]to[- ](?:audio|music)"
    r"|синхрон\w*|в такт (?:с )?(?:картинк|действи|движени|монтаж)\w*|под (?:действие|картинку|движени\w*|монтаж)"
    r"|по картинке|следу\w* за (?:действием|картинкой|движением)",
    re.I,
)


def follows_picture(spec: "bs.Spec", text: str = "") -> bool:
    """The ordered sound must follow the brought picture: `spec.follows_picture` (round 16), else the sync words."""
    поле = sf.flag(spec, "follows_picture")
    if поле is not None:
        return поле
    return any(FOLLOWS_PICTURE.search(str(у)) for у in (*spec.conditions, text) if у)


def walkthrough(spec: "bs.Spec", text: str = "") -> bool:
    """A camera tour of a place from the customer's photos (round 12)."""
    if "video" not in spec.outputs or "photo" not in spec.inputs or _photo_count(spec) < 2:
        return False
    # Round 16: `spec.subject` (interior) or `spec.domain` (real-estate) named decides, any brief language.
    поле = sf.subject(spec, "interior")
    if поле is None:
        поле = sf.domain(spec, "real-estate")
    if поле is not None:
        return поле and not any(п.get("real") for п in spec.people)
    if any(п.get("real") for п in spec.people):
        return False
    return any(WALKTHROUGH.search(str(у)) for у in (*spec.conditions, text) if у)


def drawn(spec: "bs.Spec", text: str = "") -> bool:
    """The footage is drawn (anime, cartoon): mouths are drawn shapes, not a photographed face.

    Round 16: `spec.style` named decides (stylised / limited-animation = drawn; photoreal = not)."""
    поле = sf.style(spec, *sf.STYLISED_STYLES)
    if поле is not None:
        return поле
    return any(DRAWN.search(str(у)) for у in (*spec.conditions, text) if у)


def local_only(spec: "bs.Spec", text: str = "") -> bool:
    """Everything runs on the customer's own machine: `spec.self_host`, `open_weights`, or said in words."""
    if spec.open_weights:
        return True
    # Round 16: `self_host: false` ({"enabled": False}) is a NAMED no — the words do not overrule it.
    if spec.self_host:
        return spec.self_host.get("enabled", True) is not False
    return any(LOCAL_ONLY.search(str(у)) for у in (*spec.conditions, text) if у)


def whole_character(spec: "bs.Spec", text: str = "") -> bool:
    """A face-replace order whose replacement is a non-human character (mascot, costume): the whole figure goes.

    `spec.people` first: a person with `real: false` named as a character. Then
    `spec.conditions` and the brief's words — the brief is read only for this
    role, which the spec has no field for. A face named ("put my face on the
    mascot") keeps it a face swap.
    """
    named = [str(п.get("name") or "") for п in spec.people if п.get("real") is False]
    if any(CHARACTER.search(n) for n in named):
        return True
    # Round 16: `spec.subject` named — a mascot in it is a whole-character swap, otherwise a face swap.
    поле = sf.subject(spec, "mascot")
    if поле is not None:
        return поле
    said = [str(у) for у in (*spec.conditions, text) if у]
    return any(CHARACTER.search(у) for у in said) and not any(FACE_ONLY.search(у) for у in said)


def wants_try_on(spec: "bs.Spec", text: str = "") -> bool:
    """A garment from the customer's photo put on a model: an image edit order that names a garment and wearing it.

    Round 16: `spec.subject` named decides — a garment in it is a try-on."""
    поле = sf.subject(spec, "garment")
    if поле is not None:
        return поле
    said = [str(у) for у in (*spec.conditions, text) if у]
    return any(TRY_ON.search(у) for у in said) and any(GARMENT.search(у) for у in said)


# --- round 16: the recipe words read their spec field first -------------------------------


def logo_named(spec: "bs.Spec") -> bool:
    """A logo / wordmark is part of the piece: `spec.subject` (logo) when named, else `spec.conditions` words."""
    поле = sf.subject(spec, "logo")
    if поле is not None:
        return поле
    return any(LOGO.search(у) for у in spec.conditions)


def exact_text_named(spec: "bs.Spec") -> bool:
    """Exact lettering or a logo must be legible: `spec.subject` (logo / text) when named, else the words."""
    поле = sf.subject(spec, "logo", "text")
    if поле is not None:
        return поле
    return any(LOGO.search(у) or TEXT_EXACT.search(у) for у in spec.conditions)


def blur_named(spec: "bs.Spec") -> bool:
    """The material is BLURRED (then a deblur model is the tool): `spec.inputs[].defects` when named, else words."""
    поле = sf.blurred(spec)
    if поле is not None:
        return поле
    return any(BLUR.search(у) for у in (*spec.conditions, *spec.edit))


def scenes_named(spec: "bs.Spec") -> bool:
    """A visualiser made of distinct SCENES (a music video), not loops: `outputs[].loop: false` when named."""
    петля = getattr(spec, "loop", None)
    if петля is not None:
        return петля is False
    return any(SCENES.search(у) for у in spec.conditions)


def art_moves(spec: "bs.Spec") -> bool:
    """The brought art itself is animated (not a static audiogram): `spec.animate_input` when named, then
    `outputs[].loop` named (animated loops or scenes are both motion), else the words of `spec.conditions`."""
    поле = sf.flag(spec, "animate_input")
    if поле is not None:
        return поле
    if getattr(spec, "loop", None) is not None:
        return True
    return any(ANIMATE_ART.search(у) or SCENES.search(у) for у in spec.conditions)


#: Edits of the customer's footage that are a mask and a composite (`spec.edit`).
MASK_EDITS: frozenset[str] = frozenset({"remove-object", "replace-object", "replace-sky"})
#: Speech-driven video steps: a long one is made in segments.
SPEECH_VIDEO_STEPS: frozenset[str] = frozenset({"говорящий_аватар", "липсинк"})
#: Steps that move lips on footage with several faces.
LIP_STEPS: frozenset[str] = frozenset({"липсинк"})
#: Steps whose output is speech in a language (a regional variety matters there).
SPEECH_STEPS: frozenset[str] = frozenset(
    {"озвучка", "дубляж", "клонирование_голоса", "говорящий_аватар", "видео_со_звуком"}
)
#: Steps that make a generated frame (an aspect outside the native set is a crop).
FRAME_MAKERS: frozenset[str] = IMAGE_GENERATORS | VIDEO_GENERATORS | {"оборот_360"}
#: Tasks whose deliverable carries captions burned in at assembly.
CAPTION_TASKS: frozenset[str | None] = frozenset({"cut-to-shorts", "captions"})

NOTE_CLONE = (
    "голос — клон по ВАШЕЙ записи: текст читается этим голосом",
    "the voice is cloned from YOUR recording: the text is read in that voice",
)
NOTE_OWN_LIPSYNC = (
    "губы двигаются на ВАШЕМ видео человека под новую речь — нового лица не генерируется",
    "the lips move on YOUR video of the person to the new speech — no new face is generated",
)
NOTE_ENDCARD_FOOTAGE = (
    "рекламные кадры без текста; ваш снимок — логотип, он ложится финальной карточкой при сборке",
    "ad footage without text; your image is the logo and goes on as the end card at assembly",
)
NOTE_LOOPS = (
    f"{VISUALISER_LOOP_CLIPS} зацикливаемых клипа по {VISUALISER_LOOP_CLIP_S} с; длину трека даёт сборка",
    f"{VISUALISER_LOOP_CLIPS} loopable clips of {VISUALISER_LOOP_CLIP_S} s; assembly reaches the track's length",
)
NOTE_V2A = (
    "видео -> звук: модель смотрит ВАШ ролик (MMAudio, HunyuanVideo-Foley)",
    "video-to-audio: the model watches YOUR footage (MMAudio, HunyuanVideo-Foley)",
)
NOTE_LOOP_ONCE = (
    "одна бесшовная петля на {s} с — ОБЩАЯ для всех версий и длин: генерируется один раз",
    "one seamless loop of {s} s — SHARED by every version and length: generated once",
)
NOTE_ONE_REFERENCE = (
    f"{SINGLE_HOST_REFERENCES} референс ведущего на все ролики",
    f"{SINGLE_HOST_REFERENCES} reference of the host for every short",
)
NOTE_MATTE = (
    "фон снимается в каждом кадре в альфа-канал (видео-маттинг) — на выходе прозрачность",
    "the background is removed per frame to an alpha channel (video matting) — the output is transparent",
)
NOTE_LYRICS = (
    "вокал ВАШЕГО трека расшифровывается с метками слов — по ним выравнивается текст песни",
    "the vocals of YOUR track are transcribed with word timestamps — the lyrics are aligned to them",
)
NOTE_AUDIOGRAM_CAPTIONS = (
    "расшифровка ВАШЕЙ записи с таймингами — для субтитров аудиограммы",
    "timed transcript of YOUR recording — for the audiogram's captions",
)
NOTE_WHOLE_CHARACTER = (
    "персонаж заменяется ЦЕЛИКОМ (фигура, силуэт, движение) по референсу маскота — это не замена лица",
    "the whole character is replaced (figure, silhouette, motion) from the mascot reference — not a face swap",
)
NOTE_TRY_ON = (
    "виртуальная примерка: снимок модели + снимок вещи -> вещь на модели (крой, принт и логотип сверяются с фото товара)",
    "virtual try-on: model photo + garment photo -> the garment on the model (check cut, print and logo against "
    "the product photo)",
)
NOTE_TRY_ON_MODEL = (
    "снимок модели (человека нет на ваших фото): поза в полный рост, простой фон, одежда близкого кроя",
    "the model photo (no person on your photos): full-length pose, plain background, clothing of a similar cut",
)

NOTE_WALKTHROUGH = (
    "проход камеры по ВАШИМ снимкам: каждая комната — свой короткий клип (наезд, проезд, панорама) из снимка, "
    "людей и мебели не выдумывать, прямые линии держать",
    "a camera path through YOUR photos: each room is its own short clip (push-in, dolly, pan) from the photo — no "
    "invented people or furniture, straight lines kept",
)
NOTE_DRAWN_DUB = (
    "рисованный ролик: губы двигает липсинк, но модель берётся та, у которой записана поддержка рисованных / "
    "стилизованных лиц (2D-персонажи); сначала проверьте 5 с — детектор лица может не найти нарисованный рот, "
    "линии контура рвутся; запасной путь — рты переставляются в проекте анимации по фонемам новой речи (Rhubarb "
    "Lip Sync, автолипсинк Toon Boom / Character Animator)",
    "drawn footage: lip sync moves the mouths, on a model that records support for drawn / stylised faces (2D "
    "characters); test 5 s first — the face detector may miss a drawn mouth and line art can break; the fallback "
    "is re-timing the mouth flaps in the animation project from the new speech's phonemes (Rhubarb Lip Sync, Toon "
    "Boom / Character Animator auto lip-sync)",
)
#: Round 15: drawn ANIMAL characters — no lip-sync model records them (Kling's guide: human 2D/3D only).
NOTE_DRAWN_ANIMAL = (
    "персонажи — животные: ни у одной модели липсинка не записана поддержка морд животных (руководство Kling: "
    "только человеческие персонажи, реальные / 3D / 2D) — проверьте 5 с до всего эпизода, иначе рты "
    "переставляются в проекте анимации",
    "the characters are animals: no lip-sync model records support for animal faces (Kling's guide: human "
    "characters only, real / 3D / 2D) — test 5 s before the whole episode, otherwise the mouth flaps are re-timed "
    "in the animation project",
)
NOTE_DRAWN_DUB_ANIMAL = (NOTE_DRAWN_DUB[0] + "; " + NOTE_DRAWN_ANIMAL[0], NOTE_DRAWN_DUB[1] + "; " + NOTE_DRAWN_ANIMAL[1])
#: Round 15: route / assembly lines that the server localises through `studio/l10n.py` (EN table).
R15_NOTE_PAIRS: tuple[tuple[str, str], ...] = (NOTE_DRAWN_DUB, NOTE_DRAWN_DUB_ANIMAL)
#: Round 15: animal characters named in the brief (drawn dub: no recorded lip-sync model for them).
ANIMAL_CHARACTERS = re.compile(
    r"\b(?:animal|fox|dog|puppy|cat|kitten|bear|rabbit|bunny|mouse|duck|pig|lion|wolf|bird|owl|frog|horse|cow|monkey|dragon|dinosaur)s?\b"
    r"|животн\w*|лис\w*|собак\w*|щен\w*|кош\w*|кот\b|котён\w*|медвед\w*|зай\w*|кролик\w*|мыш\w*|утк\w*|свин\w*|лев\b|льв\w*"
    r"|волк\w*|птиц\w*|сов\w*|лягуш\w*|лошад\w*|коров\w*|обезьян\w*|дракон\w*|динозавр\w*",
    re.I,
)

NOTE_LOCAL_TRANSCRIBE = (
    "речь ВАШЕГО видео расшифровывается с таймингами на вашем GPU (Whisper / faster-whisper)",
    "the speech of YOUR video is transcribed with timestamps on your GPU (Whisper / faster-whisper)",
)
NOTE_LOCAL_VOICE = (
    "расшифровка переводится локальной моделью (NLLB-200 / MADLAD-400 / локальная LLM) и читается голосом "
    "исходного диктора (клон без обучения: XTTS-v2 / CosyVoice / Chatterbox) по отрезкам таймингов",
    "the transcript is translated by a local model (NLLB-200 / MADLAD-400 / a local LLM) and read in the original "
    "speaker's voice (zero-shot clone: XTTS-v2 / CosyVoice / Chatterbox), segment by segment on the timestamps",
)

ASSEMBLY_WALKTHROUGH = (
    "клипы комнат склеиваются в порядке прохода (ffmpeg concat / xfade) — 0 usd",
    "the room clips are joined in walking order (ffmpeg concat / xfade) — 0 usd",
)
ASSEMBLY_SPLAT = (
    "снимков много: вместо клипов по снимкам возможен настоящий облёт — 3D gaussian splat по снимкам "
    "(nerfstudio splatfacto / Postshot на своём GPU) и рендер пути камеры; нужны снимки с перекрытием",
    "many photos: instead of per-photo clips a true fly-through is possible — a 3D gaussian splat from the "
    "photos (nerfstudio splatfacto / Postshot on your GPU) and a rendered camera path; the photos must overlap",
)
ASSEMBLY_DRAWN_DUB = (
    "новая дорожка заменяет речь ВАШЕГО ролика (ffmpeg), губы подгоняет шаг липсинка — 0 usd за сборку",
    "the new track replaces the speech of YOUR video (ffmpeg) and the lip-sync step fits the mouths — 0 usd "
    "for the assembly",
)
R15_NOTE_PAIRS = R15_NOTE_PAIRS + (ASSEMBLY_DRAWN_DUB,)
#: Round 16: the base plan of a drawn dub — the new track over the untouched picture, no lip sync.
ASSEMBLY_DRAWN_ADAPT = (
    "новая дорожка, адаптированная под существующие рты, заменяет речь ВАШЕГО ролика (ffmpeg); картинка не "
    "перерисовывается — 0 usd за сборку",
    "the new track, adapted to the existing mouth flaps, replaces the speech of YOUR video (ffmpeg); the picture "
    "is not redrawn — 0 usd for the assembly",
)
R16_NOTE_PAIRS: tuple[tuple[str, str], ...] = (ASSEMBLY_DRAWN_ADAPT,)
#: Assembly lines that describe a dubbed track over the customer's picture (dropped on the voice route).
DUB_ONLY_ASSEMBLY: tuple[tuple[str, str], ...] = (ASSEMBLY_DRAWN_ADAPT, ASSEMBLY_DRAWN_DUB)
ASSEMBLY_LOCAL_DUB = (
    "голос отделяется от музыки и шумов (Demucs), новая речь сводится поверх них и кладётся в ВАШЕ видео "
    "(ffmpeg) — всё на вашем GPU, 0 usd",
    "the voice is separated from music and effects (Demucs), the new speech is mixed over them and muxed into "
    "YOUR video (ffmpeg) — all on your GPU, 0 usd",
)

ASSEMBLY_LOOP_VERSIONS = (
    "петля повторяется до каждой заказанной длины и версии (ffmpeg -stream_loop, обрезка по длине) — 0 usd",
    "the loop is repeated to every ordered length and version (ffmpeg -stream_loop, cut to length) — 0 usd",
)
ASSEMBLY_LOGO = (
    "логотип накладывается из ВАШЕГО файла (ffmpeg overlay) финальной карточкой — буква в букву; "
    "сгенерированный текст в кадр не идёт — 0 usd",
    "the logo is composited from YOUR file (ffmpeg overlay) as the end card — letter for letter; no "
    "generated lettering is used — 0 usd",
)
ASSEMBLY_LOGO_STING = (
    "финальная пауза: сгенерированное движение перетекает (ffmpeg xfade) в настоящий логотип из ВАШЕГО файла — 0 usd",
    "final hold: the generated motion crossfades (ffmpeg xfade) into the true logo from YOUR file — 0 usd",
)
ASSEMBLY_FOLEY = (
    "шумы сводятся под исходный звук (ffmpeg amix), громкость — ffmpeg loudnorm — 0 usd",
    "the foley is mixed under the original sound (ffmpeg amix), loudness by ffmpeg loudnorm — 0 usd",
)
ASSEMBLY_LOOPS = (
    f"{VISUALISER_LOOP_CLIPS} клипа по {VISUALISER_LOOP_CLIP_S} с зацикливаются и режутся по долям трека "
    "(ffmpeg concat) на всю его длину — 0 usd",
    f"the {VISUALISER_LOOP_CLIPS} clips of {VISUALISER_LOOP_CLIP_S} s are looped and cut on the track's beats "
    "(ffmpeg concat) to its full length — 0 usd",
)
ASSEMBLY_FILM = (
    "до модели, на исходнике: мерцание — ffmpeg deflicker, пыль и царапины — VapourSynth DeScratch / "
    "RemoveDirt — 0 usd",
    "before the model, on the source: flicker — ffmpeg deflicker, dust and scratches — VapourSynth DeScratch / "
    "RemoveDirt — 0 usd",
)
ASSEMBLY_EXTRACT = (
    "образец голоса вынимается из ВАШЕГО видео (ffmpeg -vn) — 0 usd",
    "the voice sample is taken out of YOUR video (ffmpeg -vn) — 0 usd",
)
ASSEMBLY_ALPHA = (
    "ролик с альфа-каналом кодируется в WebM (VP9 с альфой) для сайта или ProRes 4444 для монтажа — 0 usd",
    "the matted clip is encoded with alpha: WebM (VP9 alpha) for the web or ProRes 4444 for editing — 0 usd",
)
ASSEMBLY_LYRICS = (
    "строки текста ставятся по меткам слов и анимируются типографикой (ffmpeg / After Effects) — 0 usd",
    "the lyric lines are placed on the word timestamps and animated as typography (ffmpeg / After Effects) — 0 usd",
)
ASSEMBLY_MESH_RENDER = (
    "ролик-оборот рендерится из 3D-модели (Blender) — 0 usd",
    "the turntable clip is rendered from the 3D model (Blender) — 0 usd",
)
ASSEMBLY_AUDIOGRAM = (
    "волна звука (ffmpeg showwaves) и субтитры ложатся поверх ВАШЕЙ обложки — 0 usd",
    "the waveform (ffmpeg showwaves) and the captions are laid over YOUR cover art — 0 usd",
)


@dataclass(frozen=True)
class Applied:
    """What the recipes did to one plan."""

    route: "bs.Маршрут"
    recipes: tuple[str, ...] = ()
    priors: tuple[str, ...] = ()
    overridden: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    #: op -> (seconds priced, seconds of one run).
    step_seconds: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    #: op -> artefact a candidate should take as input (ranked first).
    prefer_input: Mapping[str, str] = field(default_factory=dict)
    #: op -> regex of model names ranked last.
    avoid: Mapping[str, str] = field(default_factory=dict)
    #: Round 15: ops whose candidates that RECORD drawn / stylised face support rank first (a cartoon dub).
    prefer_stylised: tuple[str, ...] = ()
    #: Round 16: steps that are an OPTIONAL upgrade (drawn dub lip sync): kept in the plan, priced apart.
    optional: tuple[str, ...] = ()
    #: (ru, en) assembly reasons — free tools, 0 usd.
    assembly: tuple[tuple[str, str], ...] = ()
    #: 0 budget: the plan offers the open-weights route.
    free_route: bool = False
    #: Round 10: a printed still — ((w, h) at print DPI, size label, dpi); None — not print or no size.
    print_frame: tuple[tuple[int, int], str, int] | None = None
    #: Round 12: the route was rebuilt for the customer's own machine (a local chain):
    #: selection goes to open weights on their GPU even when `spec.self_host` is silent.
    local_only: bool = False
    #: Round 13: steps whose output is a SHARED ASSET (made once, reused by every
    #: version / shot): the plan states the reuse.
    shared: tuple[str, ...] = ()


def enabled(spec: "bs.Spec", prior_id: str) -> bool:
    """A prior is on unless `spec.priors[id]` is false."""
    return (spec.priors or {}).get(prior_id, True) is not False


class _Acc:
    """Accumulator: recipes and priors in the order met, without repeats."""

    def __init__(self, spec: "bs.Spec") -> None:
        self.spec = spec
        self.recipes: list[str] = []
        self.priors: list[str] = []
        self.overridden: list[str] = []
        self.assembly: list[tuple[str, str]] = []
        self.tools: list[str] = []

    def prior(self, recipe: str, prior_id: str) -> bool:
        """Matched: True when the prior is on (and records it), False when switched off."""
        if recipe not in self.recipes:
            self.recipes.append(recipe)
        if not enabled(self.spec, prior_id):
            if prior_id not in self.overridden:
                self.overridden.append(prior_id)
            return False
        if prior_id not in self.priors:
            self.priors.append(prior_id)
        return True


def _replace_step(steps: list[str], old: str, new: str) -> list[str]:
    return list(dict.fromkeys(new if s == old else s for s in steps))


def wants_alpha(spec: "bs.Spec", text: str = "") -> bool:
    """A transparent background asked for: `spec.conditions`, or the brief's own words.

    Round 14: a hologram / Pepper's-ghost / transparent LED display wants the subject on BLACK (black is
    its transparent colour, `checklist.hologram_black_background`) — no alpha unless one is named outright.
    """
    from studio.recipes import checklist

    # ПЯТНАДЦАТЫЙ КРУГ: `spec.outputs[].alpha` названо — оно и решает, на любом языке брифа.
    альфа = getattr(spec, "alpha", None)
    if альфа is not None:
        return альфа
    слова = (*(str(у) for у in spec.conditions), str(text or ""))
    if any(checklist.W_HOLOGRAM.search(у) for у in слова) and not any(ALPHA_EXPLICIT.search(у) for у in слова):
        return False
    return any(ALPHA.search(у) for у in слова)


def wants_mesh(spec: "bs.Spec", text: str = "") -> bool:
    """A 3D model asked for: `spec.delivery.format` (glb / usdz / …, round 16), else `spec.conditions` or the words."""
    поле = sf.mesh_format(spec)
    if поле is not None:
        return поле
    return any(MESH.search(str(у)) for у in (*spec.conditions, text))


def rewrite(spec: "bs.Spec", route: "bs.Маршрут", text: str = "") -> Applied:
    """Recipes of the job classes this spec belongs to, applied to its route.

    :param text: the brief's words — read ONLY for a delivery format the spec has
        no field for (a transparent background); every other decision is spec's.
    """
    acc = _Acc(spec)
    steps = list(route.шаги)
    notes = dict(route.пометки)
    counts = dict(route.штук)
    step_seconds: dict[str, tuple[float, float]] = {}
    prefer: dict[str, str] = {}
    avoid: dict[str, str] = {}
    stylised: list[str] = []
    optional: list[str] = []
    anonymise_assembly: tuple[str, ...] = ()
    drop_assembly: tuple[str, ...] = ()
    inputs = set(spec.inputs)
    outputs = set(spec.outputs)
    tasks = {spec.task, *spec.then_tasks}
    free = False
    local = False

    # --- customer likeness: their recording, their video -----------------------
    if spec.task == "avatar" and "video" in inputs and "photo" not in inputs and "говорящий_аватар" in steps:
        if acc.prior("customer_likeness", "own_video_likeness"):
            steps = _replace_step(steps, "говорящий_аватар", "липсинк")
            notes.pop("говорящий_аватар", None)
            notes["липсинк"] = NOTE_OWN_LIPSYNC[0]
            if "audio" not in inputs:
                steps = ["клонирование_голоса", *steps]
                notes["клонирование_голоса"] = NOTE_CLONE[0]
                acc.assembly.append(ASSEMBLY_EXTRACT)
    if (
        "audio" in inputs
        and "script" in inputs
        and ("speech" in outputs or spec.task == "avatar")
        and "клонирование_голоса" not in steps
        and (set(steps) & SPEECH_CONSUMERS or "озвучка" in steps)
    ):
        if acc.prior("customer_likeness", "voice_sample_clone"):
            steps = ["клонирование_голоса", *(s for s in steps if s != "озвучка")]
            notes["клонирование_голоса"] = NOTE_CLONE[0]

    # --- one recurring host -----------------------------------------------------
    if (
        (spec.characters == 1 or len(spec.people) == 1)
        and (spec.shots or 0) >= 2
        and not inputs & {"photo", "video"}
        and "video" in outputs
        and set(steps) & {"говорящий_аватар", "оживление", "видео_по_референсу"}
    ):
        if acc.prior("single_host_series", "single_reference"):
            counts["генерация_изображения"] = SINGLE_HOST_REFERENCES
            notes.setdefault("генерация_изображения", NOTE_ONE_REFERENCE[0])

    # --- round 10: a mascot or costumed character replaces the person --------------
    # Face swap is for a HUMAN face; a mascot replaces the whole figure (silhouette,
    # body, motion) — the Wan Animate replace class, not inswapper / FaceFusion.
    if spec.task == "face-replace" and "замена_персонажа" in steps and whole_character(spec, text):
        if acc.prior("character_replacement", "whole_character_replace"):
            steps = _replace_step(steps, "замена_персонажа", "замена_фигуры")
            notes.pop("замена_персонажа", None)
            notes["замена_фигуры"] = NOTE_WHOLE_CHARACTER[0]

    # --- round 10: virtual try-on on a generated model -------------------------------
    # The customer brings the garment; the person wearing it does not exist yet:
    # text-to-image makes the model photo, then a try-on puts the garment on it.
    # With two or more photos brought, the model photo is the customer's.
    if (
        spec.task in ("edit", "generate", None)
        and "image" in outputs
        and "video" not in outputs
        and "photo" in inputs
        and "редактирование_изображения" in steps
        and wants_try_on(spec, text)
    ):
        if acc.prior("virtual_try_on", "virtual_try_on"):
            made = ["генерация_изображения"] if _photo_count(spec) <= 1 else []
            steps = [s for s in steps if s not in ("редактирование_изображения", "генерация_изображения")]
            steps = [*made, "примерка", *steps]
            notes.pop("редактирование_изображения", None)
            notes["примерка"] = NOTE_TRY_ON[0]
            if made:
                notes["генерация_изображения"] = NOTE_TRY_ON_MODEL[0]

    # --- round 12: a property walkthrough from photos ---------------------------------
    # Motion transfer needs a DRIVING video of a performer; a tour of rooms is a camera
    # moving through stills: one image-to-video camera move per photo, joined in order.
    if walkthrough(spec, text) and set(steps) & {"перенос_движения", "генерация_видео", "оживление"}:
        if acc.prior("property_walkthrough", "walkthrough_camera_path"):
            for old in ("перенос_движения", "генерация_видео"):
                steps = _replace_step(steps, old, "оживление")
                notes.pop(old, None)
            notes["оживление"] = NOTE_WALKTHROUGH[0]
            avoid["оживление"] = MOTION_CONTROL_MODELS
            acc.assembly.append(ASSEMBLY_WALKTHROUGH)
            if _photo_count(spec) >= SPLAT_PHOTOS_MIN:
                acc.assembly.append(ASSEMBLY_SPLAT)

    # --- round 12: dubbing drawn footage ---------------------------------------------
    if spec.task == "dub-translate" and "липсинк" in steps and drawn(spec, text):
        # Round 15 (hidden set): an expert keeps lip sync on a 2D cartoon dub — on a model recorded for
        # drawn / stylised faces (`planner.STYLISED_FACE_FACT`), with the mouth-flap re-time as the fallback.
        if acc.prior("drawn_dub", "drawn_stylised_lipsync"):
            stylised.append("липсинк")
            notes["липсинк"] = NOTE_DRAWN_DUB[0]
            if ANIMAL_CHARACTERS.search(" ".join((*map(str, spec.conditions), text))):
                notes["липсинк"] = NOTE_DRAWN_DUB_ANIMAL[0]
            # Round 16: long anime / cartoon dubs adapt the script to the existing mouth flaps; visual
            # lip sync is an OPTIONAL upgrade priced apart (`expert_r16.optional_lips`), required only
            # when `spec.lipsync` is true.
            if x16.optional_lips(spec, drawn=True):
                optional.append(x16.OPTIONAL_LIPS_STEP)
                notes["дубляж"] = x16.NOTE_DRAWN_ADAPT[0]
                acc.assembly.append(ASSEMBLY_DRAWN_ADAPT)
            else:
                acc.assembly.append(ASSEMBLY_DRAWN_DUB)

    # --- round 12: a dub that must run on the customer's own machine --------------------
    # Hosted dubbing endpoints are one call; on own hardware the same job is a chain.
    if spec.task == "dub-translate" and "дубляж" in steps and local_only(spec, text):
        if acc.prior("local_dub", "local_dub_chain"):
            i = steps.index("дубляж")
            steps = [*steps[:i], "расшифровка", "клонирование_голоса", *steps[i + 1 :]]
            notes.pop("дубляж", None)
            notes["расшифровка"] = NOTE_LOCAL_TRANSCRIBE[0]
            notes["клонирование_голоса"] = NOTE_LOCAL_VOICE[0]
            avoid["клонирование_голоса"] = NO_CLONE_MODELS
            acc.assembly += [ASSEMBLY_EXTRACT, ASSEMBLY_LOCAL_DUB]
            local = True

    # --- logo / wordmark ----------------------------------------------------------
    # Only where the piece is MADE (generate / animate): a logo printed on a brought
    # product (turntable of packshots) stays on the product and is not overlaid.
    if spec.task in LOGO_TASKS and "video" in outputs and logo_named(spec):
        if (
            spec.task in (None, "generate")
            and "photo" in inputs
            and "оживление" in steps
            and acc.prior("brand_mark", "logo_image_is_endcard")
        ):
            steps = _replace_step(steps, "оживление", "генерация_видео")
            notes.pop("оживление", None)
            notes["генерация_видео"] = NOTE_ENDCARD_FOOTAGE[0]
        if acc.prior("brand_mark", "logo_overlay"):
            if spec.task == "animate":
                acc.assembly.append(ASSEMBLY_LOGO_STING)
                acc.tools.append("ffmpeg_xfade")
            else:
                acc.assembly.append(ASSEMBLY_LOGO)

    # --- foley for the customer's picture ---------------------------------------
    # Round 13: the step IS video-to-audio (its own operation, job v2a), not the
    # text-to-sound-effects step with a preference: a model that does not watch the
    # picture cannot land the hits on it. A soundtrack asked to follow the action
    # of the brought footage is the same job.
    if "video" in inputs and "audio" not in inputs:
        sound = [s for s in ("звук_фон", "музыка") if s in steps and (s == "звук_фон" or follows_picture(spec, text))]
        if sound and acc.prior("foley_for_picture", "foley_v2a"):
            for old in sound:
                steps = _replace_step(steps, old, bs.V2A_STEP)
                notes.pop(old, None)
            prefer[bs.V2A_STEP] = ARTEFACT_VIDEO
            notes[bs.V2A_STEP] = NOTE_V2A[0]
            acc.assembly.append(ASSEMBLY_FOLEY)

    # --- archive film ---------------------------------------------------------------
    if tasks & {"restore", "colorize"}:
        blur = blur_named(spec)
        if "реставрация" in steps and not blur and acc.prior("archive_restoration", "film_damage_not_blur"):
            avoid["реставрация"] = DEBLUR_MODELS
            acc.assembly.append(ASSEMBLY_FILM)
        if len(set(steps) & set(CHAIN_RANK)) >= 2:
            acc.prior("archive_restoration", "restore_colourise_upscale_order")

    # --- music visualiser: audiogram over brought art, lyrics -----------------------
    # Round 9. A visualiser over the customer's own cover art (an audiogram) is
    # assembly: the waveform and the captions move, the art does not — the route
    # animated the art (image-to-video, ~$2.7 for 45 s) for what ffmpeg showwaves
    # does at 0 usd. Animating the art stays one condition away.
    if (
        spec.task == "music-visualiser"
        and "photo" in inputs
        and "оживление" in steps
        and not art_moves(spec)
    ):
        if acc.prior("audiogram", "audiogram_static_art"):
            steps = [s for s in steps if s != "оживление"]
            notes.pop("оживление", None)
            if spec.language_tags and "расшифровка" not in steps:
                steps = ["расшифровка", *steps]
                notes["расшифровка"] = NOTE_AUDIOGRAM_CAPTIONS[0]
            acc.assembly.append(ASSEMBLY_AUDIOGRAM)
    # A lyric video: the customer's words (a text input) are timed to the vocals.
    if spec.task == "music-visualiser" and "script" in inputs and "audio" in inputs and "расшифровка" not in steps:
        if acc.prior("lyric_video", "lyrics_alignment"):
            steps = ["расшифровка", *steps]
            notes["расшифровка"] = NOTE_LYRICS[0]
            acc.assembly.append(ASSEMBLY_LYRICS)

    # --- 3D model of a product -----------------------------------------------------
    # Round 9: «interactive 3D model of our chair (GLB) from 6 photos» was planned
    # as a turntable VIDEO — a clip is not a mesh.
    if spec.task == "turntable" and "оборот_360" in steps and wants_mesh(spec, text):
        if acc.prior("product_3d", "mesh_reconstruction"):
            steps = _replace_step(steps, "оборот_360", "модель_3d")
            notes.pop("оборот_360", None)
            if "video" in outputs:
                acc.assembly.append(ASSEMBLY_MESH_RENDER)

    # --- transparent background ---------------------------------------------------
    # Round 9. No generator renders alpha: «transparent background for our
    # website» got one image-to-video step and an opaque MP4.
    if (
        "video" in outputs
        and wants_alpha(spec, text)
        and "удаление_фона_видео" not in steps
        and any(s in VIDEO_GENERATORS for s in steps)
    ):
        if acc.prior("alpha_delivery", "alpha_matte"):
            maker = max(i for i, s in enumerate(steps) if s in VIDEO_GENERATORS)
            steps = [*steps[: maker + 1], "удаление_фона_видео", *steps[maker + 1 :]]
            notes["удаление_фона_видео"] = NOTE_MATTE[0]
            acc.assembly.append(ASSEMBLY_ALPHA)

    # --- beat-reactive visualiser -----------------------------------------------
    # Round 14: a visualiser ordered as "generate" (YOUR track, nobody on screen) is the same job.
    visualiser = spec.task == "music-visualiser" or bs.визуализатор(spec, text)
    if visualiser and not scenes_named(spec):
        loop_maker = next((s for s in steps if s in VIDEO_GENERATORS), None)
        if loop_maker is not None and acc.prior("music_visualiser", "visualiser_loops"):
            step_seconds[loop_maker] = (
                float(VISUALISER_LOOP_CLIPS * VISUALISER_LOOP_CLIP_S),
                float(VISUALISER_LOOP_CLIP_S),
            )
            notes[loop_maker] = NOTE_LOOPS[0]
            acc.assembly.append(ASSEMBLY_LOOPS)

    # --- round 13: one loop, many versions (a shared asset) ----------------------------
    shared: list[str] = []
    loop_s = loop_seconds(spec, text)
    if (
        loop_s is not None
        and spec.task in (None, "generate", "animate")
        and "speech" not in outputs
        and "video" in outputs
        and not set(steps) & SPEECH_CONSUMERS
        and (spec.characters or 0) < 2
    ):
        loop_step = next((s for s in steps if s in LOOP_MAKERS), None)
        if loop_step is not None and acc.prior("shared_loop", "loop_reuse"):
            step_seconds[loop_step] = (loop_s, loop_s)
            counts[loop_step] = 1
            if "генерация_изображения" in steps:
                counts["генерация_изображения"] = 1
            notes[loop_step] = NOTE_LOOP_ONCE[0].format(s=f"{loop_s:g}")
            acc.assembly.append(ASSEMBLY_LOOP_VERSIONS)
            shared.append(loop_step)
    if counts.get("генерация_изображения") == SINGLE_HOST_REFERENCES and "генерация_изображения" in steps:
        shared.append("генерация_изображения")

    # --- round 15: hours of ambience are one loopable segment ------------------------------
    # A 3-hour rain track or an 8-hour fireplace was priced as full-length generation
    # (108 usd of music, 5760 usd of video): an expert generates one loopable segment and
    # repeats it at assembly (`expert_r15.ambient_segment_s`, `checklist.long_ambient_loop`).
    from studio import expert_r15 as x15

    ambient = [s for s in steps if s in AMBIENT_MAKERS]
    if ambient and not set(steps) & SPEECH_CONSUMERS and "speech" not in outputs:
        audio_s = x15.ambient_segment_s(spec, text, audio=True)
        if audio_s is not None and acc.prior("ambient_loop", "ambient_segment_loop"):
            said = " ".join((str(text or ""), *map(str, spec.conditions)))
            video_s = loop_seconds(spec, text) if LOOP_LENGTH.search(said) else None
            video_s = video_s or x15.ambient_segment_s(spec, text, audio=False) or float(x15.AMBIENT_VIDEO_SEGMENT_S)
            for s in ambient:
                seg = audio_s if s in AMBIENT_AUDIO_MAKERS else video_s
                step_seconds[s] = (seg, seg)
                counts[s] = 1
                notes[s] = (x15.NOTE_AMBIENT_AUDIO if s in AMBIENT_AUDIO_MAKERS else x15.NOTE_AMBIENT_VIDEO)[0].format(
                    n=f"{seg:g}"
                )
                if s not in shared:
                    shared.append(s)
            if "генерация_изображения" in steps:
                counts["генерация_изображения"] = 1
            acc.assembly.append(x15.ASSEMBLY_AMBIENT)

    # --- round 15: anonymising bystanders in the customer's footage --------------------------
    # Round 16: `spec.anonymise` decides in any brief language (`studio/anonymise.py`); with the field
    # named the face route does not need an edit / swap step on the route — a dub order of a witness
    # whose face is hidden too gets it.
    from studio import anonymise as an

    named = an.field_named(spec)
    method = an.face_method(spec, text)
    # Round-16 integration: an edit whose named target is not the person (a new background, sky,
    # object, light, style or lettering) is the customer's own change, not the anonymisation — it stays
    # on the route beside the face route (and keeps its own model choice, e.g. the edit tier swap).
    own_edit = ANONYMISE_KEEPS_EDIT if spec.edit_target not in (None, "person") else frozenset()
    stripped = ANONYMISE_ROUTES - own_edit
    if method and "video" in inputs and (named or set(steps) & ANONYMISE_ROUTES):
        if method == "swap" and acc.prior("anonymise_bystanders", "anonymise_face_swap"):
            steps = [s for s in steps if s not in stripped]
            steps = [*an.FACE_SWAP_STEPS, *steps]
            counts["генерация_изображения"] = 1
            notes["генерация_изображения"] = x15.NOTE_SYNTHETIC_FACE[0]
            notes["замена_персонажа"] = x15.NOTE_ANON_SWAP[0]
            avoid["замена_персонажа"] = x15.PERSON_REPLACE_LINKS
            acc.assembly.append(x15.ASSEMBLY_ANON_BLUR_ALT)
        elif method == "blur" and acc.prior("anonymise_bystanders", "anonymise_blur"):
            steps = [s for s in steps if s not in stripped]
            for s in stripped:
                notes.pop(s, None)
            anonymise_assembly = (x15.ASSEMBLY_ANON_BLUR[0],)
            acc.assembly.append(x15.ASSEMBLY_ANON_BLUR)
        elif method == "pixelate" and acc.prior("anonymise_bystanders", "anonymise_pixelate"):
            steps = [s for s in steps if s not in stripped]
            for s in stripped:
                notes.pop(s, None)
            anonymise_assembly = (an.ASSEMBLY_PIXELATE[0],)
            acc.assembly.append(an.ASSEMBLY_PIXELATE)
    # The VOICE: transcript + a different stock voice — never a clone, never a dub (it keeps the timbre).
    voice_anon = an.voice(spec, text) and bool(inputs & {"video", "audio"})
    if voice_anon and acc.prior("anonymise_voice", "anonymise_voice_replace"):
        steps = an.voice_route(steps)
        for s in an.VOICE_DROPS:
            notes.pop(s, None)
        notes["расшифровка"] = an.NOTE_VOICE_TRANSCRIPT[0]
        notes["озвучка"] = an.NOTE_VOICE_TTS[0]
        avoid["озвучка"] = an.CLONE_ONLY_MODELS
        acc.assembly.append(an.ASSEMBLY_VOICE)
        # The dubbed-track mux line of a dub route no longer describes the plan.
        drop_assembly = (bs.NOTE_DUB_MUX,)
        # Round-16 integration: nor do the drawn-dub lines (adaptation to the mouth flaps, the
        # optional lip-sync upgrade) — the voice route has no dub and no lip-sync step.
        acc.assembly[:] = [a for a in acc.assembly if a not in DUB_ONLY_ASSEMBLY]
    # --- round 17: the missing routes (`studio/routes_r17.py`) -------------------------------------
    # Burned-in subtitles, a singer's music video from a performer reference, a 3D reconstruction of a
    # place, a whole-person replacement, a UGC product batch — spec first, EN/RU words only as fallback.
    from studio import routes_r17 as r17
    from studio import routes_r18 as r18

    # Round 18: a tour over a photo SET / walk-through video is the 3D route (assumption named).
    steps = r17.rewrite(r18.with_tour(spec, text), steps, notes, counts, step_seconds, acc, text)
    # --- round 18: routes & decomposition (`studio/routes_r18.py`) ----------------------------------
    # Try-on batch, the restoration chain's faces, a speech batch, a podcast audiogram, a vertical reframe's
    # captions, a motion comic, a dance performance, one presenter still — spec first, EN/RU words fallback.
    steps = r18.rewrite(spec, steps, notes, counts, step_seconds, acc, text, avoid=avoid, shared=shared)
    drop_assembly = (*drop_assembly, *r18.dropped_assembly(acc.priors))
    # Round-17 integration: with the burned-subtitle route the new subtitles come from the transcript and
    # its own burn-in line; "your SRT burned in — no transcription needed" no longer describes the plan.
    if "burned_subtitles_replace" in acc.priors:
        drop_assembly = (*drop_assembly, bs.NOTE_BURN_CAPTIONS)
    # An optional step the route no longer has is not offered.
    optional = [s for s in optional if s in steps]

    # --- round 17: accessibility package, series recap, background blur -----------------------
    from studio import expert_r17 as x17

    # An accessibility package with audio description: ONE transcript (captions, text, translation and
    # the speech gaps come from it) and a distinct stock voice for the GAP seconds, not the runtime.
    runtime = x17.material_seconds(spec)
    if x17.ad_package(spec, text) and runtime and acc.prior("accessibility_package", "ad_gap_voice"):
        if "расшифровка" not in steps:
            steps = ["расшифровка", *steps]
        notes["расшифровка"] = x17.NOTE_AD_TRANSCRIPT[0]
        if "озвучка" not in steps:
            steps = [*steps, "озвучка"]
        gap = x17.ad_voice_seconds(runtime)
        step_seconds["озвучка"] = (gap, gap)
        notes["озвучка"] = x17.NOTE_AD_VOICE[0].format(share=f"{x17.AD_GAP_SHARE * 100:g}", n=f"{gap:g}")
        avoid["озвучка"] = an.CLONE_ONLY_MODELS  # the description voice is never a clone of the speaker
        acc.assembly.append(x17.ASSEMBLY_AD_MIX)
    # A recap of the customer's series: their footage is cut (a generative edit regenerates nothing that
    # is needed), and a narrator is priced by the RECAP's length, not the series'.
    if x17.recap_edit(spec, text) and "правка_видео" in steps and acc.prior("series_recap", "recap_short_vo"):
        if "burned_subtitles_replace" in acc.priors:
            # Round-17 integration: the edit left is the removal of the burned-in subtitles (the recap
            # is still cut at assembly) — the route keeps it and the transcript it already has.
            if "расшифровка" not in steps:
                steps = ["расшифровка", *steps]
        else:
            steps = _replace_step(steps, "правка_видео", "расшифровка")
            notes.pop("правка_видео", None)
            notes["расшифровка"] = bs.NOTE_SHORTS_TRANSCRIPT
        acc.assembly.append(x17.ASSEMBLY_RECAP)
    vo_s = x17.recap_vo_seconds(spec)
    if x17.recap_narration(spec, text) and vo_s and acc.prior("series_recap", "recap_short_vo"):
        if "озвучка" not in steps:
            steps = [*steps, "озвучка"]
        notes["озвучка"] = x17.NOTE_RECAP_VO[0].format(n=f"{vo_s:g}")
        acc.assembly.append(x17.ASSEMBLY_RECAP)
    # A background blur (bokeh): a person matte and a lens blur at assembly — never a generative edit.
    # Round-17 integration: beside a whole-person replacement (`замена_фигуры` took the edit's place) the
    # matte is pulled over the replaced footage and the background blurred under it — both edits stay.
    blur_from = "правка_видео" if "правка_видео" in steps else "замена_фигуры" if "замена_фигуры" in steps else None
    if x17.background_blur(spec, text) and blur_from and acc.prior("background_blur", "matte_background_blur"):
        if blur_from == "правка_видео":
            steps = _replace_step(steps, "правка_видео", "удаление_фона_видео")
        else:
            steps = list(dict.fromkeys((*steps, "удаление_фона_видео")))
        notes.pop("правка_видео", None)
        notes["удаление_фона_видео"] = x17.NOTE_MATTE_BLUR[0]
        acc.assembly.append(x17.ASSEMBLY_BLUR)


    # --- zero budget ------------------------------------------------------------------
    # Own GPU already named — the plan is on the free route; nothing to add.
    if not spec.self_host and (
        (spec.budget_amount is not None and spec.budget_amount <= 0)
        or (spec.budget_amount is None and spec.budget_usd is not None and spec.budget_usd <= 0)
    ):
        free = acc.prior("zero_budget", "zero_budget_self_host")

    if tasks & {"restore", "colorize"} or steps != list(route.шаги):
        steps = order(steps)
    new_route = replace(route, шаги=tuple(steps), пометки=notes, штук=counts)
    # The assembly-only route (blur / pixelate with no model step left) carries its line on the route;
    # with model steps the line is in `assembly` already (not twice).
    if anonymise_assembly and not steps:
        new_route = replace(new_route, сборка=tuple(dict.fromkeys((*new_route.сборка, *anonymise_assembly))))
    if drop_assembly:
        new_route = replace(new_route, сборка=tuple(с for с in new_route.сборка if с not in drop_assembly))
    return Applied(
        route=new_route,
        recipes=tuple(acc.recipes),
        priors=tuple(acc.priors),
        overridden=tuple(acc.overridden),
        tools=tuple(dict.fromkeys((*_tools_of(acc.priors), *acc.tools))),
        failures=_failures_of(acc.priors),
        step_seconds=step_seconds,
        prefer_input=prefer,
        avoid=avoid,
        prefer_stylised=tuple(stylised),
        optional=tuple(optional),
        assembly=tuple(dict.fromkeys(acc.assembly)),
        free_route=free,
        local_only=local,
        print_frame=delivery.print_frame(spec, text),
        shared=tuple(dict.fromkeys(shared)),
    )


def _tools_of(priors: Sequence[str]) -> tuple[str, ...]:
    """Free tools the applied priors bring."""
    return tuple(dict.fromkeys(t for p in priors for t in PRIORS[p].tools))


def _failures_of(priors: Sequence[str]) -> tuple[str, ...]:
    """Failure modes to check for the applied priors."""
    return tuple(dict.fromkeys(f for p in priors for f in PRIORS[p].failures))


def _mp(frame: tuple[int, int]) -> float:
    return frame[0] * frame[1] / 1e6


def frame_prior(
    op_name: str, asked: tuple[int, int] | None, spec: "bs.Spec", printed: bool = False
) -> tuple[Prior, bool] | None:
    """The class prior for a SILENT frame at a generator step: (prior, on) or None.

    Only a generator's class has a native maximum; a pass over a brought clip
    (lip sync, edit) carries its input's frame and is not judged here.

    :param printed: the still is a print (round 10, `delivery.print_frame`): a
        silent generator is taken to render `delivery.PRINT_SILENT_NATIVE_MP`.
    """
    if asked is None:
        return None
    if op_name in IMAGE_GENERATORS and _mp(asked) > T2I_NATIVE_MAX_MP:
        prior = PRIORS["t2i_native_max"]
    elif printed and op_name in IMAGE_GENERATORS and _mp(asked) > delivery.PRINT_SILENT_NATIVE_MP:
        prior = PRIORS["print_upscale"]
    elif op_name in VIDEO_GENERATORS and _mp(asked) > T2V_NATIVE_MAX_MP:
        prior = PRIORS["t2v_native_max"]
    else:
        return None
    return prior, enabled(spec, prior.id)


def fps_prior(op_name: str, asked: float | None, spec: "bs.Spec") -> tuple[Prior, bool] | None:
    """The class prior for a SILENT frame rate at a generator step: (prior, on) or None."""
    if not asked or op_name not in VIDEO_GENERATORS or asked <= T2V_NATIVE_FPS_MAX:
        return None
    prior = PRIORS["t2v_fps_native"]
    return prior, enabled(spec, prior.id)


def requirement_frame(
    op_name: str, asked: tuple[int, int] | None, spec: "bs.Spec"
) -> tuple[int, int] | None:
    """The frame a generator is RANKED against when its class prior applies.

    Round-8 integration: the planner's order-requirement key ("frame native")
    asks every candidate for the ordered frame. Above the class maximum (8K
    video, 8K stills) no generator can meet it, so every candidate tied at
    "unknown" and price alone decided -- a 1080p generator beat a native-4K
    one, and the upscale step then started from 1080p. With the prior on, the
    requirement is the class maximum at the ordered aspect: the generator is
    chosen for the largest native frame, and the upscale (added by the same
    prior) covers the rest. Prior off, or the frame within the class: the
    ordered frame, unchanged.
    """
    found = frame_prior(op_name, asked, spec)
    if asked is None or found is None or not found[1]:
        return asked
    cap = T2I_NATIVE_MAX_MP if found[0].id == "t2i_native_max" else T2V_NATIVE_MAX_MP
    k = (cap / _mp(asked)) ** 0.5
    # Snap to a multiple of 8, the way real frames are sized: T2V_NATIVE_MAX_MP
    # is a rounded megapixel figure, and 8K scaled by it came out 3841x2160 —
    # one pixel wider than 4K, so every native-4K generator read as "below".
    return (int(round(asked[0] * k / 8)) * 8, int(round(asked[1] * k / 8)) * 8)


def order(names: Sequence[str]) -> list[str]:
    """Order of operations: `FIRST_STEPS` in front; the chain steps re-sorted in their own slots.

    Steps outside the chain keep their places: only the slots the chain
    occupies are refilled in `CHAIN_RANK` order (stable).
    """
    # A clone that reads a TRANSCRIPT (the local dub chain) comes after the transcription.
    first = [n for n in FIRST_STEPS if n in names and "расшифровка" not in names]
    rest = [n for n in names if n not in first]
    slots = [i for i, n in enumerate(rest) if n in CHAIN_RANK]
    chain = sorted((rest[i] for i in slots), key=lambda n: CHAIN_RANK[n])
    for i, n in zip(slots, chain):
        rest[i] = n
    return [*first, *rest]


#: Names of endpoints that do the job a preferred-input prior asks for (searched in the registry
#: when the chosen model does not take that input).
HINT_MODELS: dict[str, str] = {bs.V2A_STEP: r"mmaudio|foley|thinksound|video-to-audio|(?:^|-)v2a(?:-|$)"}


def unmet(applied: Applied, chosen: Mapping[str, str | None], registry: object, english: bool) -> list[dict]:
    """Steps where the prior asked for a model taking an input, and the chosen one does not.

    P1: the prior is not reported as satisfied on silence — the chosen model's
    recorded inputs decide; with none recorded the row says so.
    """
    rows: list[dict] = []
    for step, artefact in applied.prefer_input.items():
        model = chosen.get(step)
        if model is None:
            continue
        node = registry.get(model)  # type: ignore[attr-defined]
        inputs = tuple(node.inputs) if node is not None else ()
        if artefact in inputs:
            continue
        pattern = HINT_MODELS.get(step, "")
        known = (
            sorted(
                n.model
                for n in registry.by_key.values()  # type: ignore[attr-defined]
                if artefact in n.inputs and re.search(pattern, n.model, re.I)
            )
            if pattern
            else []
        )
        rows.append(
            {
                "step": step,
                "model": model,
                "outcome": "fail" if inputs else "could not measure",
                "note": (
                    f"the chosen {model} "
                    + (f"takes {', '.join(inputs)}, not {artefact}" if inputs else "records no inputs")
                    + "; the recipe asks for a model that watches the footage"
                    + (
                        f"; in the base but not listed for this step by the registry: {', '.join(known)}"
                        if known
                        else ""
                    )
                    if english
                    else f"выбранная {model} "
                    + (f"принимает {', '.join(inputs)}, а не {artefact}" if inputs else "входов не записала")
                    + "; рецепт просит модель, которая смотрит ролик"
                    + (f"; в базе есть, но реестр не ставит на этот шаг: {', '.join(known)}" if known else "")
                ),
            }
        )
    return rows


def block(
    applied: Applied,
    post_priors: Sequence[str],
    post_overridden: Sequence[str],
    steps: Sequence[str],
    english: bool,
    label: Callable[[str, bool], str],
    free_route: Mapping[str, object] | None = None,
    not_met: Sequence[Mapping[str, object]] = (),
) -> dict | None:
    """The plan's `recipe` row in the answer's language; None when no recipe matched."""
    priors = list(dict.fromkeys((*applied.priors, *post_priors)))
    overridden = list(dict.fromkeys((*applied.overridden, *post_overridden)))
    recipes = list(applied.recipes)
    for p in (*post_priors, *post_overridden):
        r = next(r for r in RECIPES.values() if p in r.priors).id
        if r not in recipes:
            recipes.append(r)
    if not recipes:
        return None
    failures = list(_failures_of(priors))
    row: dict = {
        "classes": recipes,
        "priors_applied": [
            {
                "id": p,
                "says": PRIORS[p].en if english else PRIORS[p].ru,
                "tag": PRIORS[p].tag if english else TAG_RU[PRIORS[p].tag],
                "sources": [{"model": s.model, "attribute": s.attribute, "url": s.url} for s in PRIORS[p].sources],
            }
            for p in priors
        ],
        "priors_overridden": overridden,
        "tools": [
            {"name": TOOLS[t].name, "does": TOOLS[t].en if english else TOOLS[t].ru, "price": "0 usd"}
            for t in dict.fromkeys((*applied.tools, *_tools_of(post_priors)))
        ],
        "order": [{"step": s, "label": label(s, english)} for s in steps],
        "check": [
            {
                "failure": FAILURES[f].en if english else FAILURES[f].ru,
                "look": FAILURES[f].check_en if english else FAILURES[f].check_ru,
            }
            for f in failures
        ],
        "how_to_override": (
            "spec.priors={'<id>': false} switches a prior off; a fact recorded about the chosen model always "
            "wins over a prior"
            if english
            else "spec.priors={'<id>': false} выключает допущение; записанный о выбранной модели факт всегда "
            "старше допущения"
        ),
    }
    if free_route:
        row["free_route"] = dict(free_route)
    if not_met:
        row["prior_not_met"] = [dict(r) for r in not_met]
    return row


def assumption(prior_id: str, english: bool) -> str:
    """The prior as an assumption line of `understood_as`."""
    p = PRIORS[prior_id]
    if english:
        return f"prior {p.id} ({p.tag}): {p.en}; pass spec.priors={{'{p.id}': false}} to switch it off"
    return f"допущение {p.id} ({TAG_RU[p.tag]}): {p.ru}; выключить — spec.priors={{'{p.id}': false}}"


#: Route notes of the recipes, Russian -> English (`brief_spec.note_en`).
NOTES_EN: dict[str, str] = dict(
    (
        NOTE_CLONE,
        NOTE_OWN_LIPSYNC,
        NOTE_ENDCARD_FOOTAGE,
        NOTE_LOOPS,
        NOTE_V2A,
        NOTE_ONE_REFERENCE,
        NOTE_MATTE,
        NOTE_LYRICS,
        NOTE_AUDIOGRAM_CAPTIONS,
        NOTE_WHOLE_CHARACTER,
        NOTE_TRY_ON,
        NOTE_TRY_ON_MODEL,
        NOTE_WALKTHROUGH,
        NOTE_DRAWN_DUB,
        NOTE_DRAWN_DUB_ANIMAL,
        NOTE_LOCAL_TRANSCRIBE,
        NOTE_LOCAL_VOICE,
    )
)
# Round 17: the route notes of `studio/routes_r17.py`.
from studio import routes_r17 as _r17  # noqa: E402

NOTES_EN.update(dict(_r17.NOTE_PAIRS))
# Round 18: the route notes of `studio/routes_r18.py`.
from studio import routes_r18 as _r18  # noqa: E402

NOTES_EN.update(dict(_r18.NOTE_PAIRS))


# --- production notes (round 9) --------------------------------------------------------


def _ratio(aspect: str | None) -> float | None:
    """W:H as a number: «2.39:1» -> 2.39, «16:9» -> 1.78; None when unreadable."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[:x/]\s*(\d+(?:\.\d+)?)\s*", str(aspect or ""))
    if not m or float(m.group(2)) == 0:
        return None
    return float(m.group(1)) / float(m.group(2))


def native_aspect(aspect: str | None) -> bool | None:
    """Is the ordered aspect one a generator renders natively? None — no aspect or unreadable."""
    r = _ratio(aspect)
    if r is None:
        return None
    return any(abs(r - n) / n <= ASPECT_TOLERANCE for n in NATIVE_ASPECTS)


def _photo_count(spec: "bs.Spec") -> int:
    """How many images the customer brought (an image input without a count is one)."""
    return sum(int(з.get("count") or 1) for з in spec.input_items if з.get("kind") == "photo")


def _speakers(spec: "bs.Spec") -> int:
    return max(len(spec.people), spec.characters or 0)


def _regional_tags(spec: "bs.Spec") -> list[str]:
    """Language tags that name a region (`ar-EG`, `pt-BR`, `es-419`): a variety, not only a language."""
    out = []
    for тег in spec.language_tags:
        части = str(тег).split("-")
        if len(части) >= 2 and re.fullmatch(r"[A-Za-z]{2}|\d{3}", части[1]):
            out.append(str(тег))
    return out


def note_ids(
    spec: "bs.Spec",
    steps: Sequence[str],
    *,
    text: str = "",
    applied: "Applied | None" = None,
    extra_priors: Sequence[str] = (),
) -> list[tuple[str, dict[str, str]]]:
    """Which production notes this plan carries, with the fields of their wording.

    One rule per job class or condition — never per brief. `steps` are the plan's
    final operation names (an assembly-only plan has none).
    """
    names = set(steps)
    outputs = set(spec.outputs)
    priors = (set(applied.priors) if applied is not None else set()) | set(extra_priors)
    seconds = spec.duration_s or bs.source_seconds(spec)
    out: list[tuple[str, dict[str, str]]] = []
    if "музыка" in names:
        out.append(("music_licence", {}))
    if spec.open_weights or spec.self_host:
        out.append(("weights_licence", {}))
    if any(з.get("kind") == "audio" and з.get("owned") is False for з in spec.input_items):
        out.append(("song_rights", {}))
    if names & SPEECH_VIDEO_STEPS and seconds and seconds > LONG_FORM_S:
        out.append(("long_form_segmented", {"seconds": f"{seconds:g}"}))
    if set(spec.edit) & MASK_EDITS:
        out.append(("mask_composite", {}))
    if "reframe" in spec.edit:
        out.append(("crop_track", {"aspect": str(spec.aspect or "")}))
    if names & FRAME_MAKERS and native_aspect(spec.aspect) is False:
        r = _ratio(spec.aspect) or 1.0
        out.append(("aspect_crop", {"aspect": str(spec.aspect), "native": "16:9" if r >= 1 else "9:16"}))
    if "EU" in spec.jurisdiction and names:
        out.append(("ai_act_label", {}))
    if names & LIP_STEPS and _speakers(spec) >= 2:
        out.append(("multi_speaker", {"speakers": str(_speakers(spec))}))
    if (
        exact_text_named(spec)
        and not priors & {"logo_overlay", "logo_image_is_endcard"}
    ):
        out.append(("logo_text_composited", {}))
    if "оборот_360" in names and _photo_count(spec) <= 1:
        out.append(("unseen_side", {}))
    if spec.task in CAPTION_TASKS and ("text" in outputs or spec.task == "captions"):
        out.append(("captions_burned", {}))
    if names & SPEECH_STEPS and (теги := _regional_tags(spec)):
        out.append(("regional_variety", {"tags": ", ".join(теги)}))
    if "lyrics_alignment" in priors:
        out.append(("lyric_alignment", {}))
    if "alpha_matte" in priors or ("video" in outputs and wants_alpha(spec, text)):
        out.append(("alpha_delivery", {}))
    if applied is not None and applied.free_route:
        out.append(("self_host_route", {}))
    if "audiogram_static_art" in priors:
        out.append(("waveform_layer", {}))
    if "модель_3d" in names:
        out.append(("mesh_route", {}))
    # Round 10: delivery conditions (`delivery.py`) — one rule per class.
    if delivery.is_print(spec, text) and names & (FRAME_MAKERS | {"апскейл_изображения"}):
        out.append(("print_resolution", _print_fields(spec, text)))
    if delivery.interlaced_source(spec, text) and names:
        out.append(("deinterlace", {}))
    if delivery.eight_k(spec) and names:
        out.append(("eight_k_detail", {}))
    if delivery.extreme_fps(spec) and names:
        out.append(("interp_artifacts", {"fps": f"{spec.fps:g}"}))
    # Round 11: the engineering checklist (`checklist.py`) — every job class and
    # common condition, read from structured spec fields first. A plan without a
    # step (assembly only) still carries the condition rules of its deliverable.
    out.extend(checklist.fire(spec, steps, text=text, priors=sorted(priors)))
    return out


#: The print note's frame when no trim size is named, per answer language (ru, en).
PRINT_NO_SIZE = (
    "назовите формат, чтобы получить пиксели (8x10 дюймов = 2400x3000 px при 300 DPI)",
    "name the trim size to get the pixels (8x10 in = 2400x3000 px at 300 DPI)",
)


def _print_fields(spec: "bs.Spec", text: str) -> dict[str, str]:
    """Fields of the print note: dpi, the named size, and the pixel frame it needs ("" = no size named)."""
    found = delivery.print_frame(spec, text)
    if found is None:
        return {"dpi": str(delivery.PRINT_DPI), "size": "", "frame": ""}
    (w, h), label, dpi = found
    return {"dpi": str(dpi), "size": f" ({label})", "frame": f"{w}x{h} px"}


def notes(
    spec: "bs.Spec",
    steps: Sequence[str],
    english: bool,
    *,
    text: str = "",
    applied: "Applied | None" = None,
    extra_priors: Sequence[str] = (),
) -> list[dict]:
    """The plan's `production_notes` rows in the answer's language.

    :param extra_priors: facts of the CHOSEN plan the recipe cannot know (round 14:
        `checklist.RUN_OVER_PRIOR` — a step's chosen model records a shorter run than the take).
    """
    rows: list[dict] = []
    for nid, fields in note_ids(spec, steps, text=text, applied=applied, extra_priors=extra_priors):
        n = NOTES.get(nid) or checklist.RULES[nid]
        if "aspect" in fields and not fields["aspect"]:
            fields = {**fields, "aspect": "the new aspect" if english else "новый формат"}
        if nid == "print_resolution" and not fields["frame"]:
            fields = {**fields, "frame": PRINT_NO_SIZE[1] if english else PRINT_NO_SIZE[0]}
        rows.append(
            {
                "id": nid,
                "says": (n.en if english else n.ru).format(**fields),
                "tag": n.tag if english else TAG_RU[n.tag],
                "sources": (
                    [{"model": s.model, "attribute": s.attribute, "url": s.url} for s in n.sources]
                    if isinstance(n, Note)
                    else [{"url": u} for u in n.sources]
                ),
            }
        )
    return rows
