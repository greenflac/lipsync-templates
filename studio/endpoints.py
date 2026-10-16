"""РЕЕСТР ЭНДПОИНТОВ: что можно ЗАКАЗАТЬ, какую работу оно делает и почём.

ЗАЧЕМ (2026-10-15, пятый круг). Четыре круга правок плановщика упёрлись в
одно и то же (диагноз независимого валидатора круга 4): каталог плановщика —
плоский список имён базы фактов без типов. Отсюда три класса дефектов:

1. выбирался УЗЕЛ СЕМЬИ без цены — `kling-3.0` в 24 шагах «цена не записана»,
   хотя цены записаны у вариантов (`kling-3.0-standard-t2v`): 47 из 115 планов
   кончались «цена неизвестна», «самое дешёвое» давало 0.00 -> 0.00;
2. видеомодель выигрывала липсинк (`hunyuanvideo-i2v`), замену лица
   (`flux-3-image-to-video-draft`), TTS — шумы (`eleven_v3`): сверялись только
   ВИДЫ входа и выхода, а не РАБОТА;
3. каждая новая работа (реставрация, удаление фона, интерполяция,
   расшифровка, клон голоса, оборот 360°) требовала ручной маршрутизации.

ЧТО ЗДЕСЬ. Реестр выводится ДЕТЕРМИНИРОВАННО из тех же строк, что читает
плановщик (`model_facts.jsonl` через `FactIndex`), семей `modelnames` и строк
каталога площадки (`availability`: «on fal.ai as <id> (<category>)»). Узел —
`Endpoint`: заказываемый идентификатор, маршруты, семья, РАБОТЫ (управляемый
словарь `FUNCTIONS`), входы и выходы, единицы цены, длина прогона, кадры,
нативный звук, лицензия, веса, память.

РАБОТА ИЗ СВИДЕТЕЛЬСТВА, А НЕ ИЗ НАШЕГО МНЕНИЯ. Каналы по старшинству, и
младший читается, только если старшие молчат (`classify`):

0. `curated` — короткая таблица `CURATED`: прочитанное человеком, у каждой
   строки — почему и адрес источника, уже лежащий в базе под этой моделью;
1. `id` — ИДЕНТИФИКАТОР эндпоинта (адрес на площадке, путь схемы, имя в базе):
   вендор сам назвал работу (`.../lipsync/...`, `-t2v`, `tts/eleven-v3`).
   Работа (`JOB_RULES`) старше режима (`MODE_RULES`): `kling-video-lipsync-
   text-to-video` — липсинк, а не генерация по тексту;
1б. `shape` — ОБЯЗАТЕЛЬНЫЙ звук на входе видеомодели (`AUDIO_DRIVEN`): старше
   категории площадки, которая числит аватар «image-to-video»;
2. `category` — категория каталога площадки (`CATEGORY_FUNCTIONS`);
3. `docs` — описательные строки вендора и площадки (`DOC_ATTRIBUTES`) и имена
   их атрибутов (`ATTRIBUTE_MODES`: `ratio_enum_text_to_video`);
4. `shape` — объявленные схемой входы и выход (`SHAPE_RULES`), только
   однозначные сочетания;
5. `variants` — узел семьи со своей ценой и без своей работы берёт режимы
   генерации у вариантов (`FAMILY_MODES`).

УЗЕЛ СЕМЬИ НЕ ЗАКАЗЫВАЕТСЯ. Имя, у которого в базе есть варианты
(`modelnames.parent`), а своего маршрута нет (ни цены, ни идентификатора
площадки), — это семья, а не эндпоинт: купить «kling-3.0» нельзя, можно купить
`kling-3.0-standard-t2v`. Семья ОДАЛЖИВАЕТ варианту применимость (её строки —
о той же модели) и длину прогона, но НИКОГДА не цену: цена — свойство тарифа.

Реестр не выбирает победителя: он отвечает «кто вообще годится на эту работу».
Порядок, доказательства, жёсткие требования и бюджет — по-прежнему
`studio/planner.py`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Iterable, Iterator, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from studio.selfrag import modelnames
from studio.selfrag.facts import Fact
from studio.selfrag.modelnames import fold

# --- словарь работ -----------------------------------------------------------

T2V = "t2v"
I2V = "i2v"
R2V = "r2v"
V2V_EDIT = "v2v-edit"
LIPSYNC = "lipsync"
AVATAR = "talking-avatar"
FACE_SWAP = "face-swap"
DUB = "dub-translate"
TTS = "tts"
VOICE_CLONE = "voice-clone"
MUSIC = "music"
SFX = "sfx"
T2I = "t2i"
IMAGE_EDIT = "image-edit"
BG_REMOVE = "bg-remove"
UPSCALE_IMAGE = "upscale-image"
UPSCALE_VIDEO = "upscale-video"
#: Реставрация и раскраска — РАЗНЫЕ работы (шестой круг): `seedvr2-7b`
#: восстанавливает (шум, царапины, резкость), но не раскрашивает; `ddcolor`
#: раскрашивает, но не реставрирует. Общая работа «restore-colorize» отдавала
#: реставратор на шаг раскраски.
RESTORE = "restore"
COLORIZE = "colorize"
INTERPOLATE = "frame-interpolate"
TRANSCRIBE = "transcribe-diarize"
CAPTIONS = "captions"
TURNTABLE = "turntable-360"
#: Девятый круг: 3D-модель по снимкам (TRELLIS, Hunyuan3D, Tripo). Не видео:
#: выход — сетка (GLB), а видео-оборот из неё рендерит монтаж.
IMAGE_TO_3D = "image-to-3d"

#: Управляемый словарь работ. Порядок — порядок отчёта покрытия.
FUNCTIONS: tuple[str, ...] = (
    T2V,
    I2V,
    R2V,
    V2V_EDIT,
    LIPSYNC,
    AVATAR,
    FACE_SWAP,
    DUB,
    TTS,
    VOICE_CLONE,
    MUSIC,
    SFX,
    T2I,
    IMAGE_EDIT,
    BG_REMOVE,
    UPSCALE_IMAGE,
    UPSCALE_VIDEO,
    RESTORE,
    COLORIZE,
    INTERPOLATE,
    TRANSCRIBE,
    CAPTIONS,
    TURNTABLE,
    IMAGE_TO_3D,
)

#: Работы, у которых ВЫХОД — видео: им нужна длина прогона (ролик длиннее
#: прогона — несколько прогонов) и им одалживается длина прогона семьи.
VIDEO_FUNCTIONS: frozenset[str] = frozenset(
    {
        T2V,
        I2V,
        R2V,
        V2V_EDIT,
        LIPSYNC,
        AVATAR,
        FACE_SWAP,
        UPSCALE_VIDEO,
        RESTORE,
        COLORIZE,
        INTERPOLATE,
        TURNTABLE,
    }
)

# --- каналы свидетельства ----------------------------------------------------

EVIDENCE_ID = "id"
EVIDENCE_CATEGORY = "category"
EVIDENCE_DOCS = "docs"
EVIDENCE_SHAPE = "shape"
EVIDENCE_CURATED = "curated"

#: РАБОТА, названная в идентификаторе. КОНСТАНТА-РЕШЕНИЕ: каждый образец —
#: звено (или звенья) идентификатора, сведённого к дефисам (`_звенья`), и
#: ловится только целым звеном. Работа старше режима (`MODE_RULES`): найдена
#: работа — режимы идентификатора не читаются.
#:
#: Порядок не значит ничего — работ у эндпоинта может быть несколько
#: (`dub` + `lipsync`). Апскейл раскладывается на картинку и видео отдельно
#: (`_апскейл`), потому что звено «upscale» одно на оба.
JOB_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # `latentsync` (ByteDance LatentSync, «audio-conditioned latent diffusion
    # for lip sync») — работа срослась с именем, как `i2vgen`.
    (r"lip-?sync(?:ing)?|lipsync|latentsync", (LIPSYNC,)),
    # «The avatar lip-syncs to the provided audio» — глагол в описании площадки.
    (r"lip-?syncs", (LIPSYNC,)),
    # `avatar4`, `avatar3-digital-twin` (HeyGen на fal): номер поколения
    # прилип к звену — шестой круг, `heygen-avatar4-image-to-video` читался i2v.
    (
        r"(?:ai-)?avatars?\d*|talking-?heads?|talking-?videos?|audio-to-video|a2v|s2v|speech-to-video|digital-twin"
        # «audio-driven talking/singing video from a start frame» (`hedra-
        # character-3`, страница вендора) — снимок + звук -> говорящее видео.
        r"|audio-driven",
        (AVATAR,),
    ),
    # ЗАМЕНА ЛИЦА — только лицо (восьмой круг): FaceFusion, roop и его
    # inswapper_128, `fal-ai/face-swap`. `animate-replace` (Wan Animate) меняет
    # ВЕСЬ персонаж в кадре — это правка видео (замена объекта), а не замена
    # лица: валидатор v8 (n25) получил на «вставь моё лицо» замену фигуры.
    (r"face-?swap|faceswap|inswapper(?:-\d+)?|facefusion|roop", (FACE_SWAP,)),
    (r"animate-replace|character-replace", (V2V_EDIT,)),
    (r"dub|dubbing", (DUB,)),
    (r"tts|text-to-speech|(?<!to-)speech(?!-to)", (TTS,)),
    (r"voice-?clon\w*", (VOICE_CLONE,)),
    (r"music|song", (MUSIC,)),
    (r"sound-effects?|sfx|foley|video-to-audio|v2a", (SFX,)),
    # `rmbg` (BRIA RMBG) и `background-remove` (`fal-ai/bria/background/remove`):
    # интеграция пятого круга — без них площадка числила их «image-to-image».
    (
        r"background-removal|remove-background|background-remove|bg-remov\w*|rembg|rmbg|birefnet|matting",
        (BG_REMOVE,),
    ),
    # `ddcolor`/`deoldify` — модели раскраски, названные по себе, без слова «colorize».
    (r"coloriz\w*|colouriz\w*|colorization|ddcolor|deoldify", (COLORIZE,)),
    (r"restor\w*", (RESTORE,)),
    # Шумодав, удаление смаза и артефактов сжатия — реставрация (седьмой
    # круг): `topaz/denoise/video`, `fal-ai/ltx-2.3-quality/deblur` и
    # `…/decompression` площадка числит «video-to-video», и работа
    # `restore` оставалась без единого эндпоинта с ценой. Работа `v2v-edit`
    # за ними СОХРАНЯЕТСЯ (полка площадки — правка видео; шаг правки сам
    # отбирает по под-работе, `edit_intents`), у картиночных её снимает
    # подпись (`consistent`: выход — картинка).
    (r"denois\w*|deblur\w*|decompression", (RESTORE, V2V_EDIT)),
    (r"interpolat\w*|rife", (INTERPOLATE,)),
    (r"speech-to-text|transcri\w*|diariz\w*|scribe|whisper|asr|stt", (TRANSCRIBE,)),
    (r"auto-caption\w*|subtitl\w*", (CAPTIONS,)),
    (r"turntable|orbit|360-?spin|multi-?view|novel-view", (TURNTABLE,)),
    (r"image-to-3d|img-to-3d|image23d|trellis|hunyuan-?3d|tripo(?:sr|sg)?|rodin|instantmesh|sf3d|spar3d", (IMAGE_TO_3D,)),
)

#: Звено апскейла: какая из двух работ — решает выход или звено видео/картинки.
UPSCALE_RULE = r"upscal\w*|upacaler|super-?resolution|superresolution|vsr"

#: РЕЖИМ генерации, названный в идентификаторе, — когда работы не названо.
MODE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"text-to-video|t2v|txt2vid|text2video", (T2V,)),
    # `i2vgen-xl` — «Image-to-Video GENeration»: режим, сросшийся с именем (шестой круг;
    # хаб числит его «text-to-video», а без снимка он не запускается).
    (r"image-to-video|i2v|img2vid|image2video|flf2v|i2vgen", (I2V,)),
    # «TI2V» — текст И/ИЛИ кадр в видео (`wan-2.2-ti2v-5b`): оба режима.
    (r"ti2v", (T2V, I2V)),
    (r"reference-to-video|r2v|ref2v", (R2V,)),
    (
        r"v2v(?:-edit)?|video-edit|edit-video|video-to-video|retake-video|recast|relight",
        (V2V_EDIT,),
    ),
    (r"text-to-image|t2i|txt2img|text2image", (T2I,)),
    # `style-transfer` (Stability) — перенос стиля на ДАННУЮ картинку: правка,
    # а не генерация по тексту (восьмой круг: читался t2i по «price_per_image»).
    (r"image-to-image|i2i|img2img|edit-image|image-edit|edit|inpaint|outpaint|style-transfer", (IMAGE_EDIT,)),
)

#: Категория каталога площадки -> работы, когда идентификатор молчит.
#: `text-to-audio` НЕ раскладывается: речь, музыка и шумы делят категорию, и
#: работу назовёт только путь.
CATEGORY_FUNCTIONS: dict[str, tuple[str, ...]] = {
    "text-to-video": (T2V,),
    "image-to-video": (I2V,),
    "video-to-video": (V2V_EDIT,),
    "text-to-image": (T2I,),
    "image-to-image": (IMAGE_EDIT,),
    "text-to-speech": (TTS,),
    "speech-to-text": (TRANSCRIBE,),
    "audio-to-video": (AVATAR,),
}

#: Атрибут, где записана задача весов, объявленная на хабе (HF `pipeline_tag`).
PIPELINE_ATTRIBUTE = "pipeline_tag"

#: Задача хаба -> работы. Только однозначные; «text-to-audio» (речь? музыка?
#: шумы?), «any-to-any», «text-generation» — не наши работы, и это не пропуск,
#: а ответ: такая модель на шаги студии не годится.
PIPELINE_FUNCTIONS: dict[str, tuple[str, ...]] = {
    "text-to-image": (T2I,),
    "image-to-image": (IMAGE_EDIT,),
    "text-to-video": (T2V,),
    "image-to-video": (I2V,),
    "video-to-video": (V2V_EDIT,),
    "text-to-speech": (TTS,),
    "automatic-speech-recognition": (TRANSCRIBE,),
}

#: Единица цены в имени атрибута -> работа (младший канал, `classify` шаг 5).
EVIDENCE_PRICE_UNIT = "price-unit"
PRICE_UNIT_FUNCTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"^price_per_image(?:_usd)?(?:_via_|$)", (T2I,)),
)

#: Описательные атрибуты, чьи значения — слова вендора или площадки о том, ЧТО
#: модель делает. Строки провалов и наблюдений сюда нарочно не входят: «лицо
#: плывёт при липсинке» пишут и о видеомоделях — так `hunyuanvideo-i2v`
#: оказывалась кандидатом на липсинк.
DOC_ATTRIBUTES: frozenset[str] = frozenset(
    {"positioning", "summary_line", "best_for", "model_id", "availability"}
)

#: Ступени источника, чьим описательным строкам верится как каналу работы.
DOC_TIERS: frozenset[str] = frozenset({"vendor", "portal"})

#: Режимы, которые читаются из ИМЕНИ атрибута документации (`ratio_enum_
#: image_to_video`). Правка и картинка сюда не входят: `image_edit_*` и
#: `*_edit_*` пишут и о генераторах (как правят сгенерированное).
ATTRIBUTE_MODES: frozenset[str] = frozenset({T2V, I2V, R2V})

#: ОБЪЯВЛЕННАЯ ФОРМА -> работа: (обязательные входы, выход). Только
#: однозначные сочетания; «текст -> аудио» (речь? музыка? шумы?) — нет.
SHAPE_RULES: dict[tuple[frozenset[str], str], str] = {
    (frozenset({"текст"}), "видео"): T2V,
    (frozenset({"изображение"}), "видео"): I2V,
    (frozenset({"изображение", "текст"}), "видео"): I2V,
    (frozenset({"аудио", "видео"}), "видео"): LIPSYNC,
    (frozenset({"аудио", "изображение"}), "видео"): AVATAR,
    (frozenset({"текст"}), "изображение"): T2I,
    (frozenset({"изображение", "текст"}), "изображение"): IMAGE_EDIT,
}

#: ПОДПИСЬ РАБОТЫ (шестой круг): (виды входа, которые работа вправе ТРЕБОВАТЬ;
#: виды выхода, один из которых она обязана ОТДАВАТЬ). Работа, которой
#: объявленная схема противоречит (`consistent`), снимается: модель, отдающая
#: картинку, не делает t2v; модель, без звука не запускающаяся, — не i2v.
#:
#: ПРОТИВОРЕЧИЕ — ТОЛЬКО ПО ОБЯЗАТЕЛЬНЫМ ВХОДАМ И ПО ВЫХОДУ. Список
#: ПРИНИМАЕМЫХ входов читатель схемы собирает по именам полей и бывает неполон
#: (`veo-3.1-flf2v`: поля кадров не узнаны, «принимает текст»), поэтому
#: отсутствие вида среди принимаемых противоречием не считается. Пусто — вид
#: не проверяется. КОНСТАНТА-РЕШЕНИЕ: сторожит свойство-тест по всему реестру.
_ВИДЕО, _КАРТИНКА, _ЗВУК, _ТЕКСТ = "видео", "изображение", "аудио", "текст"
_3D = "3d-модель"
SIGNATURES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    T2V: (frozenset({_ТЕКСТ}), frozenset({_ВИДЕО})),
    I2V: (frozenset({_КАРТИНКА, _ТЕКСТ}), frozenset({_ВИДЕО})),
    R2V: (frozenset({_КАРТИНКА, _ВИДЕО, _ТЕКСТ, _ЗВУК}), frozenset({_ВИДЕО})),
    V2V_EDIT: (frozenset({_ВИДЕО, _КАРТИНКА, _ТЕКСТ}), frozenset({_ВИДЕО})),
    LIPSYNC: (frozenset({_ЗВУК, _ВИДЕО, _КАРТИНКА, _ТЕКСТ}), frozenset({_ВИДЕО})),
    AVATAR: (frozenset({_ЗВУК, _КАРТИНКА, _ТЕКСТ, _ВИДЕО}), frozenset({_ВИДЕО})),
    FACE_SWAP: (frozenset({_КАРТИНКА, _ВИДЕО, _ТЕКСТ}), frozenset({_ВИДЕО, _КАРТИНКА})),
    DUB: (frozenset({_ВИДЕО, _ЗВУК, _ТЕКСТ}), frozenset({_ВИДЕО, _ЗВУК})),
    TTS: (frozenset({_ТЕКСТ, _ЗВУК}), frozenset({_ЗВУК})),
    VOICE_CLONE: (frozenset({_ЗВУК, _ТЕКСТ}), frozenset({_ЗВУК, _ТЕКСТ})),
    MUSIC: (frozenset({_ТЕКСТ, _ЗВУК}), frozenset({_ЗВУК})),
    SFX: (frozenset({_ТЕКСТ, _ВИДЕО}), frozenset({_ЗВУК, _ВИДЕО})),
    T2I: (frozenset({_ТЕКСТ}), frozenset({_КАРТИНКА})),
    IMAGE_EDIT: (frozenset({_КАРТИНКА, _ТЕКСТ}), frozenset({_КАРТИНКА})),
    BG_REMOVE: (frozenset({_КАРТИНКА, _ВИДЕО}), frozenset({_КАРТИНКА, _ВИДЕО})),
    UPSCALE_IMAGE: (frozenset({_КАРТИНКА, _ТЕКСТ}), frozenset({_КАРТИНКА})),
    UPSCALE_VIDEO: (frozenset({_ВИДЕО, _ТЕКСТ}), frozenset({_ВИДЕО})),
    RESTORE: (frozenset({_КАРТИНКА, _ВИДЕО, _ТЕКСТ}), frozenset({_КАРТИНКА, _ВИДЕО})),
    COLORIZE: (frozenset({_КАРТИНКА, _ВИДЕО, _ТЕКСТ}), frozenset({_КАРТИНКА, _ВИДЕО})),
    INTERPOLATE: (frozenset({_КАРТИНКА, _ВИДЕО}), frozenset({_ВИДЕО})),
    TRANSCRIBE: (frozenset({_ЗВУК, _ВИДЕО}), frozenset({_ТЕКСТ})),
    CAPTIONS: (frozenset({_ВИДЕО, _ЗВУК, _ТЕКСТ}), frozenset({_ВИДЕО})),
    TURNTABLE: (frozenset({_КАРТИНКА, _ТЕКСТ}), frozenset({_ВИДЕО})),
    IMAGE_TO_3D: (frozenset({_КАРТИНКА, _ТЕКСТ}), frozenset({_3D})),
}


def consistent(function: str, required: Iterable[str], outputs: Iterable[str]) -> bool:
    """Не противоречит ли работа объявленной схеме: обязательные входы и выход."""
    нужны, выходы = set(required), set(outputs)
    вправе, отдаёт = SIGNATURES.get(function, (frozenset(), frozenset()))
    if нужны and вправе and not нужны <= вправе:
        return False
    return not (выходы and отдаёт and not (выходы & отдаёт))


#: Работы, чья подпись — ОБЯЗАТЕЛЬНЫЙ звук на входе видеомодели: форма схемы
#: старше категории площадки и режима в имени (см. `classify`, шаг 1б).
AUDIO_DRIVEN: frozenset[str] = frozenset({LIPSYNC, AVATAR})

#: Режимы генерации, которые узел семьи СО СВОИМ маршрутом (цена у вендора:
#: `seedance-2.0` у Runway) берёт у своих вариантов, если о себе не говорит
#: ничего. Только режимы: работа варианта (`minimax-h3-latent-upscaler`) —
#: свойство варианта, а не семьи.
FAMILY_MODES: frozenset[str] = frozenset({T2V, I2V, R2V, T2I, IMAGE_EDIT})
EVIDENCE_VARIANTS = "variants"

#: КУРИРОВАННЫЕ РАБОТЫ — короткая таблица для моделей, о чьей работе правила
#: молчат или читают категорию площадки шире работы, а сама работа записана в
#: базе словами, которых правила не разбирают. Строка ПЕРЕКРЫВАЕТ каналы
#: (`classify`, шаг 0): она — прочитанное человеком, а не выведенное. Каждая —
#: (работы, почему, источник), и источник — адрес, УЖЕ лежащий в базе фактов
#: под этой моделью (сторожит тест: строка без своего адреса в базе — выдумка).
CURATED: dict[str, tuple[tuple[str, ...], str, str]] = {
    "veo-3.1": (
        (T2V, I2V),
        "Gemini API Veo page: 8-second videos from a text prompt, and image-to-video from a start frame",
        "https://ai.google.dev/gemini-api/docs/veo",
    ),
    "sora-2": (
        (T2V, I2V),
        "OpenAI video-generation guide: video from a text prompt; input_reference acts as the first frame",
        "https://platform.openai.com/docs/guides/video-generation.md",
    ),
    "sora-2-pro": (
        (T2V, I2V),
        "OpenAI video-generation guide: sora-2-pro is the higher-quality model on the same Videos API",
        "https://platform.openai.com/docs/guides/video-generation.md",
    ),
    "infinitalk": (
        (AVATAR, LIPSYNC),
        "InfiniteTalk model card (accepts_inputs row): video + audio (dubbing), or image + audio",
        "https://huggingface.co/MeiGen-AI/InfiniteTalk",
    ),
    "wav2lip": (
        (LIPSYNC,),
        "LatentSync paper evaluates Wav2Lip as a lip-sync baseline on existing face video",
        "https://arxiv.org/html/2412.09262v2",
    ),
    "xtts-v2": (
        (TTS, VOICE_CLONE),
        "coqui/XTTS-v2 model card: a voice generation model that clones a voice from a short clip",
        "https://huggingface.co/coqui/XTTS-v2",
    ),
    "bark": (
        (TTS,),
        "suno/bark model card: a transformer text-to-audio model that speaks the prompt",
        "https://huggingface.co/suno/bark",
    ),
    # Интеграция пятого круга: FILM — интерполяция кадров, но имя работы не
    # называет, а площадка числит его «image-to-image» / «video-to-video».
    "film": (
        (INTERPOLATE,),
        "google-research/frame-interpolation (licence row): FILM is built for frame interpolation with large motion",
        "https://raw.githubusercontent.com/google-research/frame-interpolation/main/LICENSE",
    ),
    "film-video": (
        (INTERPOLATE,),
        "fal.ai lists fal-ai/film/video: the FILM frame-interpolation model applied to a video",
        "https://fal.ai/models/fal-ai/film/video",
    ),
    # Седьмой круг (валидатор v7, «промахи реестра»): заказываемые узлы без
    # работы. Имена ElevenLabs и Google работу не называют.
    "eleven_flash_v2": (
        (TTS,),
        "ElevenLabs models page: Flash v2 — text-to-speech, English only, ~30 minutes of audio per request",
        "https://elevenlabs.io/docs/models.md",
    ),
    "eleven_flash_v2_5": (
        (TTS,),
        "ElevenLabs models page: Flash v2.5 — low-latency text-to-speech (~75 ms), 40,000 characters per request",
        "https://elevenlabs.io/docs/models.md",
    ),
    "chirp-3-hd": (
        (TTS,),
        "Google Cloud Text-to-Speech pricing: Chirp 3: HD voices, billed per character of synthesised text",
        "https://cloud.google.com/text-to-speech/pricing",
    ),
    # FLUX.1 Kontext [max] multi — правка картинки по НЕСКОЛЬКИМ опорным
    # снимкам (`image_urls`); категории у эндпоинта на площадке нет.
    "flux-1-kontext-max-multi": (
        (IMAGE_EDIT,),
        "fal.ai OpenAPI of fal-ai/flux-pro/kontext/max/multi: image edit from several reference images "
        "(image_urls array) — multi-reference",
        "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=fal-ai/flux-pro/kontext/max/multi",
    ),
    # Восьмой круг (валидатор v8, реестр 40 строк): заказываемые без работы.
    "facefusion": (
        (FACE_SWAP,),
        "FaceFusion README: face manipulation platform — face swap on video and images, self-hosted CLI/UI",
        "https://raw.githubusercontent.com/facefusion/facefusion/master/README.md",
    ),
    "gpt-image-1": (
        (T2I, IMAGE_EDIT),
        "OpenAI image-generation guide: generates images from a prompt and edits images (masked edits)",
        "https://platform.openai.com/docs/guides/image-generation",
    ),
    "hallo": (
        (AVATAR,),
        "Hallo README (Fudan): audio-driven portrait image animation — one portrait + speech audio -> talking video",
        "https://raw.githubusercontent.com/fudan-generative-vision/hallo/main/README.md",
    ),
    "float": (
        (AVATAR,),
        "FLOAT README (DeepBrain AI): audio-driven talking portrait video from a single image",
        "https://raw.githubusercontent.com/deepbrainai-research/float/main/README.md",
    ),
    # Восьмой круг (агент рецептов): MMAudio — звук по видео (foley), а схема
    # площадки числит его «video-to-video» и отдаёт ВИДЕО со звуком.
    "mmaudio-v2": (
        (SFX,),
        "fal OpenAPI of fal-ai/mmaudio-v2: requires video_url and prompt — 'The URL of the video to generate "
        "the audio for' — and returns the video with the generated audio (video-to-audio / foley)",
        "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=fal-ai/mmaudio-v2",
    ),
    "image-apps-v2-headshot-photo": (
        (IMAGE_EDIT,),
        "fal OpenAPI of fal-ai/image-apps-v2/headshot-photo: requires one image, returns an image (a headshot "
        "made from the customer's photo)",
        "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=fal-ai/image-apps-v2/headshot-photo",
    ),
    "seedvr2-3b": (
        (UPSCALE_VIDEO, UPSCALE_IMAGE, RESTORE),
        "SeedVR2-3B README: one-step diffusion video restoration and super-resolution",
        "https://huggingface.co/ByteDance-Seed/SeedVR2-3B/raw/main/README.md",
    ),
}

# --- маршруты -------------------------------------------------------------------

#: Хосты, адрес которых несёт ЗАКАЗЫВАЕМЫЙ идентификатор эндпоинта.
ROUTE_HOSTS: dict[str, str] = {
    "fal.ai": "fal",
    "fal.run": "fal",
    "replicate.com": "replicate",
}
#: Атрибуты, где записано, ГДЕ вендор обслуживает запросы (`Endpoint.hosting`).
HOSTING_ATTRIBUTES: frozenset[str] = frozenset(
    {"serving_regions", "data_residency", "hosting_regions", "processing_regions", "data_location"}
)
#: МЕСТА ОБСЛУЖИВАНИЯ -> юрисдикция (девятый круг). Строки хостинга называют
#: не страны, а ГОРОДА и регионы облака («Global: Beijing, Tokyo, Frankfurt,
#: Virginia, Hong Kong»): `pipeline.jurisdictions_in` (имена стран для
#: лицензий) не находил в такой строке ничего, и записанный хостинг Wan 3.0
#: читался как «не записан». КОНСТАНТА-ТАБЛИЦА, список закрытый: незнакомое
#: место не распознаётся (и юрисдикцией не становится).
HOSTING_PLACES: dict[str, str] = {
    "CN": r"\bbeijing\b|\bshanghai\b|\bhangzhou\b|\bshenzhen\b|\bguangzhou\b|\bhong kong\b|\bcn-[a-z]",
    "SG": r"\bsingapore\b",
    "JP": r"\btokyo\b|\bosaka\b",
    "KR": r"\bseoul\b",
    "IN": r"\bmumbai\b",
    "UK": r"\blondon\b",
    "EU": r"\bfrankfurt\b|\bamsterdam\b|\bnetherlands\b|\bireland\b|\bdublin\b|\bparis\b|\bmilan\b"
    r"|\bstockholm\b|\beu-[a-z]",
    "US": r"\bvirginia\b|\boregon\b|\bohio\b|\bcalifornia\b|\biowa\b|\bus-(?:east|west|central)",
}
#: Как строка хостинга говорит, что регион можно ЗАКРЕПИТЬ за собой («api.us.…
#: pins USA», «data residency in the EU»): то, что после этих слов, — регион,
#: в котором запрос остаётся.
HOSTING_PIN = re.compile(r"\bpins?\s+([^;,.()]+)|data residency (?:in|for) (?:the )?([^;,.()]+)", re.I)


def hosting_of(text: str) -> tuple[str, ...]:
    """Юрисдикции, где строка хостинга обслуживает запросы: страны и места (`HOSTING_PLACES`)."""
    from studio import pipeline as pl  # как в `build`: модуль импортируется без pipeline

    found = set(pl.jurisdictions_in(text))
    found |= {j for j, r in HOSTING_PLACES.items() if re.search(r, str(text or ""), re.I)}
    return tuple(sorted(found))


def hosting_pinned_of(text: str) -> tuple[str, ...]:
    """Юрисдикции, за которыми строка хостинга позволяет ЗАКРЕПИТЬ запрос (`HOSTING_PIN`)."""
    found: set[str] = set()
    for m in HOSTING_PIN.finditer(str(text or "")):
        found |= set(hosting_of(m.group(1) or m.group(2) or ""))
    return tuple(sorted(found))

#: Хосты страниц весов: маршрут «запустить у себя».
WEIGHTS_HOSTS: tuple[str, ...] = ("huggingface.co", "github.com", "raw.githubusercontent.com")
ROUTE_SELF_HOST = "self-host"

_AVAILABILITY = re.compile(r"\bon ([\w.]+) as (\S+) \(([^)]*)\)")
_FAL_PATH = re.compile(r"/models/([\w.-]+/[\w./-]+?)/?(?:$|[?#])")


@dataclass(frozen=True)
class Endpoint:
    """Один узел реестра: модель базы как вещь, которую можно (или нельзя) заказать."""

    model: str
    key: str
    family: str = ""
    #: Варианты этого узла в базе (непусто — узел семьи).
    variants: tuple[str, ...] = ()
    #: Идентификаторы на площадках (`fal-ai/kling-video/v3/standard/text-to-video`).
    ids: tuple[str, ...] = ()
    #: Кто продаёт или где запускать: fal, replicate, маршруты строк цены, self-host.
    routes: tuple[str, ...] = ()
    #: МАРШРУТ = (кто продаёт, под каким идентификатором): `("fal", "fal-ai/
    #: rife/video")`, `("elevenlabs", "eleven_v3")`, `("self-host", "<страница
    #: весов>")`. Заказываемый узел ⇔ маршрутов хотя бы один (шестой круг).
    route_ids: tuple[tuple[str, str], ...] = ()
    orderable: bool = True
    why_not_orderable: str = ""
    #: Веса открыты (страница весов с лицензией): узел запускается на СВОЁМ GPU,
    #: даже если через API его не купить — для плана «свой GPU» это маршрут.
    self_hostable: bool = False
    functions: tuple[str, ...] = ()
    #: Каким каналом найдены работы (`EVIDENCE_*`) и чем — словами.
    evidence: str = ""
    evidence_note: str = ""
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    #: Единицы цены (`pricing.PER`), разобранные из строк цены модели.
    price_units: tuple[str, ...] = ()
    priced: bool = False
    #: Предел одного прогона, секунды; откуда он (своя запись, семья).
    run_s: float | None = None
    run_basis: str = ""
    resolutions: tuple[str, ...] = ()
    native_audio: bool | None = None
    licence: str = ""
    #: Территории, которые ЛИЦЕНЗИЯ исключает (`pipeline.licence_reservations`).
    territories: tuple[str, ...] = ()
    #: Где вендор ОБСЛУЖИВАЕТ запросы (хостинг, регионы данных) — юрисдикции из
    #: строк `HOSTING_ATTRIBUTES`; пусто — не записано. Седьмой круг
    #: (валидатор v7): `spec.jurisdiction` судил только лицензию, а о том, где
    #: модель запущена, молчал — без единой строки об этом.
    hosting: tuple[str, ...] = ()
    hosting_note: str = ""
    #: Юрисдикции, за которыми запрос можно закрепить (`HOSTING_PIN`); пусто —
    #: строка хостинга закрепления не называет.
    hosting_pinned: tuple[str, ...] = ()
    open_weights: str = ""
    vram_gb: float | None = None
    #: ПОМЕТКИ ОТБОРА (`FLAGS`): мёрж сообщества, NSFW, стилевой LoRA. Узел в
    #: базе остаётся, но в `Registry.by_function` (откуда плановщик и
    #: `find_models` берут кандидатов) не попадает — только в `flagged`.
    flags: tuple[str, ...] = ()

    def does(self, function: str) -> bool:
        return function in self.functions


@dataclass
class Registry:
    """Все узлы и индекс «работа -> заказываемые узлы»."""

    by_key: dict[str, Endpoint] = field(default_factory=dict)
    by_function: dict[str, list[Endpoint]] = field(default_factory=dict)
    #: Узлы с пометками (`Endpoint.flags`): та же работа, но кандидатами их
    #: делает только явная просьба заказчика (`requested_flags`).
    flagged: dict[str, list[Endpoint]] = field(default_factory=dict)

    def get(self, model: str) -> Endpoint | None:
        return self.by_key.get(fold(model))

    def orderable_for(self, function: str) -> list[Endpoint]:
        return [e for e in self.by_function.get(function, []) if e.orderable]

    def all_for(self, function: str) -> list[Endpoint]:
        """Все узлы работы, помеченные (`flagged`) тоже — для отчёта покрытия."""
        return [*self.by_function.get(function, []), *self.flagged.get(function, [])]


# --- разбор ---------------------------------------------------------------------


def _звенья(текст: str) -> str:
    """Идентификатор или фраза -> звенья через дефис: `fal-ai/kling-video/v3` -> `fal-ai-kling-video-v3`."""
    низ = str(текст or "").lower()
    низ = re.sub(r"[\s/_.:,;()\[\]]+", "-", низ)
    return re.sub(r"-{2,}", "-", низ).strip("-")


def _звено(образец: str, звенья: str) -> bool:
    return re.search(rf"(?:^|-)(?:{образец})(?:-|$)", звенья) is not None


def _работы_имени(
    звенья: str, выходы: Iterable[str] = (), категория: str = ""
) -> tuple[set[str], set[str]]:
    """(работы, режимы) из звеньев идентификатора."""
    работы: set[str] = set()
    for образец, что in JOB_RULES:
        if _звено(образец, звенья):
            работы.update(что)
    if _звено(UPSCALE_RULE, звенья):
        работы.update(_апскейл(звенья, выходы, категория))
    режимы: set[str] = set()
    for образец, что in MODE_RULES:
        if _звено(образец, звенья):
            режимы.update(что)
    # «edit» у ВИДЕО — правка видео, а не картинки.
    if IMAGE_EDIT in режимы and (_звено("video", звенья) or "видео" in set(выходы)):
        режимы.discard(IMAGE_EDIT)
        режимы.add(V2V_EDIT)
    return работы, режимы


def _апскейл(звенья: str, выходы: Iterable[str], категория: str) -> set[str]:
    выходы = set(выходы)
    if _звено("video|vsr", звенья) or "видео" in выходы or категория == "video-to-video":
        return {UPSCALE_VIDEO}
    if (
        _звено("image|img|photo", звенья)
        or "изображение" in выходы
        or категория == "image-to-image"
    ):
        return {UPSCALE_IMAGE}
    return {UPSCALE_VIDEO, UPSCALE_IMAGE}


def endpoint_ids(rows: Sequence[Fact]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(идентификаторы на площадках, категории каталога) из строк модели."""
    ids: list[str] = []
    категории: list[str] = []
    for f in rows:
        if f.attribute == "availability":
            м = _AVAILABILITY.search(str(f.value))
            if м:
                ids.append(м.group(2))
                категории.append(м.group(3).strip().lower())
        url = f.source_url or ""
        разбор = urlparse(url)
        хост = (разбор.hostname or "").lower()
        if not any(хост == h or хост.endswith("." + h) for h in ROUTE_HOSTS):
            continue
        запрос = parse_qs(разбор.query).get("endpoint_id")
        if запрос:
            ids.append(запрос[0])
            continue
        путь = _FAL_PATH.search(разбор.path + "?")
        if путь:
            ids.append(путь.group(1))
        elif "replicate.com" in хост:
            части = [ч for ч in разбор.path.split("/") if ч]
            if len(части) >= 2:
                ids.append("/".join(части[:2]))
    return tuple(dict.fromkeys(ids)), tuple(dict.fromkeys(категории))


