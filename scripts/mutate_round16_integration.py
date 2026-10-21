#!/usr/bin/env python3
"""Т1: мутация решений СВЕДЕНИЯ шестнадцатого круга (поля spec × экспертиза) — в обе стороны.

    python scripts/mutate_round16_integration.py          # все мутанты
    python scripts/mutate_round16_integration.py 0 4      # мутанты с 0 по 3

Что мутируется: анонимизация голоса на рисованном дубляже (строки сборки дубляжа и
необязательный липсинк уходят вместе с дубляжем); своя правка видео рядом с заменой лиц
(цель правки — не человек); `voiceover: false` — не озвученная серия; `outputs[].spatial`
в поле черновика и в словах.

Устройство — как у `scripts/mutate_round16_knowledge.py`. ТРИ ИСХОДА (Р1).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_round16_integration",)

X16 = "studio/expert_r16.py"
RA = "studio/recipes/apply.py"
BS = "studio/brief_spec.py"

#: (файл, было, стало, что ломается)
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    (RA, "        acc.assembly[:] = [a for a in acc.assembly if a not in DUB_ONLY_ASSEMBLY]\n", "",
     "строка адаптации под рты остаётся без дубляжа"),
    (RA, "DUB_ONLY_ASSEMBLY: tuple[tuple[str, str], ...] = (ASSEMBLY_DRAWN_ADAPT, ASSEMBLY_DRAWN_DUB)",
     "DUB_ONLY_ASSEMBLY: tuple[tuple[str, str], ...] = (ASSEMBLY_DRAWN_DUB,)", "строка адаптации не считается строкой дубляжа"),
    (RA, "    optional = [s for s in optional if s in steps]\n", "", "необязательный липсинк без липсинка в маршруте"),
    (RA, '    own_edit = ANONYMISE_KEEPS_EDIT if spec.edit_target not in (None, "person") else frozenset()',
     "    own_edit = frozenset()", "своя правка фона уходит вместе с анонимизацией"),
    (RA, '    own_edit = ANONYMISE_KEEPS_EDIT if spec.edit_target not in (None, "person") else frozenset()',
     "    own_edit = ANONYMISE_KEEPS_EDIT", "правка человека остаётся рядом с заменой лица"),
    (RA, '    own_edit = ANONYMISE_KEEPS_EDIT if spec.edit_target not in (None, "person") else frozenset()',
     '    own_edit = ANONYMISE_KEEPS_EDIT if spec.edit_target not in ("person",) else frozenset()',
     "правка без цели остаётся рядом с заменой лица"),
    (X16, '    if getattr(spec, "voiceover", None) is False:\n        return False\n    return bool(W_SERIES', "    return bool(W_SERIES",
     "voiceover: false — всё равно озвученная серия"),
    (X16, '    if getattr(spec, "voiceover", None) is False:\n        return False\n    return bool(W_SERIES',
     '    if getattr(spec, "voiceover", None) is not True:\n        return False\n    return bool(W_SERIES',
     "серия по словам только при названном voiceover"),
    (BS, "DECISION_FIELDS = (*DECISION_FIELDS, *DECISION_FIELDS_R16_OUTPUTS)\n", "", "outputs[].spatial не в черновике"),
    (BS, '    if x16.W_SPATIAL.search(brief):\n        прочитано["outputs[].spatial"] = True\n', "",
     "слова о пространственном звуке не подсказывают поле"),
    (BS, "f\"(known: {', '.join((*OUTPUT_ITEM_FIELDS, *OUTPUT_ITEM_FLAGS_R16))})\"",
     "f\"(known: {', '.join(OUTPUT_ITEM_FIELDS)})\"", "ошибка записи выхода не называет spatial"),
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
