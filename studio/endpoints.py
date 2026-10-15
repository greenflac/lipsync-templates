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
from typing import Iterable, Mapping, Sequence
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
RESTORE = "restore-colorize"
INTERPOLATE = "frame-interpolate"
TRANSCRIBE = "transcribe-diarize"
CAPTIONS = "captions"
TURNTABLE = "turntable-360"

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
    INTERPOLATE,
    TRANSCRIBE,
    CAPTIONS,
    TURNTABLE,
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
    (r"lip-?sync(?:ing)?|lipsync", (LIPSYNC,)),
    (r"(?:ai-)?avatars?|talking-?heads?|audio-to-video|a2v|s2v|speech-to-video", (AVATAR,)),
    (r"face-?swap|faceswap|inswapper(?:-\d+)?|animate-replace|character-replace", (FACE_SWAP,)),
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
    (r"coloriz\w*|colouriz\w*|restor\w*|ddcolor|deoldify", (RESTORE,)),
    (r"interpolat\w*|rife", (INTERPOLATE,)),
    (r"speech-to-text|transcri\w*|diariz\w*|scribe|whisper|asr|stt", (TRANSCRIBE,)),
    (r"auto-caption\w*|subtitl\w*", (CAPTIONS,)),
    (r"turntable|orbit|360-?spin|multi-?view|novel-view", (TURNTABLE,)),
)

#: Звено апскейла: какая из двух работ — решает выход или звено видео/картинки.
UPSCALE_RULE = r"upscal\w*|upacaler|super-?resolution|superresolution|vsr"

#: РЕЖИМ генерации, названный в идентификаторе, — когда работы не названо.
MODE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"text-to-video|t2v|txt2vid|text2video", (T2V,)),
    (r"image-to-video|i2v|img2vid|image2video|flf2v", (I2V,)),
    # «TI2V» — текст И/ИЛИ кадр в видео (`wan-2.2-ti2v-5b`): оба режима.
    (r"ti2v", (T2V, I2V)),
    (r"reference-to-video|r2v|ref2v", (R2V,)),
    (
        r"v2v(?:-edit)?|video-edit|edit-video|video-to-video|retake-video|recast|relight",
        (V2V_EDIT,),
    ),
    (r"text-to-image|t2i|txt2img|text2image", (T2I,)),
    (r"image-to-image|i2i|img2img|edit-image|image-edit|edit|inpaint|outpaint", (IMAGE_EDIT,)),
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
#: Хосты страниц весов: маршрут «запустить у себя».
WEIGHTS_HOSTS: tuple[str, ...] = ("huggingface.co", "github.com")
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
    territories: tuple[str, ...] = ()
    open_weights: str = ""
    vram_gb: float | None = None

    def does(self, function: str) -> bool:
        return function in self.functions


