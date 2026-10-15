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
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from studio import endpoints as ep
from studio import hardneed as hn
from studio import pipeline as pl

# --- словари поля `spec` ---------------------------------------------------

OUTPUTS: tuple[str, ...] = ("video", "image", "speech", "music", "sfx", "text")
TASKS: tuple[str, ...] = (
    "generate",
    "animate",
    "lipsync",
    "dub-translate",
    "face-replace",
    "avatar",
    "upscale",
    "edit",
    # Пятый круг (реестр эндпоинтов): работы, которые маршрут знает только по
    # названию в спецификации — подсказками брифа они не выводятся (`ROUTE_TASKS`).
    "restore",
    "remove-background",
    "interpolate",
    "transcribe",
    "voice-clone",
    "turntable",
    "captions",
    # Шестой круг (вызывающий — языковая модель, она и понимает бриф): работы
    # над материалом заказчика и консистентные персонажи, которые прежде
    # собирались генерацией с нуля.
    "video-edit",
    "r2v",
    "music-visualiser",
    "sing-photo",
    "cut-to-shorts",
    # Седьмой круг: раскраска — НЕ реставрация (`seedvr2` чистит, но цвета не
    # добавляет); «отреставрировать и раскрасить» — цепочка ["restore", "colorize"].
    "colorize",
)
AUDIO_MODES: tuple[str, ...] = ("none", "native", "voiceover")
INPUT_KINDS: tuple[str, ...] = ("photo", "video", "audio", "script", "model-weights")
#: Вид входа в `spec.inputs[].kind` -> внутреннее имя (`INPUT_KINDS`). Слева —
#: словарь контракта шестого круга (video|image|audio|text|model-weights) и
#: прежние имена (photo, script), чтобы старый вызов не ломался.
SPEC_INPUT_KINDS: dict[str, str] = {
    "video": "video",
    "image": "photo",
    "photo": "photo",
    "audio": "audio",
    "text": "script",
    "script": "script",
    "model-weights": "model-weights",
}
#: Внутреннее имя входа -> имя в контракте (для черновика и эха).
INPUT_KIND_OUT: dict[str, str] = {
    "video": "video",
    "photo": "image",
    "audio": "audio",
    "script": "text",
    "model-weights": "model-weights",
}
#: Согласие и род заявления о человеке в кадре (`spec.people`, читает `screen`).
CONSENT_STATES: tuple[str, ...] = ("stated", "none", "unknown")
CLAIM_KINDS: tuple[str, ...] = ("none", "endorsement", "political", "news", "other")
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
    # Шестой круг.
    "budget",
    "people",
    "conditions",
    "open_weights",
    # Интеграция шестого круга: ЧТО правится в `video-edit` (`endpoints.EDIT_INTENTS`).
    "edit",
    # Седьмой круг: двигать ли губы под новую речь (дубляж). Не названо —
    # `lipsync_default`.
    "lipsync",
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
    r"(?<![\w.$:])(?P<n>" + _ЧИСЛО + r")"
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
    # 2.7K — ступень экшн-камер и дронов (2704x1520): так заказчик называет свой исходник.
    "2.7k": (2704, 1520),
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
#: «Качество важнее цены» — ТЕ ЖЕ формы, что у отбора (`hardneed.QUALITY_CUES`),
#: плюс две английские: цель, прочитанная здесь, и цель, по которой
#: `hardneed.Hard` требует родной кадр, — одно поле. «premium» и «качественный»
#: — описание кадра, а не цель отбора, и сюда не входят.
QUALITY = re.compile(
    "|".join((*hn.QUALITY_CUES, r"top quality", r"max(?:imum)? quality", r"лучш\w+ качеств\w*"))
)

_ТОКЕН = re.compile(r"[a-zа-яё0-9][a-zа-яё0-9'’.-]*[a-zа-яё0-9]|[a-zа-яё0-9]")
_КЛАУЗА = re.compile(r"[,;:.!?\n]|\s—\s|\s-\s|\bthen\b|\bзатем\b|\bпотом\b")


#: ЗАДАЧА -> (шаг, какой вход нужен, шаг при другом входе). КОНСТАНТА-РЕШЕНИЕ
#: пятого круга: работа над ГОТОВЫМ материалом заказчика, названная задачей
#: спецификации. Нужного входа нет — вопрос, а не выдуманный исходник. Шаги —
#: имена операций плановщика; кандидатов на них даёт реестр эндпоинтов по
#: работе (`planner.ФУНКЦИЯ_ОПЕРАЦИИ`), а не слова брифа.
ROUTE_TASKS: dict[str, tuple[tuple[str, str], ...]] = {
    "restore": (("video", "реставрация"),),
    "colorize": (("video", "раскраска"),),
    "interpolate": (("video", "интерполяция_кадров"),),
    "remove-background": (("photo", "удаление_фона"), ("video", "удаление_фона_видео")),
    "transcribe": (("audio", "расшифровка"), ("video", "расшифровка")),
    "captions": (("video", "расшифровка"),),
    "voice-clone": (("audio", "клонирование_голоса"),),
    "turntable": (("photo", "оборот_360"),),
}

#: Пометки шагов маршрута пятого круга: чего модель НЕ делает и кто делает это.
NOTE_CAPTIONS = "субтитры вжигает монтаж (ffmpeg) по расшифровке с таймингами — модели на это не нужно"

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
    # --- шестой круг -------------------------------------------------------
    #: Работы ПОСЛЕ главной (`task` списком: ["video-edit", "upscale"]).
    then_tasks: tuple[str, ...] = ()
    #: Входы подробно: {kind, owned, duration_s, count, resolution} — как
    #: назвал вызывающий (kind — внутреннее имя).
    input_items: tuple[Mapping[str, Any], ...] = ()
    #: Языки речи как ТЕГИ BCP-47 (`languages` — имена для отбора).
    language_tags: tuple[str, ...] = ()
    #: Бюджет, как назван: сумма и валюта ISO 4217; `budget_usd` — только
    #: если валюта — USD или курс записан (`RECORDED_RATES`).
    budget_amount: float | None = None
    budget_currency: str | None = None
    budget_note: str = ""
    #: Люди в кадре: {name, real, public_figure, consent, claim} (читает `screen`).
    people: tuple[Mapping[str, Any], ...] = ()
    #: Условия кадра свободными словами («profile face», «hands») — в отбор.
    conditions: tuple[str, ...] = ()
    #: Требуются открытые веса (без своего запуска тоже).
    open_weights: bool | None = None
    #: Что правится в `video-edit`: reframe | replace-object | remove-object |
    #: replace-sky | stabilise | relight | restyle (`endpoints.EDIT_INTENTS`).
    edit: tuple[str, ...] = ()
    #: Губы под новую речь (седьмой круг): True/False — сказано; None — `lipsync_default`.
    lipsync: bool | None = None

    def has(self, имя: str) -> bool:
        значение = getattr(self, имя)
        return значение not in (None, (), {}, "")


# --- языки: теги BCP-47 ----------------------------------------------------------

#: Синтаксис тега BCP-47 (RFC 5646), без реестра: язык 2–3 буквы (+ до трёх
#: расширений), письменность 4 буквы, регион 2 буквы или 3 цифры, варианты,
#: расширения, private use. КОНСТАНТА-РЕШЕНИЕ шестого круга: проверяется
#: ТОЛЬКО синтаксис — поддержку языка моделью судит план по записям о модели
#: (измерено / не измерено), а не список «языков, которые мы знаем». До него
#: казахский, польский и иврит отвергались ещё до плана (`spec_не_разобран`).
BCP47 = re.compile(
    r"^[a-z]{2,3}(?:-[a-z]{3}){0,3}(?:-[a-z]{4})?(?:-(?:[a-z]{2}|\d{3}))?"
    r"(?:-(?:[a-z\d]{5,8}|\d[a-z\d]{3}))*(?:-[a-wyz\d](?:-[a-z\d]{2,8})+)*(?:-x(?:-[a-z\d]{1,8})+)?$"
)

#: Первичный подтег -> имя языка, которым его знает база (`pipeline.LANGUAGE_FORMS`).
#: Язык вне этой таблицы остаётся ТЕГОМ: о нём в базе не записано ничего, и
#: поддержка его любой моделью — «не измерено», а не отказ.
CODE_TO_LANGUAGE: dict[str, str] = {
    "en": "english", "ru": "russian", "hi": "hindi", "te": "telugu", "ta": "tamil",
    "bn": "bengali", "zh": "chinese", "cmn": "chinese", "yue": "chinese", "ja": "japanese",
    "ko": "korean", "ar": "arabic", "es": "spanish", "fr": "french", "de": "german",
    "pt": "portuguese", "it": "italian", "tr": "turkish", "uk": "ukrainian", "vi": "vietnamese",
}  # fmt: skip

#: Имена языков ВНЕ словаря базы — для черновика из текста и для вызывающего,
#: написавшего имя вместо тега. Тег -> формы в тексте.
EXTRA_LANGUAGE_FORMS: dict[str, tuple[str, ...]] = {
    "kk": ("kazakh", "казахск"), "pl": ("polish", "польск"), "he": ("hebrew", "иврит"),
    "nl": ("dutch", "нидерландск", "голландск"), "sv": ("swedish", "шведск"),
    "el": ("greek", "греческ"), "cs": ("czech", "чешск"), "ro": ("romanian", "румынск"),
    "hu": ("hungarian", "венгерск"), "id": ("indonesian", "индонезийск"), "th": ("thai", "тайск"),
    "fa": ("persian", "farsi", "персидск"), "uz": ("uzbek", "узбекск"), "ka": ("georgian", "грузинск"),
    "hy": ("armenian", "армянск"), "fi": ("finnish", "финск"), "da": ("danish", "датск"),
    "no": ("norwegian", "норвежск"), "ms": ("malay", "малайск"), "fil": ("filipino", "tagalog"),
    "sw": ("swahili", "суахили"), "be": ("belarusian", "белорусск"), "az": ("azerbaijani", "азербайджанск"),
}  # fmt: skip

#: Имя языка базы -> тег (обратная `CODE_TO_LANGUAGE`).
LANGUAGE_TO_CODE: dict[str, str] = {
    "english": "en", "russian": "ru", "hindi": "hi", "telugu": "te", "tamil": "ta",
    "bengali": "bn", "chinese": "zh", "japanese": "ja", "korean": "ko", "arabic": "ar",
    "spanish": "es", "french": "fr", "german": "de", "portuguese": "pt", "italian": "it",
    "turkish": "tr", "ukrainian": "uk", "vietnamese": "vi", "indic": "hi",
}  # fmt: skip


