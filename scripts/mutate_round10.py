#!/usr/bin/env python3
"""Т1: мутация констант-решений ДЕСЯТОГО КРУГА — в обе стороны.

    python scripts/mutate_round10.py          # все мутанты
    python scripts/mutate_round10.py 0 6      # мутанты с 0 по 5 (прогон частями)

Что мутируется: печать (DPI, большой формат, родной кадр на молчании), 8K и
экстремальная частота, политика заявлений (окно, ранг решений, слова),
своя машина без GPU (признак и лестница), допуск кадра, порог «самого
дешёвого» вне полосы, замена персонажа целиком и примерка (слова и работы
реестра).

Устройство — как у `scripts/mutate_knowledge_r9.py` (Е1): файл правится на
диске, набор гоняется через `python -B` со снесённым `__pycache__`, файл
ВОЗВРАЩАЕТСЯ как был. Первой строкой — ЗДОРОВЫЙ прогон.

ТРИ ИСХОДА (Р1): годно — здоровый зелёный и покраснели все мутанты; не годно —
здоровый красный или хоть один промолчал; не смогли — цели мутанта нет в файле.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_round10_general",)

DL = "studio/recipes/delivery.py"
CP = "studio/claims_policy.py"
HN = "studio/hardneed.py"
PN = "studio/planner.py"
RA = "studio/recipes/apply.py"
EP = "studio/endpoints.py"

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    (DL, "PRINT_DPI = 300", "PRINT_DPI = 299", "печать ниже 300 DPI"),
    (DL, "PRINT_DPI = 300", "PRINT_DPI = 301", "печать выше 300 DPI"),
    (DL, "LARGE_FORMAT_DPI = 150", "LARGE_FORMAT_DPI = 300", "большой формат печатается как книга"),
    (DL, "LARGE_FORMAT_MIN_MM = 1000", "LARGE_FORMAT_MIN_MM = 3001", "билборд 3 м не большой формат"),
    (DL, "LARGE_FORMAT_MIN_MM = 1000", "LARGE_FORMAT_MIN_MM = 400", "A2 считается большим форматом"),
    (DL, "PRINT_SILENT_NATIVE_MP = 4.2", "PRINT_SILENT_NATIVE_MP = 7.3", "8x10 in без апскейла на молчании"),
    (DL, "PRINT_SILENT_NATIVE_MP = 4.2", "PRINT_SILENT_NATIVE_MP = 3.9", "4 Мп получает лишний апскейл"),
    (DL, "EIGHT_K_HEIGHT = 4320", "EIGHT_K_HEIGHT = 4321", "8K не узнаётся"),
    (DL, "EIGHT_K_HEIGHT = 4320", "EIGHT_K_HEIGHT = 2160", "4K читается как 8K"),
    (DL, "EXTREME_FPS = 120", "EXTREME_FPS = 121", "120 fps без ноты об артефактах"),
    (DL, "EXTREME_FPS = 120", "EXTREME_FPS = 60", "60 fps с нотой об артефактах"),
    (DL, '    r"|печат|постер', '    r"|печатьНЕТ|постерНЕТ', "русская печать не узнаётся"),
    (CP, "CLAIM_WINDOW = 4", "CLAIM_WINDOW = 1", "«cures your chronic insomnia» не ловится"),
    (CP, "CLAIM_WINDOW = 4", "CLAIM_WINDOW = 9", "чужие предложения склеиваются в заявление"),
    (CP, "DECISION_RANK: dict[str, int] = {DECISION_PLAN: 0, DECISION_QUESTION: 1, DECISION_REFUSE: 2}",
     "DECISION_RANK: dict[str, int] = {DECISION_PLAN: 0, DECISION_QUESTION: 2, DECISION_REFUSE: 1}",
     "вопрос старше отказа"),
    (CP, "            if r[\"substantiated\"] is False\n", "            if r[\"substantiated\"] is None\n",
     "неподтверждённое не отказывается"),
    (HN, "CPU_ORDER: dict[str, int] = {CPU_ARM: 0, CPU_YES: 1, CPU_UNKNOWN: 2, CPU_NO: 3}",
     "CPU_ORDER: dict[str, int] = {CPU_ARM: 0, CPU_YES: 1, CPU_UNKNOWN: 3, CPU_NO: 2}",
     "тяжёлая GPU-модель обгоняет молчание на Pi"),
    (HN, '    r"raspberry|', '    r"raspberryНЕТ|', "Raspberry Pi не узнаётся машиной без GPU"),
    (PN, "FRAME_REACH_TOLERANCE = 0.05", "FRAME_REACH_TOLERANCE = 0.0", "1280x704 снова дописывает апскейл"),
    (PN, "CHEAP_OFFER_RATIO = 5.0", "CHEAP_OFFER_RATIO = 50.0", "дешёвый вне полосы не предлагается"),
    (PN, "CHEAP_OFFER_RATIO = 5.0", "CHEAP_OFFER_RATIO = 1.0", "любая разница меняет выбор"),
    (RA, '    r"mascot|costume|', '    r"mascotНЕТ|costumeНЕТ|', "маскот не узнаётся"),
    (RA, "    return any(CHARACTER.search(у) for у in said) and not any(FACE_ONLY.search(у) for у in said)",
     "    return any(CHARACTER.search(у) for у in said)", "«моё лицо на маскоте» уходит в замену фигуры"),
    (RA, '    r"try-?on|virtual fitting|', '    r"tryНЕТ|virtual fitting|', "«try-on» не узнаётся"),
    (RA, "    return any(TRY_ON.search(у) for у in said) and any(GARMENT.search(у) for у in said)",
     "    return any(TRY_ON.search(у) for у in said)", "примерка без вещи"),
    (EP, '    (r"try-?on|tryon|vton?|virtual-fitting", (TRY_ON, IMAGE_EDIT)),\n', "",
     "эндпоинт примерки без своей работы"),
    (EP, '    (r"animate-replace|character-replace|animate-mix", (CHARACTER_REPLACE, V2V_EDIT)),',
     '    (r"animate-replace|character-replace", (CHARACTER_REPLACE, V2V_EDIT)),',
     "Wan Animate mix не меняет персонажа"),
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