def _схема_эндпоинта(url: str) -> str:
    """`...openapi.json?endpoint_id=<id>` -> id; иначе пусто."""
    запрос = parse_qs(urlparse(url or "").query).get("endpoint_id")
    return запрос[0] if запрос else ""


def own_routes(
    model: str,
    rows: Sequence[Fact],
    *,
    family: bool,
    price_routes: Sequence[str] = (),
    vendor_hosts: Mapping[str, str] | None = None,
    weights_page: str = "",
) -> tuple[tuple[str, str], ...]:
    """Маршруты узла: (кто продаёт, идентификатор). Пусто — заказать не у кого.

    СВОИ идентификаторы — строка каталога («on fal.ai as <id>»), адрес схемы
    (`openapi.json?endpoint_id=<id>`) и адрес страницы, с которой снята ЦЕНА.
    Адрес страницы-источника без цены своим считается только у узла, у
    которого нет вариантов: у семьи `kling-3.0` лежат строки со страниц
    motion-control эндпоинтов — это соседи, а не её заказ.

    Без идентификатора площадки маршрут даёт: строка цены (маршрут строки,
    идентификатор — имя модели у продавца); страница API самого вендора
    (`vendor_hosts`, не у семьи); страница весов с лицензией (`self-host`).
    """
    vendor_hosts = vendor_hosts or {}
    маршруты: list[tuple[str, str]] = []

    def площадка(url: str) -> str:
        хост = (urlparse(url or "").hostname or "").lower()
        return next(
            (имя for h, имя in ROUTE_HOSTS.items() if хост == h or хост.endswith("." + h)), ""
        )

    for f in rows:
        if f.attribute == "availability":
            м = _AVAILABILITY.search(str(f.value))
            if м:
                имя = ROUTE_HOSTS.get(м.group(1).lower(), м.group(1).lower())
                маршруты.append((имя, м.group(2)))
                continue
        кто = площадка(f.source_url or "")
        if not кто:
            continue
        ид = _схема_эндпоинта(f.source_url or "")
        if not ид and (not family or "price" in f.attribute):
            ид = next(iter(endpoint_ids([f])[0]), "")
        # У СЕМЬИ схема соседа — не её заказ: под `kling-3.0` лежит схема
        # `…/v3/standard/motion-control`, под `minimax-speech-02` — схема
        # `…/minimax/voice-clone`. Свой — идентификатор, свёрнутый в имя узла
        # (`fal-ai/hunyuan-video` у `hunyuan-video`).
        if ид and family and "price" not in f.attribute and fold(ид) != fold(model):
            continue
        if ид:
            маршруты.append((кто, ид))
    продавцы = {кто for кто, _ in маршруты}
    for кто in price_routes:
        if кто not in продавцы:
            маршруты.append((кто, model))
            продавцы.add(кто)
    if not family:
        for f in rows:
            if f.tier != "vendor":
                continue
            хост = (urlparse(f.source_url or "").hostname or "").lower()
            кто = next(
                (имя for h, имя in vendor_hosts.items() if хост == h or хост.endswith("." + h)), ""
            )
            if кто and кто not in продавцы:
                маршруты.append((кто, model))
                продавцы.add(кто)
    if weights_page:
        маршруты.append((ROUTE_SELF_HOST, weights_page))
    return tuple(dict.fromkeys(маршруты))