def language_tag(значение: str) -> str | None:
    """Тег BCP-47 из тега или имени языка; None — не тег и не известное имя."""
    низ = str(значение or "").strip().replace("_", "-").lower()
    if низ in LANGUAGE_TO_CODE:
        return LANGUAGE_TO_CODE[низ]
    for тег, формы in EXTRA_LANGUAGE_FORMS.items():
        if низ in формы:
            return тег
    if BCP47.match(низ):
        # Каноническое написание RFC 5646: язык строчными, письменность с
        # заглавной, регион заглавными («pt-br» -> «pt-BR», «zh-hant» -> «zh-Hant»).
        части = низ.split("-")
        return "-".join(
            [части[0]]
            + [ч.title() if len(ч) == 4 and ч.isalpha() else ч.upper() if len(ч) == 2 else ч for ч in части[1:]]
        )
    return None


def language_name(тег: str) -> str:
    """Имя для отбора: язык базы, если он ей известен, иначе сам тег."""
    return CODE_TO_LANGUAGE.get(тег.split("-")[0], тег)


def languages_in_text(низ: str) -> tuple[str, ...]:
    """Теги языков, названных в тексте: словарь базы + `EXTRA_LANGUAGE_FORMS`."""
    теги = {LANGUAGE_TO_CODE[я] for я in pl.languages_in(низ) if я in LANGUAGE_TO_CODE}
    for тег, формы in EXTRA_LANGUAGE_FORMS.items():
        if any(re.search(rf"(?<![a-zа-яё]){re.escape(ф)}", низ) for ф in формы):
            теги.add(тег)
    return tuple(sorted(теги))


# --- соотношение сторон ------------------------------------------------------------

#: Любое W:H (или W/H) и одно десятичное число («2.39» = 2.39:1).
_ASPECT_FREE = re.compile(r"^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$|^(\d+(?:\.\d+)?)$")
#: Предел соотношения: уже 1:10 или шире 10:1 — не кадр, а опечатка.
ASPECT_LIMIT = 10.0


def aspect_label(значение: Any) -> str | None:
    """«2.39:1», «9:16», «2.39», «vertical» -> «W:H»; None — не соотношение."""
    a = str(значение).strip().lower()
    a = {"vertical": "9:16", "portrait": "9:16", "horizontal": "16:9", "landscape": "16:9", "square": "1:1"}.get(a, a)
    м = _ASPECT_FREE.match(a)
    if not м:
        return None
    w = float(м.group(1) or м.group(3))
    h = float(м.group(2) or 1)
    if w <= 0 or h <= 0 or not (1 / ASPECT_LIMIT <= w / h <= ASPECT_LIMIT):
        return None
    return f"{w:g}:{h:g}"


def aspect_ratio(метка: str | None) -> float | None:
    """W/H из метки «W:H»; None — метки нет."""
    if not метка:
        return None
    w, h = метка.split(":")
    return float(w) / float(h)


# --- деньги ---------------------------------------------------------------------

#: Курсы к USD, ЗАПИСАННЫЕ с источником и датой: валюта -> (usd за единицу,
#: источник, дата). ПУСТО НАМЕРЕННО: курса у нас не записано ни одного, а
#: выдуманный курс — выдуманный потолок. Валюта без записи — бюджет назван,
#: вердикта по нему нет, и это печатается.
RECORDED_RATES: dict[str, tuple[float, str, str]] = {}

ISO_CURRENCY = re.compile(r"^[A-Z]{3}$")

#: Знаки и слова валют в тексте -> код ISO 4217 (для черновика и для
#: `planner.budget_from`). Порядок — порядок поиска.
CURRENCY_WORDS: tuple[tuple[str, str], ...] = (
    ("USD", r"\$|us\$|usd|доллар\w*|долл\.?|бакс\w*|dollars?|bucks?"),
    ("EUR", r"€|eur|euros?|евро"),
    ("RUB", r"₽|rub|руб\.?|рубл\w*|roubles?|rubles?"),
    ("GBP", r"£|gbp|фунт\w*|pounds?"),
    ("KZT", r"₸|kzt|тенге|tenge"),
    ("UAH", r"₴|uah|гривн\w*|hryvni?a"),
    ("INR", r"₹|inr|рупи\w*|rupees?"),
    ("CNY", r"¥|cny|rmb|юан\w*|yuan"),
    ("JPY", r"jpy|иен\w*|yen"),
    ("PLN", r"pln|zł|zloty|злот\w*"),
    ("TRY", r"₺|lira|лир[аыу]"),
    ("ILS", r"₪|ils|nis|shekels?|шекел\w*"),
)
_СУММА = r"(\d[\d ]{0,12}?(?:[.,]\d{1,2})?)(?: ?(k|к|тыс\.?|тысяч\w*|thousand)(?![a-zа-яё]))?"


def money_in_text(текст: str) -> tuple[float, str] | None:
    """(сумма, ISO-код) — ЧИСЛО ВПЛОТНУЮ К ЗНАКУ ВАЛЮТЫ, а не первое в окне.

    НАЙДЕНО валидатором пятого круга: «9:16 … budget €12» читалось как 9 EUR
    (первое число в окне вокруг «€» — из соотношения сторон), «1:1, бюджет 100
    рублей» — как 1 RUB. Число берётся только примыкающее к знаку: знак перед
    («€12», «$ 4») или слово после («100 рублей», «12 EUR»), и не часть
    соотношения («9:16»).
    """
    низ = _norm(текст)
    for код, слова in CURRENCY_WORDS:
        перед = rf"(?<![\w])(?:{слова}) ?{_СУММА}(?![\d:])"
        после = rf"(?<![\d:.,]){_СУММА} ?(?:{слова})(?![a-zа-яё])"
        for м in re.finditer(rf"{перед}|{после}", низ):
            сырое = м.group(1) or м.group(3)
            тыс = м.group(2) or м.group(4)
            if not сырое or not сырое.strip():
                continue
            число = float(сырое.replace(" ", "").replace(",", "."))
            if тыс:
                число *= 1000
            return число, код
    return None


def budget_in_usd(сумма: float, валюта: str) -> tuple[float | None, str]:
    """(потолок в USD или None, нота). Перевод только по записанному курсу."""
    if валюта == "USD":
        return сумма, ""
    if валюта in RECORDED_RATES:
        курс, источник, дата = RECORDED_RATES[валюта]
        return сумма * курс, (
            f"budget {сумма:g} {валюта} = {сумма * курс:.2f} USD at the recorded rate {курс:g} USD/{валюта} "
            f"({источник}, {дата})"
        )
    return None, (
        f"budget named in {валюта} ({сумма:g} {валюта}); no {валюта}->USD rate is recorded and none is "
        "invented — the plan gives NO budget verdict. Pass the budget in USD to get one"
    )


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


#: Признак Apple silicon в имени «GPU»: единая память — НЕ видеопамять CUDA.
APPLE_SILICON = re.compile(
    r"\bapple\b|\bm[1-9](?:\s*(?:pro|max|ultra))?\b|\bmac(?:book|studio| ?mini| ?pro)?\b|\bmps\b|\bmlx\b"
)

NOTE_APPLE = (
    "Apple silicon: {mem} unified memory is NOT CUDA VRAM — candidates are not filtered by it; "
    "whether each model runs on MPS/MLX is unmeasured unless the base records it (see apple_silicon per step)"
)

_INPUT_FIELDS = frozenset({"kind", "owned", "duration_s", "count", "resolution", "note"})


def _входы_spec(raw: Any, ошибки: list[str]) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
    """`spec.inputs` -> (виды, подробные записи). Строка — прежняя форма: владение не названо."""
    виды: list[str] = []
    подробно: list[dict[str, Any]] = []
    for i, вход in enumerate(_список(raw)):
        if isinstance(вход, str):
            вид = SPEC_INPUT_KINDS.get(вход.strip().lower())
            if вид is None:
                ошибки.append(f"spec.inputs[{i}]: {вход!r} not in {', '.join(INPUT_KIND_OUT.values())}")
                continue
            виды.append(вид)
            подробно.append({"kind": вид, "owned": None})
            continue
        if not isinstance(вход, Mapping):
            ошибки.append(f"spec.inputs[{i}]: must be an object {{kind, owned, duration_s, count, resolution}}")
            continue
        лишние = set(вход) - _INPUT_FIELDS
        if лишние:
            ошибки.append(f"spec.inputs[{i}]: unknown field(s) {', '.join(sorted(лишние))}")
        вид = SPEC_INPUT_KINDS.get(str(вход.get("kind", "")).strip().lower())
        if вид is None:
            ошибки.append(
                f"spec.inputs[{i}].kind={вход.get('kind')!r}: not in {', '.join(INPUT_KIND_OUT.values())}"
            )
            continue
        запись: dict[str, Any] = {"kind": вид, "owned": None}
        if вход.get("owned") is not None:
            if not isinstance(вход["owned"], bool):
                ошибки.append(f"spec.inputs[{i}].owned={вход['owned']!r}: must be true or false")
            else:
                запись["owned"] = вход["owned"]
        for ключ, целое in (("duration_s", False), ("count", True)):
            if вход.get(ключ) is not None:
                try:
                    запись[ключ] = _положительное(вход[ключ], целое)
                except ValueError as e:
                    ошибки.append(f"spec.inputs[{i}].{ключ}={вход[ключ]!r}: {e}")
        if вход.get("resolution") is not None:
            метка = resolution_label(str(вход["resolution"]))
            if метка is None:
                ошибки.append(f"spec.inputs[{i}].resolution={вход['resolution']!r}: not a resolution")
            else:
                запись["resolution"] = метка
        виды.append(вид)
        подробно.append(запись)
    return tuple(dict.fromkeys(виды)), tuple(подробно)


_PEOPLE_FIELDS = frozenset({"name", "real", "public_figure", "consent", "claim"})


def _люди_spec(raw: Any, ошибки: list[str]) -> tuple[dict[str, Any], ...]:
    """`spec.people` -> записи. Поля — для `screen` (политика образа), здесь только проверка формы."""
    люди: list[dict[str, Any]] = []
    for i, ч in enumerate(_список(raw)):
        if not isinstance(ч, Mapping):
            ошибки.append(f"spec.people[{i}]: must be an object {{name, real, public_figure, consent, claim}}")
            continue
        лишние = set(ч) - _PEOPLE_FIELDS
        if лишние:
            ошибки.append(f"spec.people[{i}]: unknown field(s) {', '.join(sorted(лишние))}")
        запись: dict[str, Any] = {"name": str(ч.get("name") or "").strip()}
        for ключ in ("real", "public_figure"):
            if ч.get(ключ) is not None and not isinstance(ч[ключ], bool):
                ошибки.append(f"spec.people[{i}].{ключ}={ч[ключ]!r}: must be true or false")
            запись[ключ] = ч[ключ] if isinstance(ч.get(ключ), bool) else None
        for ключ, допустимо, по_умолчанию in (
            ("consent", CONSENT_STATES, "unknown"),
            ("claim", CLAIM_KINDS, "none"),
        ):
            з = str(ч.get(ключ) if ч.get(ключ) is not None else по_умолчанию).strip().lower()
            if з not in допустимо:
                ошибки.append(f"spec.people[{i}].{ключ}={ч.get(ключ)!r}: not in {', '.join(допустимо)}")
                з = по_умолчанию
            запись[ключ] = з
        люди.append(запись)
    return tuple(люди)


