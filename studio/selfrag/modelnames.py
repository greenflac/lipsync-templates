"""Одно имя модели — одна модель: разрешение написаний в ОДНОМ месте.

ДЕФЕКТ, ИЗМЕРЕНО 2026-09-02 на живой базе (`studio/knowledge/model_facts.jsonl`)

    стоящих утверждений          1696
    имён модели                   466
    имён после свёртки            457
    групп из >1 написания           9   все девять — одна модель дважды

Девятка целиком: flux-1-dev/flux.1-dev, flux-1-kontext-pro/flux.1-kontext-pro,
flux-2-dev/flux.2-dev, flux-2-klein-4b/flux.2-klein-4b,
flux-2-klein-9b/flux.2-klein-9b, hunyuan-video/hunyuanvideo, ltx-2.3/ltx-2-3,
seedance2_5/seedance-2.5, wan-2.2-t2v-a14b/wan2.2-t2v-a14b.

Что это стоит спрашивающему, ИЗМЕРЕНО тем же днём через `advice.advise`:

    advise("flux.2-klein-9b")   4 атрибута, 6 провалов
    advise("flux-2-klein-9b")   2 атрибута, 0 провалов   <- та же модель
    advise("ltx-2.3")           4 атрибута, 6 провалов
    advise("ltx-2-3")           2 атрибута, 0 провалов

И оба ответа — `pass`. Ответ не то что неполон: он не сообщает, что неполон.

ПОЧЕМУ НЕ ПЕРЕПИСАТЬ СТРОКИ. Журнал фактов append-only, и это сторожит гейт
`scripts/check_append_only.py`. Свёртка поэтому делается НА ЧТЕНИИ: строки
остаются как записаны, а поиск по имени достаёт все карманы сразу.
`scripts/merge_model_ids.py` канонизирует иначе — записью нового факта и
отзывом старого, — и это по-прежнему верный способ для написания, о котором
известно, КАК его пишет вендор. Здесь же случай, когда такого свидетельства
нет: `hunyuan-video` против `hunyuanvideo` — обе формы встречаются у самого
вендора. Свёртка на чтении не требует выбирать победителя и потому применима
ко всем девяти группам, а не к тем, где вендор высказался.

ТРИ ИСХОДА (правило Р1). Имя либо разрешается, либо не разрешается, либо не
названо, и последние два — РАЗНЫЕ положения дел: «мы не знаем такой модели»
лечится поиском источника, «имени не назвали» — вопросом к спрашивающему.
Тихая пустота вместо третьего исхода — самая частая ошибка на этом проекте.
"""

from __future__ import annotations

import re

from collections import defaultdict
from functools import lru_cache
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from lipsync.fork_identity import PASS, UNMEASURED

__all__ = [
    "MIN_SHARED_PREFIX",
    "NOT_IN_BASE",
    "NO_NAME_ASKED",
    "RESOLVED",
    "Resolution",
    "canonical_spelling",
    "family",
    "fold",
    "group",
    "parent",
    "resolve",
    "similar",
    "strip_vendor",
    "tokens",
]

#: ВЫБРАНО (эта сессия, 2026-09-02): что считается одним и тем же именем.
#: Регистр, пробелы и разделители `- _ . /` — оформление, а не имя: вендоры
#: пишут одну и ту же модель и так и эдак на соседних страницах. Всё
#: остальное значимо. `*` сохраняется: это не имя модели, а ОБЛАСТЬ
#: («о поле» / «о линейке вендора»), и склеить `*` с пустой строкой значило бы
#: сделать все находки о классе безымянными.
KEPT_SYMBOLS = "*"

#: Буква `v` ПЕРЕД номером версии, стоящая в начале звена имени: `sync-lipsync-v2`
#: и `sync-lipsync-2` — одна модель, и обе записи есть в живой базе с одной и
#: той же ценой с одного и того же адреса.
#:
#: ИЗМЕРЕНО 2026-09-03 на живой базе: правило склеивает СЕМЬ новых групп, и все
#: семь — одна модель под двумя написаниями:
#:
#:     ideogram-3 / ideogram-v3                 flux-pro-1.1-ultra / flux-pro-v1.1-ultra
#:     wan-2.7-edit-video / wan-v2.7-…          bytedance-omnihuman-1.5 / …-v1.5
#:     sync-lipsync-2 / sync-lipsync-v2         wan-2.2-14b-animate-replace / wan-v2.2-…
#:     sync-lipsync-3-image-to-video / sync-lipsync-v3-image-to-video
#:
#: НАЧАЛО ЗВЕНА, А НЕ ЛЮБОЕ МЕСТО, И ЭТО НЕГАТИВНЫЙ КОНТРОЛЬ (И5). Правило,
#: ловящее `v` перед цифрой ГДЕ УГОДНО, превратило бы `wav2lip` — самую
#: известную липсинк-модель в этой базе — в `wa2lip`. Проверено перебором живых
#: имён: внутри слова `v` перед цифрой встречается ровно у трёх — `wav2lip`,
#: `proteusv0.3`, `pornmasterpro_noobv3vae`.
#:
#: ПЕРВАЯ РЕДАКЦИЯ ЭТОГО КОММЕНТАРИЯ НАЗЫВАЛА ДРУГОЙ ПРИМЕР — `s2v`, `t2v`,
#: `i2v`, — и он был НЕВЕРЕН: там `v` стоит в конце и цифра перед ним, а не
#: после, так что слабое правило их не трогает. Мутация это и показала: мутант
#: «`v` ловится где угодно» ПРОМОЛЧАЛ, потому что тест сторожил не тот случай.
ПРИСТАВКА_ВЕРСИИ = re.compile(r"(?:(?<=[-_./ ])|^)v(?=\d)")

