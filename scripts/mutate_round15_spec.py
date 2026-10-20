#!/usr/bin/env python3
"""Т1: мутация ветвей ПЯТНАДЦАТОГО КРУГА (решения по полям spec) — в обе стороны.

    python scripts/mutate_round15_spec.py          # все мутанты
    python scripts/mutate_round15_spec.py 0 20     # мутанты с 0 по 19 (прогон частями)

Что мутируется: каждое новое поле spec и ветвь, которая его читает раньше слов
брифа, — живая система (`live`), цель правки (`edit_target`), петля и прозрачность
выхода (`outputs[].loop`, `outputs[].alpha`), говорящий и исполнитель в кадре
(`people[].on_screen`, `people[].speaks`, `lipsync` на генерируемом клипе), кадр на
двоих (`cast_together`), длина дубля (`single_take_s`), обучение (`training_use`),
постоянство (`consistency`), датасет (`dataset_count`), зритель (`audience` для
слов о детях), и поля решений в черновике вопроса о спецификации. Каждая ветвь —
в обе стороны: поле проигнорировано (решают слова) и поле решает всегда одно.

Устройство — как у `scripts/mutate_round14_steps.py`: файл правится на диске, набор
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

НАБОРЫ = ("studio.tests.test_round15_spec",)

BS = "studio/brief_spec.py"
RT = "studio/realtime.py"
EI = "studio/edit_intent.py"
CL = "studio/recipes/checklist.py"
AP = "studio/recipes/apply.py"
PN = "studio/planner.py"

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- разбор полей ---------------------------------------------------------------------
    (BS, '    for ключ in ("live", "cast_together", "training_use"):', '    for ключ in ("live", "training_use"):',
     "cast_together не читается"),
    (BS, '    for ключ, целое in (("single_take_s", False), ("dataset_count", True)):',
     '    for ключ, целое in (("dataset_count", True),):', "single_take_s не читается"),
    (BS, '    _enum("edit_target", EDIT_TARGETS)\n', "", "edit_target не читается"),
    (BS, '        поля["consistency"] = tuple(dict.fromkeys(з for з in оси if з in CONSISTENCY_AXES))',
     '        поля["consistency"] = ()', "consistency пусто"),
    (BS, "            поля[ключ] = any(значения)", "            поля[ключ] = not any(значения)", "петля наоборот"),
    (BS, "            поля[ключ] = any(значения)", "            pass", "петля выхода не читается"),
    (BS, '        for ключ in _PEOPLE_FLAGS:\n            if ч.get(ключ) is not None:',
     '        for ключ in ():\n            if ч.get(ключ) is not None:', "on_screen / speaks не читаются"),
    # --- говорящий в кадре по полям ------------------------------------------------------
    (BS, "    if spec.lipsync is not None and spec.task in GENERATED_LIPS_TASKS:\n        return spec.lipsync\n",
     "", "lipsync генерируемого клипа не решает"),
    (BS, "    if spec.lipsync is not None and spec.task in GENERATED_LIPS_TASKS:\n        return spec.lipsync\n",
     "    if spec.lipsync is not None and spec.task in GENERATED_LIPS_TASKS:\n        return True\n",
     "lipsync=false всё равно губы"),
    (BS, "    if any(п.get(\"on_screen\") is True and п.get(\"speaks\") is True for п in описаны):\n        return True",
     "    if any(п.get(\"on_screen\") is True and п.get(\"speaks\") is True for п in описаны):\n        return False",
     "говорящий в кадре без губ"),
    (BS, "    if all(п.get(\"on_screen\") is False or п.get(\"speaks\") is False for п in описаны):\n        return False",
     "    if all(п.get(\"on_screen\") is False or п.get(\"speaks\") is False for п in описаны):\n        return True",
     "молчащий / невидимый с губами"),
    (BS, "    if any(п.get(\"on_screen\") is True and п.get(\"speaks\") is True for п in описаны):\n        return True",
     "    if False:\n        return True", "поля людей не решают «да»"),
    (BS, "    if решено is not None:\n        return решено\n    сказано = \" \".join(",
     "    сказано = \" \".join(", "говорят в кадре — снова только слова"),
    (BS, "    if решено is not None:\n        return решено\n    сказано = исполнитель_словами(",
     "    сказано = исполнитель_словами(", "поют в кадре — снова только слова"),
    (BS, "    if решено is False:\n        return False\n    if решено is None:\n", "    if решено is None:\n",
     "молчащий повар — нативный звук"),
    (BS, "    if решено is None:\n        if not SPEAKING_IN_FRAME", "    if True:\n        if not SPEAKING_IN_FRAME",
     "говорящий повар по полю без слов — закадр"),
    # --- исполнитель и визуализатор ------------------------------------------------------
    (BS, "    if not видны:\n        return None\n    return any(видны)", "    if not видны:\n        return None\n    return True",
     "исполнитель вне кадра — референс исполнителя"),
    (BS, "    if в_кадре is not None:\n        return сцен and в_кадре\n", "", "on_screen исполнителя не решает"),
    (BS, "    if spec.task in GENERATED_LIPS_TASKS and spec.lipsync is True:\n        return сцен\n", "",
     "lipsync=true без исполнителя"),
    (BS, "        return сцен and bool(PERFORMER.search(сказано))\n", "        return False\n",
     "lipsync=false убирает и названного исполнителя"),
    (BS, "    if spec.task in GENERATED_LIPS_TASKS and spec.lipsync is False:\n", "    if False:\n",
     "lipsync=false — «поёт» словами ставит исполнителя"),
    (BS, '    if any(п.get("on_screen") is not False for п in spec.people):\n        return False',
     "    if spec.people:\n        return False", "артист вне кадра мешает визуализатору"),
    (BS, '    текст = NO_LIPSYNC.sub(" ", str(текст or ""))\n', "", "«no lip sync» словами — липсинк"),
    # --- кадр на двоих, постоянство, датасет ----------------------------------------------
    (BS, "    if spec.cast_together is not None:\n", "    if False:\n", "cast_together не решает"),
    (BS, "        return spec.cast_together\n", "        return True\n", "cast_together=false — ключевые кадры"),
    (BS, '    elif "consistency" in spec.source:\n', '    elif False:\n', "consistency=character не даёт персонажа"),
    (BS, '        if "character" not in spec.consistency:\n            return 0, ""\n', "",
     "consistency без character — слова «same cat» решают"),
    (BS, "    if spec.dataset_count:\n        # Пятнадцатый круг", "    if False:\n        # Пятнадцатый круг",
     "датасет полем — одна картинка"),
    # --- черновик -----------------------------------------------------------------------
    (BS, '        "decision_fields": decision_fields(brief, raw),\n', "", "черновик не предлагает поля решений"),
    (BS, '        if верх in названо and верх not in ("outputs", "people"):\n            continue\n', "",
     "названные поля снова предлагаются"),
    (BS, '        if верх in названо and верх not in ("outputs", "people"):', "        if верх not in названо:",
     "неназванные поля не предлагаются"),
    (BS, '    if NO_LIPSYNC.search(brief):\n        прочитано["lipsync"] = False', '    if False:\n        прочитано["lipsync"] = False',
     "черновик не читает «no lip sync»"),
    # --- живая система ---------------------------------------------------------------------
    (RT, "    if isinstance(live, bool):\n        return live and", "    if False:\n        return live and",
     "live не решает"),
    (RT, "        return live and (bool(tasks & REALTIME_TASKS) or bool(outputs & SPEAKING_OUTPUTS))",
     "        return live", "живое без речи — пробел"),
    (RT, "        return live and (bool(tasks & REALTIME_TASKS) or bool(outputs & SPEAKING_OUTPUTS))",
     "        return False", "live=true — план"),
    # --- цель правки -----------------------------------------------------------------------
    (EI, "    if цель is not None:\n        return цель == EDIT_TARGET_TEXT", "    if False:\n        return цель == EDIT_TARGET_TEXT",
     "edit_target не решает"),
    (EI, "        return цель == EDIT_TARGET_TEXT", "        return True", "edit_target=person — правка надписи"),
    (EI, "        return цель == EDIT_TARGET_TEXT", "        return False", "edit_target=text — замена персонажа"),
    # --- оговорки: слова -> поле -----------------------------------------------------------
    (CL, "            if решено is not None:\n                return решено\n", "", "поля оговорок не старше слов"),
    (CL, "    W_TRAINING_DATA: lambda spec: spec.training_use,\n", "", "training_use не решает"),
    (CL, "    W_LOOP: lambda spec: spec.loop,\n", "", "петля выхода не решает оговорку"),
    (CL, "    W_KIDS: _audience_children,\n", "", "audience не решает «для детей»"),
    (CL, '    return None if spec.audience is None else spec.audience == "children"', '    return spec.audience == "children"',
     "audience не названо — слова о детях молчат"),
    (CL, '        return {"seconds": f"{дубль:g}"} if дубль > предел else None', "        return None",
     "single_take_s не даёт оговорки"),
    (CL, '        return {"seconds": f"{дубль:g}"} if дубль > предел else None', '        return {"seconds": f"{дубль:g}"}',
     "короткий single_take_s — оговорка"),
    (CL, "    if c.spec.single_take_s is not None:\n", "    if False:\n", "single_take_s не решает"),
    (CL, "        return правка or int(c.spec.shots or 1) >= RELIGHT_SERIES_MIN_SHOTS", "        return False",
     "consistency=light без оговорки света"),
    (CL, '    if "consistency" in c.spec.source or c.spec.edit_target is not None:\n        return False\n', "",
     "consistency без света — слова о свете решают"),
    (CL, '    серия = "light" in c.spec.consistency and', '    серия = "light" in c.spec.edit and',
     "consistency=light не читается"),
    (CL, "    if c.spec.dataset_count or c.says(W_TRAINING_DATA)", "    if c.says(W_TRAINING_DATA)",
     "малый датасет полем — без согласий"),
    (CL, "        [int(c.spec.shots or 0), int(c.spec.dataset_count or 0)]", "        [int(c.spec.shots or 0)]",
     "размер датасета не из поля"),
    # --- план: число картинок -----------------------------------------------------------------
    (PN, '    if понято.source.get("shots") == bs.SOURCE_SPEC:\n        return None\n    return кадров_заказано(brief)',
     "    return кадров_заказано(brief)", "«6 images» словами старше spec.shots"),
    (PN, '    if понято.source.get("shots") == bs.SOURCE_SPEC:\n        return None\n    return кадров_заказано(brief)',
     "    return None", "без spec.shots слова о числе картинок молчат"),
    # --- рецепты: петля, прозрачность --------------------------------------------------------
    (AP, "    if петля is False:\n        return None\n", "", "loop=false — петля по словам"),
    (AP, "    if петля is None and not any(", "    if not any(", "loop=true без слов — не петля"),
    (AP, "    if альфа is not None:\n        return альфа\n", "", "alpha не решает"),
    (AP, "    if альфа is not None:\n        return альфа\n", "    if альфа is not None:\n        return True\n",
     "alpha=false — прозрачный фон"),
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
