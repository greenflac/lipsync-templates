#!/usr/bin/env python3
"""Т1: мутация констант-решений ШЕСТНАДЦАТОГО КРУГА (экспертиза моделей и цены) — в обе стороны.

    python scripts/mutate_round16_knowledge.py          # все мутанты
    python scripts/mutate_round16_knowledge.py 0 10     # мутанты с 0 по 9 (прогон частями)

Что мутируется: открытые веса без API-маршрута на своём GPU и оговорка о чувствительной
расшифровке; картинка с надписями по записанной отрисовке текста (условие, кавычки, «за»
только на условии); пространственный звук (поле старше слов); ступень правки видео и
пачка липсинка / аватаров (шаги, края, порог, годность кадра и выхода); серия из ключевых
кадров (порог шотов, поле стиля, слова); рассказчик за кадром; липсинк рисованного
дубляжа как необязательный шаг вне цены.

Устройство — как у `scripts/mutate_round15_knowledge.py`: файл правится на диске,
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

НАБОРЫ = ("studio.tests.test_round16_knowledge",)

X16 = "studio/expert_r16.py"
PN = "studio/planner.py"
RA = "studio/recipes/apply.py"
BS = "studio/brief_spec.py"
CAP = "studio/mcp/capability.py"
AF = "studio/selfrag/attrfamily.py"

#: (файл, было, стало, что ломается)
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- 1. расшифровка
    (X16, '    if hard is None or not getattr(hard, "open_weights", False) or getattr(hard, "self_host", False):',
     "    if True:", "открытые веса без API — снова «кандидата нет»"),
    (X16, '    if hard is None or not getattr(hard, "open_weights", False) or getattr(hard, "self_host", False):',
     "    if hard is None:", "свой GPU включается и без открытых весов"),
    (PN, "        if not найдены and (свой_gpu := x16.open_weights_route(жёсткие)) is not None:",
     "        if False and (свой_gpu := x16.open_weights_route(жёсткие)) is not None:", "повторный поиск на своём GPU не идёт"),
    (PN, "                шаги_на_своём_gpu.add(op.name)\n", "", "шаг на своём GPU без пометки"),
    (X16, '    if getattr(spec, "self_host", None) or getattr(spec, "open_weights", False):\n        return True\n', "",
     "свой GPU не делает материал чувствительным"),
    (X16, r'    r"\bcourt\b|courtroom|', r'    r"courtroom|', "суд словами не чувствителен"),
    (X16, r'    r"|суд\w*|заседани\w*|', r'    r"|заседани\w*|', "суд по-русски не чувствителен"),
    # --- 2. картинка с надписями
    (X16, "    if TEXT_CONDITION in понятые:\n        return True\n", "", "условие заказчика о тексте не читается"),
    (X16, '    return bool(W_TEXT_HEAVY.search(text or "") or QUOTED_TEXT.search(text or ""))',
     '    return bool(W_TEXT_HEAVY.search(text or ""))', "кавычки на любом языке не читаются"),
    (X16, '    return bool(W_TEXT_HEAVY.search(text or "") or QUOTED_TEXT.search(text or ""))',
     '    return bool(W_TEXT_HEAVY.search(text or "") or QUOTED_TEXT.search(text or "") or "a" in text)',
     "любой бриф — картинка с надписями"),
    (X16, r"(?:^|\s)'[^'\n]{2,80}'(?=$|[\s.,!?;:])", r"'[^'\n]{2,80}'", "апострофы — надпись"),
    (PN, "    if x16.TEXT_CONDITION not in заявленные_условия and x16.text_heavy(понято, текст):",
     "    if False:", "план не ставит условие о тексте"),
    (CAP, '            if з == INFO and (за_условия := attrfamily.УСЛОВИЯ.get(у, {}).get("за")) and re.search(',
     '            if False and (за_условия := attrfamily.УСЛОВИЯ.get(у, {}).get("за")) and re.search(',
     "«за» на условии не читается"),
    (AF, r'            r"exceptional\w* (?:typograph|text|at)|specialized for typography|excels? at rendering text"',
     r'            r"specialized for typography|excels? at rendering text"', "«exceptional text rendering» не «за»"),
    (AF, r'            r"|excels? at text|legible, stylized text|exceptionally well in alphabetic|readable text and clean typography"',
     r'            r"|excels? at text|legible, stylized text|exceptionally well in alphabetic|readable text and clean typography|improved"',
     "оговорка «improved» — «за»"),
    # --- 3. пространственный звук
    (X16, "    if isinstance(поле, bool):\n        return поле\n", "", "spatial поля не читается"),
    (X16, '    if not (set(getattr(spec, "outputs", ()) or ()) & AUDIO_OUTPUTS):\n        return False\n', "",
     "пространственный звук без звука на выходе"),
    (X16, r"spatial (?:audio|sound|ambien\w*)|ambisonic\w*|binaural|", r"spatial (?:audio|sound|ambien\w*)|binaural|",
     "амбисоника словами не читается"),
    (X16, r'    r"|объёмн\w* звук\w*|', r'    r"|', "объёмный звук по-русски не читается"),
    # --- 4. ступень правки
    (X16, 'EDIT_TIER_STEPS: frozenset[str] = frozenset({"правка_видео"})', "EDIT_TIER_STEPS: frozenset[str] = frozenset()",
     "правка видео по премиум-ступени"),
    (X16, "    return step in EDIT_TIER_STEPS and objective != QUALITY", "    return step in EDIT_TIER_STEPS",
     "цель «качество» не держит премиум"),
    (X16, "EDIT_TIER_RATIO = 1.5", "EDIT_TIER_RATIO = 1.6", "правка в 1.51 раза дороже — не обмен"),
    (X16, "EDIT_TIER_RATIO = 1.5", "EDIT_TIER_RATIO = 1.0", "копейки — уже обмен"),
    (X16, "    return cheaper_usd > 0 and chosen_usd > EDIT_TIER_RATIO * cheaper_usd",
     "    return chosen_usd > EDIT_TIER_RATIO * cheaper_usd", "бесплатная ступень — обмен"),
    (X16, 'BELOW_FRAME_MARK = "нужен апскейл"', 'BELOW_FRAME_MARK = "нет такой пометки"', "тариф ниже кадра — годен"),
    (X16, '    if getattr(candidate, "below_frame", False):\n        return False\n', "", "кадр ниже по записи — годен"),
    # --- 5. пачка
    (X16, 'BATCH_STEPS: frozenset[str] = frozenset({"липсинк", "говорящий_аватар"})',
     'BATCH_STEPS: frozenset[str] = frozenset({"липсинк"})', "пачка аватаров не дешевеет"),
    (X16, "BATCH_CLIPS_MIN = 3", "BATCH_CLIPS_MIN = 4", "три ролика — не пачка"),
    (X16, "BATCH_CLIPS_MIN = 3", "BATCH_CLIPS_MIN = 2", "два ролика — пачка"),
    (X16, "BATCH_CHEAP_RATIO = 1.5", "BATCH_CHEAP_RATIO = 1.6", "в 1.51 раза дороже — не обмен"),
    (X16, "BATCH_CHEAP_RATIO = 1.5", "BATCH_CHEAP_RATIO = 1.4", "в 1.5 раза дороже — уже обмен"),
    (X16, "    return cheapest_usd > 0 and chosen_usd > BATCH_CHEAP_RATIO * cheapest_usd",
     "    return chosen_usd > BATCH_CHEAP_RATIO * cheapest_usd", "бесплатный «дешёвый» — обмен"),
    (X16, "    return step in BATCH_STEPS and int(clips or 0) >= BATCH_CLIPS_MIN and objective != QUALITY",
     "    return step in BATCH_STEPS and int(clips or 0) >= BATCH_CLIPS_MIN", "«качество» на пачке не держит выбор"),
    # --- 6. серии
    (X16, "KEY_VISUAL_SHOTS_MIN = 4", "KEY_VISUAL_SHOTS_MIN = 5", "четыре шота — не серия ключевых кадров"),
    (X16, "KEY_VISUAL_SHOTS_MIN = 4", "KEY_VISUAL_SHOTS_MIN = 3", "три шота — серия ключевых кадров"),
    (X16, '    return "style" in {str(к).lower() for к in (getattr(spec, "consistency", None) or ())}', "    return True",
     "любой многошотовый ролик — ключевые кадры"),
    (X16, '    if "consistency" in dict(getattr(spec, "source", {}) or {}):\n        return False\n', "",
     "названное поле стиля не старше слов"),
    (X16, r'    r"\bseries\b|\bepisodes?\b|explainer\w*|\bexplains?\b|', r'    r"\bepisodes?\b|\bexplains?\b|',
     "«explainer series» словами не читается"),
    (BS, '        and not говорят_в_кадре(spec, текст)\n', "", "ведущий в кадре — тоже ключевые кадры без губ"),
    (BS, r'    r"voice-?over|narrat\w*|off-?screen|озвучк\w*|закадров\w*|за кадром|рассказчик\w*|диктор\w*|配音", re.I',
     r'    r"voice-?over|narrat\w*|off-?screen|озвучк\w*|закадров\w*|диктор\w*|配音", re.I', "«голос за кадром» — губы в кадре"),
    # --- 7. рисованный дубляж
    (X16, '    return getattr(spec, "task", None) == "dub-translate" and drawn and getattr(spec, "lipsync", None) is not True',
     '    return getattr(spec, "task", None) == "dub-translate" and drawn', "липсинк заказан — всё равно необязателен"),
    (X16, '    return getattr(spec, "task", None) == "dub-translate" and drawn and getattr(spec, "lipsync", None) is not True',
     "    return False", "липсинк рисованного снова в цене"),
    (RA, "                optional.append(x16.OPTIONAL_LIPS_STEP)\n", "", "необязательный шаг не передан плану"),
    (PN, '                условные.add(строка["step"])\n                строка["conditional"] = True\n                строка["optional"] = True\n',
     '                строка["optional"] = True\n', "необязательный шаг входит в цену ролика"),
    (PN, '                **({"optional": True} if op.name in getattr(рецепт, "optional", ()) else {}),\n', "",
     "отдельная цена улучшения без пометки"),
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