#: ВЫБРАНО, перенесено из `facts.NEAR_MIN_SHARED` без изменения значения:
#: сколько знаков общего начала делают подсказку подсказкой. Три знака (`gen`)
#: цепляют половину базы, и это проверяется тестом с обеих сторон.
MIN_SHARED_PREFIX = 4

#: ОДНА МОДЕЛЬ, ДВА НАПИСАНИЯ, КОТОРЫЕ НЕ СКЛЕИТЬ ГРУБОЙ СВЁРТКОЙ. Таблица, а
#: не правило: правило, склеивающее `infinitalk` с `infinitetalk`, склеило бы
#: заодно десяток чужих пар. Каждая строка — решение об ИДЕНТИЧНОСТИ, и у
#: каждой названо свидетельство, потому что ошибка здесь приписывает модели
#: чужие наблюдения — худший вид вранья, который умеет этот продукт.
#:
#: РАЗБОР 2026-09-04, из-за которого таблица появилась. У 49 моделей базы есть
#: применимость, и планировщик ВИДИТ из них три: остальным 46 нечего сопоставить
#: с шагом — у них нет строк о входах и выходах. `infinitetalk` — 12 строк, из
#: них 3 применимости, схемы нет. `infinitalk` — 7 строк, схема есть,
#: применимости ноль. Это одна модель, разъехавшаяся написанием между площадкой
#: и репозиторием, и из-за разъезда продукт выбирал её вслепую.
#:
#: СВИДЕТЕЛЬСТВО ПО ЭТОЙ СТРОКЕ: эндпоинт `fal-ai/infinitalk`, страница которого
#: описывает его теми же словами, что репозиторий MeiGen-AI/InfiniteTalk —
#: «talking avatar video from an image and audio file, the avatar lip-syncs to
#: the provided audio»; вход (изображение + аудио) и выход (видео) совпадают.
#: ПРОТИВОРЕЧАЩЕЕ СВИДЕТЕЛЬСТВО, названное вслух: поле `about` в машинной схеме
#: fal начинается словом «MultiTalk» — имя СОСЕДНЕЙ модели той же лаборатории.
#: Поэтому `multitalk` в таблицу НЕ внесён: у него свой репозиторий и свои
#: наблюдения, и склеить его сюда значило бы приписать чужое.
ALIASES: dict[str, str] = {
    "infinitalk": "infinitetalk",
    # ВТОРАЯ И ТРЕТЬЯ СТРОКИ, 2026-09-04. Свидетельство машинное и проверяемое:
    # схема эндпоинта `fal-ai/bytedance/omnihuman` и статья arXiv 2508.19209 —
    # об одной модели, и версия в имени эндпоинта совпадает с версией в базе
    # (`/v1.5` против `omnihuman-1.5`). Разъехалось написание, а не модель:
    # площадка ставит впереди имя лаборатории, статья — нет.
    #
    # ПОЧЕМУ НЕ ПРАВИЛО «СРЕЗАТЬ ИМЯ ЛАБОРАТОРИИ». Пробовал и отказался:
    # `elevenlabs-dubbing-v2` после среза станет `dubbing-v2` — имя, не
    # называющее ничего, и склеится с любым чужим «дубляжом». Срез безопасен
    # только когда остаток УЖЕ есть в базе, а это уже не свёртка имени, а
    # разрешение против списка известных — другая функция и другая работа.
    # Записано отдельным пунктом в хэндофе, потому что моделей с таким
    # разъездом в базе ещё сорок с лишним.
    "bytedanceomnihuman": "omnihuman1",
    "bytedanceomnihuman15": "omnihuman15",
    # ЧЕТВЁРТАЯ И ПЯТАЯ СТРОКИ, 2026-09-04. Площадка роняет версию семейства из
    # слага: эндпоинт `fal-ai/flux/dev` — это FLUX.1 [dev], `fal-ai/flux-kontext/dev`
    # — FLUX.1 Kontext [dev]. Свидетельство машинное: у первого вход `текст` и
    # выход `изображение`, у второго `изображение, текст` -> `изображение` —
    # ровно то, чем эти две модели и различаются в документации вендора.
    #
    # НЕГАТИВНЫЙ КОНТРОЛЬ ЗДЕСЬ ОСОБЕННО ВАЖЕН: `flux.1-dev` и
    # `flux.1-kontext-dev` — РАЗНЫЕ модели, и `flux-2-dev` тоже; таблица обязана
    # склеить пары и не тронуть соседей. Проверяется тестом с обеих сторон.
    "fluxdev": "flux1dev",
    "fluxkontextdev": "flux1kontextdev",
}

