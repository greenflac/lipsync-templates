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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from lipsync.fork_identity import PASS, UNMEASURED

__all__ = [
    "MIN_SHARED_PREFIX",
    "NOT_IN_BASE",
    "NO_NAME_ASKED",
    "RESOLVED",
    "Resolution",
    "fold",
    "group",
    "resolve",
    "similar",
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
}

#: Исходы разрешения имени. Ровно три, и третий не сворачивается во второй.
RESOLVED = "resolved"
NOT_IN_BASE = "not_in_base"
NO_NAME_ASKED = "no_name_asked"


def fold(name: str) -> str:
    """Написание -> то, что от имени остаётся, когда убрано оформление.

    Свёртка НАМЕРЕННО грубая, и вот на чём это проверено: на 466 именах живой
    базы она склеивает 9 групп, и все девять — одна модель под двумя
    написаниями. Ни одной пары РАЗНЫХ моделей она не склеила (негативный
    контроль в `studio/selfrag/tests/test_modelnames.py`: `flux-2-pro` против
    `flux-2-pro-edit`, `kling-3.0` против `kling-3.0-pro-i2v`, `eleven_v3`
    против `eleven_v3_conversational` обязаны остаться разными).
    """
    low = " ".join(str(name or "").split()).strip().lower()
    low = ПРИСТАВКА_ВЕРСИИ.sub("", low)
    голое = "".join(ch for ch in low if ch.isalnum() or ch in KEPT_SYMBOLS)
    # Таблица применяется ПОСЛЕ грубой свёртки и к её результату: иначе она
    # ловила бы только одно написание из многих (`InfiniTalk`, `infini-talk`).
    return ALIASES.get(голое, голое)


def group(known: Iterable[str]) -> dict[str, list[str]]:
    """Свёртка -> все написания базы, которые в неё попадают, по алфавиту."""
    out: dict[str, list[str]] = defaultdict(list)
    for name in known:
        out[fold(name)].append(name)
    return {key: sorted(set(names)) for key, names in out.items()}


def similar(name: str, known: Iterable[str], *, limit: int = 8) -> list[str]:
    """Имена базы, близкие к спрошенному: общее начало, затем вхождение.

    Порядок значим: совпадения по началу точнее и идут первыми, иначе короткое
    общее имя вытеснило бы точного соседа. Сравнение идёт по СВЁРТКЕ — иначе
    порог общего начала съедали бы дефисы и точки.
    """
    asked = fold(name)
    if len(asked) < MIN_SHARED_PREFIX:
        return []
    hits: list[tuple[int, int, str]] = []
    for candidate in sorted(set(known)):
        свёрнутый = fold(candidate)
        if свёрнутый == asked:
            continue
        shared = 0
        for a, b in zip(asked, свёрнутый):
            if a != b:
                break
            shared += 1
        if shared >= MIN_SHARED_PREFIX:
            hits.append((0, -shared, candidate))
        elif asked in свёрнутый or свёрнутый in asked:
            hits.append((1, -len(asked), candidate))
    return [c for _rank, _shared, c in sorted(hits)][:limit]


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


def resolve(name: str, known: Iterable[str]) -> Resolution:
    """Имя от спрашивающего -> написания базы, под которыми оно лежит.

    Три исхода:

    * `pass` + `resolved` — нашлось; `names` держит ВСЕ написания одной
      модели, а не то одно, которым спросили.
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

    groups = group(every)
    names = tuple(groups.get(fold(asked), ()))
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
    return Resolution(
        outcome=PASS,
        reason=RESOLVED,
        asked=asked,
        canonical=canonical,
        names=names,
        checked=len(names),
        spellings_seen=len(every),
        note=(
            f"{asked!r} разрешено в {canonical!r}"
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
