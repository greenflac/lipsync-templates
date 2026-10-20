#!/usr/bin/env python3
"""Т1: мутация констант-решений ПЯТНАДЦАТОГО КРУГА (экспертные знания и цены) — в обе стороны.

    python scripts/mutate_round15_knowledge.py          # все мутанты
    python scripts/mutate_round15_knowledge.py 0 10     # мутанты с 0 по 9 (прогон частями)

Что мутируется: правила чек-листа круга (кавер и права на песню, длинный фон петлёй,
бесшовная текстура, растр печатного скана, интерполяция таймлапса, единый стиль серии,
шортс без речи, вставка товара, анонимизация прохожих) — пороги, поля spec старше слов
и слова-исключения; длинный фон как один отрезок (длины отрезков, поле петли);
пачка липсинка по роликам (шаг, блок секунд, минутный блок в каждом ролике);
расшифровка по всему материалу и разметка говорящих по записи; липсинк рисованного
на модели с записью о рисованных лицах; правка предмета без замены персонажа;
анонимизация заменой лица на синтетическое (вход-картинка из шага плана) или размытием.

Устройство — как у `scripts/mutate_round14_models.py`: файл правится на диске,
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

НАБОРЫ = ("studio.tests.test_round15_knowledge",)

CL = "studio/recipes/checklist.py"
X15 = "studio/expert_r15.py"
RA = "studio/recipes/apply.py"
PN = "studio/planner.py"
PR = "studio/pricing.py"

#: (файл, было, стало, что ломается)
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- пороги чек-листа, в обе стороны
    (CL, "AMBIENT_LOOP_MIN_S = 1800", "AMBIENT_LOOP_MIN_S = 1801", "полчаса фона — не петля"),
    (CL, "AMBIENT_LOOP_MIN_S = 1800", "AMBIENT_LOOP_MIN_S = 1799", "фон короче получаса — петля"),
    (CL, "STYLE_SET_MIN = 3", "STYLE_SET_MIN = 4", "три картинки — не серия стиля"),
    (CL, "STYLE_SET_MIN = 3", "STYLE_SET_MIN = 2", "две картинки — серия стиля"),
    (CL, "NO_SPEECH_SHORT_MAX_S = 180", "NO_SPEECH_SHORT_MAX_S = 179", "трёхминутный ролик без речи — не шортс"),
    (CL, "NO_SPEECH_SHORT_MAX_S = 180", "NO_SPEECH_SHORT_MAX_S = 181", "ролик длиннее трёх минут — шортс"),
    # --- поле spec старше слов
    (CL, "    if петля is False:\n        return None\n    if петля or c.says(W_LOOP)",
     "    if петля or c.says(W_LOOP)", "loop=false не гасит слова о фоне"),
    (CL, "    if тайл is not None:", "    if False:", "tileable поля не читается"),
    (CL, '    if "style" in оси or (not оси and c.says(W_STYLE_SET)):', '    if c.says(W_STYLE_SET):',
     "consistency не старше слов"),
    (CL, "        return all(г is False for г in говорят)", "        return any(г is False for г in говорят)",
     "один молчащий — уже шортс без речи"),
    (CL, '        return цель == "object" and (c.says(W_INSERT) or c.says(W_PRODUCT))',
     '        return цель != "text" and (c.says(W_INSERT) or c.says(W_PRODUCT))', "вставка человека — вставка товара"),
    # --- слова и исключения
    (CL, "covers?\\b(?! (?:image|art|artwork|photo|picture|frame|letter|page|shot|story))", "covers?\\b",
     "обложка песни — кавер"),
    (CL, " and not c.says(W_OWN_SONG)\n", "\n", "своя песня — чужие права"),
    (CL, "    return bool(c.jobs & SCAN_JOBS) and c.says(W_HALFTONE)",
     '    return bool(c.jobs & {"restore"}) and c.says(W_HALFTONE)', "апскейл скана журнала без снятия растра"),
    (CL, '    return "interpolate" in c.jobs and c.says(W_TIMELAPSE)', "    return c.says(W_TIMELAPSE)",
     "таймлапс без интерполяции — оговорка интерполяции"),
    (CL, "    return c.says(W_INSERT) and not c.says(W_NOT_AN_OBJECT)", "    return c.says(W_INSERT)",
     "логотип в ролик — вставка товара"),
    # --- длинный фон одним отрезком
    (X15, "AMBIENT_AUDIO_SEGMENT_S = 180", "AMBIENT_AUDIO_SEGMENT_S = 181", "отрезок звука длиннее трёх минут"),
    (X15, "AMBIENT_AUDIO_SEGMENT_S = 180", "AMBIENT_AUDIO_SEGMENT_S = 179", "отрезок звука короче трёх минут"),
    (X15, "AMBIENT_VIDEO_SEGMENT_S = 10", "AMBIENT_VIDEO_SEGMENT_S = 11", "отрезок видео длиннее прогона"),
    (X15, "AMBIENT_VIDEO_SEGMENT_S = 10", "AMBIENT_VIDEO_SEGMENT_S = 9", "отрезок видео короче"),
    (X15, "    if петля is False:\n        return None\n    слова", "    слова", "loop=false снова петля по словам"),
    (RA, '        if audio_s is not None and acc.prior("ambient_loop", "ambient_segment_loop"):',
     "        if False:", "часы фона снова генерируются целиком"),
    # --- пачка роликов
    (X15, 'BATCH_PRICED_STEPS: frozenset[str] = frozenset({"липсинк"})', "BATCH_PRICED_STEPS: frozenset[str] = frozenset()",
     "пачка липсинка одним прогоном"),
    (PR, "    if (м := _ВВЕРХ_ДО_СЕКУНД.search(текст)) is not None:", "    if False and (м := _ВВЕРХ_ДО_СЕКУНД.search(текст)):",
     "блок 5 секунд не читается"),
    (PR, "        if r.block and need.shots > 1:\n            # Пятнадцатый круг", "        if False:\n            # Пятнадцатый круг",
     "минута не округляется в каждом ролике"),
    # --- расшифровка
    (X15, '            всего += float(з["duration_s"]) * max(1, int(з.get("count") or 1))',
     '            всего += float(з["duration_s"])', "двадцать интервью считаются как одно"),
    (PN, "        if материал_с and исходник_с and материал_с > исходник_с", "        if материал_с and исходник_с and материал_с < исходник_с",
     "весь материал не идёт в цену расшифровки"),
    (X15, 'DIARISES = re.compile(r"diari[sz]|', 'DIARISES = re.compile(r"diarizzz|', "разметка по записи не видна"),
    (X15, "    if any(DIARISATION_ADDON.search(str(f.value)) for f in свои):", "    if False:",
     "платное дополнение разметки не названо"),
    (PN, "and op.name == x15.TRANSCRIBE_STEP and x15.needs_diarisation(понято, текст)",
     "and op.name == x15.TRANSCRIBE_STEP", "метки говорящих у лекции одного"),
    # --- рисованный дубляж
    (RA, '            stylised.append("липсинк")\n', "", "липсинк рисованного без модели для рисованных лиц"),
    (PN, '    r"\\b2D\\b|illustration|', '    r"illustration|', "запись Kling о 2D-лицах не читается"),
    (RA, "            if ANIMAL_CHARACTERS.search(", "            if False and ANIMAL_CHARACTERS.search(",
     "о мордах животных не сказано"),
    # --- правка предмета
    (X15, 'PERSON_TARGETS: frozenset[str] = frozenset({"person"})',
     'PERSON_TARGETS: frozenset[str] = frozenset({"person", "object"})', "предмет — цель-человек"),
    (X15, 'PERSON_TARGETS: frozenset[str] = frozenset({"person"})', "PERSON_TARGETS: frozenset[str] = frozenset()",
     "человек — не цель"),
    (PN, "        if not person_edit and персонажная_замена(что):", "        if False:",
     "вставка товара снова заменой персонажа"),
    # --- анонимизация
    (X15, 'IMAGE_FED_STEPS: frozenset[str] = frozenset({"замена_персонажа"})', "IMAGE_FED_STEPS: frozenset[str] = frozenset()",
     "синтетическое лицо не доходит до замены"),
    (X15, '    return "blur" if BLUR_WORDS.search(слова) else "swap"', '    return "swap"', "размытие не выбирается"),
    (X15, "    if SWAP_WORDS.search(слова):\n        return \"swap\"\n", "", "замена при словах о замене не выбирается"),
    (X15, "    if (цель and цель not in PERSON_TARGETS) or not cl.W_ANONYMISE.search(слова):",
     "    if not cl.W_ANONYMISE.search(слова):", "цель-небо всё равно анонимизация"),
    (RA, '            acc.assembly.append(x15.ASSEMBLY_ANON_BLUR)\n', "", "размытие без строки монтажа"),
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
