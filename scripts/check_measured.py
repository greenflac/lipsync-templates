#!/usr/bin/env python3
"""Сторожит адрес для измеренных чисел — и размер хэндофа, который он заменяет.

    python scripts/check_measured.py --check

ДВЕ ПРОВЕРКИ, И ВТОРАЯ ВАЖНЕЕ

1. СХЕМА. Каждая запись в `studio/knowledge/measured.jsonl` несёт id, тему,
   происхождение из И4, исход из Р1, дату, заметку и хотя бы одно из двух —
   скрипт или метод. Число, которое нельзя перепроверить, это слух с датой.

2. РАЗМЕР ХЭНДОФА. Ради этого всё и делалось. Один `HANDOFF_*.md` дорос до 2330
   строк и ~39 000 токенов, и каждая сессия читала их целиком, чтобы найти три
   числа — платя за это контекстом и дрейфом на каждом ходу. Правило «факты не
   в хэндоф» существовало и раньше, словами, и не соблюдалось. Правило, которое
   обязано выполняться всегда, — это гейт, а не строка в документе (Ц7).

ТРИ ИСХОДА (Р1): годно / не годно / не смогли, и третий — когда файла со
списком нет вообще, а не когда он пуст.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

from studio import measured  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

#: Сколько строк хэндофу позволено. ВЫБРАНО 400: столько нужно, чтобы описать
#: состояние ветки, открытые вопросы и куда идти дальше, и мало, чтобы архив
#: туда не поместился. Прежний рекорд — 2330 строк, из них числа и разборы
#: багов, у которых есть свои адреса.
HANDOFF_MAX_LINES = 400

#: Хэндофы, написанные ДО этого правила. Они не переписываются задним числом:
#: чужой append-only документ трогать нельзя (Ц2), а свой уже разгружен. Список
#: пустой не бывает молча — каждый элемент виден в отчёте и в диффе.
GRANDFATHERED = ("HANDOFF_MCP_AGENT.md", "HANDOFF_studio-mvp.md")


def check_records(rows: list[dict]) -> dict:
    """Схема записей. Вынесено из main (Т5), чтобы развилка была достижима тестом."""
    if not rows:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "проблемы": [],
            "note": "в measured.jsonl нет ни одной записи — проверять нечего",
        }
    found = [p for row in rows for p in measured.problems(row)]
    return {
        "outcome": FAIL if found else PASS,
        "checked": len(rows),
        "violations": len(found),
        "unmeasured": 0,
        "проблемы": [f"{p.record_id} · {p.field}: {p.said}" for p in found],
        "note": (
            f"{len(rows)} записей: у каждой происхождение из И4, исход из Р1 и способ перепроверки"
            if not found
            else f"{len(found)} записей нельзя перепроверить или у них нет происхождения"
        ),
    }


def check_handoffs(sizes: dict[str, int], limit: int = HANDOFF_MAX_LINES) -> dict:
    """Размер хэндофов. `sizes` — имя файла к числу строк, чтобы тест не ходил на диск."""
    if not sizes:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "раздулись": [],
            "note": "хэндофов не найдено — сравнивать нечего",
        }
    fat = sorted(
        f"{name}: {count} строк при потолке {limit}"
        for name, count in sizes.items()
        if count > limit and name not in GRANDFATHERED
    )
    old = sorted(name for name in sizes if name in GRANDFATHERED)
    checked = len(sizes) - len(old)
    # Ноль проверенных — не успех, даже когда нарушений тоже ноль (правило Р2).
    # Поймано собственным тестом: файл, целиком состоящий из унаследованных
    # хэндофов, печатал «годно», ничего не проверив.
    outcome = FAIL if fat else (PASS if checked else UNMEASURED)
    return {
        "outcome": outcome,
        "checked": checked,
        "violations": len(fat),
        "unmeasured": len(old),
        "раздулись": fat,
        "унаследованные": old,
        "note": (
            f"{checked} хэндофов в пределах {limit} строк"
            if not fat and checked
            else f"{len(fat)} хэндофов снова стали архивом: {'; '.join(fat)}"
            if fat
            else f"проверять нечего: все {len(old)} хэндофов унаследованы"
        ),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--find", default="", help="показать записи по подстроке")
    args = parser.parse_args(argv)

    rows = measured.load()
    if args.find:
        for row in measured.find(measured.current(rows), args.find):
            # Запись без одного числа — норма: у распределения по уровням его
            # нет, оно в заметке. Печатать «None» было бы враньём про пустоту.
            value = " ".join(
                str(part) for part in (row.get("value"), row.get("unit")) if part is not None
            ).strip()
            print(f"\n{row['subject']}\n  {row['origin']} · {row['outcome']} · {value or '—'}")
            print(f"  {row.get('script') or row.get('method')}\n  {row['note']}")
        return 0

    records = check_records(rows)
    sizes = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in sorted(REPO.glob("HANDOFF_*.md"))
    }
    handoffs = check_handoffs(sizes)

    for problem in records["проблемы"]:
        print(f"  СХЕМА {problem}")
    for fat in handoffs["раздулись"]:
        print(f"  РАЗДУЛСЯ {fat}")
    for name in handoffs.get("унаследованные", []):
        print(f"  (унаследован, до правила: {name})")

    checked = records["checked"] + handoffs["checked"]
    violations = records["violations"] + handoffs["violations"]
    unmeasured = records["unmeasured"] + handoffs["unmeasured"]
    outcome = FAIL if violations else (PASS if checked else UNMEASURED)
    print(f"\nпроверено {checked}\nнарушений {violations}\nне смогли {unmeasured}")
    print(f"\n{outcome}: {records['note']}; {handoffs['note']}")
    if not args.check:
        return 0
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[outcome]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
