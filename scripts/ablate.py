"""Абляция: участвует ли база в рассуждении вообще.

САМЫЙ ДЕШЁВЫЙ ВОПРОС, КОТОРЫЙ РЕШАЕТ СУДЬБУ ОСТАЛЬНЫХ

Все прочие числа — доля цитирования, покрытие, состав корпуса — меряют
ГИГИЕНУ рассуждения. Ни одно не говорит, что база на рассуждение влияет.
Проверить это можно ровно одним способом: дать тот же вопрос дважды — с
настоящей базой и с базой, где факты приписаны НЕ ТЕМ моделям, — и спросить
у того, кто не знает, какой прогон какой, различимы ли ответы.

Если неразличимы, то всё построенное декоративно, и это надо узнать сейчас, а
не после четырёх пунктов стройки.

ЧЕМ ПЕРЕМЕШИВАТЬ, И ПОЧЕМУ НЕ СЛУЧАЙНЫМ МУСОРОМ

Перемешиваются ИМЕНА МОДЕЛЕЙ между фактами, а сами факты остаются настоящими:
тир, дата, источник, формулировка. Мусор отличить легко, и такая проверка
ничего не стоила бы. Подмена имён оставляет текст одинаково правдоподобным и
бьёт ровно по тому, ради чего база нужна, — по связи «эта модель умеет это».

Перестановка ПОСЕЯНА и сид печатается: прогон обязан повторяться.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.factindex import FactIndex  # noqa: E402
from studio.selfrag.facts import Fact, load_facts  # noqa: E402

#: Сид по умолчанию. ВЫБРАНО фиксированным, чтобы прогон повторялся; меняется
#: флагом, когда нужно убедиться, что вывод не держится на одной перестановке.
SEED = 20260831

#: Сколько фактов показывать в каждом плане. ВЫБРАНО 6: столько человек
#: прочитает, не пролистывая, и столько же увидит слепой оценщик.
SHOWN = 6


def shuffled(facts: list[Fact], seed: int = SEED) -> list[Fact]:
    """Те же факты, но имена моделей переставлены между ними.

    Скоупы («про класс задач») НЕ переставляются: они и так возвращаются на
    любой вход, и подмена их имени ничего не изменила бы — перемешивать надо
    то, что несёт связь модели со свойством.
    """
    имена = [f.model for f in facts]
    rng = random.Random(seed)
    rng.shuffle(имена)
    return [
        Fact(
            model=новое,
            attribute=f.attribute,
            value=f.value,
            source_url=f.source_url,
            tier=f.tier,
            stated_on=f.stated_on,
            note=f.note,
            fix=f.fix,
        )
        for f, новое in zip(facts, имена)
    ]


def plan(index: FactIndex, brief: str, shown: int = SHOWN) -> list[dict[str, Any]]:
    """Что база отдаёт на этот бриф: голая выдача, без прозы.

    Именно голая: если различимость планов появляется от формулировок, а не от
    фактов, значит различает писатель, а не база.
    """
    return [
        {
            "model": h.fact.model,
            "attribute": h.fact.attribute,
            "value": h.fact.value[:160],
            "tier": h.fact.tier,
        }
        for h in index.search(brief, k=shown)
    ]


def _jaccard(a: set, b: set) -> float | None:
    if not a and not b:
        return None
    return len(a & b) / (len(a | b) or 1)


def compare(real: list[dict], fake: list[dict]) -> dict[str, Any]:
    """Насколько две выдачи различаются. ДВА ключа, и это не педантизм.

    Первая редакция считала совпадение по (модель, атрибут) и получила ноль на
    всех брифах — то есть «различимо». Это была ТАВТОЛОГИЯ: перемешивание
    меняет ровно имена, а имя входило в ключ. Поймано пересчётом по второму
    ключу, и второй показал ровно обратное.

    * `by_label` — (модель, атрибут). Ломается перемешиванием всегда.
    * `by_content` — (атрибут, значение). Текст факта перемешивание НЕ трогает,
      и если поиск идёт по тексту, сюда придёт единица.

    Единица по содержанию означает: индекс достал ТЕ ЖЕ факты, просто
    подписанные другими моделями. Для плана это худший исход из возможных —
    правильные тексты при неверной атрибуции.
    """
    метка = lambda r: (r["model"].lower(), r["attribute"].lower())  # noqa: E731
    текст = lambda r: (r["attribute"].lower(), r["value"])  # noqa: E731
    by_label = _jaccard({метка(r) for r in real}, {метка(r) for r in fake})
    by_content = _jaccard({текст(r) for r in real}, {текст(r) for r in fake})
    if by_label is None:
        return {
            "outcome": "не смогли",
            "by_label": None,
            "by_content": None,
            "note": "обе выдачи пусты",
        }
    # ЧТО ЗДЕСЬ РЕШАЕТСЯ, И ЧТО НЕТ. Единственный вопрос абляции: участвует ли
    # база в ответе. Ответ даёт `by_label`: если он меньше единицы, план на
    # перемешанной базе НАЗЫВАЕТ ДРУГИЕ МОДЕЛИ, то есть база участвует.
    #
    # `by_content` отвечает на другой вопрос и не должен подменять первый.
    # Единица там означает: поиск достал те же тексты и честно принёс ту
    # атрибуцию, что лежала в базе, — то есть у инструмента НЕТ защиты от
    # испорченной атрибуции, он ответит с той же уверенностью. Это настоящий
    # дефект, но он не про участие базы, и объявлять по нему «база не
    # участвует» значит выдать грубую метрику за вывод. Первая редакция
    # этого модуля так и делала; поймано пересчётом до публикации.
    исход = "годно" if by_label < 1.0 else "не годно"
    заметка = f"по ярлыку {by_label:.2f}"
    if by_content is not None and by_content >= 1.0:
        заметка += "; ВНИМАНИЕ: тексты совпали целиком — атрибуция ничем не проверяется"
    return {
        "outcome": исход,
        "by_label": round(by_label, 4),
        "by_content": round(by_content, 4) if by_content is not None else None,
        "note": заметка,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    вопросы = [
        json.loads(s)
        for s in (
            Path(__file__).resolve().parents[1] / "studio" / "knowledge" / "frozen_questions.jsonl"
        )
        .read_text(encoding="utf-8")
        .splitlines()
        if s.strip() and not s.startswith("//")
    ]
    брифы = [q for q in вопросы if q["kind"] == "brief"]

    настоящие = load_facts()
    живой = FactIndex(настоящие)
    кривой = FactIndex(shuffled(настоящие, args.seed))

    строки = []
    for q in брифы:
        real = plan(живой, q["ask"])
        fake = plan(кривой, q["ask"])
        строки.append(
            {"id": q["id"], "ask": q["ask"], "real": real, "fake": fake, **compare(real, fake)}
        )

    if args.json:
        print(json.dumps(строки, ensure_ascii=False, indent=2))
        return 0

    print("АБЛЯЦИЯ: участвует ли база в рассуждении")
    print(f"сид {args.seed}, фактов {len(настоящие)}, брифов {len(брифы)}\n")
    for r in строки:
        print(f"[{r['id']}] {r['ask'][:64]}")
        print(
            f"    исход {r['outcome']}, по ярлыку {r['by_label']}, "
            f"по содержанию {r['by_content']} — {r['note']}"
        )
        for кто, выдача in (("настоящая", r["real"]), ("перемешанная", r["fake"])):
            имена = ", ".join(f"{x['model']}.{x['attribute']}" for x in выдача[:3]) or "пусто"
            print(f"      {кто:13} {имена}")
        print()
    годно = sum(1 for r in строки if r["outcome"] == "годно")
    несмогли = sum(1 for r in строки if r["outcome"] == "не смогли")
    print(
        f"проверено {len(строки)}, различимо {годно}, неразличимо "
        f"{len(строки) - годно - несмогли}, не смогли {несмогли}"
    )
    if not строки:
        print("исход: не смогли — брифов в наборе нет")
        return 2
    без_защиты = sum(1 for r in строки if (r.get("by_content") or 0) >= 1.0)
    if годно == 0:
        print("исход: НЕ ГОДНО — база в рассуждении не участвует")
        return 1
    print(
        f"база участвует: план на перемешанной базе называет другие модели во всех {годно}.\n"
        f"ОТДЕЛЬНО, и это не то же самое: у {без_защиты} из {len(строки)} брифов тексты "
        "фактов совпали целиком — значит атрибуция ничем не проверяется, и на\n"
        "испорченной базе инструмент ответит с той же уверенностью."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
