#!/usr/bin/env python3
"""Т1: мутация констант-решений СЕДЬМОГО КРУГА (find_models и ранжирование) — в обе стороны.

    python scripts/mutate_knowledge_r7.py          # все мутанты
    python scripts/mutate_knowledge_r7.py 0 12     # мутанты с 0 по 11 (прогон частями)

Что мутируется: язык по BCP-47 (первичный подтег), память GPU (отсев, оценка,
слова о памяти), требование «open» без записи, лицензия как довод только при
вопросе из одних требований, звук «нет», множитель частоты (граница и
исходная частота), правка, названная идентификатором; поле «провал против
объявленной хорошей новости» (ступени, условие, один дубль), число прогонов,
похвала без цены, хостинг против юрисдикции, узел семьи «только у себя»;
реставрация шумодавом и именованная правка в реестре; «--t5_cpu» не память.

Устройство — как у `scripts/mutate_registry_r6.py` (Е1): файл правится на
диске, наборы гоняются через `python -B` со снесённым `__pycache__`, файл
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

НАБОРЫ = (
    "studio.mcp.tests.test_knowledge_r7",
    "studio.mcp.tests.test_find_models",
    "studio.tests.test_endpoints_r5",
)

CAP = "studio/mcp/capability.py"
PN = "studio/planner.py"
EP = "studio/endpoints.py"
HN = "studio/hardneed.py"

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- find_models: язык, память, требования
    (
        CAP,
        '    return имя if имя != тег else тег.split("-")[0].lower()',
        "    return имя",
        "kk-KZ снова не kk",
    ),
    (
        CAP,
        "REQUIRE_RECORDED: frozenset[str] = frozenset({REQ_OPEN})",
        "REQUIRE_RECORDED: frozenset[str] = frozenset()",
        "open без записи о весах снова «прошла»",
    ),
    (
        CAP,
        "REQUIRE_RECORDED: frozenset[str] = frozenset({REQ_OPEN})",
        'REQUIRE_RECORDED: frozenset[str] = frozenset({REQ_OPEN, REQ_COMMERCIAL, "vram"})',
        "незаписанное отсеивает и там, где должно ранжировать",
    ),
    (
        CAP,
        "            if положение == hn.VRAM_OVER:",
        "            if False:",
        "память больше спрошенной не отсеивает",
    ),
    (
        CAP,
        "            if положение == hn.VRAM_FITS:",
        "            if положение != hn.VRAM_OVER:",
        "оценка снизу по параметрам — «влезает»",
    ),
    (
        CAP,
        "    if м and (требование or _ПАМЯТЬ_КОНТЕКСТ.search(низ)):",
        "    if м:",
        "любой «5GB» в вопросе — память GPU",
    ),
    (
        CAP,
        "            if id(f) not in уже and вопрос.только_требования:",
        "            if id(f) not in уже:",
        "лицензия снова довод при вопросе о памяти (f18)",
    ),
    (
        CAP,
        "            if id(f) not in уже and вопрос.только_требования:",
        "            if id(f) not in уже and False:",
        "подтверждённое требование не ответ и на вопрос из одних требований",
    ),
    # --- find_models: знак по значению
    (
        CAP,
        '                if re.search(правило["нет"], низ):',
        "                if False:",
        "«no audio» не плохая новость",
    ),
    (
        CAP,
        "                    if итог >= вопрос.кадров:",
        "                    if итог > вопрос.кадров:",
        "30 fps × 4 = 120 не дотягивает до 120",
    ),
    (
        CAP,
        '                return (\n                    INFO,\n                    POLARITY_NONE,\n                    f"x{множитель:g} of the source',
        '                return (\n                    GOOD,\n                    POLARITY_NONE,\n                    f"x{множитель:g} of the source',
        "множитель без исходной частоты — хорошая новость",
    ),
    (
        CAP,
        "            if п in ep.edit_named(у):",
        "            if п in ep.edit_intents(у):",
        "правка по инструкции — как названная идентификатором",
    ),
    # --- плановщик: провал против объявленной хорошей новости, прогоны, хостинг
    (
        PN,
        "FAILURE_CLEAR = 0\nFAILURE_OTHER = 1",
        "FAILURE_CLEAR = 1\nFAILURE_OTHER = 0",
        "провал снова выше объявленной похвалы",
    ),
    (
        PN,
        "    if c.against == 0 and (sign_rank(c) == SIGN_CLEAN or c.declared_good > 0 or c.one_take):",
        "    if (sign_rank(c) == SIGN_CLEAN or c.declared_good > 0 or c.one_take):",
        "похвала перевешивает записанный провал",
    ),
    (
        PN,
        "    if c.against == 0 and (sign_rank(c) == SIGN_CLEAN or c.declared_good > 0 or c.one_take):",
        "    if c.against == 0 and (sign_rank(c) == SIGN_CLEAN or c.declared_good > 0):",
        "один прогон на весь ролик — не довод",
    ),
    (
        PN,
        'ONE_TAKE_STEPS: frozenset[str] = frozenset({"говорящий_аватар"})',
        "ONE_TAKE_STEPS: frozenset[str] = frozenset()",
        "аватар не шаг одного дубля",
    ),
    (
        PN,
        'ONE_TAKE_STEPS: frozenset[str] = frozenset({"говорящий_аватар"})',
        'ONE_TAKE_STEPS: frozenset[str] = frozenset({"говорящий_аватар", "липсинк"})',
        "липсинк тоже «один дубль»",
    ),
    (
        PN,
        "        # ЧИСЛО ПРОГОНОВ (седьмой круг): куски — швы, сборка и цена.\n        c.runs,",
        "        # ЧИСЛО ПРОГОНОВ (седьмой круг): куски — швы, сборка и цена.\n        0,",
        "число прогонов не решает ничью",
    ),
    (
        PN,
        "    return max(1, math.ceil(секунды / предел - 1e-9))",
        "    return max(1, int(секунды / предел))",
        "61 с при пределе 60 — один прогон",
    ),
    (
        PN,
        '        if f.contra is False and not f.attribute.startswith("price") and not fa.is_contra(f)',
        "        if f.contra is False and not fa.is_contra(f)",
        "цена — объявленная хорошая новость",
    ),
    (
        PN,
        '    if set(узел.hosting) & set(юрисдикции):\n        return ""',
        '    if False:\n        return ""',
        "хостинг в вашей юрисдикции всё равно отсеивает",
    ),
    (
        PN,
        '    if not юрисдикции or узел is None or not узел.hosting:\n        return ""',
        '    if not юрисдикции or узел is None:\n        return ""',
        "незаписанный хостинг — отсев, а не «не измерено»",
    ),
    (
        PN,
        "    return bool(узел.variants) and bool(узел.routes) and set(узел.routes) == {ep.ROUTE_SELF_HOST}",
        "    return False",
        "узел семьи «только у себя» — кандидат API-плана",
    ),
    # --- реестр и память
    (
        EP,
        '                страница_весов\n                if страница_весов\n                else "weights"',
        '                ""\n                if страница_весов\n                else "weights"',
        "узел семьи со своими весами снова не заказывается",
    ),
    (
        EP,
        '    (r"denois\\w*|deblur\\w*|decompression", (RESTORE, V2V_EDIT)),',
        '    (r"denois\\w*|deblur\\w*|decompression", (V2V_EDIT,)),',
        "шумодав не реставрация",
    ),
    (
        EP,
        '    + r"|object-remov\\w*|inpaint\\w*",',
        '    + r"|object-remov\\w*",',
        "inpaint не называет удаление объекта",
    ),
    (
        HN,
        '_GB = re.compile(r"(?<![\\w.])(\\d{1,3}(?:\\.\\d+)?)\\s*(?:gb|гб)?", re.I)',
        '_GB = re.compile(r"(\\d{1,3}(?:\\.\\d+)?)\\s*(?:gb|гб)?", re.I)',
        "«--t5_cpu» снова 5 ГБ",
    ),
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
