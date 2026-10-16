#!/usr/bin/env python3
"""Т1: мутация констант-решений ДЕВЯТОГО КРУГА (знание и выбор модели) — в обе стороны.

    python scripts/mutate_knowledge_r9.py          # все мутанты
    python scripts/mutate_knowledge_r9.py 0 4      # мутанты с 0 по 3 (прогон частями)

Что мутируется: ступени запуска на своём Mac и отсев по единой памяти,
продление как правка (правило имени, вывод из длины, допуск `…/extend`),
порядок «правка старше кадра», инпейнт в замене неба, отвергнутый валидатором
кандидат при названном бюджете.

Устройство — как у `scripts/mutate_selection_r8.py` (Е1): файл правится на
диске, наборы гоняются через `python -B` со снесённым `__pycache__`, файл
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

НАБОРЫ = ("studio.tests.test_knowledge_r9",)

PN = "studio/planner.py"
HN = "studio/hardneed.py"
EP = "studio/endpoints.py"
BS = "studio/brief_spec.py"

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    (HN, "APPLE_ORDER: dict[str, int] = {APPLE_GPU: 0, APPLE_CPU: 1, APPLE_UNKNOWN: 2}",
     "APPLE_ORDER: dict[str, int] = {APPLE_GPU: 0, APPLE_CPU: 2, APPLE_UNKNOWN: 1}",
     "молчание о Mac обгоняет записанный CPU"),
    (HN, '_APPLE_CPU_WORDS = re.compile(r"\\bcpu\\b", re.I)', '_APPLE_CPU_WORDS = re.compile(r"$^", re.I)',
     "CPU-запуск на Mac не узнаётся"),
    (HN, '            r"no mps|без mps|not supported", f.value, re.I\n',
     '            r"$^", f.value, re.I\n', "«no MPS path» читается как MPS"),
    (PN, "            and память > hard.unified_memory_gb\n", "            and False\n",
     "единая память Mac не отсеивает веса больше машины"),
    (EP, '    EDIT_EXTEND: r"extend\\w*|extension",\n', "", "продление не названо эндпоинтом"),
    (PN, "    return ep.EDIT_EXTEND in нужно and ep.EDIT_EXTEND in ep.edit_intents(что)",
     "    return ep.EDIT_EXTEND in ep.edit_intents(что)", "продление годится и на чужую правку"),
    (BS, "EXTEND_RATIO = 1.2", "EXTEND_RATIO = 1.0", "округление длины читается продлением"),
    (PN, "    return (правка, рамка, частота, язык)", "    return ранг", "кадр снова старше названной правки"),
    (EP, '    + r"|inpaint\\w*",\n}', '\n}', "инпейнт не называет замену неба"),
    (PN, "        int(c.refused),\n", "", "отвергнутый валидатором не уступает при бюджете"),
    (PN, '    if "видео" in доступно:\n        доступно.add("аудио")\n', "", "звук принесённого видео недоступен"),
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
