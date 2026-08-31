#!/usr/bin/env python3
"""Гейт каталога: подсадные не доехали до базы фактов, и прибор при этом жив.

    python scripts/check_catalog.py           # отчёт
    python scripts/check_catalog.py --check   # 0 годно / 1 не годно / 2 не смогли

ЗАЧЕМ ЭТО ГЕЙТ, А НЕ АБЗАЦ

Решение владельца «каталог — повод прочитать, а не повод записать» держится
ровно до первой сессии, которая не знает о нём. Импорт 763 каталожных строк в
базу фактов делается одной командой и выглядит как большая полезная работа:
покрытие «растёт», применимость падает вдвое, а метрика перестаёт быть прибором.
Написанное словами отменяется под сроком; отключение гейта видно в диффе (Ц7).

ЧТО ПРОВЕРЯЕТСЯ, ТРЕМЯ ИСХОДАМИ

  1. ПРИБОР ЖИВ. Контрольный набор `studio.mcp.catalog.CONTROL_SET`: четыре
     класса подсадных обязаны быть отсеяны, две здоровые записи обязаны пройти,
     одна нечитаемая обязана дать третий исход. Обратный контроль здесь не
     украшение: гейт, отсекающий всё, проходит проверку «подсадные не доехали»
     идеально и при этом бесполезен (правило И5).
  2. УТЕЧКА. Ни одна отсеянная запись каталога не встречается в
     `model_facts.jsonl` строкой, пришедшей С ХОСТА КАТАЛОГА; маршрутизатор —
     ни при каком источнике. Почему именно так, а не по совпадению имени, —
     в докстроке `studio.mcp.catalog.leaks`.
  3. КАНАЛЫ БЕЗ КЛЮЧА НЕ ИСЧЕЗЛИ. Четыре каталога (replicate, together,
     artificialanalysis, wavespeed) отвечают 401. Они обязаны стоять в отчёте
     опроса как «не смогли, нужен ключ». Пропасть из списка они могут только
     одним способом — если кто-то решит, что двух каналов достаточно, и тогда
     «опрошено 2, не смогли 0» соврёт про охват.

Ноль утечек при нуле проверенных записей — не успех (правило Р2), поэтому
пустой или отсутствующий каталог даёт 2, а не 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

from studio.mcp import catalog as cat  # noqa: E402
from scripts.poll_catalogs import KEYED, POLL_PATH  # noqa: E402


def keyed_gap(path: Path | None = None) -> dict:
    """Каждый закрытый ключом каталог записан как незакрытый третий исход?"""
    target = path or POLL_PATH
    if not target.exists():
        return {"outcome": UNMEASURED, "missing": [], "note": f"нет отчёта опроса {target}"}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {"outcome": UNMEASURED, "missing": [], "note": f"отчёт опроса не читается: {error}"}
    recorded = {
        str(row.get("catalog"))
        for row in payload.get("keyed_out") or []
        if row.get("state") == UNMEASURED and row.get("reason")
    }
    missing = sorted(set(KEYED) - recorded)
    if missing:
        return {
            "outcome": FAIL,
            "missing": missing,
            "note": "каталоги пропали из отчёта вместо «не смогли, нужен ключ»: "
            + ", ".join(missing),
        }
    return {
        "outcome": PASS,
        "missing": [],
        "note": f"закрытых ключом каналов записано {len(recorded)} из {len(KEYED)}",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="только код возврата и итог")
    args = parser.parse_args(argv)

    control = cat.control_report()
    audit = cat.audit()
    keyed = keyed_gap()

    print("ГЕЙТ КАТАЛОГА")
    if not args.check:
        for line in control["lines"]:
            print("  " + line)
    print(f"контрольный набор: проверено {control['checked']}, расхождений {control['violations']}")
    print(
        f"каталог: проверено {audit['checked']}, отсеяно {audit['rejected']}, "
        f"пропущено {audit['admitted']}, не смогли {audit['unmeasured']}"
    )
    for rule, count in sorted(audit.get("by_rule", {}).items()):
        print(f"  правилом {rule}: {count}")
    for rule in ("router", "deprecated", "edit_op", "forever_date"):
        if not audit.get("by_rule", {}).get(rule):
            print(f"  (правило {rule} не сработало ни разу на живом срезе — сработало на контроле)")
    print(
        f"утечек в базу фактов: {len(audit['leaks'])} (прочитано строк {audit.get('facts_read', 0)})"
    )
    for leak in audit["leaks"]:
        print(f"  {leak['model']} ({leak['rule']}) из {leak['source_url']}")
    print(f"каналы без ключа: {keyed['note']}")
    for problem in audit.get("problems", [])[:10]:
        print(f"  не смогли: {problem}")

    outcomes = [control["outcome"], audit["outcome"], keyed["outcome"]]
    if FAIL in outcomes:
        print(f"\nисход: {FAIL} — {audit['note'] if audit['outcome'] == FAIL else keyed['note']}")
        return 1
    if UNMEASURED in outcomes:
        note = next(
            part["note"]
            for part in ({**control, "note": "контрольный набор не отработал"}, audit, keyed)
            if part["outcome"] == UNMEASURED
        )
        print(f"\nисход: {UNMEASURED} — {note}")
        return 2
    print(f"\nисход: {PASS} — {audit['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
