#!/usr/bin/env python3
"""Т1: мутация решений СВЕДЕНИЯ семнадцатого круга (маршруты × экспертиза) — в обе стороны.

    python scripts/mutate_round17_integration.py          # все мутанты
    python scripts/mutate_round17_integration.py 0 4      # мутанты с 0 по 3

Что мутируется: пересказ / нарезка рядом с вшитыми субтитрами (снятие старой полосы остаётся, цена
по секундам нарезки, строка «ваши субтитры — расшифровка не нужна» уходит); тег `mul` — не цель
перевода; размытие фона рядом с заменой человека целиком; дверь согласованных учений закрыта для
несовершеннолетнего (поле и слова), выдуманного заявления и зрителя вне своих взрослых сотрудников.

Устройство — как у `scripts/mutate_round16_integration.py`. ТРИ ИСХОДА (Р1).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_round17_integration",)

RA = "studio/recipes/apply.py"
R17 = "studio/routes_r17.py"
CS = "studio/consented_simulation.py"

#: (файл, было, стало, что ломается)
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    (RA, '        if "burned_subtitles_replace" in acc.priors:\n            # Round-17 integration: the edit left',
     "        if False:\n            # Round-17 integration: the edit left", "пересказ съедает снятие вшитых субтитров"),
    (RA, "        drop_assembly = (*drop_assembly, bs.NOTE_BURN_CAPTIONS)\n", "        drop_assembly = drop_assembly\n",
     "строка «расшифровка не нужна» рядом с расшифровкой"),
    (RA, '    blur_from = "правка_видео" if "правка_видео" in steps else "замена_фигуры" if "замена_фигуры" in steps else None',
     '    blur_from = "правка_видео" if "правка_видео" in steps else None', "размытие фона теряется рядом с заменой человека"),
    (RA, "            steps = list(dict.fromkeys((*steps, \"удаление_фона_видео\")))\n",
     "            steps = _replace_step(steps, \"замена_фигуры\", \"удаление_фона_видео\")\n", "маска вытесняет замену человека"),
    (R17, 'SUBTITLE_ADD_REMOVAL_TASKS: frozenset[str] = frozenset({"dub-translate", SHORTS_TASK})',
     'SUBTITLE_ADD_REMOVAL_TASKS: frozenset[str] = frozenset({"dub-translate"})', "нарезка без снятия старой полосы"),
    (R17, '                step_seconds["правка_видео"] = (float(spec.duration_s), float(spec.duration_s) / штук)\n',
     "                pass\n", "снятие полосы по секундам сериала, а не нарезки"),
    (R17, 'if str(т).split("-")[0].lower() != MIXED_LANGUAGE_TAG]', "if True]", "mul считается целью перевода"),
    (R17, '    if getattr(spec, "task", None) == SHORTS_TASK:\n        return False\n', "",
     "слова нарезки о новых субтитрах снимают старые"),
    (R17, '    if EDIT_BURN_CAPTIONS in set(getattr(spec, "edit", None) or ()) and', '    if False and',
     "названное вшивание новых субтитров снимает старые"),
    (CS, '        and person.get("minor") is not True\n', "", "несовершеннолетний проходит как свой"),
    (CS, '    if _strings(spec.get("audience")) - INTERNAL_AUDIENCES:\n        return нет\n', "", "зритель вне сотрудников открывает дверь"),
    (CS, 'INTERNAL_AUDIENCES: frozenset[str] = frozenset({"adults"})',
     'INTERNAL_AUDIENCES: frozenset[str] = frozenset({"adults", "general"})', "широкая публика считается своей"),
    (CS, '        if з.get("fabricated") is True:\n            return нет\n', "", "выдуманное заявление открывает дверь"),
    (CS, '    if W_KEEP_REFUSED.search(str(brief or "")) or W_MINOR.search(str(brief or "")):\n',
     '    if W_KEEP_REFUSED.search(str(brief or "")):\n', "ребёнок словами не закрывает дверь"),
)

def clean() -> None:
    for p in ROOT.rglob("__pycache__"):
        if ".claude" not in p.parts:
            shutil.rmtree(p, ignore_errors=True)


def run() -> int:
    clean()
    return subprocess.run(
        [sys.executable, "-B", "-m", "unittest", *НАБОРЫ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).returncode


def main(argv: list[str]) -> int:
    с, по = (int(argv[0]), int(argv[1])) if len(argv) == 2 else (0, len(MUTANTS))
    здоровый = run()
    print(f"ЗДОРОВЫЙ | тесты rc={здоровый}")
    if здоровый != 0:
        print("не годно: здоровое дерево красное — таблица мутаций ничего не значит")
        return 1
    промолчали: list[str] = []
    нет_цели: list[str] = []
    for файл, было, стало, что in MUTANTS[с:по]:
        путь = ROOT / файл
        исходный = путь.read_text()
        if исходный.count(было) != 1:
            нет_цели.append(f"{файл}: {что} (цель найдена {исходный.count(было)} раз)")
            print(f"НЕТ ЦЕЛИ | {что}")
            continue
        try:
            путь.write_text(исходный.replace(было, стало))
            rc = run()
        finally:
            путь.write_text(исходный)
        print(f"{'покраснел' if rc else 'ПРОМОЛЧАЛ'} | {что}", flush=True)
        if rc == 0:
            промолчали.append(что)
    clean()
    print(f"мутантов {по - с}, промолчали {len(промолчали)}, без цели {len(нет_цели)}")
    if нет_цели:
        print("не смогли: " + "; ".join(нет_цели))
        return 2
    if промолчали:
        print("не годно: " + "; ".join(промолчали))
        return 1
    print("годно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
