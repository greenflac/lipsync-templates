"""Модель, которую выключили или собираются выключить.

ЗАЧЕМ

Спрашивая базу про `sora-2`, ось доступности сказала: «end of life 2026-09-24,
22 days away». Я этого не увидел, читая план, — и не увидел бы никто: реестр
держит СЕМЬ карточек, а база фактов 505 моделей, и для остальных 498 запись о
снятии лежит в `claims` рядовой строкой, как разрешение или цена.

ИЗМЕРЕНО 2026-09-02: в базе 11 строк с признаком снятия у 9 моделей. Среди них

    imagen-4.0  / deprecation  «deprecated; Gemini API shutdown Aug 17 2026»
    imagen-4    / availability «DISCONTINUED on Vertex AI»
    sora-2      / limitation   «deprecated with a hard shutdown»
    eleven_turbo_v2_5 / status «deprecated; replacement eleven_flash_v2_5»
    gemini-3-pro/ availability «Not available: ... "Previous models"»

Первая из них — про дату в ПРОШЛОМ: 17 августа уже было. То есть база держит
модель, которая на этом пути уже не отвечает, и ничем этого не помечает.
Порекомендовать такую — значит послать человека платить за 404.

ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ

Не ищет слово. Слово находится и там, где речь не о модели:

    «...standing on a rusty metal roof, SUNSET background. 15. A weak black cat»
        — `sunset` в тексте промпта, это свет, а не снятие с обслуживания
    «FutureWarning: `Transformer2DModelOutput` is DEPRECATED and will be removed»
        — устарел класс библиотеки, а не модель

Обе строки лежат в живой базе и обе поймались наивным поиском по слову. Здесь
требуется, чтобы рядом стояло имя того, что снимают (модель, API, эндпоинт,
версия), и чтобы подлежащим не был идентификатор кода.

ТРИ ИСХОДА (Р1)

    не годно   снято: дата в прошлом или сказано «недоступна»
    не смогли  объявлено снятие, но даты нет или она в будущем — предупреждение
    годно      признаков снятия в строках нет
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

#: Слова, которыми объявляют снятие. Взяты у `pipeline.DEPRECATION_MARKERS` по
#: смыслу, но проверяются иначе — вместе с подлежащим (см. `СЛУЖБА`).
СНЯТИЕ = re.compile(
    r"\b(deprecat\w*|retired?|sunsett?\w*|discontinued?|shut ?down|end[- ]of[- ]life|eol"
    r"|no longer (available|supported|served)|not available|снят\w*|отключ\w*)\b",
    re.I,
)

#: Что именно снимают. Без этого «sunset background» в тексте промпта читается
#: как снятие с обслуживания.
СЛУЖБА = re.compile(
    r"\b(model|models|api|apis|endpoints?|version|versions|family|service|"
    r"access|weights|checkpoint|модель|модели|эндпоинт|верси\w+)\b",
    re.I,
)

#: Насколько близко к слову о снятии обязано стоять имя службы. ВЫБРАНО 60
#: знаков и проверено на живой базе: при 60 из 11 строк остаются 9 настоящих и
#: уходят обе ложные.
БЛИЗКО = 60

#: Идентификатор кода перед словом: «`Transformer2DModelOutput` is deprecated».
#: Подлежащее здесь — символ библиотеки, а не модель. Ловится обратный апостроф
#: и ВерблюжийРегистр — две формы, которыми в этой базе пишут имена из кода.
СИМВОЛ_КОДА = re.compile(r"(`[^`]+`|\b[A-Z][a-z]+[A-Z]\w*)\s+(?:is|was|are|were)\s+\w*$")

#: РАБОТАЕТ, ХОТЯ И УСТАРЕЛА. Поймано на живой строке `gpt-5 / availability`:
#:
#:   «Still callable but superseded: ... the only snapshot, gpt-5-2025-08-07,
#:    is marked Deprecated. ... Sep 30 2024 knowledge cutoff»
#:
#: Модель ЗОВЁТСЯ. Устарел её снимок, а не она; пометить её снятой значит
#: выбросить рабочую модель — ошибка в ту сторону, которая дороже.
РАБОТАЕТ = re.compile(
    r"\b(still (callable|available|works?|served|supported)|remains (available|callable))\b", re.I
)

#: Дата, которой называют срок. Три формы, все три встречаются в базе:
#: «Aug 17 2026», «2026-09-24», «September 24, 2026».
ДАТА_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
МЕСЯЦЫ = {
    m: i
    for i, m in enumerate(
        ("jan feb mar apr may jun jul aug sep oct nov dec".split()),
        start=1,
    )
}
ДАТА_СЛОВОМ = re.compile(r"\b([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")


#: Исходы этого модуля — словами, как у `studio/pricing.py`. Названы
#: константами, чтобы потребитель не набирал их литералом: `advice.py` сравнил
#: исход с английским `PASS` из `lipsync.fork_identity`, фильтр не совпал
#: никогда, и в ответ поехали ВСЕ строки модели как «снятие». Поймано на
#: первом же прогоне провода.
ГОДНО = "годно"
НЕ_ГОДНО = "не годно"
НЕ_СМОГЛИ = "не смогли"


@dataclass(frozen=True)
class Снятие:
    """Что сказано о конце службы. `outcome` — три исхода, как везде."""

    когда: str
    прошло: bool | None
    outcome: str
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "when": self.когда,
            "already": self.прошло,
            "outcome": self.outcome,
            "note": self.note,
        }


#: Насколько близко к слову о снятии обязана стоять дата, чтобы считаться его
#: сроком. ВЫБРАНО 80 знаков — та же мера, что у цен, и по той же причине:
#: строка несёт не одну дату, и дальняя относится к другому.
ДАТА_БЛИЗКО = 80

#: ДАТА, КОТОРАЯ НЕ СРОК. `gpt-5 / availability` несёт «Sep 30 2024 knowledge
#: cutoff» в шестидесяти знаках от слова `Deprecated` — то есть близость её НЕ
#: отсекает, и одной близости мало. Отсекается тем, что стоит СРАЗУ ПОСЛЕ
#: даты: обучающая отсечка называет себя сама.
НЕ_СРОК_ПОСЛЕ = re.compile(
    r"^\s*(knowledge cutoff|training (data|cutoff)|cutoff|released?|launched?)\b", re.I
)


def дата_в_тексте(текст: str, около: int | None = None) -> str:
    """Дата в ISO, или пусто. Пусто — законный исход.

    `около` — позиция слова о снятии: дата ищется рядом с ним, а не где угодно
    в строке.
    """
    начало = 0 if около is None else max(0, около - ДАТА_БЛИЗКО)
    кусок = текст if около is None else текст[начало : около + ДАТА_БЛИЗКО]
    for м in ДАТА_ISO.finditer(кусок):
        if not НЕ_СРОК_ПОСЛЕ.match(кусок[м.end() : м.end() + 40]):
            return м.group(0)
    for сл in ДАТА_СЛОВОМ.finditer(кусок):
        if НЕ_СРОК_ПОСЛЕ.match(кусок[сл.end() : сл.end() + 40]):
            continue
        месяц = МЕСЯЦЫ.get(сл.group(1).lower())
        if месяц:
            return f"{int(сл.group(3)):04d}-{месяц:02d}-{int(сл.group(2)):02d}"
    return ""


#: Имена атрибутов, которые САМИ называют подлежащее: строка под ними говорит о
#: модели целиком. Нужны потому, что источник подлежащее опускает —
#: `eleven_turbo_v2_5 / status = «deprecated; replacement eleven_flash_v2_5»`
#: не содержит слова «модель» вовсе, а говорит именно о ней.
#:
#: Список закрытый и БЕЗ составных имён вроде `remix_endpoint_status`: там снят
#: ОДИН эндпоинт, а не модель, и пометить модель мёртвой по такой строке значит
#: выбросить рабочую модель (`sora-2 / remix_endpoint_status = «deprecated,
#: replaced by /v1/videos/edits»` — сама модель при этом работает).
ОБ_ОБСЛУЖИВАНИИ: frozenset[str] = frozenset({"status", "availability", "deprecation", "lifecycle"})


def все_места_снятия(значение: str, attribute: str = "") -> list[int]:
    """Позиции ВСЕХ слов о снятии модели. Пустой список — снятия нет.

    Отдельной функцией (Т5): «около какого слова искать дату» — развилка, из-за
    которой терялся срок, и она обязана быть достижима тестом.
    """
    текст = str(значение or "")
    if РАБОТАЕТ.search(текст):
        return []
    подлежащее_в_имени = str(attribute or "").strip().lower() in ОБ_ОБСЛУЖИВАНИИ
    места: list[int] = []
    for м in СНЯТИЕ.finditer(текст):
        до = текст[max(0, м.start() - БЛИЗКО) : м.start()]
        if СИМВОЛ_КОДА.search(до):
            continue
        окно = текст[max(0, м.start() - БЛИЗКО) : м.end() + БЛИЗКО]
        if подлежащее_в_имени or СЛУЖБА.search(окно):
            места.append(м.start())
    return места


def разобрать(значение: str, attribute: str = "", *, сегодня: date | None = None) -> Снятие:
    """Что строка говорит о конце службы модели."""
    текст = str(значение or "")
    места = все_места_снятия(текст, attribute)
    if not места:
        return Снятие("", None, "годно", "признаков снятия нет")
    # Дата ищется около КАЖДОГО слова о снятии, а не только первого. Строка
    # `imagen-4` говорит «DISCONTINUED on Vertex AI. ... listed as discontinued
    # with discontinuation date June 30, 2026»: срок стоит у ВТОРОГО слова, в
    # ста сорока знаках от первого, и по первому терялся.
    когда = ""
    for где in места:
        когда = дата_в_тексте(текст, где)
        if когда:
            break
    сейчас = сегодня or date.today()
    if not когда:
        return Снятие(
            "", None, "не смогли", "снятие объявлено, но даты в строке нет — срок неизвестен"
        )
    прошло = когда <= сейчас.isoformat()
    return Снятие(
        когда,
        прошло,
        "не годно" if прошло else "не смогли",
        f"снятие назначено на {когда}" + (" — дата уже прошла" if прошло else " — впереди"),
    )
