#!/usr/bin/env python3
"""Т1: мутация констант-решений ВОСЬМОГО КРУГА (требования до цены, ступени цены) — в обе стороны.

    python scripts/mutate_selection_r8.py          # все мутанты
    python scripts/mutate_selection_r8.py 0 12     # мутанты с 0 по 11 (прогон частями)

Что мутируется: требования заказа в ключе (место до цены, кадр выше 1080p,
частота, язык, правка), голая ставка выше всех ступеней, округление до
минуты и по языкам, картинка по заказанному размеру, частота по заявленному
значению, лицензия как довод только при подтверждённых требованиях, строка о
нескольких языках, выдуманный по spec человек, раздевание и сексуальное с
несовершеннолетним, продукт для детей.

Устройство — как у `scripts/mutate_knowledge_r7.py` (Е1): файл правится на
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
    "studio.tests.test_selection_r8",
    "studio.mcp.tests.test_selection_r8",
    "studio.tests.test_budget_resolution_licence",
    "studio.tests.test_registry_r6",
    "studio.tests.test_integration_r8",
)

PN = "studio/planner.py"
PR = "studio/pricing.py"
CAP = "studio/mcp/capability.py"
PL = "studio/pipeline.py"
SC = "studio/mcp/screen.py"

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- планировщик: требования заказа
    (PN, "        c.requirement_rank,\n        цена,\n", "        цена,\n", "требования заказа уходят из ключа"),
    (PN, "FRAME_REQUIREMENT_MIN = 1440", "FRAME_REQUIREMENT_MIN = 720", "1080p — требование до цены (строже)"),
    (
        PN,
        "    родные = _родные(все) or _родные([f for _, строки in семья for f in строки])",
        "    родные = _родные([*все, *(f for _, строки in семья for f in строки)])",
        "строка семьи опускает вариант со своей строкой о родном выходе",
    ),
    (
        PN,
        "        if строки_свои and min(строки_свои) >= предел:\n            return предел\n",
        "",
        "предел семьи ниже своей строки снова решает",
    ),
    (
        "studio/recipes/apply.py",
        "    return (int(round(asked[0] * k / 8)) * 8, int(round(asked[1] * k / 8)) * 8)",
        "    return (int(asked[0] * k) + 1, int(asked[1] * k))",
        "кадр допущения на пиксель шире 4K",
    ),
    (PN, "FRAME_REQUIREMENT_MIN = 1440", "FRAME_REQUIREMENT_MIN = 4321", "4K — не требование (слабее)"),
    (
        PN,
        "        рамка = REQ_MET if родной is True else REQ_UNKNOWN",
        "        рамка = REQ_MET",
        "кадр: молчание равно родному",
    ),
    (
        PN,
        "        частота = REQ_MET if записано and max(записано) >= просят else REQ_UNKNOWN",
        "        частота = REQ_MET",
        "частота: ниже заказанной равно родной",
    ),
    (
        PN,
        "        for строки in (все, *(rows for _, rows in семья)):",
        "        for строки in (все,):",
        "частота семьи не читается",
    ),
    (
        PN,
        'frozenset({"озвучка", "дубляж", "клонирование_голоса", AVATAR_STEP})',
        "frozenset()",
        "язык перестаёт быть требованием",
    ),
    (
        PN,
        'frozenset({"озвучка", "дубляж", "клонирование_голоса", AVATAR_STEP})',
        'frozenset({"озвучка", "дубляж", "клонирование_голоса", AVATAR_STEP, "липсинк"})',
        "язык — требование и к липсинку",
    ),
    (
        PN,
        "            languages if languages_named else (),",
        "            languages,",
        "язык брифа (не названный) — требование",
    ),
    (
        PN,
        "        правка = REQ_MET if set(edit_intents) <= названы else REQ_UNKNOWN",
        "        правка = REQ_MET",
        "правка по инструкции равна названной",
    ),
    # --- цена
    (PR, "UNTIERED_ABOVE_TOP = 4", "UNTIERED_ABOVE_TOP = 2", "голая ставка снова обгоняет верхнюю ступень"),
    (
        PR,
        "        if нужно is not None and верх is not None and нужно > верх:",
        "        if нужно is not None and верх is not None and нужно > 0:",
        "голая ставка проигрывает и внутри ступеней",
    ),
    (
        PR,
        '    r"rounded up to (?:the )?(?:closest|nearest|next) (?:full )?minute"',
        '    r"rounded up to the (?:closest|nearest|next) (?:full )?minute"',
        "«rounded up to closest minute» снова не узнаётся",
    ),
    (
        PR,
        '    r"rounded up to (?:the )?(?:closest|nearest|next) (?:full )?minute"',
        '    r"per minute|rounded up to (?:the )?(?:closest|nearest|next) (?:full )?minute"',
        "любая цена за минуту — блоками",
    ),
    (
        PN,
        "        jobs=языков if (секунды is not None and языков > 1) else 1,",
        "        jobs=1,",
        "минута округляется по сумме языков, а не в каждом",
    ),
    (
        PN,
        "    if умолчание.tier or умолчание.resolution or not need.resolution or умолчание.rate is None:",
        "    if True:",
        "картинка снова по ступени 1024x768",
    ),
    (
        PN,
        "    if умолчание.tier or умолчание.resolution or not need.resolution or умолчание.rate is None:",
        "    if умолчание.tier or умолчание.resolution or умолчание.rate is None:",
        "ступень по размеру и без заказанного размера",
    ),
    # --- find_models и валидатор
    (
        CAP,
        "    return _ОПРОВЕРЖЕНИЕ.split(без_скобок, maxsplit=1)[0]",
        "    return без_скобок",
        "частота: опровергаемое число читается значением",
    ),
    (
        CAP,
        '    без_скобок = re.sub(r"\\([^)]*\\)?", " ", str(значение or ""))',
        '    без_скобок = str(значение or "")',
        "частота: скобки читаются значением",
    ),
    (
        CAP,
        '        все_подтверждены = all(в["outcome"] == PASS for в in требования.values())',
        "        все_подтверждены = True",
        "лицензия — довод при неподтверждённом языке",
    ),
    (
        CAP,
        '        все_подтверждены = all(в["outcome"] == PASS for в in требования.values())',
        "        все_подтверждены = False",
        "лицензия — никогда не довод",
    ),
    (PL, "    return not language_clause_clear(str(fact.value), шага)", "    return True", "строка о телугу снова судит хинди"),
    (
        PL,
        '    if not all(_НОЛЬ_ПРОВАЛОВ.search(ч) or re.search(r"\\d", ч) for ч in свои):',
        "    if False:",
        "перечень языков снят как «чужой провал»",
    ),
    (
        PL,
        "    if any(_ПРОВАЛ_СЛОВАМИ.search(_НОЛЬ_ПРОВАЛОВ.sub(\" \", ч)) for ч in свои):",
        "    if any(_ПРОВАЛ_СЛОВАМИ.search(ч) for ч in свои):",
        "«0 срывов» читается провалом",
    ),
    # --- просев
    (
        SC,
        "ЛИЧНЫЕ_ГРУППЫ: frozenset[str] = frozenset({ЗАЯВЛЕНИЕ_ПУБЛИЧНОГО, ЗНАМЕНИТОСТЬ_В_РЕКЛАМЕ})",
        "ЛИЧНЫЕ_ГРУППЫ: frozenset[str] = frozenset()",
        "выдуманный по spec снова отклоняется парой слов",
    ),
    (
        SC,
        '                and not знаменитость(м.split(": ", 1)[1])\n',
        "",
        "реальное имя из списка становится выдуманным по spec",
    ),
    (
        SC,
        '        з.get("verdict") in (None, "none") for з in политика.get("claims") or []',
        "        True for з in политика.get(\"claims\") or []",
        "реальное событие не мешает снять отказ",
    ),
    (
        SC,
        "    темы += [м for м in интимные_отказы(строка) if м not in темы]",
        "    темы += []",
        "раздевание снова проходит просев",
    ),
    (
        SC,
        "    if (секс or раздеть) and ребёнок:",
        "    if False:",
        "сексуальное с несовершеннолетним — без отдельного отказа",
    ),
    (
        SC,
        "    return следующее in ДЕТСКИЙ_ПРОДУКТ or any(а in низ for а in АНИМАЦИЯ)",
        "    return False",
        "детский сериал снова «несовершеннолетние»",
    ),
    (
        SC,
        "    if any(о in низ for о in РЕАЛЬНЫЙ_РЕБЁНОК) or any(о in низ for о in ОБОРОТ_КАДРА):",
        "    if False:",
        "реальный ребёнок в кадре проходит как «для детей»",
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
