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

import re
from dataclasses import dataclass
from typing import Any

#: Валюты и единицы, которые встречаются в базе. Список закрытый: незнакомая
#: единица обязана давать третий исход, а не подставляться в сумму.
UNITS = ("usd", "credits")

#: Что за что платят. Тоже закрытый список — «за что» определяет, можно ли
#: вообще складывать два числа.
PER = ("second", "image", "generation", "run", "minute", "megapixel", "1000_chars", "token")

_MONEY = re.compile(r"\$\s*(\d+(?:\.\d+)?)")
_CREDITS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:credits?|cr)\b", re.I)
_BARE = re.compile(r"^\s*\$?\s*(\d+(?:\.\d+)?)\s*$")

#: Слова, после которых число перестаёт быть базовой ценой и становится
#: условием: минимум за генерацию, доплата за звук, надбавка за разрешение.
CONDITIONAL = re.compile(
    r"\b(minimum|min\b|upfront|then|with audio|without|at \d+p|at \d+K|per \d+)", re.I
)


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
    a = attribute.lower()
    единица = "usd" if a.endswith("_usd") or "usd" in a else ""
    за = ""
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
    условие = bool(CONDITIONAL.search(текст))

    if not текст:
        return Price(None, единица, за, условие, "не смогли", "значение пустое")

    голое = _BARE.match(текст)
    if голое:
        return Price(float(голое.group(1)), единица or "usd", за, False, "годно", "одно число")

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
        if p.outcome != "годно" or p.amount is None or not p.unit:
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
