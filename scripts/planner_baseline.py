#!/usr/bin/env python
"""Что репозиторий отвечал на восемь настоящих брифов ДО планировщика.

ЗАЧЕМ ЭТОТ СКРИПТ СУЩЕСТВУЕТ

Правило дома П1: счётчик раньше ручки. Прежде чем заводить прибор, который
собирает план из брифа, надо числом показать, чего именно не хватает — иначе
«не собиралось» неотличимо от «собиралось, но плохо».

Скрипт не импортирует `studio/planner.py` намеренно: он меряет то, что было
БЕЗ него, и обязан продолжать это делать после. Сети здесь нет (Т4): читается
только `studio/knowledge/model_facts.jsonl`.

Снимок прогона лежит рядом с набором брифов:
`studio/fixtures/planner_baseline_2026-09-02.txt`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.factindex import DEFAULT_K, FactIndex, verdict  # noqa: E402

BRIEFS = Path(__file__).resolve().parents[1] / "studio" / "fixtures" / "planner_briefs.jsonl"


def briefs(path: Path = BRIEFS) -> list[dict]:
    """Набор брифов из файла. Негодная строка пропускается и считается отдельно."""
    if not path.is_file():
        return []
    строки = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("id") and "brief" in row:
            строки.append(row)
    return строки


def rows_in(path: Path = BRIEFS) -> int:
    """Сколько строк данных в файле, годных и негодных вместе."""
    if not path.is_file():
        return 0
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("//")
    )


def measure(path: Path = BRIEFS) -> dict:
    """Прогон восьми брифов по тому, что в репозитории уже есть.

    Меряются две вещи, и обе — про ОТСУТСТВИЕ моста между словами заказчика и
    планом:

    * `steps` — сколько шагов плана репозиторий произвёл из брифа. Ни один
      модуль этого не делает, поэтому число здесь всегда 0, и оно печатается,
      а не подразумевается;
    * `facts` — сколько фактов достаёт поиск, если подать ему бриф ЦЕЛИКОМ.
      Это единственный существующий канал «слова задачи -> база», и главное
      его свойство меряется тут же: молчит ли он на брифе, к которому база
      отношения не имеет.
    """
    индекс = FactIndex()
    случаи = []
    for row in briefs(path):
        находки = индекс.search(str(row["brief"]), k=DEFAULT_K)
        в = verdict(находки, str(row["brief"]))
        случаи.append(
            {
                "id": str(row["id"]),
                "brief": str(row["brief"]),
                "steps_built": 0,
                "facts_found": len(находки),
                "search_outcome": str(в["outcome"]),
                "models": sorted({h.fact.model for h in находки}),
                "expect_steps": list(row.get("expect_steps") or ()),
            }
        )
    ждали = sum(len(c["expect_steps"]) for c in случаи)
    собрано = sum(c["steps_built"] for c in случаи)
    молчащие = [c for c in случаи if not c["expect_steps"]]
    заговорил = [c for c in молчащие if c["facts_found"]]
    return {
        "rows_in_file": rows_in(path),
        "briefs": len(случаи),
        "steps_expected": ждали,
        "steps_built": собрано,
        "negative_controls": len(молчащие),
        "negative_controls_answered": len(заговорил),
        "cases": случаи,
    }


def render(итог: dict) -> str:
    строки = [
        f"брифов в файле {итог['rows_in_file']}, разобрано {итог['briefs']}",
        f"шагов плана ожидается {итог['steps_expected']}, собрано репозиторием {итог['steps_built']}",
        (
            f"негативных контролей {итог['negative_controls']}, "
            f"на скольких поиск фактов всё равно ответил: "
            f"{итог['negative_controls_answered']}"
        ),
        "",
    ]
    for c in итог["cases"]:
        строки.append(
            f"  {c['id']:20} шагов собрано {c['steps_built']}/{len(c['expect_steps'])}; "
            f"поиск: {c['search_outcome']}, фактов {c['facts_found']}, "
            f"моделей {len(c['models'])}"
        )
        if c["models"]:
            строки.append(f"      {', '.join(c['models'])}")
    return "\n".join(строки)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="выдать замер машиночитаемо")
    args = ap.parse_args()
    итог = measure()
    print(json.dumps(итог, ensure_ascii=False, indent=2) if args.json else render(итог))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
