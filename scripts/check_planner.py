#!/usr/bin/env python3
"""Гейт планировщика: план из брифа, и негативный контроль в обе стороны.

    python scripts/check_planner.py --check
    python scripts/check_planner.py --brief "оживить фото клиента, он говорит мою озвучку"

ЧТО ЗДЕСЬ СТОРОЖИТСЯ, И ПОЧЕМУ ИМЕННО ЭТО

1. ВОСЕМЬ НАСТОЯЩИХ БРИФОВ (`studio/fixtures/planner_briefs.jsonl`). У каждого
   выписан ожидаемый состав шагов, исход и КОД ПРИЧИНЫ. Сравнивается кортеж
   шагов целиком, а не вхождение: прибор, собирающий «что-нибудь похожее»,
   читается как работающий и не работает.

2. НЕГАТИВНЫЙ КОНТРОЛЬ В ОБЕ СТОРОНЫ (И5). Вход, где прибор обязан МОЛЧАТЬ:
   «сделай красиво» и бриф про промышленный манипулятор — ни одного шага, и
   исход третий. Вход, где обязан ШЕВЕЛЬНУТЬСЯ: шесть брифов со шагами. Без
   первой половины прибор, выдающий план на что угодно, прошёл бы приёмку; без
   второй — прибор, молчащий всегда.

3. ТРЕТИЙ ИСХОД ОТДЕЛЬНО ОТ ПУСТОГО ПЛАНА (Р1). `фоли-к-оживлению` обязан дать
   «не смогли» с НЕПУСТЫМ планом: операция словарю известна, база о ней молчит.
   Свернуть это в «шагов нет» значило бы потерять ровно то, что человек должен
   увидеть — какой шаг некем закрыть.

4. МОДЕЛЬ БЕЗ ДОКАЗАТЕЛЬСТВА ТОЛЬКО С ПОМЕТКОЙ. У каждого выбранного кандидата
   обязаны стоять строки доказательства, и если среди них нет ни одной строки
   ПРИМЕНИМОСТИ, пометка `planner.NOT_MEASURED_MARK` обязана стоять в выдаче.
   Проверяется на всех кандидатах всех брифов разом, числом.

5. ЗНАМЕНАТЕЛЬ. Строк в файле контроля и разобранных строк — два числа рядом:
   молча пропавший контроль не должен читаться как зелёный прогон.

Сети здесь нет (Т4): читается только `studio/knowledge/model_facts.jsonl`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import UNMEASURED  # noqa: E402

from studio import planner as pn  # noqa: E402
from studio.factindex import FactIndex  # noqa: E402

#: Дата, на которую судится свежесть фактов. ВЫБРАНО фиксированной: гейт,
#: зависящий от `date.today()`, краснеет однажды сам по себе, и разбирать это
#: будет тот, кто ничего не менял.
TODAY = "2026-09-02"


def run(path: Path = pn.DEFAULT_BRIEFS_PATH) -> dict:
    """Прогон всего набора. Возвращает числа, а не булев флаг (Е3)."""
    from datetime import date

    сегодня = date.fromisoformat(TODAY)
    индекс = FactIndex()
    разметка = None
    набор = pn.briefs(path)
    случаи = []
    for row in набор:
        начало = time.perf_counter()
        итог = pn.plan(
            str(row["brief"]),
            creative=str(row.get("creative") or ""),
            budget_usd=row.get("budget_usd"),
            today=сегодня,
            overrides=разметка,
            index=индекс,
        )
        шаги = tuple(s["step"] for s in итог["steps"])
        ждали = tuple(str(x) for x in (row.get("expect_steps") or ()))
        беды = []
        if шаги != ждали:
            беды.append(f"шаги {list(шаги)}, ждали {list(ждали)}")
        if итог["outcome"] != row["expect_outcome"]:
            беды.append(f"исход {итог['outcome']}, ждали {row['expect_outcome']}")
        if итог["reason"] != row["expect_reason"]:
            беды.append(f"причина {итог['reason']}, ждали {row['expect_reason']}")
        # Вхождение, а не равенство: база живая, и в неё дописывают. Почему
        # именно так — записано в шапке `planner_briefs.jsonl`.
        нет = [k for k in (row.get("expect_classes") or ()) if k not in итог["classes"]]
        if нет:
            беды.append(f"классы {итог['classes']} не содержат {нет}")
        случаи.append(
            {
                "id": str(row["id"]),
                "outcome": итог["outcome"],
                "reason": итог["reason"],
                "steps": list(шаги),
                "faults": беды,
                "ms": round((time.perf_counter() - начало) * 1000, 1),
                "plan": итог,
            }
        )

    # Пометка на кандидате без применимости — числом по всем брифам разом.
    кандидатов = 0
    без_применимости = 0
    без_пометки = 0
    без_доказательства = 0
    for c in случаи:
        for s in c["plan"]["steps"]:
            выбран = s["chosen"]
            if выбран is None:
                continue
            кандидатов += 1
            if not выбран["evidence"]:
                без_доказательства += 1
            if выбран["applicability"] == 0:
                без_применимости += 1
                if выбран["mark"] != pn.NOT_MEASURED_MARK:
                    без_пометки += 1

    молчащие = [c for c in случаи if not c["steps"]]
    заговорившие = [c for c in случаи if c["steps"]]
    исходы = {c["outcome"] for c in случаи}
    причины = {c["reason"] for c in случаи}
    провалы = [c for c in случаи if c["faults"]]

    return {
        "rows_in_file": pn.rows_in(path),
        "parsed": len(набор),
        "cases": случаи,
        "faults": провалы,
        "silent": len(молчащие),
        "spoke": len(заговорившие),
        "outcomes_seen": sorted(исходы),
        "reasons_seen": sorted(причины),
        "candidates": кандидатов,
        "candidates_without_applicability": без_применимости,
        "candidates_unmarked": без_пометки,
        "candidates_without_evidence": без_доказательства,
    }


def verdict(итог: dict) -> tuple[int, list[str]]:
    """Код возврата и причины. Три исхода, и третий не сворачивается (Р1)."""
    беды: list[str] = []
    if итог["parsed"] == 0:
        return 2, ["контрольный набор пуст: мерить нечем"]
    if итог["parsed"] != итог["rows_in_file"]:
        беды.append(
            f"строк в файле {итог['rows_in_file']}, разобрано {итог['parsed']}: "
            "контроль пропал молча"
        )
    for c in итог["faults"]:
        беды.append(f"{c['id']}: " + "; ".join(c["faults"]))
    if not итог["silent"]:
        беды.append("ни на одном входе прибор не промолчал: негативного контроля нет")
    if not итог["spoke"]:
        беды.append("ни на одном входе прибор не собрал плана: он мёртв")
    if len(итог["outcomes_seen"]) < 2:
        беды.append(f"различённых исходов {len(итог['outcomes_seen'])}, нужно не меньше двух")
    if итог["candidates_unmarked"]:
        беды.append(
            f"кандидатов без применимости {итог['candidates_without_applicability']}, "
            f"из них БЕЗ ПОМЕТКИ «{pn.NOT_MEASURED_MARK}» {итог['candidates_unmarked']}"
        )
    if итог["candidates_without_evidence"]:
        беды.append(
            f"кандидатов без единой строки доказательства {итог['candidates_without_evidence']}: "
            "чем выбран — не сказано"
        )
    return (1 if беды else 0), беды


def render(итог: dict) -> str:
    строки = [
        f"брифов в файле {итог['rows_in_file']}, разобрано {итог['parsed']}",
        (
            f"молчал на {итог['silent']}, собрал план на {итог['spoke']}; "
            f"исходов различено {len(итог['outcomes_seen'])} {итог['outcomes_seen']}; "
            f"причин {len(итог['reasons_seen'])} {итог['reasons_seen']}"
        ),
        (
            f"кандидатов выбрано {итог['candidates']}, из них без применимости "
            f"{итог['candidates_without_applicability']} (все с пометкой: "
            f"{итог['candidates_unmarked'] == 0}), без доказательства "
            f"{итог['candidates_without_evidence']}"
        ),
        "",
    ]
    for c in итог["cases"]:
        знак = "!" if c["faults"] else ("?" if c["outcome"] == UNMEASURED else ".")
        строки.append(
            f"  {знак} {c['id']:20} {c['outcome']:18} [{c['reason']:22}] "
            f"шаги: {', '.join(c['steps']) or '—'} ({c['ms']} мс)"
        )
        for f in c["faults"]:
            строки.append(f"      ПРОВАЛ: {f}")
    return "\n".join(строки)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="прогнать контрольный набор")
    ap.add_argument("--brief", default="", help="собрать план по одному брифу")
    ap.add_argument("--creative", default="", help="путь к поданному креативу")
    ap.add_argument("--json", action="store_true", help="выдать машиночитаемо")
    args = ap.parse_args()

    if args.brief:
        итог = pn.plan(args.brief, creative=args.creative)
        print(json.dumps(итог, ensure_ascii=False, indent=2) if args.json else pn.render(итог))
        return 0

    итог = run()
    код, беды = verdict(итог)
    if args.json:
        print(json.dumps({**итог, "exit": код, "faults_named": беды}, ensure_ascii=False, indent=2))
    else:
        print(render(итог))
        for b in беды:
            print(f"ПРОВАЛ: {b}")
        print("ok" if код == 0 else ("не смогли" if код == 2 else "провал"))
    return код


if __name__ == "__main__":
    raise SystemExit(main())