#: ПЛОЩАДКА ВПЕРЕДИ ПУТИ — не часть имени модели (2026-10-14). `fal-ai/…`,
#: `replicate/…`: так площадка называет СВОЙ эндпоинт, а модель под ним та же.
#: Срезается только звено ПУТИ (через `/`), никогда не кусок имени через дефис:
#: `fal-ai-avatar` — не путь.
ПЛОЩАДКИ_В_ПУТИ: frozenset[str] = frozenset({"fal-ai", "fal", "replicate", "models"})

#: ВЕНДОР ПЕРВЫМ ЗВЕНОМ ПУТИ (`google/nano-banana-2`, `bytedance/seedance/…`,
#: `openai/gpt-image-2.5/…`, `minimax/hailuo-2.3`). Срезается так же, как
#: площадка, но ТОЛЬКО в пути: в пути вендор — каталог, а не имя.
#:
#: НЕГАТИВНЫЙ КОНТРОЛЬ (И5): `veed` и `elevenlabs` здесь НЕТ нарочно. У VEED
#: вендор и есть имя модели (`veed/lipsync/v2` в базе — `veed-lipsync-v2`), а
#: у ElevenLabs путь `elevenlabs/tts/eleven-v3` — это ровно то, что база
#: держит под `elevenlabs-tts-eleven-v3`; срез оставил бы `tts-eleven-v3`.
ВЕНДОРЫ_В_ПУТИ: frozenset[str] = frozenset(
    {
        "bytedance",
        "google",
        "openai",
        "minimax",
        "minimaxai",
        "xai",
        "lightricks",
        "black-forest-labs",
        "kwaivgi",
        "kuaishou",
        "wan-ai",
        "alibaba",
        "tencent",
    }
)

#: ВЕНДОР ПЕРВЫМ ЗВЕНОМ ИМЕНИ (`bytedance-seedance-v1-pro-image-to-video`).
#: Срез ЗДЕСЬ — не свёртка, а разрешение ПРОТИВ СПИСКА ИЗВЕСТНЫХ: остаток
#: принимается, только если он УЖЕ есть в базе (см. `group` и `resolve`). Это
#: та «другая функция», о которой говорит комментарий к `ALIASES` выше:
#: `elevenlabs-dubbing-v2` после среза — `dubbing-v2`, имя ничьё, и в базе его
#: нет, поэтому ничего не склеивается.
ВЕНДОРЫ_В_ИМЕНИ: frozenset[str] = frozenset(
    {
        "bytedance",
        "google",
        "openai",
        "minimax",
        "xai",
        "lightricks",
        "blackforestlabs",
        "alibaba",
        "kuaishou",
        "tencent",
        "elevenlabs",
    }
)

#: ОДНО СЛОВО — ОДНО ЗВЕНО: синонимы режима генерации. Площадки пишут
#: `image-to-video`, репозитории — `i2v`, и в живой базе ИЗМЕРЕНО 2026-10-14
#: пять пар «одна модель, два написания режима»: `minimax-h3-i2v` /
#: `minimax-h3-image-to-video`, `veo-3.1-i2v` / `veo3.1-image-to-video`,
#: `wan-2.2-a14b-i2v` / `wan-v2.2-a14b-image-to-video`, `pixverse-v5-i2v` /
#: `pixverse-v5-image-to-video`, `pixverse-v6-i2v` / `pixverse-v6-image-to-video`.
СИНОНИМЫ_ЗВЕНЬЕВ: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("image", "to", "video"), ("i2v",)),
    (("text", "to", "video"), ("t2v",)),
    (("text", "to", "image"), ("t2i",)),
    (("image2video",), ("i2v",)),
    (("text2video",), ("t2v",)),
    (("text2image",), ("t2i",)),
    (("text", "to", "speech"), ("tts",)),
    (("speech", "to", "video"), ("s2v",)),
    (("reference", "to", "video"), ("r2v",)),
)

