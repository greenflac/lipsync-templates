#!/usr/bin/env python3
"""T1: mutate the decision constants of the recipe layer (`studio/recipes`) and
the planner lines that consume it — each one both ways.

    python scripts/mutate_recipes.py

The script edits a file on disk, runs `НАБОРЫ` through `python -B` with the
`__pycache__` directories removed (a mutant must not be read back from a
compiled copy), and RESTORES the file. The first line is the HEALTHY run: a
table over a red tree means nothing. A mutant after which everything stays
green is a constant nobody guards; the outcome is then "не годно".

Three outcomes (P1): годно — healthy green and every mutant red; не годно —
healthy red or a mutant stayed silent; не смогли — a mutant's target is not in
the file (the mutant is stale and checks nothing).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_recipes_r8",)

RT = "studio/recipes/table.py"
RA = "studio/recipes/apply.py"
PN = "studio/planner.py"

#: (file, was, becomes, what breaks). Each constant — stricter and looser.
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    (RT, "T2I_NATIVE_MAX_MP = 16.8", "T2I_NATIVE_MAX_MP = 40.0", "8K still counted as native"),
    (RT, "T2I_NATIVE_MAX_MP = 16.8", "T2I_NATIVE_MAX_MP = 8.0", "4K still gets an upscale"),
    (RT, "T2V_NATIVE_MAX_MP = 8.3", "T2V_NATIVE_MAX_MP = 40.0", "8K video counted as native"),
    (RT, "T2V_NATIVE_MAX_MP = 8.3", "T2V_NATIVE_MAX_MP = 2.0", "4K video gets an upscale"),
    (RT, "T2V_NATIVE_FPS_MAX = 30", "T2V_NATIVE_FPS_MAX = 60", "60 fps counted as native"),
    (RT, "T2V_NATIVE_FPS_MAX = 30", "T2V_NATIVE_FPS_MAX = 24", "30 fps gets an interpolation"),
    (RT, "VISUALISER_LOOP_CLIPS = 4", "VISUALISER_LOOP_CLIPS = 3", "fewer loop clips"),
    (RT, "VISUALISER_LOOP_CLIPS = 4", "VISUALISER_LOOP_CLIPS = 5", "more loop clips"),
    (RT, "VISUALISER_LOOP_CLIP_S = 8", "VISUALISER_LOOP_CLIP_S = 6", "shorter loop clips"),
    (RT, "VISUALISER_LOOP_CLIP_S = 8", "VISUALISER_LOOP_CLIP_S = 10", "longer loop clips"),
    (RT, "SINGLE_HOST_REFERENCES = 1", "SINGLE_HOST_REFERENCES = 2", "two references for one host"),
    (RT, "SINGLE_HOST_REFERENCES = 1", "SINGLE_HOST_REFERENCES = 5", "a reference per short again"),
    (RA, '    "раскраска": 2,\n    "апскейл": 3,', '    "раскраска": 3,\n    "апскейл": 2,', "upscale before colourise"),
    (RA, '    "реставрация": 1,\n', '    "реставрация": 5,\n', "restore after upscale"),
    (RA, 'FIRST_STEPS: tuple[str, ...] = ("клонирование_голоса",)', "FIRST_STEPS: tuple[str, ...] = ()", "clone not first"),
    (RA, 'DEBLUR_MODELS = r"deblur|sharpen"', 'DEBLUR_MODELS = r"sharpen"', "deblur allowed on film damage"),
    (RA, 'DEBLUR_MODELS = r"deblur|sharpen"', 'DEBLUR_MODELS = r"deblur|denoise"', "denoise ranked last too"),
    (RA, 'BLUR = re.compile(r"blur|', 'BLUR = re.compile(r"blurx|', "named blur no longer allows deblur"),
    (RA, 'LOGO = re.compile(r"\\blogo|', 'LOGO = re.compile(r"\\blogox|', "logo condition not read"),
    (RA, "        and (spec.shots or 0) >= 2\n", "        and (spec.shots or 0) >= 1\n", "one short counted as a series"),
    (RA, "        and (spec.shots or 0) >= 2\n", "        and (spec.shots or 0) >= 6\n", "five shorts not a series"),
    (RA, "        if len(set(steps) & set(CHAIN_RANK)) >= 2:", "        if len(set(steps) & set(CHAIN_RANK)) >= 1:", "order prior stated for one step"),
    (RA, "        if len(set(steps) & set(CHAIN_RANK)) >= 2:", "        if len(set(steps) & set(CHAIN_RANK)) >= 4:", "order prior not stated for three"),
    (RA, '    return (spec.priors or {}).get(prior_id, True) is not False', "    return True", "spec cannot switch a prior off"),
    (RA, '        and "script" in inputs\n', "", "a recording without text cloned"),
    (
        PN,
        '    {"правка_видео", "реставрация", "раскраска", "удаление_фона_видео", "интерполяция_кадров"}',
        '    {"правка_видео", "реставрация", "удаление_фона_видео", "интерполяция_кадров"}',
        "colourise priced at the ordered frame",
    ),
    (
        PN,
        "        if допущение is not None and (почему := допущение(op.name)):\n            return почему, False, \"\"",
        "        if False:\n            return \"\", False, \"\"",
        "silent frame read as neutral again",
    ),
    (
        PN,
        "    if генератор is not None and допущение is not None and (почему := допущение(генератор.name)):",
        "    if False:",
        "silent frame rate read as neutral again",
    ),
)


def clean() -> None:
    for p in ROOT.rglob("__pycache__"):
        if ".claude" not in p.relative_to(ROOT).parts:
            shutil.rmtree(p, ignore_errors=True)


def run() -> int:
    clean()
    return subprocess.run(
        [sys.executable, "-B", "-m", "unittest", *НАБОРЫ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).returncode


def main() -> int:
    здоровый = run()
    print(f"ЗДОРОВЫЙ | тесты rc={здоровый}")
    if здоровый != 0:
        print("не годно: здоровое дерево красное — таблица мутаций ничего не значит")
        return 1
    промолчали: list[str] = []
    нет_цели: list[str] = []
    for файл, было, стало, что in MUTANTS:
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
        print(f"{'покраснел' if rc else 'ПРОМОЛЧАЛ'} | {что}")
        if rc == 0:
            промолчали.append(что)
    clean()
    print(f"мутантов {len(MUTANTS)}, промолчали {len(промолчали)}, без цели {len(нет_цели)}")
    if нет_цели:
        print("не смогли: " + "; ".join(нет_цели))
        return 2
    if промолчали:
        print("не годно: " + "; ".join(промолчали))
        return 1
    print("годно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
