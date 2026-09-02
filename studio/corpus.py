"""Единственный способ сосчитать корпус. Все остальные — ошибка.

ЗАЧЕМ ЭТОТ МОДУЛЬ

2026-08-31 я опубликовал «1047 живых фактов, 258 моделей». Прибор на том же
коммите говорил 969 и 245. Оба числа получены честно и оба «правильные»: я
считал СТРОКИ файла минус отозванные, а `load_facts` считает УТВЕРЖДЕНИЯ —
перезапись того же факта даёт новую строку, но не новое знание. Разница 8%.

Это ровно правило Е1 в самом опасном месте: в числе, которым меряют успех.
Пока способ счёта не один, любой замер «до и после» мерит способ, а не знание.

ЧТО ЗДЕСЬ ЕСТЬ, ЧЕГО НЕТ НИГДЕ ЕЩЁ

`snapshot()` возвращает не одно число, а СОСТАВ. Публиковать сумму запрещено
правилом Е3: агрегат читается как полная работа. 245 моделей, из которых у 46%
ровно один факт, — это не то же самое, что 245 разобранных моделей, и разница
видна только в распределении.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from studio.selfrag.facts import CLASS_SUFFIX, Fact, FactStore, load_facts
from studio.selfrag.modelnames import fold

#: Атрибуты, которые говорят, как модель СЕБЯ ВЕДЁТ, а не что принимает её API.
#: Это дефицитная половина базы, и считать её отдельно — весь смысл снимка.
#: ВЫБРАНО по перечислению того, что уже записано: список закрытый нарочно,
#: чтобы «применимость» не расползлась на всё подряд при первом же удобном
#: случае. Расширять его — осознанное решение с правкой этой строки.
APPLICABILITY = frozenset(
    {
        # Практик описал прогон, но знак не назвал. Это применимость: он
        # запускал. ИЗМЕРЕНО 2026-09-01: таких наблюдений 6 из 11 на живом
        # замере тел тредов — больше половины выхода канала.
        "observed_behaviour",
        "failure_mode",
        "limitation",
        "degrades_when",
        "holds_identity",
        "artifact_taxonomy",
        "metric_blind_spot",
        "runs_on",
    }
)

#: Тиры, означающие «кто-то это ЗАПУСКАЛ»: зонд вендорского API и собственный
#: опыт оператора. Самая дорогая и самая редкая часть корпуса.
WITNESSED_TIERS = frozenset({"probe", "operator"})


#: Что считать скоупом, а не моделью, решает `CLASS_SUFFIX` из `facts.py`, а не
#: этот модуль. Первая редакция сравнивала с литералом `"*"` и потому считала
#: МОДЕЛЬЮ семейный скоуп `eleven-*` — то есть завела второе определение
#: одного понятия ровно в том модуле, который написан против этого. Поймано
#: независимой приёмкой 2026-08-31; цена сегодня единица, но растёт с каждым
#: новым семейным скоупом.
def is_scope(model: str) -> bool:
    """Это скоуп («про класс»), а не модель."""
    return str(model or "").endswith(CLASS_SUFFIX)


@dataclass(frozen=True)
class Snapshot:
    """Состав корпуса. Ни одно поле не заменяет остальные."""

    facts: int
    models: int
    class_facts: int
    one_fact_only: int
    with_vendor: int
    with_applicability: int
    with_witness: int
    contested_pairs: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def share(self, field: str) -> float | None:
        """Доля моделей. `None`, когда моделей ноль — а не ноль процентов."""
        if not self.models:
            return None
        return getattr(self, field) / self.models


def snapshot(facts: list[Fact] | None = None, path: Path | None = None) -> Snapshot:
    """Состав корпуса на данных, а не на строках файла.

    Считает по `load_facts`, то есть по УТВЕРЖДЕНИЯМ: отозванное снято,
    перезаписанное схлопнуто. Это и есть тот единственный способ, ради
    которого модуль написан.
    """
    rows = facts if facts is not None else load_facts(path) if path else load_facts()
    по_моделям: dict[str, list[Fact]] = {}
    class_facts = 0
    for fact in rows:
        if is_scope(fact.model):
            class_facts += 1
            continue
        # Ключ — СВЁРТКА имени, а не сырое написание: `ltx-2.3` и `ltx-2-3`
        # это одна модель, и до 2026-09-02 она считалась двумя — то есть
        # знаменатель покрытия был завышен на число дублей (ИЗМЕРЕНО: 9 групп
        # на 466 именах).
        по_моделям.setdefault(fold(fact.model), []).append(fact)

    # Спорные пары считает FactStore.contested(), а НЕ этот модуль. Своя
    # арифметика здесь дала бы 76 против 7 у существующего прибора: тот знает
    # про MULTI_VALUED — атрибуты, у которых несколько значений это список, а
    # не противоречие (у модели два разрешения, две цены за режим). Второе
    # определение одного понятия — ровно тот дефект Е1, ради которого написан
    # этот модуль; поймано на себе при первом же прогоне.
    спорных = len((FactStore(rows) if facts is not None or path else FactStore()).contested())

    return Snapshot(
        facts=len(rows),
        models=len(по_моделям),
        class_facts=class_facts,
        one_fact_only=sum(1 for v in по_моделям.values() if len(v) == 1),
        with_vendor=sum(1 for v in по_моделям.values() if any(f.tier == "vendor" for f in v)),
        with_applicability=sum(
            1 for v in по_моделям.values() if any(f.attribute in APPLICABILITY for f in v)
        ),
        with_witness=sum(
            1 for v in по_моделям.values() if any(f.tier in WITNESSED_TIERS for f in v)
        ),
        contested_pairs=спорных,
    )


def render(now: Snapshot, before: Snapshot | None = None) -> str:
    """Снимок строками. Сумма НИКОГДА не печатается одна (правило Е3)."""
    поля = (
        ("ровно один факт", "one_fact_only"),
        ("есть вендорский факт", "with_vendor"),
        ("есть применимость", "with_applicability"),
        ("кто-то запускал", "with_witness"),
    )
    строки = [
        f"фактов {now.facts}, моделей {now.models}, "
        f"из них про класс задач {now.class_facts} (не про модель)",
        f"спорных пар {now.contested_pairs}",
    ]
    for имя, поле in поля:
        доля = now.share(поле)
        часть = f"  {имя:24} {getattr(now, поле):4}"
        часть += f"  {доля:.0%}" if доля is not None else "   нечего делить"
        if before is not None:
            было = before.share(поле)
            if было is not None and доля is not None:
                часть += f"   (было {было:.0%})"
        строки.append(часть)
    return "\n".join(строки)