def _бюджет_spec(raw: Mapping[str, Any], поля: dict[str, Any], ошибки: list[str]) -> None:
    """`budget_usd` (прежняя форма) или `budget` {amount, currency} — одно из двух."""
    if raw.get("budget_usd") is not None:
        б = raw["budget_usd"]
        if isinstance(б, bool) or not isinstance(б, (int, float)) or math.isnan(б) or math.isinf(б) or б < 0:
            ошибки.append(f"spec.budget_usd={б!r}: must be a finite number, 0 or more")
        else:
            поля["budget_usd"] = float(б)
            поля["budget_amount"], поля["budget_currency"] = float(б), "USD"
    if raw.get("budget") is None:
        return
    б = raw["budget"]
    if raw.get("budget_usd") is not None:
        ошибки.append("spec.budget: give budget {amount, currency} OR budget_usd, not both")
        return
    if not isinstance(б, Mapping):
        ошибки.append("spec.budget: must be an object {amount, currency}")
        return
    сумма, валюта = б.get("amount"), str(б.get("currency") or "").strip().upper()
    if (
        isinstance(сумма, bool)
        or not isinstance(сумма, (int, float))
        or math.isnan(сумма)
        or math.isinf(сумма)
        or сумма < 0
    ):
        ошибки.append(f"spec.budget.amount={сумма!r}: must be a finite number, 0 or more")
        return
    if not ISO_CURRENCY.match(валюта):
        ошибки.append(f"spec.budget.currency={б.get('currency')!r}: an ISO 4217 code such as USD, EUR, KZT")
        return
    usd, нота = budget_in_usd(float(сумма), валюта)
    поля["budget_amount"], поля["budget_currency"] = float(сумма), валюта
    if usd is not None:
        поля["budget_usd"] = float(usd)
    if нота:
        поля["budget_note"] = нота


def _свой_запуск_spec(sh: Any, поля: dict[str, Any], ошибки: list[str]) -> None:
    if isinstance(sh, bool):
        # true — свой GPU без имени; false — явно НЕ свой (перекрывает текст).
        поля["self_host"] = {"gpu": None, "vram_gb": None} if sh else {"enabled": False}
        return
    if not isinstance(sh, Mapping):
        ошибки.append("spec.self_host: must be an object {gpu, vram_gb, unified_memory_gb} or true/false")
        return
    лишние = set(sh) - {"gpu", "vram_gb", "unified_memory_gb"}
    if лишние:
        ошибки.append(f"spec.self_host: unknown field(s) {', '.join(sorted(лишние))}")
    память: dict[str, Any] = {}
    for ключ in ("vram_gb", "unified_memory_gb"):
        if sh.get(ключ) is not None:
            try:
                память[ключ] = _положительное(sh[ключ])
            except ValueError as e:
                ошибки.append(f"spec.self_host.{ключ}={sh[ключ]!r}: {e}")
    gpu = sh.get("gpu")
    if (gpu and APPLE_SILICON.search(str(gpu).lower())) or "unified_memory_gb" in память:
        # ЕДИНАЯ ПАМЯТЬ — НЕ ВИДЕОПАМЯТЬ CUDA (шестой круг). «128 GB» у M3 Max
        # прежде шло в отбор как `vram_gb` и пускало модели, которые на MPS не
        # запускал никто.
        поля["self_host"] = {
            "gpu": gpu,
            "vram_gb": None,
            "unified_memory_gb": память.get("unified_memory_gb") or память.get("vram_gb"),
            "platform": "apple-silicon",
        }
    else:
        поля["self_host"] = {"gpu": gpu, "vram_gb": память.get("vram_gb")}


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

    _enum("outputs", OUTPUTS, много=True)
    _enum("audio", AUDIO_MODES)
    _enum("objective", OBJECTIVES)
    # Работа — одна или ЦЕПОЧКА: ["video-edit", "upscale"] — стабилизировать,
    # затем поднять разрешение. Первая — главная (`task`), прочие — `then_tasks`.
    if raw.get("task") is not None:
        работы = [str(з).strip().lower() for з in _список(raw["task"])]
        плохие = [з for з in работы if з not in TASKS]
        if плохие:
            ошибки.append(f"spec.task: {', '.join(плохие)} not in {', '.join(TASKS)}")
        работы = list(dict.fromkeys(з for з in работы if з in TASKS))
        if работы:
            поля["task"] = работы[0]
            if работы[1:]:
                поля["then_tasks"] = tuple(работы[1:])
    if raw.get("inputs") is not None:
        поля["inputs"], поля["input_items"] = _входы_spec(raw["inputs"], ошибки)
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
    _бюджет_spec(raw, поля, ошибки)
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
        a = aspect_label(raw["aspect"])
        if a is None:
            ошибки.append(
                f"spec.aspect={raw['aspect']!r}: use W:H such as 9:16, 16:9, 2.39:1 (or a decimal like 2.39)"
            )
        else:
            поля["aspect"] = a
    if raw.get("languages") is not None:
        теги: list[str] = []
        for я in _список(raw["languages"]):
            тег = language_tag(str(я))
            if тег is None:
                ошибки.append(f"spec.languages: {я!r} is not a BCP-47 language tag (e.g. en, kk, pl, he, pt-BR)")
                continue
            теги.append(тег)
        поля["language_tags"] = tuple(dict.fromkeys(теги))
        поля["languages"] = tuple(dict.fromkeys(language_name(т) for т in теги))
    if raw.get("jurisdiction") is not None:
        # Коды и имена («DE», «Germany», «EU») — тем же разборщиком, что у отбора.
        блоки, _ = hn.jurisdiction_codes([str(з) for з in _список(raw["jurisdiction"])])
        поля["jurisdiction"] = tuple(
            sorted({к for з in _список(raw["jurisdiction"]) for к in pl.jurisdictions_in(str(з))} | {
                str(з).upper() for з in _список(raw["jurisdiction"]) if str(з).upper() in pl.JURISDICTIONS
            } | set(блоки))
        )
    if raw.get("self_host") is not None:
        _свой_запуск_spec(raw["self_host"], поля, ошибки)
    if raw.get("people") is not None:
        поля["people"] = _люди_spec(raw["people"], ошибки)
    if raw.get("conditions") is not None:
        if any(not isinstance(у, str) for у in _список(raw["conditions"])):
            ошибки.append('spec.conditions: a list of short phrases, e.g. ["profile face", "logo legible"]')
        поля["conditions"] = tuple(
            dict.fromkeys(str(у).strip() for у in _список(raw["conditions"]) if str(у).strip())
        )
    if raw.get("edit") is not None:
        правки = [str(п).strip().lower() for п in _список(raw["edit"]) if str(п).strip()]
        чужие = [п for п in правки if п not in ep.EDIT_INTENTS]
        if чужие:
            ошибки.append(
                f"spec.edit: {', '.join(map(repr, чужие))} — allowed: {', '.join(ep.EDIT_INTENTS)}"
            )
        поля["edit"] = tuple(dict.fromkeys(п for п in правки if п in ep.EDIT_INTENTS))
    if raw.get("lipsync") is not None:
        if not isinstance(raw["lipsync"], bool):
            ошибки.append(f"spec.lipsync={raw['lipsync']!r}: must be true or false")
        else:
            поля["lipsync"] = raw["lipsync"]
    if raw.get("open_weights") is not None:
        if not isinstance(raw["open_weights"], bool):
            ошибки.append(f"spec.open_weights={raw['open_weights']!r}: must be true or false")
        else:
            поля["open_weights"] = raw["open_weights"]
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
        # «1970s home movie» — десятилетие, а не 1970 секунд (валидатор 5-го круга).
        if re.fullmatch(r"(?:19|20)\d0", м.group("n")) and м.group("u") == "s":
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
    # Свой GPU читает ОДИН разборщик — `hardneed.from_brief`: «self-host»,
    # «on-prem», «run locally» и GPU, названный по имени («on one RTX 4090»).
    свой = hn.from_brief(brief)
    if свой.self_host:
        поля["self_host"] = {"gpu": свой.gpu, "vram_gb": свой.vram_gb}
    # Юрисдикция — по тексту БЕЗ названий языков: «Japanese voice» — язык
    # речи, а не страна показа.
    без_языков = низ
    for формы in pl.LANGUAGE_FORMS.values():
        for ф in формы:
            без_языков = re.sub(rf"(?<![a-zа-яё]){re.escape(ф)}[a-zа-яё]*", " ", без_языков)
    if (ю := pl.jurisdictions_in(без_языков)):
        поля["jurisdiction"] = tuple(ю)
    return Spec(**поля, source={к: SOURCE_TEXT for к in поля if к != "absent"})


#: Поля `Spec`, которые несут ЗНАЧЕНИЕ заказа (а не источник, допущения и
#: основание шотов): по ним `resolve` кладёт spec поверх текста.
SPEC_STATE_FIELDS: tuple[str, ...] = tuple(
    имя for имя in Spec.__dataclass_fields__ if имя not in ("source", "assumptions", "shots_basis")
)


def resolve(brief: str, raw: Mapping[str, Any] | None = None) -> tuple[Spec, list[str]]:
    """Поля `spec` поверх разобранного из текста. Возвращает (итог, ошибки spec)."""
    от_вызова, ошибки = parse_spec(raw)
    из_текста = from_text(brief)
    поля: dict[str, Any] = {}
    источник: dict[str, str] = {}
    for имя in SPEC_STATE_FIELDS:
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


# --- жёсткие требования отбора ---------------------------------------------------

#: Источник поля спецификации -> подпись источника в `hardneed.Hard.sources`.
HARD_SOURCE: dict[str, str] = {SOURCE_SPEC: "spec", SOURCE_TEXT: "бриф", SOURCE_DEFAULT: "допущение"}