def _виды(rows: Sequence[Fact], атрибут: str) -> set[str]:
    виды: set[str] = set()
    for f in rows:
        if f.attribute == атрибут:
            виды |= {ч.strip() for ч in str(f.value).split(",") if ч.strip()}
    return виды


def classify(
    model: str,
    rows: Sequence[Fact],
    curated: Mapping[str, tuple[tuple[str, ...], str, str]] | None = None,
) -> tuple[tuple[str, ...], str, str]:
    """Работы модели по её строкам: (работы, канал, чем найдено). Пусто — не установлено.

    ПОСЛЕДНЕЕ СЛОВО — ЗА ОБЪЯВЛЕННОЙ СХЕМОЙ (шестой круг): работа, которой
    схема противоречит (`consistent`), снимается, и это сказано в ноте. Сняты
    все — работы нет, а не «работа по имени вопреки схеме».
    """
    входы = _виды(rows, "requires_inputs")
    выходы = _виды(rows, "produces_outputs")
    подпись = f"схема: {', '.join(sorted(входы)) or '—'} -> {', '.join(sorted(выходы)) or '—'}"
    отвергнуто: list[str] = []
    for работы, канал, нота in _каналы(model, rows, curated):
        годные = tuple(ф for ф in работы if consistent(ф, входы, выходы))
        снятые = ", ".join(ф for ф in работы if ф not in годные)
        if not годные:
            отвергнуто.append(f"{канал}: {снятые}")
            continue
        хвост = f"; снято схемой: {снятые} ({подпись})" if снятые else ""
        if отвергнуто:
            хвост += f"; отвергнуто схемой: {'; '.join(отвергнуто)} ({подпись})"
        return годные, канал, нота + хвост
    if отвергнуто:
        return (), "", f"{'; '.join(отвергнуто)} — противоречит схеме ({подпись})"
    return (), "", ""