#: КУРИРУЕМЫЕ ПЕРЕПИСИ НАЧАЛА ИМЕНИ. Каждая строка — решение об ИДЕНТИЧНОСТИ, и
#: у каждой названо свидетельство (то же правило, что у `ALIASES`): ошибка
#: здесь приписывает модели чужие наблюдения.
ПЕРЕПИСИ_НАЧАЛА: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    # fal называет каталог эндпоинтов Kling `kling-video/…`: `fal-ai/kling-video/
    # v3/pro/image-to-video` — это Kling 3.0 Pro i2v, слово `video` — имя
    # каталога площадки, а не модели.
    (("kling", "video"), ("kling",)),
    # ElevenLabs: id API — `eleven_v3`, `eleven_multilingual_v2` (их же
    # документация, цитаты в базе; см. `scripts/merge_model_ids.py`). Площадка
    # fal пишет `elevenlabs/tts/eleven-v3`, люди — «ElevenLabs v3».
    (("elevenlabs", "tts", "eleven"), ("eleven",)),
    (("elevenlabs", "eleven"), ("eleven",)),
    (("elevenlabs", "tts", "multilingual"), ("eleven", "multilingual")),
    (("elevenlabs", "multilingual"), ("eleven", "multilingual")),
    (("elevenlabs", "turbo"), ("eleven", "turbo")),
    (("elevenlabs", "flash"), ("eleven", "flash")),
    (("elevenlabs", "3"), ("eleven", "3")),
    # LTX-2.3: Lightricks пишет «LTX-2.3», HuggingFace-слаги — `ltx-2-3`
    # (точка в слаге недопустима). Пара `ltx-2.3`/`ltx-2-3` — та самая из
    # девятки, найденной 2026-09-02.
    (("ltx", "2", "3"), ("ltx", "2.3")),
    # Nano Banana 2 — это Gemini 3.1 Flash Image (анонс Google, февраль 2026),
    # Nano Banana Pro — Gemini 3 Pro Image: в базе это подтверждено строкой
    # `nano-banana-pro.underlying_model = "Gemini 3 Pro Image"` со схемы fal.
    # Runway пишет те же модели `gemini_image3.1_flash` / `gemini_image3_pro`.
    (("gemini", "3.1", "flash", "image"), ("nano", "banana", "2")),
    (("gemini", "image", "3.1", "flash"), ("nano", "banana", "2")),
    (("gemini", "3", "pro", "image"), ("nano", "banana", "pro")),
    (("gemini", "image", "3", "pro"), ("nano", "banana", "pro")),
    # HappyHorse пишут и слитно, и через дефис; в базе — `happyhorse_1_0`.
    (("happy", "horse"), ("happyhorse",)),
    # `h3-max` -> `minimax-h3-max` НАРОЧНО НЕ ПЕРЕПИСЬ. Голден-задача g15
    # (решение владельца): «двигаться подсказкой можно, фактом — нет». Имя
    # находится выводом по единственному соседу (`HOW_NEIGHBOUR`), и ответ
    # по нему идёт с исходом `could not measure`, а не `pass`.
)

#: КУРИРУЕМЫЕ ХВОСТЫ, НЕ МЕНЯЮЩИЕ МОДЕЛИ. Vertex называет GA-версию модели
#: `<имя>-generate-001` (`veo-3.1-generate-001`, `imagen-4.0-generate-001` —
#: строки базы с cloud.google.com). Это id выпуска, а не другая модель.
#: `veo-3.1-fast-generate-001` после среза — `veo-3.1-fast`, вариант, а не
#: `veo-3.1`: срезается только хвост.
ХВОСТЫ_ВЫПУСКА: tuple[tuple[str, ...], ...] = (
    ("generate", "001"),
    ("generate", "preview"),
)

#: Звено — голый номер версии: `2`, `2.3`, `0.6`. Такое звено после имени
#: семьи — ДРУГАЯ ВЕРСИЯ, а не вариант: `veo-3` и `veo-3.1`, `latentsync` и
#: `latentsync-1.5` — разные модели, и в семью они друг другу не входят (И5).
_ГОЛАЯ_ВЕРСИЯ = re.compile(r"\d+(?:\.\d+)*")
_БУКВЫ_И_ВЕРСИЯ = re.compile(r"([a-z]+)(\d+(?:\.\d+)*)")
_РАЗДЕЛИТЕЛИ_ЗВЕНЬЕВ = re.compile(r"[\s\-_/]+")


def _без_площадки(low: str) -> str:
    """`fal-ai/bytedance/omnihuman/v1.5` -> `omnihuman/v1.5`. Только звенья пути."""
    if "/" not in low:
        return low
    куски = [к for к in low.strip("/").split("/") if к]
    while len(куски) > 1 and (куски[0] in ПЛОЩАДКИ_В_ПУТИ or куски[0] in ВЕНДОРЫ_В_ПУТИ):
        куски = куски[1:]
    return "/".join(куски)


