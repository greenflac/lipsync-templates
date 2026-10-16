#!/usr/bin/env python3
"""T1: mutate the decision constants of the round-8 modules that had no mutant.

    python scripts/mutate_round8.py

`check_mutants_cover` counted 13 modules with decision constants and no
mutant after the round-8 merge (ceiling 9). The recipe layer is guarded by
`mutate_recipes.py` and the selection keys by `mutate_selection_r8.py`; both
are now registered tables. This one covers what stayed bare:

* `studio/draft_lexicon.py` — the any-script draft parser (windows, own-media
  and make words, aspect words), guarded by `studio.tests.test_draft_r8`;
* `scripts/eval_plans.py` — the expert-evaluation scorer (prose vs echo and
  evidence keys, the outcome and job vocabularies), guarded by
  `studio.tests.test_eval_plans`;
* `studio/endpoints.py` — the integration's output-kind cut
  (`OUTPUT_MEDIA`), guarded by `studio.tests.test_integration_r4`;
* `lipsync/fork_batch.py` — the batch modes, guarded by
  `lipsync.tests.test_fork_batch`.

The script edits a file on disk, runs `НАБОРЫ` through `python -B` with the
`__pycache__` directories removed, and RESTORES the file. The first line is
the HEALTHY run: a table over a red tree means nothing.

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

НАБОРЫ = (
    "studio.tests.test_draft_r8",
    "studio.tests.test_eval_plans",
    "studio.tests.test_integration_r4",
    "lipsync.tests.test_fork_batch",
)

DL = "studio/draft_lexicon.py"
EV = "scripts/eval_plans.py"
EP = "studio/endpoints.py"
FB = "lipsync/fork_batch.py"

#: (file, was, becomes, what breaks).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    (DL, "CJK_WINDOW = 10", "CJK_WINDOW = 0", "own-media mark before a CJK noun not seen"),
    (DL, "PURPOSE_WINDOW = 8", "PURPOSE_WINDOW = 0", "'video for' read as an ordered video"),
    (DL, '    "生成", "制作",', '    "制作",', "a Chinese 'generate' order not read as generate"),
    (DL, 'VERTICAL = ("竖屏", ', "VERTICAL = (", "a Chinese vertical aspect not read"),
    (DL, '"我们的", "我的", ', "", "Chinese 'our' no longer makes media own"),
    (EV, '{"brief", "understood_as", "full", "omitted", "stated_conditions"}',
     '{"understood_as", "full", "omitted", "stated_conditions"}',
     "the brief's own words satisfy its notes"),
    (EV, '        "evidence",\n        "failures_outside_brief",', '        "failures_outside_brief",',
     "quoted evidence satisfies a note"),
    (EV, '{"plan", "question", "refuse", "gap", "assembly_only", "over_budget", "plan_failed"}',
     '{"plan", "question", "refuse", "assembly_only", "over_budget", "plan_failed"}',
     "a reference outcome 'gap' declared malformed"),
    (EP, "OUTPUT_MEDIA: frozenset[str] = frozenset({_ВИДЕО, _КАРТИНКА})",
     "OUTPUT_MEDIA: frozenset[str] = frozenset({_ВИДЕО})",
     "an image face-swap stays a candidate on a video step"),
    (FB, 'MODES = ("full", "cover")', 'MODES = ("full",)', "cover mode refused"),
    (FB, 'MODES = ("full", "cover")', 'MODES = ("full", "cover", "almost_full")', "an unknown mode accepted"),
)


def clean() -> None:
    for p in ROOT.rglob("__pycache__"):
        # Относительно корня: рабочая копия сама может лежать под `.claude/`.
        части = p.relative_to(ROOT).parts
        if ".claude" not in части:
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
        исходный = путь.read_text(encoding="utf-8")
        if исходный.count(было) != 1:
            нет_цели.append(f"{файл}: {что} (цель найдена {исходный.count(было)} раз)")
            print(f"НЕТ ЦЕЛИ | {что}")
            continue
        try:
            путь.write_text(исходный.replace(было, стало), encoding="utf-8")
            rc = run()
        finally:
            путь.write_text(исходный, encoding="utf-8")
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
