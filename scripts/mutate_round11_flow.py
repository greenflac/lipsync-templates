#!/usr/bin/env python3
"""Т1: мутация констант-решений ОДИННАДЦАТОГО КРУГА — в обе стороны.

    python scripts/mutate_round11_flow.py          # все мутанты
    python scripts/mutate_round11_flow.py 0 6      # мутанты с 0 по 5 (прогон частями)

Что мутируется: слова текста, которые решает заполненная `spec.people`
(`studio/mcp/spec_screen.py`: дети-зрители, согласие на образ, знаменитость,
реальный ребёнок по имени), озвучка сценария без длины, реставрация и замена
лица на снимке, перенос движения (и его правило только по собственному имени
узла), повторяющийся персонаж без `characters`, нативный звук короткого
говорящего клипа против закадровой озвучки, образец голоса в заказе речи.

Устройство — как у `scripts/mutate_round10.py` (Е1): файл правится на диске,
набор гоняется через `python -B` со снесённым `__pycache__`, файл ВОЗВРАЩАЕТСЯ
как был. Первой строкой — ЗДОРОВЫЙ прогон.

ТРИ ИСХОДА (Р1): годно — здоровый зелёный и покраснели все мутанты; не годно —
здоровый красный или хоть один промолчал; не смогли — цели мутанта нет в файле.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_round11_flow",)

BS = "studio/brief_spec.py"
EP = "studio/endpoints.py"
SS = "studio/mcp/spec_screen.py"

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- слово решает spec ------------------------------------------------------------
    (SS, "    if GROUP_MINORS in groups and not minors:", "    if False:", "дети-зрители снова отказ"),
    (SS, "    if GROUP_MINORS in groups and not minors:", "    if GROUP_MINORS in groups:", "реальный ребёнок без отказа"),
    (SS, "    if GROUP_LIKENESS in groups and consented and not celebrities and not minors:", "    if False:",
     "актёр с согласием снова отказ"),
    (SS, "    if GROUP_LIKENESS in groups and consented and not celebrities and not minors:",
     "    if GROUP_LIKENESS in groups and not celebrities and not minors:", "образ без согласия без отказа"),
    (SS, "    if GROUP_LIKENESS in groups and consented and not celebrities and not minors:",
     "    if GROUP_LIKENESS in groups and consented and not minors:", "знаменитость при слове подмены без отказа"),
    (SS, '    return any(group_of(м) == GROUP_MINORS for м in screen.просеять(name)["banned"])', "    return False",
     "детское имя в people не считается ребёнком"),
    (SS, "    people = _people(spec)", "    people = _people(spec) or []", "без spec.people слово решается как с ней"),
    (SS, '    if isinstance(person.get("minor"), bool):\n        return bool(person["minor"])',
     '    if isinstance(person.get("minor"), bool):\n        return False', "minor: true не держит отказ"),
    # --- озвучка сценария -------------------------------------------------------------
    (BS, "SCRIPT_SPEECH_DEFAULT_S = 60.0", "SCRIPT_SPEECH_DEFAULT_S = 30.0", "сценарий оценён на полминуты"),
    (BS, "SCRIPT_SPEECH_DEFAULT_S = 60.0", "SCRIPT_SPEECH_DEFAULT_S = 120.0", "сценарий оценён на две минуты"),
    (BS, 'SCRIPT_TIMED_OUTPUTS: frozenset[str] = frozenset({"speech", "text"})',
     'SCRIPT_TIMED_OUTPUTS: frozenset[str] = frozenset({"text"})', "озвучка сценария снова спрашивает длину"),
    (BS, 'SCRIPT_TIMED_OUTPUTS: frozenset[str] = frozenset({"speech", "text"})',
     'SCRIPT_TIMED_OUTPUTS: frozenset[str] = frozenset({"speech", "text", "video"})', "видео по сценарию без длины"),
    # --- снимки: реставрация, замена лица ----------------------------------------------
    (BS, '    над_снимком = "video" not in spec.outputs and "photo" in spec.inputs and "video" not in spec.inputs',
     "    над_снимком = False", "раскраска фото после реставрации уходит в видео"),
    (BS, '        над_своими = bool(set(работы) & (MATERIAL_TASKS | {"colorize"})) and "photo" in spec.inputs',
     "        над_своими = False", "одно фото без count снова спрашивает число"),
    (BS, '        if "video" not in входы and "photo" in входы and "video" not in выходы:',
     '        if "video" not in входы and "audio" in входы and "video" not in выходы:', "замена лица на снимке спрашивает видео"),
    (BS, '        if "video" not in входы and "photo" in входы and "video" not in выходы:',
     '        if "photo" in входы:', "видео-замена лица уходит в картиночную"),
    # --- перенос движения -------------------------------------------------------------
    (BS, '        if "video" in входы and "photo" in входы:\n            # ПЕРЕНОС',
     '        if False:\n            # ПЕРЕНОС', "ведущее видео снова в простой i2v"),
    (BS, '        if "video" in входы and "photo" in входы:\n            # ПЕРЕНОС',
     '        if "photo" in входы:\n            # ПЕРЕНОС', "любое оживление — перенос движения"),
    (EP, '    (r"motion-control|motion-transfer|animate-move|act-two", (MOTION_TRANSFER, V2V_EDIT)),',
     '    (r"motion-controlНЕТ|motion-transferНЕТ", (MOTION_TRANSFER, V2V_EDIT)),', "motion control не своя работа"),
    (EP, "        if _звено(образец, _звенья(model)):\n            работы |= set(что)",
     "        if any(_звено(образец, _звенья(и)) for и in (model, *ids)):\n            работы |= set(что)",
     "схема соседа делает семью переносом движения"),
    # --- повторяющийся персонаж ---------------------------------------------------------
    (BS, "SERIES_DURATION_MIN_S = 15.0", "SERIES_DURATION_MIN_S = 45.0", "40 с с персонажем без референса"),
    (BS, "SERIES_DURATION_MIN_S = 15.0", "SERIES_DURATION_MIN_S = 5.0", "один прогон с персонажем от референса"),
    (BS, 'SERIES_HERO = re.compile(r"\\babout (?:a|an|the|our|two|three) |character|\\bhero|\\bпро |персонаж|геро", re.I)',
     'SERIES_HERO = re.compile(r"НЕТ_ГЕРОЯ", re.I)', "сериал про робота без референса"),
    (BS, 'SERIES_HERO = re.compile(r"\\babout (?:a|an|the|our|two|three) |character|\\bhero|\\bпро |персонаж|геро", re.I)',
     'SERIES_HERO = re.compile(r"", re.I)', "заставка сериала получает референс героя"),
    # --- нативный звук ----------------------------------------------------------------
    (BS, "NATIVE_SPEECH_MAX_S = 15.0", "NATIVE_SPEECH_MAX_S = 7.0", "8 с говорящего повара без нативного звука"),
    (BS, "NATIVE_SPEECH_MAX_S = 15.0", "NATIVE_SPEECH_MAX_S = 90.0", "минута экскурсии одним нативным дублем"),
    (BS, '    if not SPEAKING_IN_FRAME.search(текст or "") or VOICE_OFF_FRAME.search(текст or ""):',
     '    if not SPEAKING_IN_FRAME.search(текст or ""):', "реклама с озвучкой уходит в нативный звук"),
    (BS, '    if not SPEAKING_IN_FRAME.search(текст or "") or VOICE_OFF_FRAME.search(текст or ""):',
     "    if True:", "говорящий повар без нативного звука"),
    # --- образец голоса -----------------------------------------------------------------
    (BS, '    образец = "audio" in spec.inputs and "script" in spec.inputs', "    образец = False",
     "образец голоса и текст снова без шага"),
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
