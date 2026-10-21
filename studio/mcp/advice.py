"""Answer "can this model do that", and let the web refresh the answer.

WHAT THIS ADDS TO WHAT ALREADY EXISTED

`registry.py` holds one conservative answer per attribute, because a prompt
assembler needs one number. `facts.py` holds every answer anybody gave, with
its tier and its date, and reports `fail` when they disagree instead of
voting. Neither is reachable from a conversation, and neither can be updated
without a commit. This module joins them into one answer and opens the one
door that lets the base grow: `record`.

THE REFRESH PATH, AND THE MEASUREMENT THAT FORCED IT

This process cannot fetch the web. MEASURED 2026-08-27 on this machine:
`docs.bfl.ai`, `arxiv.org` and `kling.ai` all answer CONNECT 403 through the
egress proxy, and going around a policy-closed host is forbidden (Ц3). What is
NOT refused is the assistant's own search tool, in the conversation where the
owner is already standing.

So the refresh is a two-step the assistant performs in the open: search the
web, then call `record_model_fact` (this module's `record`) with the value,
the URL, the tier and the date the source stated it. Nothing is written without those four. A claim with no URL
cannot be checked later, and a claim with no date cannot go stale — and a
claim that cannot go stale is the one that quietly rots.

WHAT THIS REFUSES TO DO

It never resolves a contradiction. When two sources disagree the answer is
`fail` with both sides shown, because the flattening is the bug: asked how
long one Kling 3.0 generation runs, the sources say 15s and 10s and "3
minutes", and a third-party summary of those same sources confidently reported
"up to 5 minutes", which matches none of them.

It never promotes a claim by repetition. Ten blogs quoting each other are one
source, and `facts.py` enforces that; this module only reports it.
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio import l10n
from studio import lifecycle as _lifecycle
from studio.mcp import fetch, probe
from studio.selfrag import attrfamily, modelnames, registry, source_hosts
from studio.selfrag.facts import (
    DEFAULT_FACTS_PATH,
    STALE_AFTER_DAYS,
    TIERS,
    TIER_BENCHMARK,
    TIER_BLOG,
    TIER_OPERATOR,
    TIER_PAPER,
    TIER_PORTAL,
    TIER_PROBE,
    TIER_VENDOR,
    Fact,
    FactStore,
    claim_key,
    load_facts,
)

__all__ = [
    "advise",
    "brief",
    "claims_found",
    "gap_reason",
    "REASONS",
    "record",
    "withdraw",
    "stale",
    "TIERS",
    "IDENTITY_TIERS",
    "MUTABLE_FIELDS",
    "store_for",
]

#: The rungs decided by whose page it is, and therefore never taken on trust
#: from a caller. Everything else in `TIERS` describes how the fact was
#: obtained, which the URL cannot know.
#: CHOSEN. How many class-level findings ride along with a model's answer.
#: 170 of them stand after the 2026-08-27 verification pass; a caller reading
#: an answer needs the strongest few and the count of the rest, not all of
#: them. Not measured — measure it when somebody reports the answer is thin.
CLASS_FINDINGS_SHOWN = 12

#: ПОЧЕМУ ответ такой, машиночитаемо и рядом с нотой.
#:
#: Заведено 2026-09-02, потому что три РАЗНЫХ положения дел печатались одним
#: исходом `could not measure` и одинаково читались: имени нет в базе вовсе;
#: имя набрано с опечаткой, а база держит соседнее; модель база знает, а
#: спрошенного атрибута про неё никто не записывал. Пользователь получал
#: «не смогли» и не мог понять, искать ли источник, переспросить ли другим
#: именем или спросить другой атрибут. Нота это иногда объясняла словами;
#: слова нельзя ни сгруппировать, ни сосчитать.
REASON_NO_MODEL_NAMED = "no_model_named"
REASON_MODEL_UNKNOWN = "model_unknown"
REASON_NAME_MAYBE_MISTYPED = "name_maybe_mistyped"
REASON_NOTHING_RECORDED = "nothing_recorded"
REASON_ATTRIBUTE_UNKNOWN = "attribute_unknown"
REASON_SOURCES_BLOG_ONLY = "sources_blog_only"
REASON_SOURCES_DISAGREE = "sources_disagree"
REASON_MODEL_UNUSABLE = "model_unusable"
REASON_ANSWERED = "answered"
#: Ответ есть, но на часть атрибутов источники расходятся (аудит ae94057,
#: 2026-10-14). До этого ОДИН спорный атрибут делал `fail` всему ответу, и
#: заголовок шёл обратно знанию: kling-3.0, veo-3.1, seedance-2.0 — `fail`,
#: малоизвестные модели — `pass`. Спор не прячется: он в `contested` и в ноте.
REASON_ANSWERED_SOME_CONTESTED = "answered_some_contested"
#: У самой модели ничего не записано, ответ — с уровня СЕМЬИ (`veo-3.1` для
#: `veo-3.1-lite`) или её вариантов (`seedvr2-7b` для `seedvr2`). Каждое
#: утверждение помечено, о каком имени оно (`about`, `scope`).
REASON_ANSWERED_BY_FAMILY = "answered_by_family"
#: Имени в базе нет, но оно — известная семья плюс слово-ступень линейки
#: (`veo-3.1-fast`: семья `veo-3.1` + `fast`). Валидатор G5/G9, 2026-10-14:
#: такой вопрос получал `name_maybe_mistyped`, то есть «вы опечатались», хотя
#: спросили о настоящем варианте, о котором просто не записано ничего. Исход
#: `could not measure`: утверждения семьи едут КОНТЕКСТОМ, с пометкой.
REASON_VARIANT_NOT_RECORDED = "variant_not_recorded"
#: Имени в базе нет, но есть ДРУГИЕ ВЕРСИИ той же линейки (`seedream-4.5` при
#: `seedream-4.0`). Другая версия — не та же модель (И5): соседи едут списком
#: `other_versions`, а не подсказкой «спросите этим именем».
REASON_VERSION_NOT_RECORDED = "version_not_recorded"
#: Имя длиннее `modelnames.MAX_NAME_LENGTH` — это не имя модели (G11): ответ
#: не эхает его и ничего не ищет. Исход `fail`, как у `stale(days=-5)`.
REASON_NAME_TOO_LONG = "name_too_long"

#: Весь словарь причин. Список — не украшение: он делает состав причин
#: проверяемым тестом, а не памятью читающего.
REASONS: tuple[str, ...] = (
    REASON_NO_MODEL_NAMED,
    REASON_MODEL_UNKNOWN,
    REASON_NAME_MAYBE_MISTYPED,
    REASON_NOTHING_RECORDED,
    REASON_ATTRIBUTE_UNKNOWN,
    REASON_SOURCES_BLOG_ONLY,
    REASON_SOURCES_DISAGREE,
    REASON_MODEL_UNUSABLE,
    REASON_ANSWERED,
    REASON_ANSWERED_SOME_CONTESTED,
    REASON_ANSWERED_BY_FAMILY,
    REASON_VARIANT_NOT_RECORDED,
    REASON_VERSION_NOT_RECORDED,
    REASON_NAME_TOO_LONG,
)


def sources_behind(claims: object) -> int:
    """Сколько РАЗНЫХ страниц стоит за ответом — не сколько строк.

    `claims_found` считает НАЙДЕННЫЕ УТВЕРЖДЕНИЯ, и это правильное число для
    вердикта «есть ли чем ответить». Но в ноте оно стояло со словом
    «source(s)», и восемь атрибутов с одной страницы читались как восемь
    источников: `advise("minimax-h3-max")` печатал «8 attribute(s) answered
    from 8 recorded source(s)», хотя страница была ОДНА (ИЗМЕРЕНО 2026-09-03).

    Счёт по строкам обещает подтверждение, которого никто не давал. Здесь —
    по адресам, и оба числа печатаются рядом, потому что отвечают на разные
    вопросы: «сколько записано» и «сколькими независимыми страницами».
    """
    if not isinstance(claims, dict):
        return 0
    адреса: set[str] = set()
    for verdict in claims.values():
        if not isinstance(verdict, dict):
            continue
        for строка in verdict.get("claims") or []:
            for источник in (строка or {}).get("sources") or []:
                адреса.add(str((источник or {}).get("url") or ""))
    return len(адреса)


def claims_found(claims: object) -> int:
    """Сколько записанных источников стоит за этими утверждениями.

    ОДНО место, где считается «сколько нашлось» (правило Е1): отсюда это берёт
    и вердикт `advise`, и журнал вопросов через `misses.evidence`. Пока число
    считали порознь, вердикт мог сказать «нечем ответить» о том же ответе, в
    котором журнал видел свидетельство, — и именно это расхождение стоило
    пяти сессий сбора (ИЗМЕРЕНО 2026-09-02 на живой базе: 999 пар
    «модель.атрибут» из 1236 имели утверждение с исходом `pass` и получали от
    `advise` исход `could not measure`).

    Считается `checked` каждого утверждения — число НАЙДЕННЫХ источников, а не
    число опрошенных атрибутов: `advise("flux-2", "выдуманный-атрибут")`
    возвращает `checked 2` при нуле найденного.
    """
    if not isinstance(claims, dict):
        return 0
    found = 0
    for verdict in claims.values():
        if isinstance(verdict, dict):
            found += int(verdict.get("checked") or 0)
    return found


def gap_reason(claims: object) -> str:
    """Почему на вопрос нечем ответить: не записано ничего или всё на нижней ступени.

    Развилка вынесена функцией (правило Т5): от неё зависит, что пользователь
    сделает дальше — пойдёт искать источник вообще или пойдёт искать источник
    ПОКРЕПЧЕ блога, а это разная работа.
    """
    return REASON_SOURCES_BLOG_ONLY if claims_found(claims) else REASON_ATTRIBUTE_UNKNOWN


IDENTITY_TIERS: tuple[str, ...] = (TIER_VENDOR, TIER_PORTAL, TIER_BLOG)

#: НЕ-ОТВЕТЫ: слова, которыми говорят «я не знаю», записанные в поле значения.
#:
#: ВОСПРОИЗВЕДЕНО 2026-09-07 (И2). `record("kling-3.0", "max_seconds",
#: "не знаю", …)` возвращал `pass` и дописывал строку в базу. Семь таких
#: значений подряд прошли без единого возражения: «не знаю», «unknown», «N/A»,
#: «—», «не указано», «TBD», «?».
#:
#: ЧЕМ ЭТО ПЛОХО, ИЗМЕРЕНО ТАМ ЖЕ. Одна такая строка рядом с настоящим фактом
#: переводит утверждение из `pass` в `fail`: «источники расходятся на
#: kling-3.0.max_seconds: '10 s' (probe); 'не знаю' (blog)». То есть незнание,
#: записанное как факт, не просто занимает место — оно ОТМЕНЯЕТ измеренное.
#: Это ровно то, против чего написан весь пакет: у проекта есть третий исход,
#: чтобы говорить «не знаю» исходом, а не значением.
#:
#: СРАВНЕНИЕ ЦЕЛЫМ ЗНАЧЕНИЕМ, А НЕ ПОДСТРОКОЙ, И СПИСОК ЗАКРЫТ. Здесь ложный
#: отказ дороже пропуска: пропущенную строку поймает читатель базы, а
#: отвергнутый настоящий факт не запишет никто и никогда — он просто не
#: попадёт. Подстрочное сравнение отвергло бы «unknown artifacts at 8 s» и
#: «N/A regions», то есть настоящие наблюдения. Поэтому: приводим к нижнему
#: регистру, снимаем края из пробелов и знаков — и сверяем ЦЕЛИКОМ.
#:
#: ВЫБРАНО (И4): списком названы обороты, которыми не-ответ записывают
#: по-русски и по-английски. Числа за ним нет: это не порог, а перечень.
#:
#: ТРИ СЛОВА УБИРАЛИСЬ ОТСЮДА И ВЕРНУЛИСЬ В ТОТ ЖЕ ДЕНЬ — ЗАПИСЬ ОБ ОШИБКЕ.
#: 2026-09-07 первая приёмка сочла `none`, `null` и `na` ложными отказами:
#: «none» отвечает на `requires_inputs`, `NA` — код региона. Я согласился и
#: убрал их. ВТОРАЯ ПРИЁМКА ПОКАЗАЛА, ЧТО ОСНОВАНИЕ БЫЛО НЕВЕРНЫМ: дверь
#: сравнивает значение ЦЕЛИКОМ, и прогон старой версии это подтвердил —
#:
#:     'none — no prompt upsampling on klein'  -> прошло
#:     'none required'                         -> прошло
#:     'N/A regions'                           -> прошло
#:     'none' / 'None' / 'null' / 'NA'         -> отказ
#:
#: — то есть ни одному настоящему значению дверь не мешала, а голых в базе
#: НОЛЬ строк из 2127. Ложного отказа, ради которого её открыли, не случалось
#: ни разу; заплачено за это тем, что `str(None)` и JSON `null`, приведённые к
#: строке, стали записываться как факты. Слова возвращены.
#:
#: ЧТОБЫ ОТКАЗ НЕ СТАЛ ЛОВУШКОЙ, у него есть выход, и он назван в ноте: если
#: «none» — это НАСТОЯЩИЙ ответ («ограничений нет»), его надо написать словами
#: («none — no restrictions»), и такая строка проходит.
#: ПОЧЕМУ РЯДОМ ЖИВЁТ ВТОРОЙ ПОХОЖИЙ СПИСОК И ЭТО НЕ ДУБЛЬ ПО Е1.
#: `studio/selfrag/facts.ПУСТЫЕ_ЗНАЧЕНИЯ` («other», «unknown», «n/a», «none»,
#: «-») отвечает на ДРУГОЙ вопрос: какие значения не считать голосом при
#: сверке источников между собой. Признак настоящего дубля — «изменишь одно,
#: обязано измениться второе» — здесь не выполняется: `license = 'other'`
#: (8 живых строк, это категория лицензии HuggingFace) записывать МОЖНО, а
#: голосом при сверке она не является.
НЕ_ОТВЕТЫ: frozenset[str] = frozenset(
    {
        "не знаю",
        "неизвестно",
        "не указано",
        "не записано",
        "нет данных",
        "unknown",
        "not known",
        "no data",
        "not specified",
        "unspecified",
        "n/a",
        "na",
        "none",
        "null",
        "tbd",
        "tba",
        "?",
    }
)

#: Знаки, которыми не сказано ничего: значение из них одних — тоже не-ответ.
_ПУСТЫЕ_ЗНАКИ = " \t-–—_.,;:!?*«»\"'()[]"


def не_ответ(value: str) -> str:
    """Значение говорит «не знаю»? Возвращает приведённую форму или пустую строку.

    Развилка вынесена функцией (Т5): её проверяют тестом отдельно от `record`,
    и ложный отказ на настоящем значении виден сразу.
    """
    приведено = " ".join(str(value or "").lower().split()).strip(_ПУСТЫЕ_ЗНАКИ)
    if not приведено:
        return "значение из одних знаков препинания"
    return приведено if приведено in НЕ_ОТВЕТЫ else ""


#: ПЛОЩАДКИ, ГДЕ АДРЕС САМ ГОВОРИТ «ЭТО СТАТЬЯ». Сверяется по РЕГИСТРИРУЕМОМУ
#: ДОМЕНУ, а не по подстроке: подстрочное сравнение принимало
#: `blog.example.com/why-openreview.net-is-broken` за статью с OpenReview.
#:
#: Список ВЫБРАН (И4): полного перечня научных площадок не существует, здесь
#: названы те, где публикуются работы этой области. Не нашлось площадки —
#: остаются DOI и идентификатор arxiv ниже, они площадку не спрашивают.
ПЛОЩАДКИ_СТАТЕЙ: frozenset[str] = frozenset(
    {
        "arxiv.org",
        "openreview.net",
        "aclanthology.org",
        "acm.org",
        "ieee.org",
        "thecvf.com",
        "springer.com",
        "mlr.press",
        "nips.cc",
        "neurips.cc",
        "jmlr.org",
        "biorxiv.org",
        "medrxiv.org",
        "doi.org",
        "sciencedirect.com",
        "nature.com",
        "aaai.org",
        "usenix.org",
        "ecva.net",
        "semanticscholar.org",
        "jstor.org",
        "nih.gov",
    }
)

#: ЗЕРКАЛА, где статья лежит под своим идентификатором, а сама площадка — не
#: научная. ИЗМЕРЕНО: 9 живых строк тира `paper` лежат на huggingface.co, все
#: с идентификатором arxiv в пути.
ЗЕРКАЛА_СТАТЕЙ: frozenset[str] = frozenset({"huggingface.co"})

#: DOI где угодно в адресе: `dl.acm.org/doi/10.1145/…`, `biorxiv.org/content/10.1101/…`.
_DOI = re.compile(r"\b10\.\d{4,9}/", re.I)

#: Идентификатор arxiv ЦЕЛЫМ сегментом пути или именем файла, с осмысленным
#: месяцем: `…/2412/2412.09262.md` на зеркале HuggingChat — статья, а
#: `…/build-9912.34567/` — нет. Раньше сравнение шло по любому вхождению
#: `NNNN.NNNNN` в адрес.
_ARXIV = re.compile(
    r"(?:^|/)\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}(?:v\d+)?(?:\.[a-z]+)?(?:$|[/?#])", re.I
)


def признак_статьи(url: str) -> bool:
    """Есть ли в САМОМ адресе то, по чему статью можно перепроверить.

    ЗАЧЕМ. Ступени-МЕТОДЫ (`probe`, `operator`, `paper`, `benchmark`) берутся на
    слово: никакой адрес не докажет, что у утверждения есть проверяемый метод.
    Независимая проверка каналов 2026-09-05 показала, чем это кончается: три
    строки на `probe` оказались чужим тредом обсуждения. Для `probe` дыра
    закрыта в тот же день; здесь она закрыта для `paper`, у которого признак в
    адресе ЕСТЬ — статья почти всегда несёт свой идентификатор.

    ЧТО БЫЛО НЕ ТАК С ПЕРВОЙ ВЕРСИЕЙ (найдено независимой проверкой 2026-09-06,
    она же назвала обе стороны):

    СЛИШКОМ СТРОГО — отвергались NeurIPS, `dl.acm.org/doi/…`, IEEE, CVF,
    Springer, MLR, bioRxiv и старый формат arxiv (`arxiv.org/abs/cs/0501001`).
    Отказ по этим адресам — это отказ записать настоящую статью.

    СЛИШКОМ СЛАБО — принимался ЛЮБОЙ `.pdf` (в том числе рекламная презентация
    вендора), любой сегмент пути вида `NNNN.NNNNN` и любой адрес, где
    `openreview.net` встречается ПОДСТРОКОЙ, включая чужой блог про OpenReview.

    ИЗМЕРЕНО на живой базе 2026-09-06: строк тира `paper` 184, признак несут
    183 — те же, что и раньше (174 arxiv, 9 зеркал HuggingChat). Одна не несёт:
    репозиторий кода к статье (`github.com/Vchitect/RAPO`), и это ровно тот
    случай, ради которого проверка написана.
    """
    адрес = str(url or "").strip()
    домен = source_hosts.registrable(source_hosts.host_of(адрес))
    if домен in ПЛОЩАДКИ_СТАТЕЙ:
        return True
    # ТОЛЬКО ПУТЬ, БЕЗ СТРОКИ ЗАПРОСА И ЯКОРЯ. Независимая проверка 2026-09-06:
    # `blog.example.com/why-video-models-fail?ref=10.1145/3592433` проходил как
    # статья — чужой хост нёс признак в ЗАПРОСЕ. Форма дефекта одна и та же,
    # что и у `openreview.net` подстрокой, и чинится она по форме (И7).
    путь = адрес.split("://", 1)[-1].split("?")[0].split("#")[0]
    if _DOI.search(путь):
        return True
    # Идентификатор arxiv в пути — признак ТОЛЬКО на площадке или её зеркале:
    # `vendor.example/pricing/2401.12345/` статьёй не является.
    return домен in ЗЕРКАЛА_СТАТЕЙ and bool(_ARXIV.search(путь))


# The ladder is IMPORTED, never restated. It was restated here until
# 2026-08-27, and the copy went stale the moment `probe` was added to the real
# one: `record` refused the tier its own module had just introduced, saying it
# "is not one of vendor, benchmark, paper, blog". Two lists of the same thing
# are one list and one bug waiting.


#: Прочитанная база, ключ — файл И ЕГО СОСТОЯНИЕ. Не срок жизни и не флаг:
#: кэш, который может отстать от файла, ломает обещание «`record` виден сразу»,
#: и отладка такого расхождения дороже всего, что кэш сэкономил.
#:
#: ЗАЧЕМ. ИЗМЕРЕНО 2026-09-02: `scripts/check_headline.py` задаёт 1182 вопроса
#: и на каждый перечитывает файл в 1833 строки — 43 секунды при 85 у всей
#: сборки. Продукту это стоит того же: `plan_pipeline` спрашивает базу по разу
#: на кандидата.
_ПРОЧИТАННОЕ: dict[tuple[str, int, int], FactStore] = {}


def store_for(path: Path | None = None) -> FactStore:
    """A fact store read fresh from disk, so a `record` is visible immediately.

    Кэшируется по (путь, время изменения в наносекундах, размер). Файл
    изменился хоть на байт — ключ другой, и база читается заново; поэтому
    «свежесть» здесь не обещание, а следствие ключа. Файла нет — читаем как
    прежде, без кэша: у отсутствующего файла нет состояния, по которому его
    можно отличить от появившегося.
    """
    файл = Path(path or DEFAULT_FACTS_PATH)
    try:
        снимок = файл.stat()
    except OSError:
        return FactStore(load_facts(файл))
    ключ = ключ_снимка(файл, снимок)
    готовое = _ПРОЧИТАННОЕ.get(ключ)
    if готовое is None:
        готовое = FactStore(load_facts(файл))
        # Один ключ на файл: держать историю состояний незачем, а память за
        # длинный прогон она съедает (1833 строки на снимок).
        for прежний in [к for к in _ПРОЧИТАННОЕ if к[0] == str(файл)]:
            _ПРОЧИТАННОЕ.pop(прежний, None)
        _ПРОЧИТАННОЕ[ключ] = готовое
    return готовое


def snapshot_size(снимок: Any) -> int:
    """Размер из `stat`. Отдельной функцией, чтобы подменяться в тесте (Т5)."""
    return int(снимок.st_size)


def ключ_снимка(файл: Path, снимок: Any) -> tuple[str, int, int]:
    """Ключ кэша: путь, время изменения в наносекундах И РАЗМЕР.

    Вынесено отдельной функцией (Т5), потому что размер в ключе иначе
    недостижим тестом: любая настоящая правка файла сдвигает и время, так что
    ключ различался бы и без размера, и мутант «время без размера» проходил
    молча. Здесь его видно.

    Размер нужен на файловых системах, округляющих время: две правки в один
    такт часов дали бы один ключ и ответ по прежней базе.
    """
    return (str(файл), int(снимок.st_mtime_ns), snapshot_size(снимок))


def _spread_by_attribute(facts: list[Fact]) -> list[Fact]:
    """Round-robin across attributes, keeping each attribute's own order.

    Sorting by tier alone hands the caller twelve `metric_blind_spot` rows and
    no failure mode, every time, for every model — OBSERVED 2026-08-27: the
    first twelve of 170 came back as one tier and two attributes, so the cap
    was choosing by alphabet rather than by usefulness. Taking one of each in
    turn means the twelve that are shown cover what there is.
    """
    buckets: dict[str, list[Fact]] = {}
    for fact in facts:
        buckets.setdefault(fact.attribute, []).append(fact)
    out: list[Fact] = []
    while buckets:
        for attribute in list(buckets):
            out.append(buckets[attribute].pop(0))
            if not buckets[attribute]:
                del buckets[attribute]
    return out


#: Card field -> the fact-base attribute that answers the same question. Only
#: fields a harvested claim can actually contradict; a skeleton or a parameter
#: map has no counterpart in the base and is not compared.
CARD_MIRRORS: tuple[tuple[str, str], ...] = (
    ("max_seconds", "max_seconds"),
    ("fps", "fps"),
    ("resolutions", "max_resolution"),
    ("aspect_ratios", "aspect_ratio"),
    ("audio", "audio"),
)


def _says_the_same(card_value: object, recorded: str) -> bool:
    """Does a recorded claim carry what the card states?

    Numbers first, because a card holds `8.0` and a harvest holds `"8"`, and a
    substring test calls those two a contradiction — OBSERVED the moment this
    check was first run, on veo-3.1.max_seconds, where card and base agree.
    A boolean card field is matched the same way rather than by its repr.
    """
    text = str(recorded).strip().lower()
    try:
        return float(str(card_value)) == float(text)
    except (TypeError, ValueError):
        pass
    if isinstance(card_value, bool):
        return text in (("true", "yes") if card_value else ("false", "no"))
    needle = str(card_value).strip().lower()
    return bool(needle) and needle in text


def _card_vs_base(card: object, store: FactStore, name: str) -> list[dict]:
    """Where the registry card and the recorded claims tell different stories.

    THE DEFECT THIS EXISTS FOR, found by a blind evaluation on 2026-08-27.
    Asked whether sora-2 could be used as a reference arm, the card answered
    that its "duration, resolution and fps limits could not be sourced at
    all" — `max_seconds=None`, `resolutions=()` — while the claims layer of
    the SAME answer held `max_seconds` 20 and `max_resolution` 1280x720 /
    720x1280, both read off OpenAI's own page. A caller who reads the card
    first, which is what a card is for, walks away believing nothing is known.

    Two shapes are reported and they are not the same complaint:

    * `card is silent`  — the card says unknown and the base knows. The card
      is behind; nothing is wrong, but the caller must not be told "unknown".
    * `card contradicts` — the card asserts a value and the base's sources say
      another. That is a real disagreement and it is NEVER resolved here.

    Reported, never merged. The card is one conservative answer for a prompt
    assembler and the base is every answer anybody gave; making one overwrite
    the other silently is how the assembler starts lying with confidence.
    """
    if card is None:
        return []
    out: list[dict] = []
    for field_name, attribute in CARD_MIRRORS:
        stated = getattr(card, field_name, None)
        verdict = store.claims(name, attribute)
        if verdict["outcome"] != PASS:
            continue
        values = verdict.get("values") or []
        empty = stated is None or stated == () or stated == ""
        if empty:
            out.append(
                {
                    "field": field_name,
                    "attribute": attribute,
                    "shape": "card is silent",
                    "card": stated,
                    "base": values,
                    "note": (
                        f"the card leaves {field_name} unset while the base holds "
                        f"{len(values)} recorded value(s). The card is behind the base."
                    ),
                }
            )
            continue
        wanted = stated if isinstance(stated, tuple) else (stated,)
        if any(_says_the_same(one, v) for one in wanted for v in values):
            continue
        out.append(
            {
                "field": field_name,
                "attribute": attribute,
                "shape": "card contradicts",
                "card": stated,
                "base": values,
                "note": (
                    f"the card states {field_name}={stated!r} and no recorded source says "
                    "so. Neither is corrected here; both are shown."
                ),
            }
        )
    return out


def _card_as_dict(card: object) -> dict | None:
    """Карточка реестра в виде обычного словаря. `None` остаётся `None`.

    Кортежи разворачиваются в списки: JSON кортежей не знает, а разница между
    «поле пустое» и «поля нет» здесь значащая, поэтому пустое поле остаётся
    пустым списком, а не исчезает.
    """
    if card is None:
        return None
    if isinstance(card, dict):
        return card
    if not dataclasses.is_dataclass(card) or isinstance(card, type):
        return {"repr": str(card)}
    готово: dict = {}
    for поле in dataclasses.fields(card):
        значение = getattr(card, поле.name)
        готово[поле.name] = list(значение) if isinstance(значение, tuple) else значение
    return готово


def advise(model: str, attribute: str = "", *, path: Path | None = None) -> dict:
    """What is known about one model, and how much of it is worth believing.

    Тонкая обёртка над `_advise`: имя, найденное ВЫВОДОМ по единственному
    соседу (`h3-max` -> `minimax-h3-max`, `happyhorse` -> `happyhorse_1_0`),
    отдаёт ответ о соседе, но исходом `could not measure` (см. `_по_соседу`).
    """
    return _по_соседу(_advise(model, attribute, path=path))


def _по_соседу(ответ: dict) -> dict:
    """Ответ по соседу — подсказка, а не факт. Развилка вынесена (Т5).

    Голден-задача g15, решение владельца: «Какая лицензия у h3-max?» —
    «двигаться подсказкой можно, фактом — нет». Аудит ae94057 просил
    разрешать единственного соседа автоматически и говорить об этом. Оба
    требования выполняются вместе: данные соседа возвращаются целиком
    (`claims`, `resolved_as`), а заголовок не утверждает их о спрошенном имени.
    """
    как = str((ответ.get("resolved_as") or {}).get("how") or "")
    if как not in modelnames.HOW_INFERRED or ответ.get("outcome") == UNMEASURED:
        return ответ
    сосед = str((ответ.get("resolved_as") or {}).get("spellings", [""])[0] or "")
    спрошено = str((ответ.get("resolved_as") or {}).get("asked") or "")
    out = dict(ответ)
    out["outcome"] = UNMEASURED
    out["reason"] = REASON_NAME_MAYBE_MISTYPED
    out["unmeasured"] = max(1, int(ответ.get("unmeasured") or 0))
    out["near"] = [сосед] if сосед else []
    out["inferred_answer_outcome"] = ответ.get("outcome")
    out["note"] = (
        f"ИМЯ ВЫВЕДЕНО ПО СОСЕДУ: {спрошено!r} в базе нет, единственный сосед — "
        f"{сосед!r}. Ниже — ответ О {сосед!r} (его исход был "
        f"{ответ.get('outcome')!r}), но это ПОДСКАЗКА, а не факт о {спрошено!r}: "
        f"если это та же модель, спросите по {сосед!r}. " + str(ответ.get("note") or "")
    )
    return out


def _advise(model: str, attribute: str = "", *, path: Path | None = None) -> dict:
    """What is known about one model, and how much of it is worth believing.

    :param attribute: one attribute to focus on (`max_seconds`, `resolution`,
        ...). Empty means "everything recorded about this model".
    :returns: the house judging dict plus `availability` (the registry's
        conservative answer), `claims` (every recorded value with its source),
        `failure_modes` (known ways it breaks, each with its fix) and
        `contested` (the attributes whose sources disagree).

    Three outcomes, and the middle one is the point: an unknown model is
    `could not measure`, never `fail`. Not knowing is a gap in this base, not
    a defect in the model, and the two must never print the same.
    """
    name = str(model or "").strip()
    if not name:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "reason": REASON_NO_MODEL_NAMED,
            "note": "no model was named, so nothing was looked up",
            "availability": None,
            "claims": {},
            "failure_modes": [],
            "class_findings": [],
            "contested": [],
        }

    if len(name) > modelnames.MAX_NAME_LENGTH:
        return {
            "outcome": FAIL,
            "checked": 0,
            "violations": 1,
            "unmeasured": 0,
            "reason": REASON_NAME_TOO_LONG,
            "note": (
                f"a model name of {len(name)} characters is not a model name (limit "
                f"{modelnames.MAX_NAME_LENGTH}); nothing was looked up. Starts with "
                f"{name[:40]!r}."
            ),
            "availability": None,
            "claims": {},
            "failure_modes": [],
            "class_findings": [],
            "contested": [],
        }

    store = store_for(path)
    live = registry.availability(name)
    # Разрешение имени — одно на весь проект (`studio/selfrag/modelnames.py`),
    # и здесь оно спрашивается, а не повторяется. До 2026-09-02 эта строка
    # сравнивала сырое написание с сырым: `flux-2-klein-9b` и
    # `flux.2-klein-9b` — одна модель в двух карманах, и спросивший первым
    # получал 2 атрибута из 6 при исходе `pass`.
    resolution = store.resolve(name)

    # КАРТОЧКА РЕЕСТРА И БАЗА ФАКТОВ ОБЯЗАНЫ ГОВОРИТЬ ОБ ОДНОЙ МОДЕЛИ (аудит
    # ae94057, 2026-10-14). Псевдоним реестра доходил до карточки, но не до
    # базы: `advise("kling-3")` отвечал `nothing_recorded` при 12 атрибутах
    # `kling-3.0`, а `advise("veo-3")` показывал карточку veo-3.1 над фактами
    # veo-3 — две РАЗНЫЕ модели в одном ответе.
    имя_в_базе, live, о_карточке = _сверить_с_карточкой(name, live, store, resolution)
    if имя_в_базе != name:
        resolution = store.resolve(имя_в_базе)
    known_here = bool(resolution.names)
    роль, семья_ответа = _семья(store, имя_в_базе, attribute, known_here)

    # СПРОШЕННОЕ СЛОВО РАЗВОРАЧИВАЕТСЯ В ЗАПИСАННЫЕ ИМЕНА. ИЗМЕРЕНО
    # 2026-09-02: цена записана у 79 моделей, а на вопрос `price` отвечали 7
    # — у остальных 72 она лежит под `price_per_minute`,
    # `price_per_second_usd`, `price_per_image_usd` и ещё пятнадцатью именами.
    # Ответ «nothing is recorded» при записанном факте гонит спросившего
    # искать заново то, что уже лежит; правила разворота и его негативный
    # контроль — в `studio/selfrag/attrfamily.py`.
    if attribute:
        attributes = attrfamily.expand(attribute, store.attributes(имя_в_базе))
        # Не нашлось родственников — спрашиваем ровно то, что спросили, чтобы
        # ветка `attribute_unknown` ниже сработала как прежде (Р1).
        attributes = attributes or [attribute]
    else:
        attributes = store.attributes(имя_в_базе)
    asked_as = attrfamily.как_отвечено(attribute, attributes) if attribute else ""
    # СМЕЖНОЕ — НЕ ОТВЕТ (валидатор 5-го круга): `negative_prompt` у
    # `kling-3.0` отвечался строкой `prompt_skeleton` с исходом `pass`.
    # Члены той же ТЕМЫ, что не отвечают на спрошенное, едут отдельным полем
    # `substitutes`, каждый с `substitute_for` и `counts_as_answer: false`, и
    # ни в `claims`, ни в счёт исхода не входят. Ответ ищется сначала тем же
    # атрибутом у вариантов и семьи (`family_claims`), смежное — последним.
    заменители = (
        attrfamily.substitutes(attribute, store.attributes(имя_в_базе)) if attribute else []
    )
    substitutes = {
        attr: {
            **store.claims(имя_в_базе, attr),
            "substitute_for": attribute,
            "counts_as_answer": False,
        }
        for attr in заменители
    }
    claims: dict[str, dict] = {}
    contested: list[str] = []
    for attr in attributes:
        verdict = store.claims(имя_в_базе, attr)
        claims[attr] = verdict
        if verdict["outcome"] == FAIL:
            contested.append(attr)

    # СНЯТА ЛИ МОДЕЛЬ С ОБСЛУЖИВАНИЯ — ПО БАЗЕ, А НЕ ПО РЕЕСТРУ. Реестр держит
    # семь карточек, база — 505 моделей, и для остальных 498 запись о снятии
    # лежала рядовой строкой среди прочих. ИЗМЕРЕНО 2026-09-02: таких строк 6 у
    # 5 моделей, и у двух (`imagen-4`, `imagen-4.0`) срок УЖЕ ПРОШЁЛ. Отдать
    # такую модель в сравнение значит послать человека платить за 404.
    #
    # Правила разбора и их негативный контроль — `studio/lifecycle.py`.
    свои_написания = set(store.spellings(имя_в_базе))
    # По ВСЕМ написаниям имени: `imagen-4` и `imagen-4.0` — одна модель в
    # двух карманах, и снятие записано у обоих по-разному.
    свои_строки = [f for f in store.facts if f.model.lower() in свои_написания]
    lifecycle = [
        запись for запись in (_строка_службы(f) for f in свои_строки) if запись is not None
    ]
    # СРОКИ ПО МАРШРУТАМ (пункт 12, 2026-10-15): строки
    # `deprecation_date_via_<маршрут>` сводятся одним правилом с планировщиком
    # (`lifecycle.по_маршрутам`) и вкладываются в ось доступности реестра.
    маршрутные = [(f.attribute, str(f.value)) for f in свои_строки]
    по_маршрутам = _lifecycle.по_маршрутам(маршрутные)
    live = registry.with_route_deadlines(live, маршрутные)

    failures = [
        {
            "value": fact.value,
            "fix": fact.fix,
            "source_url": fact.source_url,
            "tier": fact.tier,
            "stated_on": fact.stated_on,
        }
        for fact in store.failure_modes(имя_в_базе)
        # ОПРОВЕРЖЕНИЕ ПРОВАЛА — НЕ ПРОВАЛ (пункт 11, 2026-10-15): строка
        # `failure_mode` с явным `contra=False` («ОПРОВЕРГНУТО: minimax-h3
        # моргает») стояла в списке провалов. Знак записавшего старше имени.
        if getattr(fact, "contra", None) is not False
    ]

    # Findings about the CLASS, in their own list and never folded into the
    # per-model answer. They were recorded with `*` (the field) or
    # `<family>-*` (one vendor's line) as the model, which is the honest scope
    # and meant nothing ever returned them: every query starts with a model
    # name. MEASURED 2026-08-27, 26 such rows were in the base and reachable
    # by nobody.
    #
    # Separate rather than merged, because "said about the class" and
    # "measured on this model" are different claims and a reader has to be
    # able to tell them apart. They also never vote in a contradiction.
    card_vs_base = _card_vs_base(live.get("card"), store, имя_в_базе)

    # КАРТОЧКА ОТДАЁТСЯ СЛОВАРЁМ, А НЕ PYTHON-ОБЪЕКТОМ. Найдено чтением
    # собственной выдачи (П3, 2026-09-02): в ответе стояло
    #     "card": "ModelCard(model_id='kling-3.0', media='video', status=...)"
    # — то есть `repr()` датакласса, засунутый в поле JSON сериализатором
    # сервера (`default=str`). Потребитель не может прочесть из него ни одного
    # поля, не разбирая строку регулярками, а любой другой потребитель
    # (`json.dumps` без `default`) на этом объекте прямо падает.
    #
    # Преобразуется ОДИН раз и здесь, ниже по коду `live` уходит в шесть
    # разных ответов (Е1: одно знание — одно место).
    live = dict(live)
    live["card"] = _card_as_dict(live.get("card"))

    # ОСЬ РЕЕСТРА НЕ ВЕДЁТСЯ ДЛЯ ЭТОЙ МОДЕЛИ — и это не «мы знаем семь
    # моделей». Нота реестра раньше перечисляла его семь карточек, и читалась
    # как весь объём знания (аудит ae94057). Теперь она говорит, что ось не
    # ведётся, а что можно — выводится из записей базы о жизненном цикле.
    if live.get("card") is None:
        live["note"] = _доступность_по_базе(str(live.get("note", "")), lifecycle, known_here)
        near = store.near(имя_в_базе)
        if near:
            live["note"] = (
                str(live.get("note", ""))
                + f" The FACT BASE is a different and much larger set: it holds "
                f"{store.model_count()} ids, among them {', '.join(near)}."
            )
    if о_карточке:
        live["note"] = f"{о_карточке} {live.get('note', '')}".strip()

    every_class_fact = _spread_by_attribute(
        sorted(
            store.class_claims(имя_в_базе),
            key=lambda f: (TIERS.index(f.tier) if f.tier in TIERS else len(TIERS), f.attribute),
        )
    )
    class_findings = [
        {
            "scope": fact.model,
            "attribute": fact.attribute,
            "value": fact.value,
            "fix": fact.fix,
            "source_url": fact.source_url,
            "tier": fact.tier,
            "stated_on": fact.stated_on,
        }
        for fact in every_class_fact[:CLASS_FINDINGS_SHOWN]
    ]
    # The denominator travels with the list (rule R2). 170 class facts stand
    # for most models after the 2026-08-27 verification pass, and returning
    # all of them would bury the model's own answer under statements about the
    # field. Strongest tier first, and the count of what was left out — a
    # silent truncation reads as "that is all there is".
    class_findings_note = (
        f"{len(class_findings)} of {len(every_class_fact)} findings about the class, "
        "strongest tier first. These were said about the field or about a vendor's "
        "line, NOT measured on this model."
    )
    # ВОЗМОЖНО УСТАРЕЛО (валидатор G14): цены и факты о видеомоделях
    # меняются помесячно, и строка двухмесячной давности — не та же правда,
    # что вчерашняя. Пометка, а не вердикт: исход не меняется (Р1).
    видео = _это_видео(store, имя_в_базе, live.get("card"))
    устарело = _пометить_свежесть(claims, видео) + _пометить_свежесть(семья_ответа, видео)
    # Что едет в КАЖДЫЙ ответ ниже, одним словарём (Е1): раньше эти ключи
    # повторялись в шести ветках, и новый ключ терялся в половине из них.
    общее = {
        "possibly_stale": устарело,
        "possibly_stale_note": (
            f"{len(устарело)} attribute(s) are prices or facts about a video model whose "
            f"newest source is older than its freshness window ({POSSIBLY_STALE_DAYS} days "
            f"for prices and most facts, {DURABLE_STALE_DAYS} for licence, architecture "
            f"and maximum specs): {', '.join(устарело[:8])}"
            f"{', …' if len(устарело) > 8 else ''}. Possibly stale — re-check before quoting."
            if устарело
            else ""
        ),
        "availability": live,
        "failure_modes": failures,
        "class_findings": class_findings,
        "class_findings_total": len(every_class_fact),
        "class_findings_note": class_findings_note,
        "card_vs_base": card_vs_base,
        "lifecycle": lifecycle,
        "resolved_as": {
            "asked": name,
            "looked_up_as": имя_в_базе,
            "spellings": list(resolution.names),
            "how": resolution.how,
            "note": resolution.note,
        },
        "family": роль,
        "family_claims": семья_ответа,
        "substitutes": substitutes,
        "substitutes_note": (
            f"RELATED, NOT AN ANSWER: recorded for {name!r} under the same topic as "
            f"{attribute!r}, but each answers a different question and none is counted as "
            f"answering {attribute!r}: {', '.join(substitutes)} (in substitutes)."
            if substitutes
            else ""
        ),
    }
    # Разрешение по единственному соседу — вывод, а не совпадение (Е2): оно
    # называется в главной ноте, а не только в поле.
    авто = (
        f" ИМЯ: {resolution.note}."
        if resolution.how in (modelnames.HOW_VENDOR, *modelnames.HOW_INFERRED)
        or (resolution.names and name.strip().lower() not in resolution.names)
        else ""
    )
    семейное = _семейная_нота(роль, семья_ответа)

    if live["card"] is None and not known_here:
        # Соседние имена идут В ЭТУ ноту, а не только в `availability`. Ветка
        # писала свою ноту с нуля и теряла подсказку, добавленную выше, —
        # ПОЙМАНО на живом вопросе владельца 2026-08-31: он спросил про
        # `h3-max`, база держала `minimax-h3-max` с двадцатью одним атрибутом,
        # и верхняя нота отвечала «нет ни в реестре, ни в базе». Формально про
        # эту строку — верно; по существу — нет, и читают именно её.
        neighbours = store.near(name)
        # СЕМЬЯ БЕЗ СОБСТВЕННЫХ СТРОК (аудит ae94057): `seedvr2` в базе нет, а
        # `seedvr2-3b`, `seedvr2-7b`, `seedvr2_comfyui` есть. Ответ — сводка по
        # вариантам, каждое утверждение помечено своим именем, и в ноте
        # сказано, что о самой `seedvr2` не записано ничего.
        if роль.get("role") == "family" and семья_ответа:
            ответ_семьи = _ответ_семьи(name, attribute, семья_ответа, "variant")
            if ответ_семьи is not None:
                # Ответ стоит на утверждениях семьи — они и едут в `claims`
                # (ключ `атрибут@имя`, у каждого `about`/`scope`): иначе исход
                # `pass` стоял бы без единого значения, а журнал промахов
                # (`misses.evidence`) считал бы этот ответ пустым (Е1).
                return {
                    **ответ_семьи,
                    **общее,
                    "near": list(neighbours),
                    "claims": семья_ответа,
                    "own_claims": {},
                    "contested": [],
                }
        # ВАРИАНТ БЕЗ ЗАПИСЕЙ И ДРУГАЯ ВЕРСИЯ — НЕ ОПЕЧАТКА (валидатор G5/G9).
        неописанный = _неописанный_вариант(store, name, attribute)
        if неописанный is not None:
            return {**общее, **неописанный}
        версии = modelnames.lineage(name, store.models())
        if версии:
            return {
                **общее,
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "reason": REASON_VERSION_NOT_RECORDED,
                "note": (
                    f"{name!r} is not recorded in the fact base under any spelling. The base "
                    f"holds OTHER VERSIONS of the same line ({', '.join(версии)}); a different "
                    "version is a different model, so none of their claims is an answer "
                    f"about {name!r}. Search the web and call `record_model_fact` to put it there."
                ),
                "near": [],
                "other_versions": версии,
                "claims": {},
                "contested": [],
            }
        # Два РАЗНЫХ положения дел, и до 2026-09-02 они печатались одинаково:
        # база не знает такого имени вовсе — и база знает соседнее имя, то
        # есть спрашивавший, вероятнее всего, опечатался. Первое лечится
        # поиском источника, второе — повторным вопросом. Нота их различала
        # словами, ответ — ничем.
        hint = (
            f" The base does hold {', '.join(neighbours)} — if that is the same "
            "model under another name, ask again by that id."
            if neighbours
            else ""
        )
        return {
            **общее,
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"{name!r} is in neither the registry nor the fact base under "
                "that exact name. Nothing was checked, which is not the same as "
                "nothing being wrong. Search the web and call `record_model_fact` "
                "to put it there." + hint
            ),
            "reason": REASON_NAME_MAYBE_MISTYPED if neighbours else REASON_MODEL_UNKNOWN,
            "near": list(neighbours),
            "claims": {},
            # The class findings come back even here. They are true of the
            # field, not of this name, so an unknown model does not make them
            # less true — and the outcome stays `could not measure` with
            # `checked` at 0, so nothing reads as having been verified.
            "contested": [],
        }

    checked = len(claims) + (1 if live["card"] is not None else 0)
    if live["outcome"] == FAIL:
        return {
            **общее,
            "outcome": FAIL,
            "checked": checked,
            "violations": 1,
            "unmeasured": len(contested),
            "reason": REASON_MODEL_UNUSABLE,
            "note": f"the model itself is unusable: {live['note']}",
            "claims": claims,
            "contested": contested,
        }

    отвечено = [attr for attr, verdict in claims.items() if verdict["outcome"] == PASS]
    # СПОР ПО ЧАСТИ АТРИБУТОВ НЕ РОНЯЕТ ВЕСЬ ОТВЕТ (аудит ae94057). `fail`
    # остаётся, когда спорно ВСЁ, о чём спросили, или спорен САМ спрошенный
    # атрибут (`kling-3.0.max_seconds`): это и есть ответ на вопрос, и
    # отвеченные соседи по семье атрибутов его не отменяют. Когда спорна
    # часть полного ответа, заголовок отражает знание (`pass`), а спорные
    # атрибуты названы в ноте и в `contested`, со всеми сторонами в `claims`.
    спорен_спрошенный = bool(attribute) and (claims.get(attribute) or {}).get("outcome") == FAIL
    if contested and (not отвечено or спорен_спрошенный):
        return {
            **общее,
            "outcome": FAIL,
            "checked": checked,
            "violations": len(contested),
            "unmeasured": 0,
            "note": (
                f"sources disagree on {', '.join(contested)}. Every side is "
                "returned with its URL and its date; nothing here votes, "
                "averages or takes the newest." + авто + семейное
            ),
            "reason": REASON_SOURCES_DISAGREE,
            "claims": claims,
            "contested": contested,
        }

    if not claims:
        return {
            **общее,
            "outcome": UNMEASURED,
            "checked": checked,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"the registry has a card for {name!r} but the fact base holds no "
                "claim about it, so there is nothing to cite. " + str(live["note"])
            ),
            "reason": REASON_NOTHING_RECORDED,
            "known_attributes": list(store.attributes(имя_в_базе)),
            "claims": {},
            "contested": [],
        }

    unmeasured = sum(1 for v in claims.values() if v["outcome"] == UNMEASURED)

    # ДВЕ ОСИ, И ОНИ БОЛЬШЕ НЕ ПОДМЕНЯЮТ ДРУГ ДРУГА.
    #
    # Здесь стояло `live["outcome"] == UNMEASURED or ...`, и из-за этого
    # вердикт о ЗНАНИИ выносился по реестру ДОСТУПНОСТИ. В реестре семь имён;
    # в базе фактов 466. ИЗМЕРЕНО 2026-09-02 на живой базе до правки: 457
    # моделей из 466 получали `could not measure` при непустом свидетельстве,
    # а по парам «модель.атрибут» — 999 из 1236 при утверждении с исходом
    # `pass`. Пользователь получал «не знаю» поверх готового ответа вендора:
    # `seedance-2.5.max_seconds` вернуло `could not measure` со значением
    # `'30'` из вендорского источника в руках.
    #
    # Доступность не исчезла и не должна: она отдельная ось («знаем ли мы»
    # против «можно ли этим воспользоваться») и по-прежнему едет целиком в
    # `availability`, а её собственный вердикт называется в ноте. Она НЕ
    # выносит вердикт о знании — но остаётся видимой, и `fail` от неё
    # (модель снята с обслуживания) выше по функции по-прежнему главнее
    # всего: платить за 404 нельзя, даже зная про модель всё.
    # СНЯТИЕ НАЗЫВАЕТСЯ В НОТЕ, А НЕ ТОЛЬКО ПОЛЕМ. Поле, которого никто не
    # читает, — тот же дефект, что честная деталь при неверном заголовке:
    # именно за него сегодня заведён `scripts/check_headline.py`.
    # Маршрутная строка о модели целиком не говорит: она судится сводкой.
    целиком = [с for с in lifecycle if not с.get("route")]
    снято = [с for с in целиком if с["outcome"] == _lifecycle.НЕ_ГОДНО]
    впереди = [с for с in целиком if с["outcome"] == _lifecycle.НЕ_СМОГЛИ]
    жизнь = ""
    if снято:
        когда = снято[0]["when"] or "без даты"
        жизнь = f" СНЯТА С ОБСЛУЖИВАНИЯ ({когда}), по записи базы: {снято[0]['attribute']}."
    elif по_маршрутам.outcome == _lifecycle.НЕ_ГОДНО:
        жизнь = f" СНЯТА С ОБСЛУЖИВАНИЯ НА ВСЕХ ЗАПИСАННЫХ МАРШРУТАХ: {по_маршрутам.note}."
    elif впереди:
        когда = впереди[0]["when"] or "срок не назван"
        жизнь = f" ОБЪЯВЛЕНО СНЯТИЕ ({когда}), по записи базы: {впереди[0]['attribute']}."
    if по_маршрутам.outcome == _lifecycle.НЕ_СМОГЛИ:
        жизнь += f" ПО МАРШРУТАМ: {по_маршрутам.note}."

    axis = (
        жизнь + f" Availability is a SEPARATE axis, and it says {live['outcome']!r}: {live['note']}"
    )
    if unmeasured == len(claims):
        why = gap_reason(claims)
        # ОТВЕТ С УРОВНЯ СЕМЬИ, когда у самого варианта атрибут не записан
        # (аудит ae94057): `veo-3.1-lite.price` молчал, а цена Lite записана у
        # `veo-3.1` — «$0.08/s Lite 1080p» со страницы вендора. Ответ помечен:
        # это утверждение о семье, а не измерение варианта.
        if семья_ответа:
            ответ_семьи = _ответ_семьи(name, attribute, семья_ответа, роль.get("role", ""))
            if ответ_семьи is not None:
                # Кусок строки семьи о СВОЕЙ ступени (`veo-3.1-lite` ->
                # «Lite $0.05/s …»), если вариант отличается словом-ступенью.
                срезы = (
                    _срезы_ступени(семья_ответа, _слова_ступени(имя_в_базе, роль))
                    if роль.get("role") == "variant"
                    else {}
                )
                return {
                    **общее,
                    **ответ_семьи,
                    "variant_slices": срезы,
                    "note": ответ_семьи["note"]
                    + (
                        " Срез строки семьи о ступени варианта: "
                        + "; ".join(f"{k} -> {v['value']!r}" for k, v in срезы.items())
                        + " (ВЫВЕДЕНО из строки семьи, не измерено)."
                        if срезы
                        else ""
                    )
                    + (f" {общее['substitutes_note']}" if substitutes else "")
                    + авто
                    + axis,
                    "claims": семья_ответа,
                    "own_claims": claims,
                    "contested": [],
                    "known_attributes": list(store.attributes(имя_в_базе)),
                }
        известные = list(store.attributes(имя_в_базе))
        gap_note = (
            f"nothing is recorded about {'.'.join(filter(None, (name, attribute)))}"
            if why == REASON_ATTRIBUTE_UNKNOWN
            else (
                f"{unmeasured} of {len(claims)} attribute(s) rest on blog-tier or "
                "stale sources only, and repetition is not corroboration"
            )
        )
        # ЧТО ЗАПИСАНО, НАЗЫВАЕТСЯ В НОТЕ (аудит ae94057): «не записано»
        # без списка того, что есть, не даёт спросить правильным словом.
        перечень = (
            f" Recorded attributes for this model ({len(известные)}): "
            + ", ".join(известные[:ПЕРЕЧЕНЬ_АТРИБУТОВ])
            + (
                f", … and {len(известные) - ПЕРЕЧЕНЬ_АТРИБУТОВ} more"
                if len(известные) > ПЕРЕЧЕНЬ_АТРИБУТОВ
                else ""
            )
            + "."
            if why == REASON_ATTRIBUTE_UNKNOWN and известные
            else ""
        )
        return {
            **общее,
            "outcome": UNMEASURED,
            "checked": checked,
            "violations": 0,
            "unmeasured": max(unmeasured, 1),
            "note": (
                f"{gap_note}. The model itself IS in the fact base, so this is a "
                "gap in what was recorded, not an unknown name."
                + (f" {общее['substitutes_note']}" if substitutes else "")
                + перечень
                + авто
                + axis
            ),
            "reason": why,
            # Что о модели ЕСТЬ. Без этого «не смогли» на опечатку в атрибуте
            # неотличимо от «не смогли» на настоящий пробел, и спрашивавшему
            # нечем сделать следующий шаг.
            "known_attributes": известные,
            "claims": claims,
            "contested": [],
        }

    спорное = (
        f" ОСПОРЕНО {len(contested)} из {len(claims)}: {', '.join(contested)} — источники "
        "расходятся, все стороны с адресами в claims (в счёте — среди unmeasured); "
        "на остальное ответ есть."
        if contested
        else ""
    )
    return {
        **общее,
        "outcome": PASS,
        "checked": checked,
        # Спорный атрибут при исходе `pass` — НЕ нарушение проверки, а атрибут
        # без единого значения: он считается в `unmeasured` (Р2), а `violations`
        # у `pass` остаётся нулём (`scripts/check_headline.py`).
        "violations": 0,
        "unmeasured": unmeasured + len(contested),
        "note": (
            f"{len(claims)} attribute(s) answered from {claims_found(claims)} recorded "
            f"statement(s) across {sources_behind(claims)} source(s), "
            f"{unmeasured} of them only weakly."
            + спорное
            # Разворот спрошенного слова называется в ноте, а не только в
            # ключах: читают ноту, и «спросил price — получил price_per_minute»
            # обязано быть видно там же, где ответ.
            + (f" ВНИМАНИЕ: {asked_as}" if asked_as else "")
            + авто
            + семейное
            + axis
        ),
        "reason": REASON_ANSWERED_SOME_CONTESTED if contested else REASON_ANSWERED,
        "asked_as": asked_as,
        "claims": claims,
        "contested": contested,
    }


#: ВОЗРАСТ, ПОСЛЕ КОТОРОГО ЦЕНА ИЛИ ФАКТ О ВИДЕОМОДЕЛИ ПОМЕЧАЕТСЯ «ВОЗМОЖНО
#: УСТАРЕЛО» (валидатор G14, 2026-10-14). ВЫБРАНО 30: видеоплощадки меняли
#: цены и пределы помесячно весь 2026 год (veo-3.1 Lite/Fast, kling-3.0
#: turbo). Общий порог базы `STALE_AFTER_DAYS` (90) остаётся для остального:
#: этот — только пометка, исход ответа он не меняет. Сторожится мутацией в обе
#: стороны: строка 30 дней — свежая, 31 — помечена.
POSSIBLY_STALE_DAYS = 30

#: ОКНО СВЕЖЕСТИ — ПО АТРИБУТУ, А НЕ ОДНО НА ВСЁ (пункт 15, 2026-10-15).
#: Один порог 30 дней помечал «возможно устарело» лицензию, архитектуру и
#: fps через месяц после чтения — то есть почти всю базу, и пометка перестала
#: что-либо отличать. Помесячно меняются ЦЕНЫ (и тарифные ступени); лицензия,
#: архитектура, предельные характеристики выпуска (длительность, разрешение,
#: частота кадров, соотношения сторон) меняются с новой версией модели, а
#: новая версия — это новое имя в базе. Им окно 180 дней. Ключ — семья
#: атрибута из `attrfamily` (Е1); прочие семьи — общий `POSSIBLY_STALE_DAYS`.
DURABLE_STALE_DAYS = 180
STALE_DAYS_BY_FAMILY: dict[str, int] = {
    "price": POSSIBLY_STALE_DAYS,
    "license": DURABLE_STALE_DAYS,
    "architecture": DURABLE_STALE_DAYS,
    "max_seconds": DURABLE_STALE_DAYS,
    "duration_floor": DURABLE_STALE_DAYS,
    "resolution": DURABLE_STALE_DAYS,
    "image_size": DURABLE_STALE_DAYS,
    "frame_rate": DURABLE_STALE_DAYS,
    "aspect_ratio": DURABLE_STALE_DAYS,
    "text_limit": DURABLE_STALE_DAYS,
    "model_identity": DURABLE_STALE_DAYS,
}

#: Имена, которых нет ни в одной семье `attrfamily`, но которые по смыслу —
#: характеристики выпуска (`fps` не входит в `frame_rate`, `max_resolution`
#: читается семьёй не всегда). Префикс `max_`/`min_` — предельная
#: характеристика; цена в таких именах ловится семьёй `price` раньше.
_ДОЛГИЕ_ИМЕНА = re.compile(
    r"^(fps|max_\w+|min_\w+|license\w*|licence\w*|architecture\w*|open_weights\w*|"
    r"parameters?|param_count|model_size)$",
    re.I,
)


def окно_свежести(attribute: str) -> int:
    """Сколько дней строка об этом атрибуте считается свежей."""
    семья = attrfamily.семья_имени(attribute)
    if семья in STALE_DAYS_BY_FAMILY:
        return STALE_DAYS_BY_FAMILY[семья]
    if _ДОЛГИЕ_ИМЕНА.match(str(attribute or "").strip()):
        return DURABLE_STALE_DAYS
    return POSSIBLY_STALE_DAYS


#: Атрибуты, по которым модель — ВИДЕОмодель, если карточки реестра нет.
_ВИДЕО_АТРИБУТЫ: frozenset[str] = frozenset(
    {"max_seconds", "min_seconds", "fps", "duration_enum", "max_duration_seconds"}
)


def _это_видео(store: FactStore, имя: str, card: object) -> bool:
    """Видеомодель? Карточка реестра, затем записанные выходы, затем атрибуты."""
    if str(getattr(card, "media", "") or "").lower() == "video":
        return True
    атрибуты = set(store.attributes(имя))
    for выход in ("produces_outputs", "output_modality", "outputs", "modality"):
        if выход in атрибуты:
            значения = " ".join(str(v) for v in store.claims(имя, выход).get("values") or [])
            if re.search(r"video|видео", значения, re.I):
                return True
    return bool(атрибуты & _ВИДЕО_АТРИБУТЫ)


def _пометить_свежесть(claims: dict, видео: bool) -> list[str]:
    """Пометить разборы `possibly_stale`; вернуть помеченные ключи.

    Цена — всегда (семья `price` из `attrfamily`), остальное — у видеомодели.
    Мерило — САМЫЙ СВЕЖИЙ источник разбора: одна свежая строка снимает
    пометку, потому что кто-то это недавно подтвердил.
    """
    помечено: list[str] = []
    for ключ, разбор in claims.items():
        атрибут = str(ключ).split("@", 1)[0]
        if not (видео or attrfamily.семья_имени(атрибут) == "price"):
            continue
        возрасты = [
            и.get("age_days")
            for строка in (разбор.get("claims") or [])
            for и in (строка.get("sources") or [])
            if isinstance(и.get("age_days"), int)
        ]
        if not возрасты:
            continue
        свежайший = min(возрасты)
        окно = окно_свежести(атрибут)
        разбор["newest_age_days"] = свежайший
        разбор["stale_after_days"] = окно
        разбор["possibly_stale"] = свежайший > окно
        if разбор["possibly_stale"]:
            помечено.append(str(ключ))
    return помечено


#: Сколько записанных атрибутов назвать в ноте, когда спрошенного нет. ВЫБРАНО:
#: у хорошо изученных моделей их 20–40, а нота — строка, которую читают.
ПЕРЕЧЕНЬ_АТРИБУТОВ = 20

#: Сколько вариантов семьи разворачивать в `family_claims`. ВЫБРАНО: у
#: `flux-2` в базе 20 с лишним вариантов, включая общинные дообучения, и
#: развернуть их все значит утопить ответ. Остаток считается (Р2).
ВАРИАНТОВ_ПОКАЗАНО = 12


def _сверить_с_карточкой(
    name: str, live: dict, store: FactStore, resolution: Any
) -> tuple[str, dict, str]:
    """(имя для базы, ответ реестра, нота о сверке). Одна модель на ответ.

    * Имя само разрешается в базе, и карточка — о ДРУГОЙ модели (`veo-3`
      -> карточка `veo-3.1`): карточка снимается, ответ — о спрошенной модели.
    * Имя в базе не разрешается, а реестр знает псевдоним (`kling` ->
      `kling-3.0`): факты ищутся под id карточки, и это сказано в ноте.
    """
    card = live.get("card")
    if card is None:
        return name, live, ""
    card_id = str(getattr(card, "model_id", "") or "")
    if not card_id or card_id == name:
        return name, live, ""
    по_карточке = set(store.spellings(card_id))
    # Псевдоним реестра — РЕШЕНИЕ, вывод по единственному соседу — догадка:
    # при обоих побеждает решение.
    if resolution.names and resolution.how not in modelnames.HOW_INFERRED:
        if (
            по_карточке
            and set(resolution.names) != по_карточке
            and modelnames.fold(card_id) != modelnames.fold(name)
        ):
            снято = {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": (
                    f"реестр свёл {name!r} к карточке {card_id!r}, но база фактов держит "
                    f"{name!r} как ОТДЕЛЬНУЮ модель — карточка к ней не применена"
                ),
                "card": None,
            }
            return name, снято, ""
        return name, live, ""
    if по_карточке:
        return (
            card_id,
            live,
            (f"реестр знает {name!r} как псевдоним {card_id!r}; факты взяты под {card_id!r}."),
        )
    return name, live, ""


def _строка_службы(fact: Fact) -> dict | None:
    """Строка базы о конце службы, с маршрутом, если он назван; иначе `None`.

    Маршрутная строка (`deprecation_date_via_gemini`) разбирается по своему
    сроку и несёт `route`: печатать её надо, а судить модель по ней одной —
    нельзя (это делает сводка `lifecycle.по_маршрутам`).
    """
    куда = _lifecycle.маршрут(fact.attribute)
    if куда:
        снятие = _lifecycle.срок_атрибутом(str(fact.value), fact.attribute)
    else:
        снятие = _lifecycle.разобрать(str(fact.value), fact.attribute)
    if снятие is None or снятие.outcome == _lifecycle.ГОДНО:
        return None
    return {
        "attribute": fact.attribute,
        "value": fact.value,
        "source_url": fact.source_url,
        "tier": fact.tier,
        **({"route": куда} if куда else {}),
        **снятие.as_dict(),
    }


def _доступность_по_базе(нота_реестра: str, lifecycle: list[dict], known_here: bool) -> str:
    """Нота оси доступности для модели без карточки. Что можно — из базы."""
    if not known_here:
        return нота_реестра
    if not lifecycle:
        вывод = "записей о жизненном цикле (снятие, вывод из обслуживания) в базе нет"
    else:
        первое = lifecycle[0]
        вывод = (
            f"по записи базы {первое['attribute']} = {str(первое['value'])[:120]!r} "
            f"({первое['tier']}, {первое['source_url']})"
        )
    return f"{нота_реестра} Из базы фактов: {вывод}."


def _срезы_ступени(семья_ответа: dict, слова: tuple[str, ...] | list[str]) -> dict:
    """Куски строк семьи о ступени варианта (`Fast $0.10/s …`), с пометкой.

    Валидатор G5: строка семьи о трёх ступенях на вопрос об одной заставляет
    читающего искать свою — и сравнение по первому числу берёт чужую. Кусок
    — ДОСЛОВНЫЙ (`attrfamily.variant_slice`), и помечен: выведен из строки
    семьи, а не измерен на варианте.
    """
    out: dict = {}
    for ключ, разбор in семья_ответа.items():
        for строка in разбор.get("claims") or []:
            кусок = attrfamily.variant_slice(str(строка.get("value") or ""), слова)
            if not кусок:
                continue
            источник = (строка.get("sources") or [{}])[0]
            out[ключ] = {
                "value": кусок,
                "derived_from": строка.get("value"),
                "about": разбор.get("about"),
                "tier": строка.get("best_tier"),
                "source_url": источник.get("url"),
                "stated_on": источник.get("stated_on"),
                "derivation": (
                    "DERIVED: the slice of the FAMILY row that names this tier "
                    f"({', '.join(слова)}); not a measurement of the variant"
                ),
            }
            break
    return out


def _неописанный_вариант(store: FactStore, name: str, attribute: str) -> dict | None:
    """Ответ о варианте, которого в базе нет, при известной семье; иначе None.

    `veo-3.1-fast` (и `Veo3.1 Fast`, и `veo-3.1-fast-generate-preview`):
    семья `veo-3.1`, лишнее звено `fast` из `modelnames.TIER_WORDS`. Исход
    `could not measure` — о самом варианте не записано ничего (Р1); семья и
    куски её строк о ступени едут контекстом, каждое помечено.
    """
    семья, лишнее = modelnames.unrecorded_variant(name, store.models())
    if not семья:
        return None
    главное = store.canonical(семья[0]) or семья[0]
    семья = [главное] + [n for n in семья if n != главное]
    роль = {
        "role": "unrecorded_variant",
        "name": name,
        "family_name": семья[0],
        "family_spellings": семья,
        "variant_words": list(лишнее),
        "role_in_family": modelnames.ROLE_VENDOR_VARIANT,
    }
    семья_ответа = _утверждения(store, [семья[0]], attribute, "family")
    срезы = _срезы_ступени(семья_ответа, [с for с in лишнее if с not in _РЕЖИМЫ])
    return {
        "outcome": UNMEASURED,
        "checked": 0,
        "violations": 0,
        "unmeasured": 1,
        "reason": REASON_VARIANT_NOT_RECORDED,
        "note": (
            f"{name!r} is not recorded, but it reads as the {' '.join(лишнее)!r} variant of "
            f"{семья[0]!r}, which the base does know. Nothing was measured on {name!r} itself; "
            f"the family's claims ({len(семья_ответа)}) ride along in family_claims, each "
            "marked scope=family, and are NOT measurements of the variant."
            + (
                " Slices of family rows that name this tier: "
                + "; ".join(f"{k} -> {v['value']!r}" for k, v in срезы.items())
                + " (DERIVED from the family row, not measured)."
                if срезы
                else ""
            )
            + " Search the web and call `record_model_fact` to record the variant itself."
        ),
        "near": [],
        "family": роль,
        "family_claims": семья_ответа,
        "variant_slices": срезы,
        "claims": {},
        "contested": [],
    }


#: Звенья режима (`i2v`), а не ступени: куска строки о них не ищут — строка
#: цены семьи режимы не перечисляет, а слово `i2v` в начале куска значило бы
#: другое.
_РЕЖИМЫ: frozenset[str] = frozenset({"i2v", "t2v", "t2i", "s2v", "r2v", "edit"})


def _семья(store: FactStore, имя: str, attribute: str, known_here: bool) -> tuple[dict, dict]:
    """Роль имени в семье и утверждения семьи, каждое помечено, о ком оно.

    * `family`  — имя САМО семья (`veo-3.1`, `minimax-h3`, `seedvr2`):
      утверждения её вариантов, ключ `атрибут@вариант`, `scope = variant`.
    * `variant` — имя — вариант известной семьи (`veo-3.1-lite`): утверждения
      семьи, ключ `атрибут@семья`, `scope = family`. Только если сам вариант
      в базе есть: незнакомое имя рядом с семьёй — не та же модель (И5,
      негативный контроль `test-model-pro`).

    РАЗНЫЕ ВЕРСИИ НЕ СЕМЬЯ (И5): `veo-3` и `veo-3.1` друг другу не варианты —
    см. `modelnames.family`.
    """
    все = store.family(имя)
    # РОЛЬ В СЕМЬЕ (валидатор G10): за семью отвечают только варианты вендора.
    # Общинные работы и надстройки называются отдельными списками и в
    # `family_claims` не идут — их строки о других весах или другой задаче.
    роли = {names[0]: store.variant_role(names[0]) for names in все}
    варианты = [names for names in все if роли[names[0]] == modelnames.ROLE_VENDOR_VARIANT]
    чужие = {
        "community": [n for n, r in роли.items() if r == modelnames.ROLE_COMMUNITY],
        "addons": [n for n, r in роли.items() if r == modelnames.ROLE_ADDON],
    }
    if варианты or any(чужие.values()):
        показано = варианты[:ВАРИАНТОВ_ПОКАЗАНО]
        роль = {
            "role": "family",
            "name": имя,
            "variants": [names[0] for names in варианты],
            "variants_total": len(варианты),
            "variants_shown": len(показано),
            **чужие,
            "variant_roles": роли,
        }
        return роль, _утверждения(store, [names[0] for names in показано], attribute, "variant")
    if known_here:
        родитель = store.parent(имя)
        if родитель:
            своя_роль = store.variant_role(имя)
            # Имя семьи — каноническое написание группы, а не первое по
            # алфавиту: иначе `minimax-h3-…` называл семьёй `hailuo3`.
            родитель = [store.canonical(родитель[0]) or родитель[0]] + [
                n for n in родитель if n != (store.canonical(родитель[0]) or родитель[0])
            ]
            роль = {
                "role": "variant",
                "name": имя,
                "family_name": родитель[0],
                "family_spellings": родитель,
                "role_in_family": своя_роль,
            }
            if своя_роль != modelnames.ROLE_VENDOR_VARIANT:
                # Общинная работа или надстройка: семья за неё НЕ отвечает, и
                # она за семью тоже. Родство названо, утверждений семьи нет.
                return роль, {}
            return роль, _утверждения(store, [родитель[0]], attribute, "family")
    return {}, {}


def _слова_ступени(имя: str, роль: dict) -> list[str]:
    """Слова-ступени, которыми вариант отличается от семьи (`lite`)."""
    семья = modelnames.tokens(str(роль.get("family_name") or ""))
    свои = modelnames.tokens(имя)
    хвост = свои[len(семья) :] if свои[: len(семья)] == семья else свои
    return [з for з in хвост if з in modelnames.TIER_WORDS and з not in _РЕЖИМЫ]


def _утверждения(store: FactStore, о_ком: list[str], attribute: str, scope: str) -> dict:
    out: dict[str, dict] = {}
    for about in о_ком:
        записано = store.attributes(about)
        имена = attrfamily.expand(attribute, записано) if attribute else записано
        for attr in имена:
            verdict = dict(store.claims(about, attr))
            verdict["about"] = about
            verdict["scope"] = scope
            out[f"{attr}@{about}"] = verdict
    return out


def _семейная_нота(роль: dict, семья_ответа: dict) -> str:
    if not роль:
        return ""
    if роль.get("role") == "family":
        return (
            f" СЕМЬЯ: у {роль['name']!r} {роль['variants_total']} вариант(а/ов) в базе "
            f"({', '.join(роль['variants'][:6])}{', …' if роль['variants_total'] > 6 else ''}); "
            f"их утверждения — в family_claims ({len(семья_ответа)}), каждое помечено "
            "вариантом и НЕ голосует в ответе о самой модели."
        )
    return (
        f" СЕМЬЯ: это вариант {роль['family_name']!r}; утверждения семьи — в "
        f"family_claims ({len(семья_ответа)}), помечены scope=family."
    )


def _ответ_семьи(name: str, attribute: str, семья_ответа: dict, роль: str) -> dict | None:
    """Ответ из утверждений семьи, когда своих нет. None — семья тоже молчит."""
    годные = [k for k, v in семья_ответа.items() if v.get("outcome") == PASS]
    спорные = [k for k, v in семья_ответа.items() if v.get("outcome") == FAIL]
    if not годные:
        return None
    о_ком = sorted({str(семья_ответа[k].get("about")) for k in годные})
    чьё = "вариантов семьи" if роль == "family" else "семьи"
    return {
        "outcome": PASS,
        "checked": claims_found(семья_ответа),
        # Как и у собственного ответа: спорное при `pass` — без единого
        # значения, то есть среди `unmeasured`, а не нарушение (check_headline).
        "violations": 0,
        "unmeasured": len(семья_ответа) - len(годные),
        "reason": REASON_ANSWERED_BY_FAMILY,
        "note": (
            f"о самой {name!r}{'.' + attribute if attribute else ''} не записано ничего; "
            f"ответ — из утверждений {чьё} ({', '.join(о_ком)}): {len(годные)} из "
            f"{len(семья_ответа)} в family_claims, каждое помечено, О КАКОМ ИМЕНИ оно. "
            "Это НЕ измерение спрошенной модели."
            + (f" Спорно: {', '.join(спорные)}." if спорные else "")
        ),
    }


def record(
    model: str,
    attribute: str,
    value: str,
    source_url: str,
    tier: str,
    stated_on: str,
    *,
    note: str = "",
    fix: str = "",
    read_directly: bool | None = None,
    witnessed: str = "",
    contra: bool | None = None,
    new_model: bool = False,
    asked_as: str = "",
    path: Path | None = None,
) -> dict:
    """Write one web finding into the fact base, with who said it and when.

    Every argument up to `stated_on` is required and none may be blank. A claim
    without a URL cannot be re-checked; a claim without a date cannot go stale;
    a claim without a tier would let a blog outrank a vendor document.

    :param tier: one of `TIERS`, but only three of them are yours to choose.

        `probe`, `paper` and `benchmark` say HOW the fact was obtained — the
        API was asked, a venue published a method — and no URL can tell anyone
        that, so you state them and they are taken as stated.

        `vendor`, `portal` and `blog` say WHOSE PAGE IT IS, and that is decided
        from the URL by `source_hosts.classify`, not by you. Passing one that
        the URL contradicts is refused rather than quietly corrected: a caller
        who believes `docs.example.com` is the vendor for this model and is
        wrong needs to find out, and a caller who is right needs the table
        updated. Silently overriding either would put the ladder back where it
        was on 2026-08-27, when `blog` held nine vendor pages.
    :param read_directly: True if you opened the page (or the API answered
        you), False if you know it only through somebody else's summary. Leave
        it None when you did not record it — that is a third state and it is
        not the same as False.
    :param stated_on: ISO date the SOURCE stated it, not today's date. Writing
        today's date for an old article is how a stale claim looks fresh.

    :returns: three outcomes. A rejected claim is `fail` and is not written.

    RECORDING SOMETHING ALREADY RECORDED IS AN UPDATE, NOT A SECOND SOURCE.
    A claim is `(model, attribute, value, source_url)`, and this appends a row
    that supersedes any earlier one with that key — which is how a fact known
    through a summary becomes one somebody opened, without the page counting
    twice. An append that would change nothing is skipped, so a script that
    replays a reading pass can be re-run without growing the file.

    If the page turns out not to say what was recorded, this is the wrong
    door: `withdraw` is, and it takes a reason.

    ОДНО ИМЯ — ОДНА МОДЕЛЬ И НА ЗАПИСИ (аудит ae94057, 2026-10-14). Имя
    проходит разрешение (`modelnames`): написание уже известной модели
    (`seedance2`, `kling-v3`, `ElevenLabs v3`) пишется под её каноническим id,
    а спрошенное написание сохраняется в поле строки `asked_as`. Имя, которое
    совпало с известным только через единственного соседа (`happyhorse` при
    `happyhorse_1_0` в базе), НЕ пишется: ответ называет соседа, и запись
    повторяется либо под его id, либо с `new_model=True`, если модель правда
    новая.

    :param new_model: явное «это новая модель», для имени, которое иначе было
        бы отвергнуто как, вероятно, написание соседа.
    :param asked_as: исходное написание, если вызывающий уже канонизировал
        имя сам (так делает `scripts/merge_model_ids.py`).
    """
    fields = {
        "model": str(model or "").strip(),
        "attribute": str(attribute or "").strip(),
        "value": str(value or "").strip(),
        "source_url": str(source_url or "").strip(),
        "tier": str(tier or "").strip().lower(),
        "stated_on": str(stated_on or "").strip(),
    }
    missing = [name for name, text in fields.items() if not text]
    if missing:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": len(missing),
            "unmeasured": 0,
            "note": (
                "nothing was written: " + ", ".join(missing) + " is required. "
                "A claim missing any of these cannot be re-checked later."
            ),
            "written": None,
        }

    target = path or DEFAULT_FACTS_PATH
    имя, отказ_имени = каноническое_имя(fields["model"], target, new_model=new_model)
    if отказ_имени:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": отказ_имени,
            "written": None,
        }
    спрошено_как = str(asked_as or "").strip()
    if имя != fields["model"]:
        спрошено_как = спрошено_как or fields["model"]
        fields["model"] = имя

    # НЕЗНАНИЕ — ЭТО ИСХОД, А НЕ ЗНАЧЕНИЕ (Р1). Проверка стоит РАНЬШЕ разбора
    # тира и адреса нарочно (П2): она стоит микросекунду и не зависит ни от
    # чего внешнего, а отвергает то, что портит уже записанное.
    пусто = не_ответ(fields["value"])
    if пусто:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": (
                f"ничего не записано: value {fields['value']!r} — это не факт, "
                f"а не-ответ ({пусто}). ИЗМЕРЕНО 2026-09-07: такая строка рядом "
                "с настоящим фактом переводит утверждение из pass в fail — "
                "«источники расходятся», — то есть отменяет измеренное. Если "
                "источник ничего не сказал про этот атрибут, не записывайте "
                "ничего: отсутствие строки И ЕСТЬ «никто не знает», и "
                "model_advice сообщит это третьим исходом. А если это НАСТОЯЩИЙ "
                "ответ («ограничений нет», «ничего не требуется»), напишите его "
                "словами — «none — no restrictions» проходит, голое «none» нет: "
                "по нему не отличить ответ от невыставленного поля."
            ),
            "written": None,
        }

    if fields["tier"] not in TIERS:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": f"tier {fields['tier']!r} is not one of {', '.join(TIERS)}",
            "written": None,
        }

    # Тир `operator` стоит третьим сверху — выше статьи и выше бенчмарка, — и
    # платит за это единственным условием: сказать, ЧТО ИМЕННО было запущено и
    # что вышло. Без этого запись отвергается, а не просто весит меньше.
    # «Модель держит текст» — мнение; «подали кадр с текстом, отрисованным
    # Pillow, текст дошёл без искажений» — факт, который кто-то может пойти и
    # опровергнуть. Ярлык нужен ровно затем, чтобы одно отличалось от другого.
    if fields["tier"] == TIER_OPERATOR and not str(witnessed).strip():
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": (
                "ничего не записано: тир operator требует поля witnessed — что "
                "запущено и что вышло, в наблюдаемых словах. Вывод без "
                "наблюдения это мнение, а тир для мнений уже есть, он "
                "называется blog"
            ),
            "written": None,
        }

    # У наблюдения оператора страницы нет и быть не может, поэтому требование
    # http-ссылки к нему не применяется: `source_url` несёт его собственную
    # отметку — дату разговора, номер задачи, путь к файлу.
    if fields["tier"] != TIER_OPERATOR and not fields["source_url"].startswith(
        ("http://", "https://")
    ):
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": f"source_url {fields['source_url']!r} is not a URL",
            "written": None,
        }

    # Who owns the page is read off the URL; how the fact was obtained is not.
    if fields["tier"] in IDENTITY_TIERS:
        owner = source_hosts.classify(
            fields["model"],
            fields["source_url"],
            vendor_tier=TIER_VENDOR,
            portal_tier=TIER_PORTAL,
            blog_tier=TIER_BLOG,
        )
        if owner != fields["tier"]:
            return {
                "outcome": FAIL,
                "checked": len(fields),
                "violations": 1,
                "unmeasured": 0,
                "note": (
                    f"tier {fields['tier']!r} does not match the URL: "
                    f"{source_hosts.host_of(fields['source_url']) or 'that host'} is "
                    f"{owner!r} for {fields['model']}. The URL decides the rung. If "
                    f"this host really is {fields['tier']} for this model, add it to "
                    "studio/selfrag/source_hosts.py and record again."
                ),
                "written": None,
            }

    # СТУПЕНЬ `paper` ТРЕБУЕТ ПРОВЕРЯЕМОГО АДРЕСА. Отказ, а не понижение: тир
    # здесь объявляет САМ пишущий, и подменить его молча значило бы решить за
    # него, чем является его находка. Сказать «дайте адрес статьи» дешевле, чем
    # потом гадать, статья это была или пересказ.
    if fields["tier"] == TIER_PAPER and not признак_статьи(fields["source_url"]):
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": (
                f"tier {TIER_PAPER!r} без признака статьи в адресе "
                f"{fields['source_url']!r}: ни известной площадки (arXiv, "
                "OpenReview, ACL, ACM, IEEE, CVF, Springer, MLR, NeurIPS, AAAI, "
                "USENIX, bioRxiv), ни DOI в пути, ни идентификатора arxiv. Сам "
                "по себе PDF признаком НЕ считается: у вендора в PDF лежат "
                "презентации. По такому адресу статью не перепроверить, а "
                "ступень метода берётся на слово. Дайте адрес самой статьи — "
                "или запишите это как другой тир."
            ),
            "written": None,
        }

    try:
        stated = date.fromisoformat(fields["stated_on"])
    except ValueError:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": f"stated_on {fields['stated_on']!r} is not an ISO date (YYYY-MM-DD)",
            "written": None,
        }
    if stated > date.today():
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": f"stated_on {fields['stated_on']} is in the future",
            "written": None,
        }

    # ФЛАГ ЧТЕНИЯ СВЕРЯЕТСЯ СО СВИДЕТЕЛЬСТВОМ (Е2). До 2026-09-05 `read_directly`
    # не сверялся НИ С ЧЕМ: можно было записать «я эту страницу открыл» про хост,
    # который в этом окружении закрыт политикой и не открывался ни разу.
    # Независимая проверка это и сделала — выдуманное утверждение прошло с
    # исходом `pass`. Журнал отказов у проекта уже есть; здесь он и спрашивается.
    #
    # Факт при этом НЕ отвергается: сам он может быть верен, неверно только
    # утверждение о чтении. Верим свидетельству, а не флагу, и говорим об этом
    # вслух в ноте — молча переписать чужое утверждение значило бы завести
    # третий способ соврать.
    прочитано = None if read_directly is None else bool(read_directly)
    поправка = ""

    # ТИР `probe` ТОЖЕ СВЕРЯЕТСЯ СО СВИДЕТЕЛЬСТВОМ (Е2). «Их API ответил» —
    # утверждение о СОБЫТИИ, и с 2026-09-07 у события есть журнал
    # (`probe.PROBES_PATH`, пишется в момент ответа). До журнала сверять было
    # не с чем, и тир брался на слово — та же дыра, что была у флага чтения.
    #
    # ФАКТ НЕ ОТВЕРГАЕТСЯ, И ЭТО НЕ МЯГКОСТЬ. Зонд мог быть выполнен на другой
    # машине, в другой сессии или руками через curl — журнал этого окружения
    # такого не видит. Отказ потерял бы настоящий факт, а потерянный факт не
    # запишет уже никто; пометка же едет вместе с источником и видна читателю.
    if fields["tier"] == TIER_PROBE and not probe.зонд_был(fields["source_url"]):
        поправка += (
            " [ТИР probe ЗАЯВЛЕН, НО ЗОНДА В ЖУРНАЛЕ НЕТ: ни одного обращения к "
            f"{source_hosts.host_of(fields['source_url']) or 'этому хосту'} в "
            "probes.jsonl не записано. Строка оставлена — зонд мог быть выполнен "
            "вне этого окружения, — но «их API ответил» здесь ничем не "
            "подтверждено]"
        )
    if прочитано and fetch.закрыт_политикой(fields["source_url"]):
        прочитано = False
        # `+=`, А НЕ `=`. Приёмка 2026-09-07: здесь стояло присваивание, и оно
        # затирало пометку про зонд — ровно в самом подозрительном сочетании,
        # где заявлены И зонд, И чтение закрытого хоста, читатель базы видел
        # только одну претензию из двух.
        поправка += (
            " [ЗАЯВЛЕНО ЧТЕНИЕ, НО ХОСТ ЗАКРЫТ ПОЛИТИКОЙ: последнее записанное "
            "состояние хоста — отказ, открыть его в этом окружении было нечем; "
            "флаг чтения снят]"
        )

    # Annotated because `read_directly` is the one non-string value in the row;
    # without it the whole dict widens and `row["model"]` stops being a str.
    row: dict[str, str | bool | None] = {
        **fields,
        "note": str(note or "") + поправка,
        "fix": str(fix or ""),
        "read_directly": прочитано,
        "witnessed": str(witnessed or ""),
        # ЗНАК, ОБЪЯВЛЕННЫЙ ЯВНО: True — плохая новость, False — хорошая, None —
        # не объявлен, и тогда его выведут по имени атрибута. Заведено
        # 2026-09-05 после того, как отрицательный оплаченный замер, записанный
        # под именем `holds_identity`, сделал план ложно ГОДНЫМ.
        "contra": None if contra is None else bool(contra),
    }
    if спрошено_как and спрошено_как != fields["model"]:
        # Исходное написание не теряется: оно стоит в строке рядом с
        # каноническим id и читается глазами и `grep`-ом. В ключ утверждения
        # оно не входит — модель одна.
        row["asked_as"] = спрошено_как
    key = claim_key(fields["model"], fields["attribute"], fields["value"], fields["source_url"])
    before = {claim_key(f.model, f.attribute, f.value, f.source_url): f for f in load_facts(target)}
    standing = before.get(key)
    unchanged = standing is not None and _same_claim(standing, row)

    if not unchanged:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    after = store_for(target).claims(fields["model"], fields["attribute"])
    if unchanged:
        what = "already stood exactly like this, so nothing was appended"
    elif standing is None:
        what = "written as a new claim"
    else:
        what = f"supersedes the row that stood before it ({_diff(standing, row)})"
    return {
        "outcome": PASS,
        "checked": len(fields),
        "violations": 0,
        "unmeasured": 0,
        # ПОМЕТКА ЕДЕТ И В ОТВЕТ, А НЕ ТОЛЬКО В ФАЙЛ. Приёмка 2026-09-07:
        # `record` отвечал `pass` и «written as a new claim», а претензия к
        # записи оставалась в файле — то есть тот, кто записывал, её не видел
        # и поправить не мог.
        "note": (
            f"{what}. {row['model']}.{row['attribute']} now stands at "
            f"{after['outcome']!r} across {after.get('checked', 0)} source(s)."
            + (
                f" ИМЯ: спрошено как {row['asked_as']!r}, записано под каноническим "
                f"id {row['model']!r} — это та же модель."
                if row.get("asked_as")
                else ""
            )
            + (f" ПОМЕТКА К ЭТОЙ ЗАПИСИ:{поправка}" if поправка else "")
        ),
        "written": None if unchanged else row,
        "superseded": None if standing is None else _as_row(standing),
        "claims_now": after,
    }


def каноническое_имя(
    model: str, path: Path | None = None, *, new_model: bool = False
) -> tuple[str, str]:
    """(имя для записи, отказ). Отказ пуст — писать под возвращённым именем.

    Развилка вынесена функцией (Т5): от неё зависит, в какой карман ляжет
    строка, и тестом она проверяется без записи файла.

    * Область (`*`, `eleven-*`) не разрешается: это не модель.
    * Свёртка совпала с известной моделью — каноническое написание группы
      (`FactStore.canonical`).
    * Вендор впереди спрошенного, а без него имя известно
      (`bytedance-seedance-…` при `seedance-…`) — то же, правило детерминированное.
    * Совпало только с ЕДИНСТВЕННЫМ СОСЕДОМ (без вендора у спрошенного, или
      как единственная версия) — отказ с указателем, если не `new_model`.
    * Не совпало ни с чем — новая модель, пишется как названа.
    """
    имя = str(model or "").strip()
    if not имя or имя.endswith("*"):
        return имя, ""
    store = store_for(path or DEFAULT_FACTS_PATH)
    решение = store.resolve(имя)
    if решение.outcome != PASS:
        return имя, ""
    канон = store.canonical(имя) or решение.canonical
    if решение.how == modelnames.HOW_EXACT:
        return (имя if канон.lower() == имя.lower() else канон), ""
    if решение.how == modelnames.HOW_VENDOR:
        return канон, ""
    if new_model:
        return имя, ""
    return имя, (
        f"ничего не записано: {имя!r} в базе нет, но {решение.note}. Если это та "
        f"же модель — запишите под {канон!r}; если это ДРУГАЯ, новая модель — "
        "повторите с new_model=True. Угадывать здесь нельзя: ошибка приписывает "
        "модели чужие наблюдения."
    )


def _as_row(fact: Fact) -> dict:
    """A stored fact in the shape `record` writes, so the two can be compared."""
    return {
        "model": fact.model,
        "attribute": fact.attribute,
        "value": fact.value,
        "source_url": fact.source_url,
        "tier": fact.tier,
        "stated_on": fact.stated_on,
        "note": fact.note,
        "fix": fact.fix,
        "read_directly": fact.read_directly,
        "contra": fact.contra,
    }


#: What `record` may change about a standing claim. Model, attribute, value and
#: URL are excluded because changing one of those makes it a different claim.
#:
#: `contra` СТОИТ ЗДЕСЬ НАМЕРЕННО: объявить знак у строки, записанной без него,
#: — это НОВОЕ знание о ней, и такая запись обязана дописываться, а не считаться
#: «уже стоит ровно так».
MUTABLE_FIELDS: tuple[str, ...] = (
    "tier",
    "stated_on",
    "note",
    "fix",
    "read_directly",
    "contra",
)


def _same_claim(standing: Fact, row: dict) -> bool:
    """True when appending `row` would tell a reader nothing new."""
    return all(_as_row(standing)[name] == row.get(name) for name in MUTABLE_FIELDS)


def _diff(standing: Fact, row: dict) -> str:
    """Name the fields the new row changes, so the caller sees what moved."""
    was = _as_row(standing)
    moved = [f"{n}: {was[n]!r} -> {row.get(n)!r}" for n in MUTABLE_FIELDS if was[n] != row.get(n)]
    return "; ".join(moved) if moved else "nothing"


def withdraw(
    model: str,
    attribute: str,
    value: str,
    source_url: str,
    reason: str,
    *,
    path: Path | None = None,
) -> dict:
    """Take back a claim its own source does not make, and say why.

    The door for the thing this base was built wrong around: a claim recorded
    from somebody's summary, whose page, once opened, says nothing of the sort.
    MEASURED 2026-08-27, the day the vendor hosts were unblocked: `wavespeed.ai/`
    was cited for what Veo 3.1 is best for and the page does not contain the
    string "Veo" at all.

    Deleting the line would be the obvious move and it is the wrong one — it
    loses the fact that anybody believed this, and the next research pass
    re-derives it from the same summary. So the withdrawal is APPENDED, carries
    its reason, and `load_facts` drops the claim from what the base asserts
    while the file keeps the argument.

    :param reason: required, and not decorative. "wrong" tells the next reader
        nothing; "the page does not mention Veo" tells them what was checked.
    :returns: three outcomes. Withdrawing a claim nobody recorded is
        `could not measure`, never `pass` — a caller who misspelled the model
        would otherwise be told their withdrawal worked.
    """
    fields = {
        "model": str(model or "").strip(),
        "attribute": str(attribute or "").strip(),
        "value": str(value or "").strip(),
        "source_url": str(source_url or "").strip(),
        "reason": str(reason or "").strip(),
    }
    missing = [name for name, text in fields.items() if not text]
    if missing:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": len(missing),
            "unmeasured": 0,
            "note": (
                "nothing was withdrawn: " + ", ".join(missing) + " is required. "
                "A withdrawal names the exact claim it takes back and says why."
            ),
            "withdrawn": None,
        }

    target = path or DEFAULT_FACTS_PATH
    key = claim_key(fields["model"], fields["attribute"], fields["value"], fields["source_url"])
    standing = {
        claim_key(f.model, f.attribute, f.value, f.source_url): f for f in load_facts(target)
    }
    if key not in standing:
        return {
            "outcome": UNMEASURED,
            "checked": 1,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"no claim {fields['model']}.{fields['attribute']} = {fields['value']!r} "
                f"from {fields['source_url']} stands in the base, so nothing was "
                "withdrawn. Check the model, the attribute, the exact value and the "
                "exact URL: all four identify a claim."
            ),
            "withdrawn": None,
        }

    row: dict[str, str | bool] = {
        "model": fields["model"],
        "attribute": fields["attribute"],
        "value": fields["value"],
        "source_url": fields["source_url"],
        "withdrawn": True,
        "note": fields["reason"],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    after = store_for(target).claims(fields["model"], fields["attribute"])
    return {
        "outcome": PASS,
        "checked": 1,
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"withdrawn: {fields['reason']} — {fields['model']}.{fields['attribute']} "
            f"now stands at {after['outcome']!r} across {after.get('checked', 0)} source(s)."
        ),
        "withdrawn": row,
        "claims_now": after,
    }


#: Тиры, у которых дата — это ДАТА ПУБЛИКАЦИИ, а не срок годности. Статья и
#: бенчмарк опубликованы однажды и говорят одно и то же всегда; «поищи в сети и
#: запиши, что найдёшь» для них — работа, которую нельзя сделать.
#:
#: ИЗМЕРЕНО 2026-09-02: из 49 строк, объявленных протухшими, 21 (20 статей и
#: 1 бенчмарк) именно такая, то есть 43% очереди — работа впустую. Остальные
#: 28 — цены площадок и вендорские спеки, и они протухают по-настоящему.
PUBLISHED_TIERS: frozenset[str] = frozenset({TIER_PAPER, TIER_BENCHMARK})


def nota_bez_dostupnosti(нота: str, полная: str, доступность: dict) -> str:
    """Главная нота без ПОВТОРА ноты доступности, но с её вердиктом.

    Отдельной функцией (Т5): развилка «что именно вырезать» иначе живёт внутри
    сборки словаря и тестом недостижима, а вырезать лишнее здесь значит
    потерять вторую ось из строки, которую читают первой.
    """
    # Вердикт в главной ноте УЖЕ стоит — полный ответ пишет «Availability ...
    # says 'could not measure': <нота>». Дописать его ещё раз значило бы
    # получить «says 'could not measure': 'could not measure'»; поймано
    # чтением собственной выдачи сразу после правки.
    del доступность  # вердикт берётся из уже написанного текста, не отсюда
    return нота.replace(полная, "см. поле availability.").strip()


#: ПОТОЛОК КРАТКОЙ ФОРМЫ в байтах UTF-8 — так, как её печатает сервер
#: (`json.dumps(..., indent=2, ensure_ascii=False)`). Валидатор G11,
#: 2026-10-14: краткий ответ по `minimax-h3` был 26.6 КБ — уже не «пятая часть
#: полной», а целая полная пятилетней давности. ВЫБРАНО 6 КБ: пять кандидатов
#: в сравнении — 30 КБ, около 8 тысяч токенов. Сверх потолка режутся строки
#: НИЗШЕГО приоритета, и счёт срезанного печатается (Р2).
BRIEF_MAX_BYTES = 6144

#: Длина одного значения в краткой форме. Спорные значения не режутся НИКОГДА:
#: спор — то, ради чего инструмент, и усечённая сторона спора — уже не сторона.
КРАТКО_ЗНАЧЕНИЕ = 160
#: Сколько значений показать у неспорного атрибута (их счёт печатается).
КРАТКО_ЗНАЧЕНИЙ = 3
#: Сколько отказов показать в краткой форме (счёт печатается).
КРАТКО_ОТКАЗОВ = 3


def _коротко(текст: object, n: int = КРАТКО_ЗНАЧЕНИЕ) -> str:
    строка = str(текст if текст is not None else "")
    # По фразе или слову, не посреди слова (`l10n.clip`, 7-й круг).
    return строка if len(строка) <= n else l10n.clip(строка, n)


def размер(ответ: object) -> int:
    """Байты ответа так, как его печатает сервер."""
    return len(json.dumps(ответ, ensure_ascii=False, indent=2, default=str).encode("utf-8"))


def brief(model: str, attribute: str = "", *, path: Path | None = None, lang: str = "") -> dict:
    """Та же выдача, но в размере, который не съедает ответ пользователю.

    ЗАЧЕМ. ИЗМЕРЕНО 2026-09-02: полный ответ по `minimax-h3` — 23 751 символ.
    Инструкция сервера велит спросить базу о КАЖДОМ кандидате перед
    сравнением, и пять кандидатов стоят больше, чем сам ответ.

    ПОТОЛОК (валидатор G11, 2026-10-14): краткая форма сама доросла до 26 КБ.
    Теперь она не больше `BRIEF_MAX_BYTES`: по атрибуту — одно главное
    значение (или все стороны спора и `recommended`), ступень, свежесть, число
    источников; `family_claims` — сводкой по вариантам; что не влезло —
    счётом и списком имён в `omitted`, и как получить больше — в `full_answer`.

    Краткая форма — ВИД на полную (Е1): она строится из неё же, поэтому
    разойтись они не могут. Что НЕ выбрасывается ни при каких условиях: исход
    и его причина, отметка о споре источников (`contested` целиком) и ось
    доступности.
    """
    полный = advise(model, attribute, path=path)
    # ЯЗЫК — ДО СЖАТИЯ (аудит 4-го круга): краткая форма режет ноты
    # (`_коротко`), а обрезанный посреди слова шаблон таблица `l10n` не узнаёт.
    # Пустой `lang` — ответ на языке шаблонов, как раньше.
    if lang:
        полный = l10n.localise_payload(полный, lang)
    кратко: dict = {
        ключ: полный[ключ]
        for ключ in (
            "outcome",
            "checked",
            "violations",
            "unmeasured",
            "reason",
            "note",
            "asked_as",
            "lifecycle",
            "possibly_stale_note",
            "other_versions",
            "near",
        )
        if полный.get(ключ) not in (None, "", [])
    }
    доступность = полный.get("availability") or {}
    кратко["availability"] = {
        "outcome": доступность.get("outcome"),
        "note": _коротко(доступность.get("note"), 300),
    }
    нота = str(кратко.get("note") or "")
    полная_нота_доступности = str(доступность.get("note") or "")
    if полная_нота_доступности and полная_нота_доступности in нота:
        нота = nota_bez_dostupnosti(нота, полная_нота_доступности, доступность)
    кратко["note"] = _коротко(нота, 1500)
    кратко["claims"] = _сжать_утверждения(полный.get("claims") or {})
    семья = dict(полный.get("family") or {})
    семья.pop("variant_roles", None)
    кратко["family"] = семья
    семейные = полный.get("family_claims") or {}
    кратко["family_claims"] = _сжать_утверждения(семейные)
    кратко["family_claims_summary"] = _сводка_семьи(семейные)
    if полный.get("substitutes"):
        кратко["substitutes"] = {
            k: {
                **v,
                "substitute_for": полный["substitutes"][k].get("substitute_for"),
                "counts_as_answer": False,
            }
            for k, v in _сжать_утверждения(полный["substitutes"]).items()
        }
        кратко["substitutes_note"] = полный.get("substitutes_note")
    if полный.get("variant_slices"):
        кратко["variant_slices"] = {
            k: {
                "value": v.get("value"),
                "tier": v.get("tier"),
                "derivation": "DERIVED, not measured",
            }
            for k, v in полный["variant_slices"].items()
        }
    resolved = dict(полный.get("resolved_as") or {})
    if resolved:
        resolved["note"] = _коротко(resolved.get("note"), 200)
        resolved["spellings"] = list(resolved.get("spellings") or [])[:8]
        кратко["resolved_as"] = resolved
    отказы = [
        строка.get("value") if isinstance(строка, dict) else строка
        for строка in (полный.get("failure_modes") or [])
    ]
    кратко["failure_modes"] = [_коротко(о, 120) for о in отказы[:КРАТКО_ОТКАЗОВ]]
    кратко["failure_modes_total"] = len(отказы)
    кратко["contested"] = полный.get("contested")
    # Список помеченных атрибутов — в полной форме; здесь счёт, а пометка
    # стоит у каждого показанного атрибута (`possibly_stale: true`).
    кратко["possibly_stale_total"] = len(полный.get("possibly_stale") or [])
    кратко["class_findings_total"] = полный.get("class_findings_total")
    кратко["full_answer"] = (
        "это КРАТКАЯ форма: разбор источников, ноты и находки о классе лежат в "
        "полной выдаче — позовите тот же инструмент с `full=True` (или с "
        "`attribute=<имя>`, чтобы получить один атрибут целиком)"
    )
    if not lang:
        return _в_потолок(кратко, полный, attribute)
    кратко = l10n.localise_payload(кратко, lang)
    return l10n.localise_payload(_в_потолок(кратко, полный, attribute), lang)


def _сводка_семьи(семейные: dict) -> dict:
    """Счёт утверждений семьи по имени, о котором они: вариант -> атрибутов."""
    сводка: dict[str, int] = {}
    for разбор in семейные.values():
        about = str(разбор.get("about") or "")
        сводка[about] = сводка.get(about, 0) + 1
    return dict(sorted(сводка.items()))


def _приоритет(ключ: str, разбор: dict, спрошено: str) -> tuple:
    """Что резать последним: спорное, спрошенное, сильная ступень, свежее."""
    атрибут = str(ключ).split("@", 1)[0]
    return (
        0 if разбор.get("outcome") == FAIL else 1,
        0 if спрошено and attrfamily.семья_имени(атрибут) == attrfamily.семья(спрошено) else 1,
        TIERS.index(разбор.get("best_tier")) if разбор.get("best_tier") in TIERS else len(TIERS),
        str(ключ),
    )


#: Байт под поле `size_bytes` в отступе сервера: `,\n  "size_bytes": 6144`.
_МЕСТО_ПОД_РАЗМЕР = 24


def _в_потолок(кратко: dict, полный: dict, attribute: str) -> dict:
    """Срезать строки низшего приоритета, пока ответ больше `BRIEF_MAX_BYTES`.

    Порядок среза: сначала утверждения семьи (контекст), потом свои — от
    слабой ступени к сильной; спорные свои — никогда. Срезанное считается и
    называется в `omitted` (Р2): молчаливая обрезка читается как «это всё».
    Размер меряется ВМЕСТЕ с `omitted` — счёт срезанного тоже занимает место.
    """
    очередь: list[tuple[str, str]] = []
    for раздел in ("family_claims", "claims"):
        утверждения: dict = кратко[раздел]
        for ключ in sorted(
            утверждения,
            key=lambda k: _приоритет(k, утверждения[k], attribute),
            reverse=True,
        ):
            if not (раздел == "claims" and утверждения[ключ].get("outcome") == FAIL):
                очередь.append((раздел, ключ))
    срезано: dict[str, list[str]] = {"claims": [], "family_claims": []}

    def пометить() -> None:
        if not any(срезано.values()):
            return
        кратко["omitted"] = {
            "claims": len(срезано["claims"]),
            "family_claims": len(срезано["family_claims"]),
            "claims_names": sorted(срезано["claims"])[:20],
            "how_to_get_more": (
                "full=True for everything, or attribute=<name> for one attribute in full"
            ),
        }
        # Счёт целиком остаётся: срезан ВИД, не знание.
        кратко["claims_total"] = len(полный.get("claims") or {})
        кратко["family_claims_total"] = len(полный.get("family_claims") or {})

    for раздел, ключ in очередь:
        # `size_bytes` (до 4 цифр и ключ) печатается следом — место под него.
        if размер(кратко) + _МЕСТО_ПОД_РАЗМЕР <= BRIEF_MAX_BYTES:
            break
        del кратко[раздел][ключ]
        срезано[раздел].append(ключ)
        пометить()
    # Размер — вместе с собственным полем: число меряет то, что напечатают.
    кратко["size_bytes"] = 0
    for _ in range(3):
        кратко["size_bytes"] = размер(кратко)
    return кратко


#: Сколько строк каждого списка отдаёт краткая форма `stale`. ВЫБРАНО: аудит
#: ae94057 измерил 755 тысяч знаков на `days=30` — ответ, который съедает
#: разговор целиком. Пятнадцать строк на список плюс счёт по моделям — это
#: очередь, которую читают; всё остальное — по `full=True`.
STALE_TOP = 15


def _сжать_утверждения(утверждения: dict) -> dict:
    """Утверждения в краткой форме: сравнимые величины без разбора источников.

    Неспорный атрибут: главное значение (`value`, усечённое), до
    `КРАТКО_ЗНАЧЕНИЙ` значений и их счёт. Спорный: ВСЕ значения дословно и
    `recommended` — что брать по лестнице ступеней, с правилом.
    """
    сжатые: dict = {}
    for атрибут, разбор in утверждения.items():
        строки = разбор.get("claims") or []
        источники = [и for строка in строки for и in (строка.get("sources") or [])]
        значения = list(разбор.get("values") or [строка.get("value") for строка in строки])
        спорно = разбор.get("outcome") == FAIL
        сжатое: dict = {
            "outcome": разбор.get("outcome"),
            "values": значения if спорно else [_коротко(v) for v in значения[:КРАТКО_ЗНАЧЕНИЙ]],
            "best_tier": min(
                (строка.get("best_tier", "") for строка in строки),
                key=lambda t: TIERS.index(t) if t in TIERS else len(TIERS),
                default="",
            ),
            "sources": len({str(и.get("url") or "") for и in источники}),
            "newest": max((str(и.get("stated_on") or "") for и in источники), default=""),
        }
        if len(значения) > КРАТКО_ЗНАЧЕНИЙ and not спорно:
            сжатое["values_total"] = len(значения)
        совет = разбор.get("recommended") or {}
        if совет:
            сжатое["recommended"] = {
                "value": совет.get("value"),
                "tier": совет.get("tier"),
                "rule": совет.get("rule"),
            }
        if разбор.get("possibly_stale"):
            сжатое["possibly_stale"] = True
        for ключ in ("about", "scope"):
            if ключ in разбор:
                сжатое[ключ] = разбор[ключ]
        if разбор.get("scoped_elsewhere"):
            сжатое["scoped_elsewhere"] = len(разбор["scoped_elsewhere"])
        сжатые[атрибут] = сжатое
    return сжатые


def stale(
    *,
    days: int = STALE_AFTER_DAYS,
    path: Path | None = None,
    model: str = "",
    full: bool = False,
    top: int | None = None,
    offset: int = 0,
) -> dict:
    """Which claims are old enough to need a fresh look on the web.

    A claim with no date is counted as unmeasured, not as fresh. That is the
    whole reason `record` insists on a date.

    :param days: возраст, после которого утверждение протухло; целое ≥ 0.
        Отрицательное и не-целое — отказ (`fail`, ничего не проверено), а не
        тихая подмена: `days=-5` раньше объявлял протухшей ВСЮ базу.
    :param model: только эта модель (все её написания, `modelnames`).
        Неизвестное имя — третий исход с подсказкой, а не пустая «всё свежо».
    :param full: все поля строк. По умолчанию — КРАТКАЯ форма: счёт по каждому
        списку, счёт по моделям и первые `top` строк каждого списка.
    :param top: строк на список: по умолчанию `STALE_TOP` в краткой форме и
        `STALE_FULL_PAGE` в полной.
    :param offset: с какой строки каждого списка начинать (страница). Полная
        форма ТОЖЕ постранична (валидатор G11: `days=0, full=True` — 762 КБ):
        следующая страница названа в `next_offset`.
    """
    if isinstance(days, bool) or not isinstance(days, int) or days < 0:
        return {
            "outcome": FAIL,
            "checked": 0,
            "violations": 1,
            "unmeasured": 0,
            "note": f"days={days!r} — нужно целое число ≥ 0; ничего не проверено",
            "stale": [],
            "undated": [],
            "published_and_old": [],
            "blocked_source": [],
        }
    if isinstance(top, bool) or not isinstance(top, int) or top < 1:
        top = STALE_FULL_PAGE if full else STALE_TOP
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        offset = 0
    target = path or DEFAULT_FACTS_PATH
    facts = load_facts(target)
    имя = str(model or "").strip()
    if имя:
        склад = store_for(target)
        свои = set(склад.spellings(имя))
        if not свои:
            соседи = склад.near(имя)
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": (
                    f"{имя!r} не найдено в базе фактов ни в одном написании — стареть нечему"
                    + (f"; близкие имена: {', '.join(соседи)}" if соседи else "")
                ),
                "near": соседи,
                "stale": [],
                "undated": [],
                "published_and_old": [],
                "blocked_source": [],
            }
        facts = [f for f in facts if f.model.lower() in свои]
    итог = _stale_rows(facts, days)
    if имя:
        итог["model"] = имя
    return _stale_page(итог, top, offset) if full else _stale_brief(итог, top, offset)


#: Строк на список в ПОЛНОЙ форме `stale`, если `top` не задан. ВЫБРАНО 100:
#: строка полной формы — около 250 байт, четыре списка по сто — около 100 КБ,
#: против 762 КБ всей очереди одним ответом (валидатор G11).
STALE_FULL_PAGE = 100

_STALE_LISTS = ("stale", "undated", "published_and_old", "blocked_source")


def _stale_page(итог: dict, top: int, offset: int) -> dict:
    """Полная форма постранично: строки целиком, но не больше `top` на список."""
    счёт = {ключ: len(итог.get(ключ) or []) for ключ in _STALE_LISTS}
    if offset == 0 and all(n <= top for n in счёт.values()):
        return итог
    страница = dict(итог)
    for ключ in _STALE_LISTS:
        страница[ключ] = list(итог.get(ключ) or [])[offset : offset + top]
    страница["counts"] = счёт
    страница["offset"] = offset
    дальше = offset + top
    страница["next_offset"] = дальше if any(n > дальше for n in счёт.values()) else None
    страница["truncated"] = True
    страница["full_answer"] = (
        f"ПОЛНАЯ форма постранично: строки {offset}–{дальше - 1} каждого списка, полный "
        "счёт — в `counts`; следующая страница — offset=next_offset."
    )
    return страница


def _stale_brief(итог: dict, top: int, offset: int = 0) -> dict:
    """Краткая форма: счёт целиком, строки — `top` каждого списка с `offset` (Р2)."""
    списки = _STALE_LISTS
    кратко = dict(итог)
    счёт = {ключ: len(итог.get(ключ) or []) for ключ in списки}
    по_моделям: dict[str, int] = {}
    for ключ in ("stale", "undated", "blocked_source"):
        for row in итог.get(ключ) or []:
            по_моделям[str(row["model"])] = по_моделям.get(str(row["model"]), 0) + 1
    for ключ in списки:
        кратко[ключ] = list(итог.get(ключ) or [])[offset : offset + top]
    кратко["counts"] = счёт
    кратко["by_model"] = dict(sorted(по_моделям.items(), key=lambda kv: (-kv[1], kv[0]))[:top])
    кратко["models_with_work"] = len(по_моделям)
    обрезано = offset > 0 or any(счёт[ключ] > offset + top for ключ in списки)
    if обрезано:
        кратко["offset"] = offset
        кратко["next_offset"] = (
            offset + top if any(счёт[ключ] > offset + top for ключ in списки) else None
        )
    кратко["truncated"] = обрезано
    if обрезано:
        кратко["full_answer"] = (
            f"КРАТКАЯ форма: в каждом списке не больше {top} строк, полный счёт — в "
            "`counts`. Все строки — с full=True; одна модель — с model=<имя>."
        )
    return кратко


def _stale_rows(facts: list[Fact], days: int) -> dict:
    """Разбор возраста по уже отобранным строкам. Полная форма."""
    if not facts:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "the fact base is empty: there is nothing to age",
            "stale": [],
            "undated": [],
            "published_and_old": [],
            "blocked_source": [],
        }

    old: list[dict] = []
    undated: list[dict] = []
    published: list[dict] = []
    for fact in facts:
        age = fact.age_days
        row = {
            "model": fact.model,
            "attribute": fact.attribute,
            "value": fact.value,
            "source_url": fact.source_url,
            "tier": fact.tier,
            "stated_on": fact.stated_on,
            "age_days": age,
        }
        if age is None:
            undated.append(row)
        elif age > days:
            # ДАТА ПУБЛИКАЦИИ — НЕ ИЗНОС. Найдено чтением выдачи (П3,
            # 2026-09-02): из 49 «протухших» строк 21 оказалась СТАТЬЁЙ или
            # бенчмарком, и первая — arXiv:2103.00020 от 2021 года. Статья
            # сегодня говорит ровно то же, что и в день публикации; «поищи в
            # сети и запиши, что найдёшь» для неё — работа, которую нельзя
            # сделать. А очередь, где такой работы 43%, читается по диагонали,
            # и вместе с ней по диагонали читаются 28 строк, которые ДЕЙСТВИТЕЛЬНО
            # протухли: цены площадок и вендорские спеки.
            #
            # Не выброшено, а ОТДЕЛЕНО: статья 2021 года о модели, которая с тех
            # пор изменилась, вводит в заблуждение по-настоящему. Но лечится это
            # не перечитыванием статьи, а измерением модели, и в ноте сказано
            # именно так.
            (published if fact.tier in PUBLISHED_TIERS else old).append(row)

    # СТРАНИЦА, КОТОРУЮ НЕЧЕМ ОТКРЫТЬ, — НЕ РАБОТА В ОЧЕРЕДИ. Та же болезнь,
    # что и с датой публикации десятью строками выше: очередь наполняется
    # строками, по которым сказанное ею действие выполнить нельзя, и тогда
    # её читают по диагонали вместе с теми строками, где работа настоящая.
    #
    # «Поищи в сети и запиши, что найдёшь» для хоста, закрытого политикой
    # окружения, — работа, которую нельзя сделать, и обходить запрет нечем
    # (Ц3). Строка НЕ выбрасывается: утверждение стареет по-прежнему, и
    # лечится оно двумя способами, названными в ноте, — попросить доступ
    # (хост уже в журнале отказов) или измерить модель зондом.
    #
    # Журнал отказов читается ФАЙЛОМ, сети здесь не появляется (Т4).
    закрытые = [row for row in old if fetch.закрыт_политикой(str(row["source_url"]))]
    old = [row for row in old if row not in закрытые]

    old.sort(key=lambda row: -(row["age_days"] or 0))
    published.sort(key=lambda row: -(row["age_days"] or 0))
    закрытые.sort(key=lambda row: -(row["age_days"] or 0))
    if old or undated:
        return {
            "outcome": FAIL,
            "checked": len(facts),
            "violations": len(old),
            # ЗАКРЫТЫЕ СЧИТАЮТСЯ, А НЕ ИСЧЕЗАЮТ (Р2). Приёмка 2026-09-07:
            # строки уносились из `old` и не досчитывались никуда, поэтому
            # ноль работы над закрытыми хостами читался как ноль проблем.
            "unmeasured": len(undated) + len(закрытые),
            "note": (
                f"{len(old)} claim(s) older than {days} days and {len(undated)} "
                f"with no date at all, out of {len(facts)} checked. Search the "
                "web for these and call `record_model_fact` with what you find. "
                f"Separately, {len(published)} claim(s) rest on a PUBLISHED "
                "source (paper or benchmark) older than that: a paper does not "
                "rot, so re-reading it changes nothing. If one of those models "
                "has moved since, the answer is a fresh measurement of the "
                "model, not a fresh reading of the paper."
                + (
                    f" Ещё {len(закрытые)} строк(и) стоят на хостах, закрытых "
                    "политикой окружения: перечитать их здесь НЕЧЕМ, и обходить "
                    "запрет нельзя. Под ключом `blocked_source`; лечится "
                    "просьбой о доступе или замером модели, а не поиском."
                    if закрытые
                    else ""
                )
            ),
            "stale": old,
            "undated": undated,
            "published_and_old": published,
            "blocked_source": закрытые,
        }

    # «ВСЁ СВЕЖО» НАД ПРОТУХШИМИ СТРОКАМИ — ЭТО НЕПРАВДА, А НЕ ТРЕТИЙ ИСХОД.
    # Приёмка 2026-09-07 воспроизвела: две строки the-decoder.com от 2024 года,
    # обе на закрытом хосте — прибор отвечал `pass` и «all 2 claim(s) are
    # within 90 days». Пока закрытых нет, это латентно; растёт с каждым
    # закрываемым хостом. Р1: не «годно», а «не смогли», и сказано, чем.
    if закрытые:
        return {
            "outcome": UNMEASURED,
            "checked": len(facts),
            "violations": 0,
            "unmeasured": len(закрытые),
            "note": (
                f"из {len(facts)} утверждений протухших вне закрытых хостов нет, "
                f"НО {len(закрытые)} строк(и) старше {days} дней стоят на хостах, "
                "закрытых политикой окружения: перечитать их здесь НЕЧЕМ, и "
                "обходить запрет нельзя. Это не «всё свежо» — это «свежесть "
                "части строк не проверить». Лечится просьбой о доступе или "
                "замером модели."
            ),
            "stale": [],
            "undated": [],
            "published_and_old": published,
            "blocked_source": закрытые,
        }

    return {
        "outcome": PASS,
        "checked": len(facts),
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"all {len(facts)} claim(s) are within {days} days"
            + (
                f"; {len(published)} rest on a published source older than that, "
                "which is a date and not decay"
                if published
                else ""
            )
        ),
        "stale": [],
        "undated": [],
        "published_and_old": published,
        "blocked_source": закрытые,
    }
