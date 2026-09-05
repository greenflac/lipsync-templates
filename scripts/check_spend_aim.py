#!/usr/bin/env python3
"""Заявки на платный замер против того, что продукт РЕКОМЕНДУЕТ.

    python scripts/check_spend_aim.py            # таблица
    python scripts/check_spend_aim.py --check    # для гейта: числа и исход

ЗАЧЕМ

Владелец поставил условие: сперва голден-сет, потом деньги. Набор собран — и
первым же вопросом к нему оказался не «что продукт умеет», а «куда нацелены
деньги». ИЗМЕРЕНО 2026-09-03, и это ноль:

    продукт рекомендует 5 моделей, у 22 шагов из 32 применимость НЕ ИЗМЕРЕНА
    заявок на замер 6, на общую сумму ~$4.25
    пересечение                                                          0

Все шесть заявок — на модели, которых планировщик не выбирает ни разу
(`minimax-h3`, `veo-3.1`, `runway-gen-4.5`, `sync-lipsync`, `latentsync-1.6`,
`kling-3.0`), а все 22 непроверенных шага — на моделях, о которых не подано ни
одной заявки. Деньги, потраченные в таком виде, не сдвинули бы ни один план,
который продукт выдаёт СЕГОДНЯ.

Это тот же дефект, что вёл всю сессию, — «прибор смотрит не туда», — но на
уровне трат, где он дороже всего.

ТРИ ИСХОДА (Р1)

    годно      у каждой рекомендуемой модели с неизмеренной применимостью
               есть заявка
    не годно   заявки ЕСТЬ, и ни одна не про рекомендуемую модель: деньги
               нацелены мимо продукта
    не смогли  заявок нет вовсе — сверять нечего

Р2: рядом с исходом печатаются числа — сколько моделей рекомендуется, у
скольких есть заявка, сколько заявок висит мимо.

СЕТИ ЗДЕСЬ НЕТ: планировщик читает записанную базу, заявки — свой журнал.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402
from studio import planner  # noqa: E402
from studio.mcp import server as mcp_server  # noqa: E402
from studio.selfrag.modelnames import fold  # noqa: E402

ЗАДАЧИ = Path(__file__).resolve().parents[1] / "studio" / "knowledge" / "golden_tasks.jsonl"

#: Пометка планировщика о том, что применимость кандидата никем не измерена.
#: ИМПОРТИРУЕТСЯ, а не переписывается: она живёт у планировщика (Е1).
НЕ_ИЗМЕРЕНА = planner.NOT_MEASURED_MARK


def брифы(путь: Path = ЗАДАЧИ) -> list[dict[str, Any]]:
    """Планы берутся из ГОЛДЕН-СЕТА, а не из отдельного списка.

    Второй список брифов разъехался бы с набором на первой же правке, и сверка
    считала бы не то, что меряет продукт (Е1).
    """
    из: list[dict[str, Any]] = []
    for строка in путь.read_text(encoding="utf-8").splitlines():
        строка = строка.strip()
        if not строка or строка.startswith("//"):
            continue
        задача = json.loads(строка)
        if задача["канал"] == "plan":
            из.append(задача["вход"])
    return из


def рекомендации(входы: list[dict[str, Any]]) -> tuple[Counter, Counter]:
    """(сколько раз модель выбрана, сколько раз выбрана без применимости)."""
    выбраны: Counter = Counter()
    без: Counter = Counter()
    for вход in входы:
        итог = planner.plan(вход["brief"], creative=вход.get("creative", ""))
        for шаг in итог["steps"]:
            кандидат = шаг["chosen"]
            if not кандидат:
                continue
            выбраны[кандидат["model"]] += 1
            if НЕ_ИЗМЕРЕНА in кандидат["mark"]:
                без[кандидат["model"]] += 1
    return выбраны, без


def заявки() -> list[dict[str, Any]]:
    орудие = mcp_server.measurement_proposals
    ответ = json.loads(getattr(орудие, "fn", орудие)())
    return list(ответ.get("proposals", []))


def свести() -> dict[str, Any]:
    выбраны, без = рекомендации(брифы())
    поданы = заявки()
    # Сверка по СВЁРНУТОМУ имени: `sync-lipsync-2` и `sync-lipsync-v2` — одна
    # модель, и считать их разными значило бы объявить заявку промахом на
    # написании (`studio/selfrag/modelnames.py`).
    свёрнуты = {fold(з["model"]): з for з in поданы}
    нужны = sorted(м for м, n in без.items() if n)
    покрыты = [м for м in нужны if fold(м) in свёрнуты]
    мимо = [з["model"] for к, з in свёрнуты.items() if к not in {fold(м) for м in выбраны}]

    if not поданы:
        исход = UNMEASURED
    elif покрыты:
        исход = PASS if len(покрыты) == len(нужны) else FAIL
    else:
        исход = FAIL
    return {
        "outcome": исход,
        "checked": len(нужны),
        "violations": len(нужны) - len(покрыты),
        "unmeasured": 0 if поданы else len(нужны),
        "рекомендуется": выбраны,
        "без применимости": без,
        "нужны замеры": нужны,
        "покрыты заявкой": покрыты,
        "заявки мимо": мимо,
        "заявок": len(поданы),
    }


def main(argv: list[str]) -> int:
    р = argparse.ArgumentParser(description=__doc__)
    р.add_argument("--check", action="store_true", help="кратко, для гейта")
    аргс = р.parse_args(argv)

    итог = свести()
    if not аргс.check:
        for модель, n in итог["рекомендуется"].most_common():
            без = итог["без применимости"][модель]
            метка = "заявка есть" if модель in итог["покрыты заявкой"] else "ЗАЯВКИ НЕТ"
            print(
                f"  {модель:44} шагов {n:2}, без применимости {без:2} — {метка if без else 'измерена'}"
            )
    for имя in итог["заявки мимо"]:
        print(f"  ЗАЯВКА МИМО ПРОДУКТА: {имя} — планировщик не выбирает эту модель ни разу")
    print()
    print(f"проверено {итог['checked']}")
    print(f"нарушений {итог['violations']}")
    print(f"не смогли {итог['unmeasured']}")
    print()
    print(
        f"{итог['outcome']}: моделей без применимости {итог['checked']}, "
        f"из них с заявкой {len(итог['покрыты заявкой'])}; "
        f"заявок всего {итог['заявок']}, мимо продукта {len(итог['заявки мимо'])}"
    )
    return 1 if итог["outcome"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