def hard(
    spec: Spec,
    brief: str,
    raw: Mapping[str, Any] | None = None,
    кадр: tuple[int, int] | None = None,
    дешевле: bool = False,
) -> hn.Hard:
    """ЖЁСТКИЕ ТРЕБОВАНИЯ ОТБОРА из ОДНОЙ спецификации (круг 4, интеграция).

    `spec` — уже сведённые `resolve` поля (вызывающий поверх текста). Отсюда
    берутся свой GPU, цель, юрисдикция и кадр; `hardneed.from_brief` даёт
    только то, чего в спецификации нет полем: требование открытых весов без
    своего запуска («open-source only»). Так «quality over price», «self-host
    on one RTX 4090», «4K» действуют на отбор одинаково — из текста и из spec.

    :param raw: spec вызывающего как пришёл: страны юрисдикции («DE») берутся
        из него (`resolve` хранит только блоки).
    :param кадр: заказанный кадр, как его видит план (спецификация или
        `кадр_из_брифа`) — короткая сторона становится `Hard.resolution`.
    :param дешевле: план прочёл «самое дешёвое» своими словами (`CHEAPEST_CUES`).
    """
    из_текста = hn.from_brief(brief)
    поля: dict[str, Any] = {"open_weights": из_текста.open_weights}
    источники: dict[str, str] = {"open_weights": "бриф"} if из_текста.open_weights else {}
    if spec.open_weights is not None:
        поля["open_weights"] = spec.open_weights
        источники["open_weights"] = HARD_SOURCE.get(spec.source.get("open_weights", SOURCE_SPEC), "spec")

    def _от(имя: str) -> str:
        return HARD_SOURCE.get(spec.source.get(имя, SOURCE_TEXT), "бриф")

    свой = spec.self_host
    if свой and свой.get("enabled", True):
        gpu = hn.gpu_key(str(свой["gpu"])) if свой.get("gpu") else None
        vram = свой.get("vram_gb")
        поля.update(
            self_host=True,
            gpu=gpu,
            vram_gb=float(vram) if vram is not None else (hn.GPU_VRAM_GB.get(gpu) if gpu else None),
        )
        for имя in ("self_host", "gpu", "vram_gb"):
            if поля[имя]:
                источники[имя] = _от("self_host")
    цель = spec.objective or (hn.OBJECTIVE_CHEAPEST if дешевле else "")
    if цель:
        поля["objective"] = цель
        источники["objective"] = _от("objective") if spec.objective else "бриф"
    if spec.source.get("jurisdiction") == SOURCE_SPEC and spec.jurisdiction:
        названия = raw.get("jurisdiction") if isinstance(raw, Mapping) else None
        блоки, страны = hn.jurisdiction_codes(
            [названия] if isinstance(названия, str) else list(названия or spec.jurisdiction)
        )
        поля["jurisdiction"] = tuple(sorted(set(блоки) | set(spec.jurisdiction))) or None
        поля["countries"] = страны
        источники["jurisdiction"] = "spec"
    else:
        # Юрисдикция из ТЕКСТА — по всему брифу, как и раньше читал план.
        блоки = tuple(pl.jurisdictions_in(brief))
        if блоки:
            поля["jurisdiction"] = блоки
            поля["countries"] = tuple(sorted(pl.countries_in(brief)))
            источники["jurisdiction"] = "бриф"
    if кадр:
        поля["resolution"] = min(кадр)
        источники["resolution"] = _от("resolution")
    return hn.Hard(**поля, sources=tuple(sorted(источники.items())))


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
    #: Седьмой круг. Работа МОНТАЖА (ffmpeg, vidstab, синхронизация по долям),
    #: которую маршрут называет сам, — ключи `ASSEMBLY_REASONS`. Модели в ней
    #: нет, цена 0; шагов-моделей при этом может не быть вовсе.
    сборка: tuple[str, ...] = ()
    #: Работа, которую генеративные модели НЕ делают (язык жестов): (ru, en).
    #: План не строится, а говорится, что это пробел, — никогда не подмена.
    пробел: tuple[str, str] | None = None
    #: Правки (`spec.edit`), которые делает ШАГ-МОДЕЛЬ `правка_видео`; None —
    #: как названо в spec. Правки монтажа (`ASSEMBLY_EDITS`) сюда не входят.
    правки: tuple[str, ...] | None = None
    #: Сколько штук делает шаг, если не столько, сколько заказано кадров:
    #: референс серии — один, правок по нему — N (седьмой круг).
    штук: Mapping[str, int] = field(default_factory=dict)


def _нехватка_видео(задача: str) -> tuple[str, str, str, tuple[str, ...], tuple[str, ...]]:
    return (
        "вход_задачи",
        f"для задачи «{задача}» нужно ВАШЕ видео — приложите файл (creative) или скажите, что видео есть",
        f"the task '{задача}' works on YOUR video — attach it (creative=path) and pass spec.inputs=[{{kind: 'video', owned: true}}]",
        ("видео есть — приложу", "видео нет — сделать с нуля"),
        ("I have the video and will attach it", "there is no video — make one from scratch"),
    )


#: Как вход задачи называется заказчику: (по-русски, spec.inputs).
ВХОД_СЛОВАМИ: dict[str, tuple[str, str]] = {
    "video": ("ВАШЕ видео", "video"),
    "photo": ("ВАШ снимок", "image"),
    "audio": ("ВАША запись (образец голоса, дорожка)", "audio"),
}


def _нехватка_входа(задача: str, вход: str) -> tuple[str, str, str, tuple[str, ...], tuple[str, ...]]:
    if вход == "video":
        return _нехватка_видео(задача)
    по_русски, имя = ВХОД_СЛОВАМИ[вход]
    return (
        "вход_задачи",
        f"для задачи «{задача}» нужен вход — {по_русски}: приложите файл",
        f"the task '{задача}' works on YOUR {имя} — attach it and pass spec.inputs=[{{kind: '{имя}', owned: true}}]",
        ("приложу", "его нет"),
        ("I have it and will attach it", "there is none"),
    )


#: Пометки маршрута — по-русски и по-английски (английский бриф получает план
#: по-английски, `planner._по_английски`).
NOTE_DUB_LIPS = "перевод готового видео: губы под новый язык (лиц в кадре нет — шаг снимается)"
NOTE_KEYFRAMES = "персонажей {n}: ключевой кадр на каждый шот, иначе лица разъезжаются от шота к шоту"
NOTE_VIDEO_EDIT = "правка ВАШЕГО видео (стабилизация, рефрейм, замена неба, вырезка): нового ролика никто не генерирует"
NOTE_R2V_REF = "референс персонажа делается один раз, и каждый шот строится по нему — персонаж не разъезжается"
NOTE_R2V = "каждый шот — по одному референсу персонажа (reference-to-video)"
NOTE_VISUALISER = "только картинка под ВАШ трек: музыка не генерируется, дорожку кладёт монтаж"
NOTE_SING = "ВАШ снимок поёт ВАШУ дорожку: аватар, ведомый звуком; ни синтеза речи, ни генерации музыки"
NOTE_SHORTS_TRANSCRIPT = "расшифровка с таймингами ВАШЕГО длинного видео — по ней выбираются фрагменты"
NOTE_SHORTS_EDIT = "каждый короткий ролик вырезан и перекадрирован из ВАШЕГО видео — ничего не генерируется"
NOTE_DUB_MUX = "новая дорожка кладётся в ВАШЕ видео при сборке; губы не двигаются (spec.lipsync=false)"
NOTE_DUB_AUDIO = "отдаётся дорожка на новом языке; видео не трогается и губ не двигает никто"
NOTE_STABILISE = "стабилизация — монтажный инструмент (ffmpeg vidstab или Gyroflow по гироскопу), не модель"
NOTE_VISUALISER_SYNC = "реакция на звук делается при сборке; генерируемое видео трек не слышит"
NOTE_SERIES_REF = "один референс персонажа, и каждая картинка серии — правка по нему"
NOTE_SERIES_EDIT = "{n} картинок — правки по референсу (а не {n} независимых генераций); вариант — обучить LoRA"
NOTE_SIGN = (
    "язык жестов генеративные модели не делают: липсинк и говорящие аватары двигают губы, а не руки — "
    "пробел записан, план не строится"
)
NOTES_EN: dict[str, str] = {
    NOTE_DUB_LIPS: "translating your own video: lip sync moves the lips to the new language (no faces on screen — drop the step)",
    NOTE_CAPTIONS: "captions are burned in at assembly (ffmpeg) from the timed transcript — no model needed for that",
    NOTE_VIDEO_EDIT: "an edit of YOUR video (stabilise, reframe, sky replacement, cut-out): no new clip is generated",
    NOTE_R2V_REF: "the character reference is made once and every shot is built from it, so the character does not drift",
    NOTE_R2V: "every shot from one character reference (reference-to-video)",
    NOTE_VISUALISER: "visuals only, under YOUR track: no music is generated, the track is laid in at assembly",
    NOTE_SING: "YOUR photo sings YOUR track: an audio-driven avatar; no speech synthesis, no music generation",
    NOTE_SHORTS_TRANSCRIPT: "timed transcript of YOUR long video — the moments are picked from it",
    NOTE_SHORTS_EDIT: "each short is cut and reframed from YOUR video — nothing is generated",
    NOTE_DUB_MUX: "the new track is laid into YOUR video at assembly; the lips do not move (spec.lipsync=false)",
    NOTE_DUB_AUDIO: "the new-language track is delivered as audio; the video is not touched and no lips are moved",
    NOTE_STABILISE: "stabilisation is an assembly tool (ffmpeg vidstab, or Gyroflow from gyro data), not a model",
    NOTE_VISUALISER_SYNC: "audio reactivity is made at assembly; the generated video does not hear the track",
    NOTE_SERIES_REF: "one character reference, and every picture of the series is an edit from it",
    NOTE_SIGN: (
        "sign language is not something generative models do: lip sync and talking avatars move lips, not "
        "hands — a recorded gap, no plan is built"
    ),
}

#: Причины сборки, которые называет МАРШРУТ (а не состав шагов): дорожка
#: заказчика под картинкой, отбор фрагментов по расшифровке. Читает
#: `planner.нужна_сборка`. Ключ — пометка, значение — (ru, en).
ASSEMBLY_REASONS: dict[str, tuple[str, str]] = {
    NOTE_VISUALISER: (
        "под картинку кладётся ВАША дорожка (её длина — длина ролика)",
        "YOUR track is laid under the visuals (its length is the clip length)",
    ),
    NOTE_SHORTS_EDIT: (
        "фрагменты выбираются по расшифровке (вами или языковой моделью), режутся, перекадрируются и "
        "склеиваются ffmpeg — 0 usd, модель не нужна",
        "the moments are picked from the transcript (by you or a language model), then cut, reframed and "
        "joined with ffmpeg — 0 usd, no model",
    ),
    NOTE_CAPTIONS: (
        "субтитры вжигаются ffmpeg по расшифровке с таймингами — 0 usd",
        "captions are burned in with ffmpeg from the timed transcript — 0 usd",
    ),
    NOTE_DUB_MUX: (
        "переведённая дорожка заменяет звук ВАШЕГО видео (ffmpeg) — 0 usd, липсинка нет",
        "the dubbed track replaces the audio of YOUR video (ffmpeg) — 0 usd, no lip sync",
    ),
    NOTE_STABILISE: (
        "стабилизация: ffmpeg vidstab (vidstabdetect + vidstabtransform) или Gyroflow по данным гироскопа — "
        "0 usd, первой, на исходнике до шагов-моделей; генеративной модели стабилизации с записанным "
        "свидетельством в реестре нет",
        "stabilisation: ffmpeg vidstab (vidstabdetect + vidstabtransform) or Gyroflow from gyro data — 0 usd, "
        "first, on the source before any model step; no generative stabilisation endpoint with recorded "
        "evidence is in the registry",
    ),
    NOTE_VISUALISER_SYNC: (
        "реакция на звук — при сборке: доли и атаки ВАШЕГО трека (librosa / aubio) ведут склейки и пульсацию, "
        "слой волны или спектра — ffmpeg showwaves / showspectrum (или аудио-ключи After Effects / "
        "TouchDesigner); генерируемое t2v-видео трек НЕ слышит и само в такт не попадает",
        "audio reactivity is made at assembly: the beats and onsets of YOUR track (librosa / aubio) drive cuts "
        "and pulses, a waveform or spectrum layer comes from ffmpeg showwaves / showspectrum (or After Effects / "
        "TouchDesigner audio keyframes); generated t2v footage does NOT hear the track and is not audio-reactive",
    ),
}

