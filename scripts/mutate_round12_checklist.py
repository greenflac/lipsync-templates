#!/usr/bin/env python3
"""Т1: мутация констант-решений ДВЕНАДЦАТОГО КРУГА — в обе стороны.

    python scripts/mutate_round12_checklist.py          # все мутанты
    python scripts/mutate_round12_checklist.py 0 6      # мутанты с 0 по 5 (прогон частями)

Что мутируется: наборы письменностей длинного хвоста чек-листа (подмена букв,
брахмические, без пробелов, локальные формы кириллицы), частоты DCP, потолок
коротких вертикальных видео, платформы не CUDA; бэкенд своего GPU не NVIDIA
(имя карты -> ROCm/XPU, атрибут базы, порядок, слово бэкенда без своего
запуска, платформа в spec, ранг в отборе, строка шага).

Устройство — как у `scripts/mutate_round11.py`: файл правится на диске, набор
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

НАБОРЫ = ("studio.tests.test_checklist_r12",)

CL = "studio/recipes/checklist.py"
HN = "studio/hardneed.py"
BS = "studio/brief_spec.py"
PN = "studio/planner.py"

_GLYPH = '{"ru", "uk", "be", "bg", "sr", "mk", "kk", "ky", "tg", "mn", "el", "hy", "ka"}'
_INDIC = '{"hi", "mr", "ne", "sa", "bn", "as", "pa", "gu", "or", "ta", "te", "kn", "ml", "si"}'
_SEA = 'SEA_LANGS: frozenset[str] = frozenset({"th", "lo", "km", "my"})'
_LOCL = 'LOCL_LANGS: frozenset[str] = frozenset({"bg", "sr", "mk"})'
_DCP = "DCP_FPS: frozenset[int] = frozenset({24, 48})"
_NON = 'NON_NVIDIA_PLATFORMS: frozenset[str] = frozenset({"rocm", "xpu", "apple-silicon"})'
_ATTRS = 'GPU_BACKEND_ATTRS: dict[str, str] = {"rocm": "rocm_inference", "xpu": "intel_xpu_inference"}'
_ORDER = "BACKEND_ORDER: dict[str, int] = {BACKEND_YES: 0, BACKEND_UNKNOWN: 1, BACKEND_NO: 2}"

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    (CL, _GLYPH, _GLYPH.replace(', "el"', ""), "греческий текст генерируется"),
    (CL, _GLYPH, _GLYPH.replace('"ka"}', '"ka", "de"}'), "немецкий — «подмена букв»"),
    (CL, _INDIC, _INDIC.replace('"ta", ', ""), "тамильский без сложной вёрстки"),
    (CL, _INDIC, _INDIC.replace('"si"}', '"si", "ur"}'), "урду — брахмическое"),
    (CL, _SEA, _SEA.replace('"km", ', ""), "кхмерский рвётся внутри слов"),
    (CL, _SEA, _SEA.replace('"my"}', '"my", "id"}'), "индонезийский без пробелов"),
    (CL, _LOCL, _LOCL.replace(', "mk"', ""), "македонский без локальных форм"),
    (CL, _LOCL, _LOCL.replace('"mk"}', '"mk", "ru"}'), "русский — «локальные формы»"),
    (CL, _DCP, _DCP.replace("24, 48", "24"), "48 к/с не DCP"),
    (CL, _DCP, _DCP.replace("24, 48", "24, 25, 48"), "25 к/с — DCP"),
    (CL, "SOCIAL_SHORT_MAX_S = 180", "SOCIAL_SHORT_MAX_S = 181", "181 с — ещё короткое видео"),
    (CL, "SOCIAL_SHORT_MAX_S = 180", "SOCIAL_SHORT_MAX_S = 179", "180 с — уже длинное"),
    (CL, _NON, _NON.replace('"xpu", ', ""), "Intel без ноты бэкенда"),
    (HN, '    if AMD_GPU.search(низ):\n        return "rocm"\n', "", "AMD не ROCm"),
    (HN, '    if INTEL_GPU.search(низ):\n        return "xpu"\n', "", "Intel не XPU"),
    (HN, _ATTRS, _ATTRS.replace('"rocm_inference"', '"rocm"'), "ROCm читает чужой атрибут"),
    (HN, _ORDER, _ORDER.replace("BACKEND_YES: 0, BACKEND_UNKNOWN: 1", "BACKEND_YES: 1, BACKEND_UNKNOWN: 0"),
     "молчание старше записи"),
    (HN, '    бэкенд = gpu_backend(gpu) or (gpu_backend(низ) if свой else "")',
     "    бэкенд = gpu_backend(gpu) or gpu_backend(низ)", "слово бэкенда без своего запуска"),
    (HN, '    "rx-7900-xtx": 24.0,', '    "rx-7900-xtx": 20.0,', "память RX 7900 XTX"),
    (BS, "    elif gpu and hn.gpu_backend(str(gpu)):", "    elif False:", "spec без платформы ROCm"),
    (BS, '        if свой.get("platform") in hn.GPU_BACKEND_ATTRS:', "        if False:", "жёсткое без бэкенда"),
    (PN, "        if hard.gpu_backend:\n            бэк, нота_бэка", "        if False:\n            бэк, нота_бэка",
     "отбор не смотрит бэкенд"),
    (PN, "        if выбран is not None and бэкенд:", "        if False:", "шаг без строки бэкенда"),
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
