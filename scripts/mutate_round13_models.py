#!/usr/bin/env python3
"""Т1: мутация констант-решений ТРИНАДЦАТОГО КРУГА — в обе стороны.

    python scripts/mutate_round13_models.py          # все мутанты
    python scripts/mutate_round13_models.py 0 10     # мутанты с 0 по 9 (прогон частями)

Что мутируется: предел выхода апскейлера (шаги, атрибуты, порядок, сравнение,
отсев «ниже» только когда кто-то дотягивает, кадр исходника и заказа в отбор),
правка надписи в видео (задачи, слово о лице, человек в spec, правка в
допустимых, условие читаемости), правила чек-листа круга (многокамерность,
предел дубля, задачи генерации дубля, задачи с реалистичным лицом, роли
своего ведущего) и узкая дверь своего ведущего (роли, правило, поля заявлений,
запреты текста, число запретов, подключение в сервере).

Устройство — как у `scripts/mutate_round12_checklist.py`: файл правится на
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

НАБОРЫ = ("studio.tests.test_round13_models",)

UR = "studio/upscale_reach.py"
EI = "studio/edit_intent.py"
IH = "studio/inhouse_news.py"
CL = "studio/recipes/checklist.py"
EP = "studio/endpoints.py"
PN = "studio/planner.py"
SV = "studio/mcp/server.py"

_OPS = 'UPSCALE_OPS: frozenset[str] = frozenset({"апскейл", "апскейл_изображения"})'
_ORDER = "REACH_ORDER: dict[str, int] = {REACH_YES: 0, REACH_UNTESTED: 1, REACH_UNKNOWN: 2, REACH_BELOW: 3}"
_CAP = 'CAP_ATTRIBUTES: frozenset[str] = frozenset({"max_resolution", "max_output_resolution", "output_resolution_max"})'
_FACTOR = 'FACTOR_ATTRIBUTES: frozenset[str] = frozenset({"upscale_factor_max", "max_upscale_factor"})'
_TASKS = 'TEXT_EDIT_TASKS: frozenset[str] = frozenset({"face-replace", "edit", "video-edit"})'
_GEN = 'GENERATED_TAKE_JOBS: frozenset[str] = frozenset({"t2v", "i2v", "t2v_audio", "r2v"})'
_FACE = 'PHOTOREAL_FACE_JOBS: frozenset[str] = frozenset({"lipsync", "avatar", "sing", "char_replace", "dub"})'
_ROLES = 'IN_HOUSE_ROLES: frozenset[str] = frozenset({"employee", "self"})'

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- предел выхода апскейлера
    (UR, _OPS, _OPS.replace('"апскейл", ', ""), "апскейл видео без предела выхода"),
    (UR, _OPS, _OPS.replace('"апскейл_изображения"}', '"апскейл_изображения", "генерация_видео"}'),
     "предел выхода судит генератор"),
    (UR, _ORDER, _ORDER.replace("REACH_YES: 0, REACH_UNTESTED: 1, REACH_UNKNOWN: 2", "REACH_YES: 2, REACH_UNTESTED: 1, REACH_UNKNOWN: 0"), "молчание выше записи"),
    (UR, _CAP, _CAP.replace('"max_resolution", ', ""), "предел выхода не читается"),
    (UR, _FACTOR, _FACTOR.replace('"upscale_factor_max", ', ""), "множитель не читается"),
    (UR, "        if до >= target_short:", "        if до > target_short:", "ровно заказанный кадр — «ниже»"),
    (UR, "        if до >= target_short:", "        if до >= target_short * 0.5:", "половина кадра — «дотягивает»"),
    (UR, "    if прочитано and not не_решили:", "    if прочитано:", "нерешённый режим — «ниже»"),
    (PN, "        if дотяг_сост == ur.REACH_BELOW and not все_ниже:", "        if False:", "ниже предела не отсеивается"),
    (PN, "        if дотяг_сост == ur.REACH_BELOW and not все_ниже:", "        if дотяг_сост == ur.REACH_BELOW:",
     "все ниже — шаг без кандидатов вместо двух проходов"),
    (PN, "            треб_ранг = (ur.REACH_ORDER[дотяг_сост], *треб_ранг[1:])\n", "", "дотяг не ранжирует"),
    (PN, "            upscale_target=None if понято.source.get(\"resolution\") == bs.SOURCE_DEFAULT else заказанный_кадр,",
     "            upscale_target=None,", "заказанный кадр не доходит до отбора"),
    (PN, "            source_frame=bs.source_frame(понято),", "            source_frame=None,", "кадр исходника не доходит"),
    # --- надпись в видео
    (EI, _TASKS, _TASKS.replace('"face-replace", ', ""), "надпись под заменой лица остаётся заменой"),
    (EI, "    return bool(TEXT_EDIT_WORDS.search(низ)) and not PERSON_EDIT.search(низ)",
     "    return bool(TEXT_EDIT_WORDS.search(низ))", "слово о лице не держит задачу"),
    (EP, "    EDIT_EXTEND,\n    EDIT_REPLACE_TEXT,\n)", "    EDIT_EXTEND,\n)", "правка надписи не допустима"),
    (PN, 'TEXT_EDIT_CONDITION = "text_legibility"', 'TEXT_EDIT_CONDITION = "hands"', "читаемость надписи не в отборе"),
    # --- правила чек-листа
    (CL, "MULTICAM_MIN_INPUTS = 2", "MULTICAM_MIN_INPUTS = 3", "две камеры — не многокамерность"),
    (CL, "MULTICAM_MIN_INPUTS = 2", "MULTICAM_MIN_INPUTS = 1", "одна камера — многокамерность"),
    (CL, "SINGLE_TAKE_TYPICAL_MAX_S = 15.0", "SINGLE_TAKE_TYPICAL_MAX_S = 16.0", "16 с — ещё один прогон"),
    (CL, "SINGLE_TAKE_TYPICAL_MAX_S = 15.0", "SINGLE_TAKE_TYPICAL_MAX_S = 14.0", "15 с — уже несколько прогонов"),
    (CL, _GEN, _GEN.replace('"r2v"}', '"r2v", "avatar"}'), "аватар по звуку — «длинный дубль»"),
    (CL, _GEN, _GEN.replace('"t2v", ', ""), "генерация по тексту без предела дубля"),
    (CL, _FACE, _FACE.replace('"lipsync", ', ""), "липсинк мультяшки без оговорки"),
    (CL, _ROLES, _ROLES.replace(', "self"', ""), "сам заказчик — не свой ведущий (чек-лист)"),
    (CL, _ROLES, _ROLES.replace('"self"}', '"self", "talent"}'), "нанятый — свой ведущий (чек-лист)"),
    # --- свой ведущий
    (IH, _ROLES, _ROLES.replace('"employee", ', ""), "сотрудник — не свой"),
    (IH, _ROLES, _ROLES.replace('"self"}', '"self", "talent"}'), "нанятый — свой"),
    (IH, 'LIFTED_RULE = "public_statement"', 'LIFTED_RULE = "consent_none"', "дверь не для публичного заявления"),
    (IH, "    if any(з.get(\"real_brand\") is True for з in claims):\n        return False\n", "", "чужой канал проходит"),
    (IH, '    if any(з.get("fabricated") is not False for з in новости):', '    if any(з.get("fabricated") is True for з in новости):',
     "неизвестно, выдумано ли, — проходит"),
    (IH, '    return any(з.get("own_brand") is True for з in новости)', "    return True", "не своя редакция проходит"),
    (IH, '    if text_screen.get("banned") or text_screen.get("injection"):', "    if False:", "запрет текста снимается"),
    (IH, "    if len(list(screened.get(\"banned\") or [])) != len(отказаны)", "    if False", "лишний запрет снимается"),
    (SV, "    просев, политика = inhouse_news.apply(свой_выпуск, просев, политика)\n", "", "дверь не подключена"),
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
