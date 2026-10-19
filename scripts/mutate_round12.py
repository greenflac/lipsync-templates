#!/usr/bin/env python3
"""Т1: мутация констант-решений ДВЕНАДЦАТОГО КРУГА — в обе стороны.

    python scripts/mutate_round12.py          # все мутанты
    python scripts/mutate_round12.py 0 10     # мутанты с 0 по 9 (прогон частями)

Что мутируется: состав выходов маршрута (диктор поверх своего видео, губы
говорящего в кадре, вопрос о выходе без шага, своя речь у нарезки), нижняя
граница цены (оценка секунды вычисления, ставка за меньшую частоту, цена ролика
у своего видео), проход по снимкам, дубляж рисованного, локальная цепочка
дубляжа, знаки настоящего канала на выдуманных новостях, визуализатор без трека
и липсинк без материала.

Устройство — как у `scripts/mutate_round11_flow.py` (Е1): файл правится на
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

НАБОРЫ = ("studio.tests.test_round12",)

BS = "studio/brief_spec.py"
PR = "studio/pricing.py"
PN = "studio/planner.py"
AP = "studio/recipes/apply.py"
BM = "studio/broadcast_marks.py"

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- состав выходов ---------------------------------------------------------------
    (BS, "    return _все_выходы(spec, _цепочка(spec, сборочные))", "    return _цепочка(spec, сборочные)",
     "диктор к реставрации снова теряется"),
    (BS, '        шаги.append("озвучка")\n        пометки.setdefault("озвучка", NOTE_NARRATION)',
     '        пометки.setdefault("озвучка", NOTE_NARRATION)', "речь в выходе без шага озвучки"),
    (BS, "        if видео:\n            сборка.append(NOTE_NARRATION_MIX)", "        if False:\n            сборка.append(NOTE_NARRATION_MIX)",
     "голос без сведения при сборке"),
    (BS, '    if "music" in выходы and "музыка" not in шаги and "audio" not in входы:',
     "    if False:", "музыка к апскейлу теряется"),
    (BS, '    if "music" in выходы and "музыка" not in шаги and "audio" not in входы:',
     '    if "music" in выходы and "музыка" not in шаги:', "своя дорожка снова генерируется"),
    (BS, '    if "video" in входы and spec.task in SOURCE_SOUND_TASKS and spec.audio != "voiceover":',
     "    if False:", "нарезка подкладывает синтез поверх своей речи"),
    (BS, '    {"cut-to-shorts", "captions", "transcribe", "video-edit", "edit", "face-replace", "lipsync", "dub-translate"}',
     '    {"captions", "transcribe", "video-edit", "edit", "face-replace", "lipsync", "dub-translate", "restore", "colorize", "upscale"}',
     "реставрация теряет диктора, нарезка получает"),
    (BS, "    if не_сделано:\n        return Маршрут(нехватка=_выход_без_шага(не_сделано))",
     "    if False:\n        return Маршрут(нехватка=_выход_без_шага(не_сделано))", "выход без шага молча пропадает"),
    (BS, '        if "photo" in входы and set(шаги) & IMAGE_MAKERS:\n            шаги.append("оживление")',
     '        if False:\n            шаги.append("оживление")', "заказанное видео из снимка не делается"),
    # --- говорящий в кадре ------------------------------------------------------------
    (BS, "        spec.speaker_on_screen\n        and {", "        False\n        and {", "ведущий в кадре без губ"),
    (BS, "    if ON_SCREEN_SPEAKER.search(сказано):\n        return True", "    if False:\n        return True",
     "ведущий словами не виден"),
    (BS, "    return персонаж and bool(SPEAKING_IN_FRAME.search(сказано)) and not VOICE_OFF_FRAME.search(сказано)",
     "    return bool(SPEAKING_IN_FRAME.search(сказано))", "глагол без персонажа двигает губы"),
    (BS, "    return персонаж and bool(SPEAKING_IN_FRAME.search(сказано)) and not VOICE_OFF_FRAME.search(сказано)",
     "    return False", "говорящий персонаж без губ"),
    # --- нижняя граница цены ------------------------------------------------------------
    (PR, "COMPUTE_RATIO_ESTIMATE = 1.0", "COMPUTE_RATIO_ESTIMATE = 0.5", "оценка вычисления вдвое ниже"),
    (PR, "COMPUTE_RATIO_ESTIMATE = 1.0", "COMPUTE_RATIO_ESTIMATE = 2.0", "оценка вычисления вдвое выше"),
    (PR, "        if отношение is None:\n            отношение, основание = COMPUTE_RATIO_ESTIMATE, LOWER_BOUND_COMPUTE",
     "        if отношение is None:\n            return None", "секунда вычисления снова без цены"),
    (PR, "        if отношение is None:\n            отношение, основание = COMPUTE_RATIO_ESTIMATE, LOWER_BOUND_COMPUTE",
     "        if отношение is None:\n            отношение, основание = COMPUTE_RATIO_ESTIMATE, \"\"",
     "оценка читается ценой, а не границей"),
    (PR, "    if not по_тарифу:\n        # ДВЕНАДЦАТЫЙ", "    if False:\n        # ДВЕНАДЦАТЫЙ", "120 fps снова без цены"),
    (PR, "            деньги = (деньги[0], деньги[1], деньги[2] or LOWER_BOUND_FPS)",
     "            деньги = (деньги[0], деньги[1], деньги[2])", "меньшая частота читается ценой"),
    (PN, '        and not (spec_only and "video" in понято.inputs),', "        and True,",
     "дубляж своего видео снова без цены ролика"),
    # --- проход по снимкам ------------------------------------------------------------
    (AP, "SPLAT_PHOTOS_MIN = 20", "SPLAT_PHOTOS_MIN = 10", "12 снимков уже облёт по splat"),
    (AP, "SPLAT_PHOTOS_MIN = 20", "SPLAT_PHOTOS_MIN = 40", "25 снимков без облёта"),
    (AP, '            for old in ("перенос_движения", "генерация_видео"):',
     '            for old in ("генерация_видео",):', "тур по снимкам остаётся переносом движения"),
    (AP, '    if any(п.get("real") for п in spec.people):\n        return False\n    return any(WALKTHROUGH.search',
     '    if any(п.get("real") for п in spec.people):\n        return False\n    return True or any(WALKTHROUGH.search',
     "любые снимки с видео — тур"),
    (AP, "            avoid[\"оживление\"] = MOTION_CONTROL_MODELS\n", "", "motion control не отодвинут в туре"),
    # --- дубляж рисованного -------------------------------------------------------------
    (AP, '    if spec.task == "dub-translate" and "липсинк" in steps and drawn(spec, text):',
     "    if False:", "аниме снова с фотореалистичным липсинком"),
    (AP, '    if spec.task == "dub-translate" and "липсинк" in steps and drawn(spec, text):',
     '    if spec.task == "dub-translate" and "липсинк" in steps:', "снятое интервью теряет губы"),
    # --- локальный дубляж ---------------------------------------------------------------
    (AP, '    if spec.task == "dub-translate" and "дубляж" in steps and local_only(spec, text):',
     "    if False:", "локальный дубляж снова пустой шаг"),
    (AP, '    if spec.task == "dub-translate" and "дубляж" in steps and local_only(spec, text):',
     '    if spec.task == "dub-translate" and "дубляж" in steps:', "облачный дубляж разбит цепочкой"),
    (AP, '            avoid["клонирование_голоса"] = NO_CLONE_MODELS\n', "", "TTS без клона выбирается клоном"),
    (AP, '    first = [n for n in FIRST_STEPS if n in names and "расшифровка" not in names]',
     "    first = [n for n in FIRST_STEPS if n in names]", "клон раньше расшифровки"),
    (PN, "        if понято.then_tasks or понято.task in ORDERED_ROUTES or рецепт.local_only:",
     "        if понято.then_tasks or понято.task in ORDERED_ROUTES:", "цепочка в порядке OPERATIONS"),
    # --- знаки канала ---------------------------------------------------------------------
    (BM, "NEGATION_WINDOW = 4", "NEGATION_WINDOW = 2", "«nothing like Fox News branding» — отказ"),
    (BM, "NEGATION_WINDOW = 4", "NEGATION_WINDOW = 9", "далёкое «no» снимает отказ"),
    (BM, "    if m and FAKE.search(text) and _marks_asked(text):", "    if m and _marks_asked(text):",
     "стиль канала без выдумки — отказ"),
    (BM, "    if m and FAKE.search(text) and _marks_asked(text):", "    if False:", "пародия с логотипом не отказ"),
    (BM, "        if not (_flag(c.get(\"fabricated\")) or _flag(c.get(\"parody\"))):\n            continue",
     "        if True:\n            continue", "spec.claims канала не решают"),
    # --- без лишнего вопроса ------------------------------------------------------------
    (BS, '        if "audio" not in входы:\n            # ДВЕНАДЦАТЫЙ КРУГ: визуализатор',
     '        if False:\n            # ДВЕНАДЦАТЫЙ КРУГ: визуализатор', "визуализатор без трека — другой маршрут"),
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
