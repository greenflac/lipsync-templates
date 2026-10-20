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
#: Кем человек приходится заказчику (тринадцатый круг, `spec.people[].role`):
#: employee — сотрудник заказчика (свой ведущий канала), self — сам заказчик,
#: talent — нанятый актёр/модель, other — посторонний. Решает
#: `studio/inhouse_news.py`: свой ведущий со своими новостями — план, не отказ.
PERSON_ROLES: tuple[str, ...] = ("employee", "self", "talent", "other")
OBJECTIVES: tuple[str, ...] = ("cheapest", "balanced", "quality")
#: Для кого сделано (одиннадцатый круг, `spec.audience`): ЗРИТЕЛЬ, а не тот, кто
#: в кадре. Мультсериал для детей — `children`; ребёнка в кадре это не значит
#: (кто в кадре — `spec.people`, `minor`).
AUDIENCES: tuple[str, ...] = ("children", "teens", "general", "adults")
#: Пятнадцатый круг (`spec.edit_target`): ЧТО меняется в кадре правкой — цель, а
#: не слово задачи. text — надпись (вывеска, этикетка, билборд): правка видео с
#: текстом, а не замена персонажа; person — лицо или человек.
EDIT_TARGETS: tuple[str, ...] = ("text", "person", "object", "background", "sky", "light", "style")
#: Пятнадцатый круг (`spec.consistency`): что держится ОДИНАКОВЫМ от шота к шоту
#: (кадру серии): light — свет, style — стиль, character — персонаж.
CONSISTENCY_AXES: tuple[str, ...] = ("light", "style", "character")
#: Пятнадцатый круг: поля записи выхода (`spec.outputs[]` объектом).
OUTPUT_ITEM_FIELDS: tuple[str, ...] = ("kind", "loop", "tileable", "alpha")

# --- ШЕСТНАДЦАТЫЙ КРУГ: поля решений, которые пятнадцатый круг оставил словам ---------------
# Каждое решение ниже прежде читалось ТОЛЬКО из английских и русских слов брифа
# (`checklist.spec_fields_to_add()`, рецепты `studio/recipes/apply.py`). Поле
# названо — решает поле, на любом языке брифа; не названо — запасные слова.
# Читатели полей — `studio/spec_first.py`.

#: `spec.anonymise.method`: swap — лицо на синтетическое (замена лица в видео, с
#: ценой); blur / pixelate — размытие / пикселизация при сборке; voice-replace —
#: голос заменяется другим голосом синтеза (расшифровка + TTS, НЕ клон).
ANONYMISE_METHODS: tuple[str, ...] = ("swap", "blur", "pixelate", "voice-replace")
ANONYMISE_FIELDS: tuple[str, ...] = ("faces", "voice", "method")
#: Методы для ЛИЦ (первый — по умолчанию, когда лица названы без метода).
FACE_ANON_METHODS: tuple[str, ...] = ("swap", "blur", "pixelate")
#: `spec.delivery.platform`: куда сдаётся результат (решает оговорки площадки).
DELIVERY_PLATFORMS: tuple[str, ...] = (
    "broadcast", "cinema", "streaming-premium", "youtube", "youtube-shorts", "tiktok", "instagram", "reels",
    "web", "podcast", "audiobook", "telephony", "voice-agent", "game-engine", "marketplace", "print", "vfx",
    "editorial", "app-store", "music-distribution", "other",
)  # fmt: skip
#: Площадки коротких вертикальных роликов и соцсетей (`checklist.W_PLATFORM`).
SOCIAL_PLATFORMS: tuple[str, ...] = ("youtube", "youtube-shorts", "tiktok", "instagram", "reels")
DYNAMIC_RANGES: tuple[str, ...] = ("sdr", "hdr")
CALL_DIRECTIONS: tuple[str, ...] = ("inbound", "outbound")
#: `spec.delivery.format`: форматы сдачи; glb / gltf / usdz / obj / fbx — 3D-модель.
DELIVERY_FORMATS: tuple[str, ...] = (
    "mp4", "mov", "prores", "webm", "gif", "png", "jpg", "tiff", "pdf", "svg", "wav", "mp3", "srt",
    "glb", "gltf", "usdz", "obj", "fbx",
)  # fmt: skip
MESH_FORMATS: tuple[str, ...] = ("glb", "gltf", "usdz", "obj", "fbx")
DELIVERY_FIELDS: tuple[str, ...] = ("platform", "dynamic_range", "stems", "direction", "format")
#: `spec.domain`: к какой области относится заказ (решает оговорки рекламы, новостей, политики).
DOMAINS: tuple[str, ...] = (
    "advertising", "health-advertising", "financial-advertising", "branded-content", "news", "documentary",
    "real-estate", "political", "education", "entertainment", "corporate", "other",
)  # fmt: skip
#: Рекламные области (любая из них — реклама).
AD_DOMAINS: tuple[str, ...] = ("advertising", "health-advertising", "financial-advertising", "branded-content")
#: `spec.style`: photoreal — фотореализм; stylised — рисованный / 3D-мульт / стилизованный;
#: limited-animation — рисованная анимация «на двойках» (аниме, 2D).
STYLES: tuple[str, ...] = ("photoreal", "stylised", "limited-animation")
#: `spec.subject`: что в кадре важно для решения.
SUBJECTS: tuple[str, ...] = (
    "product", "cosmetic", "reflective", "transparent", "logo", "text", "garment", "interior", "mascot",
    "before-after", "person", "other",
)  # fmt: skip
ACCESSIBILITY_NEEDS: tuple[str, ...] = ("captions", "audio-description")
#: `spec.display`: additive — голограмма / прозрачный LED (чёрное прозрачно).
DISPLAYS: tuple[str, ...] = ("standard", "additive")
#: `spec.audio_content`: что звучит в результате (или в принесённом звуке).
AUDIO_CONTENTS: tuple[str, ...] = ("speech", "song", "music", "ambience")
#: `spec.inputs[].source`: что это за материал.
INPUT_SOURCES: tuple[str, ...] = (
    "print-scan", "archival", "cine-film", "timelapse", "green-screen", "stock", "third-party-song",
    "screen-recording", "slides", "own",
)  # fmt: skip
#: `spec.inputs[].defects`: что с материалом не так.
INPUT_DEFECTS: tuple[str, ...] = ("halftone", "blur", "noise", "hum", "echo", "scratches", "flicker")
#: Дефекты звука — чистка звука.
AUDIO_DEFECTS: tuple[str, ...] = ("noise", "hum", "echo")

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
    # Седьмой круг: новость или реальное событие (читает и проверяет `screen`).
    "claims",
    # Седьмой круг: двигать ли губы под новую речь (дубляж). Не названо —
    # `lipsync_default`.
    "lipsync",
    # Восьмой круг: допущения рецептов (`studio/recipes`) — {id: false} выключает.
    "priors",
    # Одиннадцатый круг: для кого ролик (зритель) — читает политика текста `spec_screen`.
    "audience",
    # ПЯТНАДЦАТЫЙ КРУГ — поля решений, которые прежде брались ТОЛЬКО из слов брифа
    # (EN/RU) и молчали на любом другом языке. Вызывающая модель понимает любой
    # язык и называет их сама; слова — запасной путь, когда поля нет, и поле
    # старше слов, когда они спорят. Ещё два — внутри записей: `outputs[].loop`,
    # `outputs[].tileable`, `people[].on_screen`, `people[].speaks`.
    "live",
    "edit_target",
    "cast_together",
    "single_take_s",
    "training_use",
    "consistency",
    "dataset_count",
    # ШЕСТНАДЦАТЫЙ КРУГ — остальные решения, прежде читавшиеся только словами
    # (EN/RU). Внутри записей входа: `inputs[].source`, `inputs[].defects`, `inputs[].fps`.
    "anonymise",
    "voiceover",
    "delivery",
    "domain",
    "style",
    "subject",
    "accessibility",
    "display",
    "audio_content",
    "follows_picture",
    "animate_input",
    "community",
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
    "restore": (("video", "реставрация"), ("photo", "реставрация_изображения")),
    "colorize": (("video", "раскраска"), ("photo", "раскраска_изображения")),
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
    #: Новости и реальные события {type, real_brand, brand, fabricated} — форму
    #: проверяет и решает `screen` (политика новостей), здесь поле только есть.
    claims: tuple[Mapping[str, Any], ...] = ()
    #: Условия кадра свободными словами («profile face», «hands») — в отбор.
    conditions: tuple[str, ...] = ()
    #: Требуются открытые веса (без своего запуска тоже).
    open_weights: bool | None = None
    #: Что правится в `video-edit`: reframe | replace-object | remove-object |
    #: replace-sky | stabilise | relight | restyle (`endpoints.EDIT_INTENTS`).
    edit: tuple[str, ...] = ()
    #: Губы под новую речь (седьмой круг): True/False — сказано; None — `lipsync_default`.
    lipsync: bool | None = None
    #: Для кого ролик (одиннадцатый круг): children | teens | general | adults.
    audience: str | None = None
    #: Двенадцатый круг: говорящий ВИДЕН в кадре (ведущий, персонаж говорит в
    #: камеру). Поля в контракте нет — решает `with_defaults` по словам брифа
    #: (`говорят_в_кадре`); маршрут читает его, чтобы к речи и картинке добавить
    #: шаг, который двигает губы.
    speaker_on_screen: bool = False
    #: Четырнадцатый круг: персонажи серии ДЕЛЯТ кадр (диалог, «вместе», «в каждом
    #: шоте»). Поля в контракте нет — решает `with_defaults` по словам брифа
    #: (`персонажи_в_одном_кадре`): только тогда ключевой кадр шота — правка по
    #: референсам; иначе шот оживляется прямо от референса своего персонажа.
    cast_together: bool | None = None
    #: Восьмой круг: допущения рецептов, выключенные вызывающим ({id: False});
    #: не названо — допущение класса заполняет молчание базы (`studio/recipes`).
    priors: Mapping[str, bool] = field(default_factory=dict)
    # --- пятнадцатый круг: поля решений (см. `SPEC_FIELDS`) --------------------
    #: Живая / интерактивная система (стрим, звонок, аватар, отвечающий в сеансе):
    #: True — пробел `studio/realtime.py`; False — обычный план, что бы ни говорили слова.
    live: bool | None = None
    #: Цель правки (`EDIT_TARGETS`): text — надпись в кадре, person — человек.
    edit_target: str | None = None
    #: Выход — бесшовная петля / бесшовная (тайлящаяся) текстура (`outputs[].loop`,
    #: `outputs[].tileable`); None — не сказано.
    loop: bool | None = None
    tileable: bool | None = None
    #: Выход с прозрачным фоном (альфа-канал: PNG, WebM, ProRes 4444) — `outputs[].alpha`.
    alpha: bool | None = None
    #: Записи выходов, как названы объектами: {kind, loop?, tileable?}.
    output_items: tuple[Mapping[str, Any], ...] = ()
    #: Самый длинный НЕПРЕРЫВНЫЙ дубль, секунды (без склейки внутри).
    single_take_s: float | None = None
    #: Результат пойдёт в обучение модели (датасет, дообучение, синтетические данные).
    training_use: bool | None = None
    #: Что держится одинаковым от шота к шоту (`CONSISTENCY_AXES`).
    consistency: tuple[str, ...] = ()
    #: Сколько образцов в датасете, который составляют выходы.
    dataset_count: int | None = None
    # --- шестнадцатый круг: поля решений (см. `SPEC_FIELDS`, читатели — `studio/spec_first.py`) ---
    #: Анонимизация: {faces: bool, voice: bool, method: str | None}; {faces: False, voice: False} — НЕТ.
    anonymise: Mapping[str, Any] | None = None
    #: Речь в результате (закадр, диктор, говорящий в кадре): False — ни слова.
    voiceover: bool | None = None
    #: Сдача: {platform: (…), dynamic_range, stems, direction, format: (…)}.
    delivery: Mapping[str, Any] | None = None
    domain: tuple[str, ...] = ()
    style: str | None = None
    subject: tuple[str, ...] = ()
    accessibility: tuple[str, ...] = ()
    display: str | None = None
    audio_content: tuple[str, ...] = ()
    #: Заказанный звук следует за действием принесённой картинки (video-to-audio).
    follows_picture: bool | None = None
    #: Принесённая картинка САМА движется (визуализатор поверх обложки); False — статична (аудиограмма).
    animate_input: bool | None = None
    #: Нужны модели / LoRA / воркфлоу сообщества (Civitai, Hugging Face).
    community: bool | None = None

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
        "invented — the plan gives NO budget verdict. Convert it to USD yourself and pass "
        f"budget={{amount: {сумма:g}, currency: '{валюта}', usd: <your figure>}} to get one"
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

_INPUT_FIELDS = frozenset({"kind", "owned", "duration_s", "count", "resolution", "note", "source", "defects", "fps"})


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
        # ШЕСТНАДЦАТЫЙ КРУГ: что это за материал и что с ним не так — списки из
        # перечня (скан печати, архив, хромакей; растр, шум, размытие).
        for ключ, допустимо in (("source", INPUT_SOURCES), ("defects", INPUT_DEFECTS)):
            if вход.get(ключ) is None:
                continue
            значения = [str(з).strip().lower() for з in _список(вход[ключ]) if str(з).strip()]
            чужие = [з for з in значения if з not in допустимо]
            if чужие:
                ошибки.append(f"spec.inputs[{i}].{ключ}: {', '.join(чужие)} not in {', '.join(допустимо)}")
            запись[ключ] = tuple(dict.fromkeys(з for з in значения if з in допустимо))
        if вход.get("fps") is not None:
            try:
                запись["fps"] = _положительное(вход["fps"])
            except ValueError as e:
                ошибки.append(f"spec.inputs[{i}].fps={вход['fps']!r}: {e}")
        виды.append(вид)
        подробно.append(запись)
    return tuple(dict.fromkeys(виды)), tuple(подробно)


_PEOPLE_FIELDS = frozenset(
    {"name", "real", "public_figure", "consent", "claim", "deceased", "minor", "role", "on_screen", "speaks"}
)
#: Пятнадцатый круг: кто В КАДРЕ и кто ГОВОРИТ (или поёт) — решают губы (липсинк),
#: исполнитель клипа и визуализатор без исполнителя, а не слова брифа.
_PEOPLE_FLAGS: tuple[str, ...] = ("on_screen", "speaks")


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
        for ключ in ("real", "public_figure", "deceased", "minor"):
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
        if ч.get("role") is not None:
            роль = str(ч["role"]).strip().lower()
            if роль not in PERSON_ROLES:
                ошибки.append(f"spec.people[{i}].role={ч['role']!r}: not in {', '.join(PERSON_ROLES)}")
            else:
                запись["role"] = роль
        for ключ in _PEOPLE_FLAGS:
            if ч.get(ключ) is not None:
                if not isinstance(ч[ключ], bool):
                    ошибки.append(f"spec.people[{i}].{ключ}={ч[ключ]!r}: must be true or false")
                else:
                    запись[ключ] = ч[ключ]
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
        ошибки.append("spec.budget: must be an object {amount, currency, usd?}")
        return
    лишние = set(б) - {"amount", "currency", "usd"}
    if лишние:
        ошибки.append(f"spec.budget: unknown field(s) {', '.join(sorted(лишние))} (known: amount, currency, usd)")
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
    свой = б.get("usd")
    if свой is not None:
        # ПЕРЕСЧЁТ ВЫЗЫВАЮЩЕГО (седьмой круг): курса у нас не записано ни
        # одного, а вызывающий знает сегодняшний. Его число — потолок; сумма в
        # валюте остаётся для эха. Записанный курс старше чужого пересчёта нет:
        # вызывающий назвал число явно.
        if isinstance(свой, bool) or not isinstance(свой, (int, float)) or math.isnan(свой) or math.isinf(свой) or свой < 0:
            ошибки.append(f"spec.budget.usd={свой!r}: must be a finite number, 0 or more")
            return
        usd = float(свой)
        нота = (
            ""
            if валюта == "USD"
            else f"budget {float(сумма):g} {валюта} converted by the caller to {usd:g} USD — no {валюта}->USD rate "
            "is recorded here; the budget verdict uses the caller's figure"
        )
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
        ошибки.append("spec.self_host: must be an object {gpu, vram_gb, unified_memory_gb, cpu_only} or true/false")
        return
    лишние = set(sh) - {"gpu", "vram_gb", "unified_memory_gb", "cpu_only"}
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
    elif sh.get("cpu_only") is True or (gpu and hn.CPU_ONLY.search(str(gpu))):
        # БЕЗ GPU (десятый круг): Raspberry Pi, мини-ПК, «CPU only» — видеопамяти
        # нет, отбор идёт по записанному запуску на ARM / CPU (`hn.cpu_state`).
        поля["self_host"] = {"gpu": gpu, "vram_gb": None, "platform": "cpu"}
    elif gpu and hn.gpu_backend(str(gpu)):
        # КАРТА НЕ NVIDIA (двенадцатый круг): видеопамять настоящая, но CUDA нет —
        # отбор идёт по записанному запуску на ROCm / XPU (`hn.backend_state`).
        поля["self_host"] = {
            "gpu": gpu,
            "vram_gb": память.get("vram_gb"),
            "platform": hn.gpu_backend(str(gpu)),
        }
    else:
        поля["self_host"] = {"gpu": gpu, "vram_gb": память.get("vram_gb")}