def _каналы(
    model: str,
    rows: Sequence[Fact],
    curated: Mapping[str, tuple[tuple[str, ...], str, str]] | None = None,
) -> Iterator[tuple[tuple[str, ...], str, str]]:
    """Ответы каналов по старшинству: (работы, канал, чем найдено).

    Генератор, а не одно значение (шестой круг): ответ, которому противоречит
    схема, не обрывает разбор — `classify` берёт следующий канал. Так
    `infinitalk-single-text` (площадка: «text-to-video», схема: снимок +
    текст) находит работу в описании площадки — говорящий аватар.
    """
    curated = CURATED if curated is None else curated
    ids, категории = endpoint_ids(rows)
    выходы = _виды(rows, "produces_outputs")
    категория = категории[0] if категории else ""
    # 0. Курированная строка — прочитанное человеком — старше выведенного.
    имя_курированное = next((к for к in curated if fold(к) == fold(model)), "")
    if имя_курированное:
        что, почему, источник = curated[имя_курированное]
        yield _порядок(set(что)), EVIDENCE_CURATED, f"{почему} ({источник})"
    # 1. Идентификаторы: имя в базе и адреса площадки.
    работы: set[str] = set()
    режимы: set[str] = set()
    #: Режимы, названные ИДЕНТИФИКАТОРОМ ПЛОЩАДКИ (не именем в базе): это имя
    #: самого заказываемого эндпоинта, и оно не могло прийти из семьи.
    режимы_площадки: set[str] = set()
    откуда: list[str] = []
    for ид in (model, *ids):
        р, м = _работы_имени(_звенья(ид), выходы, категория)
        if р or м:
            откуда.append(ид)
        работы |= р
        режимы |= м
        if ид in ids:
            режимы_площадки |= м
    if работы:
        yield _порядок(работы), EVIDENCE_ID, "; ".join(откуда)
    # 1б. ОБЯЗАТЕЛЬНЫЙ ЗВУК НА ВХОДЕ ВИДЕОМОДЕЛИ — подпись работы, а не режим:
    # `omnihuman-1.5` площадка числит «image-to-video», `latentsync` —
    # «video-to-video», а схема обоих требует аудио. Модель, без звука не
    # запускающаяся, двигает губы под звук (`AUDIO_DRIVEN`).
    нужны = _виды(rows, "requires_inputs")
    for выход in sorted(выходы):
        # Текст рядом со звуком — подсказка к движению, а не другая работа
        # (`infinitalk` требует аудио, изображение и текст).
        работа = SHAPE_RULES.get((frozenset(нужны - {"текст"}), выход))
        if работа in AUDIO_DRIVEN:
            yield (работа,), EVIDENCE_SHAPE, f"requires {', '.join(sorted(нужны))} -> {выход}"
    # 2. Категория каталога (если она есть) уточняет и дополняет режимы имени.
    из_категории = {ф for к in категории for ф in CATEGORY_FUNCTIONS.get(к, ())}
    if режимы:
        if из_категории and режимы_площадки and not (режимы_площадки & из_категории):
            # ПУТЬ ЭНДПОИНТА УЖЕ КАТЕГОРИИ (шестой круг): `bytedance/seedance-2.5/
            # reference-to-video` площадка числит «image-to-video», а
            # `wan/v2.6/reference-to-video/flash` — «video-to-video». Категория
            # — полка каталога, путь — имя этого эндпоинта: верится пути.
            yield (
                _порядок(режимы_площадки),
                EVIDENCE_ID,
                f"{', '.join(i for i in ids if _работы_имени(_звенья(i), выходы, категория)[1])}"
                f" (категория площадки: {категория})",
            )
        if из_категории and not (режимы & из_категории):
            # Категория площадки и звено имени спорят — верится площадке, которая
            # продаёт ЭТОТ эндпоинт: имя могло прийти из семьи.
            yield (
                _порядок(из_категории),
                EVIDENCE_CATEGORY,
                f"{категория} (имя: {', '.join(откуда)})",
            )
        yield _порядок(режимы), EVIDENCE_ID, "; ".join(откуда)
    if из_категории:
        yield _порядок(из_категории), EVIDENCE_CATEGORY, ", ".join(категории)
    # 2б. Задача, которую автор весов ОБЪЯВИЛ на хабе (`pipeline_tag` HF):
    # та же полка каталога, только каталог — хаб весов, а не площадка API.
    for f in rows:
        if f.attribute == PIPELINE_ATTRIBUTE and f.tier in DOC_TIERS:
            что = PIPELINE_FUNCTIONS.get(str(f.value).strip().lower(), ())
            if что:
                yield _порядок(что), EVIDENCE_CATEGORY, f"{PIPELINE_ATTRIBUTE} = {f.value} ({f.source_url})"
    # 3. Описательные строки вендора/площадки — значение, а у строк схемы и
    # документации ещё и ИМЯ атрибута (`ratio_enum_text_to_video`,
    # `prompt_rule_i2v`: вендор записал предел ДЛЯ РЕЖИМА — режим есть).
    for f in rows:
        if f.tier in DOC_TIERS and f.attribute in DOC_ATTRIBUTES and f.attribute != "availability":
            р, м = _работы_имени(_звенья(f.value), выходы, "")
            if р or м:
                yield (
                    _порядок(р or м),
                    EVIDENCE_DOCS,
                    f"{f.attribute} = «{str(f.value)[:80]}» ({f.source_url})",
                )
    по_именам: set[str] = set()
    имена: list[str] = []
    for f in rows:
        if f.tier in DOC_TIERS:
            _, м = _работы_имени(_звенья(f.attribute), выходы, "")
            м &= ATTRIBUTE_MODES
            if м:
                по_именам |= м
                имена.append(f.attribute)
    if по_именам:
        yield _порядок(по_именам), EVIDENCE_DOCS, "атрибуты: " + ", ".join(dict.fromkeys(имена))
    # 4. Объявленная форма: обязательные входы; без них — принимаемые, и тогда
    # каждый принимаемый вид картинки или текста — свой режим (`hunyuanvideo-1.5`
    # принимает текст и изображение — делает и t2v, и i2v).
    for выход in sorted(выходы):
        работа = SHAPE_RULES.get((frozenset(нужны), выход))
        if работа:
            yield (работа,), EVIDENCE_SHAPE, f"requires {', '.join(sorted(нужны))} -> {выход}"
    берёт = _виды(rows, "accepts_inputs")
    if not нужны and берёт and not (берёт & {"аудио", "видео"}):
        режимы = {
            SHAPE_RULES[(frozenset({вид}), выход)]
            for вид in берёт
            for выход in выходы
            if (frozenset({вид}), выход) in SHAPE_RULES
        }
        if режимы:
            yield (
                _порядок(режимы),
                EVIDENCE_SHAPE,
                f"accepts {', '.join(sorted(берёт))} -> {', '.join(sorted(выходы))}",
            )
    # 5. ЕДИНИЦА ЦЕНЫ В ИМЕНИ АТРИБУТА (шестой круг): «price_per_image» —
    # продавец берёт деньги за КАРТИНКУ на выходе. Картиночная модель, о
    # которой больше не сказано ничего, рисует по тексту (`gen4_image`,
    # `gemini-2.5-flash-image`, `imagen-4.0-ultra`): младший канал.
    for f in rows:
        for образец, что in PRICE_UNIT_FUNCTIONS:
            if re.match(образец, f.attribute):
                yield что, EVIDENCE_PRICE_UNIT, f"{f.attribute} = {str(f.value)[:40]} ({f.source_url})"


