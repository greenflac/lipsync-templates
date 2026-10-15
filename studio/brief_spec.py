"""СТРУКТУРНОЕ ПОНИМАНИЕ БРИФА: что заказано, из чего и сколько.

ЗАЧЕМ ЭТОТ МОДУЛЬ (2026-10-15, четвёртый круг). Валидатор третьего круга
нашёл корень: понимание брифа — списки подстрок (`planner.OPERATIONS[*].cues`,
`HAVE_VIDEO_CUES`, `KEYFRAME_CUES`), и починщики подгоняли их под ТОЧНЫЕ
фразы валидатора. Свежая формулировка давала ноль шагов: из семи новых
английских брифов четыре ушли в `шаги_не_выведены`.

Два слоя, и порядок их — решение:

1. `spec` — СТРУКТУРА от вызывающего. Плановщика зовёт языковая модель; она
   понимает бриф лучше любого списка подстрок и может назвать поля прямо
   (`outputs`, `duration_s`, `shots`, `inputs`, `task` …). Поле, названное в
   `spec`, СТАРШЕ всего, что выведено из текста.
2. `from_text` — ЗАПАСНОЙ разбор по СТРУКТУРЕ текста, а не по фразам: числа с
   единицами (5s, 1080p, 24fps, $4), счётные существительные («3 product
   shots»), существительные медиа и притяжательное в ОКНЕ слов от них («my 45s
   English video» — `my` в трёх словах от `video`), глаголы работы с объектом.

Что понято — ВСЕГДА печатается (`echo`, поле ответа `understood_as`), с
источником каждого поля (spec / text / default), чтобы вызывающий мог
поправить. Ничего не понято — ВОПРОС, называющий, чего не хватает (Р1), а не
пустой список шагов.

Модуль не знает моделей и базы фактов: он отвечает «что заказано», а «кем
делать» решает `studio/planner.py`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from studio import duration as dur
from studio import pipeline as pl

# --- словари поля `spec` ---------------------------------------------------

OUTPUTS: tuple[str, ...] = ("video", "image", "speech", "music", "sfx")
TASKS: tuple[str, ...] = (
    "generate",
    "animate",
    "lipsync",
    "dub-translate",
    "face-replace",
    "avatar",
    "upscale",
    "edit",
)
AUDIO_MODES: tuple[str, ...] = ("none", "native", "voiceover")
INPUT_KINDS: tuple[str, ...] = ("photo", "video", "audio", "script")
OBJECTIVES: tuple[str, ...] = ("cheapest", "balanced", "quality")

#: Все поля `spec`, которые плановщик принимает. Неизвестное поле — ошибка, а
#: не молчание: вызывающий, написавший `durations`, должен узнать, что его не
#: прочли.
SPEC_FIELDS: tuple[str, ...] = (
    "task",
    "outputs",
    "duration_s",
    "shots",
    "per_shot_s",
    "characters",
    "resolution",
    "aspect",
    "fps",
    "audio",
    "languages",
    "inputs",
    "objective",
    "budget_usd",
    "self_host",
    "jurisdiction",
)

SOURCE_SPEC = "spec"
SOURCE_TEXT = "text"
SOURCE_DEFAULT = "default"
#: Поле ВЫЧИСЛЕНО из других (шоты = длительность / предел прогона модели).
SOURCE_DERIVED = "derived"

# --- константы-решения (Т1: каждая мутируется тестом в обе стороны) ------

#: Сколько слов может стоять МЕЖДУ притяжательным и существительным медиа:
#: «my video» — 0, «my 45s English video» — 2, «our new product launch video»
#: — 3. ВЫБРАНО 3: на большем окне «my brother wants a video» читалось бы как
#: принесённое видео.
POSSESSIVE_WINDOW = 3

#: Сколько слов после глагола работы ищется его объект: «translate the 45s
#: video» — 2, «animate the attached product photo» — 3.
OBJECT_WINDOW = 4

#: Сколько слов может стоять между «по»/«per» и числом с единицей, чтобы
#: число было длиной ШОТА: «по 5 секунд» — 0, «по целых 5 секунд» — 1. ВЫБРАНО
#: 1: при 2 «по брифу ролик 30 секунд» читалось бы как шот 30 с. Слова
#: «каждый/each» действуют на всю клаузу (`DISTRIBUTIVE`) и окна не требуют.
EACH_WINDOW = 1

#: Сколько персонажей делают ролик «многоперсонажным»: тогда видео идёт из
#: ключевых кадров (по кадру на шот), иначе персонажи разъезжаются от шота к
#: шоту.
MULTI_CHARACTER_MIN = 2

#: Разрешение по умолчанию для видео, если заказчик его не назвал, а план
#: собран маршрутом из спецификации. 1080p — стандарт площадок рекламы 9:16
#: (Reels, TikTok, Shorts принимают 1080x1920). Значение ПЕЧАТАЕТСЯ в `echo`
#: как допущение, а не подставляется молча — молча выбранные 480p и были
#: находкой валидатора.
DEFAULT_VIDEO_RESOLUTION = "1080p"

#: Длина одного шота, если предел выбранной модели не записан. Нужна только
#: для счёта ключевых кадров многоперсонажного ролика и печатается в `echo`
#: допущением.
ASSUMED_SHOT_S = 8.0

# --- разбор чисел и единиц --------------------------------------------------

NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a pair of": 2,
    "один": 1, "одна": 1, "одну": 1, "одно": 1, "два": 2, "две": 2, "двух": 2, "три": 3,
    "трёх": 3, "трех": 3, "четыре": 4, "четырёх": 4, "четырех": 4, "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "both": 2, "оба": 2, "обе": 2, "двое": 2, "трое": 3,
}  # fmt: skip

_ЧИСЛО = r"(?:\d{1,3}|" + "|".join(sorted(map(re.escape, NUMBER_WORDS), key=len, reverse=True)) + r")"

#: Счётное существительное ШОТА: то, чем режут ролик или что делают поштучно.
SHOT_NOUN = (
    r"(?:shots?|packshots?|scenes?|clips?|cuts?|segments?|images?|photos?|pictures?|stills?|keyframes?"
    r"|key frames?|frames?|videos?|products?|variations?|versions?"
    r"|кадр[а-яё]*|сцен[а-яё]*|клип[а-яё]*|ролик[а-яё]*|фото[а-яё]*|снимк[а-яё]*|снимок"
    r"|картин[а-яё]*|изображени[а-яё]*|шот[а-яё]*|вариант[а-яё]*)"
)
_СЧЁТ = re.compile(
    r"(?<![\w.$])(?P<n>" + _ЧИСЛО + r")"
    r"(?!\s*-?\s*(?:s|secs?|seconds?|minutes?|mins?|с|сек|секунд[а-яё]*|минут[а-яё]*)(?![a-zа-яё]))"
    r"\s+(?:[a-zа-яё'-]+\s+){0,2}?(?P<noun>" + SHOT_NOUN + r")(?![a-zа-яё])"
    r"(?!\s*(?:в секунду|per second|a second|/\s*s\b|fps))"
)

_ДЛИТЕЛЬНОСТЬ = re.compile(
    r"(?<![\w.])(?P<n>\d+(?:[.,]\d+)?)\s*-?\s*(?P<u>seconds?|secs?|s|minutes?|mins?|min"
    r"|секунд[а-яё]*|сек|с|минут[а-яё]*|мин)(?![a-zа-яё0-9])"
)
#: Распределительные слова: «каждый», «each», «per shot». Где угодно в клаузе.
DISTRIBUTIVE = re.compile(
    r"\beach\b|\bevery\b|\bapiece\b|\bper (?:shot|clip|scene|image|photo|picture|video|still|one)\b"
    r"|кажд[а-яё]+|на (?:каждый|каждое|каждую|шот|клип|сцену|кадр)\b"
)
_EACH = re.compile(
    r"^(?:each|every|per|apiece|каждый|каждая|каждое|каждую|каждого|каждому|по)$"
)
_FPS = re.compile(r"(?<![\w.])(\d{2,3})\s*(?:fps|к/с|frames? per second|кадр[а-яё]* в секунду)")
_ASPECT = re.compile(r"(?<![\d:])(9:16|16:9|1:1|4:5|4:3|3:4|21:9|2:3|3:2)(?![\d:])")
_WXH = re.compile(r"(?<![\d])(\d{3,5})\s*[x×*]\s*(\d{3,5})(?![\d])")

#: Ступени разрешения: метка -> (длинная, короткая) сторона.
RESOLUTIONS: dict[str, tuple[int, int]] = {
    "8k": (7680, 4320),
    "4k": (3840, 2160),
    "2160p": (3840, 2160),
    "1440p": (2560, 1440),
    "2k": (2560, 1440),
    "1080p": (1920, 1080),
    "full hd": (1920, 1080),
    "fullhd": (1920, 1080),
    "fhd": (1920, 1080),
    "720p": (1280, 720),
    "hd": (1280, 720),
    "540p": (960, 540),
    "480p": (854, 480),
}

VERTICAL = re.compile(r"вертикал|vertical|portrait mode|reels?\b|tiktok|shorts\b|сторис|stories")
HORIZONTAL = re.compile(r"horizontal|landscape|widescreen|горизонт|youtube\b")
SQUARE = re.compile(r"\bsquare\b|квадрат")

# --- существительные медиа и глаголы ---------------------------------------

VIDEO_NOUN = re.compile(
    r"^(?:videos?|clips?|footage|reels?|films?|recordings?|mp4|mov|demos?|promos?|explainers?|trailers?"
    r"|commercials?|teasers?|vlogs?|webinars?|ролик[а-яё]*|видео|видеоролик[а-яё]*|видеофайл[а-яё]*|видеозапис[а-яё]*|влог[а-яё]*|вебинар[а-яё]*"
    r"|видос[а-яё]*|клип[а-яё]*|исходник[а-яё]*|съ[её]мк[а-яё]*)$"
)
PHOTO_NOUN = re.compile(
    r"^(?:photos?|pictures?|images?|selfies?|headshots?|portraits?|stills?|jpe?g|png|pics?"
    r"|фото[а-яё]*|фотк[а-яё]*|снимк[а-яё]*|снимок|селфи|портрет[а-яё]*|картинк[а-яё]*"
    r"|изображени[а-яё]*)$"
)
AUDIO_NOUN = re.compile(
    r"^(?:audio|voiceover|voice-over|narration|mp3|wav|track|аудио[а-яё]*|озвучк[а-яё]*"
    r"|дорожк[а-яё]*|начитк[а-яё]*)$"
)
SCRIPT_NOUN = re.compile(r"^(?:script|copy|text|сценари[а-яё]*|текст[а-яё]*)$")

#: Притяжательное и «уже есть»: в окне перед существительным медиа оно делает
#: медиа ВХОДОМ.
POSSESSIVE = re.compile(
    r"^(?:my|our|own|existing|attached|uploaded|supplied|provided"
    r"|мо(?:й|я|ё|е|ю|его|ей|их|и|им|ими|ём|ем)|наш[а-яё]*|сво(?:й|я|ё|е|ю|его|ей|их|и|им|ими|ём|ем)"
    r"|готов[а-яё]*|существующ[а-яё]*|имеющ[а-яё]*|приложенн[а-яё]*|загруженн[а-яё]*"
    r"|присланн[а-яё]*|отснят[а-яё]*)$"
)
#: Владение, сказанное ПОСЛЕ существительного медиа (в окне `OBJECT_WINDOW`).
OWNED_AFTER = re.compile(
    r"^(?:(?:that|which|который|которое|которую|которые)\s+)?"
    r"(?:(?:i|we)\s+(?:already\s+|have\s+)?(?:uploaded|attached|shot|filmed|recorded|sent|made|have|got)\b"
    r"|(?:is|are)\s+(?:attached|uploaded|ready|here)\b"
    r"|(?:я|мы)\s+(?:уже\s+)?(?:снял|сняли|записал|записали|загрузил|загрузили|прислал|прислали|приложил)[а-яё]*"
    r"|уже\s+(?:есть|снят|готов)[а-яё]*)"
)

#: Отрицание в окне перед существительным: медиа НЕТ.
NEGATION = re.compile(r"^(?:no|without|не|нет|без|никаких|don't|dont|haven't|lack)$")

#: Глаголы работы НАД готовым: объект в окне после них — вход.
WORK_VERB = re.compile(
    r"^(?:translate|translating|dub|dubbing|lip-?sync|lipsync|upscale|upscaling|enhance|re-?voice"
    r"|revoice|replace|replacing|swap|swapping|edit|editing|retouch|animate|animating|subtitle"
    r"|перевед[а-яё]*|переве[сд]ти|дублир[а-яё]*|переозвуч[а-яё]*|замени[а-яё]*|замен[а-яё]*"
    r"|подмени[а-яё]*|апскейл[а-яё]*|улучши[а-яё]*|отредактир[а-яё]*|редактир[а-яё]*"
    r"|оживи[а-яё]*|анимир[а-яё]*)$"
)
#: Глаголы и обороты ПРОИЗВОДСТВА: в клаузе с ними существительное медиа —
#: заказ, а не вход («make our video from scratch»).
MAKE_WORDS = re.compile(
    r"\b(?:generate|create|make|produce|render|from scratch|сгенерир|созда|сделай|сделать|сними|снять"
    r"|с нуля)"
)
#: Предлог материала перед притяжательным спасает его и в клаузе заказа:
#: «make a dub FROM our video».
MATERIAL_PREP = re.compile(r"^(?:from|on|over|in|into|using|of|под|на|из|по|в|с|со)$")

ANIMATE = re.compile(
    r"\banimat(?:e|es|ed|ing)\b|bring (?:\w+ ){0,3}to life|make (?:\w+ ){0,2}move|оживи|оживл|ожив[ие]т|анимир"
)
FACE_REPLACE = re.compile(
    r"(?:replac\w*|swap\w*|подмен\w*|замен\w*)\s+(?:[\w'’-]+\s+){0,3}?"
    r"(?:face|faces|actor|actress|character|person|presenter|лиц[оаеу]?|актёр\w*|актер\w*|персонаж\w*|геро\w*|ведущ\w*)"
    r"|(?:face|faces|actor|character|лиц[оаеу]?|актёр\w*|актер\w*|персонаж\w*)['’s]*\s+(?:[\w-]+\s+){0,2}?"
    r"(?:replace\w*|swap\w*|замен\w*)|face[ -]?swap"
)
DUB = re.compile(
    r"\btranslat\w*|\bdub(?:bing|bed|s)?\b|\bre-?voice|\blocali[sz]\w*|перевед\w*|переве[сд]ти|перевод\w*"
    r"|дубл[яи]\w*|переозвуч\w*|локализ\w*"
)
#: Аватар — ЯВНО названный: «avatar», «talking head», «говорящая голова».
#: «Говорящий персонаж» сюда НЕ взят: персонажа в сцене делает видеомодель
#: (с нативным звуком или липсинком), а не аватар-продукт.
AVATAR = re.compile(r"\bavatars?\b|talking[ -]heads?|аватар\w*|говорящ\w+ голов\w*")
LIPSYNC = re.compile(r"lip[ -]?sync|lipsync|липсинк|губ[ыа]?\b|синхрон\w* губ")
UPSCALE = re.compile(r"upscal\w*|super[ -]resolution|апскейл\w*|апскел\w*|повы\w+ разрешени|увелич\w+ разрешени")
EDIT = re.compile(r"\bedit (?:the |my |our |this )?(?:photo|image|picture)|retouch|inpaint|отретуш|отредактир\w* (?:фото|картин|изображ)")

SPEECH = re.compile(
    r"\bvoice\w*|narrat\w*|\bspeak\w*|\bspoken\b|\bsays?\b|\bdialog\w*|\bdialogue|\btalk\w*|\btts\b"
    r"|голос\w*|озвуч\w*|диктор\w*|\bречь|говор\w*|произнос\w*|зачитыва\w*|начитк\w*"
)
OFFSCREEN = re.compile(r"voice[ -]?over|narrat\w*|закадр\w*|за кадром|диктор\w*")
MUSIC = re.compile(r"\bmusic\w*|\bsong\w*|soundtrack|\bjingle|музык\w*|песн\w*|саундтрек\w*|джингл\w*")
SFX = re.compile(r"sound effects?|\bsfx\b|foley|ambien\w*|шумы|звуков\w+ эффект\w*|фонов\w+ звук\w*")
NO_AUDIO = re.compile(
    r"\bno (?:audio|sound)\b|without (?:any )?(?:audio|sound)|\bsilent\b|\bmuted?\b|без звука|без аудио"
    r"|беззвуч\w*|звук не нуж\w*"
)
NATIVE = re.compile(
    r"native(?:ly)?[ -](?:audio|sound)|with (?:its own|generated|built-in) (?:audio|sound)"
    r"|нативн\w*\s+(?:звук|аудио)|встроенн\w*\s+(?:звук|аудио)"
)
#: Обороты, при которых голос НЕ звучит вовсе: «no voice», «без голоса».
NO_SPEECH = re.compile(r"\bno (?:voice|speech|narration|dialogue)|without (?:voice|speech)|без (?:голоса|речи|слов|озвучки)")
NO_MUSIC = re.compile(r"\bno music|without music|без музык")

VIDEO_WORDS = re.compile(
    r"\bvideos?\b|\bclips?\b|footage|\breels?\b|\bads?\b|commercial|promo\b|trailer|teaser|b-?roll"
    r"|\banimation\b|\bcinematic\b|\bshort film|(?<![а-яё])видео(?:ролик|файл|запис)?(?![а-яё])|ролик|клип"
    r"|реклам|трейлер|тизер|анимац"
)
IMAGE_WORDS = re.compile(
    r"\bimages?\b|\bpictures?\b|\bposters?\b|\bkeyframes?\b|key frames?|\bstills?\b|illustrat\w*|\bphotos?\b"
    r"|\bbanners?\b|\bthumbnails?\b|\bshots?\b|картин\w*|изображени\w*|постер\w*|ключев\w* кадр\w*|иллюстрац\w*"
    r"|баннер\w*|обложк\w*|\bфото\b"
)
#: Назначение: «for an ad», «для ролика» — для чего делается, а не что.
PURPOSE = re.compile(
    r"\b(?:for|для)\s+(?:an?\s+|the\s+|our\s+|my\s+|нашего\s+|моего\s+)?(?:[\w-]+\s+){0,2}?"
    r"(?:ads?|videos?|clips?|reels?|commercials?|ролик[а-яё]*|видео|реклам[а-яё]*|клип[а-яё]*)\b"
)

#: Голова брифа — ТОЛЬКО звук: тогда длительность — длина дорожки, а не ролика.
AUDIO_ONLY_HEAD = re.compile(
    r"\bpodcast|audiobook|\bjingle|\bsong\b|soundtrack|\bvoiceover\b|\bvoice-over\b|\bnarration\b"
    r"|\bmusic\b|\binstrumental|sound effects?|\bsfx\b"
    r"|подкаст|аудиокниг|джингл|песн\w*|саундтрек|озвучк\w*|начитк\w*|музык\w*|звуков\w+ эффект\w*"
)
VISUAL_STYLE = re.compile(
    r"\banime\b|\bcartoon|\b3d\b|photoreal\w*|\brealistic|\bcinematic|\bstop[- ]motion|\bclaymation"
    r"|\bpixar|аниме|мульт\w*|кинематограф\w*|фотореал\w*"
)

PEOPLE = (
    r"(?:characters?|persons?|people|fighters?|heroe?s?|actors?|actress(?:es)?|presenters?|hosts?"
    r"|mascots?|men|man|women|woman|girls?|boys?|guys?|warriors?|boxers?|athletes?|influencers?"
    r"|avatars?|speakers?|бойц[а-яё]*|бо[её]ц|персонаж[а-яё]*|геро[а-яё]*|человек[а-яё]*|люд[а-яё]*"
    r"|актёр[а-яё]*|актер[а-яё]*|актрис[а-яё]*|ведущ[а-яё]*|девушк[а-яё]*|парн[а-яё]*|мужчин[а-яё]*"
    r"|женщин[а-яё]*|спортсмен[а-яё]*|боксёр[а-яё]*|боксер[а-яё]*)"
)
_ЛЮДИ_СЧЁТ = re.compile(
    r"(?<![\w.])(?P<n>" + _ЧИСЛО + r")\s+(?:[a-zа-яё-]+\s+){0,1}?" + PEOPLE + r"(?![a-zа-яё])"
)
#: Множественное число «бойцы/fighters» без числа — уже двое.
_ЛЮДИ_МНОГО = re.compile(
    r"\b(?:fighters|characters|heroes|actors|warriors|boxers|rivals|opponents|athletes)\b"
    r"|\bvs\.?\b|\bversus\b|бойц(?:ы|ов|ами)|персонаж(?:и|ей|ами)|геро(?:и|ев|ями)|актёр(?:ы|ов)"
    r"|актер(?:ы|ов)|соперник(?:и|ов)"
)

CHEAPEST = re.compile(r"cheapest|\bcheap\b|lowest (?:cost|price)|budget[- ]friendly|as cheap|дешев\w*|дешёв\w*|подешевле|эконом\w*")
QUALITY = re.compile(r"best quality|highest quality|top quality|max(?:imum)? quality|premium|лучш\w+ качеств\w*|максимальн\w+ качеств\w*|качественн\w*")
SELF_HOST = re.compile(r"self[- ]?host\w*|open[- ]weights?|on (?:my|our) (?:own )?(?:gpu|server|machine)|локальн\w*|на сво\w+ (?:сервер|gpu|видеокарт)")
_GPU = re.compile(r"\b(rtx ?\d{4}\w*|a100|h100|h200|l40s?|a6000|a10g?|t4|4090|3090|5090)\b")
_VRAM = re.compile(r"(\d{1,3})\s*gb(?:\s*(?:of\s*)?vram)?")

_ТОКЕН = re.compile(r"[a-zа-яё0-9][a-zа-яё0-9'’.-]*[a-zа-яё0-9]|[a-zа-яё0-9]")
_КЛАУЗА = re.compile(r"[,;:.!?\n]|\s—\s|\s-\s|\bthen\b|\bзатем\b|\bпотом\b")


#: Что выходит у работы, когда она названа (выход шире названного не бывает).
TASK_OUTPUTS: dict[str, tuple[str, ...]] = {
    "avatar": ("video", "speech"),
    "animate": ("video",),
    "lipsync": ("video",),
    "face-replace": ("video",),
    "dub-translate": ("video", "speech"),
}

#: Стили, которые НЕ снимают, а генерируют: бриф с ними ответил на «видео уже
#: снято?» сам. «cinematic»/«realistic» сюда не входят — так снимают тоже.
GENERATED_STYLE = re.compile(
    r"\banime\b|\bcartoon|\bclaymation|\bstop[- ]motion|\b3d\b|\bpixar|photoreal\w*|\bwatercolou?r"
    r"|\blow[- ]poly|\bvoxel|аниме|мульт\w*|фотореал\w*|акварел\w*|пластилин\w*"
)


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _tokens(text: str) -> list[str]:
    return [t.strip(".'’") or t for t in _ТОКЕН.findall(text)]


def _число(слово: str) -> int:
    return int(слово) if слово.isdigit() else NUMBER_WORDS[слово]


@dataclass(frozen=True)
class Spec:
    """Что заказано. None/пусто — не известно; `source` говорит, откуда каждое поле."""

    task: str | None = None
    outputs: tuple[str, ...] = ()
    duration_s: float | None = None
    shots: int | None = None
    per_shot_s: float | None = None
    characters: int | None = None
    resolution: str | None = None
    aspect: str | None = None
    fps: int | None = None
    audio: str | None = None
    languages: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    #: Входы, о которых сказано «нет» («without a photo», «фото нет»).
    absent: tuple[str, ...] = ()
    objective: str | None = None
    budget_usd: float | None = None
    self_host: Mapping[str, Any] | None = None
    jurisdiction: tuple[str, ...] = ()
    source: Mapping[str, str] = field(default_factory=dict)
    #: Допущения, сделанные за заказчика, словами (печатаются в `echo`).
    assumptions: tuple[str, ...] = ()
    #: Почему число шотов такое (явный счёт, «each», деление длительности).
    shots_basis: str = ""

    def has(self, имя: str) -> bool:
        значение = getattr(self, имя)
        return значение not in (None, (), {}, "")


# --- spec от вызывающего -------------------------------------------------------


def _список(значение: Any) -> list[Any]:
    if значение is None:
        return []
    if isinstance(значение, (list, tuple, set, frozenset)):
        return list(значение)
    return [значение]


def _положительное(значение: Any, целое: bool = False) -> float | int | None:
    if isinstance(значение, bool) or not isinstance(значение, (int, float)):
        raise ValueError("must be a number")
    if math.isnan(значение) or math.isinf(значение) or значение <= 0:
        raise ValueError("must be a finite number above 0")
    if целое:
        if int(значение) != значение:
            raise ValueError("must be a whole number")
        return int(значение)
    return float(значение)


def parse_spec(raw: Mapping[str, Any] | None) -> tuple[Spec, list[str]]:
    """`spec` вызывающего -> (Spec, ошибки). Ошибка не роняет: поле пропускается и называется."""
    if raw is None:
        return Spec(), []
    if not isinstance(raw, Mapping):
        return Spec(), [f"spec must be an object with fields {', '.join(SPEC_FIELDS)}, got {type(raw).__name__}"]
    ошибки: list[str] = []
    поля: dict[str, Any] = {}
    for ключ in raw:
        if ключ not in SPEC_FIELDS:
            ошибки.append(f"spec.{ключ}: unknown field (known: {', '.join(SPEC_FIELDS)})")

    def _enum(ключ: str, допустимо: tuple[str, ...], много: bool = False) -> None:
        if ключ not in raw or raw[ключ] is None:
            return
        значения = [str(з).strip().lower() for з in _список(raw[ключ])]
        плохие = [з for з in значения if з not in допустимо]
        if плохие:
            ошибки.append(f"spec.{ключ}: {', '.join(плохие)} not in {', '.join(допустимо)}")
            значения = [з for з in значения if з in допустимо]
        if много:
            поля[ключ] = tuple(dict.fromkeys(значения))
        elif значения:
            поля[ключ] = значения[0]

    _enum("task", TASKS)
    _enum("outputs", OUTPUTS, много=True)
    _enum("audio", AUDIO_MODES)
    _enum("inputs", INPUT_KINDS, много=True)
    _enum("objective", OBJECTIVES)
    for ключ, целое in (
        ("duration_s", False),
        ("per_shot_s", False),
        ("shots", True),
        ("characters", True),
        ("fps", True),
    ):
        if raw.get(ключ) is None:
            continue
        try:
            поля[ключ] = _положительное(raw[ключ], целое)
        except ValueError as e:
            ошибки.append(f"spec.{ключ}={raw[ключ]!r}: {e}")
    if raw.get("budget_usd") is not None:
        б = raw["budget_usd"]
        if isinstance(б, bool) or not isinstance(б, (int, float)) or math.isnan(б) or math.isinf(б) or б < 0:
            ошибки.append(f"spec.budget_usd={б!r}: must be a finite number, 0 or more")
        else:
            поля["budget_usd"] = float(б)
    if raw.get("resolution") is not None:
        метка = resolution_label(str(raw["resolution"]))
        if метка is None:
            ошибки.append(
                f"spec.resolution={raw['resolution']!r}: not a resolution (use one of "
                f"{', '.join(RESOLUTIONS)} or WIDTHxHEIGHT)"
            )
        else:
            поля["resolution"] = метка
    if raw.get("aspect") is not None:
        a = str(raw["aspect"]).strip().lower()
        a = {"vertical": "9:16", "horizontal": "16:9", "landscape": "16:9", "square": "1:1"}.get(a, a)
        if not _ASPECT.fullmatch(a):
            ошибки.append(f"spec.aspect={raw['aspect']!r}: use W:H such as 9:16, 16:9, 1:1, 4:5")
        else:
            поля["aspect"] = a
    if raw.get("languages") is not None:
        языки = []
        for я in _список(raw["languages"]):
            найдено = pl.languages_in(str(я)) or (
                {str(я).strip().lower()} if str(я).strip().lower() in pl.LANGUAGE_FORMS else set()
            )
            if not найдено:
                ошибки.append(f"spec.languages: {я!r} is not a language we know ({', '.join(pl.LANGUAGE_FORMS)})")
            языки.extend(sorted(найдено))
        поля["languages"] = tuple(dict.fromkeys(языки))
    if raw.get("jurisdiction") is not None:
        поля["jurisdiction"] = tuple(
            sorted({к for з in _список(raw["jurisdiction"]) for к in pl.jurisdictions_in(str(з))} | {
                str(з).upper() for з in _список(raw["jurisdiction"]) if str(з).upper() in pl.JURISDICTIONS
            })
        )
    if raw.get("self_host") is not None:
        sh = raw["self_host"]
        if not isinstance(sh, Mapping):
            ошибки.append("spec.self_host: must be an object {gpu, vram_gb}")
        else:
            поля["self_host"] = {"gpu": sh.get("gpu"), "vram_gb": sh.get("vram_gb")}
    if поля.get("per_shot_s") and поля.get("shots") and not поля.get("duration_s"):
        поля["duration_s"] = поля["per_shot_s"] * поля["shots"]
    return Spec(**поля, source={к: SOURCE_SPEC for к in поля}), ошибки


def resolution_label(текст: str) -> str | None:
    низ = _norm(текст).replace("к", "k")
    м = _WXH.search(низ)
    if м:
        return f"{м.group(1)}x{м.group(2)}"
    for метка in RESOLUTIONS:
        if re.search(rf"(?<![a-z0-9]){re.escape(метка)}(?![a-z0-9])", низ):
            return метка
    return None


def frame(spec: Spec) -> tuple[int, int] | None:
    """Кадр (ширина, высота) из разрешения и соотношения сторон. Не назван — None."""
    if not spec.resolution:
        return None
    м = _WXH.fullmatch(spec.resolution)
    if м:
        return int(м.group(1)), int(м.group(2))
    длинная, короткая = RESOLUTIONS[spec.resolution]
    if spec.aspect in ("9:16", "4:5", "3:4", "2:3"):
        return короткая, длинная
    if spec.aspect == "1:1":
        return короткая, короткая
    return длинная, короткая


# --- разбор текста по структуре -----------------------------------------------


def _в_окне(токены: list[str], i: int, образец: re.Pattern[str], окно: int) -> int:
    """Индекс ближайшего токена ПЕРЕД i (не дальше `окно` слов между), который совпал; -1 — нет."""
    for j in range(i - 1, max(-1, i - окно - 2), -1):
        if образец.match(токены[j]):
            return j
    return -1


def _входы(низ: str) -> tuple[set[str], set[str]]:
    """Какие медиа у заказчика ЕСТЬ и о каких сказано «нет» — по окну слов, клаузами."""
    есть: set[str] = set()
    нет: set[str] = set()
    for клауза in _КЛАУЗА.split(низ):
        токены = _tokens(клауза)
        заказ = bool(MAKE_WORDS.search(клауза))
        for i, т in enumerate(токены):
            вид = (
                "video"
                if VIDEO_NOUN.match(т)
                else "photo"
                if PHOTO_NOUN.match(т)
                else "audio"
                if AUDIO_NOUN.match(т)
                else "script"
                if SCRIPT_NOUN.match(т)
                else ""
            )
            if not вид:
                continue
            if _в_окне(токены, i, NEGATION, 2) >= 0 or (i + 1 < len(токены) and токены[i + 1] in ("нет", "missing")):
                нет.add(вид)
                continue
            p = _в_окне(токены, i, POSSESSIVE, POSSESSIVE_WINDOW)
            # В клаузе заказа притяжательное засчитывается только после
            # предлога материала: «make OUR video» — заказ, «dub FROM our
            # video» — вход.
            if p >= 0 and (not заказ or (p > 0 and MATERIAL_PREP.match(токены[p - 1]))):
                есть.add(вид)
                continue
            # «the video I uploaded», «footage we shot», «видео, которое я снял»:
            # владение сказано ПОСЛЕ существительного.
            if OWNED_AFTER.match(" ".join(токены[i + 1 : i + 1 + OBJECT_WINDOW])):
                есть.add(вид)
                continue
            v = _в_окне(токены, i, WORK_VERB, OBJECT_WINDOW)
            if v >= 0 and not заказ:
                есть.add(вид)
    return есть - нет, нет


def _длительности(низ: str) -> tuple[float | None, float | None]:
    """(всего, на шот): число с единицей; «each/каждый» в окне делает его длиной шота."""
    всего: float | None = None
    шот: float | None = None
    for м in _ДЛИТЕЛЬНОСТЬ.finditer(низ):
        до = низ[: м.start()]
        после = низ[м.end() :]
        # `m`/`s` после чисел-разрешений и денег — не время: «$4m», «4s» после «$».
        if до.rstrip().endswith("$") or re.match(r"\s*(?:fps|p\b)", после):
            continue
        число = float(м.group("n").replace(",", "."))
        секунды = число * (60.0 if м.group("u").startswith(("min", "мин")) else 1.0)
        # РАСПРЕДЕЛИТЕЛЬНОЕ СЛОВО В ТОЙ ЖЕ КЛАУЗЕ делает число длиной ШОТА:
        # «bring each one to life for 6 seconds», «3s per clip», «каждый по 4 с».
        # «по»/«per» без счётного слова — только вплотную (`EACH_WINDOW` слов):
        # «по 5 секунд», но не «по брифу … 30 секунд».
        клауза_до = _КЛАУЗА.split(до)[-1]
        клауза_после = _КЛАУЗА.split(после)[0]
        перед = _tokens(клауза_до)[-(EACH_WINDOW + 1) :]
        каждый = (
            bool(DISTRIBUTIVE.search(клауза_до))
            or bool(DISTRIBUTIVE.search(клауза_после))
            or any(_EACH.match(т) for т in перед)
        )
        if каждый and шот is None:
            шот = секунды
        elif not каждый and всего is None:
            всего = секунды
    return всего, шот


def _разрешение(низ: str) -> str | None:
    return resolution_label(низ)


def _соотношение(низ: str) -> str | None:
    м = _ASPECT.search(низ)
    if м:
        return м.group(1)
    if VERTICAL.search(низ):
        return "9:16"
    if SQUARE.search(низ):
        return "1:1"
    if HORIZONTAL.search(низ):
        return "16:9"
    return None


def _языки(низ: str) -> tuple[str, ...]:
    """Язык РЕЧИ на выходе: «to/into/на <язык>» — целевой; иначе все названные."""
    названы = pl.languages_in(низ)
    if not названы:
        return ()
    целевые = {
        я
        for я, формы in pl.LANGUAGE_FORMS.items()
        if я in названы
        and any(
            re.search(rf"(?:\bto|\binto|\bна|\bпо-)\s*{re.escape(ф)}", низ)
            or re.search(rf"\bin\s+{re.escape(ф)}", низ)
            for ф in формы
        )
    }
    return tuple(sorted(целевые or названы))


def from_text(brief: str) -> Spec:
    """Спецификация из СТРУКТУРЫ текста. Чего не видно — остаётся None."""
    низ = _norm(brief)
    if not низ:
        return Spec()
    поля: dict[str, Any] = {}
    всего, шот = _длительности(низ)
    счёт = _СЧЁТ.search(низ)
    if счёт is not None:
        n = _число(счёт.group("n"))
        if n >= 1:
            поля["shots"] = n
    if шот is not None:
        поля["per_shot_s"] = шот
    if всего is not None:
        поля["duration_s"] = всего
    elif шот is not None and поля.get("shots"):
        поля["duration_s"] = шот * поля["shots"]
    elif шот is not None:
        поля["duration_s"] = шот
    if (р := _разрешение(низ)) is not None:
        поля["resolution"] = р
    if (а := _соотношение(низ)) is not None:
        поля["aspect"] = а
    if (f := _FPS.search(низ)) is not None:
        поля["fps"] = int(f.group(1))
    if (л := _ЛЮДИ_СЧЁТ.search(низ)) is not None:
        поля["characters"] = _число(л.group("n"))
    elif _ЛЮДИ_МНОГО.search(низ):
        поля["characters"] = MULTI_CHARACTER_MIN
    есть, нет = _входы(низ)
    if есть:
        поля["inputs"] = tuple(в for в in INPUT_KINDS if в in есть)
    if нет:
        поля["absent"] = tuple(в for в in INPUT_KINDS if в in нет)
    if (я := _языки(низ)):
        поля["languages"] = я

    # Звук.
    речь = bool(SPEECH.search(низ)) and not NO_SPEECH.search(низ)
    if NO_AUDIO.search(низ):
        поля["audio"] = "none"
        речь = False
    elif NATIVE.search(низ):
        поля["audio"] = "native"
    elif речь and OFFSCREEN.search(низ):
        поля["audio"] = "voiceover"

    # Что выходит.
    выходы: list[str] = []
    # «… for an ad», «для ролика» — НАЗНАЧЕНИЕ, а не заказ видео: «30 s music
    # for an ad» — дорожка, «keyframes for an MMA ad» — кадры.
    без_назначения = PURPOSE.sub(" ", низ)
    видео_слова = bool(VIDEO_WORDS.search(без_назначения))
    стиль = bool(VISUAL_STYLE.search(низ))
    движение = bool(ANIMATE.search(низ)) or "fps" in поля
    только_звук = bool(AUDIO_ONLY_HEAD.search(низ)) and not видео_слова and not стиль
    картинки = bool(IMAGE_WORDS.search(без_назначения))
    if not только_звук and (
        видео_слова
        or движение
        or (поля.get("duration_s") and (стиль or not картинки) and not (картинки and not стиль))
    ):
        выходы.append("video")
    if картинки and "video" not in выходы and not только_звук:
        выходы.append("image")
    if речь:
        выходы.append("speech")
    if MUSIC.search(низ) and not NO_MUSIC.search(низ):
        выходы.append("music")
    if SFX.search(низ):
        выходы.append("sfx")
    if выходы:
        поля["outputs"] = tuple(в for в in OUTPUTS if в in выходы)

    # Какая работа.
    задача = None
    if FACE_REPLACE.search(низ):
        задача = "face-replace"
    elif DUB.search(низ) and ("video" in есть or "audio" in есть):
        задача = "dub-translate"
    elif AVATAR.search(низ):
        задача = "avatar"
    elif LIPSYNC.search(низ) and "video" in есть:
        задача = "lipsync"
    elif UPSCALE.search(низ) and (есть & {"video", "photo"}):
        задача = "upscale"
    elif EDIT.search(низ):
        задача = "edit"
    elif ANIMATE.search(низ):
        задача = "animate"
    elif выходы:
        задача = "generate"
    if задача:
        поля["task"] = задача
        # Работа сама говорит, что выходит: аватар — видео с речью, а «фото
        # нет» в брифе о говорящей голове — не заказ картинки.
        if задача in TASK_OUTPUTS:
            поля["outputs"] = tuple(
                в
                for в in OUTPUTS
                if в in TASK_OUTPUTS[задача] or (в in поля.get("outputs", ()) and в != "image")
            )

    if CHEAPEST.search(низ):
        поля["objective"] = "cheapest"
    elif QUALITY.search(низ):
        поля["objective"] = "quality"
    if SELF_HOST.search(низ):
        г = _GPU.search(низ)
        в = _VRAM.search(низ)
        поля["self_host"] = {"gpu": г.group(1) if г else None, "vram_gb": int(в.group(1)) if в else None}
    # Юрисдикция — по тексту БЕЗ названий языков: «Japanese voice» — язык
    # речи, а не страна показа.
    без_языков = низ
    for формы in pl.LANGUAGE_FORMS.values():
        for ф in формы:
            без_языков = re.sub(rf"(?<![a-zа-яё]){re.escape(ф)}[a-zа-яё]*", " ", без_языков)
    if (ю := pl.jurisdictions_in(без_языков)):
        поля["jurisdiction"] = tuple(ю)
    return Spec(**поля, source={к: SOURCE_TEXT for к in поля if к != "absent"})


def resolve(brief: str, raw: Mapping[str, Any] | None = None) -> tuple[Spec, list[str]]:
    """Поля `spec` поверх разобранного из текста. Возвращает (итог, ошибки spec)."""
    от_вызова, ошибки = parse_spec(raw)
    из_текста = from_text(brief)
    поля: dict[str, Any] = {}
    источник: dict[str, str] = {}
    for имя in SPEC_FIELDS + ("absent",):
        if от_вызова.has(имя):
            поля[имя] = getattr(от_вызова, имя)
            источник[имя] = SOURCE_SPEC
        elif из_текста.has(имя):
            поля[имя] = getattr(из_текста, имя)
            if имя != "absent":
                источник[имя] = SOURCE_TEXT
    # Входы, названные вызывающим, — ПОЛНЫЙ список (и пустой тоже): «нет» о прочих.
    if isinstance(raw, Mapping) and raw.get("inputs") is not None:
        поля["inputs"] = от_вызова.inputs
        источник["inputs"] = SOURCE_SPEC
        поля["absent"] = tuple(в for в in INPUT_KINDS if в not in от_вызова.inputs)
    # Шоты по одному полю: «shots» из текста при «per_shot_s» из spec и т.п.
    if поля.get("per_shot_s") and поля.get("shots") and источник.get("duration_s") != SOURCE_SPEC:
        поля["duration_s"] = поля["per_shot_s"] * поля["shots"]
        источник["duration_s"] = источник.get("per_shot_s", SOURCE_TEXT)
    return Spec(**поля, source=источник), ошибки


# --- маршрут -------------------------------------------------------------------

#: Задачи, по которым маршрут СПЕЦИФИКАЦИИ старше вывода подсказками, и вход,
#: который для этого должен БЫТЬ: подсказки систематически собирали чужой план
#: — дубляж + генерация видео и «уже снято?» для перевода СВОЕГО видео, ни
#: одного шага для замены лица в своём видео.
ROUTE_FIRST_WITH: dict[str, str] = {"dub-translate": "video", "face-replace": "video"}

#: Задачи, по которым маршрут старше, когда этих входов НЕТ: аватар без
#: снимка и без видео подсказками собирался как TTS + t2v + липсинк, а
#: делается как кадр -> говорящий аватар.
ROUTE_FIRST_WITHOUT: dict[str, tuple[str, ...]] = {"avatar": ("video", "photo")}


#: Монтаж готового — чужое ремесло (как «смонтировать» у `clarify`): маршрут
#: его не «понимает» генерацией.
MONTAGE = re.compile(r"edit (?:[\w-]+ ){0,3}?together|\bmontage|монтаж|смонтир|\bre-?cut\b|\binto a [\w-]+ (?:minute|second) cut")


def route_first(spec: "Spec") -> bool:
    """Старше ли маршрут спецификации подсказок на этой задаче (см. словари выше)."""
    входы = set(spec.inputs)
    if spec.task in ROUTE_FIRST_WITH:
        return ROUTE_FIRST_WITH[spec.task] in входы
    if spec.task in ROUTE_FIRST_WITHOUT:
        return not (входы & set(ROUTE_FIRST_WITHOUT[spec.task]))
    return False


@dataclass(frozen=True)
class Маршрут:
    """Шаги (имена операций плановщика) и пометка каждого; либо вопрос, чего не хватает."""

    шаги: tuple[str, ...] = ()
    пометки: Mapping[str, str] = field(default_factory=dict)
    #: (ось, текст ru, текст en, варианты ru, варианты en) — чего не хватает.
    нехватка: tuple[str, str, str, tuple[str, ...], tuple[str, ...]] | None = None


def _нехватка_видео(задача: str) -> tuple[str, str, str, tuple[str, ...], tuple[str, ...]]:
    return (
        "вход_задачи",
        f"для задачи «{задача}» нужно ВАШЕ видео — приложите файл (creative) или скажите, что видео есть",
        f"the task '{задача}' works on YOUR video — attach it (creative=path) or pass spec.inputs=['video']",
        ("видео есть — приложу", "видео нет — сделать с нуля"),
        ("I have the video and will attach it", "there is no video — make one from scratch"),
    )


#: Пометки маршрута — по-русски и по-английски (английский бриф получает план
#: по-английски, `planner._по_английски`).
NOTE_DUB_LIPS = "перевод готового видео: губы под новый язык (лиц в кадре нет — шаг снимается)"
NOTE_KEYFRAMES = "персонажей {n}: ключевой кадр на каждый шот, иначе лица разъезжаются от шота к шоту"
NOTES_EN: dict[str, str] = {
    NOTE_DUB_LIPS: "translating your own video: lip sync moves the lips to the new language (no faces on screen — drop the step)",
}


def note_en(ru: str) -> str | None:
    """Пометка маршрута по-английски; None — пометка не наша."""
    if ru in NOTES_EN:
        return NOTES_EN[ru]
    м = re.fullmatch(NOTE_KEYFRAMES.replace("{n}", r"(\d+)"), ru)
    if м:
        return f"{м.group(1)} characters: a keyframe per shot, otherwise faces drift from shot to shot"
    return None


def route(spec: Spec) -> Маршрут:
    """Шаги по спецификации. Пусто без нехватки — спецификация ничего не заказывает.

    Маршрут называет ГЛАВНЫЕ шаги; входы, которых им не хватает (кадр для
    аватара, речь для липсинка), дописывает замыкание плановщика
    (`planner.замкнуть`) — и помечает их как дописанные, как и в пути подсказок.
    """
    задача = spec.task
    входы = set(spec.inputs)
    выходы = set(spec.outputs)
    шаги: list[str] = []
    пометки: dict[str, str] = {}

    if задача == "face-replace":
        if "video" not in входы:
            return Маршрут(нехватка=_нехватка_видео(задача))
        # Новое лицо — РЕФЕРЕНС заказчика (вход шага `референс`, он у плана
        # есть всегда); принесён ли снимок, говорит допущение в `echo`.
        return Маршрут(("замена_персонажа",), {})
    if задача == "dub-translate":
        if "video" in входы:
            # Перевод готового ролика: речь переводится, губы под новый язык
            # двигает липсинк. Генерации видео нет — видео принесено.
            return Маршрут(("дубляж", "липсинк"), {"липсинк": NOTE_DUB_LIPS})
        if "audio" in входы:
            return Маршрут(("дубляж",), {})
        return Маршрут(нехватка=_нехватка_видео(задача))
    if задача == "avatar":
        # Снимок и речь, которых нет, дописывает замыкание: кадр персонажа ->
        # говорящий аватар, а не TTS + t2v + липсинк.
        return Маршрут(("говорящий_аватар",), {})
    if задача == "animate":
        шаги.append("оживление")
    elif задача == "lipsync":
        if "video" in входы:
            return Маршрут(("липсинк",), {})
        if "photo" in входы:
            return Маршрут(("говорящий_аватар",), {})
        return Маршрут()
    elif задача == "upscale":
        if "video" in входы:
            return Маршрут(("апскейл",), {})
        if "photo" in входы:
            return Маршрут(("апскейл_изображения",), {})
        return Маршрут(нехватка=_нехватка_видео(задача))
    elif задача == "edit":
        if "photo" in входы:
            return Маршрут(("редактирование_изображения",), {})
        return Маршрут(
            нехватка=(
                "вход_задачи",
                "правка нужна по ВАШЕМУ снимку — приложите его",
                "editing works on YOUR image — attach it or pass spec.inputs=['photo']",
                ("снимок есть — приложу", "снимка нет — сгенерировать"),
                ("I have the image", "there is no image — generate one"),
            )
        )
    elif "video" in выходы:
        # generate (или задача не названа, но выход назван)
        if "video" in входы:
            # Видео принесено, а работа над ним не названа: генерировать
            # второе видео поверх своего — чужой план. Шагов нет.
            return Маршрут()
        if "photo" in входы:
            шаги.append("оживление")
        elif (spec.characters or 0) >= MULTI_CHARACTER_MIN:
            шаги += ["генерация_изображения", "оживление"]
            пометки["генерация_изображения"] = NOTE_KEYFRAMES.format(n=spec.characters)
        else:
            шаги.append("генерация_видео")
    elif "image" in выходы:
        шаги.append("генерация_изображения")
    if "speech" in выходы and spec.audio != "native" and "audio" not in входы:
        шаги.append("озвучка")
    if "music" in выходы:
        шаги.append("музыка")
    if "sfx" in выходы and spec.audio != "native":
        шаги.append("звук_фон")
    return Маршрут(tuple(dict.fromkeys(шаги)), пометки)


def shots(spec: Spec, max_run_s: float | None, клипов_нужно: bool) -> tuple[int, str]:
    """Сколько шотов и почему. 1 — один прогон.

    Порядок оснований: явное число; «each» над N принесёнными; длительность,
    делённая на предел прогона выбранной модели (только когда шоты нужны
    поштучно — `клипов_нужно`, например ключевые кадры многоперсонажного ролика).
    """
    if spec.shots:
        основание = "spec.shots" if spec.source.get("shots") == SOURCE_SPEC else "count named in the brief"
        return spec.shots, основание
    if клипов_нужно and spec.duration_s:
        предел = max_run_s or ASSUMED_SHOT_S
        n = max(1, math.ceil(spec.duration_s / предел))
        return n, (
            f"ceil({spec.duration_s:g} s / {предел:g} s max run of the chosen model)"
            if max_run_s
            else f"ceil({spec.duration_s:g} s / {ASSUMED_SHOT_S:g} s assumed shot — the model records no max run)"
        )
    return 1, ""


def with_defaults(spec: Spec, ролик: bool) -> Spec:
    """Допущения, сделанные за заказчика, — НАЗВАННЫЕ: разрешение видео, голос поверх картинки."""
    допущения = list(spec.assumptions)
    поля = {к: getattr(spec, к) for к in spec.__dataclass_fields__}
    источник = dict(spec.source)
    # Только когда видео ДЕЛАЕТ план: у принесённого видео кадр — его
    # собственный, и «1080p по умолчанию» дописал бы апскейл чужого ролика.
    if ролик and "video" in spec.outputs and not spec.resolution and "video" not in spec.inputs:
        поля["resolution"] = DEFAULT_VIDEO_RESOLUTION
        источник["resolution"] = SOURCE_DEFAULT
        допущения.append(
            f"resolution not named — {DEFAULT_VIDEO_RESOLUTION} assumed"
            + (" (9:16 ad standard)" if spec.aspect == "9:16" else " (delivery standard)")
            + "; pass spec.resolution to change"
        )
    if "speech" in spec.outputs and "video" in spec.outputs and spec.audio is None and spec.task in (None, "generate", "animate"):
        поля["audio"] = "voiceover"
        источник["audio"] = SOURCE_DEFAULT
        допущения.append(
            "the voice plays over the picture, nobody on screen moves their lips — "
            "pass spec.task='avatar' (or 'lipsync') for an on-screen speaker, or spec.audio='native'"
        )
    if spec.task == "face-replace" and "photo" not in spec.inputs:
        допущения.append(
            "the new face/character comes from YOUR reference image — none is named in the brief; "
            "attach it, or pass spec.inputs=['video', 'photo']"
        )
    поля["source"] = источник
    поля["assumptions"] = tuple(допущения)
    return Spec(**поля)


def echo(spec: Spec, steps: list[str] | tuple[str, ...] = ()) -> dict:
    """«Понято как»: каждое поле со значением и источником, допущения и как поправить."""
    поля = {
        имя: {"value": (list(з) if isinstance(з, tuple) else з), "from": spec.source.get(имя, SOURCE_TEXT)}
        for имя in SPEC_FIELDS
        if spec.has(имя) and (з := getattr(spec, имя)) is not None
    }
    не_понято = [
        имя
        for имя in ("task", "outputs", "duration_s", "resolution", "inputs", "languages")
        if not spec.has(имя)
    ]
    return {
        "fields": поля,
        "absent_inputs": list(spec.absent),
        "not_understood": не_понято,
        "shots_basis": spec.shots_basis,
        "assumptions": list(spec.assumptions),
        "steps": list(steps),
        "how_to_correct": (
            "call plan_pipeline again with spec={...}: any field named there overrides what was read "
            "from the text (fields: " + ", ".join(SPEC_FIELDS) + ")"
        ),
    }


#: Русские слова для того, чего не хватает (вопрос на языке брифа).
MISSING_RU: dict[str, str] = {
    "what should come out (video / image / speech / music / sound effects)": "что должно получиться (видео / картинка / речь / музыка / шумы)",
    "what you already have (photo, video, audio, script — or nothing)": "что у вас уже есть (фото, видео, аудио, текст — или ничего)",
    "which job to do with it (generate / animate / lip sync / dub / replace a face / avatar / upscale / edit)": "какую работу сделать (сгенерировать / оживить / липсинк / перевести / заменить лицо / аватар / апскейл / правка)",
}


def missing(spec: Spec) -> list[str]:
    """Чего не хватает, чтобы собрать план (для вопроса, когда шагов нет)."""
    нет: list[str] = []
    if not spec.outputs and not spec.task:
        нет.append("what should come out (video / image / speech / music / sound effects)")
    if not spec.inputs:
        нет.append("what you already have (photo, video, audio, script — or nothing)")
    return нет
