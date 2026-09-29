#!/usr/bin/env python3
"""Отметить, что утверждения за страницей ПЕРЕЧИТАНЫ.

ЗАЧЕМ

Канал отпечатков говорит «страница изменилась» и ставит её в очередь. Человек
(или агент) перечитывает утверждения за ней — и очередь предлагает ту же
страницу завтра, потому что о перечитывании она не знает ничего. ИЗМЕРЕНО
2026-09-03: 11 страниц перечитаны, 56 утверждений сверены, очередь по-прежнему
показывает те же 11.

Это тот же дефект, что был у портальных семейств: очередь предлагает работу,
которая сделана. Очередь, где строки сделаны, учит себя не открывать.

ЧЕГО ЭТА ЗАПИСЬ НЕ ДЕЛАЕТ, И ЭТО ГЛАВНОЕ

Она НЕ трогает `stated_on` у фактов. Дата факта — дата ИСТОЧНИКА, и
перечитывание её не сдвигает: страница, прочитанная сегодня и не изменившаяся
с августа, остаётся августовской. Здесь записывается только НАШЕ действие:
кто, когда и сколько утверждений сверил.

ТРИ ИСХОДА (Р1) у самой отметки

    годно      запись дописана
    не годно   адрес не похож на адрес (пустой, без схемы)
    не смогли  журнал не читается
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ЖУРНАЛ = Path(__file__).resolve().parents[1] / "studio" / "knowledge" / "reread.jsonl"

_ШАПКА = (
    "// Перечитанные страницы: НАШЕ действие, а не дата источника.\n"
    "// `stated_on` у фактов этим не двигается — см. шапку scripts/mark_reread.py.\n"
    "// Журнал: строки дописываются, прежние не трогаются.\n"
)


def записи(путь: Path = ЖУРНАЛ) -> list[dict[str, Any]]:
    if not путь.is_file():
        return []
    строки: list[dict[str, Any]] = []
    for строка in путь.read_text(encoding="utf-8").splitlines():
        строка = строка.strip()
        if not строка or строка.startswith("//"):
            continue
        try:
            строки.append(json.loads(строка))
        except ValueError:
            continue
    return строки


def последнее(путь: Path = ЖУРНАЛ) -> dict[str, str]:
    """Адрес -> дата последнего перечитывания. Журнал: побеждает последняя."""
    итог: dict[str, str] = {}
    for запись in записи(путь):
        url = str(запись.get("url") or "")
        if url:
            итог[url] = str(запись.get("on") or "")
    return итог


def дописать(запись: dict[str, Any], путь: Path = ЖУРНАЛ) -> None:
    было = путь.read_text(encoding="utf-8") if путь.is_file() else _ШАПКА
    путь.write_text(было + json.dumps(запись, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--checked", type=int, required=True, help="сверено утверждений")
    parser.add_argument("--confirmed", type=int, required=True, help="подтвердилось дословно")
    parser.add_argument("--corrected", type=int, default=0, help="уточнено или снято")
    parser.add_argument("--added", type=int, default=0, help="записано новых фактов")
    parser.add_argument("--note", default="")
    parser.add_argument("--on", default=date.today().isoformat())
    args = parser.parse_args(argv)

    if not urlparse(args.url).scheme or not urlparse(args.url).netloc:
        print(f"не адрес: {args.url!r}")
        print("\nпроверено 0\nнарушений 1\nне смогли 0")
        return 1
    if args.checked != args.confirmed + args.corrected:
        # Р2: три числа обязаны сходиться, иначе отметка врёт о работе.
        print(
            f"числа не сходятся: сверено {args.checked}, "
            f"подтвердилось {args.confirmed} + уточнено {args.corrected}"
        )
        print("\nпроверено 0\nнарушений 1\nне смогли 0")
        return 1

    дописать(
        {
            "url": args.url,
            "on": args.on,
            "checked": args.checked,
            "confirmed": args.confirmed,
            "corrected": args.corrected,
            "added": args.added,
            "note": args.note,
        }
    )
    print(
        f"отмечено: {args.url}\n  сверено {args.checked}, подтвердилось {args.confirmed}, "
        f"уточнено {args.corrected}, новых фактов {args.added}"
    )
    print(f"\nпроверено {args.checked}\nнарушений 0\nне смогли 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