def _допущения_spec(raw: Any, поля: dict[str, Any], ошибки: list[str]) -> None:
    """`spec.priors`: {id: bool} — id из таблицы рецептов; иначе ошибка с перечнем."""
    from studio.recipes.table import PRIORS  # таблица — только данные, цикла нет

    if not isinstance(raw, Mapping):
        ошибки.append("spec.priors: an object {prior_id: false} — e.g. {\"t2v_fps_native\": false}")
        return
    годные: dict[str, bool] = {}
    for ключ, значение in raw.items():
        if str(ключ) not in PRIORS:
            ошибки.append(f"spec.priors.{ключ}: unknown prior (known: {', '.join(PRIORS)})")
        elif not isinstance(значение, bool):
            ошибки.append(f"spec.priors.{ключ}={значение!r}: must be true or false")
        else:
            годные[str(ключ)] = значение
    if годные:
        поля["priors"] = годные


def _выходы_spec(raw: Any, поля: dict[str, Any], ошибки: list[str]) -> None:
    """`spec.outputs` -> виды выходов; запись объектом {kind, loop?, tileable?} (пятнадцатый круг).

    Строка — прежняя форма. `loop` / `tileable` — свойства выхода: петля без шва
    (первый кадр = последний), текстура без шва по краям. Поле названо хоть у
    одного выхода — `Spec.loop` / `Spec.tileable` = есть ли такой выход.
    """
    виды: list[str] = []
    записи: list[dict[str, Any]] = []
    флаги: dict[str, list[bool]] = {ключ: [] for ключ in OUTPUT_ITEM_FIELDS[1:]}
    плохие: list[str] = []
    for i, выход in enumerate(_список(raw)):
        запись: dict[str, Any] = {}
        if isinstance(выход, Mapping):
            лишние = set(выход) - set(OUTPUT_ITEM_FIELDS)
            if лишние:
                ошибки.append(
                    f"spec.outputs[{i}]: unknown field(s) {', '.join(sorted(map(str, лишние)))} "
                    f"(known: {', '.join(OUTPUT_ITEM_FIELDS)})"
                )
            вид = str(выход.get("kind") or "").strip().lower()
            for ключ in флаги:
                if выход.get(ключ) is None:
                    continue
                if not isinstance(выход[ключ], bool):
                    ошибки.append(f"spec.outputs[{i}].{ключ}={выход[ключ]!r}: must be true or false")
                    continue
                запись[ключ] = выход[ключ]
        else:
            вид = str(выход).strip().lower()
        if вид not in OUTPUTS:
            плохие.append(вид or repr(выход))
            continue
        виды.append(вид)
        for ключ, значение in запись.items():
            флаги[ключ].append(значение)
        if запись:
            записи.append({"kind": вид, **запись})
    if плохие:
        ошибки.append(f"spec.outputs: {', '.join(плохие)} not in {', '.join(OUTPUTS)}")
    поля["outputs"] = tuple(dict.fromkeys(виды))
    if записи:
        поля["output_items"] = tuple(записи)
    for ключ, значения in флаги.items():
        if значения:
            поля[ключ] = any(значения)


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

    if raw.get("outputs") is not None:
        _выходы_spec(raw["outputs"], поля, ошибки)
    _enum("audio", AUDIO_MODES)
    _enum("objective", OBJECTIVES)
    _enum("audience", AUDIENCES)
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
    if raw.get("claims") is not None:
        # Четырнадцатый круг: заявления доходят до заметок плана (синтетический
        # ведущий своей программы, `checklist.synthetic_presenter_disclosure`).
        # Решают их политика людей и `claims_policy` — здесь только перенос.
        поля["claims"] = tuple(dict(з) for з in _список(raw["claims"]) if isinstance(з, Mapping))
    if raw.get("conditions") is not None:
        if any(not isinstance(у, str) for у in _список(raw["conditions"])):
            ошибки.append('spec.conditions: a list of short phrases, e.g. ["profile face", "logo legible"]')
        поля["conditions"] = tuple(
            dict.fromkeys(str(у).strip() for у in _список(raw["conditions"]) if str(у).strip())
        )
    if raw.get("edit") is not None:
        правки = [str(п).strip().lower().replace("_", "-").replace(" ", "-") for п in _список(raw["edit"]) if str(п).strip()]
        правки = [EDIT_ALIASES.get(п, п) for п in правки]
        чужие = [п for п in правки if п not in EDIT_VALUES]
        if чужие:
            ошибки.append(
                f"spec.edit: {', '.join(map(repr, чужие))} — allowed: {', '.join(EDIT_VALUES)}"
            )
        поля["edit"] = tuple(dict.fromkeys(п for п in правки if п in EDIT_VALUES))
    if raw.get("lipsync") is not None:
        if not isinstance(raw["lipsync"], bool):
            ошибки.append(f"spec.lipsync={raw['lipsync']!r}: must be true or false")
        else:
            поля["lipsync"] = raw["lipsync"]
    for ключ in ("live", "cast_together", "training_use"):
        if raw.get(ключ) is not None:
            if not isinstance(raw[ключ], bool):
                ошибки.append(f"spec.{ключ}={raw[ключ]!r}: must be true or false")
            else:
                поля[ключ] = raw[ключ]
    for ключ, целое in (("single_take_s", False), ("dataset_count", True)):
        if raw.get(ключ) is not None:
            try:
                поля[ключ] = _положительное(raw[ключ], целое)
            except ValueError as e:
                ошибки.append(f"spec.{ключ}={raw[ключ]!r}: {e}")
    _enum("edit_target", EDIT_TARGETS)
    if raw.get("consistency") is not None:
        оси = [str(з).strip().lower() for з in _список(raw["consistency"]) if str(з).strip()]
        чужие = [з for з in оси if з not in CONSISTENCY_AXES]
        if чужие:
            ошибки.append(f"spec.consistency: {', '.join(чужие)} not in {', '.join(CONSISTENCY_AXES)}")
        поля["consistency"] = tuple(dict.fromkeys(з for з in оси if з in CONSISTENCY_AXES))
    _поля_r16(raw, поля, ошибки)
    if raw.get("open_weights") is not None:
        if not isinstance(raw["open_weights"], bool):
            ошибки.append(f"spec.open_weights={raw['open_weights']!r}: must be true or false")
        else:
            поля["open_weights"] = raw["open_weights"]
    if raw.get("priors") is not None:
        _допущения_spec(raw["priors"], поля, ошибки)
    if поля.get("per_shot_s") and поля.get("shots") and not поля.get("duration_s"):
        поля["duration_s"] = поля["per_shot_s"] * поля["shots"]
    return Spec(**поля, source={к: SOURCE_SPEC for к in поля}), ошибки


def _список_из(raw: Any, ключ: str, допустимо: tuple[str, ...], ошибки: list[str], где: str = "spec") -> tuple[str, ...]:
    """Список значений из перечня; чужие — ошибка с перечнем (строгость полей пятнадцатого круга)."""
    значения = [str(з).strip().lower() for з in _список(raw) if str(з).strip()]
    чужие = [з for з in значения if з not in допустимо]
    if чужие:
        ошибки.append(f"{где}.{ключ}: {', '.join(чужие)} not in {', '.join(допустимо)}")
    return tuple(dict.fromkeys(з for з in значения if з in допустимо))


def _анонимизация_spec(raw: Any, ошибки: list[str]) -> dict[str, Any] | None:
    """`spec.anonymise`: {faces?, voice?, method?} или false (= не анонимизировать, что бы ни говорили слова)."""
    if raw is False:
        return {"faces": False, "voice": False, "method": None}
    if not isinstance(raw, Mapping):
        ошибки.append(
            "spec.anonymise: an object {faces?: bool, voice?: bool, method?: "
            + " | ".join(ANONYMISE_METHODS) + "} or false"
        )
        return None
    лишние = set(raw) - set(ANONYMISE_FIELDS)
    if лишние:
        ошибки.append(
            f"spec.anonymise: unknown field(s) {', '.join(sorted(map(str, лишние)))} (known: {', '.join(ANONYMISE_FIELDS)})"
        )
    запись: dict[str, Any] = {"faces": None, "voice": None, "method": None}
    for ключ in ("faces", "voice"):
        if raw.get(ключ) is not None:
            if not isinstance(raw[ключ], bool):
                ошибки.append(f"spec.anonymise.{ключ}={raw[ключ]!r}: must be true or false")
            else:
                запись[ключ] = raw[ключ]
    методы = _список_из(raw.get("method"), "method", ANONYMISE_METHODS, ошибки, "spec.anonymise") if raw.get(
        "method"
    ) is not None else ()
    лицам = [м for м in методы if м in FACE_ANON_METHODS]
    if лицам:
        запись["method"] = лицам[0]
        if запись["faces"] is None:
            запись["faces"] = True
    if "voice-replace" in методы and запись["voice"] is None:
        запись["voice"] = True
    if запись["faces"] and not запись["method"]:
        запись["method"] = FACE_ANON_METHODS[0]
    запись["faces"] = bool(запись["faces"])
    запись["voice"] = bool(запись["voice"])
    if not запись["faces"]:
        запись["method"] = None
    return запись


def _сдача_spec(raw: Any, ошибки: list[str]) -> dict[str, Any] | None:
    """`spec.delivery`: {platform?, dynamic_range?, stems?, direction?, format?}."""
    if not isinstance(raw, Mapping):
        ошибки.append("spec.delivery: an object {" + ", ".join(DELIVERY_FIELDS) + "}")
        return None
    лишние = set(raw) - set(DELIVERY_FIELDS)
    if лишние:
        ошибки.append(
            f"spec.delivery: unknown field(s) {', '.join(sorted(map(str, лишние)))} (known: {', '.join(DELIVERY_FIELDS)})"
        )
    запись: dict[str, Any] = {}
    for ключ, допустимо in (("platform", DELIVERY_PLATFORMS), ("format", DELIVERY_FORMATS)):
        if raw.get(ключ) is not None:
            запись[ключ] = _список_из(raw[ключ], ключ, допустимо, ошибки, "spec.delivery")
    for ключ, допустимо in (("dynamic_range", DYNAMIC_RANGES), ("direction", CALL_DIRECTIONS)):
        if raw.get(ключ) is not None:
            з = str(raw[ключ]).strip().lower()
            if з not in допустимо:
                ошибки.append(f"spec.delivery.{ключ}: {з} not in {', '.join(допустимо)}")
            else:
                запись[ключ] = з
    if raw.get("stems") is not None:
        if not isinstance(raw["stems"], bool):
            ошибки.append(f"spec.delivery.stems={raw['stems']!r}: must be true or false")
        else:
            запись["stems"] = raw["stems"]
    return запись


def _поля_r16(raw: Mapping[str, Any], поля: dict[str, Any], ошибки: list[str]) -> None:
    """Поля решений шестнадцатого круга: строгие — чужое значение называется с перечнем."""
    if raw.get("anonymise") is not None:
        анон = _анонимизация_spec(raw["anonymise"], ошибки)
        if анон is not None:
            поля["anonymise"] = анон
    if raw.get("delivery") is not None:
        сдача = _сдача_spec(raw["delivery"], ошибки)
        if сдача is not None:
            поля["delivery"] = сдача
    for ключ in ("voiceover", "follows_picture", "animate_input", "community"):
        if raw.get(ключ) is not None:
            if not isinstance(raw[ключ], bool):
                ошибки.append(f"spec.{ключ}={raw[ключ]!r}: must be true or false")
            else:
                поля[ключ] = raw[ключ]
    for ключ, допустимо in (
        ("domain", DOMAINS),
        ("subject", SUBJECTS),
        ("accessibility", ACCESSIBILITY_NEEDS),
        ("audio_content", AUDIO_CONTENTS),
    ):
        if raw.get(ключ) is not None:
            поля[ключ] = _список_из(raw[ключ], ключ, допустимо, ошибки)
    for ключ, допустимо in (("style", STYLES), ("display", DISPLAYS)):
        if raw.get(ключ) is not None:
            з = str(raw[ключ]).strip().lower()
            if з not in допустимо:
                ошибки.append(f"spec.{ключ}: {з} not in {', '.join(допустимо)}")
            else:
                поля[ключ] = з


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
        поля["self_host"] = {
            "gpu": свой.gpu,
            "vram_gb": свой.vram_gb,
            **({"platform": свой.gpu_backend} if свой.gpu_backend else {}),
        }
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
        # СВОЙ MAC (девятый круг): единая память — не видеопамять CUDA, но
        # потолок: модель, чьи веса больше всей памяти машины, не запустится.
        # Платформа решает и порядок: запуск на MPS/MLX/Core ML по записи
        # старше молчания (`hardneed.apple_state`).
        if свой.get("platform") == "cpu":
            поля["cpu_only"] = True
            поля["vram_gb"] = None
        if свой.get("platform") in hn.GPU_BACKEND_ATTRS:
            поля["gpu_backend"] = str(свой["platform"])
        if свой.get("platform") == "apple-silicon":
            поля["apple_silicon"] = True
            единая = свой.get("unified_memory_gb")
            поля["unified_memory_gb"] = float(единая) if единая is not None else None
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


def face_swap_items(spec: "Spec") -> int:
    """How many stills an image face swap makes: `spec.shots`, else the largest image item of at least
    `FACE_SWAP_BATCH_MIN` (the targets of a data set); 0 — as many as ordered frames (one)."""
    if spec.shots:
        return int(spec.shots)
    if spec.dataset_count:
        # Пятнадцатый круг: датасет назван полем — столько образцов и делается.
        return int(spec.dataset_count)
    штуки = [int(з.get("count") or 1) for з in spec.input_items if str(з.get("kind")) in ("photo", "image")]
    наибольшее = max(штуки, default=0)
    return наибольшее if наибольшее >= FACE_SWAP_BATCH_MIN else 0


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
#: Тринадцатый круг: референсы персонажей — ОБЩИЙ актив серии, делаются один раз.
NOTE_CAST_REFS = "референсы персонажей ({n}) делаются ОДИН раз и общие для всех шотов — не генерируются на каждый шот"
NOTE_CAST_KEYFRAMES = "ключевой кадр каждого шота — правка по общим референсам персонажей (лица не разъезжаются)"
NOTE_SPEAKER_LIPS_SHOTS = "губы двигает липсинк в КАЖДОМ шоте, где говорят в кадре ({n})"
#: Четырнадцатый круг: персонажи кадра не делят — шот оживляется прямо от референса.
NOTE_CAST_STRAIGHT = (
    "каждый шот оживляется прямо от референса своего персонажа (image-to-video): персонажи кадра не делят, "
    "отдельный ключевой кадр на шот не нужен"
)
NOTE_SINGER_LIPS = "исполнитель поёт в кадре: липсинк под вокал ВАШЕГО трека в каждой сцене ({n})"
NOTE_MUSIC_VIDEO = "клип из сцен: референс исполнителя один раз, каждая сцена оживляется по нему; дорожку кладёт монтаж"
NOTE_R2V = "каждый шот — по одному референсу персонажа (reference-to-video)"
NOTE_VISUALISER = "только картинка под ВАШ трек: музыка не генерируется, дорожку кладёт монтаж"
NOTE_SING = "ВАШ снимок поёт ВАШУ дорожку: аватар, ведомый звуком; ни синтеза речи, ни генерации музыки"
NOTE_SHORTS_TRANSCRIPT = "расшифровка с таймингами ВАШЕГО длинного видео — по ней выбираются фрагменты"
NOTE_SHORTS_EDIT = "каждый короткий ролик вырезан и перекадрирован из ВАШЕГО видео — ничего не генерируется"
NOTE_DUB_MUX = "новая дорожка кладётся в ВАШЕ видео при сборке; губы не двигаются (spec.lipsync=false)"
NOTE_DUB_AUDIO = "отдаётся дорожка на новом языке; видео не трогается и губ не двигает никто"
NOTE_STABILISE = "стабилизация — монтажный инструмент (ffmpeg vidstab или Gyroflow по гироскопу), не модель"
NOTE_VISUALISER_SYNC = "реакция на звук делается при сборке; генерируемое видео трек не слышит"
NOTE_FRAMES_FROM_VIDEO = "кадры для замены лица вынимаются из ВАШЕГО видео при сборке (ffmpeg), лицо меняется на каждом снимке"
#: Round 14 (DECISION CONSTANT, T1): from this many images in one input item a face swap without
#: `spec.shots` counts the item as the targets (a data set), not as one picture.
FACE_SWAP_BATCH_MIN = 10
NOTE_SERIES_REF = "один референс персонажа, и каждая картинка серии — правка по нему"
NOTE_MOTION = "движение берётся из ВАШЕГО ведущего видео, внешность — со снимка (motion control), а не выдумывается"
NOTE_SERIES_EDIT = "{n} картинок — правки по референсу (а не {n} независимых генераций); вариант — обучить LoRA"
NOTE_SIGN = (
    "язык жестов генеративные модели не делают: липсинк и говорящие аватары двигают губы, а не руки — "
    "пробел записан, план не строится"
)
#: Двенадцатый круг: работы, которые добавляет СОСТАВ выходов (`_все_выходы`).
NOTE_NARRATION = "закадровый голос для заказанной речи: синтез по тексту, кладётся поверх картинки при сборке"
NOTE_NARRATION_MIX = "голос кладётся поверх картинки при сборке (ffmpeg amix, приглушение фона под речью)"
NOTE_SPEAKER_LIPS = "говорящий виден в кадре: губы двигает липсинк под синтезированную речь"
NOTE_PHOTO_TO_VIDEO = "заказано видео, а работа отдаёт снимок: снимок оживляется (image-to-video)"
NOTE_POSTER = "заказана картинка, а план делает только видео: картинка (обложка, постер) генерируется отдельно"
NOTE_VISUALISER_NO_TRACK = (
    "трек не приложен: визуал делается петлями без него, дорожку кладёт монтаж, когда трек будет"
)
NOTES_EN: dict[str, str] = {
    NOTE_CAST_KEYFRAMES: "each shot's keyframe is an edit from the shared character references (faces do not drift)",
    NOTE_CAST_STRAIGHT: (
        "every shot is animated straight from its character's reference (image-to-video): the characters do not "
        "share the frame, so no per-shot keyframe is made"
    ),
    NOTE_MUSIC_VIDEO: (
        "a music video of scenes: the performer's reference is made once and every scene is animated from it; "
        "the track is laid in at assembly"
    ),
    NOTE_NARRATION: "a voice-over for the ordered speech: synthesised from the text and laid over the picture at assembly",
    NOTE_NARRATION_MIX: "the voice is laid over the picture at assembly (ffmpeg amix, background ducked under speech)",
    NOTE_SPEAKER_LIPS: "the speaker is seen on screen: lip sync moves the lips to the synthesised speech",
    NOTE_PHOTO_TO_VIDEO: "a video is ordered and the job returns a still: the still is animated (image-to-video)",
    NOTE_POSTER: "a picture is ordered and the plan only makes video: the picture (cover, poster) is generated separately",
    NOTE_VISUALISER_NO_TRACK: (
        "no track attached: the visuals are made as loops without it, and assembly lays the track in once it exists"
    ),
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
    NOTE_MOTION: "the motion comes from YOUR driving video and the look from the photo (motion control), not invented",
    NOTE_SIGN: (
        "sign language is not something generative models do: lip sync and talking avatars move lips, not "
        "hands — a recorded gap, no plan is built"
    ),
}