def _заменить(звенья_: list[str], было: tuple[str, ...], стало: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(звенья_):
        if tuple(звенья_[i : i + len(было)]) == было:
            out.extend(стало)
            i += len(было)
        else:
            out.append(звенья_[i])
            i += 1
    return out


@lru_cache(maxsize=16384)
def tokens(name: str) -> tuple[str, ...]:
    """Имя -> звенья: `veo3.1-image-to-video` -> (`veo`, `3.1`, `i2v`).

    Звенья — то, по чему решается СЕМЬЯ (`family`, `parent`): `veo-3` и
    `veo-3.1` различаются звеном `3` против `3.1`, а не первыми знаками строки.
    Свёртка (`fold`) — это звенья, склеенные без точек.
    """
    low = " ".join(str(name or "").split()).strip().lower()
    low = _без_площадки(low)
    low = ПРИСТАВКА_ВЕРСИИ.sub("", low)
    # `flux.2-dev`: точка между буквой и цифрой — разделитель, как дефис.
    low = re.sub(r"(?<=[a-z])\.(?=\d)", "-", low)
    сырые = [з for з in _РАЗДЕЛИТЕЛИ_ЗВЕНЬЕВ.split(low) if з]
    звенья_: list[str] = []
    for з in сырые:
        склейка = _БУКВЫ_И_ВЕРСИЯ.fullmatch(з)
        части = [склейка.group(1), склейка.group(2)] if склейка else [з]
        for ч in части:
            # X.0 и X — одна версия: `kling-3.0` / `kling-3`, `seedance-2.0` /
            # `seedance2`, `imagen-4.0` / `imagen-4`. Хвостовые нули снимаются
            # только у ГОЛОГО номера: `2.05` и `1.0.1` не трогаются.
            if _ГОЛАЯ_ВЕРСИЯ.fullmatch(ч) and "." in ч:
                ч = re.sub(r"(?:\.0+)+$", "", ч)
            # `happyhorse_1_0`: ноль отдельным звеном после номера — та же `.0`.
            if re.fullmatch(r"0+", ч) and звенья_ and _ГОЛАЯ_ВЕРСИЯ.fullmatch(звенья_[-1]):
                continue
            звенья_.append(ч)
    for было, стало in СИНОНИМЫ_ЗВЕНЬЕВ:
        звенья_ = _заменить(звенья_, было, стало)
    for было, стало in ПЕРЕПИСИ_НАЧАЛА:
        if tuple(звенья_[: len(было)]) == было:
            звенья_ = list(стало) + звенья_[len(было) :]
            break
    for хвост in ХВОСТЫ_ВЫПУСКА:
        if len(звенья_) > len(хвост) and tuple(звенья_[-len(хвост) :]) == хвост:
            звенья_ = звенья_[: -len(хвост)]
    return tuple(звенья_)


def fold_tokens(звенья_: Sequence[str]) -> str:
    """Звенья -> свёртка. Таблица `ALIASES` применяется здесь, к склеенному."""
    голое = "".join(ch for ch in "".join(звенья_) if ch.isalnum() or ch in KEPT_SYMBOLS)
    return ALIASES.get(голое, голое)


#: Исходы разрешения имени. Ровно три, и третий не сворачивается во второй.
RESOLVED = "resolved"
NOT_IN_BASE = "not_in_base"
NO_NAME_ASKED = "no_name_asked"

#: КАК имя разрешилось — печатается в ноте, потому что разрешение «по
#: единственному соседу» — это вывод, а не совпадение, и спросивший обязан
#: это видеть (Е2).
HOW_EXACT = "exact"
#: Вендор впереди СПРОШЕННОГО имени, а без него имя в базе есть
#: (`bytedance-seedance-v1-pro-image-to-video` -> `seedance-1.0-pro-i2v`).
#: Правило детерминированное — то же, что у `group`.
HOW_VENDOR = "vendor_prefix"
#: Единственный сосед: у него вендор впереди, а у спрошенного нет
#: (`h3-max` -> `minimax-h3-max`). Это ВЫВОД, а не совпадение.
HOW_NEIGHBOUR = "unique_neighbour"
#: Единственный сосед — единственная версия (`happyhorse` -> `happyhorse_1_0`).
#: Тоже вывод.
HOW_ONLY_VERSION = "only_version"
#: Как разрешается выводом, а не тождеством: такой ответ — подсказка, а не факт.
HOW_INFERRED: frozenset[str] = frozenset({HOW_NEIGHBOUR, HOW_ONLY_VERSION})


def fold(name: str) -> str:
    """Написание -> то, что от имени остаётся, когда убрано оформление.

    Свёртка НАМЕРЕННО грубая, и вот на чём это проверено: на 466 именах живой
    базы она склеивает 9 групп, и все девять — одна модель под двумя
    написаниями. Ни одной пары РАЗНЫХ моделей она не склеила (негативный
    контроль в `studio/selfrag/tests/test_modelnames.py`: `flux-2-pro` против
    `flux-2-pro-edit`, `kling-3.0` против `kling-3.0-pro-i2v`, `eleven_v3`
    против `eleven_v3_conversational` обязаны остаться разными).

    УСИЛЕНО 2026-10-14 (аудит ae94057): `X.0` = `X` (`kling-3` / `kling-3.0`),
    синонимы режима (`i2v` = `image-to-video`), площадка и вендор впереди
    ПУТИ (`fal-ai/…`, `google/…`) и курируемые переписи `ПЕРЕПИСИ_НАЧАЛА`.
    Список новых склеек на живой базе — в шапке `scripts/merge_model_ids.py`.
    """
    return fold_tokens(tokens(str(name or "")))


def _без_вендора(звенья_: Sequence[str]) -> tuple[str, ...]:
    """Звенья без вендора впереди, если после него что-то осталось."""
    if len(звенья_) > 1 and звенья_[0] in ВЕНДОРЫ_В_ИМЕНИ:
        return tuple(звенья_[1:])
    return tuple(звенья_)


def strip_vendor(name: str) -> str:
    """Имя без вендора первым звеном (`bytedance-seedance-2.5` -> `seedance-2.5`).

    Возвращает ЗВЕНЬЯ через дефис; имя без вендора впереди — как было.
    """
    звенья_ = tokens(name)
    без = _без_вендора(звенья_)
    return "-".join(без) if без != tuple(звенья_) else str(name or "")


def _стержень(name: str) -> str:
    """Свёртка без вендора впереди; пусто, если вендора впереди нет."""
    звенья_ = tokens(name)
    без = _без_вендора(звенья_)
    if без == tuple(звенья_):
        return ""
    стержень = fold_tokens(без)
    return стержень if len(стержень) >= MIN_SHARED_PREFIX else ""


def group(known: Iterable[str]) -> dict[str, list[str]]:
    """Свёртка -> все написания базы, которые в неё попадают, по алфавиту.

    Вендор впереди имени (`bytedance-seedance-v1-pro-image-to-video`)
    снимается ТОЛЬКО если остаток уже стоит в базе отдельным именем
    (`seedance-1.0-pro-i2v`): это разрешение против списка, а не свёртка.
    """
    names = sorted({str(n) for n in known})
    ключи = {n: fold(n) for n in names}
    есть = set(ключи.values())
    out: dict[str, list[str]] = defaultdict(list)
    for name in names:
        ключ = ключи[name]
        стержень = _стержень(name)
        if стержень and стержень != ключ and стержень in есть:
            ключ = стержень
        out[ключ].append(name)
    return {key: sorted(set(spellings)) for key, spellings in out.items()}


def _первое_звено(name: str) -> str:
    без = _без_вендора(tokens(name))
    return без[0] if без else ""


def _вхождение_звеньями(малое: Sequence[str], большое: Sequence[str]) -> bool:
    """Звенья `малое` стоят подряд внутри `большое` (по границам звеньев)."""
    n = len(малое)
    if not n or n > len(большое):
        return False
    return any(tuple(большое[i : i + n]) == tuple(малое) for i in range(len(большое) - n + 1))


def similar(name: str, known: Iterable[str], *, limit: int = 8) -> list[str]:
    """Имена базы, близкие к спрошенному: общее начало, затем вхождение.

    Порядок значим: совпадения по началу точнее и идут первыми, иначе короткое
    общее имя вытеснило бы точного соседа. Сравнение идёт по СВЁРТКЕ — иначе
    порог общего начала съедали бы дефисы и точки.

    ШУМ СНЯТ 2026-10-14 (аудит ae94057). Общих четырёх знаков было мало:
    `seedvr2` подсказывал `seed_audio` (общее `seed`), `minimax-h3` —
    языковую модель `minimax-m2.7` (общее `minimax`). Теперь общее начало
    засчитывается, только если оно покрывает ПЕРВОЕ ЗВЕНО спрошенного после
    вендора (`seedvr` не покрыто `seed`, `h` не покрыто `m`), а вхождение —
    только целыми звеньями.
    """
    asked = fold(name)
    if len(asked) < MIN_SHARED_PREFIX:
        return []
    звенья_спрошенного = _без_вендора(tokens(name))
    первое = _первое_звено(name)
    hits: list[tuple[int, int, str]] = []
    сам = " ".join(str(name or "").split()).strip().lower()
    for candidate in sorted(set(known)):
        свёрнутый = fold(candidate)
        if свёрнутый == asked:
            # Сама модель под ТЕМ ЖЕ написанием — не сосед. Под ДРУГИМ (через
            # курируемую перепись: `h3-max` -> `minimax-h3-max`) — самый точный
            # сосед, и он идёт первым.
            if candidate.strip().lower() != сам:
                hits.append((-1, 0, candidate))
            continue
        shared = 0
        for a, b in zip(asked, свёрнутый):
            if a != b:
                break
            shared += 1
        звенья_кандидата = _без_вендора(tokens(candidate))
        # Общее начало засчитывается, если оно покрывает ПЕРВОЕ ЗВЕНО
        # спрошенного целиком: `omni-thing` -> `omnihuman-1` (звено `omni`
        # внутри `omnihuman`) — да; `seedvr2` -> `seed_audio` (звено
        # `seedvr` длиннее общего `seed`) — нет.
        # Короткое первое звено (`h` у `minimax-h3`) покрывает слишком много
        # (`hailuo`): короче порога оно обязано совпасть целиком.
        чужое_первое = _первое_звено(candidate)
        if (
            shared >= MIN_SHARED_PREFIX
            and первое
            and _первое_звено(candidate).startswith(первое)
            and (len(первое) >= MIN_SHARED_PREFIX or чужое_первое == первое)
        ):
            hits.append((0, -shared, candidate))
        elif (asked in свёрнутый or свёрнутый in asked) and (
            _вхождение_звеньями(звенья_спрошенного, tokens(candidate))
            or _вхождение_звеньями(звенья_кандидата, tokens(name))
            or _вхождение_звеньями(tokens(name), tokens(candidate))
        ):
            hits.append((1, -len(asked), candidate))
    return [c for _rank, _shared, c in sorted(hits)][:limit]


def family(name: str, known: Iterable[str]) -> list[str]:
    """Варианты семьи `name` в базе: `veo-3.1` -> `veo-3.1-lite`, `veo-3.1-i2v`…

    Вариант — имя, чьи звенья НАЧИНАЮТСЯ звеньями семьи (после вендора и после
    переписей), а следующее звено — НЕ голый номер версии. Поэтому `veo-3`
    не семья `veo-3.1` (звено `3` ≠ `3.1`), а `latentsync-1.5` не вариант
    `latentsync` (следующее звено — версия): это РАЗНЫЕ модели (И5).
    """
    ключ = fold(name)
    if len(ключ) < MIN_SHARED_PREFIX:
        return []
    out: list[str] = []
    for candidate in sorted(set(known)):
        if fold(candidate) == ключ:
            continue
        for звенья_ in {tokens(candidate), _без_вендора(tokens(candidate))}:
            if any(
                fold_tokens(звенья_[:k]) == ключ and not _ГОЛАЯ_ВЕРСИЯ.fullmatch(звенья_[k])
                for k in range(1, len(звенья_))
            ):
                out.append(candidate)
                break
    return out


def parent(name: str, known: Iterable[str]) -> list[str]:
    """Написания базы для СЕМЬИ, вариантом которой является `name`. Пусто — нет.

    Самая длинная семья побеждает: у `kling-3.0-turbo-standard-i2v` семья
    `kling-3.0`, а не `kling`. Звено-версия не отрезается: у `veo-3.1-lite`
    семья `veo-3.1`, и никогда `veo-3` (И5).
    """
    groups = group(known)
    for звенья_ in (tokens(name), _без_вендора(tokens(name))):
        for k in range(len(звенья_) - 1, 0, -1):
            if _ГОЛАЯ_ВЕРСИЯ.fullmatch(звенья_[k]):
                continue
            ключ = fold_tokens(звенья_[:k])
            if ключ != fold(name) and ключ in groups and len(ключ) >= MIN_SHARED_PREFIX:
                return list(groups[ключ])
    return []


#: КАКОЕ НАПИСАНИЕ КАНОНИЧЕСКОЕ, когда вендор высказался. Ключ — свёртка.
#: Для остальных групп каноническим считается написание с наибольшим числом
#: строк (при равенстве — первое по алфавиту): `canonical_spelling`.
ПРЕДПОЧТЕНИЕ: dict[str, str] = {
    # id API ElevenLabs, с подчёркиваниями — их же документация.
    "eleven3": "eleven_v3",
    "elevenmultilingual2": "eleven_multilingual_v2",
    # Как вендор пишет на своих страницах.
    "kling3": "kling-3.0",
    "seedance2": "seedance-2.0",
    "seedance25": "seedance-2.5",
    "veo31": "veo-3.1",
    "ltx23": "ltx-2.3",
    "imagen4": "imagen-4.0",
    "nanobanana2": "nano-banana-2",
    "nanobananapro": "nano-banana-pro",
    "minimaxh3i2v": "minimax-h3-i2v",
    "veo31i2v": "veo-3.1-i2v",
    "synclipsync2": "sync-lipsync-2",
    # Имя статьи и сайта ByteDance — без лаборатории впереди (arXiv 2508.19209).
    "omnihuman1": "omnihuman-1",
    "omnihuman15": "omnihuman-1.5",
    # id API ElevenLabs — `scribe_v2` (elevenlabs.io/docs/models).
    "scribe2": "scribe-v2",
    # BFL пишет FLUX.1 / FLUX.2 через точку на своих страницах.
    "flux2klein4b": "flux.2-klein-4b",
    "flux2klein9b": "flux.2-klein-9b",
    "flux1kontextpro": "flux.1-kontext-pro",
    "flux2dev": "flux.2-dev",
    "flux1dev": "flux.1-dev",
}


def canonical_spelling(names: Sequence[str], counts: dict[str, int] | None = None) -> str:
    """Одно написание группы, под которым писать новое. Детерминированно.

    Вендор высказался (`ПРЕДПОЧТЕНИЕ`) — его написание, даже если в базе его
    ещё нет. Иначе — написание с наибольшим числом строк, при равенстве первое
    по алфавиту: не выбор победителя, а отказ плодить новый карман.
    """
    if not names:
        return ""
    # Ключ группы — свёртка ЛЮБОГО её написания или его стержень без вендора:
    # `elevenlabs-scribe-v2` и `scribe-v2` в одной группе по стержню.
    for name in sorted(names):
        for ключ in (fold(name), _стержень(name)):
            if ключ in ПРЕДПОЧТЕНИЕ:
                return ПРЕДПОЧТЕНИЕ[ключ]
    счёт = counts or {}
    return sorted(names, key=lambda n: (-int(счёт.get(n, 0)), n))[0]


@dataclass(frozen=True)
class Resolution:
    """Чем кончилось разрешение имени. `names` — все карманы, а не один."""

    outcome: str
    reason: str
    asked: str
    canonical: str = ""
    names: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = ()
    note: str = ""
    #: Р2: неизмеримость печатается числами рядом с исходом.
    checked: int = 0
    unmeasured: int = 0
    spellings_seen: int = field(default=0)
    #: Как разрешилось: `exact` (свёртка), `vendor_prefix` (вендор впереди с
    #: одной из сторон), `only_version` (единственный сосед — версия). Пусто —
    #: не разрешилось.
    how: str = ""


def _единственный_сосед(
    asked: str, every: Sequence[str], groups: dict[str, list[str]]
) -> tuple[str, str]:
    """(ключ группы, как) для имени, которого нет в базе дословно; иначе пусто.

    Разрешается автоматически ТОЛЬКО когда сосед ровно один и отличается
    одним из двух способов, не меняющих модель:

    * вендор впереди: спросили `h3-max`, в базе `minimax-h3-max`;
    * единственная версия: спросили `happyhorse`, в базе только
      `happyhorse_1_0`.

    НЕГАТИВНЫЙ КОНТРОЛЬ (И5): `kling-3.0-turbo` НЕ разрешается в `kling-3.0`,
    хотя сосед один: лишнее звено `turbo` — другой вариант, а не оформление.
    """
    звенья_ = _без_вендора(tokens(asked))
    ключ = fold_tokens(звенья_)
    if ключ in groups:
        return ключ, HOW_VENDOR
    по_вендору = {k for k in groups for n in groups[k] if _стержень(n) == ключ}
    if len(по_вендору) == 1:
        return next(iter(по_вендору)), HOW_NEIGHBOUR
    по_версии = {
        k
        for k in groups
        for n in groups[k]
        if len(_без_вендора(tokens(n))) == len(звенья_) + 1
        and fold_tokens(_без_вендора(tokens(n))[:-1]) == ключ
        and _ГОЛАЯ_ВЕРСИЯ.fullmatch(_без_вендора(tokens(n))[-1])
    }
    if len(по_версии) == 1 and len(ключ) >= MIN_SHARED_PREFIX:
        return next(iter(по_версии)), HOW_ONLY_VERSION
    return "", ""


def resolve(
    name: str, known: Iterable[str], *, groups: dict[str, list[str]] | None = None
) -> Resolution:
    """Имя от спрашивающего -> написания базы, под которыми оно лежит.

    Три исхода:

    * `pass` + `resolved` — нашлось; `names` держит ВСЕ написания одной
      модели, а не то одно, которым спросили. `how` говорит, как.
    * `could not measure` + `not_in_base` — такого имени в базе нет; рядом
      идут похожие, чтобы «не знаем» не читалось как «не существует».
    * `could not measure` + `no_name_asked` — имени не назвали. Отдельный
      исход, потому что лечится он другим действием.
    """
    asked = " ".join(str(name or "").split()).strip()
    every = sorted(set(known))
    if not asked:
        return Resolution(
            outcome=UNMEASURED,
            reason=NO_NAME_ASKED,
            asked="",
            unmeasured=1,
            note="имя модели не названо, искать нечего",
        )

    groups = groups if groups is not None else group(every)
    ключ = fold(asked)
    how = HOW_EXACT
    if ключ not in groups:
        ключ, how = _единственный_сосед(asked, every, groups)
    names = tuple(groups.get(ключ, ())) if ключ else ()
    if not names:
        подсказки = tuple(similar(asked, every))
        хвост = f"; база держит близкие имена: {', '.join(подсказки)}" if подсказки else ""
        return Resolution(
            outcome=UNMEASURED,
            reason=NOT_IN_BASE,
            asked=asked,
            suggestions=подсказки,
            unmeasured=1,
            spellings_seen=len(every),
            note=(f"{asked!r} не найдено среди {len(every)} имён базы ни в одном написании{хвост}"),
        )

    # ВЫБРАНО: каноническим считается написание, которым спросили, если оно в
    # базе есть, иначе первое по алфавиту. Правило детерминированное и не
    # объявляет победителя среди написаний — этого свидетельства у нас нет
    # (см. шапку модуля), а объявить победителя без свидетельства значит
    # заморозить случайный выбор в ответе.
    canonical = asked if asked in names else names[0]
    как = {
        HOW_EXACT: "",
        HOW_VENDOR: " (разрешено по вендору впереди спрошенного имени)",
        HOW_NEIGHBOUR: " (разрешено АВТОМАТИЧЕСКИ: единственный сосед отличается только вендором впереди)",
        HOW_ONLY_VERSION: " (разрешено АВТОМАТИЧЕСКИ: в базе это единственная версия модели)",
    }[how]
    return Resolution(
        outcome=PASS,
        reason=RESOLVED,
        asked=asked,
        canonical=canonical,
        names=names,
        checked=len(names),
        spellings_seen=len(every),
        how=how,
        note=(
            f"{asked!r} разрешено в {canonical!r}{как}"
            + (
                f"; та же модель записана и как {', '.join(n for n in names if n != canonical)}"
                if len(names) > 1
                else ""
            )
        ),
    )


def collapsed(known: Iterable[str]) -> list[Sequence[str]]:
    """Группы, где одна модель живёт под несколькими написаниями."""
    return [names for _key, names in sorted(group(known).items()) if len(names) > 1]


def from_portal_id(identifier: str) -> str:
    """`fal-ai/sync-lipsync/v3` -> `sync-lipsync-v3`. Имя портала в форме базы.

    Префикс площадки на портале — не часть имени модели, а слэши — разделители
    пути. Чужой вендор в пути СОХРАНЯЕТСЯ: `veed/lipsync/v2` — это VEED, и
    выбросить его значит слить разных вендоров в одно имя.

    Живёт здесь, а не в скрипте опроса, по правилу Е1: разрешение имени — одно
    место на проект, и два канала, читающие один и тот же портал (опрос
    каталога и запись цен), обязаны получать из одного `id` одно имя. Разойтись
    им нельзя: разница между базой и порталом считается ПО ИМЕНИ, и два
    написания одного превратились бы в выдуманную работу.
    """
    путь = str(identifier or "").strip().strip("/")
    if not путь:
        return ""
    куски = путь.split("/")
    if куски and куски[0] in ("fal-ai", "fal"):
        куски = куски[1:]
    return "-".join(к for к in куски if к)
