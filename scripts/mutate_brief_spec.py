#!/usr/bin/env python3
"""Т1: мутация констант-решений структурного разбора брифа (`studio/brief_spec.py`)
и того, как его числа проходят в план и в цену, — в обе стороны.

    python scripts/mutate_brief_spec.py

Скрипт правит файл на диске, гоняет `НАБОРЫ` через `python -B` со снесённым
`__pycache__` (мутант не должен прочитаться из скомпилированного), ВОЗВРАЩАЕТ
файл как был. Первой строкой — ЗДОРОВЫЙ прогон: таблица поверх красного дерева
не значит ничего. Мутант, после которого всё зелёное, — константа, которую
никто не сторожит; исход скрипта тогда «не годно».

ТРИ ИСХОДА (Р1): годно — здоровый прогон зелёный и покраснели все мутанты;
не годно — здоровый красный или хоть один мутант промолчал; не смогли — цели
мутанта нет в файле (мутант устарел и ничего не проверяет).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_brief_spec_r4",)

BS = "studio/brief_spec.py"
PN = "studio/planner.py"
PR = "studio/pricing.py"

#: (файл, было, стало, что ломается). Каждая константа — строже и слабее.
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    (BS, "POSSESSIVE_WINDOW = 3", "POSSESSIVE_WINDOW = 2", "окно притяжательного уже"),
    (BS, "POSSESSIVE_WINDOW = 3", "POSSESSIVE_WINDOW = 4", "окно притяжательного шире"),
    (BS, "OBJECT_WINDOW = 4", "OBJECT_WINDOW = 3", "окно объекта уже"),
    (BS, "OBJECT_WINDOW = 4", "OBJECT_WINDOW = 5", "окно объекта шире"),
    (BS, "EACH_WINDOW = 1", "EACH_WINDOW = 0", "«по» только вплотную"),
    (BS, "EACH_WINDOW = 1", "EACH_WINDOW = 2", "«по» дальше от числа"),
    (BS, "MULTI_CHARACTER_MIN = 2", "MULTI_CHARACTER_MIN = 1", "кадры и у одного персонажа"),
    (BS, "MULTI_CHARACTER_MIN = 2", "MULTI_CHARACTER_MIN = 3", "двоим кадров не делают"),
    (BS, 'DEFAULT_VIDEO_RESOLUTION = "1080p"', 'DEFAULT_VIDEO_RESOLUTION = "720p"', "кадр по умолчанию ниже"),
    (BS, "ASSUMED_SHOT_S = 8.0", "ASSUMED_SHOT_S = 7.0", "допущенный шот короче"),
    (BS, "ASSUMED_SHOT_S = 8.0", "ASSUMED_SHOT_S = 10.0", "допущенный шот длиннее"),
    (
        BS,
        'ROUTE_FIRST_WITH: dict[str, str] = {"dub-translate": "video", "face-replace": "video"}',
        'ROUTE_FIRST_WITH: dict[str, str] = {"face-replace": "video"}',
        "перевод своего видео снова собирают подсказки",
    ),
    (
        BS,
        'ROUTE_FIRST_WITH: dict[str, str] = {"dub-translate": "video", "face-replace": "video"}',
        'ROUTE_FIRST_WITH: dict[str, str] = {"dub-translate": "", "face-replace": "video"}',
        "перевод маршрутом и без своего видео",
    ),
    (
        BS,
        'ROUTE_FIRST_WITHOUT: dict[str, tuple[str, ...]] = {"avatar": ("video", "photo")}',
        "ROUTE_FIRST_WITHOUT: dict[str, tuple[str, ...]] = {}",
        "аватар без снимка снова TTS + t2v + липсинк",
    ),
    (
        BS,
        'ROUTE_FIRST_WITHOUT: dict[str, tuple[str, ...]] = {"avatar": ("video", "photo")}',
        'ROUTE_FIRST_WITHOUT: dict[str, tuple[str, ...]] = {"avatar": ("video",)}',
        "аватар маршрутом и при принесённом снимке",
    ),
    (BS, '    "avatar": ("video", "speech"),\n', "", "работа аватара не говорит, что выходит видео"),
    (BS, '    if "speech" in spec.outputs and "video" in spec.outputs and spec.audio is None', "    if False", "голос поверх картинки не назван допущением"),
    (BS, '"video" not in spec.inputs:\n        поля["resolution"] = DEFAULT_VIDEO_RESOLUTION', 'True:\n        поля["resolution"] = DEFAULT_VIDEO_RESOLUTION', "кадр по умолчанию и у принесённого видео"),
    (BS, "            return Маршрут()\n        if \"photo\" in входы:\n            шаги.append(\"оживление\")", "            pass\n        if \"photo\" in входы:\n            шаги.append(\"оживление\")", "генерация поверх своего видео"),
    (BS, 'cartoon|\\bclaymation|\\bstop', 'cartoon|\\bstop', "пластилин перестаёт быть генерируемым стилем"),
    (PN, '    поштучно = "генерация_изображения" in имена_плана and "оживление" in имена_плана', "    поштучно = False", "ключевых кадров снова один"),
    (PN, "клипов if поштучно else 0) or 1", "0) or 1", "кадров меньше шотов"),
    (PN, "    if bs.GENERATED_STYLE.search(_norm(brief)):\n        return True\n", "", "стиль не отвечает на «уже снято?»"),
    (PN, "    if понято.task in (None, \"generate\") and чужое_ремесло(brief):", "    if чужое_ремесло(brief):", "чужое ремесло глушит и названную работу"),
    (PN, "    if not операции and вопрос is None and ARTEFACT_VIDEO not in есть and not чужое_ремесло(brief):", "    if False:", "пустой план снова без вопроса"),
    (PN, '    просят_кадр = None if понято.source.get("resolution") == bs.SOURCE_DEFAULT else заказанный_кадр', "    просят_кадр = заказанный_кадр", "кадр-допущение дописывает апскейл"),
    (PR, "        if сек and need.shots > 1:", "        if False:", "шоты снова одним куском в цене"),
    (PR, "            прогонов = need.shots * прогонов_на_шот", "            прогонов = прогонов_на_шот", "цена за один шот вместо всех"),
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