def _порядок(работы: Iterable[str]) -> tuple[str, ...]:
    return tuple(ф for ф in FUNCTIONS if ф in set(работы))


# --- сборка ---------------------------------------------------------------------


def _отпечаток(facts: Sequence[Fact]) -> str:
    h = hashlib.sha1()
    for f in facts:
        h.update(
            f"{f.model}\x1f{f.attribute}\x1f{f.value}\x1f{f.source_url}\x1e".encode(
                "utf-8", "replace"
            )
        )
    return h.hexdigest()


_КЭШ: dict[str, Registry] = {}
#: Сколько разных баз держит кэш (живая плюс тестовые): больше — сброс.
CACHE_LIMIT = 8


def build(facts: Sequence[Fact]) -> Registry:
    """Реестр из строк базы. Одна база — один реестр (кэш по отпечатку строк)."""
    ключ = _отпечаток(facts)
    if ключ in _КЭШ:
        return _КЭШ[ключ]
    реестр = _собрать(facts)
    if len(_КЭШ) >= CACHE_LIMIT:
        _КЭШ.clear()
    _КЭШ[ключ] = реестр
    return реестр


def _собрать(facts: Sequence[Fact]) -> Registry:
    # Ленивый импорт: плановщик импортирует этот модуль; здесь — его разборщики
    # цены, маршрута и длины прогона (Е1: второго разборщика не заводится).
    from studio import hardneed as hn
    from studio import pipeline as pl
    from studio import planner as pn
    from studio import pricing

    по_ключу: dict[str, list[Fact]] = {}
    написание: dict[str, str] = {}
    for f in facts:
        if not pn._is_model(f.model):
            continue
        к = fold(f.model)
        по_ключу.setdefault(к, []).append(f)
        написание.setdefault(к, f.model)
    известные = sorted({f.model for f in facts})
    группы = modelnames.group(известные)
    семья_у: dict[str, str] = {}
    варианты: dict[str, list[str]] = {}
    for к, имя in написание.items():
        родители = modelnames.parent(имя, известные, группы)
        if родители:
            ключ_семьи = fold(родители[0])
            if ключ_семьи in по_ключу and ключ_семьи != к:
                семья_у[к] = ключ_семьи
                варианты.setdefault(ключ_семьи, []).append(имя)

    реестр = Registry()
    for к, rows in по_ключу.items():
        имя = написание[к]
        цены = pn.price_facts(rows)
        ставки = pricing.compute_twins(
            [(pn.маршрут(f)[0], pricing.rates(f.value, f.attribute)) for f in цены]
        )
        веса, _ = hn.weights_own(rows)
        страница_весов = next(
            (
                f.source_url
                for f in rows
                if any((urlparse(f.source_url or "").hostname or "").endswith(h) for h in WEIGHTS_HOSTS)
                and hn._repo_page(f.source_url)
                and ("licen" in f.attribute or f.attribute == "open_weights")
            ),
            "",
        )
        свои_веса = веса == hn.WEIGHTS_YES or bool(страница_весов)
        мои_варианты = tuple(sorted(варианты.get(к, ())))
        # ЗАКАЗЫВАЕМЫЙ ⇔ ЕСТЬ МАРШРУТ (шестой круг): кто продаёт и под каким
        # идентификатором (`own_routes`). Прежде узел без вариантов считался
        # заказываемым по умолчанию — `lustify-v2.0` и `wan2-1-14b-fusionx`
        # (строки только с civitai) стояли в реестре заказываемыми без единого
        # маршрута, а `hunyuan-video` с адресом схемы fal — нет.
        маршруты_ид = own_routes(
            имя,
            rows,
            family=bool(мои_варианты),
            price_routes=list(dict.fromkeys(pn.маршрут(f)[0] for f in цены)),
            vendor_hosts=pn.МАРШРУТ_ХОСТА,
            # Веса СЕМЬИ запускают под именами вариантов: маршрутом узла семьи
            # страница весов не становится — КРОМЕ узла, у которого СВОЯ
            # страница весов с лицензией (седьмой круг, валидатор v7):
            # `flux.2-klein-9b` — опубликованный чекпойнт black-forest-labs/
            # FLUX.2-klein-9B, а числился «узлом семьи без маршрута».
            weights_page=(
                страница_весов
                if страница_весов
                else "weights"
                if свои_веса and not мои_варианты
                else ""
            ),
        )
        маршруты = list(dict.fromkeys(кто for кто, _ in маршруты_ид))
        ids = tuple(dict.fromkeys(ид for кто, ид in маршруты_ид if кто in ROUTE_HOSTS.values()))
        orderable = bool(маршруты_ид)
        работы, канал, нота = classify(имя, rows)
        прогон = pn.предел_прогона(rows)
        основание = "своя запись" if прогон is not None else ""
        семья = семья_у.get(к, "")
        if прогон is None and семья:
            прогон_семьи = pn.предел_прогона(по_ключу[семья])
            if прогон_семьи is not None:
                прогон, основание = прогон_семьи, f"семья {написание[семья]}"
        территории, _ = pl.licence_reservations(rows)
        хостинг = [f for f in rows if f.attribute in HOSTING_ATTRIBUTES]
        vram, _, оценка = hn.vram_need(rows)
        звук = [f for f in rows if f.attribute == "audio_output"]
        узел = Endpoint(
            model=имя,
            key=к,
            family=написание.get(семья, ""),
            variants=мои_варианты,
            ids=ids,
            routes=tuple(dict.fromkeys(маршруты)),
            route_ids=маршруты_ид,
            orderable=orderable,
            self_hostable=свои_веса,
            why_not_orderable=(
                ""
                if orderable
                else f"узел семьи: вариантов в базе {len(мои_варианты)}, своей цены и идентификатора площадки нет"
                if мои_варианты
                else "маршрута нет: ни идентификатора площадки, ни строки цены, ни страницы API вендора, "
                "ни страницы весов с лицензией"
            ),
            functions=работы,
            evidence=канал,
            evidence_note=нота,
            inputs=tuple(sorted(_виды(rows, "requires_inputs") or _виды(rows, "accepts_inputs"))),
            outputs=tuple(sorted(_виды(rows, "produces_outputs"))),
            price_units=tuple(sorted({r.per for r in ставки if r.per})),
            # ЦЕНА — ставка в долларах ЗА ИЗВЕСТНУЮ ЕДИНИЦУ (шестой круг): «$1 per
            # unit (billing unit 'units')» у `gpt-image-2` — заглушка площадки.
            priced=any(r.unit == "usd" and r.amount > 0 and r.per in pricing.PER for r in ставки),
            run_s=прогон,
            run_basis=основание,
            resolutions=tuple(
                dict.fromkeys(
                    str(f.value)[:40]
                    for f in rows
                    if f.attribute in ("resolution_enum", "max_resolution")
                )
            ),
            native_audio=(
                not re.search(r"\bno\b|none|без", " ".join(f.value for f in звук).lower())
            )
            if звук
            else None,
            licence="; ".join(
                dict.fromkeys(
                    str(f.value)[:60] for f in rows if f.attribute in ("license", "licence")
                )
            )[:200],
            territories=tuple(
                sorted({j for f in территории for j in pl.jurisdictions_in(f.value)})
            ),
            hosting=tuple(sorted({j for f in хостинг for j in hosting_of(f.value)})),
            hosting_pinned=tuple(sorted({j for f in хостинг for j in hosting_pinned_of(f.value)})),
            hosting_note="; ".join(
                f"{f.attribute} = «{str(f.value)[:80]}» ({f.source_url})" for f in хостинг[:2]
            ),
            open_weights=веса,
            vram_gb=None if оценка else vram,
        )
        реестр.by_key[к] = узел
    # ВТОРОЙ ПРОХОД: узел семьи СО СВОИМ маршрутом, о своей работе молчащий,
    # берёт РЕЖИМЫ генерации у вариантов (`FAMILY_MODES`). Цена, длина прогона
    # и прочее остаются своими.
    for к, узел in list(реестр.by_key.items()):
        if узел.functions or not узел.orderable or not узел.variants:
            continue
        режимы = {
            ф
            for в in узел.variants
            for ф in (реестр.by_key[fold(в)].functions if fold(в) in реестр.by_key else ())
            if ф in FAMILY_MODES
        }
        if режимы:
            реестр.by_key[к] = replace(
                узел,
                functions=_порядок(режимы),
                evidence=EVIDENCE_VARIANTS,
                evidence_note="режимы вариантов: " + ", ".join(узел.variants[:6]),
            )
    # ТРЕТИЙ ПРОХОД (девятый круг): ХОСТИНГ СЕМЬИ у варианта, который сам о
    # хостинге молчит и чьи веса закрыты. Закрытую модель запускает только её
    # вендор: перепродавец (fal, Replicate) передаёт запрос в его API, и запрос
    # обслуживается там, где записан хостинг семьи. `wan-3.0-t2v` на fal без
    # этого читался «хостинг не записан», хотя семья `wan-3.0` его записала.
    for к, узел in list(реестр.by_key.items()):
        if узел.hosting or узел.self_hostable or not узел.family:
            continue
        узел_семьи = реестр.by_key.get(fold(узел.family))
        if узел_семьи is None or not узел_семьи.hosting or узел_семьи.self_hostable:
            continue
        реестр.by_key[к] = replace(
            узел,
            hosting=узел_семьи.hosting,
            hosting_pinned=узел_семьи.hosting_pinned,
            hosting_note=f"семья {узел_семьи.model}: {узел_семьи.hosting_note}",
        )
    for к, узел in list(реестр.by_key.items()):
        пометки = flags_of(узел, по_ключу.get(к, ()))
        if пометки:
            узел = реестр.by_key[к] = replace(узел, flags=пометки)
        for ф in узел.functions:
            (реестр.flagged if пометки else реестр.by_function).setdefault(ф, []).append(узел)
    return реестр


