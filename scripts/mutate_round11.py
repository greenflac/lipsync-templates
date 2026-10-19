#!/usr/bin/env python3
"""Т1: мутация констант-решений ОДИННАДЦАТОГО КРУГА — в обе стороны.

    python scripts/mutate_round11.py          # все мутанты
    python scripts/mutate_round11.py 0 6      # мутанты с 0 по 5 (прогон частями)

Что мутируется: пороги чек-листа (длинный звук, длинная музыка, мало
видеопамяти, пакет, переходы, серия, несколько голосов), наборы письменностей
(справа налево, CJK, без кратких гласных), слова условий, которых в
спецификации нет (телефония, детская аудитория), цена шага на своём GPU
(0 usd, ничья по аренде, вердикт потолка 0) и вариант дешевле потолка (доля
«короче»).

Устройство — как у `scripts/mutate_round10.py` (Е1): файл правится на диске,
набор гоняется через `python -B` со снесённым `__pycache__`, файл
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

НАБОРЫ = ("studio.tests.test_checklist_r11",)

CL = "studio/recipes/checklist.py"
PN = "studio/planner.py"
SV = "studio/mcp/server.py"

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    (CL, "LONG_AUDIO_S = 300", "LONG_AUDIO_S = 299", "300 с речи режутся на куски"),
    (CL, "LONG_AUDIO_S = 300", "LONG_AUDIO_S = 301", "301 с речи без кусков"),
    (CL, "MUSIC_RUN_MAX_S = 240", "MUSIC_RUN_MAX_S = 239", "4 минуты музыки частями"),
    (CL, "MUSIC_RUN_MAX_S = 240", "MUSIC_RUN_MAX_S = 241", "241 с музыки одним прогоном"),
    (CL, "LOW_VRAM_GB = 12", "LOW_VRAM_GB = 11", "12 ГБ не «мало памяти»"),
    (CL, "LOW_VRAM_GB = 12", "LOW_VRAM_GB = 16", "16 ГБ — «мало памяти»"),
    (CL, "BULK_ITEMS = 20", "BULK_ITEMS = 21", "20 генераций не пакет"),
    (CL, "BULK_ITEMS = 20", "BULK_ITEMS = 19", "19 генераций — пакет"),
    (CL, "TRANSITION_MIN_SHOTS = 2", "TRANSITION_MIN_SHOTS = 3", "два шота без перехода"),
    (CL, "TRANSITION_MIN_SHOTS = 2", "TRANSITION_MIN_SHOTS = 1", "один шот с переходом"),
    (CL, "SERIES_MIN_SHOTS = 3", "SERIES_MIN_SHOTS = 4", "три шота с героем без листа"),
    (CL, "SERIES_MIN_SHOTS = 3", "SERIES_MIN_SHOTS = 2", "два шота — серия"),
    (CL, "MULTI_VOICE_MIN = 2", "MULTI_VOICE_MIN = 3", "два персонажа одним голосом"),
    (CL, "MULTI_VOICE_MIN = 2", "MULTI_VOICE_MIN = 1", "один диктор — «кастинг голосов»"),
    (CL, '{"ar", "he", "fa", "ur", "yi", "ps", "sd", "ug", "dv", "ckb"}',
     '{"ar", "fa", "ur", "yi", "ps", "sd", "ug", "dv", "ckb"}', "иврит не справа налево"),
    (CL, 'CJK_LANGS: frozenset[str] = frozenset({"zh", "cmn", "yue", "ja", "ko"})',
     'CJK_LANGS: frozenset[str] = frozenset({"zh", "cmn", "yue", "ko"})', "японский без кинсоку"),
    (CL, 'DIACRITIC_LANGS: frozenset[str] = frozenset({"ar", "he", "fa", "ur"})',
     'DIACRITIC_LANGS: frozenset[str] = frozenset({"ar", "he", "fa", "ur", "yi"})', "идиш с огласовками"),
    (CL, 'DIACRITIC_LANGS: frozenset[str] = frozenset({"ar", "he", "fa", "ur"})',
     'DIACRITIC_LANGS: frozenset[str] = frozenset({"ar", "he", "fa"})', "урду без огласовок"),
    (CL, '    r"\\bivr\\b|phone (?:line|menu|system|tree)', '    r"\\bivrНЕТ\\b|phone (?:line|menu|system|tree)НЕТ',
     "IVR не телефония"),
    (CL, '    r"|для детей|детск|', '    r"|для детейНЕТ|детскНЕТ|', "«для детей» не узнаётся"),
    (CL, "        if self.jobs and not (self.jobs & ctx.jobs):", "        if False:", "правило без своей работы"),
    (PN, "    if c.gpu_rent_usd is not None:\n        return True\n", "", "свой GPU с оценкой без цены"),
    (PN, "    if c.gpu_rent_usd is not None:\n        return 0, c.gpu_rent_usd\n", "", "ничья своего GPU по нулям"),
    (PN, "        elif not (неполная or без_ролика):\n            # ПОТОЛОК 0 И ПЛАН ЗА 0",
     "        elif False:\n            # ПОТОЛОК 0 И ПЛАН ЗА 0", "потолок 0 и план за 0 не сравнены"),
    (PN, "SHORTER_MIN_SHARE = 0.25", "SHORTER_MIN_SHARE = 0.3", "четверть длины не предлагается"),
    (PN, "SHORTER_MIN_SHARE = 0.25", "SHORTER_MIN_SHARE = 0.2", "меньше четверти длины предлагается"),
    (PN, "    if шаги and сумма < минимум - 0.005:", "    if False:", "дешёвые модели не названы"),
    (CL, "            (общие if р.trigger is _always else условные).append((р.id, поля))",
     "            (условные if р.trigger is _always else общие).append((р.id, поля))", "общие правила раньше условий"),
    (CL, "transparent(?!\\s+(?:background|bg|backdrop))", "transparent", "прозрачный фон — стекло"),
    (CL, "    if c.priors & LOGO_PRIORS:\n        return False\n", "", "логотип повторяется после рецепта"),
    (SV, "    if len(out) > объявлено and limit > _CAP_RESERVE * 4:", "    if False:", "объявление обрезки за потолком"),
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