#: Причины сборки, которые называет МАРШРУТ (а не состав шагов): дорожка
#: заказчика под картинкой, отбор фрагментов по расшифровке. Читает
#: `planner.нужна_сборка`. Ключ — пометка, значение — (ru, en).
ASSEMBLY_REASONS: dict[str, tuple[str, str]] = {
    NOTE_NARRATION_MIX: (
        "голос кладётся поверх картинки: ffmpeg amix, фон и музыка приглушаются под речью (sidechain) — 0 usd",
        "the voice is mixed over the picture: ffmpeg amix, background and music ducked under speech "
        "(sidechain) — 0 usd",
    ),
    NOTE_VISUALISER_NO_TRACK: (
        "трек не приложен: петли визуала режутся под длину ролика, дорожка кладётся, когда трек будет — 0 usd",
        "no track attached: the visual loops are cut to the clip length and the track is laid in once it "
        "exists — 0 usd",
    ),
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
    NOTE_FRAMES_FROM_VIDEO: (
        "кадры вынимаются из вашего видео ffmpeg (fps=… или select по сценам) — 0 usd; лицо меняется на каждом снимке",
        "the frames are extracted from your video with ffmpeg (fps=… or select by scene) — 0 usd; the face is "
        "swapped on each still",
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

# --- тринадцатый круг: правки, которые делает ТОЛЬКО монтаж -------------------------
#
# Скрытый набор: «обрезать начало и ускорить вдвое», «склеить три клипа и
# поставить логотип в угол», «наложить LUT и водяной знак» кончались ошибкой
# spec (таких значений `spec.edit` не было) или генеративной правкой ролика за
# десятки долларов; «вжечь приложенные SRT» — расшифровкой, которая не нужна.
# Это всё ffmpeg: 0 usd, модели нет, и вопрос не нужен, когда вход есть.
EDIT_TRIM = "trim"
EDIT_CONCAT = "concat"
EDIT_SPEED = "speed"
EDIT_LUT = "lut"
EDIT_WATERMARK = "watermark"
EDIT_LOGO = "logo-overlay"
EDIT_BURN_CAPTIONS = "burn-captions"
#: Кадрирование в другой формат (рефрейм, где объект в кадре остаётся целиком).
EDIT_CROP = "crop"

NOTE_TRIM = "обрезка по таймкодам — монтаж (ffmpeg -ss/-to), модели не нужно"
NOTE_CONCAT = "склейка клипов — монтаж (ffmpeg concat / xfade), модели не нужно"
NOTE_SPEED = "смена скорости — монтаж (ffmpeg setpts / atempo), модели не нужно"
NOTE_LUT = "цвет по LUT — монтаж (ffmpeg lut3d с вашим .cube), модели не нужно"
NOTE_WATERMARK = "водяной знак — монтаж (ffmpeg overlay вашего файла), модели не нужно"
NOTE_LOGO = "логотип поверх ролика — монтаж (ffmpeg overlay ВАШЕГО файла), буква в букву, модели не нужно"
NOTE_BURN_CAPTIONS = "ВАШИ субтитры (SRT/ASS) вжигаются монтажом (ffmpeg subtitles) — расшифровка не нужна"
NOTE_CROP = (
    "смена формата — кадрирование при монтаже с ведением лица/объекта (face/subject tracking), объект в "
    "кадре остаётся целиком; дорисовка краёв (outpaint) — только если объект обрезался бы"
)

#: Правка -> пометка сборки. КОНСТАНТА-РЕШЕНИЕ: эти правки делает монтаж ВСЕГДА,
#: что бы ни записал реестр (`ASSEMBLY_EDITS` — только когда эндпоинта нет).
ASSEMBLY_ONLY_EDITS: dict[str, str] = {
    EDIT_TRIM: NOTE_TRIM,
    EDIT_CONCAT: NOTE_CONCAT,
    EDIT_SPEED: NOTE_SPEED,
    EDIT_LUT: NOTE_LUT,
    EDIT_WATERMARK: NOTE_WATERMARK,
    EDIT_LOGO: NOTE_LOGO,
    EDIT_BURN_CAPTIONS: NOTE_BURN_CAPTIONS,
    EDIT_CROP: NOTE_CROP,
}
#: По-английски — для пометок и причин сборки (ru, en).
ASSEMBLY_ONLY_EN: dict[str, str] = {
    NOTE_TRIM: "trimming on timecodes is assembly (ffmpeg -ss/-to) — 0 usd, no model",
    NOTE_CONCAT: "joining the clips is assembly (ffmpeg concat / xfade) — 0 usd, no model",
    NOTE_SPEED: "the speed change is assembly (ffmpeg setpts / atempo) — 0 usd, no model",
    NOTE_LUT: "the colour LUT is applied at assembly (ffmpeg lut3d with your .cube) — 0 usd, no model",
    NOTE_WATERMARK: "the watermark is overlaid at assembly (ffmpeg overlay of your file) — 0 usd, no model",
    NOTE_LOGO: "the logo is overlaid from YOUR file at assembly (ffmpeg overlay), letter for letter — 0 usd, no model",
    NOTE_BURN_CAPTIONS: "YOUR subtitles (SRT/ASS) are burned in at assembly (ffmpeg subtitles) — no transcription needed, 0 usd",
    NOTE_CROP: (
        "the new aspect is an assembly crop with face/subject tracking (ffmpeg crop driven by a tracker — "
        "MediaPipe / AutoFlip, Premiere Auto Reframe, DaVinci Smart Reframe) — 0 usd; the subject stays whole, "
        "and outpainting the edges is only for a subject that a crop would cut"
    ),
}
NOTES_EN.update(ASSEMBLY_ONLY_EN)
ASSEMBLY_REASONS.update({ru: (ru + " — 0 usd", en) for ru, en in ASSEMBLY_ONLY_EN.items()})
#: Как вызывающий называет эти правки в `spec.edit` -> имя правки.
EDIT_ALIASES: dict[str, str] = {
    "cut": EDIT_TRIM,
    "shorten": EDIT_TRIM,
    "join": EDIT_CONCAT,
    "merge": EDIT_CONCAT,
    "stitch": EDIT_CONCAT,
    "speed-change": EDIT_SPEED,
    "speed-up": EDIT_SPEED,
    "retime": EDIT_SPEED,
    "colour-grade": EDIT_LUT,
    "color-grade": EDIT_LUT,
    "grade": EDIT_LUT,
    "colour-lut": EDIT_LUT,
    "color-lut": EDIT_LUT,
    "logo": EDIT_LOGO,
    "overlay": EDIT_LOGO,
    "subtitles": EDIT_BURN_CAPTIONS,
    "captions": EDIT_BURN_CAPTIONS,
    "burn-in": EDIT_BURN_CAPTIONS,
    "burn-subtitles": EDIT_BURN_CAPTIONS,
    "resize": EDIT_CROP,
}
#: Все значения `spec.edit`: правки реестра и правки монтажа.
EDIT_VALUES: tuple[str, ...] = (*ep.EDIT_INTENTS, *ASSEMBLY_ONLY_EDITS)

#: Монтажные правки СЛОВАМИ брифа — когда `spec.edit` о них молчит (правка ролика
#: без названной правки уходила в генеративную правку по инструкции).
ASSEMBLY_EDIT_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (EDIT_TRIM, re.compile(
        r"\btrim\w*|\bcut (?:off|out|down)\b|cut the (?:first|last|start|end|beginning|ending)|\bshorten\w*"
        r"|обреж\w*|обрез\w* (?:начал|конец|конц|перв|последн)|укорот\w*|вырежь\w* (?:начал|конец)", re.I)),
    (EDIT_CONCAT, re.compile(
        r"\bjoin\w*|concat\w*|\bstitch\w*|\bmerge\w*|combine\w* (?:\w+ ){0,3}(?:clips|videos|shots)"
        r"|склей\w*|склеи\w*|соедин\w* (?:\w+ ){0,2}(?:ролик|клип|видео)|объедин\w* (?:\w+ ){0,2}(?:ролик|клип|видео)",
        re.I)),
    (EDIT_SPEED, re.compile(
        r"speed (?:it |them )?up|sped up|speed[- ]change|change the speed|\b\d(?:\.\d+)?\s?x (?:speed|faster|slower)"
        r"|(?:twice|2x|double) (?:as )?(?:fast|speed)|ускор\w*|в (?:два|2) раза быстрее", re.I)),
    (EDIT_LUT, re.compile(r"\bluts?\b|\.cube\b|colou?r[- ]?grad\w*|\bgrade it\b|цветокор\w*|\bлут\w*", re.I)),
    (EDIT_WATERMARK, re.compile(r"watermark\w*|водян\w* знак\w*", re.I)),
    (EDIT_LOGO, re.compile(
        r"(?:add|put|place|overlay|burn|insert|stamp|show)\w* (?:\w+ ){0,3}logo|logo (?:overlay|bug|in the (?:\w+ )?corner)"
        r"|(?:добав|налож|постав|встав|размест)\w* (?:\w+ ){0,2}логотип\w*|логотип\w* в угл\w*", re.I)),
    (EDIT_BURN_CAPTIONS, re.compile(
        r"burn\w*[- ]in|burn (?:\w+ ){0,3}(?:subtitl|caption|srt)|\bsrt\b|\.ass\b|hard[- ]?(?:sub|code)\w*"
        r"|(?:add|put)\w* (?:\w+ ){0,3}(?:subtitles|captions)|вжеч\w*|вшей\w* субтитр\w*|(?:добав|налож)\w* (?:\w+ ){0,2}субтитр\w*",
        re.I)),
    (EDIT_CROP, re.compile(r"\bcrop\w*|кадрир\w*", re.I)),
)
#: Перед монтажной правкой — её отмена или удаление («remove the watermark» — работа модели).
ASSEMBLY_WORD_NEGATED = re.compile(
    r"(?:remov\w*|eras\w*|get rid of|clean (?:up|off)|without|no|убра\w*|убер\w*|удал\w*|сотр\w*|без)\s+(?:\w+\s+){0,2}$",
    re.I,
)
#: Стиль словами: правка «restyle» тогда — работа модели, а не LUT.
STYLE_WORDS = re.compile(
    r"\banime\b|cartoon|painting|watercolou?r|\bstyle\b|look like|claymation|pixar|ghibli|аниме|мульт\w*|"
    r"живопис\w*|акварел\w*|в стиле|стилиз\w*",
    re.I,
)

#: Рефрейм КАДРИРОВАНИЕМ: формат-цель не шире исходника (с допуском) — объект в
#: кадре остаётся, если его вести. КОНСТАНТА-РЕШЕНИЕ (Т1): 5 % на округление
#: соотношений (4:5 против 0.8, 1.78 против 16:9).
CROP_ASPECT_TOLERANCE = 1.05
#: Кадр исходника не назван: формат-цель не шире этого — вертикаль или квадрат
#: из горизонтального исходника (кадрирование); шире — исходник был не
#: горизонтальным (иначе менять нечего), и края дорисовываются. КОНСТАНТА-РЕШЕНИЕ (Т1).
UNKNOWN_SOURCE_CROP_MAX = 1.0
#: Объект обрезался бы, или дорисовку просят словами — кадрирование не годится.
KEEP_WHOLE_FRAME = re.compile(
    r"outpaint\w*|extend (?:the )?(?:sides|edges|frame|background)|fill (?:in )?(?:the )?(?:sides|edges|gaps|bars)"
    r"|expand (?:the )?(?:frame|canvas|sides|background)|without crop\w*|(?:don'?t|do not|no) crop\w*"
    r"|keep (?:the )?(?:whole|entire|full|everyone|everything|all|both)|nothing (?:cut|cropped)|black bars"
    r"|дорис\w*|расшир\w* (?:кадр|фон|края)|без обрез\w*|не обреза\w*|целиком",
    re.I,
)


def _соотношение_в_тексте(текст: str, кроме: float | None) -> float | None:
    """Соотношение ИСХОДНИКА словами брифа: «16:9 interview», «vertical clip» — не формат-цель."""
    низ = _norm(текст)
    for м in _ASPECT.finditer(низ):
        r = aspect_ratio(м.group(1))
        if r is not None and (кроме is None or abs(r - кроме) > 0.01):
            return r
    if VERTICAL.search(низ) and (кроме is None or кроме > 1):
        return 9 / 16
    if HORIZONTAL.search(низ) and (кроме is None or кроме < 1):
        return 16 / 9
    return None


def рефрейм_кадрированием(spec: "Spec", текст: str = "") -> bool:
    """Рефрейм — кадрирование при монтаже: формат-цель не шире исходника и дорисовку не просят."""
    if KEEP_WHOLE_FRAME.search(_norm(текст)) or any(KEEP_WHOLE_FRAME.search(_norm(у)) for у in spec.conditions):
        return False
    цель = aspect_ratio(spec.aspect) if spec.aspect else None
    if цель is None:
        return False
    кадр = source_frame(spec)
    исходник = (кадр[0] / кадр[1]) if кадр else _соотношение_в_тексте(текст, цель)
    if исходник is None:
        return цель <= UNKNOWN_SOURCE_CROP_MAX
    return цель <= исходник * CROP_ASPECT_TOLERANCE


def монтажные_правки_словами(текст: str) -> tuple[str, ...]:
    """Монтажные правки, названные словами брифа (без отмены перед ними)."""
    низ = _norm(текст)
    найдено: list[str] = []
    for правка, образец in ASSEMBLY_EDIT_WORDS:
        for м in образец.finditer(низ):
            if not ASSEMBLY_WORD_NEGATED.search(низ[: м.start()]):
                найдено.append(правка)
                break
    return tuple(найдено)


def правки_монтажа(spec: "Spec", текст: str = "") -> tuple[str, ...]:
    """Правки `video-edit` после чтения брифа: монтажные слова, рефрейм-кадрирование, LUT вместо restyle.

    Читается только у работы над ВАШИМ видео (`video-edit`, `edit` над видео) —
    у прочих работ правок нет.
    """
    if "video" not in spec.inputs or spec.task not in ("video-edit", "edit") or not текст:
        return spec.edit
    правки = list(spec.edit)
    словами = монтажные_правки_словами(текст)
    if ep.EDIT_RESTYLE in правки and EDIT_LUT in словами and not STYLE_WORDS.search(_norm(текст)):
        правки.remove(ep.EDIT_RESTYLE)
    if ep.EDIT_REFRAME in правки and рефрейм_кадрированием(spec, текст):
        правки[правки.index(ep.EDIT_REFRAME)] = EDIT_CROP
    # Монтажные правки словами: всегда, когда spec о них молчит; кадрирование словами —
    # только когда нет рефрейма (он решён выше).
    for п in словами:
        if п == EDIT_CROP and (ep.EDIT_REFRAME in правки or EDIT_CROP in правки or not spec.aspect):
            continue
        if п not in правки:
            правки.append(п)
    return tuple(dict.fromkeys(правки))


def монтаж_целиком(spec: "Spec", текст: str = "") -> bool:
    """Работа по spec (и словам брифа) — ТОЛЬКО монтаж: план без шагов-моделей, без вопросов о длине и языке."""
    if "video" not in spec.inputs or set(spec.outputs) - {"video", "text"}:
        return False
    if spec.task == "captions" and "script" in spec.inputs and not spec.then_tasks:
        return True
    if spec.task not in ("video-edit", "edit") or spec.then_tasks:
        return False
    правки = правки_монтажа(spec, текст)
    return bool(правки) and all(п in ASSEMBLY_ONLY_EDITS or п in ASSEMBLY_EDITS for п in правки)

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
    на выходе видео (или выход не назван) и речь не закадровая (`audio` != voiceover)."""
    if spec.lipsync is not None:
        return spec.lipsync
    return ("video" in spec.outputs or not spec.outputs) and spec.audio != "voiceover"


def note_en(ru: str) -> str | None:
    """Пометка маршрута по-английски; None — пометка не наша."""
    if ru in NOTES_EN:
        return NOTES_EN[ru]
    from studio.recipes.apply import NOTES_EN as RECIPE_NOTES_EN  # рецепты импортируют этот модуль

    if ru in RECIPE_NOTES_EN:
        return RECIPE_NOTES_EN[ru]
    from studio.recipes.apply import NOTE_LOOP_ONCE

    for шаблон, en in (
        (NOTE_LOOP_ONCE[0].replace("{s}", "{n}"), NOTE_LOOP_ONCE[1].replace("{s}", "{n}")),
        (NOTE_CAST_REFS, "the character references ({n}) are made ONCE and shared by every shot — not regenerated per shot"),
        (NOTE_SPEAKER_LIPS_SHOTS, "lip sync moves the lips in EVERY shot where someone speaks on screen ({n})"),
        (NOTE_SINGER_LIPS, "the performer sings on camera: lip sync to the vocals of YOUR track in every scene ({n})"),
    ):
        найдено = re.fullmatch(re.escape(шаблон).replace(re.escape("{n}"), r"(\d+(?:\.\d+)?)"), ru)
        if найдено:
            return en.format(n=найдено.group(1))
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
#: Ролик из стольких шотов с одним персонажем строится от одного референса
#: (кадр персонажа -> оживление), а не независимыми t2v. КОНСТАНТА-РЕШЕНИЕ.
SERIES_SHOTS_MIN = 2
#: Ролик с одним персонажем ДЛИННЕЕ одного прогона генератора (одиннадцатый
#: круг): «серия мультсериала на 3 минуты про робота» шла одним t2v — а 3 минуты
#: это десятки прогонов, и без референса персонаж в каждом другой. Длиннее
#: 15 с (самый длинный записанный прогон Kling 3.0 / Seedance 2.x) — от
#: референса. КОНСТАНТА-РЕШЕНИЕ.
SERIES_DURATION_MIN_S = 15.0
#: Четырнадцатый круг: сколько референсов у серии с ОДНИМ персонажем — один на всю
#: серию, сколько бы шотов ни вывела длительность. КОНСТАНТА-РЕШЕНИЕ.
SINGLE_REFERENCE = 1


def серия_с_персонажем(spec: "Spec") -> bool:
    """Один персонаж в нескольких шотах (или в ролике длиннее прогона): референс, затем оживление."""
    if (spec.characters or 0) < SERIES_CHARACTERS_MIN:
        return False
    if (spec.shots or 0) >= SERIES_SHOTS_MIN:
        return True
    return spec.duration_s is not None and float(spec.duration_s) > SERIES_DURATION_MIN_S

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
    # Запись И текст на входе — образец голоса и то, что им сказать (одиннадцатый
    # круг): «вот 30 секунд моего голоса, прочитай им сценарий» не выводило ни
    # шага и спрашивало, что заказано. Шаг озвучки здесь — место, которое рецепт
    # `voice_sample_clone` отдаёт клонированию голоса.
    образец = "audio" in spec.inputs and "script" in spec.inputs
    if "speech" in выходы and spec.audio != "native" and ("audio" not in spec.inputs or образец):
        шаги.append("озвучка")
    if "music" in выходы:
        шаги.append("музыка")
    if "sfx" in выходы and spec.audio != "native":
        шаги.append("звук_фон")


#: Тринадцатый круг: операция «видео -> звук» — шумы и саундтрек ПО КАРТИНКЕ
#: принесённого видео (MMAudio, HunyuanVideo-Foley, ThinkSound). Ставит её
#: рецепт `foley_for_picture` вместо шага шумов (и музыки под действие).
V2A_STEP = "звук_по_видео"
#: Выходы-звук, которые «видео -> звук» делает по принесённой картинке.
V2A_OUTPUTS: frozenset[str] = frozenset({"sfx", "music"})


def звук_к_своему_видео(spec: "Spec") -> bool:
    """Заказан ТОЛЬКО звук к ВАШЕМУ видео: видео принесено, выход — звук (и само видео), правки нет.

    «Сделай звук к этому немому ролику» без названной работы спрашивало работу,
    а `video-edit` без названной правки ставило генеративную правку ролика —
    хотя заказан один звук. Работа видна по входу и выходу.
    """
    выходы = set(spec.outputs)
    return (
        "video" in spec.inputs
        and bool(выходы & V2A_OUTPUTS)
        and выходы <= V2A_OUTPUTS | {"video"}
        and not spec.edit
        and spec.task in (None, "generate", "video-edit", "edit")
        and not spec.then_tasks
    )


def _подложка(выходы: set[str]) -> tuple[str, ...]:
    """Музыка и шумы ПОД правленое видео заказчика (свадебный ролик «с музыкой»).

    Речь сюда не входит: у принесённого видео свой звук, а новый голос — это
    уже дубляж, другая работа.
    """
    return tuple(ш for в, ш in (("music", "музыка"), ("sfx", "звук_фон")) if в in выходы)


#: Двенадцатый круг: КТО ОТДАЁТ какой выход (шаги — имена операций плановщика).
#: Состав выходов (`_все_выходы`) сверяет с этим каждый вид в `spec.outputs`:
#: «отреставрировать хронику И наложить диктора» терял диктора, потому что
#: маршрут реставрации возвращал один шаг и о речи не знал.
SPEECH_MAKERS: frozenset[str] = frozenset({"озвучка", "клонирование_голоса", "дубляж", "видео_со_звуком"})
#: Работы над видео заказчика, которые оставляют ЕГО звук: речь в выходе — речь исходника.
SOURCE_SOUND_TASKS: frozenset[str | None] = frozenset(
    {"cut-to-shorts", "captions", "transcribe", "video-edit", "edit", "face-replace", "lipsync", "dub-translate"}
)
#: Шаги, которым речь нужна на входе: её дописывает замыкание плановщика.
SPEECH_TAKERS: frozenset[str] = frozenset({"говорящий_аватар", "липсинк"})
VIDEO_MAKERS: frozenset[str] = frozenset(
    {
        "генерация_видео",
        "оживление",
        "видео_по_референсу",
        "говорящий_аватар",
        "липсинк",
        "перенос_движения",
        "замена_персонажа",
        "замена_фигуры",
        "правка_видео",
        "апскейл",
        "реставрация",
        "раскраска",
        "интерполяция_кадров",
        "удаление_фона_видео",
        "оборот_360",
        "видео_со_звуком",
    }
)
#: Генерируемая картинка, на которой говорящего можно «озвучить» липсинком.
GENERATED_VIDEO: frozenset[str] = frozenset({"генерация_видео", "оживление", "видео_по_референсу"})
IMAGE_MAKERS: frozenset[str] = frozenset(
    {
        "генерация_изображения",
        "редактирование_изображения",
        "примерка",
        "апскейл_изображения",
        "реставрация_изображения",
        "раскраска_изображения",
        "удаление_фона",
        "замена_лица_изображения",
    }
)


def _выход_без_шага(виды: list[str]) -> tuple[str, str, str, tuple[str, ...], tuple[str, ...]]:
    названо = ", ".join(виды)
    return (
        "выход_без_шага",
        f"заказан выход ({названо}), но ни одна работа плана его не делает — уточните, откуда он берётся",
        f"the output ({названо}) is ordered but no step of the plan makes it — say where it comes from",
        ("он у меня есть — приложу", "убрать его из заказа"),
        ("I have it and will attach it", "drop it from the order"),
    )


def _все_выходы(spec: Spec, м: Маршрут) -> Маршрут:
    """СОСТАВ: каждый заказанный вид выхода делает какой-то шаг (двенадцатый круг).

    Маршрут одной работы знает только свою работу: реставрация — реставрацию,
    апскейл — апскейл. Речь, музыка, шумы, оживление снимка и губы говорящего
    в кадре, которых работа не делает, дописываются здесь; вид, который так и
    остался без шага, — ВОПРОС, а не молча выпавшая часть заказа.
    """
    if м.нехватка is not None or м.пробел is not None or not (м.шаги or м.сборка):
        return м
    шаги = list(м.шаги)
    пометки = dict(м.пометки)
    сборка = list(м.сборка)
    выходы = set(spec.outputs)
    входы = set(spec.inputs)
    своя_речь = "audio" in входы and "script" not in входы
    # Речь ВАШЕГО видео — его собственная, когда работа оставляет звук исходника
    # (нарезка, субтитры, правка): голос дописывается, только если назван закадр.
    if "video" in входы and spec.task in SOURCE_SOUND_TASKS and spec.audio != "voiceover":
        своя_речь = True
    if "video" in выходы and not (set(шаги) & VIDEO_MAKERS or сборка or "video" in входы):
        if "photo" in входы and set(шаги) & IMAGE_MAKERS:
            шаги.append("оживление")
            пометки.setdefault("оживление", NOTE_PHOTO_TO_VIDEO)
    видео = bool(set(шаги) & VIDEO_MAKERS or сборка or "video" in входы)
    if (
        "speech" in выходы
        and spec.audio != "native"
        and not set(шаги) & (SPEECH_MAKERS | SPEECH_TAKERS)
        and not своя_речь
    ):
        шаги.append("озвучка")
        пометки.setdefault("озвучка", NOTE_NARRATION)
        if видео:
            сборка.append(NOTE_NARRATION_MIX)
    if "music" in выходы and "музыка" not in шаги and "audio" not in входы:
        шаги.append("музыка")
    if "sfx" in выходы and "звук_фон" not in шаги and spec.audio != "native":
        шаги.append("звук_фон")
    штук = dict(м.штук)
    поёт = "audio" in входы and "speech" not in выходы
    if (
        spec.speaker_on_screen
        and ({"video", "speech"} <= выходы or ("video" in выходы and поёт))
        and spec.audio != "native"
        and "video" not in входы
        and set(шаги) & GENERATED_VIDEO
        and not set(шаги) & SPEECH_TAKERS
    ):
        шаги.append("липсинк")
        пометки.setdefault("липсинк", NOTE_SINGER_LIPS.format(n=spec.shots or 1) if поёт else NOTE_SPEAKER_LIPS)
        if (spec.shots or 0) >= SERIES_SHOTS_MIN:
            # ТРИНАДЦАТЫЙ КРУГ: губы двигаются в КАЖДОМ шоте, где говорят (или поют).
            штук["липсинк"] = int(spec.shots or 0)
            if not поёт:
                пометки["липсинк"] = NOTE_SPEAKER_LIPS_SHOTS.format(n=spec.shots)
    if "image" in выходы and видео and not set(шаги) & IMAGE_MAKERS and "photo" not in входы:
        шаги.insert(0, "генерация_изображения")
        пометки.setdefault("генерация_изображения", NOTE_POSTER)
    есть = set(шаги)
    сделано = {
        "video": видео,
        "image": bool(есть & IMAGE_MAKERS) or "photo" in входы,
        "speech": bool(есть & (SPEECH_MAKERS | SPEECH_TAKERS)) or spec.audio == "native" or "audio" in входы or своя_речь,
        "music": "музыка" in есть or "audio" in входы,
        "sfx": "звук_фон" in есть or V2A_STEP in есть or spec.audio == "native",
    }
    не_сделано = [в for в in spec.outputs if not сделано.get(в, True)]
    if не_сделано:
        return Маршрут(нехватка=_выход_без_шага(не_сделано))
    if шаги == list(м.шаги) and сборка == list(м.сборка):
        return м
    return replace(
        м, шаги=tuple(dict.fromkeys(шаги)), пометки=пометки, сборка=tuple(dict.fromkeys(сборка)), штук=штук
    )


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
    return _все_выходы(spec, _цепочка(spec, сборочные))


def _цепочка(spec: Spec, сборочные: frozenset[str]) -> Маршрут:
    """Главная работа и работы цепочки (`then_tasks`), без состава выходов."""
    главный = _маршрут_одной(spec, сборочные)
    if главный.нехватка is not None or not spec.then_tasks:
        return главный
    шаги = list(главный.шаги)
    пометки = dict(главный.пометки)
    сборка = list(главный.сборка)
    правки = главный.правки
    штук = dict(главный.штук)
    # Цепочка над СНИМКАМИ (одиннадцатый круг): «реставрация -> раскраска»
    # 12 фото отдавала раскраске видео — выход работы считался видео всегда,
    # кроме генерации. Снимки на входе и снимки на выходе — звено над снимком.
    над_снимком = "video" not in spec.outputs and "photo" in spec.inputs and "video" not in spec.inputs
    выход = (
        "video"
        if "video" in spec.outputs or (spec.task not in (None, "generate") and not над_снимком)
        else "photo"
    )
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


#: Во сколько раз выход должен быть длиннее принесённого видео, чтобы правка
#: без названия читалась продлением. КОНСТАНТА-РЕШЕНИЕ, ВЫБРАНО 1.2: округление
#: длины («5 s» ролика в 5.4 с) продлением не считается, 6 с из 5 — считается.
EXTEND_RATIO = 1.2


def продление_по_длине(spec: Spec) -> bool:
    """Заказанный выход заметно длиннее принесённого видео: правка — продление."""
    видео = [
        float(з["duration_s"])
        for з in spec.input_items
        if з.get("kind") == "video" and з.get("duration_s")
    ]
    return bool(видео and spec.duration_s and spec.duration_s >= max(видео) * EXTEND_RATIO)


def _правка_своего(spec: Spec, на_сборке: frozenset[str]) -> Маршрут:
    """Правка ВИДЕО заказчика: модель — на правки, которые делает реестр; монтаж — на прочие."""
    выходы = set(spec.outputs)
    if not spec.edit and продление_по_длине(spec):
        # ДЛИНА ВЫХОДА БОЛЬШЕ ПРИНЕСЁННОГО — ЭТО ПРОДЛЕНИЕ (девятый круг, e02):
        # правка не названа, а заказано 10 с из 5 с. Правка по инструкции длины
        # не меняет; продление называют эндпоинты `…/extend`.
        return Маршрут(
            ("правка_видео", *_подложка(выходы)),
            {"правка_видео": NOTE_VIDEO_EDIT},
            правки=(ep.EDIT_EXTEND,),
        )
    монтаж = tuple(
        п for п in spec.edit if п in ASSEMBLY_ONLY_EDITS or (п in на_сборке and п in ASSEMBLY_EDITS)
    )
    модельные = tuple(п for п in spec.edit if п not in монтаж)
    сборка = tuple(ASSEMBLY_ONLY_EDITS.get(п) or ASSEMBLY_EDITS[п] for п in монтаж)
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

    if звук_к_своему_видео(spec):
        # ТРИНАДЦАТЫЙ КРУГ: заказан звук к ВАШЕМУ видео (работа не названа,
        # «generate» или правка без названной правки) — шаг правки ролика не
        # нужен: звук делается по картинке и кладётся при сборке.
        return Маршрут(_подложка(выходы), {})
    if задача in ROUTE_TASKS:
        for вход, шаг in ROUTE_TASKS[задача]:
            if вход in входы:
                if задача == "captions" and "script" in входы:
                    # ТРИНАДЦАТЫЙ КРУГ: субтитры ПРИЛОЖЕНЫ (SRT) — расшифровывать нечего.
                    return Маршрут((), {}, сборка=(NOTE_BURN_CAPTIONS,))
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
    if задача == "music-visualiser" and "photo" not in входы and (spec.characters or 0) >= 1:
        # ТРИНАДЦАТЫЙ КРУГ: клип со сценами и исполнителем — не петли визуала, а
        # референс исполнителя один раз и сцены по нему (дальше — как generate).
        задача = "generate"
    if задача == "music-visualiser":
        # Принесённый кадр оживляется, иначе картинка генерируется с нуля;
        # музыки не генерирует никто — трек заказчика.
        шаг = "оживление" if "photo" in входы else "генерация_видео"
        if "audio" not in входы:
            # ДВЕНАДЦАТЫЙ КРУГ: визуализатор без приложенного трека спрашивал
            # трек — а картинка от трека не зависит: петли делаются без него,
            # дорожку кладёт монтаж. Музыка заказана выходом — её делает шаг.
            return Маршрут(
                (шаг, *(("музыка",) if "music" in выходы else ())),
                {шаг: NOTE_VISUALISER_NO_TRACK},
                сборка=(NOTE_VISUALISER_NO_TRACK,),
            )
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
            # ЧЕТЫРНАДЦАТЫЙ КРУГ: референс — на ПЕРСОНАЖА, а не на шот (прежде
            # 60 шотов серии генерировали 60 картинок, которые r2v не берёт).
            _дорожки(spec, шаги)
            return Маршрут(
                tuple(dict.fromkeys(шаги)), пометки, штук={"генерация_изображения": max(1, int(spec.characters or 1))}
            )
        _дорожки(spec, шаги)
        return Маршрут(tuple(dict.fromkeys(шаги)), пометки)
    if задача == "face-replace":
        if "photo" in входы and "video" not in выходы and ("video" not in входы or "image" in выходы):
            # ЗАМЕНА ЛИЦА НА СНИМКЕ (одиннадцатый круг): «моё лицо на рыцаря с
            # этой картинки» спрашивало видео. Снимок-цель и новое лицо —
            # снимки заказчика; делает картиночный face-swap реестра.
            # ЧЕТЫРНАДЦАТЫЙ КРУГ: выход — КАРТИНКИ (датасет из кадров), а видео
            # принесено как источник кадров — это тоже картиночный face-swap:
            # кадры вынимает монтаж (ffmpeg), меняется лицо на каждом снимке,
            # цена — за снимок × число. Раньше шаг уходил в видео-замену
            # персонажа без цены.
            штук = face_swap_items(spec)
            return Маршрут(
                ("замена_лица_изображения",),
                {},
                сборка=(NOTE_FRAMES_FROM_VIDEO,) if "video" in входы else (),
                штук={"замена_лица_изображения": штук} if штук else {},
            )
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
        if "video" in входы and "photo" in входы:
            # ПЕРЕНОС ДВИЖЕНИЯ (одиннадцатый круг): снимок и ВЕДУЩЕЕ видео —
            # персонаж со снимка повторяет движение из видео. Простой
            # image-to-video ведущего видео не берёт.
            return Маршрут(("перенос_движения", *_подложка(выходы)), {"перенос_движения": NOTE_MOTION})
        шаги.append("оживление")
    elif задача == "lipsync":
        if "video" in входы:
            return Маршрут(("липсинк",), {})
        # ДВЕНАДЦАТЫЙ КРУГ: ни снимка, ни видео — говорящего делает план (кадр
        # персонажа -> говорящий аватар, как у задачи avatar), а не вопрос
        # «что сделать»: ответ на него плана не меняет.
        return Маршрут(("говорящий_аватар",), {})
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
        elif (spec.characters or 0) >= MULTI_CHARACTER_MIN and серия_с_персонажем(spec):
            # ТРИНАДЦАТЫЙ КРУГ: ОБЩИЕ АКТИВЫ. Референсы персонажей — по одному на
            # персонажа, ОДИН раз на всю серию; ключевой кадр шота — правка по ним;
            # шот оживляется от своего кадра. Прежде каждый шот генерировал своих
            # персонажей заново (t2i на каждый шот) — и платил за это N раз.
            # ЧЕТЫРНАДЦАТЫЙ КРУГ: ключевой кадр шота — только когда персонажи ДЕЛЯТ
            # кадр (композиции нет ни в одном референсе, а image-to-video берёт один
            # стартовый кадр); иначе шот оживляется прямо от референса.
            if spec.cast_together:
                шаги += ["генерация_изображения", "редактирование_изображения", "оживление"]
                пометки["редактирование_изображения"] = NOTE_CAST_KEYFRAMES
            else:
                шаги += ["генерация_изображения", "оживление"]
                пометки["оживление"] = NOTE_CAST_STRAIGHT
            пометки["генерация_изображения"] = NOTE_CAST_REFS.format(n=spec.characters)
            _дорожки(spec, шаги)
            return Маршрут(
                tuple(dict.fromkeys(шаги)), пометки, штук={"генерация_изображения": int(spec.characters or 0)}
            )
        elif (spec.characters or 0) >= MULTI_CHARACTER_MIN:
            шаги += ["генерация_изображения", "оживление"]
            пометки["генерация_изображения"] = NOTE_KEYFRAMES.format(n=spec.characters)
        elif серия_с_персонажем(spec):
            # ОДИН ПЕРСОНАЖ В НЕСКОЛЬКИХ ШОТАХ (девятый круг): «та же женщина в
            # двух шотах» шла двумя независимыми t2v — и лицо в них было разным.
            # Референс персонажа делается один раз, шоты оживляются от него.
            шаги += ["генерация_изображения", "оживление"]
            пометки["генерация_изображения"] = NOTE_R2V_REF
            # ЧЕТЫРНАДЦАТЫЙ КРУГ: референс ОДИН и тогда, когда шоты не названы, а
            # выведены из длительности (прежде — картинка на каждый клип).
            _дорожки(spec, шаги)
            return Маршрут(tuple(dict.fromkeys(шаги)), пометки, штук={"генерация_изображения": SINGLE_REFERENCE})
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


#: Самый длинный СГЕНЕРИРОВАННЫЙ говорящий клип, который делается одним дублем
#: видеомодели с нативным звуком (одиннадцатый круг). Видеомодели со звуком
#: (Veo 3.x, Kling 3.0, Seedance 2.x) отдают 8-15 с за прогон; длиннее — это
#: уже монтаж из шотов, и голос ведёт озвучка. КОНСТАНТА-РЕШЕНИЕ.
NATIVE_SPEECH_MAX_S = 15.0


#: Говорят В КАДРЕ: глагол речи у персонажа («повар говорит», «a chef saying»).
#: «Озвучка», «voiceover», «закадровый» — голос ЗА кадром, их здесь нет нарочно.
SPEAKING_IN_FRAME = re.compile(
    r"\b(?:say|says|saying|speak|speaks|speaking|talk|talks|talking|tells?|telling|greets?|greeting"
    r"|shouts?|shouting|whispers?|whispering|asks?|asking|delivers? (?:a |the |one |his |her )?(?:line|speech|monologue)"
    r"|lip[- ]?synced|dialogue)\b"
    r"|говор(?:ит|ят|ящ\w*)|произнос\w*|скаж\w*|рассказыва\w*|обраща\w*|приветству\w*|крич\w*|шепч\w*",
    re.I,
)
#: Тринадцатый круг: ДИАЛОГ персонажей словами — говорят они, и в кадре.
DIALOGUE = re.compile(
    r"\bdialog\w*|\bconversation\w*|(?:talk|chat|argue|speak)\w* (?:to|with) each other|\bbanter\w*|\bargu(?:e|es|ing)\b"
    r"|\bdebate\w*|разговарива\w*|бесед\w*|диалог\w*|спор(?:ят|ит|ят|ящ\w*)\b|болта\w*|переговарива\w*",
    re.I,
)
#: Тринадцатый круг: исполнитель ПОЁТ в кадре (клип на трек заказчика).
SINGING = re.compile(
    r"\bsing(?:s|ing)?\b|\blip[- ]?sync\w*|\bmouth\w* the (?:words|lyrics)|\bperform\w* (?:the |our |my )?(?:song|track)"
    r"|\brapp(?:ing|s)\b|по[её]т\b|поют\b|пою\w*|спо[её]т|исполня\w* (?:песн|трек)|чита\w* рэп|открыва\w* рот",
    re.I,
)
#: Исполнитель клипа словами: тот, кто держит клип от сцены к сцене.
PERFORMER = re.compile(
    r"\bsinger\b|\bperformer\b|\bvocalist\b|\brapper\b|\bartist\b|\bband\b|\bfrontman\b|\bfrontwoman\b"
    r"|певиц\w*|певец\w*|певц\w*|исполнител\w*|вокалист\w*|рэпер\w*|артист\w*|групп[аы]\b",
    re.I,
)
#: Голос ЗА кадром назван словами — говорящего в кадре нет.
VOICE_OFF_FRAME = re.compile(r"voice-?over|narrat\w*|off-?screen|озвучк\w*|закадров\w*|диктор\w*|配音", re.I)
#: Четырнадцатый круг: голоса ПЕРСОНАЖЕЙ («озвучка персонажей», «voiced lines») —
#: это не закадр: говорят персонажи, и в кадре. Старше `VOICE_OFF_FRAME`.
CHARACTER_VOICES = re.compile(
    r"voiced (?:lines?|dialogue|characters?|cutscenes?)|character (?:voices?|lines?|dialogue)|voice[- ]acted|voice acting"
    r"|(?:his|her|their|its) lines\b|speak\w* (?:\w+ ){0,2}lines|(?:says|say|delivers?|reads?) (?:his|her|their|its) lines"
    r"|озвучк\w* (?:персонаж\w*|геро\w*|рол\w*)|голос\w* персонаж\w*|реплик\w*",
    re.I,
)
#: Четырнадцатый круг: КАТ-СЦЕНА — персонажи игры на экране; речь в ней — их речь.
CUTSCENE = re.compile(r"\bcut-?scenes?\b|in-game cinematic\w*|кат-?сцен\w*|катсцен\w*|игров\w+ ролик\w*", re.I)
#: Двенадцатый круг: говорящий ВИДЕН словами — ведущий, «в камеру», «в кадре».
#: Старше `VOICE_OFF_FRAME`: «ведущий в кадре, озвучка нейросетью» — губы
#: двигаются. Глагол речи (`SPEAKING_IN_FRAME`) без этих слов считается только
#: при персонаже (`characters`/`people`) — «ролик, который рассказывает о
#: приложении», говорящего не показывает.
ON_SCREEN_SPEAKER = re.compile(
    r"\bpresenter|\bhost(?:s|ed)?\b|\banchor(?:man|woman|s)?\b|\bspokes(?:person|man|woman)"
    r"|(?:to|into|at|on)[- ](?:the )?camera|\bin (?:the )?frame|\bon[- ]screen (?:host|presenter|speaker|character)"
    r"|talking (?:character|head|mascot|cartoon)|gives? (?:a |the |his |her |their )?(?:speech|monologue|rant|address)"
    r"|ведущ\w*|в кадре|в камеру|на камеру|говорящ\w* (?:персонаж|геро|кот|пёс|пес|робот|маскот)",
    re.I,
)


#: Пятнадцатый круг: работы, у которых губы ГЕНЕРИРУЕМОГО клипа решает `spec.lipsync`
#: (у дубляжа и липсинка своего видео поле значит своё — `lipsync_default`).
GENERATED_LIPS_TASKS: tuple[str | None, ...] = (None, "generate", "animate", "r2v", "music-visualiser")


def говорящий_по_spec(spec: Spec) -> bool | None:
    """Виден ли говорящий (поющий) в кадре — ПО ПОЛЯМ (пятнадцатый круг); None — поля молчат.

    Порядок: `spec.lipsync` на генерируемом клипе (true — губы двигаются, false —
    липсинка нет вовсе), затем `people[].on_screen` и `people[].speaks`: хоть один
    виден и говорит — да; каждый описанный либо не виден, либо молчит — нет.
    Слова брифа (`ON_SCREEN_SPEAKER`, `SINGING`…) читаются, только когда здесь None:
    решение не зависит от языка брифа, если вызывающий назвал поле.
    """
    if spec.lipsync is not None and spec.task in GENERATED_LIPS_TASKS:
        return spec.lipsync
    описаны = [п for п in spec.people if п.get("on_screen") is not None or п.get("speaks") is not None]
    if not описаны:
        return None
    if any(п.get("on_screen") is True and п.get("speaks") is True for п in описаны):
        return True
    if all(п.get("on_screen") is False or п.get("speaks") is False for п in описаны):
        return False
    return None


def исполнитель_в_кадре_по_spec(spec: Spec) -> bool | None:
    """Есть ли в кадре исполнитель — по `people[].on_screen` (пятнадцатый круг); None — не сказано."""
    видны = [п.get("on_screen") for п in spec.people if п.get("on_screen") is not None]
    if not видны:
        return None
    return any(видны)


def говорят_в_кадре(spec: Spec, текст: str = "") -> bool:
    """Говорящий виден в кадре генерируемого ролика (двенадцатый круг): к речи нужен липсинк."""
    выходы = set(spec.outputs)
    if not {"video", "speech"} <= выходы or spec.task not in (None, "generate", "animate", "r2v"):
        return False
    решено = говорящий_по_spec(spec)
    if решено is not None:
        return решено
    сказано = " ".join(str(у) for у in (*spec.conditions, текст) if у)
    if ON_SCREEN_SPEAKER.search(сказано):
        return True
    персонаж = (spec.characters or 0) >= 1 or bool(spec.people)
    голоса_персонажей = bool(CHARACTER_VOICES.search(сказано))
    if VOICE_OFF_FRAME.search(сказано) and not голоса_персонажей:
        return False
    # ЧЕТЫРНАДЦАТЫЙ КРУГ: реплики персонажей и речь кат-сцены — тоже в кадре.
    if персонаж and (голоса_персонажей or CUTSCENE.search(сказано)):
        return True
    # ТРИНАДЦАТЫЙ КРУГ: диалог персонажей («кот и пёс разговаривают») — говорят в кадре.
    return персонаж and bool(SPEAKING_IN_FRAME.search(сказано) or DIALOGUE.search(сказано))


#: Четырнадцатый круг: исполнителя В КАДРЕ НЕТ словами — «no performer on screen»,
#: «без людей», «исполнителей в кадре нет», «nobody sings».
NO_PERFORMER = re.compile(
    r"\b(?:no|without|zero)\s+(?:\w+\s+){0,2}(?:performers?|singers?|vocalists?|rappers?|artists?|bands?|musicians?"
    r"|people|persons?|humans?|faces?|figures?|characters?|one)\b(?:\s+(?:on|in)\s+(?:the\s+)?(?:screen|camera|frame|shot))?"
    r"|\b(?:nobody|no one|no-one)\b[^.,;]{0,40}"
    r"|\b(?:performers?|singers?|bands?|artists?|people)\s+(?:is|are)?\s*(?:not|never)\s+(?:shown|seen|visible|on screen|in frame)"
    r"|\bfaceless\b|\bpurely abstract\b"
    r"|без\s+(?:\w+\s+)?(?:людей|человек\w*|исполнител\w*|артист\w*|певц\w*|певиц\w*|вокалист\w*|музыкант\w*|лиц\b|персонаж\w*)"
    r"|(?:исполнител\w*|артист\w*|певц\w*|певиц\w*|людей|музыкант\w*|персонаж\w*)\s+(?:\w+\s+){0,2}нет\b"
    r"|\bнет\s+(?:\w+\s+)?(?:людей|исполнител\w*|артист\w*)|никого\s+в\s+кадре|никто\s+не\s+\w+",
    re.I,
)
#: Исполнитель назван ЧЕЙ-ТО трек, а не тем, кто в кадре: «the band's new song»,
#: «artist's logo», «for our rapper», «песня нашей группы», «для певицы».
PERFORMER_NOT_ON_SCREEN = re.compile(
    r"\b(?:performer|singer|vocalist|rapper|artist|band|frontman|frontwoman|musician)(?:'s|’s|s'|s’)"
    r"|\bfor (?:the |our |my |a |an |their )?(?:new )?(?:band|artist|singer|rapper|musician)s?\b"
    r"|(?:песн\w*|трек\w*|клип\w*|альбом\w*|сингл\w*|логотип\w*)\s+(?:нашей |моей |этой |вашей |своей |нашего |моего )?"
    r"(?:групп\w*|певиц\w*|певц\w*|артист\w*|исполнител\w*|рэпер\w*)"
    r"|для\s+(?:нашей |моей |нашего |моего )?(?:групп\w*|певиц\w*|певц\w*|артист\w*|исполнител\w*|рэпер\w*)",
    re.I,
)


#: Пятнадцатый круг: липсинк назван, чтобы его НЕ было («no lip sync», «sin lip
#: sync», «без липсинка») — запасной путь словами, когда `spec.lipsync` не назван.
NO_LIPSYNC = re.compile(
    r"\b(?:no|without|not|never|zero|sin|sans|ohne|kein\w*|sem|senza|nada de|pas de|без|не|нет|никак\w*)"
    r"\s+(?:\w+\s+){0,2}?(?:lip[- ]?sync\w*|lipsync\w*|липсинк\w*|синхрон\w* губ)"
    r"|(?:lip[- ]?sync\w*|липсинк\w*)\s+(?:is\s+)?(?:not (?:needed|required|wanted)|не нуж\w*)",
    re.I,
)


def исполнитель_словами(текст: str) -> str:
    """Слова брифа без исполнителя, которого в кадре НЕТ (четырнадцатый круг).

    «Визуализатор без исполнителя в кадре», «логотип артиста», «трек нашей группы»
    называют исполнителя, но не ставят его в кадр: клип с референсом и губами —
    только когда исполнитель В КАДРЕ.
    """
    текст = NO_LIPSYNC.sub(" ", str(текст or ""))
    return PERFORMER_NOT_ON_SCREEN.sub(" ", NO_PERFORMER.sub(" ", str(текст or "")))


def поют_в_кадре(spec: Spec, текст: str = "") -> bool:
    """Исполнитель поёт ВАШ трек в кадре генерируемого клипа (тринадцатый круг): к треку нужен липсинк."""
    if "video" not in spec.outputs or "audio" not in spec.inputs or set(spec.inputs) & {"video", "photo"}:
        return False
    if spec.task not in (None, "generate", "music-visualiser", "r2v"):
        return False
    решено = говорящий_по_spec(spec)
    if решено is not None:
        return решено
    сказано = исполнитель_словами(" ".join(str(у) for у in (*spec.conditions, текст) if у))
    return bool(SINGING.search(сказано))


def клип_с_исполнителем(spec: Spec, текст: str = "") -> bool:
    """Клип на ВАШ трек из нескольких сцен с одним исполнителем (тринадцатый круг)."""
    if "video" not in spec.outputs or "audio" not in spec.inputs or set(spec.inputs) & {"video", "photo"}:
        return False
    if spec.task not in (None, "generate", "music-visualiser"):
        return False
    сцен = (spec.shots or 0) >= SERIES_SHOTS_MIN or float(spec.duration_s or 0) > SERIES_DURATION_MIN_S
    # ПЯТНАДЦАТЫЙ КРУГ: исполнитель в кадре по полям (`people[].on_screen`, губы
    # `spec.lipsync`) — старше слов «singer», «performs» на любом языке.
    в_кадре = исполнитель_в_кадре_по_spec(spec)
    if в_кадре is not None:
        return сцен and в_кадре
    if spec.task in GENERATED_LIPS_TASKS and spec.lipsync is True:
        return сцен
    сказано = исполнитель_словами(" ".join(str(у) for у in (*spec.conditions, текст) if у))
    if spec.task in GENERATED_LIPS_TASKS and spec.lipsync is False:
        # Губ нет — «поёт» словами исполнителя в кадр не ставит; исполнитель назван — ставит.
        return сцен and bool(PERFORMER.search(сказано))
    return сцен and bool(PERFORMER.search(сказано) or SINGING.search(сказано))


#: Четырнадцатый круг: ВИЗУАЛИЗАТОР словами — картинка под трек без исполнителя.
VISUALISER_WORDS = re.compile(
    r"visuali[sz]er|визуализ\w*|audio[- ]reactive|sound[- ]reactive|reacts? to the (?:beat|music|track)"
    r"|reactive (?:shapes|visuals)|pulsing to the beat|пульсиру\w* под|реагиру\w* на (?:бит|звук|музык)",
    re.I,
)


def визуализатор(spec: Spec, текст: str = "") -> bool:
    """Картинка под ВАШ трек без исполнителя в кадре: работа визуализатора, даже названная generate."""
    if spec.task not in (None, "generate") or "audio" not in spec.inputs or set(spec.inputs) & {"video", "photo"}:
        return False
    # Пятнадцатый круг: человек, о котором сказано `on_screen: false`, в кадр не
    # выходит — визуализатору он не помеха (артист назван ради трека, не ради кадра).
    if set(spec.outputs) != {"video"} or (spec.characters or 0) >= 1:
        return False
    if any(п.get("on_screen") is not False for п in spec.people):
        return False
    сказано = " ".join(str(у) for у in (*spec.conditions, текст) if у)
    return bool(VISUALISER_WORDS.search(сказано)) and not клип_с_исполнителем(spec, текст)


#: Четырнадцатый круг: персонажи ДЕЛЯТ кадр словами — вместе, друг с другом, оба,
#: в каждом шоте (и диалог, `DIALOGUE`).
CAST_TOGETHER = re.compile(
    r"\btogether\b|each other|one another|\bboth\b|\ball (?:two|three|four|of them)\b|in (?:every|each) (?:of (?:the )?\d+ )?(?:shots?|scenes?|frames?)"
    r"|\b(?:meet|meets|fight|fights|hug|hugs|chase|chases|dance with|play with|plays with|duel\w*)\b"
    r"|\band (?:the |a |an |his |her |their |our |its )?[\w-]+ (?:talk|chat|speak|argue|bicker|negotiate|discuss|sing)\b"
    r"|вместе|друг (?:с )?друг\w*|\bоба\b|\bобе\b|\bвсе (?:трое|четверо)|в каждом (?:из \d+ )?(?:шот\w*|кадр\w*|сцен\w*)"
    r"|встреча\w*|деру\w*|сража\w*|обнима\w*|догоня\w*|танцу\w* с",
    re.I,
)


#: «Без диалогов», «no dialogue» — диалог назван, чтобы его НЕ было.
NO_DIALOGUE = re.compile(
    r"\b(?:no|without|zero|not any)\s+(?:\w+\s+)?(?:dialog\w*|conversation\w*|talking|lines)\b"
    r"|\bnon-?dialog\w*|без\s+(?:\w+\s+)?(?:диалог\w*|разговор\w*|реплик\w*|слов)",
    re.I,
)


def персонажи_в_одном_кадре(spec: "Spec", текст: str = "") -> bool:
    """Персонажи серии делят кадр: ключевой кадр шота собирается из их референсов (четырнадцатый круг)."""
    if spec.cast_together is not None:
        # ПЯТНАДЦАТЫЙ КРУГ: поле `spec.cast_together` старше слов «together», «dialogue».
        return spec.cast_together
    if (spec.characters or 0) < MULTI_CHARACTER_MIN:
        return False
    сказано = NO_DIALOGUE.sub(" ", " ".join(str(у) for у in (*spec.conditions, текст) if у))
    return bool(CAST_TOGETHER.search(сказано) or DIALOGUE.search(сказано))


#: «Тот же персонаж» словами — серия держит одного героя (одиннадцатый круг).
RECURRING_CHARACTER = re.compile(
    r"\bsame (?:\w+ ){0,3}(?:character|mascot|hero|heroine|girl|boy|cat|dog|fox|dragon|robot|person|woman|man|kid)"
    r"|\bconsistent (?:\w+ )?(?:character|mascot|hero)|recurring (?:character|mascot|hero)"
    r"|\bour (?:\w+ ){0,2}mascot|\b(?:main|title) character|on every page|in every (?:scene|picture|image)"
    r"|(?:один|одн\w*) и т(?:от|ого|ем|ой|у) же|тот же (?:персонаж|герой)|одинаков\w*|фирменн\w* персонаж"
    r"|главн\w* геро\w*",
    re.I,
)
#: Сериал словами: эпизоды держат героев от серии к серии.
SERIES_WORDS = re.compile(r"\bseries\b|\bepisodes?\b|\bshow\b|сериал\w*|\bсери[яиюей]\b|эпизод\w*", re.I)
#: …и у сериала есть ГЕРОЙ: «про лисёнка», «about a little robot», «главный герой».
#: Без героя «заставка веб-сериала из 6 планов» — разные сцены, не один персонаж.
SERIES_HERO = re.compile(r"\babout (?:a|an|the|our|two|three) |character|\bhero|\bпро |персонаж|геро", re.I)


def персонажи_по_умолчанию(spec: Spec, текст: str = "") -> tuple[int, str]:
    """Сколько повторяющихся персонажей, когда `characters` не назван (одиннадцатый круг).

    «20 картинок с нашим котом-маскотом, везде один и тот же» без поля
    `characters` шло двадцатью независимыми генерациями — и кот каждый раз
    другой; «мультсериал про робота, серия 3 минуты» шёл одним t2v без
    референса героя. Источники по старшинству: вымышленные персонажи в
    `spec.people` (`real: false`); «тот же персонаж» или «сериал» словами.
    Ничего не сгенерировано с нуля (принесён снимок или видео) — не трогается.
    """
    if spec.characters is not None or set(spec.inputs) & {"photo", "video"}:
        return 0, ""
    if клип_с_исполнителем(spec, текст):
        # ТРИНАДЦАТЫЙ КРУГ: клип со сценами и одним исполнителем — референс исполнителя.
        return 1, (
            "a music video of scenes with one performer — characters=1 assumed: the performer's reference is "
            "made once and every scene is built from it; name spec.characters yourself to override"
        )
    if spec.task not in (None, "generate"):
        return 0, ""
    выходы = set(spec.outputs)
    картинки = "image" in выходы and "video" not in выходы and (spec.shots or 0) >= SERIES_IMAGES_MIN
    ролик = "video" in выходы and (
        (spec.shots or 0) >= SERIES_SHOTS_MIN or float(spec.duration_s or 0) > SERIES_DURATION_MIN_S
    )
    if not (картинки or ролик):
        return 0, ""
    вымышленные = [п for п in spec.people if п.get("real") is False]
    сказано = [str(у) for у in (*spec.conditions, текст) if у]
    if вымышленные:
        n = len(вымышленные)
    elif "consistency" in spec.source:
        # ПЯТНАДЦАТЫЙ КРУГ: `spec.consistency` названо — один повторяющийся персонаж,
        # только если в нём есть `character`; слова «same character» тогда не читаются.
        if "character" not in spec.consistency:
            return 0, ""
        n = 1
    elif any(RECURRING_CHARACTER.search(у) for у in сказано) or (
        ролик and any(SERIES_WORDS.search(у) and SERIES_HERO.search(у) for у in сказано)
    ):
        n = 1
    else:
        return 0, ""
    return n, (
        f"a recurring character across the {'pictures' if картинки else 'shots'} — characters={n} assumed: one "
        "reference of the character first, everything else built from it; name spec.characters yourself to "
        "override"
    )


def говорящий_ролик(spec: Spec, текст: str = "") -> bool:
    """Короткий генерируемый клип, где говорят в кадре: звук делает сама видеомодель.

    «Сгенерируй 8 секунд: повар говорит „добро пожаловать“» шло озвучкой +
    text-to-video — голос поверх немого кадра, губы не двигаются. Ничего не
    принесено, речь на одном языке, клип в один дубль — это видео с нативным
    звуком. Звук назван (`audio`) — решает он.
    """
    if spec.audio is not None or spec.task not in (None, "generate"):
        return False
    решено = говорящий_по_spec(spec)
    if решено is False:
        return False
    if решено is None:
        if not SPEAKING_IN_FRAME.search(текст or "") or VOICE_OFF_FRAME.search(текст or ""):
            return False
    выходы = set(spec.outputs)
    # Речь названа выходом — или языком речи при видео без других выходов
    # («8 секунд: повар говорит „добро пожаловать“», languages=["en"]).
    if "video" not in выходы or not ("speech" in выходы or (выходы == {"video"} and spec.languages)):
        return False
    if set(spec.inputs) & {"photo", "video", "audio"}:
        return False
    if len(spec.language_tags or spec.languages) > 1 or (spec.characters or 0) > 1:
        return False
    длина = spec.per_shot_s if spec.shots and spec.per_shot_s else spec.duration_s
    return длина is not None and 0 < float(длина) <= NATIVE_SPEECH_MAX_S and (spec.shots or 1) == 1


def with_defaults(spec: Spec, ролик: bool, текст: str = "") -> Spec:
    """Допущения, сделанные за заказчика, — НАЗВАННЫЕ: разрешение видео, голос поверх картинки.

    :param текст: слова брифа — читаются ТОЛЬКО для того, говорят ли в кадре
        (`говорящий_ролик`): у spec нет поля «кто говорит — голос за кадром или
        персонаж в кадре», а «15-секундная реклама с озвучкой» и «повар говорит
        в камеру» дают одну и ту же spec.
    """
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
    if (
        not spec.duration_s
        and not (spec.shots and spec.per_shot_s)
        and input_seconds(spec) is None
        and озвучка_по_тексту(spec)
    ):
        поля["duration_s"] = SCRIPT_SPEECH_DEFAULT_S
        источник["duration_s"] = SOURCE_DEFAULT
        допущения.append(
            f"the length of the speech is set by YOUR script and was not named — priced for "
            f"{SCRIPT_SPEECH_DEFAULT_S:g} s of speech (scale by the script's length: ~150 words a minute); "
            "pass spec.duration_s for an exact price"
        )
    if визуализатор(spec, текст):
        # ЧЕТЫРНАДЦАТЫЙ КРУГ: визуализатор под ВАШ трек, названный generate, —
        # петли визуала и монтаж, а не кадры-портреты на каждую сцену.
        поля["task"] = "music-visualiser"
        источник["task"] = SOURCE_DERIVED
        spec = replace(spec, task="music-visualiser")
        допущения.append(
            "visuals for YOUR track with nobody on screen — a music visualiser: looped generation laid under the "
            "track at assembly, no performer reference and no lip sync; pass spec.characters for a performer"
        )
    персонажей, почему = персонажи_по_умолчанию(spec, текст)
    if персонажей:
        поля["characters"] = персонажей
        источник["characters"] = SOURCE_DEFAULT
        допущения.append(почему)
    if персонажи_в_одном_кадре(replace(spec, characters=поля["characters"]), текст):
        поля["cast_together"] = True
    if говорящий_ролик(spec, текст):
        поля["audio"] = "native"
        источник["audio"] = SOURCE_DEFAULT
        допущения.append(
            "a short generated clip where someone speaks: the video model makes the voice and the lips together "
            "(native audio) — no separate voiceover or lip sync; pass spec.audio='voiceover' for an off-screen voice"
        )
    elif поют_в_кадре(replace(spec, characters=поля["characters"]), текст):
        # ТРИНАДЦАТЫЙ КРУГ: исполнитель поёт в кадре — губы под вокал трека.
        поля["speaker_on_screen"] = True
        допущения.append(
            "the performer sings on camera: a lip-sync step moves the lips to YOUR track in every scene — "
            "pass spec.conditions=['no lip sync'] for a performance without visible singing"
        )
    elif говорят_в_кадре(spec, текст):
        # ДВЕНАДЦАТЫЙ КРУГ: ведущий или персонаж говорит в кадре, а клип длиннее
        # одного дубля со звуком — речь синтезируется, губы двигает липсинк
        # (`_все_выходы`). Прежде шла одна озвучка поверх немого кадра.
        поля["speaker_on_screen"] = True
        if spec.audio is None:
            поля["audio"] = "voiceover"
            источник["audio"] = SOURCE_DEFAULT
        допущения.append(
            "the speaker is seen on screen: the voice is synthesised and a lip-sync step moves the lips to it — "
            "pass spec.audio='native' for a short single-take clip with the voice made by the video model"
        )
    elif "speech" in spec.outputs and "video" in spec.outputs and spec.audio is None and spec.task in (None, "generate", "animate"):
        поля["audio"] = "voiceover"
        источник["audio"] = SOURCE_DEFAULT
        допущения.append(
            "the voice plays over the picture, nobody on screen moves their lips — "
            "pass spec.task='avatar' (or 'lipsync') for an on-screen speaker, or spec.audio='native'"
        )
    if (
        spec.task is None
        and "video" in spec.inputs
        and set(spec.outputs) <= {"video", "text"}
        and монтажные_правки_словами(текст)
    ):
        # ТРИНАДЦАТЫЙ КРУГ: работа не названа, а бриф называет монтаж над ВАШИМ видео.
        поля["task"] = "video-edit"
        источник["task"] = SOURCE_DERIVED
    правки = правки_монтажа(replace(spec, task=поля["task"]), текст)
    if правки != spec.edit:
        # ТРИНАДЦАТЫЙ КРУГ: монтажная правка словами брифа, рефрейм кадрированием,
        # LUT вместо перерисовки стиля — названо вслух.
        поля["edit"] = правки
        источник["edit"] = SOURCE_DERIVED
        if EDIT_CROP in правки and ep.EDIT_REFRAME in spec.edit:
            допущения.append(
                "reframe to " + str(spec.aspect) + " is an assembly crop with face/subject tracking (the target is "
                "not wider than the source, so the subject stays whole); pass spec.conditions=['outpaint'] if it "
                "would be cut"
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
    if spec.output_items and "outputs" in поля:
        поля["outputs"]["items"] = [dict(з) for з in spec.output_items]
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
        "for video-edit — WHAT is edited: a list of " + " | ".join(EDIT_VALUES)
        + "; stabilise is done at assembly (ffmpeg vidstab / Gyroflow, 0 usd) when no endpoint does it; "
        + ", ".join(ASSEMBLY_ONLY_EDITS)
        + " are always assembly (ffmpeg, 0 usd, no model step); a reframe to an aspect not wider than the source is "
        "a tracked crop"
    ),
    "lipsync": (
        "for dub-translate — move the lips to the new speech: true | false; default true when outputs include "
        "video (or are not named) and audio is not voiceover, else false (voice-over-only dubs get no lip sync); "
        "on a GENERATED clip (generate / animate / r2v / music-visualiser): true = the on-screen speaker's or "
        "singer's lips move to the speech or track, false = no lip-sync step at all"
    ),
    "characters": "how many recurring characters; 1 + shots N over images = one reference and N edits from it",
    "fps": "output frames per second; above the model's recorded rate a frame-interpolation step is added",
    "audio": "none | native | voiceover",
    "audience": (
        " | ".join(AUDIENCES) + " — who WATCHES it (a cartoon series for kids = children); who is ON SCREEN is "
        "spec.people (minor: true for a real person under 18)"
    ),
    "budget": "{amount, currency: ISO 4217}; convert to USD yourself (no FX rates are recorded) and keep the original for echo",
    "conditions": "short phrases the customer actually said, e.g. [\"profile face\", \"hands\"] (ranking only)",
    # Пятнадцатый круг: поля решений — слова брифа читаются, только когда поля нет.
    "live": (
        "true | false — a LIVE / interactive system (a live stream, a video call, an avatar that answers people in "
        "session, live dubbing): true = a recorded gap (a streaming product, not rendered clips); false = an "
        "ordinary plan whatever the words say"
    ),
    "edit_target": (
        " | ".join(EDIT_TARGETS) + " — WHAT the edit changes in the shot: text = lettering on a sign, label or "
        "billboard (a video edit with text rendering, never a character swap); person = a face or a person"
    ),
    "outputs[].loop": "true when the output is a seamless loop (last frame flows into the first): outputs=[{\"kind\": \"video\", \"loop\": true}]",
    "outputs[].tileable": "true when the output is a seamless tileable texture: outputs=[{\"kind\": \"image\", \"tileable\": true}]",
    "outputs[].alpha": (
        "true when the output must have a TRANSPARENT background (alpha channel: PNG, WebM, ProRes 4444); false "
        "for an opaque frame (a hologram / transparent-LED display wants black, not alpha)"
    ),
    "people[].on_screen": "true | false — the person (or character, real=false) is VISIBLE in the frame",
    "people[].speaks": (
        "true | false — the person speaks or sings in the audio; on_screen and speaks both true = a lip-sync step "
        "moves their lips (spec.lipsync=false forbids any lip sync)"
    ),
    "cast_together": (
        "true | false — the recurring characters SHARE the frame (dialogue, together in a shot): true = a keyframe "
        "edit per shot from the shared references; false = each shot animates straight from its character's reference"
    ),
    "single_take_s": "seconds of the longest CONTINUOUS take (no cut inside it) — a take longer than one generation run is made in several joined runs",
    "training_use": "true | false — the outputs will be used to TRAIN or fine-tune a model (a data set, synthetic data): every provider's output terms decide",
    "consistency": (
        "list of " + " | ".join(CONSISTENCY_AXES) + " — what must stay the SAME across shots or pictures (light = "
        "one lighting setup for every shot, character = one recurring character)"
    ),
    "dataset_count": "how many samples the data set made of the outputs holds (e.g. 500 face-swapped images): priced per sample",
    # Шестнадцатый круг: остальные решения, прежде читавшиеся только словами (EN/RU).
    "anonymise": (
        "{faces?: bool, voice?: bool, method?: " + " | ".join(ANONYMISE_METHODS) + "} or false — hide who people "
        "are: faces + swap (default) = a synthetic face and a video face swap (priced), blur / pixelate = at "
        "assembly; voice (or method voice-replace) = transcript + a DIFFERENT stock TTS voice (never a clone, "
        "never dubbing — also for a same-language dub-translate order); false = no anonymisation whatever the words"
    ),
    "voiceover": (
        "true | false — spoken words in the deliverable (narration, voice-over, someone speaking): false = no "
        "speech at all (a music / text-only short)"
    ),
    "delivery.platform": (
        "list of " + " | ".join(DELIVERY_PLATFORMS) + " — where it is delivered: decides the platform caveats "
        "(broadcast loudness and legal range, cinema DCP, podcast / audiobook specs, telephony, social encode)"
    ),
    "delivery.dynamic_range": " | ".join(DYNAMIC_RANGES) + " — hdr = an HDR master (PQ / HLG)",
    "delivery.stems": "true | false — separate dialogue / music / effects stems are delivered (M&E for localisation)",
    "delivery.direction": " | ".join(CALL_DIRECTIONS) + " — for telephony / voice agents: outbound = the AI voice calls people",
    "delivery.format": (
        "list of " + " | ".join(DELIVERY_FORMATS) + " — delivery formats; glb / gltf / usdz / obj / fbx = a 3D "
        "model (mesh reconstruction, not a turntable clip)"
    ),
    "domain": (
        "list of " + " | ".join(DOMAINS) + " — the field of the order: advertising (and its health / financial "
        "kinds), branded-content (a sponsored post), news, real-estate, political … decide the regulation caveats"
    ),
    "style": (
        " | ".join(STYLES) + " — photoreal = looks real (synthetic-people disclosure); stylised = drawn / cartoon / "
        "3D-animated (a photoreal face model is the wrong tool); limited-animation = 2D / anime on twos"
    ),
    "subject": (
        "list of " + " | ".join(SUBJECTS) + " — what in the frame decides the craft: product (packshot fidelity), "
        "reflective / transparent material, logo / text (composited, exact), garment (virtual try-on), interior "
        "(a walkthrough of a place), mascot (a whole-character replacement), before-after"
    ),
    "accessibility": "list of " + " | ".join(ACCESSIBILITY_NEEDS) + " — accessibility deliverables ([] = none)",
    "display": " | ".join(DISPLAYS) + " — additive = a hologram / Pepper's ghost / transparent LED (black is transparent, no alpha)",
    "audio_content": (
        "list of " + " | ".join(AUDIO_CONTENTS) + " — what is HEARD in the result or the brought audio: song = "
        "sung vocals (a vocal stem), no speech = nobody speaks"
    ),
    "follows_picture": "true | false — the ordered sound follows the action of the brought picture (video-to-audio)",
    "animate_input": (
        "true | false — the brought picture itself moves (a visualiser animating the cover art); false = it stays "
        "still under a waveform and captions (an audiogram at assembly)"
    ),
    "community": "true | false — community checkpoints / LoRA / ComfyUI workflows are wanted (Civitai, Hugging Face)",
    "inputs[].source": (
        "list of " + " | ".join(INPUT_SOURCES) + " — what the brought material is: print-scan (a newspaper / "
        "magazine / book scan), archival, cine-film (8 mm / Super 8), timelapse, green-screen, stock, "
        "third-party-song, screen-recording, slides"
    ),
    "inputs[].defects": (
        "list of " + " | ".join(INPUT_DEFECTS) + " — what is wrong with it: halftone = a printed dot screen "
        "(descreen before restore / upscale), noise / hum / echo = an audio clean-up chain, blur = a deblur model"
    ),
    "inputs[].fps": "frames per second of the brought footage (16-18 = cine film: set the true speed first)",
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
    "state — ask them. Also fill the DECISION FIELDS listed in `draft.decision_fields` that apply "
    "(live, edit_target, outputs[].loop / tileable, people[].on_screen / speaks, lipsync, cast_together, "
    "single_take_s, training_use, consistency, dataset_count, anonymise, voiceover, delivery, domain, style, "
    "subject, accessibility, display, audio_content, follows_picture, animate_input, community, "
    "inputs[].source / defects / fps): in a brief in any language they decide what "
    "the keyword parser can only read in English or Russian."
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


#: Длина озвучки, допущенная, когда заказчик принёс ТЕКСТ, а длины не назвал
#: (одиннадцатый круг): длину речи задаёт сам сценарий, спрашивать её — лишний
#: круг. Цена печатается как оценка на минуту речи. КОНСТАНТА-РЕШЕНИЕ.
SCRIPT_SPEECH_DEFAULT_S = 60.0

#: Выходы, при которых длину задаёт принесённый текст: только речь (и текст).
SCRIPT_TIMED_OUTPUTS: frozenset[str] = frozenset({"speech", "text"})


def озвучка_по_тексту(spec: "Spec") -> bool:
    """Озвучка принесённого сценария: длину речи задаёт текст, вопрос о длине не нужен."""
    выходы = set(spec.outputs)
    return bool(выходы) and выходы <= SCRIPT_TIMED_OUTPUTS and "speech" in выходы and "script" in spec.inputs


def gaps(raw: Mapping[str, Any] | None, текст: str = "") -> tuple[Spec, list[str], list[dict[str, str]]]:
    """(spec, ошибки формы, НЕДОСТАЮЩИЕ решающие поля). Пусто в третьем — план строится.

    Решающие поля: работа, входы (с владением), выходы, длительность или число
    шотов, языки — там, где в выходе есть речь или текст. Остальные поля
    (кадр, соотношение, бюджет, люди, условия) уточняют план, но не решают его.
    """
    spec, ошибки = parse_spec(raw)
    if not isinstance(raw, Mapping):
        raw = {}
    нет: list[dict[str, str]] = []
    if spec.task is None and "video" in spec.inputs and монтажные_правки_словами(текст) and set(spec.outputs) <= {"video", "text"}:
        # ТРИНАДЦАТЫЙ КРУГ: работа не названа, а бриф называет монтаж над ВАШИМ видео.
        spec = replace(spec, task="video-edit")
    if монтаж_целиком(spec, текст) and raw.get("inputs") is not None:
        # ТРИНАДЦАТЫЙ КРУГ: работа целиком монтажная — длина и язык цены не решают
        # (0 usd), вопрос о них только задержал бы план.
        return spec, ошибки, []
    работы = (spec.task, *spec.then_tasks) if spec.task else ()
    if not spec.task and not звук_к_своему_видео(spec):
        # Тринадцатый круг: звук к принесённому видео — работа видна по входу и выходу.
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
        if not (spec.duration_s or (spec.shots and spec.per_shot_s) or от_входа or озвучка_по_тексту(spec)):
            нет.append(_пробел("duration_s", "length decides the price and how many runs/shots are needed"))
    elif выходы == {"image"}:
        штук = any(з.get("count") for з in spec.input_items)
        # Работа над ПРИНЕСЁННЫМИ снимками (одиннадцатый круг): сколько картинок
        # — столько, сколько принесено; «одна картинка» без count — не вопрос.
        над_своими = bool(set(работы) & (MATERIAL_TASKS | {"colorize"})) and "photo" in spec.inputs
        if not (spec.shots or штук or над_своими):
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
    (ep.EDIT_EXTEND, r"\bextend\w* (?:the |our |my )?(?:\w+ )?(?:clip|video|shot|footage)|продл\w* (?:ролик|видео|клип)"),
    # Надпись в кадре (тринадцатый круг) — раньше «replace …»: «replace the
    # text on the sign» — правка текста, а не объекта (`studio/edit_intent.py`).
    (ep.EDIT_REPLACE_TEXT, r"(?:replac|chang|swap|edit)\w* (?:the |a )?(?:\w+ )?(?:text|lettering|wording|sign(?:age)?|billboard)\b"
     r"|(?:text|lettering|wording) on (?:the |a )?(?:\w+ )?(?:sign|billboard|banner|storefront|truck|poster)"
     r"|замен\w* (?:\w+ )?(?:текст|надпис)|надпис\w* на (?:\w+ )?(?:вывеск|табличк|баннер|билборд)"),
    (ep.EDIT_REPLACE_OBJECT, r"replace (?:the |a )?(?!sky)\w+|замен\w* (?!неб)"),
    # Свет на объекте и экспозиция — переосвещение; смена времени суток — своя
    # правка (восьмой круг, валидатор v8 n13).
    (ep.EDIT_RELIGHT, r"relight\w*|under-?expos\w*|over-?expos\w*|key light|переосвет\w*|недоэкспон\w*|пересвеч\w*"),
    (ep.EDIT_DAY_TO_NIGHT, r"day[- ]to[- ]night|night[- ]to[- ]day|день в ночь|ночь в день"),
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
        r"|relight\w*|under-?expos\w*|переосвет\w*|day[- ]to[- ]night"
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


# --- доводка черновика (восьмой круг) ----------------------------------------------
#
# ВАЛИДАТОР v8 (103 черновика на брифах круга): пусто у CJK/арабского/хинди/
# тайского/испанского (8), `inputs` почти никогда (план «как есть» строился у
# 14 из 103). Доводка читает то, чего прежний разборщик не видел, — и только
# там, где поле ОТСУТСТВУЕТ или прочитано заведомо не так (`animate` без
# картинки, `interpolate` у «сгенерируй 120fps»). Незнакомое остаётся
# отсутствующим: каждая догадка пишется в `guesses`.

#: Медиа-существительные черновика сверх `VIDEO_NOUN`/`PHOTO_NOUN`/`AUDIO_NOUN`:
#: то, чем заказчик называет СВОЙ материал («documentary», «newsreel», «logo»).
DRAFT_MEDIA_EXTRA: dict[str, str] = {
    "video": r"documentar\w*|movies?|newsreels?|timelapses?|time-lapses?|interviews?|podcasts?|lectures?"
    r"|tiktoks?|talking-heads?|meetings?",
    "photo": r"logos?|drawings?|packshots?|portraits?|illustrations?|renders?",
    "audio": r"songs?|tracks?|voice samples?|samples?",
}
#: Работы над МАТЕРИАЛОМ заказчика: названный материал здесь — его вход, и
#: «свой» по умолчанию (с догадкой в `guesses`), пока нет признака чужого.
OWNED_ON_MENTION_TASKS: frozenset[str] = frozenset(
    {
        "video-edit",
        "restore",
        "colorize",
        "interpolate",
        "upscale",
        "remove-background",
        "transcribe",
        "captions",
        "dub-translate",
        "lipsync",
        "turntable",
        "cut-to-shorts",
        "edit",
    }
)
#: Признак ЧУЖОГО материала: тогда владение не угадывается.
NOT_OWNED_CUE = re.compile(
    r"\bfrom (?:a |the )?(?:movie|film|tv show|series)\b|someone else|stock footage|downloaded|found online"
    r"|not (?:mine|ours)|чуж\w*|скачанн\w*"
)
#: Притяжательное ПОСЛЕ существительного: «photos of our sneakers», «photo of me».
_ЧЬЁ_ПОСЛЕ = r"(?:\s+of\s+(?:our|my|me|us)\b)"
#: Окно притяжательного черновика: «my silent 30 s short film» — пять слов.
DRAFT_POSSESSIVE_WINDOW = 5
#: Материал, ПРИНЕСЁННЫЙ без «моего»: «use her webcam recording», «from his photo».
BROUGHT_CUE = re.compile(
    r"\b(?:use|using|from|based on|with|her|his|their)\b (?:[\w'’-]+ ){0,3}"
    r"(?:videos?|recordings?|footage|clips?|webcam|photos?|pictures?|portraits?|selfies?)\b"
)
#: Музыка БЕЗ картинки: «lo-fi instrumental for streaming».
MUSIC_ONLY = re.compile(r"instrumental|\blo-?fi\b|\bbeat\b|backing track|\bjingle\b")
VISUAL_CUE = re.compile(
    r"\bvideo|\bclip|\bshots?\b|\bscenes?\b|\bcuts?\b|footage|visual|animat\w*|anime|\bstyle\b|opening|видео|ролик|клип"
)
#: Языки жестов словами -> тег (ISO 639-3).
SIGN_TAGS: tuple[tuple[str, str], ...] = (
    (r"\basl\b|american sign", "ase"),
    (r"\bbsl\b|british sign", "bfi"),
)


def _материал_черновика(низ: str) -> dict[str, bool | None]:
    """Виды медиа, НАЗВАННЫЕ в тексте (латиница/кириллица): True — со своим притяжательным."""
    итог: dict[str, bool | None] = {}
    токены = _tokens(низ)
    for i, т in enumerate(токены):
        for вид, образец in (("video", VIDEO_NOUN), ("photo", PHOTO_NOUN), ("audio", AUDIO_NOUN)):
            if not (образец.match(т) or re.fullmatch(DRAFT_MEDIA_EXTRA[вид], т)):
                continue
            if _в_окне(токены, i, NEGATION, 2) >= 0:
                break
            хвост = " ".join(токены[i : i + 4])
            # «of our sneakers» владеет снимком, а не заказанным роликом («spin
            # video of our sneaker»); у видео — только «video of me/us».
            после = _ЧЬЁ_ПОСЛЕ if вид != "video" else r"(?:\s+of\s+(?:me|us)\b)"
            p = _в_окне(токены, i, POSSESSIVE, DRAFT_POSSESSIVE_WINDOW)
            # «photos of our sneakers INTO rotating videos»: между «нашим» и
            # существительным стоит «into» — существительное уже заказ.
            if p >= 0 and any(т_ in ("into", "в", "во") for т_ in токены[p + 1 : i]):
                p = -1
            # В клаузе заказа («make our video») притяжательное — заказ, кроме
            # предлога материала перед ним («from our video»).
            клауза_заказа = bool(MAKE_WORDS.search(" ".join(токены[max(0, i - 6) : i])))
            if (p >= 0 and (not клауза_заказа or (p > 0 and MATERIAL_PREP.match(токены[p - 1])))) or (
                re.match(rf"\S+{после}", хвост) and not клауза_заказа
            ):
                итог[вид] = True
            else:
                итог.setdefault(вид, None)
            break
    return итог


def _вход(черновик: dict[str, Any], вид: str, owned: bool | None, угадано: list[str], почему: str) -> None:
    """Добавить (или уточнить владение) вход вида `вид` в черновике."""
    вид_out = INPUT_KIND_OUT[вид]
    входы = черновик.setdefault("inputs", [])
    for в in входы:
        if в["kind"] == вид_out:
            if в.get("owned") is None and owned is not None:
                в["owned"] = owned
                угадано.append(почему)
            return
    входы.append({"kind": вид_out, "owned": owned})
    угадано.append(почему)


def _доводка_черновика(brief: str, низ: str, t: Spec, черновик: dict[str, Any], угадано: list[str]) -> None:
    from studio import draft_lexicon as lx

    мл = lx.normalise(brief)
    письмо = lx.script_language(brief)
    материал = _материал_черновика(низ)
    for вид, своё in lx.owned_media(мл).items():
        if материал.get(вид) is not True:
            материал[вид] = True if своё else материал.get(вид)
    есть_глаголом = _есть_по_глаголу(низ)
    for вид in есть_глаголом:
        материал[вид] = True
    задача = черновик.get("task")
    if isinstance(задача, list):
        задача = задача[0]
    заказ = bool(MAKE_WORDS.search(низ)) or lx.mentions(мл, lx.MAKE)

    # 1. РАБОТА: многоязычная, затем английские поправки.
    if задача is None:
        задача = lx.task(мл)
        if задача:
            угадано.append(f"task '{задача}' read from the brief's words — confirm the job")
    if задача in (None, "generate", "animate") and re.search(r"\bupscal\w*|апскейл\w*", низ):
        вид = "photo" if "photo" in материал and "video" not in материал else "video"
        if вид in материал or вид in есть_глаголом:
            задача = "upscale"
    if задача in (None, "generate") and re.search(
        r"(?:convert|turn) .{0,50}\b(?:to|into) (?:smooth )?(?:60|120|240) ?fps|smooth (?:60|120|240) ?fps", низ
    ) and "video" in материал:
        задача = "interpolate"
    if задача == "interpolate" and заказ and not any(материал.values()) and "inputs" in черновик:
        # «Generate a 120fps slow-motion shot» — заказ ролика, не интерполяция исходника.
        задача = "generate"
        черновик.pop("inputs", None)
    if задача in (None, "generate") and re.search(r"restyl\w*|\binto an? [\w -]{0,30}(?:look|style)\b", низ) and "video" in материал:
        задача = "video-edit"
        черновик["edit"] = ["restyle"]
    if задача in (None, "generate") and "video" in материал and re.search(
        r"voice-?over translation|translat\w* (?:\w+ ){0,6}(?:video|clip|webinar|demo)|\bdub\w*", низ
    ):
        задача = "dub-translate"
        if re.search(r"no lip[- ]?sync|without lip[- ]?sync|lip[- ]?sync (?:is )?not needed", низ):
            черновик["lipsync"] = False
    if (
        задача in (None, "generate", "avatar")
        and LIPSYNC.search(низ)
        and "audio" in материал
        and "photo" not in материал
        and "video" in материал
    ):
        задача = "lipsync"
    if задача in (None, "generate") and re.search(r"music video for (?:our|my) (?:own )?", низ) and материал.get("audio"):
        задача = "music-visualiser"
    if задача in (None, "generate") and re.search(r"clon\w* (?:[\w'’]+ ){0,3}voice", низ):
        задача = "voice-clone"
    if задача in (None, "generate") and re.search(
        r"\bfaces? (?:on|onto|into)\b|swap (?:my|our|his|her) face|face[- ]?swap", низ
    ):
        задача = "face-replace"
    if задача in (None, "generate") and "photo" in материал and re.search(r"rotat\w*|\bspin\w*|\b360\b", низ):
        задача = "turntable"
    if задача in (None, "generate") and re.search(r"try-?on|\bput (?:our|my) (?:\w+ ){0,3}on\b", низ):
        задача = "edit"
        материал["photo"] = True
    if задача in (None, "generate") and re.search(
        r"talking (?:host|presenter|person)|presenter avatar|\brecit\w*|\bspeaks? to (?:the )?camera", низ
    ):
        задача = "avatar"
    if задача in (None, "generate", "animate") and re.search(r"same (?:[\w-]+ ){0,3}characters?", низ) and "video" in черновик.get("outputs", []):
        задача = "r2v"
    картинки_выход = "image" in черновик.get("outputs", []) or bool(
        re.search(r"\bcomic\b|\bpanels?\b|illustrations?|posters?|thumbnails?", низ)
    )
    if задача in (None, "generate") and картинки_выход and материал.get("photo") is True:
        # Свои снимки и картинки на выходе — правка по ним (серия по референсу,
        # «убери провода с 30 фото»), а не генерация с нуля.
        задача = "edit"
    if задача in (None, "generate") and картинки_выход and "photo" in материал and re.search(
        r"\b(?:remove|replace|retouch|erase|clean)\b", низ
    ):
        задача = "edit"
    if задача == "animate" and "photo" not in материал and not re.search(r"\blogo|\bimage|\bphoto|\bpicture", низ):
        # «animated explainer» — стиль ролика, а не оживление снимка.
        задача = "generate"
    if задача is None and (черновик.get("outputs") or lx.outputs(мл) or картинки_выход):
        # Как у основного разборщика: назван выход, работы нет — заказ генерации.
        задача = "generate"
    исходная = черновик.get("task")
    if задача and not isinstance(исходная, list):
        черновик["task"] = задача

    # 2. ВЫХОДЫ.
    выходы = list(черновик.get("outputs", []))
    if not выходы:
        выходы = [в for в in lx.outputs(мл) if в in OUTPUTS]
        if "video" in выходы and "image" in выходы:
            выходы.remove("image")
    if задача in DRAFT_TASK_OUTPUTS and (not выходы or задача != исходная):
        выходы = list(DRAFT_TASK_OUTPUTS[задача])
    if задача == "upscale":
        выходы = ["image"] if "photo" in материал and "video" not in материал else ["video"]
    if задача == "edit":
        выходы = ["image"]
    if картинки_выход and not выходы:
        выходы = ["image"]
    if SIGN_WORDS.search(низ):
        выходы = [в for в in выходы if в != "speech"]
        for образец, тег in SIGN_TAGS:
            if re.search(образец, низ):
                черновик["languages"] = [тег]
                break
        else:
            черновик.pop("languages", None)
    if (not выходы or выходы == ["video"]) and MUSIC_ONLY.search(низ) and not VISUAL_CUE.search(низ):
        выходы = ["music"]
    if re.search(r"\bsounds\b|sound design|\bfoley\b", низ) and "sfx" not in выходы and выходы:
        выходы.append("sfx")
    if выходы:
        черновик["outputs"] = [в for в in OUTPUTS if в in выходы]
    if задача is None and выходы and заказ:
        задача = черновик["task"] = "generate"

    # 3. ВХОДЫ.
    чужое = bool(NOT_OWNED_CUE.search(низ))
    нужен = {
        "upscale": "photo" if "image" in выходы else "video",
        "interpolate": "video",
        "video-edit": "video",
        "restore": "video",
        "colorize": "video",
        "dub-translate": "video",
        "lipsync": "video",
        "music-visualiser": "audio",
        "voice-clone": "audio",
        "turntable": "photo",
        "edit": "photo",
        "face-replace": "video",
        "transcribe": "video" if re.search(r"\bvideos?\b|footage|\bclips?\b|видео|视频|動画|영상|فيديو|वीडियो|วิดีโอ", низ) else "audio",
        "avatar": "photo" if "photo" in материал else None,
        "remove-background": "photo" if "photo" in материал and "video" not in материал else "video",
    }.get(задача or "")
    if нужен:
        своё = материал.get(нужен)
        if своё is None and задача in OWNED_ON_MENTION_TASKS and материал and not чужое:
            своё = True
            угадано.append(
                f"inputs: the {INPUT_KIND_OUT[нужен]} the brief names is taken as the customer's own (the job works "
                "on their material) — confirm they own it"
            )
        if задача == "transcribe" and черновик.get("inputs"):
            # «interview» — разговор; видео ли это, сказано не было: вход — звук.
            черновик["inputs"] = [в for в in черновик["inputs"] if в["kind"] != "video" or нужен == "video"]
        _вход(черновик, нужен, своё, угадано, f"inputs: {INPUT_KIND_OUT[нужен]} implied by the task '{задача}'")
    if задача == "lipsync" and "audio" in материал:
        _вход(черновик, "audio", True if материал.get("audio") is not False else None, угадано,
              "inputs: the new audio named in a lipsync brief is taken as the customer's — confirm")
    if задача == "face-replace":
        лицо = True if re.search(r"\b(?:my|our) faces?\b", низ) else None
        _вход(черновик, "photo", лицо, угадано, "inputs: a face image is needed for face replacement")
    for вид, своё in материал.items():
        if своё is True and вид in INPUT_KIND_OUT:
            _вход(черновик, вид, True, угадано, f"inputs: {INPUT_KIND_OUT[вид]} named as the customer's own")
    if (м := BROUGHT_CUE.search(низ)) and задача in ("avatar", "generate", "animate", "lipsync"):
        вид = "photo" if re.search(r"photo|picture|portrait|selfie", м.group(0)) else "video"
        _вход(черновик, вид, материал.get(вид) if материал.get(вид) else None, угадано,
              f"inputs: a {INPUT_KIND_OUT[вид]} the customer brings («{м.group(0)}») — whose it is was not said")
    if (
        задача == "generate"
        and any(в["kind"] == "video" and в.get("owned") for в in черновик.get("inputs", []))
        and re.search(r"\badd\b .{0,80}\bto (?:my|our)\b", низ)
        and set(выходы) - {"video"}
    ):
        # «Add foley to my silent film»: выход — дорожка, видео — вход.
        выходы = [в for в in выходы if в != "video"]
        черновик["outputs"] = [в for в in OUTPUTS if в in выходы]
    # Названное без «своего» в заказе генерации — обычно заказанное (ролик,
    # озвучка, картинка), а не вход. Принесённым считается: своё; снимок, когда
    # картинка не заказана; материал после «use/from/her…».
    принесено = {
        в for в, своё in материал.items() if своё is True or (в == "photo" and "image" not in выходы)
    }
    if BROUGHT_CUE.search(низ):
        принесено.add("brought")
    if "inputs" not in черновик and задача in ("generate", "r2v", "avatar") and not принесено:
        # Видео без «своего» в заказе генерации — это заказанный ролик, а не вход.
        черновик["inputs"] = []
        угадано.append("inputs: [] — the brief names no photo, video, audio or script to bring; confirm nothing is brought")
    if "image" in черновик.get("outputs", []) and "shots" not in черновик and not any(
        в.get("count") for в in черновик.get("inputs", [])
    ):
        м = re.search(
            r"\b(\d{1,3})[- ](?:[\w-]+ ){0,2}(?:illustrations?|images?|pictures?|panels?|thumbnails?|posters?)\b", низ
        )
        if м:
            черновик["shots"] = int(м.group(1))
        elif re.search(r"\b(?:a|an|one|1)\s+(?:[\w-]+\s+){0,2}(?:image|picture|poster|still|illustration)\b", низ):
            черновик["shots"] = 1
    if черновик.get("inputs"):
        n = lx.count(мл)
        штук = re.search(r"(\d{1,3})\s+(?:[\w-]+\s+){0,2}(?:photos?|pictures?|images?|dresses|packshot photos?)", низ)
        for в in черновик["inputs"]:
            if в["kind"] == "image" and not в.get("count") and (n or штук) and задача in ("edit", "remove-background", "upscale", "turntable"):
                в["count"] = n or int(штук.group(1))  # type: ignore[union-attr]
        if задача in ("edit", "remove-background", "upscale") and "shots" not in черновик:
            штуки = [в.get("count") for в in черновик["inputs"] if в.get("count")]
            if штуки:
                черновик["shots"] = штуки[0]

    # 4. ПОЛЯ МНОГОЯЗЫЧНОГО БРИФА: длительность, кадр, деньги, языки.
    if "duration_s" not in черновик and "shots" not in черновик and (д := lx.duration_s(мл)):
        if задача in MATERIAL_TASKS and черновик.get("inputs"):
            главный = next((в for в in черновик["inputs"] if в["kind"] in ("video", "audio")), None)
            if главный is not None:
                главный.setdefault("duration_s", д)
        черновик["duration_s"] = д
    if "aspect" not in черновик and (а := lx.aspect(мл)):
        черновик["aspect"] = а
    if "budget" not in черновик and (деньги := lx.money(мл)):
        черновик["budget"] = {"amount": деньги[0], "currency": деньги[1]}
    if "languages" not in черновик and not SIGN_WORDS.search(низ):
        названы = lx.languages(мл)
        if названы:
            черновик["languages"] = названы
        elif письмо and ("speech" in выходы or задача in LANGUAGE_TASKS):
            черновик["languages"] = [письмо]
            угадано.append(f"languages: '{письмо}' read from the script the brief is written in — confirm")
    if задача == "dub-translate" and черновик.get("languages"):
        исходные = set(lx.source_languages(мл))
        for тег, формы in pl.LANGUAGE_FORMS.items():
            код = LANGUAGE_TO_CODE.get(тег)
            if код and any(
                re.search(rf"\bfrom {re.escape(ф)}|(?<![a-zа-яё]){re.escape(ф)}\w* (?:[\w-]+ ){{0,2}}(?:video|webinar|demo|clip)", низ)
                for ф in формы
            ):
                исходные.add(код)
        цели = [я for я in черновик["languages"] if я.split("-")[0] not in исходные]
        if цели:
            черновик["languages"] = цели
        if lx.mentions(мл, lx.LIPSYNC) and "lipsync" not in черновик:
            черновик["lipsync"] = True


#: Пятнадцатый круг: ПОЛЯ РЕШЕНИЙ, которые черновик предлагает заполнить — порядок печати.
DECISION_FIELDS: tuple[str, ...] = (
    "live",
    "edit_target",
    "outputs[].loop",
    "outputs[].tileable",
    "outputs[].alpha",
    "people[].on_screen",
    "people[].speaks",
    "lipsync",
    "cast_together",
    "single_take_s",
    "training_use",
    "consistency",
    "dataset_count",
)
#: Шестнадцатый круг: поля решений, прежде читавшиеся только словами (EN/RU).
DECISION_FIELDS_R16: tuple[str, ...] = (
    "anonymise",
    "voiceover",
    "delivery.platform",
    "delivery.dynamic_range",
    "delivery.stems",
    "delivery.direction",
    "delivery.format",
    "domain",
    "style",
    "subject",
    "accessibility",
    "display",
    "audio_content",
    "follows_picture",
    "animate_input",
    "community",
    "inputs[].source",
    "inputs[].defects",
    "inputs[].fps",
)
DECISION_FIELDS = (*DECISION_FIELDS, *DECISION_FIELDS_R16)


def _прочитано_словами(brief: str, низ: str) -> dict[str, Any]:
    """Значения полей решений, которые ЗАПАСНЫЕ слова брифа (EN/RU) дают сейчас — подсказка, не решение."""
    from studio import edit_intent as ei
    from studio import realtime as rt
    from studio.recipes import apply as rc
    from studio.recipes import checklist as cl

    прочитано: dict[str, Any] = {}
    if rt.asked(brief):
        прочитано["live"] = True
    if ei.PERSON_EDIT.search(brief):
        прочитано["edit_target"] = "person"
    elif ei.TEXT_EDIT_WORDS.search(brief):
        прочитано["edit_target"] = "text"
    if rc.LOOP.search(brief):
        прочитано["outputs[].loop"] = True
    if rc.wants_alpha(Spec(), brief):
        прочитано["outputs[].alpha"] = True
    if NO_LIPSYNC.search(brief):
        прочитано["lipsync"] = False
    elif SINGING.search(исполнитель_словами(brief)) or ON_SCREEN_SPEAKER.search(brief):
        прочитано["lipsync"] = True
    if CAST_TOGETHER.search(NO_DIALOGUE.sub(" ", brief)) or DIALOGUE.search(NO_DIALOGUE.sub(" ", brief)):
        прочитано["cast_together"] = True
    if cl.W_TRAINING_DATA.search(низ):
        прочитано["training_use"] = True
    оси = [о for о, образец in (("light", cl.W_RELIGHT), ("character", RECURRING_CHARACTER)) if образец.search(низ)]
    if оси:
        прочитано["consistency"] = оси
    прочитано.update(_прочитано_словами_r16(brief, низ))
    return прочитано


def _прочитано_словами_r16(brief: str, низ: str) -> dict[str, Any]:
    """Шестнадцатый круг: что запасные слова (EN/RU) дают полям, которые прежде решались только словами."""
    from studio import expert_r15 as x15
    from studio.recipes import apply as rc
    from studio.recipes import checklist as cl

    п: dict[str, Any] = {}
    лица = x15.anonymise_method(Spec(), brief)
    голос = bool(cl.W_VOICE_ANON.search(brief))
    if лица or голос:
        п["anonymise"] = {"faces": bool(лица), "voice": голос, **({"method": лица} if лица else {})}
    if cl.W_NO_SPEECH.search(низ):
        п["voiceover"] = False
    площадки = [
        имя for имя, образец in (
            ("broadcast", cl.W_BROADCAST), ("cinema", cl.W_CINEMA), ("streaming-premium", cl.W_STREAMING),
            ("podcast", cl.W_PODCAST), ("audiobook", cl.W_AUDIOBOOK), ("telephony", cl.W_TELEPHONY),
            ("voice-agent", cl.W_VOICE_BOT), ("game-engine", cl.W_GAME), ("marketplace", cl.W_MARKETPLACE),
            ("vfx", cl.W_VFX), ("editorial", cl.W_EDITORIAL), ("app-store", cl.W_APP_STORE),
            ("music-distribution", cl.W_DISTRIBUTION),
        ) if образец.search(низ)
    ]
    if cl.W_PLATFORM.search(низ):
        площадки.append("youtube" if re.search(r"youtube|ютуб", низ) else "tiktok" if re.search(r"tiktok|тикток", низ) else "instagram")
    if площадки:
        п["delivery.platform"] = площадки
    if cl.W_HDR.search(низ):
        п["delivery.dynamic_range"] = "hdr"
    if cl.W_OUTBOUND.search(низ):
        п["delivery.direction"] = "outbound"
    if rc.MESH.search(brief):
        п["delivery.format"] = ["glb"]
    области = [
        имя for имя, образец in (
            ("advertising", cl.W_AD), ("branded-content", cl.W_SPONSORED), ("news", cl.W_NEWS),
            ("real-estate", cl.W_REAL_ESTATE), ("political", cl.W_POLITICAL),
        ) if образец.search(низ)
    ]
    if области:
        п["domain"] = области
    if cl.W_ANIMATION_TWOS.search(низ):
        п["style"] = "limited-animation"
    elif cl.W_STYLISED_FACE.search(низ) or rc.DRAWN.search(brief):
        п["style"] = "stylised"
    elif cl.W_REALISTIC.search(низ):
        п["style"] = "photoreal"
    предметы = [
        имя for имя, да in (
            ("product", cl.W_PRODUCT.search(низ)), ("cosmetic", cl.W_COSMETIC.search(низ)),
            ("reflective", cl.W_REFLECTIVE.search(низ)), ("before-after", cl.W_BEFORE_AFTER.search(низ)),
            ("garment", rc.TRY_ON.search(brief) and rc.GARMENT.search(brief)), ("interior", rc.WALKTHROUGH.search(brief)),
            ("mascot", rc.CHARACTER.search(brief) and not rc.FACE_ONLY.search(brief)),
        ) if да
    ]
    if предметы:
        п["subject"] = предметы
    if cl.W_A11Y.search(низ):
        п["accessibility"] = ["captions"]
    if cl.W_HOLOGRAM.search(низ):
        п["display"] = "additive"
    if cl.W_SINGING.search(низ):
        п["audio_content"] = ["song"]
    if rc.FOLLOWS_PICTURE.search(brief):
        п["follows_picture"] = True
    if ep.COMMUNITY_ASKED.search(brief):
        п["community"] = True
    источники = [
        имя for имя, образец in (
            ("slides", cl.W_SLIDES), ("archival", cl.W_ARCHIVAL), ("cine-film", cl.W_CINE_FILM),
            ("timelapse", cl.W_TIMELAPSE), ("green-screen", cl.W_GREEN_SCREEN), ("stock", cl.W_STOCK),
            ("third-party-song", cl.W_COVER_SONG),
        ) if образец.search(низ)
    ]
    if источники:
        п["inputs[].source"] = источники
    дефекты = [имя for имя, образец in (("halftone", cl.W_HALFTONE), ("noise", cl.W_AUDIO_CLEAN)) if образец.search(низ)]
    if дефекты:
        п["inputs[].defects"] = дефекты
    return п


def decision_fields(brief: str, raw: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Поля решений для вопроса о спецификации: что заполнить и что дали запасные слова.

    ПЯТНАДЦАТЫЙ КРУГ. Эти решения (живая система, цель правки, петля, губы, кадр
    на двоих, длина дубля, обучение, постоянство, датасет) прежде брались только
    из английских и русских слов брифа: тот же заказ по-китайски, по-японски,
    по-испански терял оговорку или шаг. Вызывающая модель понимает любой язык —
    черновик просит её назвать поле; `read_from_text` — что дали бы запасные
    слова (на другом языке там обычно пусто — это и есть повод заполнить поле).
    """
    названо = set(raw) if isinstance(raw, Mapping) else set()
    прочитано = _прочитано_словами(brief, _norm(brief))
    out: list[dict[str, Any]] = []
    for поле in DECISION_FIELDS:
        верх = re.split(r"[\[.]", поле, maxsplit=1)[0]
        if верх in названо and верх not in ("outputs", "people", "inputs"):
            continue
        # Допустимые значения — в `spec_needed.allowed` под тем же именем (не дублируются).
        out.append({"field": поле, "read_from_text": прочитано.get(поле)})
    return out


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
        черновик["self_host"] = {
            к: в for к, в in dict(t.self_host).items() if в is not None and к != "platform"
        } or True
    if t.jurisdiction:
        черновик["jurisdiction"] = list(t.jurisdiction)
    _доводка_черновика(brief, низ, t, черновик, угадано)
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
        # Пятнадцатый круг: поля решений — заполните их на любом языке брифа.
        "decision_fields": decision_fields(brief, raw),
    }
