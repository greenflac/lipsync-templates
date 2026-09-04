#!/usr/bin/env python3
"""Какую долю базы НЕ достаёт ни один вопрос (критерий релиза R3).

ЗАЧЕМ. Строка базы, до которой не доводит ни одно спрашиваемое слово, для
продукта не существует: она собрана, хранится, показывается в отчётах о размере
базы — и молчит на вопрос, ради которого её собирали. Это самый дешёвый способ
соврать размером.

ИЗМЕРЕНО 2026-09-04 до правки: недостижимо 594 строки из 2099 (28.3%), и 256 из
них — один атрибут `adoption`: спросить «насколько популярна» было нечем.

ЧТО СЧИТАЕТСЯ ДОСТИЖИМЫМ. Имя атрибута, которое возвращает `attrfamily.expand`
хотя бы на одно объявленное семейное слово. Семьи и их синонимы — единственный
источник (Е1): второго списка «что можно спросить» в репозитории нет.

ТРИ ИСХОДА (Р1):
    годно      доля недостижимого не выше потолка
    не годно   выше потолка
    не смогли  база не прочиталась — считать нечего
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.selfrag import attrfamily as A  # noqa: E402
from studio.selfrag.facts import load_facts  # noqa: E402

#: Порог из критерия R3. ВЫБРАНО владельцем как условие релиза, а не измерено:
#: «ниже 10%» — это утверждение о том, сколько собранного продукту позволено не
#: уметь спросить. Здесь он стоит ПОТОЛКОМ и обязан только падать.
ПОТОЛОК_ДОЛИ = 0.10


def свести() -> dict:
    факты = load_facts()
    if not факты:
        return {"outcome": "could not measure", "note": "база пуста или не прочиталась"}
    имена = sorted({ф.attribute for ф in факты})
    достижимы: set[str] = set()
    for слово in list(A.СЕМЬИ) + list(A.СИНОНИМЫ):
        достижимы |= set(A.expand(слово, имена))
    молчат = collections.Counter(ф.attribute for ф in факты if ф.attribute not in достижимы)
    строк = len(факты)
    недостижимо = sum(молчат.values())
    доля = недостижимо / строк
    return {
        "outcome": "pass" if доля <= ПОТОЛОК_ДОЛИ else "fail",
        "checked": строк,
        "violations": недостижимо,
        "unmeasured": 0,
        "доля": доля,
        "семей": len(A.СЕМЬИ),
        "имён": len(имена),
        "молчат": молчат.most_common(),
    }


def main(argv: list[str]) -> int:
    разбор = argparse.ArgumentParser(description=__doc__)
    разбор.add_argument("--check", action="store_true")
    разбор.add_argument("--top", type=int, default=10)
    дано = разбор.parse_args(argv)
    итог = свести()
    if итог["outcome"] == "could not measure":
        print(f"не смогли: {итог['note']}")
        return 2 if дано.check else 0
    for имя, число in итог["молчат"][: дано.top]:
        print(f"  НЕ СПРОСИТЬ {число:4} строк(и): {имя}")
    хвост = len(итог["молчат"]) - дано.top
    if хвост > 0:
        print(f"  … и ещё {хвост} имя(имён)")
    print()
    print(f"проверено {итог['checked']}")
    print(f"нарушений {итог['violations']}")
    print(f"не смогли {итог['unmeasured']}")
    print()
    print(
        f"{итог['outcome']}: недостижимо {итог['violations']} из {итог['checked']} "
        f"= {итог['доля']:.1%} при потолке {ПОТОЛОК_ДОЛИ:.0%}; "
        f"семей {итог['семей']}, имён атрибутов {итог['имён']}"
    )
    return (1 if итог["outcome"] == "fail" else 0) if дано.check else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