# --- вид входа шага против вида входа эндпоинта ------------------------------------
#
# ВОСЬМОЙ КРУГ (агент рецептов): `topaz-restore-image` (берёт и отдаёт
# КАРТИНКУ) стоял кандидатом на реставрацию ВИДЕО — работа `restore` одна на
# оба вида. Работа совпала, вид материала — нет. Сверка по ОБЪЯВЛЕННЫМ входам
# эндпоинта и по артефактам, которые шаг подаёт.


def step_media(артефакты: Iterable[str]) -> frozenset[str]:
    """Виды медиа, которые шаг подаёт на вход: видео / изображение (по именам артефактов).

    `референс` — ВХОД ПЛАНА БЕЗ ВИДА (интеграция восьмого круга): у дубляжа это
    ваш ролик или запись, у клона голоса — запись, у замены персонажа — и
    ролик, и снимок. Причислить его к картинке значило снять с дубляжа
    `elevenlabs-dubbing` (берёт видео/аудио) как «вход не того вида»; вид
    такого входа не назван, значит и несовпадения нет.
    """
    виды: set[str] = set()
    for а in артефакты:
        а = str(а)
        if а.startswith(_ВИДЕО) or а == "готовый_ролик":
            виды.add(_ВИДЕО)
        elif а.startswith(_КАРТИНКА) or а == "селфи":
            виды.add(_КАРТИНКА)
    return frozenset(виды)


def input_mismatch(узел: "Endpoint", артефакты: Iterable[str]) -> str:
    """Почему эндпоинт не берёт материал шага (вид входа); пусто — берёт или не записано."""
    шаг = step_media(артефакты)
    берёт = set(узел.inputs) & {_ВИДЕО, _КАРТИНКА}
    if not шаг or not берёт or берёт & шаг:
        return ""
    return (
        f"вход не того вида: шаг подаёт {', '.join(sorted(шаг))}, а эндпоинт берёт "
        f"{', '.join(sorted(берёт))} (схема)"
    )


#: Виды выхода, которые сверяет `output_mismatch`: картинка против видео.
#: КОНСТАНТА-РЕШЕНИЕ (интеграция восьмого круга): звук сюда не входит —
#: `mmaudio-v2` на шаге шумов отдаёт ВИДЕО со звуком, и это его работа.
OUTPUT_MEDIA: frozenset[str] = frozenset({_ВИДЕО, _КАРТИНКА})


def output_mismatch(узел: "Endpoint", виды_шага: Iterable[str]) -> str:
    """Почему эндпоинт не отдаёт то, что шаг производит (вид выхода); пусто — отдаёт или не записано.

    ИНТЕГРАЦИЯ ВОСЬМОГО КРУГА: после того как `animate-replace` ушёл из замены
    лица в правку видео, на шаге замены персонажа (вход — нетипизированный
    `референс`, выход — ВИДЕО) остались только картиночные face-swap
    эндпоинты (`easel-advanced-face-swap`, схема: картинка -> картинка), и
    `input_mismatch` их не ловил — вид входа шага не назван. Выход же назван:
    шагу нужно видео, а эндпоинт отдаёт картинку. Та же сверка, что у входа.
    """
    шаг = set(виды_шага) & OUTPUT_MEDIA
    отдаёт = set(узел.outputs) & OUTPUT_MEDIA
    if not шаг or not отдаёт or отдаёт & шаг:
        return ""
    return (
        f"выход не того вида: шагу нужно {', '.join(sorted(шаг))}, а эндпоинт отдаёт "
        f"{', '.join(sorted(отдаёт))} (схема)"
    )


# --- пометки отбора: сообщество, NSFW, стилевой LoRA -----------------------------
#
# ВОСЬМОЙ КРУГ (валидатор v8, x05: «text-to-image на GTX 1070 8GB» выбрал
# `wan2.2_strangenames` — чужой набор с хаба, о котором база знает три строки
# метаданных; в выборке реестра 40 строк — `pornmasterpro_noobv3vae`,
# `girlslike-krea2`, `diving-illustrious-real-asian-v50-sdxl` кандидатами t2i).
# Это не модели вендора, а мёржи, NSFW-чекпойнты и стилевые LoRA: из базы они
# не удаляются (о них спрашивают), но кандидатами на общий t2i/t2v становятся
# только по явной просьбе.

FLAG_NSFW = "nsfw"
FLAG_COMMUNITY = "community_checkpoint"
FLAG_STYLE_LORA = "style_lora"
FLAGS: tuple[str, ...] = (FLAG_NSFW, FLAG_COMMUNITY, FLAG_STYLE_LORA)

