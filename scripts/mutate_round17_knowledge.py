#!/usr/bin/env python3
"""Т1: мутация констант-решений СЕМНАДЦАТОГО КРУГА (специальные знания и цены) — в обе стороны.

    python scripts/mutate_round17_knowledge.py          # все мутанты
    python scripts/mutate_round17_knowledge.py 0 10     # мутанты с 0 по 9 (прогон частями)

Что мутируется: тифлокомментарий (поле доступности старше слов, доля пауз, задачи пакета,
голос по паузам, одна расшифровка, порядок шагов); смешение языков (тег mul, слова, одна
дорожка в цене); условия провайдера (свой GPU, загрузка, обучение, дети, область, слова,
исключение суда); выбор моментов и пересказ (задача, слова, голос по длине пересказа,
правка без генерации); перевод частоты кадров (семейства, рынки 60 Гц, площадки);
разделение на стемы (поле старше слов, слова); размытие фона (правка, цель, маска вместо
генеративной правки, псевдоним).

Устройство — как у `scripts/mutate_round16_knowledge.py`: файл правится на диске,
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

НАБОРЫ = ("studio.tests.test_round17_knowledge",)

X17 = "studio/expert_r17.py"
CL = "studio/recipes/checklist.py"
RA = "studio/recipes/apply.py"
PN = "studio/planner.py"
BS = "studio/brief_spec.py"

#: (файл, было, стало, что ломается)
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- 1. тифлокомментарий
    (X17, "AD_GAP_SHARE = 0.15", "AD_GAP_SHARE = 0.2", "доля пауз больше — голос дороже"),
    (X17, "AD_GAP_SHARE = 0.15", "AD_GAP_SHARE = 1.0", "голос по всему хронометражу"),
    (X17, 'AD_TASKS: frozenset[str | None] = frozenset({"captions", "transcribe"})',
     'AD_TASKS: frozenset[str | None] = frozenset({"captions"})', "пакет на расшифровке без голоса"),
    (X17, 'AD_TASKS: frozenset[str | None] = frozenset({"captions", "transcribe"})',
     'AD_TASKS: frozenset[str | None] = frozenset({"captions", "transcribe", "dub-translate"})', "голос и на дубляже"),
    (X17, '    поле = sf.accessibility(spec, "audio-description")\n    if поле is not None:\n        return поле\n', "",
     "поле доступности не старше слов"),
    (X17, '    if not ({"video"} & (_inputs(spec) | _outputs(spec))):\n        return False\n', "",
     "тифлокомментарий без картинки"),
    (X17, r'    r"|for (?:the )?blind|visually impaired|тифлокомментар\w*|', r'    r"|for (?:the )?blind|visually impaired|',
     "тифлокомментарий по-русски не читается"),
    (X17, '        float(з.get("duration_s") or 0.0) * int(з.get("count") or 1)', '        float(з.get("duration_s") or 0.0)',
     "длина материала без числа серий"),
    (RA, '        notes["расшифровка"] = x17.NOTE_AD_TRANSCRIPT[0]\n', "", "одна расшифровка не названа"),
    (RA, '        step_seconds["озвучка"] = (gap, gap)\n', "", "голос по всей длине"),
    (RA, "    if x17.ad_package(spec, text) and runtime and acc.prior(", "    if False and acc.prior(", "голос пакета не добавлен"),
    (PN, '        if set(рецепт.recipes) & x17.ROUTE_ORDER_RECIPES:', '        if False:', "порядок шагов пакета не по маршруту"),
    (X17, 'ROUTE_ORDER_RECIPES: frozenset[str] = frozenset({"accessibility_package", "series_recap"})',
     'ROUTE_ORDER_RECIPES: frozenset[str] = frozenset({"series_recap"})', "голос раньше расшифровки"),
    # --- 2. смешение языков
    (X17, "    if MULTIPLE_LANGUAGES_TAG in теги:\n        return True\n", "", "тег mul не читается"),
    (X17, r'    r"code[- ]?switch\w*|code[- ]?mix\w*|spanglish|', r'    r"code[- ]?switch\w*|code[- ]?mix\w*|', "spanglish не читается"),
    (X17, r"|вперемешку|", r"|", "вперемешку не читается"),
    (X17, r'    r"|switch\w* (?:between )?languages|mix\w* (?:of )?languages|',
     r'    r"|switch\w* (?:between )?languages|mix\w*|', "любое «mix» — смешение языков"),
    (PN, "            if x17.code_switching(понято, текст):\n                return 1\n", "", "смешанная дорожка по языкам"),
    (CL, "    return bool(c.jobs & (SPEECH_MAKE | {\"transcribe\", \"captions\", \"shorts\", \"lipsync\", \"avatar\"})) and x17.code_switching(",
     "    return x17.code_switching(", "оговорка без речевого шага"),
    # --- 3. условия провайдера
    (X17, '    if sh and (not isinstance(sh, Mapping) or sh.get("enabled", True) is not False):\n        return False\n', "",
     "свой GPU — тоже загрузка"),
    (X17, '    if not (_inputs(spec) & UPLOAD_INPUTS):\n        return False\n', "", "без принесённого — тоже загрузка"),
    (X17, '    if getattr(spec, "training_use", None) is True:\n        return True\n', "", "обучение не читается"),
    (X17, 'CONFIDENTIAL_DOMAINS: tuple[str, ...] = ("corporate", "health-advertising", "financial-advertising")',
     'CONFIDENTIAL_DOMAINS: tuple[str, ...] = ("health-advertising", "financial-advertising")', "корпоративное не конфиденциально"),
    (X17, 'CONFIDENTIAL_DOMAINS: tuple[str, ...] = ("corporate", "health-advertising", "financial-advertising")',
     'CONFIDENTIAL_DOMAINS: tuple[str, ...] = ("corporate", "health-advertising", "financial-advertising", "entertainment")',
     "развлекательное конфиденциально"),
    (X17, 'UPLOAD_INPUTS: frozenset[str] = frozenset({"video", "audio", "photo"})',
     'UPLOAD_INPUTS: frozenset[str] = frozenset({"audio", "photo"})', "видео не загружается"),
    (X17, r'    r"|\bnda\b|confidential|', r'    r"|confidential|', "nda не читается"),
    (X17, r'    r"|клиентск\w*|', r'    r"|', "клиентское по-русски не читается"),
    (X17, '    if any(isinstance(п, Mapping) and п.get("minor") is True', '    if False and any(isinstance(п, Mapping) and п.get("minor") is True',
     "дети не читаются"),
    (CL, "    return bool(c.steps or c.jobs) and not _confidential_transcription(c) and x17.provider_data_terms(",
     "    return bool(c.steps or c.jobs) and x17.provider_data_terms(", "суд дважды"),
    # --- 4. пересказ
    (X17, 'RECAP_TASKS: frozenset[str] = frozenset({"cut-to-shorts"})', "RECAP_TASKS: frozenset[str] = frozenset()",
     "нарезка — не пересказ"),
    (X17, r'    r"\brecaps?\b|\bhighlights\b|highlight (?:reel|video|cut|clips?)|',
     r'    r"\brecaps?\b|highlight\w*|', "«highlight» глаголом — пересказ"),
    (X17, r'    r"|нарезк\w*|', r'    r"|', "нарезка по-русски не читается"),
    (X17, '        return звук == "voiceover"', '        return True', "любой звук — диктор"),
    (X17, '    if spec.duration_s:\n        return float(spec.duration_s)\n    return None', '    return 7200.0',
     "диктор по длине сериала"),
    (X17, "    if getattr(spec, \"edit\", None) or getattr(spec, \"edit_target\", None) is not None:\n        return False\n", "",
     "названная правка — пересказ"),
    (RA, '        steps = _replace_step(steps, "правка_видео", "расшифровка")\n', "", "пересказ генерирует правкой"),
    (RA, '    if x17.recap_narration(spec, text) and vo_s and acc.prior("series_recap", "recap_short_vo"):',
     '    if x17.recap_narration(spec, text) and acc.prior("series_recap", "recap_short_vo"):', "диктор без длины пересказа"),
    # --- 5. частота кадров
    (X17, '    if 23.9 <= f <= 24.01:\n        return FAMILY_FILM\n', "", "23,976 — не кино"),
    (X17, '    if f in (25.0, 50.0):', '    if f in (25.0, 50.0, 30.0):', "30 — PAL"),
    (X17, '    {"US", "CA", "MX", "BR", "JP",', '    {"CA", "MX", "BR", "JP",', "США не 60 Гц"),
    (X17, '    {"US", "CA", "MX", "BR", "JP",', '    {"US", "CA", "MX", "BR", "JP", "DE",', "Германия 60 Гц"),
    (X17, 'CONVERSION_PLATFORMS: tuple[str, ...] = ("broadcast", "cinema", "streaming-premium")',
     'CONVERSION_PLATFORMS: tuple[str, ...] = ("broadcast", "cinema", "streaming-premium", "youtube")', "YouTube в частоте рынка"),
    (X17, 'CONVERSION_PLATFORMS: tuple[str, ...] = ("broadcast", "cinema", "streaming-premium")',
     'CONVERSION_PLATFORMS: tuple[str, ...] = ("cinema", "streaming-premium")', "эфир не в частоте рынка"),
    (X17, '    if getattr(spec, "fps", None):\n        return fps_family(spec.fps)\n', "", "поле fps не читается"),
    (X17, '        return цель not in вход or len(вход) > 1', '        return True', "то же семейство — перевод"),
    (X17, r'    r"|чересстроч\w*|', r'    r"|', "чересстрочный по-русски не читается"),
    # --- 6. стемы
    (X17, "    поле = sf.stems(spec)\n    if поле is not None:\n        return поле\n", "", "поле стемов не старше слов"),
    (X17, r'    r"karaoke|instrumental version|', r'    r"instrumental version|', "караоке не читается"),
    (X17, r"|караоке|минусовк\w*|", r"|караоке|", "минусовка не читается"),
    (X17, r'(?:vocals?|dialogue|music|singing)\b|separat\w* (?:the )?(?:vocals?|voice|dialogue|music) from"',
     r'(?:vocals?|dialogue|music|singing)\b|separat\w* (?:the )?(?:\w+ )?(?:vocals?|voice|dialogue|music)"',
     "«отдельный голос» — стемы"),
    (X17, r'|разделить на (?:стемы|дорожки)|\bстем(?:ы|ам|ах|ов)?\b",', r'|разделить на (?:стемы|дорожки)|стем\w*",',
     "«система» — стемы"),
    # --- 7. размытие фона
    (X17, "    if EDIT_BLUR_BACKGROUND in правки:\n        return True\n", "", "правка размытия не читается"),
    (X17, '    if цель is not None and цель != "background":\n        return False\n', "", "цель «человек» — размытие фона"),
    (X17, '    if правки and getattr(spec, "source", {}).get("edit") == "spec":\n        return False\n', "",
     "названная другая правка — размытие"),
    (X17, r'    r"|боке|размы\w* (?:\w+ )?(?:фон|задн\w* план)\w*|', r'    r"|боке|', "размыть фон по-русски не читается"),
    (X17, '    if "video" not in _inputs(spec) or getattr(spec, "task", None) not in ("video-edit", "edit"):',
     '    if "video" not in _inputs(spec):', "размытие и на дубляже"),
    (RA, '        steps = _replace_step(steps, "правка_видео", "удаление_фона_видео")\n', "", "генеративная правка вместо маски"),
    (BS, '    "bokeh": EDIT_BLUR_BACKGROUND,\n', "", "псевдоним bokeh не принят"),
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
