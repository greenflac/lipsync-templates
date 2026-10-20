#!/usr/bin/env python3
"""Т1: мутация констант-решений ЧЕТЫРНАДЦАТОГО КРУГА (модели, знания, политика) — в обе стороны.

    python scripts/mutate_round14_models.py          # все мутанты
    python scripts/mutate_round14_models.py 0 10     # мутанты с 0 по 9 (прогон частями)

Что мутируется: цель правки надписи (лицо как объект, а не человек в кадре),
картиночная замена лица над кадрами видео и счёт снимков, заявления до заметок,
правила чек-листа круга (голограмма на чёрном, синтетический ведущий, датасет
замены лиц, свет по шотам, дубль против прогона ВЫБРАННОЙ модели), прозрачный
фон против прозрачного экрана, дотяг апскейлера (проверенный предел, покадровый
апскейлер, порядок), апскейлер для альфы только при заказанной альфе и узкая
дверь синтетического ведущего (правило, поля заявлений, люди, слова выдумки,
запреты, подключение в сервере).

Устройство — как у `scripts/mutate_round13_models.py`: файл правится на диске,
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

НАБОРЫ = ("studio.tests.test_round14_models",)

EI = "studio/edit_intent.py"
BS = "studio/brief_spec.py"
CL = "studio/recipes/checklist.py"
RA = "studio/recipes/apply.py"
UR = "studio/upscale_reach.py"
PN = "studio/planner.py"
SP = "studio/synthetic_presenter.py"
SV = "studio/mcp/server.py"

_ORDER = "REACH_ORDER: dict[str, int] = {REACH_YES: 0, REACH_UNTESTED: 1, REACH_UNKNOWN: 2, REACH_BELOW: 3}"
_NEWS = 'PRESENTER_NEWS_TYPES: frozenset[str] = frozenset({"news", "real_event"})'
_JOBS = 'FACE_SWAP_JOBS: frozenset[str] = frozenset({"char_replace", "face_swap"})'
_SP_NEWS = 'NEWS_TYPES: frozenset[str] = frozenset({"news", "real_event"})'
_ROUTE = '        if "photo" in входы and "video" not in выходы and ("video" not in входы or "image" in выходы):'

#: (файл, было, стало, что ломается)
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- цель правки решает
    (EI, "    return bool(TEXT_EDIT_WORDS.search(низ)) and not PERSON_EDIT.search(низ)",
     "    return bool(TEXT_EDIT_WORDS.search(низ)) and not PERSON_WORDS.search(низ)", "человек в кадре снова держит задачу"),
    (EI, "|logo text|typo|spelling|misspelling)", "|logo text)", "опечатка на доске — не правка надписи"),
    # --- датасет замены лиц
    (BS, "FACE_SWAP_BATCH_MIN = 10", "FACE_SWAP_BATCH_MIN = 11", "десять снимков — не набор"),
    (BS, "FACE_SWAP_BATCH_MIN = 10", "FACE_SWAP_BATCH_MIN = 9", "девять снимков — набор"),
    (BS, _ROUTE, '        if "video" not in входы and "photo" in входы and "video" not in выходы:',
     "кадры видео снова в замену персонажа"),
    (BS, _ROUTE, '        if "photo" in входы and ("video" not in входы or "image" in выходы):',
     "заказанное видео с кадрами — в картиночную"),
    (BS, '                штук={"замена_лица_изображения": штук} if штук else {},', "                штук={},",
     "набор считается одним снимком"),
    (BS, 'if str(з.get("kind")) in ("photo", "image")]', 'if str(з.get("kind")) == "image"]', "снимки входа не считаются"),
    (BS, '        поля["claims"] = tuple(dict(з) for з in _список(raw["claims"]) if isinstance(з, Mapping))',
     '        поля["claims"] = ()', "заявления не доходят до заметок"),
    # --- правила чек-листа
    (CL, "FACE_SWAP_DATASET_MIN = 20", "FACE_SWAP_DATASET_MIN = 21", "двадцать — не датасет"),
    (CL, "FACE_SWAP_DATASET_MIN = 20", "FACE_SWAP_DATASET_MIN = 19", "девятнадцать — датасет"),
    (CL, "RELIGHT_SERIES_MIN_SHOTS = 2", "RELIGHT_SERIES_MIN_SHOTS = 3", "два шота — не серия света"),
    (CL, "RELIGHT_SERIES_MIN_SHOTS = 2", "RELIGHT_SERIES_MIN_SHOTS = 1", "один шот — серия света"),
    (CL, _NEWS, _NEWS.replace('"news", ', ""), "новости — не текст ведущего"),
    (CL, _NEWS, _NEWS.replace('"real_event"}', '"real_event", "product"}'), "реклама товара — текст ведущего"),
    (CL, _JOBS, _JOBS.replace(', "face_swap"', ""), "картиночная замена лица без оговорки датасета"),
    (CL, _JOBS, _JOBS.replace('"face_swap"}', '"face_swap", "t2i"}'), "генерация картинок — датасет замены лиц"),
    (CL, '    "замена_лица_изображения": "face_swap",\n', "", "шаг замены лица без работы"),
    (CL, "        str(з.get(\"type\") or \"\").lower() in PRESENTER_NEWS_TYPES and з.get(\"own_brand\") is True",
     "        str(з.get(\"type\") or \"\").lower() in PRESENTER_NEWS_TYPES", "чужая программа — синтетический ведущий"),
    (CL, '        return {"seconds": f"{шот:g}"} if шот > прогон else None',
     '        return {"seconds": f"{шот:g}"} if шот >= прогон else None', "дубль ровно в прогон — несколько прогонов"),
    (CL, '        return {"seconds": f"{шот:g}"} if шот > прогон else None',
     '        return {"seconds": f"{шот:g}"} if шот > прогон + 1 else None', "дубль чуть длиннее прогона — один прогон"),
    (CL, "{min(прогоны):g}", "{max(прогоны):g}", "предел — самый длинный прогон"),
    (CL, "|transparent (?:led|oled|lcd|screen|display|film|glass display)", "", "прозрачный LED — не голограмма"),
    (RA, "| set(extra_priors)", "", "приоры плана не доходят до заметок"),
    # --- прозрачный фон против прозрачного экрана и предмета
    (RA, "    if any(checklist.W_HOLOGRAM.search(у) for у in слова) and not any(ALPHA_EXPLICIT.search(у) for у in слова):",
     "    if False:", "голограмма просит альфу"),
    (RA, "    if any(checklist.W_HOLOGRAM.search(у) for у in слова) and not any(ALPHA_EXPLICIT.search(у) for у in слова):",
     "    if any(checklist.W_HOLOGRAM.search(у) for у in слова):", "явная альфа на голограмме не слышна"),
    (RA, "|стекл|флакон|бутылк|", "|стекл|бутылк|", "прозрачный флакон — прозрачный фон"),
    # --- дотяг апскейлера
    (UR, _ORDER, _ORDER.replace("REACH_UNTESTED: 1, REACH_UNKNOWN: 2", "REACH_UNTESTED: 2, REACH_UNKNOWN: 1"),
     "по схеме — ниже молчания"),
    (UR, _ORDER, _ORDER.replace("REACH_YES: 0, REACH_UNTESTED: 1", "REACH_YES: 1, REACH_UNTESTED: 0"),
     "по схеме — выше записи"),
    (UR, 'TESTED_ATTRIBUTES: frozenset[str] = frozenset({"tested_output_ceiling"})',
     'TESTED_ATTRIBUTES: frozenset[str] = frozenset({"tested_max"})', "проверенный предел не читается"),
    (UR, "            ниже = [(т, у) for т, у in проверено if т < target_short]",
     "            ниже = [(т, у) for т, у in проверено if т <= target_short]", "проверено ровно на кадре — «ниже»"),
    (UR, "            if video and (кадрами := per_frame(rows)):", "            if (кадрами := per_frame(rows)):",
     "покадровый — и для картинки"),
    (UR, "            if video and (кадрами := per_frame(rows)):", "            if False and (кадрами := per_frame(rows)):",
     "покадровый апскейлер на видео — по записи"),
    (UR, 'ALPHA_ROW_ATTRIBUTES: frozenset[str] = frozenset({"best_for", "positioning", "alpha_output"})',
     'ALPHA_ROW_ATTRIBUTES: frozenset[str] = frozenset({"positioning", "alpha_output"})', "назначение альфы не читается"),
    (PN, '                по_имени.get(fold(имя_дотяга), []), цель_апскейла, исходник_апскейла, video=op.name == "апскейл"',
     "                по_имени.get(fold(имя_дотяга), []), цель_апскейла, исходник_апскейла, video=False",
     "шаг видео не говорит, что он видео"),
    (PN, "        if ключ in для_альфы and not все_для_альфы:", "        if False:", "апскейлер для альфы на непрозрачном"),
    (PN, "            alpha_wanted=rc.wants_alpha(понято, brief),", "            alpha_wanted=False,",
     "заказанная альфа не доходит"),
    # --- синтетический ведущий
    (SP, 'LIFTED_RULE = "news_brand"', 'LIFTED_RULE = "public_statement"', "дверь не для своего бренда"),
    (SP, _SP_NEWS, _SP_NEWS.replace('"news", ', ""), "новости — не программа"),
    (SP, '    return bool(people) and all(п.get("real") is False for п in people)',
     '    return bool(people) and any(п.get("real") is False for п in people)', "один вымышленный среди людей — проходит"),
    (SP, '            if з.get("own_brand") is not True:', "            if False:", "чужой бренд проходит"),
    (SP, '    if any(з.get("fabricated") is not False for з in новости):', '    if any(з.get("fabricated") is True for з in новости):',
     "неизвестно, выдумано ли, — проходит"),
    (SP, ' or FABRICATED_WORDS.search(str(brief or ""))', "", "слова выдумки не закрывают дверь"),
    (SP, '    if broadcast_marks.BROADCASTER.search(str(brief or "")) or ', "    if ", "чужой канал в брифе проходит"),
    (SP, '    if text_screen.get("banned") or text_screen.get("injection"):', "    if False:", "запрет текста снимается"),
    (SP, "    if len(list(screened.get(\"banned\") or [])) != len(отказаны)", "    if False", "лишний запрет снимается"),
    (SV, "    просев, политика = synthetic_presenter.apply(синтетик, просев, политика)\n", "", "дверь не подключена"),
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
