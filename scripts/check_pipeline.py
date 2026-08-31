#!/usr/bin/env python3
"""Гейт валидатора-2: он принимает ПАЙПЛАЙН и обязан ошибаться в обе стороны.

    python scripts/check_pipeline.py --check
    python scripts/check_pipeline.py --plan путь/к/плану.json   # живая база

ЧТО ЗДЕСЬ СТОРОЖИТСЯ, И ПОЧЕМУ ИМЕННО ЭТО

1. ПОСЕВНЫЕ МУТАНТЫ (И5). Восемь сломанных пайплайнов, в каждом РОВНО ОДИН
   посеянный дефект своего класса. Валидатор обязан не просто отвергнуть
   каждый — он обязан НАЗВАТЬ ТОТ САМЫЙ класс и только его. Совпадение по
   исходу без совпадения по классу считается бедой: прибор, отвечающий
   «не годно» с произвольным объяснением, читается как работающий и не
   работает. Именно поэтому сравнивается КОРТЕЖ классов целиком, а не
   вхождение ожидаемого в список.

2. ЗДОРОВЫЕ ЧУЖАКИ (И5, вторая половина). Четыре рабочих пайплайна, которые
   обязаны пройти. Без них прибор, отвечающий «не годно» на всё, прошёл бы
   приёмку с идеальным счётом по мутантам. Блюпринт называет это прямо:
   отклонённый здоровый — провал валидатора, и это то, что делает «мы не
   цензоры» числом, а не заявлением.

3. ТРИ ИСХОДА РАЗЛИЧАЮТСЯ (Р1). Контрольный набор обязан дать все три:
   `годно` на чужаках, `не годно` на четырёх классах и `не смогли` на трёх.
   Меньше трёх — прибор меряет не то, и это ровно тот дефект, который на этом
   проекте уже стоил прогонов.

4. КАЖДЫЙ ИЗ СЕМИ КЛАССОВ ИМЕЕТ СВОЕГО МУТАНТА. Класс без посева — это код,
   который никто не запускал: он не может покраснеть и потому не сторожит
   ничего. Гейт краснеет, если хоть один класс остался без мутанта.

5. НИ ОДНА СТРОКА КОНТРОЛЯ НЕ ПРОПАДАЕТ МОЛЧА. `load_controls` пропускает
   негодную строку, `rows_in` считает все; расхождение — это контроль, который
   человек считает стоящим, а его нет.

ПОЧЕМУ У КОНТРОЛЯ ФИКСИРОВАННАЯ ДАТА. Каждая строка контроля несёт своё
`today`. Класс `устарел` считает возраст утверждения, и контроль с датой
`date.today()` начал бы краснеть сам собой через `STALE_AFTER_DAYS` дней после
сборки — то есть прибор ломался бы от хода времени, а не от дефекта. Живой
путь (`--plan`) берёт настоящее сегодня.

Сети здесь нет (Т4): контроль несёт свои факты внутри себя и живой базы не
касается вовсе.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

from studio import factaxis as fa  # noqa: E402
from studio import pipeline as pl  # noqa: E402
from studio.selfrag.facts import load_facts  # noqa: E402


def control_results(controls: list[pl.Control]) -> list[dict]:
    """Исход каждой контрольной подачи рядом с ожидаемым. Вынесено из main (Т5)."""
    out = []
    for c in controls:
        сегодня = date.fromisoformat(c.today) if c.today else None
        отчёт = pl.pipeline_report(c.pipeline, c.facts, сегодня)
        out.append(
            {
                "id": c.id,
                "kind": c.kind,
                "expected_outcome": c.expect_outcome,
                "got_outcome": отчёт["outcome"],
                "expected_classes": list(c.expect_classes),
                "got_classes": list(отчёт["classes"]),
                "report": отчёт,
            }
        )
    return out


def control_verdict(results: list[dict], rows: int) -> dict:
    """Прибор различает то, что заявлено, и в обе стороны.

    Пять условий, и ни одно не выводится из остальных: исход, классы, набор
    исходов, покрытие классов посевом и целость файла контроля.
    """
    if not results:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "контрольных подач нет — валидатор не проверен ничем",
            "problems": [],
        }

    беды: list[str] = []
    for r in results:
        if r["got_outcome"] != r["expected_outcome"]:
            беды.append(
                f"{r['id']}: ожидался исход {r['expected_outcome']}, вышло {r['got_outcome']}"
            )
        if r["got_classes"] != r["expected_classes"]:
            беды.append(
                f"{r['id']}: ожидались классы {r['expected_classes'] or ['ни одного']}, "
                f"названы {r['got_classes'] or ['ни одного']}"
            )

    мутанты = [r for r in results if r["kind"] == pl.KIND_MUTANT]
    чужаки = [r for r in results if r["kind"] == pl.KIND_HEALTHY]
    if not мутанты:
        беды.append("в наборе нет ни одного мутанта: пропустить нечего")
    if not чужаки:
        беды.append("в наборе нет ни одного здорового чужака: прибор-отказник прошёл бы")
    прошедшие_мутанты = [r["id"] for r in мутанты if r["got_outcome"] == PASS]
    if прошедшие_мутанты:
        беды.append(f"мутанты прошли валидатор: {', '.join(прошедшие_мутанты)}")
    отвергнутые_чужаки = [r["id"] for r in чужаки if r["got_outcome"] != PASS]
    if отвергнутые_чужаки:
        беды.append(f"здоровые чужаки отвергнуты: {', '.join(отвергнутые_чужаки)}")

    исходы = {r["got_outcome"] for r in results}
    if len(исходы) < 3:
        беды.append(f"валидатор различает {len(исходы)} исход(а) из трёх: {sorted(исходы)}")

    посеяно = {k for r in мутанты for k in r["expected_classes"]}
    без_посева = [k for k in pl.CLASSES if k not in посеяно]
    if без_посева:
        беды.append(f"классы без посевного мутанта: {', '.join(без_посева)}")

    if rows != len(results):
        беды.append(
            f"строк в файле контроля {rows}, принято {len(results)}: "
            f"{rows - len(results)} пропущено молча"
        )

    return {
        "outcome": FAIL if беды else PASS,
        "checked": len(results),
        "violations": len(беды),
        "unmeasured": 0,
        "note": (
            "; ".join(беды[:6])
            if беды
            else (
                f"{len(мутанты)} мутантов отвергнуты с названным классом, "
                f"{len(чужаки)} чужаков пропущены, исходов различено {len(исходы)}, "
                f"классов посеяно {len(посеяно)} из {len(pl.CLASSES)}"
            )
        ),
        "problems": беды,
    }


def plan_report(path: Path) -> str:
    """Живой план против живой базы фактов. Вынесено из main (Т5)."""
    row = json.loads(path.read_text(encoding="utf-8"))
    план = pl.parse_pipeline(row)
    отчёт = pl.pipeline_report(план, load_facts(), None, fa.load_overrides())
    return pl.render(отчёт)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="код возврата 0/1/2")
    parser.add_argument("--plan", metavar="ФАЙЛ", help="разобрать план по живой базе")
    parser.add_argument(
        "--controls", metavar="ФАЙЛ", default=str(pl.DEFAULT_CONTROLS_PATH), help="файл контроля"
    )
    args = parser.parse_args(argv)

    if args.plan:
        print(plan_report(Path(args.plan)))
        return 0

    путь = Path(args.controls)
    контроли = pl.load_controls(путь)
    результаты = control_results(контроли)
    вердикт = control_verdict(результаты, pl.rows_in(путь))

    for r in результаты:
        знак = (
            "ok  "
            if r["got_outcome"] == r["expected_outcome"]
            and r["got_classes"] == r["expected_classes"]
            else "БЕДА"
        )
        классы = ", ".join(r["got_classes"]) or "ни одного класса"
        print(
            f"  {знак} [{r['kind']}] {r['id']}: "
            f"{fa.OUTCOME_WORDS.get(r['got_outcome'], r['got_outcome'])} — {классы}"
        )

    роды = Counter(k for r in результаты for k in r["got_classes"])
    print("\n  классы названы: " + ", ".join(f"{k} {роды.get(k, 0)}" for k in pl.CLASSES))
    for беда in вердикт["problems"][:10]:
        print(f"  БЕДА {беда}")

    # Два счёта, и они НЕ складываются в один: внутренний — про то, что
    # валидатор нашёл в подачах (там нарушения ПОСЕЯНЫ и обязаны быть), внешний
    # — про то, что гейт нашёл в самом валидаторе. Сложенные вместе, они дали бы
    # «нарушений 5» рядом с исходом `годно`, то есть число, читающееся наоборот.
    print(
        f"\nвнутри подач: оракулов отработало {sum(r['report']['checked'] for r in результаты)}, "
        f"нарушений {sum(r['report']['violations'] for r in результаты)}, "
        f"не смогли {sum(r['report']['unmeasured'] for r in результаты)}, "
        f"не заявлено {sum(r['report']['not_declared'] for r in результаты)}"
    )
    print(
        f"\nпроверено {вердикт['checked']}\nнарушений {вердикт['violations']}"
        f"\nне смогли {вердикт['unmeasured']}"
    )
    print(f"\n{вердикт['outcome']}: {вердикт['note']}")

    if not args.check:
        return 0
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[вердикт["outcome"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