#: Правки ролика, которые делает МОНТАЖ, а не модель, — когда ни один
#: эндпоинт реестра не делает их с записанным свидетельством (седьмой круг:
#: стабилизация уходила в генеративную правку за $25 или оставалась без
#: кандидата). Правка -> пометка сборки. КОНСТАНТА-РЕШЕНИЕ.
ASSEMBLY_EDITS: dict[str, str] = {ep.EDIT_STABILISE: NOTE_STABILISE}

#: Коды языков жестов (ISO 639-3) и общий `sgn` — `spec.languages`.
SIGN_LANGUAGE_CODES: frozenset[str] = frozenset(
    {"sgn", "ase", "bfi", "fsl", "gsg", "jsl", "rsl", "csl", "ins", "asf", "lsf", "ssp", "ise", "bzs", "kvk"}
)
#: Язык жестов словами (`spec.conditions`, текст брифа).
SIGN_WORDS = re.compile(
    r"sign[- ]language|signing avatar|\basl\b|\bbsl\b|язык\w* жестов|жестов\w* язык\w*|сурдоперев\w*"
)


def sign_language(spec: Spec, текст: str = "") -> bool:
    """Заказан ли язык жестов: тег языка, условие или слова брифа."""
    if any(т.split("-")[0] in SIGN_LANGUAGE_CODES for т in spec.language_tags):
        return True
    return any(SIGN_WORDS.search(_norm(у)) for у in (*spec.conditions, текст))


def lipsync_default(spec: Spec) -> bool:
    """Двигать ли губы под новую речь: названо — как названо; иначе — да, когда
    на выходе видео и речь не закадровая (`audio` != voiceover)."""
    if spec.lipsync is not None:
        return spec.lipsync
    return "video" in spec.outputs and spec.audio != "voiceover"


def note_en(ru: str) -> str | None:
    """Пометка маршрута по-английски; None — пометка не наша."""
    if ru in NOTES_EN:
        return NOTES_EN[ru]
    м = re.fullmatch(NOTE_KEYFRAMES.replace("{n}", r"(\d+)"), ru)
    if м:
        return f"{м.group(1)} characters: a keyframe per shot, otherwise faces drift from shot to shot"
    м = re.fullmatch(re.escape(NOTE_SERIES_EDIT).replace(re.escape("{n}"), r"(\d+)"), ru)
    if м:
        return (
            f"{м.group(1)} pictures are edits from the reference (not {м.group(1)} independent generations); "
            "the alternative is training a LoRA on the character"
        )
    return None


#: Серия картинок с ОДНИМ персонажем: с какого числа персонажей и картинок
#: она строится референсом и правками по нему. КОНСТАНТЫ-РЕШЕНИЯ.
SERIES_CHARACTERS_MIN = 1
SERIES_IMAGES_MIN = 2

#: Работа над ВИДЕО заказчика, которая делается одним шагом правки (v2v-edit).
VIDEO_EDIT_TASKS: frozenset[str] = frozenset({"video-edit"})


def _нехватка_двух(задача: str, нужно: tuple[str, ...], есть: set[str]) -> Маршрут | None:
    """Первый недостающий вход задачи — вопрос; всё есть — None."""
    for вход in нужно:
        if вход not in есть:
            return Маршрут(нехватка=_нехватка_входа(задача, вход))
    return None


def _дорожки(spec: Spec, шаги: list[str]) -> None:
    """Речь, музыка, шумы поверх картинки — общие для генерации и r2v."""
    выходы = set(spec.outputs)
    if "speech" in выходы and spec.audio != "native" and "audio" not in spec.inputs:
        шаги.append("озвучка")
    if "music" in выходы:
        шаги.append("музыка")
    if "sfx" in выходы and spec.audio != "native":
        шаги.append("звук_фон")


def _подложка(выходы: set[str]) -> tuple[str, ...]:
    """Музыка и шумы ПОД правленое видео заказчика (свадебный ролик «с музыкой»).

    Речь сюда не входит: у принесённого видео свой звук, а новый голос — это
    уже дубляж, другая работа.
    """
    return tuple(ш for в, ш in (("music", "музыка"), ("sfx", "звук_фон")) if в in выходы)


def route(spec: Spec, на_сборке: frozenset[str] | None = None) -> Маршрут:
    """Шаги по спецификации: главная работа, затем работы цепочки (`then_tasks`).

    Работа цепочки идёт над ВЫХОДОМ предыдущей: «стабилизировать, затем
    апскейл» — апскейл видео, которое отдала правка. Нехватка любой работы —
    вопрос всей цепочки.

    :param на_сборке: правки `spec.edit`, которые делает монтаж, потому что
        ни один эндпоинт реестра их не делает (`ASSEMBLY_EDITS`; решает
        плановщик по реестру). None — все `ASSEMBLY_EDITS`.
    """
    if sign_language(spec):
        return Маршрут(пробел=(NOTE_SIGN, NOTES_EN[NOTE_SIGN]))
    сборочные = frozenset(ASSEMBLY_EDITS) if на_сборке is None else на_сборке
    главный = _маршрут_одной(spec, сборочные)
    if главный.нехватка is not None or not spec.then_tasks:
        return главный
    шаги = list(главный.шаги)
    пометки = dict(главный.пометки)
    сборка = list(главный.сборка)
    правки = главный.правки
    штук = dict(главный.штук)
    выход = "video" if "video" in spec.outputs or spec.task not in (None, "generate") else "photo"
    for задача in spec.then_tasks:
        звено = _маршрут_одной(
            replace(spec, task=задача, then_tasks=(), inputs=tuple(dict.fromkeys((*spec.inputs, выход)))),
            сборочные,
        )
        if звено.нехватка is not None:
            return звено
        шаги += [ш for ш in звено.шаги if ш not in шаги]
        пометки.update({к: в for к, в in звено.пометки.items() if к not in пометки})
        сборка += [с for с in звено.сборка if с not in сборка]
        правки = правки if правки is not None else звено.правки
        штук.update({к: в for к, в in звено.штук.items() if к not in штук})
    return Маршрут(tuple(шаги), пометки, сборка=tuple(сборка), правки=правки, штук=штук)


def _правка_своего(spec: Spec, на_сборке: frozenset[str]) -> Маршрут:
    """Правка ВИДЕО заказчика: модель — на правки, которые делает реестр; монтаж — на прочие."""
    выходы = set(spec.outputs)
    монтаж = tuple(п for п in spec.edit if п in на_сборке and п in ASSEMBLY_EDITS)
    модельные = tuple(п for п in spec.edit if п not in монтаж)
    сборка = tuple(ASSEMBLY_EDITS[п] for п in монтаж)
    if монтаж and not модельные:
        # Только монтажная правка: шага-модели нет, а музыка/шумы под ролик — есть.
        return Маршрут(_подложка(выходы), {}, сборка=сборка, правки=())
    return Маршрут(
        ("правка_видео", *_подложка(выходы)),
        {"правка_видео": NOTE_VIDEO_EDIT},
        сборка=сборка,
        правки=модельные if монтаж else None,
    )


