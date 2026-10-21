#!/usr/bin/env python3
"""Покрытие реестра эндпоинтов по работам: сколько можно ЗАКАЗАТЬ и почём.

    python scripts/endpoint_report.py            # таблица по работам
    python scripts/endpoint_report.py --json     # то же машиной
    python scripts/endpoint_report.py --check    # гейт: не хуже записанного
    python scripts/endpoint_report.py --write    # записать текущее как базу гейта

ЗАЧЕМ (2026-10-15, пятый круг). Реестр (`studio/endpoints.py`) — то, из чего
плановщик берёт кандидатов на шаг. Работа, у которой ноль заказываемых
эндпоинтов, даёт шаг без кандидата; работа, у которой эндпоинты без цены, —
план «цена неизвестна». Отчёт печатает по каждой работе: заказываемых узлов,
сколько из них с ценой (%), сколько с записанной длиной прогона (%) — для
видео это решает, сколько прогонов стоит ролик.

ГЕЙТ — НЕ ХУЖЕ ЗАПИСАННОГО (`studio/knowledge/endpoint_coverage.json`): по
каждой работе число заказываемых, с ценой и с длиной прогона не падает. Рост —
не провал, а повод переписать базу (`--write`), и это печатается.

ТРИ ИСХОДА (П1): 0 годно / 1 не годно (упало) / 2 не смогли (базы нет, реестр
пуст — ноль проверок не «годно»).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio import endpoints as ep  # noqa: E402
from studio.factindex import FactIndex  # noqa: E402

BASELINE = ROOT / "studio" / "knowledge" / "endpoint_coverage.json"

#: Поля, которые гейт держит от падения (счёты, а не проценты: процент растёт и
#: от того, что из знаменателя ушёл узел без цены, — это не улучшение).
GUARDED: tuple[str, ...] = ("orderable", "priced", "with_run_length")


def measure() -> list[dict[str, Any]]:
    индекс = FactIndex()
    return ep.coverage(ep.build(индекс.facts))


def compare(now: list[dict[str, Any]], base: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """(падения, рост) по работам относительно базы."""
    по_работе = {r["function"]: r for r in base}
    упало: list[str] = []
    выросло: list[str] = []
    for r in now:
        b = по_работе.get(r["function"])
        if b is None:
            выросло.append(f"{r['function']}: новая работа в словаре")
            continue
        for поле in GUARDED:
            if r[поле] < b[поле]:
                упало.append(f"{r['function']}.{поле}: {b[поле]} -> {r[поле]}")
            elif r[поле] > b[поле]:
                выросло.append(f"{r['function']}.{поле}: {b[поле]} -> {r[поле]}")
    for ф in по_работе:
        if ф not in {r["function"] for r in now}:
            упало.append(f"{ф}: работа исчезла из словаря")
    return упало, выросло


def table(rows: list[dict[str, Any]]) -> str:
    строки = [f"{'function':20} {'orderable':>9} {'priced':>12} {'run length':>14}"]
    for r in rows:
        прогон = f"{r['with_run_length']} ({r['run_length_pct']:.0f}%)" if r["video"] else "—"
        строки.append(
            f"{r['function']:20} {r['orderable']:>9} {r['priced']:>5} ({r['priced_pct']:>4.0f}%) {прогон:>14}"
        )
    return "\n".join(строки)


def main(argv: list[str]) -> int:
    разбор = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    разбор.add_argument("--check", action="store_true")
    разбор.add_argument("--write", action="store_true")
    разбор.add_argument("--json", action="store_true")
    дано = разбор.parse_args(argv)
    сейчас = measure()
    if not any(r["orderable"] for r in сейчас):
        print(
            "не смогли: в реестре ни одного заказываемого эндпоинта — база фактов не прочиталась?"
        )
        return 2
    if дано.json:
        print(json.dumps(сейчас, ensure_ascii=False, indent=1))
    else:
        print(table(сейчас))
    if дано.write:
        BASELINE.write_text(
            json.dumps(сейчас, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"записано: {BASELINE.relative_to(ROOT)}")
        return 0
    if not дано.check:
        return 0
    if not BASELINE.exists():
        print(f"не смогли: базы гейта нет ({BASELINE.relative_to(ROOT)}) — сравнивать не с чем")
        return 2
    база = json.loads(BASELINE.read_text(encoding="utf-8"))
    упало, выросло = compare(сейчас, база)
    print()
    print(f"проверено {len(сейчас) * len(GUARDED)}")
    print(f"нарушений {len(упало)}")
    print("не смогли 0")
    for с in упало:
        print(f"  УПАЛО {с}")
    if выросло:
        print(
            f"  выросло {len(выросло)} (база устарела — перепишите `--write`): "
            + "; ".join(выросло[:6])
        )
    if упало:
        print("не годно: покрытие реестра упало по сравнению с записанным")
        return 1
    print("годно: покрытие реестра не ниже записанного")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
