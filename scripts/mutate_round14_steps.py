#!/usr/bin/env python3
"""Т1: мутация констант-решений ЧЕТЫРНАДЦАТОГО КРУГА (шаги и экономия) — в обе стороны.

    python scripts/mutate_round14_steps.py          # все мутанты
    python scripts/mutate_round14_steps.py 0 20     # мутанты с 0 по 19 (прогон частями)

Что мутируется: реальное время только при живой системе (слово живой системы; слово
скорости — при собеседнике и лице), референсы на персонажа (r2v и шоты из
длительности), ключевой кадр шота — только когда персонажи делят кадр, губы в
кат-сцене после видео, визуализатор без исполнителя в кадре, кадр выдачи правки
(апскейл по нему), дешёвый тариф линейки клона.

Устройство — как у `scripts/mutate_round13_steps.py`: файл правится на диске, набор
гоняется через `python -B` со снесённым `__pycache__`, файл ВОЗВРАЩАЕТСЯ как был.
Первой строкой — ЗДОРОВЫЙ прогон.

ТРИ ИСХОДА (Р1): годно — здоровый зелёный и покраснели все мутанты; не годно —
здоровый красный или хоть один промолчал; не смогли — цели мутанта нет в файле.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_round14_steps",)

BS = "studio/brief_spec.py"
PN = "studio/planner.py"
AP = "studio/recipes/apply.py"
RT = "studio/realtime.py"

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- реальное время только при живой системе ----------------------------------------
    (RT, "    if _said(LIVE, clean):\n        return True\n", "", "видеозвонок-аватар без слова скорости — план"),
    (RT, "    return face and _said(SPEED, clean) and bool(INTERACTIVE.search(clean))", "    return _said(SPEED, clean)",
     "быстрый синтез речи — пробел"),
    (RT, "    return face and _said(SPEED, clean) and bool(INTERACTIVE.search(clean))", "    return False",
     "аватар отвечает посетителям с низкой задержкой — план"),
    (RT, "    return face and _said(SPEED, clean) and bool(INTERACTIVE.search(clean))",
     "    return face and _said(SPEED, clean)", "быстрый рендер аватара без собеседника — пробел"),
    (RT, '    if not asked(said, face=bool(tasks & FACE_TASKS) or "video" in outputs):', "    if not asked(said):",
     "голосовой бот с низкой задержкой — пробел"),
    (RT, 'FACE_TASKS: frozenset[str | None] = frozenset({"avatar", "lipsync", "dub-translate"})',
     'FACE_TASKS: frozenset[str | None] = frozenset({"lipsync", "dub-translate"})', "аватар без видео в выходах — план"),
    (RT, 'FACE_TASKS: frozenset[str | None] = frozenset({"avatar", "lipsync", "dub-translate"})',
     'FACE_TASKS: frozenset[str | None] = frozenset({"avatar", "lipsync", "dub-translate", "generate"})',
     "голосовой бот (generate) с собеседником — пробел"),
    # --- референсы на персонажа -----------------------------------------------------------
    (BS, '{"генерация_изображения": max(1, int(spec.characters or 1))}', '{"генерация_изображения": int(spec.shots or 1)}',
     "r2v: картинка на каждый шот"),
    (BS, '{"генерация_изображения": max(1, int(spec.characters or 1))}', '{"генерация_изображения": 1}',
     "r2v: один референс на двух персонажей"),
    (BS, "SINGLE_REFERENCE = 1", "SINGLE_REFERENCE = 2", "один персонаж — два референса"),
    (BS, "SINGLE_REFERENCE = 1", "SINGLE_REFERENCE = 3", "один персонаж — три референса"),
    # --- ключевой кадр только когда вместе --------------------------------------------------
    (BS, "            if spec.cast_together:", "            if True:", "персонажи порознь — правка на каждый шот"),
    (BS, "            if spec.cast_together:", "            if False:", "диалог без ключевых кадров"),
    (BS, '    if персонажи_в_одном_кадре(replace(spec, characters=поля["characters"]), текст):', "    if False:",
     "«вместе» не читается"),
    (BS, "    if (spec.characters or 0) < MULTI_CHARACTER_MIN:\n        return False\n    сказано = NO_DIALOGUE", "    сказано = NO_DIALOGUE",
     "один персонаж «вместе»"),
    (BS, '    сказано = NO_DIALOGUE.sub(" ", " ".join(str(у) for у in (*spec.conditions, текст) if у))',
     '    сказано = " ".join(str(у) for у in (*spec.conditions, текст) if у)', "«без диалогов» читается диалогом"),
    (BS, '    r"|\\band (?:the |a |an |his |her |their |our |its )?[\\w-]+ (?:talk|chat|speak|argue|bicker|negotiate|discuss|sing)\\b"\n',
     "", "«герой и злодей говорят» — порознь"),
    # --- губы в кат-сцене ---------------------------------------------------------------------
    (BS, "    if персонаж and (голоса_персонажей or CUTSCENE.search(сказано)):\n        return True\n", "",
     "реплики персонажа кат-сцены без губ"),
    (BS, "    if VOICE_OFF_FRAME.search(сказано) and not голоса_персонажей:", "    if VOICE_OFF_FRAME.search(сказано):",
     "«озвучка персонажей» читается закадром"),
    (BS, "    if VOICE_OFF_FRAME.search(сказано) and not голоса_персонажей:", "    if False:",
     "рассказчик кат-сцены получает губы"),
    # --- визуализатор без исполнителя ----------------------------------------------------------
    (BS, '    return PERFORMER_NOT_ON_SCREEN.sub(" ", NO_PERFORMER.sub(" ", str(текст or "")))', '    return str(текст or "")',
     "«no performer on screen» — исполнитель"),
    (BS, '    return PERFORMER_NOT_ON_SCREEN.sub(" ", NO_PERFORMER.sub(" ", str(текст or "")))',
     '    return NO_PERFORMER.sub(" ", str(текст or ""))', "«логотип артиста» — исполнитель"),
    (BS, '    return PERFORMER_NOT_ON_SCREEN.sub(" ", NO_PERFORMER.sub(" ", str(текст or "")))',
     '    return PERFORMER_NOT_ON_SCREEN.sub(" ", str(текст or ""))', "«исполнителей в кадре нет» — исполнитель"),
    (BS, "    if визуализатор(spec, текст):\n        # ЧЕТЫРНАДЦАТЫЙ", "    if False:\n        # ЧЕТЫРНАДЦАТЫЙ",
     "визуализатор, названный generate, — сцены по кадрам"),
    (BS, "    return bool(VISUALISER_WORDS.search(сказано)) and not клип_с_исполнителем(spec, текст)",
     "    return bool(VISUALISER_WORDS.search(сказано))", "певица в клипе со словами визуализатора — визуализатор"),
    (AP, '    visualiser = spec.task == "music-visualiser" or bs.визуализатор(spec, text)',
     '    visualiser = spec.task == "music-visualiser"', "визуализатор generate — весь трек генерацией"),
    # --- кадр выдачи правки ------------------------------------------------------------------------
    (PN, 'SOURCE_FRAME_TASKS = SOURCE_FRAME_TASKS | {"remove-background", "interpolate"}',
     'SOURCE_FRAME_TASKS = SOURCE_FRAME_TASKS | {"interpolate"}', "вырезка фона не в кадре исходника"),
    (PN, 'SOURCE_FRAME_TASKS = SOURCE_FRAME_TASKS | {"remove-background", "interpolate"}',
     'SOURCE_FRAME_TASKS = SOURCE_FRAME_TASKS | {"remove-background", "interpolate", "lipsync"}',
     "липсинк-проход судится кадром исходника"),
    (PN, "        if op.name in ur.UPSCALE_OPS and (выдача := кадр_выдачи()) is not None:\n            return выдача\n", "",
     "апскейл к 4K исходника считается по 1080p"),
    # --- дешёвый тариф линейки клона ------------------------------------------------------------------
    (PN, "                дешевле_в_линейке(найдено_на_шаг[op.name], линейка_клона[0], op)\n", "",
     "голос клона читает премиальный тариф"),
    (PN, 'PREMIUM_TIER = re.compile(r"-(?:hd|pro|max|ultra|premium)(?:-|$)", re.I)', 'PREMIUM_TIER = re.compile(r"(?!)")',
     "премиальный тариф не узнаётся"),
    (PN, 'PREMIUM_TIER = re.compile(r"-(?:hd|pro|max|ultra|premium)(?:-|$)", re.I)', 'PREMIUM_TIER = re.compile(r"")',
     "любой тариф линейки читается премиальным"),
    (PN, "    свои.sort(key=ключ)\n    for i, c in zip(места, свои):", "    for i, c in zip(места, свои):",
     "места линейки не пересортированы"),
    (PN, "    места = [i for i, c in enumerate(найдены) if c.model.startswith(линейка + \"-\")]",
     "    места = list(range(len(найдены)))", "чужая линейка встаёт вперёд"),
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