def _маршрут_одной(spec: Spec, на_сборке: frozenset[str] = frozenset(ASSEMBLY_EDITS)) -> Маршрут:
    """Шаги одной работы. Пусто без нехватки — спецификация ничего не заказывает.

    Маршрут называет ГЛАВНЫЕ шаги; входы, которых им не хватает (кадр для
    аватара, речь для липсинка), дописывает замыкание плановщика
    (`planner.замкнуть`) — и помечает их как дописанные, как и в пути подсказок.
    """
    задача = spec.task
    входы = set(spec.inputs)
    выходы = set(spec.outputs)
    шаги: list[str] = []
    пометки: dict[str, str] = {}

    if задача in ROUTE_TASKS:
        for вход, шаг in ROUTE_TASKS[задача]:
            if вход in входы:
                if задача == "captions":
                    return Маршрут((шаг,), {шаг: NOTE_CAPTIONS}, сборка=(NOTE_CAPTIONS,))
                return Маршрут((шаг,), {})
        return Маршрут(нехватка=_нехватка_входа(задача, ROUTE_TASKS[задача][0][0]))
    # --- шестой круг: работа над материалом заказчика -----------------------
    if задача in VIDEO_EDIT_TASKS:
        if "video" not in входы:
            return Маршрут(нехватка=_нехватка_видео(задача))
        return _правка_своего(spec, на_сборке)
    if задача == "cut-to-shorts":
        if "video" not in входы:
            return Маршрут(нехватка=_нехватка_видео(задача))
        # СЕДЬМОЙ КРУГ: вырезать, перекадрировать, склеить, вжечь субтитры —
        # МОНТАЖ (ffmpeg, 0 usd). Модель здесь одна — расшифровка; прежде
        # каждую нарезку «правила» генеративная v2v-правка ($179 за 8 шортсов)
        # при пометке «ничего не генерируется».
        return Маршрут(
            ("расшифровка", *_подложка(выходы)),
            {"расшифровка": NOTE_SHORTS_TRANSCRIPT},
            сборка=(NOTE_SHORTS_EDIT,),
        )
    if задача == "music-visualiser":
        if (нет := _нехватка_двух(задача, ("audio",), входы)) is not None:
            return нет
        # Принесённый кадр оживляется, иначе картинка генерируется с нуля;
        # музыки не генерирует никто — трек заказчика.
        шаг = "оживление" if "photo" in входы else "генерация_видео"
        return Маршрут((шаг,), {шаг: NOTE_VISUALISER}, сборка=(NOTE_VISUALISER, NOTE_VISUALISER_SYNC))
    if задача == "sing-photo":
        if (нет := _нехватка_двух(задача, ("photo", "audio"), входы)) is not None:
            return нет
        return Маршрут(("говорящий_аватар",), {"говорящий_аватар": NOTE_SING})
    if задача == "r2v":
        if "photo" in входы:
            шаги.append("видео_по_референсу")
            пометки["видео_по_референсу"] = NOTE_R2V
        else:
            шаги += ["генерация_изображения", "видео_по_референсу"]
            пометки["генерация_изображения"] = NOTE_R2V_REF
            пометки["видео_по_референсу"] = NOTE_R2V
        _дорожки(spec, шаги)
        return Маршрут(tuple(dict.fromkeys(шаги)), пометки)
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
            # СЕДЬМОЙ КРУГ: губы — только когда их просят (`lipsync_default`):
            # «voice-over is fine» и выход-дорожка липсинка не заказывают.
            if lipsync_default(spec):
                return Маршрут(("дубляж", "липсинк"), {"липсинк": NOTE_DUB_LIPS})
            if "video" in выходы:
                return Маршрут(("дубляж",), {"дубляж": NOTE_DUB_MUX}, сборка=(NOTE_DUB_MUX,))
            return Маршрут(("дубляж",), {"дубляж": NOTE_DUB_AUDIO})
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
        # ПРАВКА ВИДЕО ЗАКАЗЧИКА (шестой круг): «edit» над принесённым видео
        # прежде спрашивал снимок — и замену неба в своём таймлапсе нельзя
        # было заказать вовсе. Видео на входе и видео на выходе — правка видео.
        if "video" in входы and ("video" in выходы or "photo" not in входы):
            return _правка_своего(replace(spec, outputs=()), на_сборке)
        if "photo" in входы:
            return Маршрут(("редактирование_изображения",), {})
        return Маршрут(
            нехватка=(
                "вход_задачи",
                "правка нужна по ВАШЕМУ снимку или видео — приложите его",
                "editing works on YOUR image or video — attach it or pass spec.inputs=[{kind: 'image'|'video', owned: true}]",
                ("снимок или видео есть — приложу", "ничего нет — сгенерировать"),
                ("I have the image or video", "there is none — generate one"),
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
        n = spec.shots or 0
        if (spec.characters or 0) >= SERIES_CHARACTERS_MIN and n >= SERIES_IMAGES_MIN:
            # СЕРИЯ С ОДНИМ ПЕРСОНАЖЕМ (седьмой круг): «24 иллюстрации с тем же
            # ёжиком» — это референс и N правок по нему, а не N независимых
            # генераций, где ёжик каждый раз другой.
            if "photo" not in входы:
                шаги.append("генерация_изображения")
                пометки["генерация_изображения"] = NOTE_SERIES_REF
            шаги.append("редактирование_изображения")
            пометки["редактирование_изображения"] = NOTE_SERIES_EDIT.format(n=n)
            return Маршрут(
                tuple(шаги), пометки, штук={"генерация_изображения": 1, "редактирование_изображения": n}
            )
        шаги.append("генерация_изображения")
    _дорожки(spec, шаги)
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
    допущения += contract_notes(spec)
    поля["source"] = источник
    поля["assumptions"] = tuple(dict.fromkeys(допущения))
    return Spec(**поля)


def contract_notes(spec: Spec) -> list[str]:
    """Оговорки, которые следуют из полей контракта шестого круга — вслух, а не молча."""
    ноты: list[str] = []
    for з in spec.input_items:
        вид = INPUT_KIND_OUT.get(з["kind"], з["kind"])
        if з.get("owned") is False:
            ноты.append(
                f"the {вид} is NOT the customer's own: the plan does not judge rights — licence or permission "
                "from its owner is needed before any of it is used"
            )
        if з["kind"] == "model-weights":
            ноты.append(
                "the customer brings their own model weights: hosted endpoints rarely accept custom weights — "
                "running them is a self-host job, and no candidate here is judged on them"
            )
    if spec.budget_note:
        ноты.append(spec.budget_note)
    sh = spec.self_host or {}
    if sh.get("platform") == "apple-silicon":
        память = sh.get("unified_memory_gb")
        ноты.append(NOTE_APPLE.format(mem=f"{память:g} GB" if память else "its"))
    вне_базы = [т for т in spec.language_tags if language_name(т) == т]
    if вне_базы:
        ноты.append(
            f"language(s) {', '.join(вне_базы)}: the base records nothing about them for any model — "
            "support is UNMEASURED for every candidate (see language_support per step), not refused"
        )
    return ноты


#: Поля эха: поля контракта, кроме `budget` — он печатается суммой и валютой отдельно.
ECHO_FIELDS: tuple[str, ...] = tuple(и for и in SPEC_FIELDS if и != "budget")


def echo(spec: Spec, steps: list[str] | tuple[str, ...] = ()) -> dict:
    """«Понято как»: каждое поле со значением и источником, допущения и как поправить."""
    поля = {
        имя: {"value": (list(з) if isinstance(з, tuple) else з), "from": spec.source.get(имя, SOURCE_TEXT)}
        for имя in ECHO_FIELDS
        if spec.has(имя) and (з := getattr(spec, имя)) is not None
    }
    if spec.then_tasks and "task" in поля:
        поля["task"]["then"] = list(spec.then_tasks)
    if spec.input_items and "inputs" in поля:
        поля["inputs"]["items"] = [
            {**з, "kind": INPUT_KIND_OUT.get(з["kind"], з["kind"])} for з in spec.input_items
        ]
    if spec.language_tags and "languages" in поля:
        поля["languages"]["tags"] = list(spec.language_tags)
    if spec.budget_currency:
        поля["budget"] = {
            "value": {"amount": spec.budget_amount, "currency": spec.budget_currency},
            "from": spec.source.get("budget_currency", SOURCE_TEXT),
            "usd": spec.budget_usd,
            **({"note": spec.budget_note} if spec.budget_note else {}),
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


# --- КОНТРАКТ ШЕСТОГО КРУГА: план строится только по ПОЛНОЙ спецификации ----------
#
# ЗАЧЕМ. Пять кругов подстрочных списков не сошлись: «transcribe interview»,
# «restore 8mm», «stabilise drone», «make my cat photo sing» уходили в
# генерацию ролика с нуля за $394–$540, хотя заказчик принёс материал. Зовёт
# плановщика языковая модель — она и понимает язык. Поэтому план решают поля
# спецификации, а текст брифа — только эхо и ноты. Нет решающих полей — ВОПРОС
# (Р1) с перечнем полей, допустимыми значениями и ЧЕРНОВИКОМ, прочитанным из
# текста прежним разборщиком: черновик помечен как неподтверждённый и НИКОГДА
# не становится планом сам.

#: РЕШАЮЩИЕ поля: без любого из них план не строится, а задаётся вопрос.
SPEC_DECIDING: tuple[str, ...] = ("task", "inputs", "outputs", "duration_s", "languages")

#: Работы, у которых в выходе есть ЯЗЫК (речь или текст) даже без `speech` в
#: `outputs`: перевод, расшифровка, субтитры, клон голоса.
LANGUAGE_TASKS: frozenset[str] = frozenset({"dub-translate", "transcribe", "captions", "voice-clone"})

#: Выходы, у которых есть ДЛИТЕЛЬНОСТЬ: без неё цену не посчитать и шоты не нарезать.
TIMED_OUTPUTS: frozenset[str] = frozenset({"video", "speech", "music", "sfx", "text"})

#: Работы над МАТЕРИАЛОМ заказчика: их длительность может прийти из входа
#: (`inputs[].duration_s`) — длина выхода равна длине принесённого.
MATERIAL_TASKS: frozenset[str] = frozenset(
    {
        "restore",
        "interpolate",
        "remove-background",
        "transcribe",
        "captions",
        "upscale",
        "video-edit",
        "edit",
        "dub-translate",
        "lipsync",
        "face-replace",
        "music-visualiser",
        "sing-photo",
        "colorize",
    }
)

#: Допустимые значения решающих полей — словами для вызывающего (и для человека).
FIELD_HELP: dict[str, str] = {
    "task": "one of " + " | ".join(TASKS) + " — or a list for a chain, e.g. [\"video-edit\", \"upscale\"]",
    "inputs": (
        "what the customer ALREADY HAS: a list of {kind: video|image|audio|text|model-weights, owned: true|false, "
        "duration_s?, count?, resolution?}; [] means nothing"
    ),
    "inputs[].owned": "true when the customer owns (or holds the rights to) this material, false when not",
    "outputs": "list of " + " | ".join(OUTPUTS),
    "duration_s": (
        "seconds of the finished output — or shots + per_shot_s; for work on the customer's own material "
        "inputs[].duration_s is enough"
    ),
    "shots": "how many images / shots / clips (for images: how many pictures)",
    "per_shot_s": "seconds per shot / per short",
    "languages": (
        "BCP-47 tags of the speech or text in the output, e.g. [\"en\"], [\"kk\", \"ru\"], [\"pt-BR\"]; "
        "[] when nothing is spoken"
    ),
}

#: НЕРЕШАЮЩИЕ поля с допустимыми значениями — в `spec_needed.allowed` (седьмой
#: круг: о `spec.edit` вызывающий не знал, и «убрать прохожего» уходило в правку
#: по умолчанию). Е1: тот же текст в описании инструмента.
OPTIONAL_HELP: dict[str, str] = {
    "edit": (
        "for video-edit — WHAT is edited: a list of " + " | ".join(ep.EDIT_INTENTS)
        + "; stabilise is done at assembly (ffmpeg vidstab / Gyroflow, 0 usd) when no endpoint does it"
    ),
    "lipsync": (
        "for dub-translate — move the lips to the new speech: true | false; default true when outputs include "
        "video and audio is not voiceover, else false (voice-over-only dubs get no lip sync)"
    ),
    "characters": "how many recurring characters; 1 + shots N over images = one reference and N edits from it",
    "fps": "output frames per second; above the model's recorded rate a frame-interpolation step is added",
    "audio": "none | native | voiceover",
    "budget": "{amount, currency: ISO 4217}; convert to USD yourself (no FX rates are recorded) and keep the original for echo",
    "conditions": "short phrases the customer actually said, e.g. [\"profile face\", \"hands\"] (ranking only)",
}

#: Полный пример — печатается в вопросе и в описании инструмента (Е1: один текст).
EXAMPLE_SPEC: dict[str, Any] = {
    "task": "dub-translate",
    "inputs": [{"kind": "video", "owned": True, "duration_s": 90, "resolution": "1080p"}],
    "outputs": ["video", "speech"],
    "duration_s": 90,
    "languages": ["pl", "tr"],
    "aspect": "16:9",
    "budget": {"amount": 40, "currency": "USD"},
    "people": [{"name": "our CEO", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}],
    "lipsync": True,
}

#: Что делать вызывающему с вопросом о спецификации — одна строка на все ответы.
SPEC_INSTRUCTION = (
    "The plan is built ONLY from spec. Read the draft below WITH the customer (it was read from the "
    "text by a keyword parser and is unconfirmed), correct it, fill every field in `missing`, and call "
    "plan_pipeline again with spec=<the confirmed object>. Do not guess a field the customer did not "
    "state — ask them."
)


def source_seconds(spec: Spec) -> float | None:
    """Длина принесённого материала (самый длинный вход видео/аудио), или None."""
    длины = [
        float(з["duration_s"])
        for з in spec.input_items
        if з.get("kind") in ("video", "audio") and з.get("duration_s")
    ]
    return max(длины) if длины else None


def source_frame(spec: Spec) -> tuple[int, int] | None:
    """Кадр принесённого видео (самый крупный вход video с `resolution`), или None.

    Нужен цене шага, который работает на исходнике ДО апскейла: правка 2.7K
    ролика считается по кадру 2.7K, а не по 4K, до которого его потом
    поднимет апскейл (круг 6, w07: $53.97 за правку по кадру 4K).
    """
    кадры: list[tuple[int, int]] = [
        к
        for з in spec.input_items
        if з.get("kind") == "video" and з.get("resolution")
        if (к := frame(replace(spec, resolution=str(з["resolution"])))) is not None
    ]
    return max(кадры, key=lambda к: к[0] * к[1]) if кадры else None


#: Работы, которые ведёт ДОРОЖКА заказчика: принесённый звук и есть длина
#: ролика (говорящая голова по своей записи), даже если работа — генерация.
AUDIO_DRIVEN_TASKS: frozenset[str] = frozenset({"avatar"})


def input_seconds(spec: Spec) -> float | None:
    """Длина выхода, которую задаёт принесённое: работа над материалом — самый
    длинный вход видео/аудио; работа под дорожку — длина своей дорожки; иначе None."""
    работы = {spec.task, *spec.then_tasks} if spec.task else set()
    if работы & MATERIAL_TASKS:
        return source_seconds(spec)
    if работы & AUDIO_DRIVEN_TASKS:
        длины = [
            float(з["duration_s"])
            for з in spec.input_items
            if з.get("kind") == "audio" and з.get("owned") and з.get("duration_s")
        ]
        return max(длины) if длины else None
    return None


def _пробел(поле: str, почему: str) -> dict[str, str]:
    return {"field": поле, "allowed": FIELD_HELP.get(поле, ""), "why": почему}


def gaps(raw: Mapping[str, Any] | None) -> tuple[Spec, list[str], list[dict[str, str]]]:
    """(spec, ошибки формы, НЕДОСТАЮЩИЕ решающие поля). Пусто в третьем — план строится.

    Решающие поля: работа, входы (с владением), выходы, длительность или число
    шотов, языки — там, где в выходе есть речь или текст. Остальные поля
    (кадр, соотношение, бюджет, люди, условия) уточняют план, но не решают его.
    """
    spec, ошибки = parse_spec(raw)
    if not isinstance(raw, Mapping):
        raw = {}
    нет: list[dict[str, str]] = []
    работы = (spec.task, *spec.then_tasks) if spec.task else ()
    if not spec.task:
        нет.append(_пробел("task", "the job decides the steps; a text guess is how footage became a generation"))
    if raw.get("inputs") is None:
        нет.append(_пробел("inputs", "what the customer brings decides whether anything is generated at all"))
    else:
        for i, з in enumerate(spec.input_items):
            if з.get("owned") is None:
                нет.append(
                    {
                        "field": f"inputs[{i}].owned",
                        "allowed": FIELD_HELP["inputs[].owned"],
                        "why": f"the {INPUT_KIND_OUT.get(з['kind'], з['kind'])} is brought, but whose it is was not said",
                    }
                )
    if not spec.outputs:
        нет.append(_пробел("outputs", "what comes out decides which steps exist"))
    выходы = set(spec.outputs)
    if "cut-to-shorts" in работы:
        # Седьмой круг: «3-минутный хайлайт из двух часов» — одна нарезка
        # длиной duration_s; шортсы — shots × per_shot_s.
        if not spec.duration_s:
            for поле in ("shots", "per_shot_s"):
                if not getattr(spec, поле):
                    нет.append(
                        _пробел(
                            поле,
                            "how many shorts and how long each (or duration_s for one cut) — the cut, not the "
                            "source, is priced",
                        )
                    )
    elif выходы & TIMED_OUTPUTS:
        от_входа = input_seconds(spec) is not None
        if not (spec.duration_s or (spec.shots and spec.per_shot_s) or от_входа):
            нет.append(_пробел("duration_s", "length decides the price and how many runs/shots are needed"))
    elif выходы == {"image"}:
        штук = any(з.get("count") for з in spec.input_items)
        if not (spec.shots or штук):
            нет.append(_пробел("shots", "how many pictures decides the price"))
    if ("speech" in выходы or set(работы) & LANGUAGE_TASKS) and (
        raw.get("languages") is None or not spec.languages
    ):
        нет.append(_пробел("languages", "speech or text is in the output, so its language decides the models"))
    return spec, ошибки, нет


# --- черновик спецификации из текста ----------------------------------------------

#: ПОДСКАЗКИ ЧЕРНОВИКА: (работа, образец, вход, без которого её нет). Только
#: для черновика — его подтверждает вызывающий; план по ним НЕ строится. Порядок
#: — старшинство: «transcribe … with SRT subtitles» — расшифровка, не субтитры.
#: Раскраска словами (черновик): «colorize», «раскрасить», «black-and-white … in colour».
COLORIZE_CUE = r"colou?ri[sz]\w*|раскрас\w*"

#: Правки ролика словами (черновик `spec.edit`): правка -> образец.
DRAFT_EDIT_CUES: tuple[tuple[str, str], ...] = (
    (ep.EDIT_STABILISE, r"stabili[sz]\w*|стабилиз\w*|shaky|трясущ\w*|дрожащ\w*"),
    (ep.EDIT_REFRAME, r"reframe\w*|re-frame|outpaint\w*|расшир\w* кадр|vertical .{0,40}into .{0,30}horizontal"
     r"|horizontal .{0,40}into .{0,30}vertical|convert (?:our|my) .{0,40}(?:16:9|9:16)"),
    (ep.EDIT_REPLACE_SKY, r"sky replac\w*|replace (?:the )?sky|замен\w* неб\w*"),
    (ep.EDIT_REMOVE_OBJECT, r"remove (?:a |the )?(?:logo|watermark|object|person|people|passer)|(?:убра|удал)\w* (?:объект|прохож|человек|логотип)"),
    (ep.EDIT_REPLACE_OBJECT, r"replace (?:the |a )?(?!sky)\w+|замен\w* (?!неб)"),
    (ep.EDIT_RELIGHT, r"relight\w*|day[- ]to[- ]night|переосвет\w*"),
    (ep.EDIT_RESTYLE, r"restyl\w*|style transfer|color[- ]?grad\w*|colou?r correct\w*|цветокор\w*"),
)

DRAFT_TASK_CUES: tuple[tuple[str, str, str], ...] = (
    ("transcribe", r"transcri\w*|расшифр\w*|speech[- ]to[- ]text|speaker labels|diari[sz]\w*|стенограм\w*", "video"),
    ("captions", r"\bcaptions?\b|subtitl\w*|субтитр\w*", "video"),
    (
        "restore",
        r"restor\w*|реставр\w*|scratch\w*|\b8 ?mm\b|super ?8|film grain|de-?flicker|old (?:film|footage|home movie)"
        r"|оцифр\w*|старо\w* (?:плёнк|пленк|видео)",
        "video",
    ),
    ("colorize", COLORIZE_CUE, "video"),
    (
        "remove-background",
        r"remove (?:the )?background|background remov\w*|без фона|удал\w* фон|убра\w* фон|убери фон"
        r"|cut ?out (?:the )?background|on (?:a )?green|green ?screen|alpha matte|matting",
        "video",
    ),
    (
        "interpolate",
        r"slow[- ]?mo\w*|interpolat\w*|интерполяц\w*|замедл\w*|smoother motion|frame rate up|"
        r"into (?:60|120|240) ?fps",
        "video",
    ),
    (
        "voice-clone",
        r"clon\w* (?:\w+ ){0,3}voice|voice[- ]?clon\w*|клон\w* голос|склонир\w*|голосом наш\w*|"
        r"in (?:his|her|my|our \w+'s) own voice",
        "audio",
    ),
    (
        "music-visualiser",
        r"visuali[sz]er|визуализ\w*|audio[- ]reactive|reactive (?:shapes|visuals)|pulsing to the beat",
        "audio",
    ),
    (
        "video-edit",
        r"stabili[sz]\w*|стабилиз\w*|reframe\w*|re-frame|outpaint\w*|расшир\w* кадр|sky replac\w*|"
        r"replace (?:the )?sky|замен\w* неб\w*|remove (?:a |the )?(?:logo|watermark|object|person|people|passer)"
        r"|color[- ]?grad\w*|colou?r correct\w*|цветокор\w*|vertical .{0,40}into .{0,30}horizontal"
        r"|horizontal .{0,40}into .{0,30}vertical|convert (?:our|my) .{0,40}(?:16:9|9:16)",
        "video",
    ),
    ("turntable", r"turntable|\b360\b|оборот|вращени\w*", "photo"),
    ("animate", r"image[- ]to[- ]video|\bi2v\b|photo[- ]to[- ]video", "photo"),
)

#: «we have the video and the audio», «у нас есть запись» — владение, сказанное
#: глаголом «есть/have» (окно до восьми слов после него). Только черновик.
HAVE_PHRASE = re.compile(r"\b(?:we|i)(?:'ve| have| already have| got| own)\b|у (?:нас|меня) (?:уже )?есть")
HAVE_WINDOW = 8

#: Признаки того, что заказчик говорит о СВОЁМ исходнике, а не о заказе ролика:
#: интервью, подкаст, запись, плёнка, таймлапс, «my/our … clip». Только черновик.
DRAFT_SOURCE_WORDS = re.compile(
    r"interview|podcast|webinar|stream|livestream|lecture|recording|home movie|footage|timelapse|time-lapse"
    r"|drone (?:footage|shot|video|clip)|\bvod\b|интервью|подкаст|вебинар|стрим|запис[ьи]|лекци\w*|съ[её]мк\w*"
    r"|исходник\w*|плёнк\w*|пленк\w*|таймлапс\w*"
)
SHORTS = re.compile(r"\bshorts\b|\btiktoks\b|нарез\w*|нареж\w*|highlights?|коротк\w+ ролик\w*|\d+ (?:reels|clips)\b")
SING = re.compile(r"\bsings?\b|\bsinging\b|\bsang\b|\bпе(?:ть|л|ла|ло|ли)\b|поёт|поет|поют|спо[её]т|спел\w*")
SAME_CHARACTER = re.compile(
    r"same character|consistent character|same (?:hero|mascot|girl|boy|man|woman)|один и тот же (?:персонаж|герой)"
    r"|одн\w+ и т\w+ же (?:персонаж|герой|героин)"
)
#: «MacBook M3 Max, 128GB unified memory» — память Apple, не VRAM.
_ЕДИНАЯ_ПАМЯТЬ = re.compile(r"(\d{2,3})\s*gb(?:\s+(?:of\s+)?unified(?:\s+memory)?)?")
_APPLE_В_ТЕКСТЕ = re.compile(r"(?:apple\s+)?(?:macbook(?:\s+pro|\s+air)?\s+)?\bm[1-9](?:\s+(?:pro|max|ultra))?\b|mac studio|mac mini")

#: Выход работы для черновика, когда текст выход не назвал.
DRAFT_TASK_OUTPUTS: dict[str, tuple[str, ...]] = {
    "transcribe": ("text",),
    "captions": ("video",),
    "restore": ("video",),
    "interpolate": ("video",),
    "video-edit": ("video",),
    "cut-to-shorts": ("video",),
    "music-visualiser": ("video",),
    "sing-photo": ("video",),
    "turntable": ("video",),
    "r2v": ("video",),
    "voice-clone": ("speech",),
    "dub-translate": ("video", "speech"),
    "lipsync": ("video",),
    "avatar": ("video", "speech"),  # говорящий в кадре
    "face-replace": ("video",),
}

DRAFT_STATUS = (
    "DRAFT — UNCONFIRMED. Read from the brief text by the keyword parser, which misreads paraphrases; "
    "it is NOT a plan and nothing was priced. Confirm or correct every field with the customer."
)


def _есть_по_глаголу(низ: str) -> set[str]:
    """Входы, названные после «we have / у нас есть» (окно `HAVE_WINDOW` слов)."""
    есть: set[str] = set()
    for м in HAVE_PHRASE.finditer(низ):
        for т in _tokens(низ[м.end() :])[:HAVE_WINDOW]:
            # «we have nothing yet, make a video» — отрицание или заказ обрывают окно.
            if NEGATION.match(т) or т in ("nothing", "ничего") or MAKE_WORDS.match(т):
                break
            if VIDEO_NOUN.match(т):
                есть.add("video")
            elif PHOTO_NOUN.match(т):
                есть.add("photo")
            elif AUDIO_NOUN.match(т) or т in ("recording", "recordings", "записи", "запись"):
                есть.add("audio")
            elif SCRIPT_NOUN.match(т):
                есть.add("script")
    return есть


def _работа_черновика(низ: str, t: Spec, есть: set[str]) -> tuple[str | None, str | None]:
    """(работа, вход, без которого её нет) — по подсказкам черновика, затем по разборщику."""
    исходник = "video" in есть or bool(DRAFT_SOURCE_WORDS.search(низ))
    if SHORTS.search(низ) and исходник:
        return "cut-to-shorts", "video"
    фото = "photo" in есть or bool(re.search(r"\bphoto\b|\bpicture\b|\bselfie\b|фото\w*|снимк\w*|картинк\w*", низ))
    if SING.search(низ) and фото:
        return "sing-photo", "photo"
    for задача, образец, вход in DRAFT_TASK_CUES:
        if re.search(образец, низ):
            if задача == "remove-background" and "video" not in есть and re.search(r"photo|image|picture|фото|снимок|картинк", низ):
                return задача, "photo"
            if задача == "transcribe" and "audio" in есть and "video" not in есть:
                return задача, "audio"
            return задача, вход
    разобрано = t.task
    if разобрано in (None, "generate") and "video" in есть and LIPSYNC.search(низ):
        return "lipsync", "video"
    if разобрано in (None, "generate", "animate") and "video" in t.outputs and SAME_CHARACTER.search(низ):
        return "r2v", None
    if разобрано == "generate" and "video" in есть:
        # Принесённое видео и «сгенерировать» — разборщик спутал заказ с
        # исходником; черновик работу не называет, а не зовёт генерацию.
        return None, None
    if разобрано == "edit" and "video" in есть:
        return "video-edit", "video"
    return разобрано, None


def draft(brief: str, raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """ЧЕРНОВИК спецификации из текста — для вопроса, а не для плана.

    Поля, названные вызывающим в `raw`, остаются его (черновик их не трогает);
    остальные читаются прежним разборщиком (`from_text`) и подсказками
    черновика (`DRAFT_TASK_CUES`). Возвращает сам черновик, какие поля прочитаны
    из текста, каких решающих не хватает и что угадано.
    """
    низ = _norm(brief)
    t = from_text(brief)
    угадано: list[str] = []
    черновик: dict[str, Any] = {}
    есть_входы = [в for в in INPUT_KINDS if в in set(t.inputs) | _есть_по_глаголу(низ)]
    задача, нужный_вход = _работа_черновика(низ, t, set(есть_входы))
    if задача:
        # Цепочка: работа над видео заказчика И «upscale to 4K» — правка, затем апскейл.
        цепочка = [задача]
        if задача == "restore" and re.search(COLORIZE_CUE, низ):
            # «отреставрировать и раскрасить» — две работы (седьмой круг).
            цепочка.append("colorize")
        if задача == "cut-to-shorts" and re.search(r"\bcaptions?\b|subtitl\w*|субтитр\w*", низ):
            цепочка.append("captions")
        if задача in ("video-edit", "restore", "interpolate", "colorize") and UPSCALE.search(низ):
            цепочка.append("upscale")
        черновик["task"] = цепочка if len(цепочка) > 1 else задача
        if задача == "video-edit":
            правки = [п for п, образец in DRAFT_EDIT_CUES if re.search(образец, низ)]
            if правки:
                черновик["edit"] = правки
                угадано.append("edit read from the brief's words — confirm what exactly is edited")
        if задача == "dub-translate":
            if re.search(r"no lip[- ]?sync|without lip[- ]?sync|lip[- ]?sync (?:is )?not needed|voice[- ]?over is fine|без липсинк", низ):
                черновик["lipsync"] = False
            elif LIPSYNC.search(низ) or re.search(r"lips? (?:must |should )?match", низ):
                черновик["lipsync"] = True
    входы: list[dict[str, Any]] = []
    for вид in есть_входы:
        входы.append({"kind": INPUT_KIND_OUT[вид], "owned": True})
    if входы:
        угадано.append("inputs[].owned=true read from 'my/our/attached' — confirm the customer owns the material")
    if нужный_вход and нужный_вход not in есть_входы:
        if not (нужный_вход == "video" and "audio" in есть_входы and задача == "transcribe"):
            входы.append({"kind": INPUT_KIND_OUT[нужный_вход], "owned": None})
            угадано.append(f"inputs: {INPUT_KIND_OUT[нужный_вход]} implied by the task '{задача}' — confirm it exists and whose it is")
    if задача == "sing-photo" and "audio" not in есть_входы:
        входы.append({"kind": "audio", "owned": None})
        угадано.append("inputs: the song/track to sing is implied — confirm the customer has it")
    if задача in MATERIAL_TASKS and t.duration_s and входы:
        # Не у нарезки: «3-minute reel from 2 hours» — 3 минуты это выход, а не исходник.
        главный = next((в for в in входы if в["kind"] in ("video", "audio")), None)
        if главный is not None:
            главный["duration_s"] = t.duration_s
    if входы or t.absent:
        черновик["inputs"] = входы
    выходы = list(t.outputs)
    if задача in DRAFT_TASK_OUTPUTS and (not выходы or задача not in ("generate", "animate")):
        выходы = list(dict.fromkeys([*DRAFT_TASK_OUTPUTS[задача], *[в for в in выходы if в in ("speech", "music", "sfx") and задача in ("r2v", "cut-to-shorts", "video-edit")]]))
    if задача == "remove-background":
        выходы = ["image"] if нужный_вход == "photo" else ["video"]
    if выходы:
        черновик["outputs"] = выходы
    if задача == "cut-to-shorts":
        штук = re.search(r"(\d{1,3})\s+(?:\w+\s+)?(?:shorts|clips|reels|tiktoks|ролик\w*|клип\w*)", низ)
        if t.shots or штук:
            черновик["shots"] = t.shots or int(штук.group(1))  # type: ignore[union-attr]
        каждый = re.search(
            r"(?:shorts|clips|reels|tiktoks)\s+(?:of\s+)?(?:about\s+|around\s+|~)?(\d{1,3})\s*(?:s\b|sec|seconds)", низ
        )
        if t.per_shot_s or каждый:
            черновик["per_shot_s"] = t.per_shot_s or float(каждый.group(1))  # type: ignore[union-attr]
        if "shots" not in черновик and t.duration_s:
            # Одна нарезка («3-minute highlight reel») — длина выхода (седьмой круг).
            черновик["duration_s"] = t.duration_s
    else:
        for поле in ("duration_s", "shots", "per_shot_s", "characters"):
            if getattr(t, поле):
                черновик[поле] = getattr(t, поле)
    for поле in ("resolution", "fps", "audio", "objective"):
        if getattr(t, поле):
            черновик[поле] = getattr(t, поле)
    if t.aspect:
        черновик["aspect"] = t.aspect
    теги = languages_in_text(низ)
    if теги:
        черновик["languages"] = list(теги)
    деньги = money_in_text(brief)
    if деньги is not None:
        черновик["budget"] = {"amount": деньги[0], "currency": деньги[1]}
    apple = _APPLE_В_ТЕКСТЕ.search(низ)
    if apple and re.search(r"unified|macbook|mac studio|mac mini|apple|locally|local", низ):
        память = _ЕДИНАЯ_ПАМЯТЬ.search(низ)
        черновик["self_host"] = {
            "gpu": "Apple " + apple.group(0).replace("macbook pro ", "").replace("apple ", "").upper(),
            **({"unified_memory_gb": float(память.group(1))} if память else {}),
        }
    elif t.self_host:
        черновик["self_host"] = {к: в for к, в in dict(t.self_host).items() if в is not None} or True
    if t.jurisdiction:
        черновик["jurisdiction"] = list(t.jurisdiction)
    прочитано = sorted(черновик)
    # Поля вызывающего — его; черновик их не перекрывает.
    if isinstance(raw, Mapping):
        for ключ, значение in raw.items():
            if ключ in SPEC_FIELDS:
                черновик[ключ] = значение
    _, ошибки, нет = gaps(черновик)
    return {
        "status": DRAFT_STATUS,
        "spec": черновик,
        "read_from_text": [п for п in прочитано if not (isinstance(raw, Mapping) and п in raw)],
        "still_missing": [н["field"] for н in нет],
        "draft_errors": ошибки,
        "guesses": угадано,
    }