@dataclass
class Registry:
    """Все узлы и индекс «работа -> заказываемые узлы»."""

    by_key: dict[str, Endpoint] = field(default_factory=dict)
    by_function: dict[str, list[Endpoint]] = field(default_factory=dict)

    def get(self, model: str) -> Endpoint | None:
        return self.by_key.get(fold(model))

    def orderable_for(self, function: str) -> list[Endpoint]:
        return [e for e in self.by_function.get(function, []) if e.orderable]


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
    """Работы модели по её строкам: (работы, канал, чем найдено). Пусто — не установлено."""
    curated = CURATED if curated is None else curated
    ids, категории = endpoint_ids(rows)
    выходы = _виды(rows, "produces_outputs")
    категория = категории[0] if категории else ""
    # 0. Курированная строка — прочитанное человеком — старше выведенного.
    имя_курированное = next((к for к in curated if fold(к) == fold(model)), "")
    if имя_курированное:
        что, почему, источник = curated[имя_курированное]
        return _порядок(set(что)), EVIDENCE_CURATED, f"{почему} ({источник})"
    # 1. Идентификаторы: имя в базе и адреса площадки.
    работы: set[str] = set()
    режимы: set[str] = set()
    откуда: list[str] = []
    for ид in (model, *ids):
        р, м = _работы_имени(_звенья(ид), выходы, категория)
        if р or м:
            откуда.append(ид)
        работы |= р
        режимы |= м
    if работы:
        return _порядок(работы), EVIDENCE_ID, "; ".join(откуда)
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
            return (работа,), EVIDENCE_SHAPE, f"requires {', '.join(sorted(нужны))} -> {выход}"
    # 2. Категория каталога (если она есть) уточняет и дополняет режимы имени.
    из_категории = {ф for к in категории for ф in CATEGORY_FUNCTIONS.get(к, ())}
    if режимы:
        if из_категории and not (режимы & из_категории):
            # Категория площадки и звено имени спорят — верится площадке, которая
            # продаёт ЭТОТ эндпоинт: имя могло прийти из семьи.
            return (
                _порядок(из_категории),
                EVIDENCE_CATEGORY,
                f"{категория} (имя: {', '.join(откуда)})",
            )
        return _порядок(режимы), EVIDENCE_ID, "; ".join(откуда)
    if из_категории:
        return _порядок(из_категории), EVIDENCE_CATEGORY, ", ".join(категории)
    # 3. Описательные строки вендора/площадки — значение, а у строк схемы и
    # документации ещё и ИМЯ атрибута (`ratio_enum_text_to_video`,
    # `prompt_rule_i2v`: вендор записал предел ДЛЯ РЕЖИМА — режим есть).
    for f in rows:
        if f.tier in DOC_TIERS and f.attribute in DOC_ATTRIBUTES and f.attribute != "availability":
            р, м = _работы_имени(_звенья(f.value), выходы, "")
            if р or м:
                return (
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
        return _порядок(по_именам), EVIDENCE_DOCS, "атрибуты: " + ", ".join(dict.fromkeys(имена))
    # 4. Объявленная форма: обязательные входы; без них — принимаемые, и тогда
    # каждый принимаемый вид картинки или текста — свой режим (`hunyuanvideo-1.5`
    # принимает текст и изображение — делает и t2v, и i2v).
    for выход in sorted(выходы):
        работа = SHAPE_RULES.get((frozenset(нужны), выход))
        if работа:
            return (работа,), EVIDENCE_SHAPE, f"requires {', '.join(sorted(нужны))} -> {выход}"
    берёт = _виды(rows, "accepts_inputs")
    if not нужны and берёт and not (берёт & {"аудио", "видео"}):
        режимы = {
            SHAPE_RULES[(frozenset({вид}), выход)]
            for вид in берёт
            for выход in выходы
            if (frozenset({вид}), выход) in SHAPE_RULES
        }
        if режимы:
            return (
                _порядок(режимы),
                EVIDENCE_SHAPE,
                f"accepts {', '.join(sorted(берёт))} -> {', '.join(sorted(выходы))}",
            )
    return (), "", ""


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
        ids, _ = endpoint_ids(rows)
        цены = pn.price_facts(rows)
        ставки = [r for f in цены for r in pricing.rates(f.value, f.attribute)]
        маршруты = list(dict.fromkeys(pn.маршрут(f)[0] for f in цены))
        for ид_ in ids:
            for f in rows:
                хост = (urlparse(f.source_url or "").hostname or "").lower()
                for h, имя_маршрута in ROUTE_HOSTS.items():
                    if (хост == h or хост.endswith("." + h)) and имя_маршрута not in маршруты:
                        маршруты.append(имя_маршрута)
            break
        веса, _ = hn.weights_own(rows)
        свои_веса = веса == hn.WEIGHTS_YES or any(
            any((urlparse(f.source_url or "").hostname or "").endswith(h) for h in WEIGHTS_HOSTS)
            and "licen" in f.attribute
            for f in rows
        )
        if свои_веса:
            маршруты.append(ROUTE_SELF_HOST)
        # СВОЙ МАРШРУТ — цена или строка каталога «on <площадка> as <id>».
        # Адрес площадки в строке-источнике маршрутом узла не считается: у
        # `kling-3.0` лежат строки со страниц motion-control эндпоинтов — это
        # строки о соседях, а не заказ семьи.
        свой_маршрут = bool(цены) or any(
            f.attribute == "availability" and _AVAILABILITY.search(str(f.value)) for f in rows
        )
        мои_варианты = tuple(sorted(варианты.get(к, ())))
        orderable = not (мои_варианты and not свой_маршрут)
        работы, канал, нота = classify(имя, rows)
        прогон = pn.предел_прогона(rows)
        основание = "своя запись" if прогон is not None else ""
        семья = семья_у.get(к, "")
        if прогон is None and семья:
            прогон_семьи = pn.предел_прогона(по_ключу[семья])
            if прогон_семьи is not None:
                прогон, основание = прогон_семьи, f"семья {написание[семья]}"
        территории, _ = pl.licence_reservations(rows)
        vram, _, оценка = hn.vram_need(rows)
        звук = [f for f in rows if f.attribute == "audio_output"]
        узел = Endpoint(
            model=имя,
            key=к,
            family=написание.get(семья, ""),
            variants=мои_варианты,
            ids=ids,
            routes=tuple(dict.fromkeys(маршруты)),
            orderable=orderable,
            self_hostable=свои_веса,
            why_not_orderable=(
                f"узел семьи: вариантов в базе {len(мои_варианты)}, своей цены и идентификатора площадки нет"
                if not orderable
                else ""
            ),
            functions=работы,
            evidence=канал,
            evidence_note=нота,
            inputs=tuple(sorted(_виды(rows, "requires_inputs") or _виды(rows, "accepts_inputs"))),
            outputs=tuple(sorted(_виды(rows, "produces_outputs"))),
            price_units=tuple(sorted({r.per for r in ставки if r.per})),
            priced=any(r.unit == "usd" and r.amount > 0 for r in ставки),
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
    for узел in реестр.by_key.values():
        for ф in узел.functions:
            реестр.by_function.setdefault(ф, []).append(узел)
    return реестр


def coverage(реестр: Registry) -> list[dict]:
    """По работе: заказываемых узлов, с ценой, с длиной прогона (доли — проценты)."""
    строки = []
    for ф in FUNCTIONS:
        узлы = реестр.orderable_for(ф)
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
