"""Цена из прозы в числа — и честное «не смогли» там, где не вышло.

ЗАЧЕМ

ИЗМЕРЕНО 2026-08-31: 82 ценовых факта под 21 именем атрибута, машиночитаемых
из них 17. Остальное — проза, которая несёт настоящую информацию и потому не
может быть выброшена:

    «12 credits/s ($0.12/s at $0.01 per credit)»
    «40 credits/s with audio, 20 credits/s without»
    «36 cr/s at 480p/720p, 40 cr/s at 1080p, 150 cr/s at 4K»
    «2 credits upfront, then 2 credits per 6 seconds»

Проверка бюджета — самый дешёвый оракул валидатора пайплайнов: ноль сети, ноль
агентов, ловит «цепочка дороже названного» ещё до всякой генерации. На такой
базе она не работает вообще.

ПОЧЕМУ РАЗБОРЩИК, А НЕ ПЕРЕПИСЫВАНИЕ ФАКТОВ

Значение факта — это то, что СКАЗАЛ источник. Переписать его в число значит
подменить свидетельство пересказом, и тогда «12 credits/s ($0.12/s at $0.01
per credit)» потеряет курс кредита, по которому число и получено. Проза
остаётся, разбор живёт рядом.

ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ НАРОЧНО

Не складывает кредиты с долларами. `price_per_second` у Runway — это кредиты
вендора, `price_per_second_usd` у Kling — доллары; это НЕ разные написания
одного, и сложить их значит получить число, которое ничего не означает.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

#: Валюты и единицы, которые встречаются в базе. Список закрытый: незнакомая
#: единица обязана давать третий исход, а не подставляться в сумму.
UNITS = ("usd", "credits")

#: Что за что платят. Тоже закрытый список — «за что» определяет, можно ли
#: вообще складывать два числа.
#: `1m_tokens` СТОИТ ПЕРЕД `token` НАМЕРЕННО: поиск идёт по вхождению, и имя
#: `price_per_million_input_usd` обязано находить миллион, а не токен.
PER = (
    "1m_tokens",
    "second",
    "image",
    "generation",
    "run",
    "minute",
    "megapixel",
    "1000_chars",
    # «За знак» (`price_per_character_usd_via_elevenlabs`, 2026-10-14): та же
    # мера, что «за 1000 знаков», в тысячу раз мельче. СТОИТ ПОСЛЕ `1000_chars`:
    # поиск по вхождению, и `price_per_1000_characters` — это тысяча знаков.
    "character",
    "token",
)

#: «За миллион токенов» в ТЕКСТЕ значения. Заведено 2026-09-05 по независимому
#: аудиту: строка `gpt-5.price_per_token` = «$1.25 per 1M input tokens …»
#: разбиралась как 1.25 доллара ЗА ТОКЕН — ошибка в миллион раз, — и валидатор
#: на ней отвергал шаг словами «цена выше потолка».
#:
#: ЗДЕСЬ НЕ ДЕЛЯТ НА МИЛЛИОН. Мы не знаем, к какому именно токену вендор отнёс
#: цену (вход, выход, кэш — в этой же строке три разных), и придумывать
#: пересчёт значило бы заменить одно уверенное неверное число другим. Меняется
#: «за что»: сравнение с потолком «за токен» честно становится несравнимым,
#: то есть третьим исходом вместо ложного отказа.
_ЗА_МИЛЛИОН = re.compile(
    r"per\s*(?:1\s*m\b|1[\s,]?000[\s,]?000|million)(?!\s*(?:characters?|chars?)\b)", re.I
)

_MONEY = re.compile(r"\$\s*(\d+(?:\.\d+)?)")
#: Ведущее число строки: то, что источник поставил ПЕРВЫМ, когда единица уже
#: названа именем атрибута. Число обязано кончаться разделителем, а не буквой:
#: иначе «360p 0.025/0.035» отдаёт 360 — ровно тот дефект, ради которого этот
#: разборщик и писался. `~` перед числом источники ставят как «около».
_LEAD = re.compile(r"^\s*~?\s*(\d+(?:\.\d+)?)(?=[\s,;/]|$)")
_CREDITS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:credits?|cr)\b", re.I)
_BARE = re.compile(r"^\s*\$?\s*(\d+(?:\.\d+)?)\s*$")

#: Слова, после которых число перестаёт быть базовой ценой и становится
#: условием: минимум за генерацию, доплата за звук, надбавка за разрешение.
CONDITIONAL = re.compile(
    r"\b(minimum|min\b|upfront|then|with audio|without|at \d+p|at \d+K|per \d+)", re.I
)


#: Слова исходов ЭТОГО модуля. Заведены 2026-09-04 именами, а не литералами:
#: сумму цены пайплайна считает планировщик, и ему нужно то же слово, что
#: пишет сюда разборщик. Первый прогон это и поймал — планировщик подставил
#: своё английское `could not measure`, и одно поле заговорило на двух языках
#: в зависимости от ветки (Е1: одно знание — одно место).
ГОДНО = "годно"
НЕ_СМОГЛИ = "не смогли"


@dataclass(frozen=True)
class Price:
    """Разобранная цена. `outcome` — три исхода, как везде."""

    amount: float | None
    unit: str
    per: str
    conditional: bool
    outcome: str
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "unit": self.unit,
            "per": self.per,
            "conditional": self.conditional,
            "outcome": self.outcome,
            "note": self.note,
        }


def unit_and_per(attribute: str) -> tuple[str, str]:
    """Единица и «за что» — из ИМЕНИ атрибута, а не из текста значения.

    Имя атрибута — то, о чём договорились при записи; текст значения пишет
    источник как хочет. Брать единицу из текста значит доверять чужому
    форматированию в вопросе, где ошибка стоит неверной суммы.
    """
    # ХВОСТ `_via_<провайдер>` — ИМЯ ПРОДАВЦА, а не единица (2026-10-15, аудит
    # импортёра LiteLLM): `price_per_character_usd_via_runwayml` находил «run»
    # в «runwayml» раньше, чем «character», и цена за знак читалась за прогон.
    a = re.sub(r"_via_[a-z0-9_]+$", "", attribute.lower())
    единица = "usd" if a.endswith("_usd") or "usd" in a else ""
    за = ""
    # Имена вида `price_per_million_input_usd` называют «за что» ЧЕСТНО, и
    # раньше теряли его вовсе: слова `million` в `PER` не было, шесть строк
    # базы уходили в третий исход. Проверяется до общего цикла, потому что
    # такое имя содержит и `million`, и (в других строках) `token`.
    if "million" in a or "_1m_" in a or a.endswith("_1m"):
        return единица, "1m_tokens"
    if "1000_chars" not in a and re.search(r"\d+_char", a):
        # `price_per_1000_characters_usd` — не «за знак»: число знаков названо,
        # но не нашим написанием. Читать его «за знак» значило бы ошибиться в
        # тысячу раз; не читается вовсе (сторож — `test_price_naming`).
        return единица, ""
    for кандидат in PER:
        if кандидат in a:
            за = кандидат
            break
    return единица, за


def parse(value: str, attribute: str = "") -> Price:
    """Разобрать одно ценовое значение. Не разобралось — третий исход.

    Порядок проверок не случаен: доллары в тексте сильнее кредитов, потому что
    строка «12 credits/s ($0.12/s at $0.01 per credit)» несёт ОБА, и доллар в
    ней — уже пересчитанный вендором, то есть ближе к тому, что платят.
    """
    текст = str(value or "").strip()
    единица, за = unit_and_per(attribute)
    # ТЕКСТ ПЕРЕБИВАЕТ ИМЯ ТОЛЬКО ЗДЕСЬ, и это исключение названо вслух.
    # Обычно «за что» берётся у имени атрибута (см. `unit_and_per`), потому что
    # имя — то, о чём договорились при записи. Но «per 1M tokens» в тексте —
    # не форматирование, а ДРУГАЯ ЕДИНИЦА, и молчаливо считать её токеном
    # значит ошибиться в миллион раз.
    if за in ("token", "") and _ЗА_МИЛЛИОН.search(текст):
        за = "1m_tokens"
    условие = bool(CONDITIONAL.search(текст))

    if not текст:
        return Price(None, единица, за, условие, "не смогли", "значение пустое")

    голое = _BARE.match(текст)
    if голое:
        # ВАЛЮТА НЕ ДОДУМЫВАЕТСЯ. Раньше здесь стояло `единица or "usd"`:
        # голое число без единого признака валюты — ни в имени атрибута, ни в
        # тексте — объявлялось долларами и шло сравниваться с потолком
        # заказчика. ИЗМЕРЕНО 2026-09-05: на живой базе таких строк ОДНА из
        # 229 (`model_facts.jsonl`, `price_per_1000_chars` = `0.1`), то есть
        # сегодня это почти не стоит денег — и ровно поэтому проходило бы и
        # дальше, пока не появился бы вендор с ценой в юанях.
        #
        # Третий исход, а не отказ: число прочитано, непрочитанной осталась
        # валюта, и сказать «цена не годится» значило бы соврать в другую
        # сторону. Само число печатается в ноте — чтобы читающий видел, о чём
        # спорить, и мог назвать валюту руками.
        сумма = float(голое.group(1))
        if not единица and "$" not in текст:
            return Price(
                None,
                "",
                за,
                False,
                НЕ_СМОГЛИ,
                f"валюта не названа: ни имя атрибута, ни текст не говорят, в чём {сумма}",
            )
        return Price(сумма, единица or "usd", за, False, "годно", "одно число")

    # Ведущее число сильнее доллара В ТЕКСТЕ, но только когда единицу назвало
    # ИМЯ атрибута. ИЗМЕРЕНО 2026-09-02 на 82 ценовых строках живой базы: без
    # этой ветки 22 строки вида «0.04 per image» при `price_per_image_usd`
    # уходили в «не смогли», а ещё у 4 доллар из хвоста строки перебивал цену
    # из её начала («0.08/sec; $0.48 for a 6s video» -> 0.48 вместо 0.08).
    if единица == "usd":
        ведущее = _LEAD.match(текст)
        if ведущее:
            return Price(
                float(ведущее.group(1)),
                "usd",
                за,
                условие,
                "годно",
                "ведущее число при единице из имени атрибута"
                + ("; есть условия" if условие else ""),
            )

    деньги = _MONEY.search(текст)
    if деньги:
        return Price(
            float(деньги.group(1)),
            "usd",
            за,
            условие,
            "годно",
            "доллары из текста" + ("; есть условия" if условие else ""),
        )

    кредиты = _CREDITS.search(текст)
    if кредиты:
        return Price(
            float(кредиты.group(1)),
            "credits",
            за,
            условие,
            "годно",
            "кредиты вендора — В ДОЛЛАРЫ НЕ ПЕРЕВОДЯТСЯ без курса"
            + ("; есть условия" if условие else ""),
        )

    return Price(None, единица, за, условие, "не смогли", "числа в тексте не нашли")


def total(prices: list[Price]) -> dict[str, Any]:
    """Нижняя граница суммы. Никогда одним числом (правило Е3).

    Складываются только величины в ОДНОЙ единице и за одно и то же. Всё
    прочее печатается отдельно как неизвестное — потому что сумма, в которой
    треть слагаемых неизвестна, читается как полная, если не сказать иначе.
    """
    по_единицам: dict[tuple[str, str], float] = {}
    неизвестно = 0
    условных = 0
    for p in prices:
        # «ЗА ЧТО» — ЧАСТЬ ВЕЛИЧИНЫ, А НЕ ПОДПИСЬ К НЕЙ. Цена, у которой оно не
        # выведено, до 2026-09-05 попадала в общий мешок `(usd, "")` и
        # СКЛАДЫВАЛАСЬ: «$3 за минуту» с «$0.5 за картинку» давали одно число,
        # а рядом печаталось «неизвестных слагаемых 0». ИЗМЕРЕНО на живой базе:
        # 34 годные цены из 214 не имеют «за что», то есть каждая шестая.
        # Сумма, в которой шестая часть слагаемых — про разное, читается как
        # полная (Е3), и это дороже, чем честное «не сложили».
        if p.outcome != "годно" or p.amount is None or not p.unit or not p.per:
            неизвестно += 1
            continue
        if p.conditional:
            условных += 1
        по_единицам[(p.unit, p.per)] = по_единицам.get((p.unit, p.per), 0.0) + p.amount
    исход = (
        "годно" if по_единицам and not неизвестно else ("не смогли" if not по_единицам else "годно")
    )
    части = ", ".join(f"{v:g} {u} за {за or '?'}" for (u, за), v in sorted(по_единицам.items()))
    return {
        "outcome": исход,
        "lower_bound": по_единицам,
        "unknown": неизвестно,
        "conditional": условных,
        "note": (
            f"не менее {части or '—'}; неизвестных слагаемых {неизвестно}"
            + (f", из них с условиями {условных}" if условных else "")
        ),
    }


# --------------------------------------------------------------------------
# ТАБЛИЦА СТАВОК: тариф × разрешение × «за что» (заведено 2026-10-14)
#
# ЗАЧЕМ. `parse` отвечает ОДНИМ числом, и это число — первое в строке. Для
# строк-таблиц это неверный ответ, а не грубый: независимый валидатор показал
#
#     veo-3.1  «Standard $0.40/s at 720p and 1080p, $0.60/s at 4k; Fast $0.10/s
#               (720p), $0.12/s (1080p) …; Lite $0.05/s (720p), $0.08/s (1080p)»
#
# — план брал 0.40 и объявлял бюджет $10 на 40 с превышенным, хотя Fast 1080p
# стоит $4.80, а Lite — $3.20. И `luma-ray-3.2` «5s: $0.15 at 540p … $1.20 at
# 1080p» шла за 0.15 на ролике 1080p — в восемь раз дешевле правды.
#
# ЧТО ЗДЕСЬ. Строка разбирается в СПИСОК ставок, у каждой — тариф, разрешение,
# звук и «за что»; потом `estimate` берёт ту, что подходит брифу (разрешение,
# звук, длительность), и считает деньги шага. Кредиты по-прежнему не
# переводятся НИКОГДА: курс — решение вендора.
#
# ЧЕГО ЗДЕСЬ НЕТ НАРОЧНО: суждения о качестве тарифа. Какой из Fast/Lite
# годится заказчику, решает он; прибор только показывает все тарифы рядом и
# говорит, какой укладывается в бюджет.
# --------------------------------------------------------------------------

#: Слова, которыми вендор называет ТАРИФ одной модели. Закрытый словарь:
#: неизвестное слово в начале куска тарифом не становится (иначе «Your
#: request» стал бы тарифом). КОНСТАНТА-РЕШЕНИЕ, ВЫБРАНО по ценовым строкам
#: живой базы 2026-10-14 (veo-3.1, luma-ray, flux-3, ideogram-character).
TIER_WORDS: tuple[str, ...] = (
    "standard",
    "fast",
    "lite",
    "turbo",
    "pro",
    "hdr",
    "draft",
    "drafts",
    "quality",
    "balanced",
    "relaxed",
    "ultra",
    "max",
    "preview",
)

#: Режимы работы, которыми вендор подписывает кусок таблицы (`t2v/i2v $0.17/s
#: hd; v2v $0.43/s`). Кусок, помеченный ТОЛЬКО чужим режимом, не цена шага.
MODE_WORDS: tuple[str, ...] = ("t2v", "i2v", "v2v")

#: Разрешение словами -> короткая сторона кадра в пикселях.
RESOLUTION_WORDS: dict[str, int] = {
    "4k": 2160,
    "2k": 1440,
    "uhd": 2160,
    "fhd": 1080,
    "full hd": 1080,
    "hd": 720,
    "sd": 480,
}

_RES = re.compile(
    r"(?<![\w.])(?:(\d{3,4})\s*p\b|(\d{3,4})\s*[x×]\s*(\d{3,4})|([248])\s*k\b|(fhd|uhd|full hd|hd|sd)\b)",
    re.I,
)
#: Сумма в строке: доллары, кредиты или голое число (последнее — только там,
#: где в куске нет ни одного `$`, а единицу назвало имя атрибута).
_AMOUNT = re.compile(
    r"\$\s*~?\s*(\d+(?:\.\d+)?)"
    r"|~?(\d+(?:\.\d+)?)\s*\$"
    r"|(\d+(?:\.\d+)?)\s*(?:credits?|cr)\b"
    r"|(?<![\w.$-])~?(\d+(?:\.\d+)?)(?![\w.%])",
    re.I,
)
#: Количество, которое НЕ сумма: «40 seconds», «1–7 supported», «5s».
_НЕ_СУММА_ПОСЛЕ = re.compile(
    r"^\s*(?:-?\s*)?(?:seconds?|secs?|s\b|minutes?|mins?|characters?|chars?|frames?|fps|images?|"
    r"megapixels?|mp\b|tokens?|k\b|m\b|x\b|supported|second\b|credit\b)",
    re.I,
)
_ПРИМЕР = re.compile(r"^\s*(?:for example|e\.g\.|a\s+\d|so\s+\d)", re.I)
_ЗВУК_ДА = re.compile(r"with audio|audio on|with sound|sound on", re.I)
_ЗВУК_НЕТ = re.compile(r"no audio|audio off|without(?: audio| sound)?\b|sound off", re.I)
#: Слова, после которых ставка — не вся цена: минимум, доплата, «если».
_УСЛОВИЕ_СТАВКИ = re.compile(r"\b(?:minimum|upfront|if|when|rounded|rolling|billed)\b", re.I)
_ЛЕГЕНДА_ЗВУКА = re.compile(r"\(\s*(?:no audio|audio off)\s*/\s*(?:with audio|audio on)\s*\)", re.I)


@dataclass(frozen=True)
class Rate:
    """Одна ставка из строки-таблицы. `per` — из `PER` или пусто."""

    amount: float
    unit: str
    per: str
    tier: str = ""
    resolutions: tuple[int, ...] = ()
    audio: bool | None = None
    #: Ставка «за прогон», который покрывает столько секунд («5s: $0.15»,
    #: «$0.2 for videos up to 40 seconds»).
    run_seconds: float | None = None
    #: Доплата за каждую секунду сверх `run_seconds` («then $0.005 per second»).
    over_per_second: float | None = None
    #: Разовая плата за прогон сверх посекундной («2 credits upfront»).
    upfront: bool = False
    #: Доплата СВЕРХ прогона («then $0.005 per second», «for longer videos»):
    #: приклеивается к предыдущей ставке-прогону, а не встаёт отдельной.
    over: bool = False
    mode: str = ""
    conditional: bool = False
    source: str = ""


def _разрешения(текст: str) -> tuple[int, ...]:
    """Все разрешения в куске текста, короткой стороной."""
    итог: list[int] = []
    for м in _RES.finditer(текст):
        if м.group(1):
            итог.append(int(м.group(1)))
        elif м.group(2):
            итог.append(min(int(м.group(2)), int(м.group(3))))
        elif м.group(4):
            итог.append(RESOLUTION_WORDS[f"{м.group(4)}k"])
        elif м.group(5):
            итог.append(RESOLUTION_WORDS[м.group(5).lower()])
    # «720p-1080p» — диапазон: обе ступени и всё между ними мы не выдумываем.
    return tuple(dict.fromkeys(итог))


def вид_доплаты(голова: str) -> str:
    """'over', если текст после суммы говорит о доплате сверх прогона."""
    return "over" if re.search(r"additional|then|longer|beyond", голова[:40]) else ""


def _за_что(после: str, по_умолчанию: str) -> tuple[str, float, float | None, str]:
    """«За что» ставки по тексту ПОСЛЕ суммы: (per, множитель суммы, секунд в прогоне, вид).

    Множитель нужен там, где вендор назвал не ту меру, что у нас: «per 100
    characters» — это десятая доля «за 1000 знаков», «per 30 seconds» — за
    тридцать секунд. Вид — '' | 'over' | 'upfront' | 'minimum' | 'skip'.
    """
    п = после.lower()
    голова = п[:60]
    if re.match(r"^\s*(?:credit\s+)?minimum", голова) or re.match(
        r"^\s*(?:credits?\s+)?minimum", голова
    ):
        return "", 1.0, None, "minimum"
    if re.match(r"^\s*(?:credits?\s+)?upfront", голова):
        return "run", 1.0, None, "upfront"
    # «per 1K characters» — ТЫСЯЧА ЗНАКОВ, а не токены (2026-10-15, по
    # независимому валидатору): строка вендора `eleven_v3` «$0.08 per 1K
    # characters (API)» уходила в правило токенов ниже и давала пустой список —
    # то есть цена ПРЯМОГО маршрута пропадала, и смета брала пересказ
    # агрегатора. Проверяется ДО правила токенов, потому что то ловит «per 1K».
    м = re.match(r"^\s*(?:/|per)\s*1\s*([km])\s*(?:characters?|chars?)\b", голова)
    if м:
        return "1000_chars", 1.0 if м.group(1) == "k" else 0.001, None, вид_доплаты(голова)
    if (
        re.match(r"^\s*(?:/\s*1\s*[km]\b|per\s+1\s*[km]\b|/\s*1k|per\s+(?:1m|million))", голова)
        or "token" in голова[:30]
    ):
        return "token", 1.0, None, "skip"
    if re.match(r"^\s*per\s+(?:clone|created voice|credit)", голова):
        return "", 1.0, None, "skip"
    вид = вид_доплаты(голова)
    м = re.match(r"^\s*(?:/|per|for every|a|each)?\s*(\d+)\s*(?:seconds?|s)\b", голова)
    if м and not re.match(r"^\s*for\b", голова):
        return "second", 1.0 / float(м.group(1)), None, вид
    м = re.match(r"^\s*(?:/|per|for every|every)?\s*(\d+)\s*(?:characters?|chars?)\b", голова)
    if м:
        return "1000_chars", 1000.0 / float(м.group(1)), None, вид
    if re.match(
        r"^[^$]{0,30}?(?:/\s*s(?:ec)?\b|per\s+(?:\w+\s+){0,2}seconds?|per\s+sec\b|for every (?:\w+\s+){0,2}seconds?|/sec)",
        голова,
    ):
        return "second", 1.0, None, вид
    if re.match(r"^[^$]{0,30}?(?:/\s*min\b|per\s+(?:\w+\s+){0,2}minutes?)", голова):
        return "minute", 1.0, None, вид
    if re.match(r"^[^$]{0,20}?per\s+(?:\w+\s+)?(?:processed\s+)?megapixel", голова):
        return "megapixel", 1.0, None, вид
    if re.match(r"^[^$]{0,20}?(?:per|/)\s*(?:\w+\s+)?image", голова):
        return "image", 1.0, None, вид
    м = re.match(
        r"^[^$]{0,25}?for (?:a |videos? )?(?:up to )?(\d+)\s*-?\s*(?:s|sec|seconds?)\b", голова
    )
    if м:
        return "run", 1.0, float(м.group(1)), вид
    м = re.match(r"^\s*per\s+(?:\d{3,4}p\s+)?(\d+)\s*s\s+video", голова)
    if м:
        return "run", 1.0, float(м.group(1)), вид
    if re.match(r"^[^$]{0,25}?per\s+(?:video\s+)?(?:run|generation|video)\b", голова):
        return "run", 1.0, None, вид
    return по_умолчанию, 1.0, None, вид


def rates(value: str, attribute: str = "") -> list[Rate]:
    """Строка цены -> список ставок. Пустой список — «не смогли», а не «бесплатно».

    Порядок ставок — порядок строки: вендор ставит флагманский тариф первым,
    и `estimate` этим пользуется, чтобы назвать тариф ПО УМОЛЧАНИЮ.
    """
    текст = str(value or "").strip()
    if not текст:
        return []
    единица_имени, за_имени = unit_and_per(attribute)
    if за_имени in ("token", "") and _ЗА_МИЛЛИОН.search(текст):
        return []
    # «Your request will cost $X» без «за что» — цена ЗАПРОСА, то есть прогона:
    # так площадка пишет цену генерации, и другого прочтения у фразы нет.
    if not за_имени and re.search(r"request will (?:cost|be priced)", текст, re.I):
        за_имени = "run"
    if за_имени in ("token", "1m_tokens"):
        return []
    легенда = bool(_ЛЕГЕНДА_ЗВУКА.search(текст))
    # Легенда «(no audio / with audio)» описывает ПАРЫ чисел, а не последнее из
    # них: вынимается из текста, чтобы её «no audio» не прилипло к соседу.
    текст = _ЛЕГЕНДА_ЗВУКА.sub(" ", текст)
    итог: list[Rate] = []
    # Предложения-ПРИМЕРЫ («For example, a 5s video will cost $0.70», «A
    # 5-second 480p clip costs $0.40») — арифметика вендора над той же
    # ставкой, а не вторая ставка.
    предложения = [п for п in re.split(r"(?<=[.!?])\s+(?=[A-Z])", текст) if not _ПРИМЕР.match(п)]
    for предложение in предложения:
        for кусок in re.split(r";", предложение):
            for r in _ставки_куска(кусок, единица_имени, за_имени, легенда, итог):
                # ДОПЛАТА СВЕРХ ПРОГОНА живёт часто в соседнем предложении
                # («$0.2 for videos up to 40 seconds. For longer videos ...
                # $0.005 per second») — и приклеивается к прогону, а не
                # становится второй, дешёвой ставкой «за секунду».
                прогон = next(
                    (
                        i
                        for i in range(len(итог) - 1, -1, -1)
                        if итог[i].run_seconds and итог[i].over_per_second is None
                    ),
                    None,
                )
                if r.over and r.per == "second" and прогон is not None:
                    итог[прогон] = Rate(**{**итог[прогон].__dict__, "over_per_second": r.amount})
                    continue
                итог.append(r)
    return итог


def _ставки_куска(
    кусок: str, единица_имени: str, за_имени: str, легенда: bool, прежние: list[Rate] | None = None
) -> list[Rate]:
    прежние = прежние or []
    низ = кусок.lower()
    голова = низ.lstrip(" ,—-")
    tier = ""
    mode = ""
    # «v4 Turbo $0.04»: номер версии перед словом тарифа тарифом не мешает
    # (иначе Turbo ложился в безымянный тариф рядом с основной ценой).
    м = re.match(r"^(?:v\d+(?:\.\d+)?\s+)?([a-z0-9/,]+)\b", голова)
    if м:
        слово = м.group(1)
        if слово in TIER_WORDS:
            tier = "draft" if слово == "drafts" else слово
        elif any(р in слово.split("/") for р in MODE_WORDS):
            mode = слово
    # «5s:» / «HDR 5s» в начале куска — цена за прогон столько-то секунд.
    м_прогон = re.match(r"^(?:[a-z]+\s+)?(\d+)\s*s\b\s*:?", голова)
    прогон_куска = float(м_прогон.group(1)) if м_прогон else None
    есть_доллар = "$" in кусок
    найдены = [
        м
        for м in _AMOUNT.finditer(кусок)
        if not (м.group(4) and (есть_доллар or единица_имени != "usd" and not единица_имени))
    ]
    # Голое число — только при единице из имени атрибута и без `$` в куске.
    найдены = [
        м
        for м in найдены
        if not (м.group(4) and (есть_доллар or единица_имени != "usd"))
        and not _НЕ_СУММА_ПОСЛЕ.match(кусок[м.end() :])
        and not re.match(r"^\s*[–-]\s*\d", кусок[м.end() :])
        and not (м.group(4) and прогон_куска is not None and float(м.group(4)) == прогон_куска)
    ]
    ставки: list[Rate] = []
    for i, м in enumerate(найдены):
        конец_след = найдены[i + 1].start() if i + 1 < len(найдены) else len(кусок)
        начало_пред = найдены[i - 1].end() if i > 0 else 0
        после = кусок[м.end() : конец_след]
        до = кусок[начало_пред : м.start()]
        if re.match(r"^\s*per credit", после, re.I):
            continue
        if м.group(1) or м.group(2):
            сумма, единица = float(м.group(1) or м.group(2)), "usd"
        elif м.group(3):
            сумма, единица = float(м.group(3)), "credits"
        else:
            сумма, единица = float(м.group(4)), единица_имени
        за, множитель, прогон, вид = _за_что(после, за_имени)
        if вид in ("skip", "minimum") or not единица:
            continue
        # «with TURBO» после суммы — тариф этой ставки.
        м_тариф = re.search(r"with\s+([a-z]+)", после, re.I)
        тариф = tier
        if м_тариф and м_тариф.group(1).lower() in TIER_WORDS:
            тариф = м_тариф.group(1).lower()
        # Разрешение: «at 720p», «(720p)», «for 720p» после суммы — или
        # «720p $0.08», «480p at $0.08» вплотную перед ней.
        разрешения: tuple[int, ...] = ()
        м_после = re.search(r"(?:\bat\b|\bfor\b|\()\s*([^$;]*)", после, re.I)
        if м_после:
            разрешения = _разрешения(
                м_после.group(1).split(",")[0]
                if "(" not in м_после.group(0)
                else м_после.group(1).split(")")[0]
            )
        if not разрешения:
            м_сразу = re.match(
                r"^\s*/\s*s(?:ec)?\s+(fhd|uhd|hd|\d{3,4}\s*p|[248]\s*k)\b", после, re.I
            )
            if м_сразу:
                разрешения = _разрешения(м_сразу.group(1))
        if not разрешения:
            хвост_до = до[-24:]
            м_до = re.search(
                r"((?:\d{3,4}\s*p|\d{3,4}\s*[x×]\s*\d{3,4}|[248]\s*k|fhd|uhd|hd)\b)\s*(?:at|-|–|:|costs?)?\s*~?\$?\s*$",
                хвост_до,
                re.I,
            )
            if м_до:
                разрешения = _разрешения(м_до.group(1))
            elif до.strip() in ("/", "or") and ставки:
                разрешения = ставки[-1].resolutions
        звук: bool | None = None
        около = после[:40]
        if _ЗВУК_НЕТ.search(около):
            звук = False
        elif _ЗВУК_ДА.search(около):
            звук = True
        if легенда and звук is None:
            звук = до.strip() == "/"
        сверх = вид == "over" or bool(
            re.search(r"\b(?:then|longer|additional|beyond|plus)\b", до, re.I)
        )
        ставки.append(
            Rate(
                amount=round(сумма * множитель, 6),
                unit=единица,
                per="run"
                if прогон_куска is not None and за in ("", "run", за_имени) and за != "second"
                else за,
                tier=тариф,
                resolutions=разрешения,
                audio=звук,
                run_seconds=прогон
                if прогон is not None
                else (прогон_куска if прогон_куска is not None and за != "second" else None),
                upfront=вид == "upfront",
                over=сверх,
                mode=mode,
                conditional=bool(_УСЛОВИЕ_СТАВКИ.search(после[:60])),
                source=кусок.strip()[:120],
            )
        )
    return _по_порядку(_режим_куска(низ, ставки), кусок, прежние)


#: «in `pro` mode», «Creative mode», «In precise mode»: РЕЖИМ, которым вендор
#: подписывает часть таблицы. Становится тарифом ставки.
_РЕЖИМ_ВЕНДОРА = re.compile(r"(?:^|\bin\s+)`?([a-z][a-z0-9-]*)`?\s+mode\b", re.I)
#: Режим, который ДОРОЖЕ обычного («10 times of the normal price», «costs
#: more», «doubles»): его ставка — условие, а не цена по умолчанию.
_РЕЖИМ_ДОРОЖЕ = re.compile(r"\b(?:\d+(?:\.\d+)?\s*(?:times|x)\b|more\b|doubles?\b|double\b)", re.I)


def _режим_куска(низ: str, ставки: list[Rate]) -> list[Rate]:
    """Ставки куска, подписанного режимом вендора, получают этот режим ТАРИФОМ.

    ЗАЧЕМ (2026-10-15, независимый валидатор). `bytedance-upscaler`: «Processing
    in `pro` mode makes the price 10 times of the normal price ($0.072/s, …,
    $0.288/s …)». Без этой ветки pro-ставки ложились в безымянный тариф рядом с
    обычными, и 1080p оценивался по pro-4K — $0.288/s вместо $0.0072/s, в сорок
    раз дороже правды. Режим, который назван ДОРОЖЕ обычного, — условие
    (`conditional`): тарифом по умолчанию он не становится никогда, потому что
    у планировщика по умолчанию — безымянный тариф.
    """
    м = _РЕЖИМ_ВЕНДОРА.search(низ.lstrip(" ,—-("))
    if not м or not ставки:
        return ставки
    слово = м.group(1).lower()
    if слово in MODE_WORDS:
        return ставки
    дороже = bool(_РЕЖИМ_ДОРОЖЕ.search(низ))
    return [
        Rate(
            **{
                **r.__dict__,
                "tier": r.tier or слово,
                "conditional": r.conditional or дороже,
            }
        )
        for r in ставки
    ]


def _по_порядку(ставки: list[Rate], кусок: str, прежние: list[Rate]) -> list[Rate]:
    """«$a, $b, $c for 1080p, 2K, 4K respectively» — разрешения ПО ПОРЯДКУ.

    ЗАЧЕМ (2026-10-15, независимый валидатор). Список разрешений после
    последней суммы прилипал к ней одной («$0.288/s for 1080p» — а это 4K), и
    1080p получал цену 4K. Здесь i-я сумма получает i-е разрешение. Если списка
    нет («Creative mode costs more at each tier: $0.20, $0.35, and $0.79 per
    second respectively»), берутся разрешения стольких же ПРЕДЫДУЩИХ ставок
    строки, по порядку, — «each tier» отсылает к ним. Не сошлось число — не
    сопоставляется ничего (выдумывать пары хуже, чем оставить без разрешения).
    «За что» у сумм списка общее: его называет последняя («per second»).
    """
    if not ставки or not re.search(r"\brespectively\b", кусок, re.I):
        return ставки
    последняя_сумма = list(_AMOUNT.finditer(кусок))
    хвост = кусок[последняя_сумма[-1].end() :] if последняя_сумма else ""
    хвост = re.split(r"\brespectively\b", хвост, maxsplit=1, flags=re.I)[0]
    разрешения: list[tuple[int, ...]] = [(р,) for р in _разрешения(хвост)]
    if not разрешения:
        с_кадром = [r.resolutions for r in прежние if r.resolutions]
        разрешения = с_кадром[-len(ставки) :] if len(с_кадром) >= len(ставки) else []
    if len(разрешения) != len(ставки):
        return ставки
    за = next((r.per for r in reversed(ставки) if r.per), "")
    return [
        Rate(**{**r.__dict__, "resolutions": разрешения[i], "per": r.per or за})
        for i, r in enumerate(ставки)
    ]


@dataclass(frozen=True)
class Need:
    """Что шаг должен выдать: от этого зависит, какая ставка из таблицы — его."""

    seconds: float | None = None
    #: Короткая сторона заказанного кадра (1080 для 1080x1920). None — не назван.
    resolution: int | None = None
    #: Нужен ли звук из самой модели. None — шагу всё равно.
    audio: bool | None = None
    #: Знаков текста (для синтеза речи). None — не знаем.
    chars: float | None = None
    images: float = 1.0
    megapixels: float = 1.0
    #: Предел одного прогона модели: ролик длиннее режется на клипы.
    max_run_seconds: float | None = None
    #: Режим шага (`t2v`, `i2v`, `v2v`), чтобы чужой кусок таблицы не стал ценой.
    mode: str = ""
    #: На сколько ШОТОВ режется `seconds` (2026-10-15): три шота по 5 с — три
    #: прогона, даже если прогон модели покрывает 10 с. 1 — ролик одним куском.
    shots: int = 1


@dataclass(frozen=True)
class Option:
    """Сколько стоит шаг на одном тарифе: число, тариф, разрешение и расчёт словами."""

    usd: float
    tier: str
    resolution: int | None
    formula: str
    conditional: bool = False


#: Сколько знаков в секунде речи. КОНСТАНТА-РЕШЕНИЕ, ВЫБРАНО 15: дикторская
#: речь 140–160 слов в минуту по ~6 знаков с пробелом. Это ОЦЕНКА объёма
#: текста, а не цена: она печатается в расчёте, чтобы её можно было оспорить.
CHARS_PER_SECOND = 15.0


def _подходит_звук(r: Rate, нужно: bool | None) -> int:
    """0 — подходит, 1 — о звуке не сказано, 2 — не тот звук."""
    if нужно is None or r.audio is None:
        return 0 if r.audio is None or нужно is None else 1
    return 0 if r.audio == нужно else 2


def _подходит_кадр(r: Rate, нужно: int | None) -> tuple[int, int] | None:
    """(штраф, выбранное разрешение) или None, если ставка кадр не даёт."""
    if not r.resolutions:
        return (1, 0) if нужно is not None else (0, 0)
    if нужно is None:
        return (0, min(r.resolutions))
    if нужно in r.resolutions:
        return (0, нужно)
    выше = [р for р in r.resolutions if р > нужно]
    if выше:
        return (2, min(выше))
    # Заказанного кадра в таблице нет и выше нет: считается по наибольшему, что
    # модель отдаёт, — до заказанного кадр поднимает апскейл (шаг плана), а
    # «цена не считается» здесь была бы неправдой о том, что модель стоит.
    return (3, max(r.resolutions))


def _деньги(r: Rate, need: Need) -> tuple[float, str] | None:
    """Стоимость шага по одной ставке и расчёт словами. None — не на что умножать."""
    сек = need.seconds
    if r.per == "second":
        if сек is None:
            return None
        return r.amount * сек, f"{сек:g} с × {r.amount:g} usd/с"
    if r.per == "minute":
        if сек is None:
            return None
        return r.amount * сек / 60.0, f"{сек:g} с × {r.amount:g} usd/мин ÷ 60"
    if r.per in ("run", "generation"):
        if сек and need.shots > 1:
            # ШОТЫ — ОТДЕЛЬНЫЕ ПРОГОНЫ: прогон не склеивает два шота, поэтому
            # число прогонов — шоты × прогонов на шот, а не ceil(всего / прогон).
            на_шот = сек / need.shots
            покрывает = r.run_seconds or need.max_run_seconds
            if r.run_seconds and r.over_per_second is not None:
                лишние = max(0.0, на_шот - r.run_seconds)
                за_шот = r.amount + лишние * r.over_per_second
                return (
                    за_шот * need.shots,
                    f"{need.shots} шот(ов) × ({r.amount:g} usd за первые {r.run_seconds:g} с"
                    f" + {лишние:g} с × {r.over_per_second:g} usd/с)",
                )
            прогонов_на_шот = math.ceil(на_шот / покрывает) if покрывает else 1
            прогонов = need.shots * прогонов_на_шот
            return r.amount * прогонов, (
                f"{need.shots} шот(ов) по {на_шот:g} с × {прогонов_на_шот} прогон(ов) × {r.amount:g} usd"
                + (f" (прогон = {покрывает:g} с)" if покрывает else "")
            )
        if r.run_seconds and r.over_per_second is not None:
            лишние = max(0.0, (сек or 0.0) - r.run_seconds)
            return (
                r.amount + лишние * r.over_per_second,
                f"{r.amount:g} usd за первые {r.run_seconds:g} с + {лишние:g} с × {r.over_per_second:g} usd/с",
            )
        if сек is None and need.images > 1:
            # Картиночный шаг с ценой «за запрос»: прогон — один кадр, и шесть
            # заказанных кадров — шесть прогонов (2026-10-15, аудит третьего круга).
            прогонов = math.ceil(need.images)
            return r.amount * прогонов, f"{прогонов} прогон(ов) × {r.amount:g} usd (прогон = 1 кадр)"
        покрывает = r.run_seconds or need.max_run_seconds
        прогонов = math.ceil(сек / покрывает) if сек and покрывает else 1
        if сек and not покрывает:
            return (
                r.amount,
                f"{r.amount:g} usd за прогон (сколько секунд даёт прогон — не записано)",
            )
        return r.amount * прогонов, f"{прогонов} прогон(ов) × {r.amount:g} usd" + (
            f" (прогон = {покрывает:g} с)" if покрывает else ""
        )
    if r.per in ("image", "megapixel") and need.images <= 0:
        return None
    if r.per == "image":
        return r.amount * need.images, f"{need.images:g} кадр(ов) × {r.amount:g} usd"
    if r.per == "megapixel":
        мп = math.ceil(need.megapixels)
        return r.amount * мп * need.images, f"{need.images:g} кадр(ов) × {мп} Мп × {r.amount:g} usd"
    if r.per in ("1000_chars", "character"):
        if need.chars is None:
            return None
        за_тысячу = r.amount * (1000.0 if r.per == "character" else 1.0)
        return (
            за_тысячу * need.chars / 1000.0,
            f"≈{need.chars:g} знаков × {за_тысячу:g} usd за 1000_chars"
            + (f" ({r.amount:g} usd за знак)" if r.per == "character" else ""),
        )
    return None


def estimate(ставки: list[Rate], need: Need) -> list[Option]:
    """Сколько стоит шаг на КАЖДОМ тарифе, где ставка подходит брифу. Дешёвые первыми не ставятся:
    порядок — порядок вендора (флагман первым), чтобы тариф по умолчанию был его, а не наш.

    Только доллары: кредиты в доллары не переводятся (курс — решение вендора).
    """
    по_тарифу: dict[str, list[tuple[tuple, Rate, int]]] = {}
    for r in ставки:
        if r.unit != "usd" or r.upfront or r.amount <= 0:
            # Ноль — не цена: бесплатным не считается ничего (запись «$0» —
            # артефакт сводки, а не тариф).
            continue
        if r.mode and need.mode and need.mode not in r.mode.split("/"):
            continue
        звук = _подходит_звук(r, need.audio)
        if звук == 2:
            continue
        кадр = _подходит_кадр(r, need.resolution)
        if кадр is None:
            continue
        по_тарифу.setdefault(r.tier, []).append(((кадр[0], звук), r, кадр[1]))
    варианты: list[Option] = []
    for тариф, пары in по_тарифу.items():
        лучшие: list[tuple[tuple[tuple[int, ...], float], Option]] = []
        for штраф, r, разрешение in пары:
            деньги = _деньги(r, need)
            if деньги is None:
                continue
            сумма, расчёт = деньги
            подпись = " ".join(
                ч
                for ч in (
                    тариф.capitalize() if тариф else "",
                    f"{разрешение}p" if разрешение else "",
                    (
                        f"ниже заказанного {need.resolution}p — нужен апскейл"
                        if штраф[0] == 3
                        else ""
                    ),
                    "со звуком" if r.audio else "без звука" if r.audio is False else "",
                )
                if ч
            )
            лучшие.append(
                (
                    (штраф, сумма),
                    Option(
                        round(сумма, 4),
                        тариф,
                        разрешение or None,
                        (f"[{подпись}] " if подпись else "") + f"{расчёт} = {сумма:.2f} usd",
                        r.conditional,
                    ),
                )
            )
        if лучшие:
            варианты.append(min(лучшие, key=lambda п: п[0])[1])
    return варианты