#: Звенья имени/страницы весов, которые ставят NSFW. Целым звеном:
#: `illustrious` не `lust…`. КОНСТАНТА-РЕШЕНИЕ.
NSFW_LINKS = r"nsfw|porn\w*|lust\w*|uncensored|nudes?|nude\w*|hentai|xxx|erotic\w*|sexgod|unfiltered|sexy|lewd"
#: Звенья стилевого LoRA/адаптера: не самостоятельный генератор.
STYLE_LORA_LINKS = r"\w*loras?|lycoris|\w*adapter|style-transfer"
#: Работы генерации, где мёрж сообщества — помеха общему заказу. На TTS/ASR
#: дообучения сообщества (`f5-tts-russian`) остаются кандидатами.
GENERATION_FUNCTIONS: frozenset[str] = frozenset({T2I, T2V, I2V, R2V, IMAGE_EDIT, V2V_EDIT})
#: Атрибуты, которые хаб весов отдаёт о ЛЮБОМ репозитории: по ним одним не
#: сказать, что это за модель (`wan2.2_strangenames`: лицензия, загрузки, задача).
HUB_METADATA_ATTRIBUTES: frozenset[str] = frozenset(
    {"license", "licence", "adoption", "pipeline_tag", "failure_mode", "base_model", "tags", "library_name"}
)
#: Хосты порталов сообщества (тот же список, что `planner.COMMUNITY_HOSTS`).
COMMUNITY_SOURCE_HOSTS: tuple[str, ...] = ("civitai.com", "civitai.green", "openart.ai", "tensor.art")
#: ОРГИ-АВТОРЫ базовых моделей на хабе: страница весов в такой орге — выпуск
#: лаборатории, а не мёрж. Остальные владельцы страниц весов узла «только у
#: себя» на работах генерации — сообщество. КОНСТАНТА-РЕШЕНИЕ (сторожит тест).
FIRST_PARTY_ORGS: frozenset[str] = frozenset(
    o.lower()
    for o in (
        "Wan-AI", "stabilityai", "black-forest-labs", "Lightricks", "ByteDance", "ByteDance-Seed",
        "nvidia", "tencent", "Tencent-Hunyuan", "Qwen", "Tongyi-MAI", "zai-org", "THUDM", "genmo",
        "CompVis", "stable-diffusion-v1-5", "runwayml", "diffusers", "playgroundai", "HiDream-ai",
        "OnomaAIResearch", "briaai", "ali-vilab", "segmind", "tianweiy", "alimama-creative",
        "FireRedTeam", "meituan-longcat", "jdopensource", "krea", "lodestones", "FastVideo",
        "timbrooks", "xinsir", "lllyasviel", "InstantX", "OpenMOSS-Team", "facebook", "microsoft",
        "google", "openai", "MeiGen-AI", "fudan-generative-vision", "deepbrainai-research",
        "TMElyralab", "OpenTalker", "Rudrabha", "hpcai-tech", "rhymes-ai", "Skywork", "SkyworkAI",
        "Kwai-Kolors", "Kwai-Kling", "deepseek-ai", "baidu", "inclusionAI", "moonshotai",
        "StepFun", "stepfun-ai", "Alpha-VLLM", "PixArt-alpha", "Efficient-Large-Model",
        "HunyuanVideo", "cerspense", "caidas", "OmniGen2", "Shitao", "VectorSpaceLab",
    )
)


def _владелец_весов(узел: "Endpoint") -> str:
    """Орг страницы весов узла (`huggingface.co/<орг>/…`, `github.com/<орг>/…`); пусто — не страница."""
    for кто, ид in узел.route_ids:
        if кто != ROUTE_SELF_HOST:
            continue
        u = urlparse(ид)
        хост = (u.hostname or "").lower()
        части = [ч for ч in u.path.split("/") if ч]
        if хост.endswith(("huggingface.co", "github.com", "githubusercontent.com")) and части:
            return части[1].lower() if части[0] in ("api", "models", "spaces") and len(части) > 1 else части[0].lower()
    return ""


def flags_of(узел: "Endpoint", rows: Sequence[Fact] = ()) -> tuple[str, ...]:
    """Пометки отбора узла (`FLAGS`) по имени, странице весов и хостам источников."""
    тексты = [узел.model, *узел.ids, *(ид for кто, ид in узел.route_ids if кто == ROUTE_SELF_HOST)]
    звенья = [_звенья(urlparse(т).path if "://" in т else т) for т in тексты]
    пометки: list[str] = []
    if any(_звено(NSFW_LINKS, з) for з in звенья):
        пометки.append(FLAG_NSFW)
    только_у_себя = bool(узел.routes) and set(узел.routes) == {ROUTE_SELF_HOST}
    генерация = bool(узел.functions) and set(узел.functions) <= GENERATION_FUNCTIONS
    if только_у_себя and генерация and any(_звено(STYLE_LORA_LINKS, з) for з in звенья):
        пометки.append(FLAG_STYLE_LORA)
    хосты = {(urlparse(f.source_url or "").hostname or "").lower() for f in rows} - {""}
    с_портала = bool(хосты) and all(х.endswith(COMMUNITY_SOURCE_HOSTS) for х in хосты)
    орг = _владелец_весов(узел)
    # О чужом чекпойнте база знает только МЕТАДАННЫЕ ХАБА (лицензия, загрузки,
    # задача, обсуждения): ни строки вендора о том, что модель делает, ни
    # числа параметров. Узел с описанием — не «мёрж неизвестно чего».
    # И пришёл он ОБХОДОМ ХАБА (строка задачи или загрузок): лицензия одна —
    # это запись человека о весах, а не карточка из листинга.
    только_метаданные = all(f.attribute in HUB_METADATA_ATTRIBUTES for f in rows) and any(
        f.attribute in ("pipeline_tag", "adoption") for f in rows
    )
    if генерация and (
        с_портала or (только_у_себя and орг and орг not in FIRST_PARTY_ORGS and только_метаданные)
    ):
        пометки.append(FLAG_COMMUNITY)
    return tuple(п for п in FLAGS if п in пометки)


#: Слова, которыми заказчик ЯВНО просит помеченное. NSFW — только своими
#: словами; сообщество и LoRA — словами о сообществе (`planner.COMMUNITY_ASKED`).
NSFW_ASKED = re.compile(r"\bnsfw\b|\badult\b|18\+|\bnude|\berotic|\bporn|для взрослых|эротик|\bню\b", re.I)
COMMUNITY_ASKED = re.compile(
    r"lora|civitai|comfy|workflow|воркфлоу|сообществ|community|checkpoint|чекпоинт|merge|мёрж|мерж", re.I
)


def requested_flags(text: str) -> frozenset[str]:
    """Какие пометки заказчик снял своими словами: пусто — ни одной."""
    снято: set[str] = set()
    if COMMUNITY_ASKED.search(text or ""):
        снято |= {FLAG_COMMUNITY, FLAG_STYLE_LORA}
    if NSFW_ASKED.search(text or ""):
        снято.add(FLAG_NSFW)
    return frozenset(снято)


def excluded_by_flags(узел: "Endpoint", снято: Iterable[str] = ()) -> str:
    """Почему узел не кандидат (пометки, не снятые просьбой); пусто — кандидат."""
    остались = [п for п in узел.flags if п not in set(снято)]
    if not остались:
        return ""
    return (
        f"помечен: {', '.join(остались)} — в базе остаётся, кандидатом становится только по явной "
        "просьбе (LoRA/civitai/community/checkpoint; NSFW — своими словами)"
    )


# --- словарь вопроса: как человек называет работу --------------------------------

#: ИМЕНА РАБОТЫ В ВОПРОСЕ (шестой круг, 2026-10-15). `find_models` держал свой
#: список из девяти «функций» с регулярками по имени и по описанию, и
#: `bria-video-background-removal-v3` считался липсинком, потому что в его
#: описании стоит «talking heads». Работа модели — одна на проект: её
#: устанавливает `classify` свидетельством; здесь только СЛОВА, которыми
#: человек называет работу в вопросе. Каждая работа `FUNCTIONS` называется и
#: своим идентификатором (строка тест-сторожа).
#:
#: Фраза сверяется с началом слова и целиком по началу (`job_words`): «липсинк»
#: ловит «липсинка», «interpolation» — «interpolation», но «tts» не ловит
#: «settings». Короче `JOB_WORD_STEM_MIN` символов — только целым словом.
JOB_WORDS: dict[str, tuple[str, ...]] = {
    T2V: ("t2v", "text-to-video", "text to video", "видео по тексту"),
    I2V: ("i2v", "image-to-video", "image to video", "img2vid", "оживить фото", "оживление фото"),
    R2V: ("r2v", "reference-to-video", "reference to video"),
    V2V_EDIT: ("v2v-edit", "v2v", "video-to-video", "video to video", "video edit", "правка видео"),
    LIPSYNC: ("lipsync", "lip-sync", "lip sync", "липсинк", "синхронизация губ"),
    AVATAR: ("talking avatar", "talking-avatar", "talking head", "talking-head", "avatar", "аватар"),
    FACE_SWAP: ("face-swap", "face swap", "faceswap", "замена лица"),
    DUB: ("dub-translate", "dubbing", "dub", "дубляж"),
    TTS: ("tts", "text-to-speech", "text to speech", "speech synthesis", "voiceover", "озвучк", "синтез речи"),
    VOICE_CLONE: ("voice-clone", "voice clone", "voice cloning", "клон голоса", "клонирование голоса"),
    MUSIC: ("music", "song", "музык", "песн"),
    SFX: ("sfx", "sound effects", "sound effect", "foley", "звуковые эффекты", "шумы"),
    T2I: ("t2i", "text-to-image", "text to image", "image generation", "генерация изображений"),
    IMAGE_EDIT: ("image-edit", "image edit", "edit image", "редактирование изображен"),
    BG_REMOVE: (
        "bg-remove",
        "background removal",
        "remove background",
        "remove the background",
        "matting",
        "удаление фона",
        "удалить фон",
    ),
    UPSCALE_IMAGE: ("upscale-image", "image upscale", "upscale image", "апскейл изображен"),
    UPSCALE_VIDEO: ("upscale-video", "video upscale", "upscale video", "апскейл видео"),
    RESTORE: ("restore", "restoration", "реставрац"),
    COLORIZE: ("colorize", "colourise", "colorization", "раскрас"),
    INTERPOLATE: ("frame-interpolate", "frame interpolation", "interpolation", "slow motion", "интерполяц"),
    TRANSCRIBE: (
        "transcribe-diarize",
        "transcribe",
        "transcription",
        "speech-to-text",
        "diarization",
        "stt",
        "расшифровк",
        "транскрипц",
    ),
    CAPTIONS: ("captions", "subtitles", "субтитр"),
    TURNTABLE: ("turntable-360", "turntable", "360 spin", "оборот 360"),
    IMAGE_TO_3D: ("image-to-3d", "3d model", "3d reconstruction", "glb", "3d-модель"),
}

#: ШИРОКИЕ СЛОВА: называют не одну работу, а несколько. Как `function` они
#: задают область; работу, названную в самом вопросе, область уточняет
#: (`function="video"`, «background removal for video» — удаление фона).
BROAD_JOB_WORDS: dict[str, tuple[str, ...]] = {
    "video": (T2V, I2V, R2V, V2V_EDIT),
    "видео": (T2V, I2V, R2V, V2V_EDIT),
    "image": (T2I, IMAGE_EDIT),
    "картинка": (T2I, IMAGE_EDIT),
    "upscale": (UPSCALE_VIDEO, UPSCALE_IMAGE),
    "upscaler": (UPSCALE_VIDEO, UPSCALE_IMAGE),
    "апскейл": (UPSCALE_VIDEO, UPSCALE_IMAGE),
    "audio": (TTS, MUSIC, SFX),
    "speech": (TTS,),
    "voice": (TTS, VOICE_CLONE),
    "restore-colorize": (RESTORE, COLORIZE),
}

