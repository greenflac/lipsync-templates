#!/usr/bin/env python3
"""Т1: мутация констант-решений ТРИНАДЦАТОГО КРУГА (шаги и объём работы) — в обе стороны.

    python scripts/mutate_round13_steps.py          # все мутанты
    python scripts/mutate_round13_steps.py 0 20     # мутанты с 0 по 19 (прогон частями)

Что мутируется: общие активы (референсы персонажей один раз, одна петля на все
версии, клон голоса), начитка голосом клона, кадр исходника у правки своего
материала, липсинк в каждом говорящем шоте и под вокал исполнителя, монтажные
правки без шагов и без вопроса, рефрейм кадрированием, работа в реальном
времени как пробел, звук по картинке своего видео.

Устройство — как у `scripts/mutate_round12.py`: файл правится на диске, набор
гоняется через `python -B` со снесённым `__pycache__`, файл ВОЗВРАЩАЕТСЯ как
был. Первой строкой — ЗДОРОВЫЙ прогон.

ТРИ ИСХОДА (Р1): годно — здоровый зелёный и покраснели все мутанты; не годно —
здоровый красный или хоть один промолчал; не смогли — цели мутанта нет в файле.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_round13",)

BS = "studio/brief_spec.py"
PN = "studio/planner.py"
PR = "studio/pricing.py"
AP = "studio/recipes/apply.py"
TB = "studio/recipes/table.py"
RT = "studio/realtime.py"
SV = "studio/mcp/server.py"

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- реальное время --------------------------------------------------------------
    (RT, "NEGATION_WINDOW = 4", "NEGATION_WINDOW = 2", "«does not need to be real time» — пробел"),
    (RT, "NEGATION_WINDOW = 4", "NEGATION_WINDOW = 9", "далёкое «no budget» снимает живой аватар"),
    (RT, "OPTIONS_SHOWN = 8", "OPTIONS_SHOWN = 4", "вариантов реального времени вдвое меньше"),
    (RT, "OPTIONS_SHOWN = 8", "OPTIONS_SHOWN = 16", "вариантов реального времени без предела"),
    (RT, "    clean = NOT_LIVE.sub(\" \", t)", "    clean = t", "real-time strategy и запись эфира читаются живым эфиром"),
    (RT, "    return bool(tasks & REALTIME_TASKS) or bool(outputs & SPEAKING_OUTPUTS)", "    return True",
     "трейлер real-time strategy — пробел"),
    (RT, "    return bool(tasks & REALTIME_TASKS) or bool(outputs & SPEAKING_OUTPUTS)",
     "    return bool(outputs & SPEAKING_OUTPUTS)", "живой аватар без речи в выходах — план"),
    (SV, "    if realtime.applies(brief, spec):", "    if False:", "живой аватар снова вопрос о длине"),
    # --- рефрейм ------------------------------------------------------------------------
    (BS, "CROP_ASPECT_TOLERANCE = 1.05", "CROP_ASPECT_TOLERANCE = 1.0", "1.8:1 из 16:9 — дорисовка"),
    (BS, "CROP_ASPECT_TOLERANCE = 1.05", "CROP_ASPECT_TOLERANCE = 1.5", "3:2 из квадрата — кадрирование"),
    (BS, "UNKNOWN_SOURCE_CROP_MAX = 1.0", "UNKNOWN_SOURCE_CROP_MAX = 0.5", "9:16 без кадра исходника — дорисовка"),
    (BS, "UNKNOWN_SOURCE_CROP_MAX = 1.0", "UNKNOWN_SOURCE_CROP_MAX = 2.0", "16:9 без кадра исходника — кадрирование"),
    (BS, "        правки[правки.index(ep.EDIT_REFRAME)] = EDIT_CROP", "        pass", "рефрейм всегда дорисовка"),
    # --- только монтаж ---------------------------------------------------------------------
    (BS, "            if not ASSEMBLY_WORD_NEGATED.search(низ[: м.start()]):", "            if True:",
     "«убрать водяной знак» читается наложением"),
    (BS, "    EDIT_LUT: NOTE_LUT,\n", "", "LUT не монтаж"),
    (BS, "        п for п in spec.edit if п in ASSEMBLY_ONLY_EDITS or (п in на_сборке and п in ASSEMBLY_EDITS)",
     "        п for п in spec.edit if (п in на_сборке and п in ASSEMBLY_EDITS)", "монтажные правки уходят в модель"),
    (BS, '                if задача == "captions" and "script" in входы:', "                if False:",
     "приложенные субтитры снова расшифровываются"),
    (BS, '    if монтаж_целиком(spec, текст) and raw.get("inputs") is not None:', "    if False:",
     "монтаж без длины — вопрос"),
    # --- звук по картинке ------------------------------------------------------------------
    (BS, 'V2A_OUTPUTS: frozenset[str] = frozenset({"sfx", "music"})', 'V2A_OUTPUTS: frozenset[str] = frozenset({"sfx"})',
     "саундтрек к своему видео без работы — вопрос"),
    (BS, 'V2A_OUTPUTS: frozenset[str] = frozenset({"sfx", "music"})',
     'V2A_OUTPUTS: frozenset[str] = frozenset({"sfx", "music", "speech"})', "речь к своему видео без работы — не вопрос"),
    (BS, "    if звук_к_своему_видео(spec):\n        # ТРИНАДЦАТЫЙ", "    if False:\n        # ТРИНАДЦАТЫЙ",
     "шумы к своему ролику с генеративной правкой"),
    (AP, '        sound = [s for s in ("звук_фон", "музыка") if s in steps and (s == "звук_фон" or follows_picture(spec, text))]',
     '        sound = [s for s in ("звук_фон",) if s in steps]', "саундтрек под действие — генерация музыки"),
    (AP, '        sound = [s for s in ("звук_фон", "музыка") if s in steps and (s == "звук_фон" or follows_picture(spec, text))]',
     '        sound = [s for s in ("звук_фон", "музыка") if s in steps]', "фоновая музыка свадьбы — видео в звук"),
    # --- общие референсы и петля -----------------------------------------------------------
    (BS, "        elif (spec.characters or 0) >= MULTI_CHARACTER_MIN and серия_с_персонажем(spec):", "        elif False:",
     "персонажи генерируются на каждый шот"),
    (BS, "        elif (spec.characters or 0) >= MULTI_CHARACTER_MIN and серия_с_персонажем(spec):",
     "        elif (spec.characters or 0) >= MULTI_CHARACTER_MIN:", "один шот двух персонажей — референсы и правка"),
    (TB, "LOOP_CLIP_S = VISUALISER_LOOP_CLIP_S", "LOOP_CLIP_S = 4", "петля без названной длины вдвое короче"),
    (TB, "LOOP_CLIP_S = VISUALISER_LOOP_CLIP_S", "LOOP_CLIP_S = 16", "петля без названной длины вдвое длиннее"),
    (AP, "            counts[maker] = 1", "            pass", "петля генерируется на каждую версию"),
    (PN, '    if штук is not None and {OUTPUT_KINDS.get(а) for а in op.produces} != {"изображение"}:', "    if False:",
     "счёт маршрута у видео-шага не печатается"),
    (PN, '        общий = шаг in отмечены or шаг == "клонирование_голоса" or (шаг in SHARED_ASSET_STEPS and берут > сделано)',
     '        общий = шаг in отмечены or шаг == "клонирование_голоса" or берут > сделано', "озвучка читается общим активом"),
    (PN, '        общий = шаг in отмечены or шаг == "клонирование_голоса" or (шаг in SHARED_ASSET_STEPS and берут > сделано)',
     '        общий = шаг in отмечены or шаг == "клонирование_голоса"', "референсы серии не названы общими"),
    # --- клон и начитка ------------------------------------------------------------------------
    (PN, "    return ep.TTS in узел.functions or ARTEFACT_TEXT_INPUT in узел.inputs or ARTEFACT_AUDIO in узел.outputs",
     "    return True", "клон без начитки читает текст сам"),
    (PN, "    return ep.TTS in узел.functions or ARTEFACT_TEXT_INPUT in узел.inputs or ARTEFACT_AUDIO in узел.outputs",
     "    return False", "клон-синтезатор получает лишнюю озвучку"),
    (PN, '                найдено_на_шаг[op.name].sort(key=lambda c: not c.model.startswith(линейка_клона[0] + "-"))',
     "                pass", "голос клона читает синтез чужой линейки"),
    (PR, "                        if any(r.unit == \"usd\" and r.amount > 0 for r in прочие) and not need.clone_only",
     "                        if any(r.unit == \"usd\" and r.amount > 0 for r in прочие)", "плата за клон — нижняя граница"),
    # --- кадр исходника ------------------------------------------------------------------------
    (PN, 'SOURCE_FRAME_TASKS: frozenset[str | None] = frozenset({"video-edit", "edit", "face-replace", "restore", "colorize"})',
     'SOURCE_FRAME_TASKS: frozenset[str | None] = frozenset({"edit", "face-replace", "restore", "colorize"})',
     "правка 4K моделью 720p без апскейла"),
    # --- губы в шотах ----------------------------------------------------------------------------
    (BS, "    return персонаж and bool(SPEAKING_IN_FRAME.search(сказано) or DIALOGUE.search(сказано))",
     "    return персонаж and bool(SPEAKING_IN_FRAME.search(сказано))", "«разговаривают» без губ"),
    (BS, '            штук["липсинк"] = int(spec.shots or 0)', "            pass", "липсинк один на весь сериал"),
    (BS, '    поёт = "audio" in входы and "speech" not in выходы', "    поёт = False", "певица без губ"),
    (BS, '    elif поют_в_кадре(replace(spec, characters=поля["characters"]), текст):', "    elif False:",
     "поёт в кадр — не видно"),
    (BS, "    if клип_с_исполнителем(spec, текст):", "    if False:", "клип с исполнителем без референса"),
    (BS, '    if задача == "music-visualiser" and "photo" not in входы and (spec.characters or 0) >= 1:', "    if False:",
     "клип с исполнителем — петли визуализатора"),
    (BS, "    return сцен and bool(PERFORMER.search(сказано) or SINGING.search(сказано))", "    return сцен",
     "пейзажный клип получает исполнителя"),
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
