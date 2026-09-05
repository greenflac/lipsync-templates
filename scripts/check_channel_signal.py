#!/usr/bin/env python3
"""Канал, отвечающий одинаково на любой вход, несёт ноль бит о входе.

    python scripts/check_channel_signal.py --check

ЧТО СЛОМАНО БЕЗ ЭТОГО, ИЗМЕРЕНО 2026-08-31

`advice.advise(model)['class_findings']` возвращает 12 находок из 171 — ОДНИ И
ТЕ ЖЕ для любого имени модели, включая заведомо выдуманное (`zzqx-nonexistent-
model-7`). Перекрытие выдач по устойчивому ключу элемента: 1.00 на всех
проверенных парах. Выдача при этом ПРАВДИВА: тир `paper`, со ссылками, ничего
не выдумано. Но правда не есть релевантность: список, не зависящий от вопроса,
занимает место ответа и читается как ответ на вопрос.

Ни один существующий гейт этого не видел и увидеть не мог. Все они проверяют
ОДНУ выдачу — схему, тир, наличие ссылки, отсутствие чужой прозы. Инвариантность
не свойство выдачи, это свойство ПАРЫ выдач на несвязанных входах, и меряется
только сравнением. Отсюда отдельная проверка (Ц7: то, что обязано выполняться
всегда, — гейт, а не абзац).

КАК МЕРИТСЯ

Жаккар по множеству устойчивых ключей элементов на паре НЕСВЯЗАННЫХ входов.
Несвязанных — значит разных вендоров и разных семейств задач (генератор видео
против клонирования голоса): у таких входов нет причины делить ответ.

ТРИ ИСХОДА (Р1)

`годно` — все отработавшие каналы различают вход; `не годно` — есть НОВЫЙ
инвариантный; `не смогли` — канал не отработал (нет корпуса, импорт не удался)
или ни одной измеримой пары не набралось. Пустой набор пар — это «не смогли»,
а не успех (Р2): рядом печатаются `проверено N`, `инвариантных M`, `не смогли K`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Collection, Hashable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

#: Порог инвариантности: перекрытие Жаккара на несвязанной паре, при котором
#: канал считается не несущим сигнала о входе.
#:
#: ВЫБРАНО (мной, 2026-08-31) из измеренного зазора, а не из общих соображений.
#: ИЗМЕРЕНО на четырёх несвязанных парах живой базы:
#:   class_findings  1.00, 1.00, 1.00, 1.00  — инвариантен
#:   claims          0.11, 0.08, 0.04, 0.17  — различает
#:   failure_modes   0.00, 0.00, 0.00, 0.00  — различает
#:   knowledge.examples 0.00                 — различает
#: Зазор между худшим различающим (0.17) и лучшим инвариантным (1.00) — почти
#: весь диапазон, поэтому порог ставится в его середине с запасом в обе стороны.
#: 1.00 не годится: канал, подмешавший к неизменной выдаче один элемент от
#: входа, стал бы «годен», оставшись инвариантным по существу. 0.30 и ниже —
#: тоже нет: каналы одной предметной области законно делят общие элементы, и
#: порог у самой границы измеренного начнёт краснеть на честных каналах.
INVARIANT_AT = 0.80

#: Каналы, инвариантные на момент появления этой проверки (2026-08-31), — долг,
#: а не повод заблокировать всякий коммит. Список ИМЕНОВАННЫЙ и печатается в
#: отчёте: он грепается, он виден в диффе, и каждый НОВЫЙ инвариантный канал
#: красит сборку. Образец — `KNOWN_UNDECLARED` в scripts/check_declared_deps.py.
#:
#: Пустой список при живом нарушителе обязан краснить — это сторожится тестом
#: `test_channel_signal.py`.
KNOWN_INVARIANT: dict[str, str] = {
    "advice.advise().class_findings": (
        "ИЗМЕРЕНО 2026-08-31: перекрытие 1.00, включая выдуманное имя модели. "
        "12 находок из 171 отбираются по тиру и атрибуту, а имя модели в отбор "
        "не входит вовсе. Правдиво, но о входе не говорит ничего. "
        "Чинится отбором находок по классу спрошенной модели, а не по тиру; "
        "владелец studio/mcp/advice.py — не я, поэтому здесь долг, а не правка."
    ),
}


@dataclass(frozen=True)
class Channel:
    """Канал: имя, пары несвязанных входов и способ достать из выдачи элементы.

    `elements` обязан вернуть коллекцию УСТОЙЧИВЫХ ключей — то, по чему два
    элемента признаются одним и тем же. Исключение изнутри — это «не смогли»
    по этой паре, а не провал: канала может не быть в этом окружении.
    """

    name: str
    pairs: tuple[tuple[str, str], ...]
    elements: Callable[[str], Collection[Hashable]]


def overlap(left: Collection[Hashable], right: Collection[Hashable]) -> float | None:
    """Жаккар двух множеств ключей; `None`, если сравнивать нечего.

    Две пустые выдачи — это не «полное совпадение» и не «полное различие»:
    канал не сказал ничего, и это «не смогли» (Р1), а не 1.0 и не 0.0.

    >>> overlap({"a", "b"}, {"b", "c"})
    0.3333333333333333
    >>> overlap([], []) is None
    True
    """
    a, b = set(left), set(right)
    union = a | b
    if not union:
        return None
    return len(a & b) / len(union)


def measure(channel: Channel, *, threshold: float = INVARIANT_AT) -> dict:
    """Один канал на всех своих парах: худший (самый инвариантный) случай.

    Берётся МАКСИМУМ перекрытия, а не среднее: канал, инвариантный на одной
    паре из четырёх, инвариантен — среднее это спрятало бы.
    """
    scores: list[tuple[str, str, float]] = []
    unmeasurable: list[str] = []
    for left, right in channel.pairs:
        try:
            a = channel.elements(left)
            b = channel.elements(right)
        except Exception as exc:  # канала нет в этом окружении — это не провал
            unmeasurable.append(f"{left} / {right}: {type(exc).__name__}: {exc}")
            continue
        score = overlap(a, b)
        if score is None:
            unmeasurable.append(f"{left} / {right}: обе выдачи пусты")
            continue
        scores.append((left, right, score))

    if not scores:
        return {
            "channel": channel.name,
            "outcome": UNMEASURED,
            "overlap": None,
            "pairs": 0,
            "unmeasurable": unmeasurable,
            "note": "ни одной измеримой пары",
        }

    left, right, worst = max(scores, key=lambda item: item[2])
    return {
        "channel": channel.name,
        "outcome": FAIL if worst >= threshold else PASS,
        "overlap": worst,
        "pairs": len(scores),
        "unmeasurable": unmeasurable,
        "note": f"худшая пара {left} / {right}: перекрытие {worst:.2f}",
    }


def judge(results: list[dict], known: dict[str, str]) -> dict:
    """Сводный вердикт по каналам, с известными нарушителями отдельной графой.

    Известный нарушитель НЕ красит сборку, но и не читается как успех: он
    попадает в `не смогли` вместе с неотработавшими каналами, как и давние
    необъявленные пакеты в scripts/check_declared_deps.py.

    Ноль отработавших каналов — `не смогли`, а не `годно` (Р2).
    """
    fresh = [r for r in results if r["outcome"] == FAIL and r["channel"] not in known]
    debt = [r for r in results if r["outcome"] == FAIL and r["channel"] in known]
    broken = [r for r in results if r["outcome"] == UNMEASURED]
    working = [r for r in results if r["outcome"] == PASS]

    if fresh:
        outcome = FAIL
    elif not working and not debt:
        outcome = UNMEASURED
    else:
        outcome = PASS

    return {
        "outcome": outcome,
        "checked": len(working) + len(fresh) + len(debt),
        "violations": len(fresh),
        "unmeasured": len(broken) + len(debt),
        "fresh": fresh,
        "debt": debt,
        "broken": broken,
    }


# --- живые каналы -----------------------------------------------------------

#: Пары несвязанных входов для `advise`: разные вендоры И разные семейства
#: задач. Родственная пара (две модели одного вендора) законно делит ответ, и
#: измеряла бы родство, а не инвариантность (И5: у прибора должен быть вход,
#: на котором он обязан промолчать).
ADVICE_PAIRS = (
    ("sora-2", "elevenlabs-pvc"),
    ("flux-3", "wav2lip"),
    ("minimax-h3", "latentsync"),
    ("veo-3.1", "musetalk"),
)

#: Пары для ретривера: два стилевых запроса без общих слов и общего замысла.
KNOWLEDGE_PAIRS = (
    ("soft golden hour light, warm amber palette", "harsh neon cyberpunk night, cold blue"),
    ("matte ivory studio portrait, low-key", "wide desert landscape at noon, dusty ochre"),
)


def live_channels() -> list[Channel]:
    """Каналы этого репозитория. Импорты ленивые: отсутствие корпуса или
    пакета обязано стать «не смогли» по одному каналу, а не падением гейта.

    `knowledge.retrieve()['core_rules']` сюда НЕ входит осознанно: он по
    контракту одинаков для всех запросов («core rules are a separate field and
    never compete for a slot in k»), то есть объявлен инвариантным и как ответ
    на вход не продаётся. Проверяется `examples` — то, что обязано зависеть от
    запроса.
    """

    def advice_list(
        field: str, key: Callable[[dict], Hashable]
    ) -> Callable[[str], Collection[Hashable]]:
        """Поле-список из `advise`, свёрнутое к множеству устойчивых ключей."""

        def elements(model: str) -> Collection[Hashable]:
            from studio.mcp import advice

            return {key(item) for item in advice.advise(model)[field]}

        return elements

    def advice_claims(model: str) -> Collection[Hashable]:
        """`claims` — словарь атрибут → вердикт; элемент здесь это атрибут."""
        from studio.mcp import advice

        return set(advice.advise(model)["claims"])

    def knowledge_examples(text: str) -> Collection[Hashable]:
        # `# type: ignore` не от лени: рядом с `studio/knowledge.py` лежит
        # каталог `studio/knowledge/` с данными, и mypy видит namespace-пакет
        # вместо модуля. На исполнении выигрывает модуль — проверено прогоном
        # этого гейта, — а разводить два имени в чужом коде запрещает Ц2.
        from studio import knowledge

        return {example["id"] for example in knowledge.retrieve(text)["examples"]}  # type: ignore[attr-defined]

    return [
        Channel(
            name="advice.advise().class_findings",
            pairs=ADVICE_PAIRS,
            elements=advice_list(
                "class_findings",
                lambda f: (f["scope"], f["attribute"], f["value"]),
            ),
        ),
        Channel(
            name="advice.advise().failure_modes",
            pairs=ADVICE_PAIRS,
            elements=advice_list(
                "failure_modes",
                lambda f: (f["value"], f["fix"], f["source_url"]),
            ),
        ),
        Channel(
            name="advice.advise().claims",
            pairs=ADVICE_PAIRS,
            elements=advice_claims,
        ),
        Channel(
            name="knowledge.retrieve().examples",
            pairs=KNOWLEDGE_PAIRS,
            elements=knowledge_examples,
        ),
    ]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="код возврата 0/1/2")
    args = parser.parse_args(argv)

    results = [measure(channel) for channel in live_channels()]
    for result in results:
        mark = {PASS: "различает", FAIL: "ИНВАРИАНТЕН", UNMEASURED: "не смогли"}[result["outcome"]]
        score = "—" if result["overlap"] is None else f"{result['overlap']:.2f}"
        print(f"  {mark:<12} {result['channel']}: перекрытие {score} на {result['pairs']} пар(ах)")
        for line in result["unmeasurable"]:
            print(f"      (пара не измерена: {line})")

    verdict = judge(results, KNOWN_INVARIANT)
    for result in verdict["debt"]:
        print(f"  (давний, до правила: {result['channel']} — {KNOWN_INVARIANT[result['channel']]})")

    print(
        f"\nпроверено {verdict['checked']}\n"
        f"инвариантных {verdict['violations']}\n"
        f"не смогли {verdict['unmeasured']}"
    )
    print(
        f"\n{verdict['outcome']}: "
        + (
            f"{verdict['violations']} НОВЫХ канал(ов) отвечают одинаково на несвязанные входы"
            if verdict["violations"]
            else (
                f"новых инвариантных нет, давних {len(verdict['debt'])}"
                if verdict["outcome"] == PASS
                else "ни один канал не отработал — измерять было нечего"
            )
        )
    )
    if not args.check:
        return 0
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[verdict["outcome"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
