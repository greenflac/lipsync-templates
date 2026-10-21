#!/usr/bin/env python3
"""Т1: мутация решений СВЕДЕНИЯ восемнадцатого круга (маршруты × экспертиза) — в обе стороны.

    python scripts/mutate_round18_integration.py          # все мутанты
    python scripts/mutate_round18_integration.py 0 4      # мутанты с 0 по 3

Что мутируется: громкость у подкаста, превращённого в видео (своя запись клиента — звук ролика);
леттеринг моушн-комикса для мастера без титров на нескольких рынках; пометки «по памяти» у цифр,
чьи источники отказал прокси (SCORM, Ofcom, AES TD1004, ASWG-R001).

Устройство — как у `scripts/mutate_round17_integration.py`. ТРИ ИСХОДА (Р1).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_round18_integration",)

CL = "studio/recipes/checklist.py"
R18 = "studio/routes_r18.py"
X18 = "studio/expert_r18.py"
PN = "studio/planner.py"

#: (файл, было, стало, что ломается)
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    (CL, '    if c.video and "audio" in c.spec.inputs and c.spec.audio != "none":\n        return True\n', "",
     "своя запись подкаста не звук ролика"),
    (CL, '    if c.video and "audio" in c.spec.inputs and c.spec.audio != "none":',
     '    if c.video and "audio" in c.spec.inputs:', "беззвучный ролик получает цель громкости"),
    (CL, '    if c.video and "audio" in c.spec.inputs and c.spec.audio != "none":',
     '    if "audio" in c.spec.inputs and c.spec.audio != "none":', "расшифровка без видео получает цель громкости"),
    (R18, "        if x18.textless_needed(spec, text):\n            acc.assembly.append(ASSEMBLY_COMIC_LETTERING)\n", "",
     "комикс для нескольких рынков без леттеринга"),
    (R18, "        if x18.textless_needed(spec, text):\n", "        if True:\n", "леттеринг и для одного рынка"),
    (PN, 'ШАГ_ПРОХОДА: dict[str, tuple[str, ...]] = {"восстановление_лиц": ("реставрация_изображения",)}',
     "ШАГ_ПРОХОДА: dict[str, tuple[str, ...]] = {}", "проход лиц снова отдельным шагом"),
    (PN, '            итог[где] = {**итог[где], "passes": [*(итог[где].get("passes") or []), ш]}\n',
     '            итог[где] = {**итог[где], "passes": [*(итог[где].get("passes") or []), ш]}\n            итог.append(ш)\n',
     "проход и внутри, и отдельно"),
    (PN, "    if not маршрут.шаги and рецепт.assembly and set(рецепт.priors) & r18.ASSEMBLED_CLIP_PRIORS:\n",
     "    if False:\n", "аудиограмма без шагов снова вопрос"),
    (R18, '    if сдача.get("platform") or "srt" in set(сдача.get("format") or ()):\n        return True\n', "",
     "площадка не даёт субтитров аудиограмме"),
    (R18, "        субтитры = podcast_captions(spec, text)\n", "        субтитры = True\n",
     "аудиограмма всегда с расшифровкой"),
    (R18, '    if any(п.get("real") is True and п.get("on_screen") is not False for п in getattr(spec, "people", None) or ()):\n'
          "        return True\n", "", "реальная модель в кадре — база генерируется"),
    (R18, "        return bool(W_INTERP_ASKED.search(_words(spec, text)))\n", "",
     "число кадров в словах снова просьба интерполяции"),
    (R18, '            steps = [s for s in steps if s != "звук_фон"]\n', "", "комикс без звука получает эффекты"),
    (R18, "        if not (голос or spec.audio or", "        if not (spec.audio or", "голос комикса не даёт эффектов"),
    (R18, '    if spec.task == "captions" and "song" not in set(getattr(spec, "audio_content", None) or ()):\n',
     '    if False:\n', "субтитры к записи снова вопрос"),
    (R18, '    if spec.task == "captions" and "song" not in set(getattr(spec, "audio_content", None) or ()):\n',
     '    if spec.task == "captions":\n', "песня с субтитрами — аудиограмма"),
    (R18, '    if spec.task == "captions" and podcast_video(spec, text):\n', "    if False:\n",
     "субтитры к записи без задачи аудиограммы"),
    (R18, '        говорит = {} if _named(spec, "audio_content") else {"audio_content": ("speech",)}\n',
     "        говорит = {}\n", "субтитры к записи без речи — слова решают"),
    (CL, "keeps 64,000 characters (both limits from memory — source not reachable; verify)",
     "keeps 64,000 characters", "SCORM без пометки «по памяти» (EN)"),
    (CL, "64 000 символов (оба предела по памяти — источник недоступен; проверить)", "64 000 символов",
     "SCORM без пометки «по памяти» (RU)"),
    (CL, "than about a sixth of the picture; from memory — source not reachable; verify)",
     "than about a sixth of the picture)", "Ofcom без пометки (EN)"),
    (CL, "шестой части кадра; по памяти — источник недоступен; проверить)", "шестой части кадра)",
     "Ofcom без пометки (RU)"),
    (X18, "(AES TD1004: -16 to -20 LUFS for file playback; from memory — source not reachable; verify)",
     "(AES TD1004: -16 to -20 LUFS for file playback)", "AES TD1004 без пометки (EN)"),
    (X18, "на длинном отрезке игры (по памяти — источник недоступен; проверить)", "на длинном отрезке игры",
     "ASWG-R001 без пометки (RU)"),
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