# --- ПРАВКА ВИДЕО: что именно правится (интеграция шестого круга) -------------
#
# Работа `v2v-edit` в реестре широкая: в ней и правка по инструкции
# (`kling-video/o3/.../video-to-video/edit`), и продление ролика (`extend-video`),
# и генерация по референсу (`.../video-to-video/reference`), и перенос движения
# (`motion-control`). Валидатор шестого круга: «замена неба» выбрала продление,
# «смена кадра» — r2v. Ниже — что правка делает, по ЗВЕНЬЯМ идентификатора
# (то же свидетельство, что и у работы, — `EVIDENCE_ID`/категория площадки).

EDIT_REFRAME = "reframe"
EDIT_REPLACE_OBJECT = "replace-object"
EDIT_REMOVE_OBJECT = "remove-object"
EDIT_REPLACE_SKY = "replace-sky"
EDIT_STABILISE = "stabilise"
EDIT_RELIGHT = "relight"
#: Смена времени суток (восьмой круг) — ОТДЕЛЬНАЯ правка: переосвещение меняет
#: свет на объекте (недоэкспонированное лицо, ключевой свет слева), а
#: «день -> ночь» перерисовывает всю сцену. Валидатор v8 (n13): на «лицо
#: недоэкспонировано» выбирался `day-to-night`.
EDIT_DAY_TO_NIGHT = "day-to-night"
EDIT_RESTYLE = "restyle"
#: ПРОДЛЕНИЕ ролика заказчика (девятый круг, валидатор e02): «5 с -> 10 с,
#: продолжить движение камеры». Эндпоинты `…/extend` делают ровно это, но
#: правкой не считались вовсе (`NOT_AN_EDIT`), и шаг правки брал правку по
#: инструкции, которая длину ролика не меняет.
EDIT_EXTEND = "extend"

#: Допустимые значения `spec.edit`. КОНСТАНТА-РЕШЕНИЕ.
EDIT_INTENTS: tuple[str, ...] = (
    EDIT_REFRAME,
    EDIT_REPLACE_OBJECT,
    EDIT_REMOVE_OBJECT,
    EDIT_REPLACE_SKY,
    EDIT_STABILISE,
    EDIT_RELIGHT,
    EDIT_DAY_TO_NIGHT,
    EDIT_RESTYLE,
    EDIT_EXTEND,
)

#: Звено ПРАВКИ ПО ИНСТРУКЦИИ: модель правит кадр заказчика словами
#: («замени небо», «убери машину») — она и отвечает за замену и удаление.
_ПРАВКА_ПО_ИНСТРУКЦИИ = r"edit|edit-video|video-edit|v2v-edit|inpaint"

#: Под-работа -> звенья идентификатора, которые её называют.
EDIT_RULES: dict[str, str] = {
    EDIT_REFRAME: r"reframe|outpaint",
    EDIT_REPLACE_OBJECT: _ПРАВКА_ПО_ИНСТРУКЦИИ + r"|animate-replace|character-replace",
    EDIT_REMOVE_OBJECT: _ПРАВКА_ПО_ИНСТРУКЦИИ + r"|clean-plate|object-removal|remove-object",
    EDIT_REPLACE_SKY: _ПРАВКА_ПО_ИНСТРУКЦИИ + r"|sky-replace\w*|replace-sky",
    EDIT_STABILISE: r"stabili[sz]\w*",
    # Свет на объекте и экспозиция: `minimax-h3-max-relight`, `qwen-edit-2509-
    # light-migration`, `qie-2511-mp-anylight`. `hdr` — динамический диапазон
    # кадра, а не свет на объекте; `day-to-night` — своя правка.
    EDIT_RELIGHT: r"relight\w*|exposure|light-migration|anylight",
    EDIT_DAY_TO_NIGHT: r"day-to-night|night-to-day|time-of-day",
    EDIT_RESTYLE: r"recast|render-to-real|restyle|style-transfer",
    EDIT_EXTEND: r"extend\w*|extension",
}

#: Под-работа, НАЗВАННАЯ идентификатором прямо (седьмой круг): без звена
#: правки по инструкции (`edit`), которое `EDIT_RULES` засчитывает каждой
#: замене и удалению. `fal-ai/ltx-2.3-quality/clean-plate` называет удаление
#: объекта; `kling-video/o3/.../video-to-video/edit` — только правку словами.
#: `find_models` различает эти два свидетельства (способность по каталогу
#: против «может, если попросить»).
EDIT_NAMED: dict[str, str] = {
    # Правила без звена правки по инструкции — те же (Е1: выводятся, не копируются).
    **{п: о for п, о in EDIT_RULES.items() if not о.startswith(_ПРАВКА_ПО_ИНСТРУКЦИИ)},
    EDIT_REPLACE_OBJECT: r"replace-object|object-replace\w*|animate-replace|character-replace",
    # `inpaint` в правиле по инструкции общий; прямо названное удаление — здесь.
    EDIT_REMOVE_OBJECT: EDIT_RULES[EDIT_REMOVE_OBJECT].removeprefix(_ПРАВКА_ПО_ИНСТРУКЦИИ + "|")
    + r"|object-remov\w*|inpaint\w*",
    # ЗАМЕНА НЕБА — ЛОКАЛЬНАЯ ПРАВКА ПО МАСКЕ (девятый круг, валидатор w34):
    # «всё остальное не трогать» = маска неба и новое небо ТОЛЬКО внутри неё.
    # Эндпоинт, который называет инпейнт (перерисовку внутри маски), делает
    # именно это; правка по инструкции перерисовывает весь кадр.
    EDIT_REPLACE_SKY: EDIT_RULES[EDIT_REPLACE_SKY].removeprefix(_ПРАВКА_ПО_ИНСТРУКЦИИ + "|")
    + r"|inpaint\w*",
}


def edit_named(endpoint: "Endpoint | str") -> frozenset[str]:
    """Правки, которые идентификатор НАЗЫВАЕТ прямо (`EDIT_NAMED`); пусто — не названо."""
    тексты = (endpoint,) if isinstance(endpoint, str) else (endpoint.model, *endpoint.ids)
    return frozenset(
        п for п, образец in EDIT_NAMED.items() for т in тексты if _звено(образец, _звенья(т))
    )


#: Звенья, при которых эндпоинт работы `v2v-edit` — НЕ правка ролика
#: заказчика: он делает новое видео (продление, по референсу, по движению,
#: из 3D, черновик). На шаге правки он кандидатом не бывает.
NOT_AN_EDIT = r"extend|extend-video|reference|motion-control|3d-to-video|draft|insert-video"


def edit_intents(endpoint: "Endpoint | str") -> frozenset[str]:
    """Какие правки называет идентификатор эндпоинта (`EDIT_INTENTS`); пусто — не названо."""
    if isinstance(endpoint, str):
        тексты: tuple[str, ...] = (endpoint,)
    else:
        тексты = (endpoint.model, *endpoint.ids)
    итог: set[str] = set()
    for т in тексты:
        звенья = _звенья(т)
        итог.update(п for п, образец in EDIT_RULES.items() if _звено(образец, звенья))
    # Голое «video-to-video» без названной правки (`ltx-2.3-22b/video-to-video`,
    # `hunyuan-video/video-to-video`) — перерисовка всего ролика по подсказке.
    if not итог and not any(_звено(NOT_AN_EDIT, _звенья(т)) for т in тексты):
        if any(_звено(r"v2v|video-to-video", _звенья(т)) for т in тексты):
            итог.add(EDIT_RESTYLE)
    return frozenset(итог)


def not_an_edit(endpoint: "Endpoint | str") -> bool:
    """Эндпоинт делает НОВОЕ видео (продление, референс, движение), а не правит данное."""
    тексты = (endpoint,) if isinstance(endpoint, str) else (endpoint.model, *endpoint.ids)
    return any(_звено(NOT_AN_EDIT, _звенья(т)) for т in тексты)


#: Короче этого — фраза ловится только целым словом (`tts`, `i2v`, `dub`).
JOB_WORD_STEM_MIN = 5


def job_words(text: str) -> tuple[str, ...]:
    """Работы, названные в тексте словами `JOB_WORDS`, в порядке ПЕРВОГО упоминания.

    Порядок — не алфавит и не `FUNCTIONS`: в «remove the background from a
    talking-head video» работа — удаление фона, а «talking-head» описывает
    материал. Первой названа работа, о которой спрашивают.
    """
    низ = " ".join(str(text or "").lower().split())
    где: dict[str, int] = {}
    for работа, фразы in JOB_WORDS.items():
        for ф in фразы:
            хвост = r"[\w-]*" if len(ф) >= JOB_WORD_STEM_MIN else ""
            м = re.search(rf"(?<![\w-]){re.escape(ф)}{хвост}(?![\w-])", низ)
            if м and (работа not in где or м.start() < где[работа]):
                где[работа] = м.start()
    return tuple(sorted(где, key=lambda р: (где[р], FUNCTIONS.index(р))))


def jobs_of_word(word: str) -> tuple[tuple[str, ...], bool]:
    """(работы, широкое ли слово) для значения `function`; пусто — не понято."""
    низ = " ".join(str(word or "").strip().lower().split())
    if not низ:
        return (), False
    if низ in FUNCTIONS:
        return (низ,), False
    if низ in BROAD_JOB_WORDS:
        return BROAD_JOB_WORDS[низ], True
    for работа, фразы in JOB_WORDS.items():
        if низ in фразы:
            return (работа,), False
    named = job_words(низ)
    return named, len(named) > 1


def coverage(реестр: Registry) -> list[dict]:
    """По работе: заказываемых узлов, с ценой, с длиной прогона (доли — проценты)."""
    строки = []
    for ф in FUNCTIONS:
        # Помеченные (`flags`) считаются: они заказываемы, просто кандидатами
        # становятся по просьбе. Гейт покрытия меряет «можно заказать».
        узлы = [e for e in реестр.all_for(ф) if e.orderable]
        n = len(узлы)
        с_ценой = sum(1 for e in узлы if e.priced)
        с_прогоном = sum(1 for e in узлы if e.run_s is not None)
        строки.append(
            {
                "function": ф,
                "orderable": n,
                "priced": с_ценой,
                "priced_pct": round(100.0 * с_ценой / n, 1) if n else 0.0,
                "with_run_length": с_прогоном,
                "run_length_pct": round(100.0 * с_прогоном / n, 1) if n else 0.0,
                "video": ф in VIDEO_FUNCTIONS,
            }
        )
    return строки


__all__ = [
    "AVATAR",
    "CATEGORY_FUNCTIONS",
    "CURATED",
    "Endpoint",
    "FUNCTIONS",
    "JOB_RULES",
    "MODE_RULES",
    "Registry",
    "SHAPE_RULES",
    "VIDEO_FUNCTIONS",
    "build",
    "classify",
    "coverage",
    "endpoint_ids",
]
