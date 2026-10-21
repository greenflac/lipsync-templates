#!/usr/bin/env python3
"""Т1: мутация решений недостающих маршрутов семнадцатого круга — в обе стороны.

    python scripts/mutate_round17_routes.py          # все мутанты
    python scripts/mutate_round17_routes.py 0 10     # мутанты с 0 по 9

Что мутируется: вшитые субтитры (поле, слова, мягкая дорожка, цены перевода и OCR, речь, дубляж),
клип исполнителя (шоты с губами, ноль, `lipsync`, референс, аватар вместо губ), 3D-реконструкция
(поле, формат сплата, слова, что снимается, пробел цены), замена человека целиком (поле, названная
правка, слова, референс), пачка UGC (ведущий, порог, принесённые кадры товара, слова), озвучка без
звука (задачи, `voiceover: false`, своё видео), согласованные учения (только internal, свой сотрудник,
«новости», политика словами и в claims, применение в сервере), поля в вопросе и в черновике, правила
оговорок и вызов маршрутов из рецептов.

Устройство — как у `scripts/mutate_round16_integration.py`. ТРИ ИСХОДА (Р1).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_round17_routes",)

R = "studio/routes_r17.py"
CS = "studio/consented_simulation.py"
BS = "studio/brief_spec.py"
RA = "studio/recipes/apply.py"
CL = "studio/recipes/checklist.py"
PN = "studio/planner.py"
SV = "studio/mcp/server.py"

#: (файл, было, стало, что ломается)
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # 7. озвучка без звука
    (R, 'NARRATION_TASKS: frozenset[str | None] = frozenset({None, "generate", "animate", "r2v", "video-edit", "turntable"})',
     'NARRATION_TASKS: frozenset[str | None] = frozenset({None, "animate", "r2v", "video-edit", "turntable"})',
     "объясняющий ролик generate без озвучки"),
    (R, '    if getattr(spec, "voiceover", None) is False:\n        return False\n    return (\n', "    return (\n",
     "voiceover: false не отменяет audio_content speech"),
    (R, '    if "video" in set(spec.inputs) and spec.voiceover is not True and spec.audio != "voiceover":\n        return spec\n',
     "", "речь своего видео читается закадром"),
    (BS, "    spec = r17.with_narration(spec)\n", "", "озвучка не входит в выходы"),
    # 1. вшитые субтитры
    (R, '        return поле == "burned"\n', "        return True\n", "subtitles none считается вшитыми"),
    (R, "    return bool(W_BURNED_SUBS.search(слова))\n\n\ndef soft_subtitles",
     "    return False\n\n\ndef soft_subtitles", "слова о вшитых субтитрах не читаются"),
    (R, "    if W_ADD_SUBS.search(слова) and not W_OLD_SUBS.search(слова):\n        return False\n", "",
     "«добавьте вшитые субтитры» читается как старые вшитые"),
    (R, "    return bool(площадки) and площадки <= SOFT_SUB_PLATFORMS\n", "    return False\n",
     "площадка с дорожкой не даёт мягких субтитров"),
    (R, 'SOFT_SUB_FORMATS: frozenset[str] = frozenset({"srt"})', "SOFT_SUB_FORMATS: frozenset[str] = frozenset()",
     "сдача srt не мягкая дорожка"),
    (R, '    return bool(площадки) and площадки <= SOFT_SUB_PLATFORMS\n', '    return bool(площадки)\n',
     "тикток получает мягкие субтитры"),
    (R, "TRANSLATE_USD_PER_M_CHARS = 20.0", "TRANSLATE_USD_PER_M_CHARS = 25.0", "цена перевода не записанная"),
    (R, "OCR_USD_PER_MIN = 0.15", "OCR_USD_PER_MIN = 0.12", "цена OCR не записанная"),
    (R, "CHARS_PER_SECOND = 15.0", "CHARS_PER_SECOND = 14.0", "знаков в секунде не как у плановщика"),
    (R, '        return "speech" in set(spec.audio_content)\n', "        return True\n", "расшифровка без речи"),
    (R, '                steps = [*steps, "правка_видео"] if "правка_видео" not in steps else steps\n', "",
     "дубляж оставляет старые субтитры"),
    (BS, "    spec = r17.with_subtitle_edit(spec, текст)\n", "", "правка не снимает текст"),
    (BS, '                ошибки.append(f"spec.inputs[{i}].subtitles: {з} not in {\', \'.join(INPUT_SUBTITLES)}")\n',
     "                pass\n", "чужое значение subtitles молчит"),
    # 2. клип исполнителя
    (R, "    поёт = всего if названо is None else min(int(названо), всего)\n", "    поёт = всего\n",
     "performer_shots не делит шоты"),
    (R, '    if getattr(spec, "performer_shots", None) == 0:\n        return False\n', "",
     "ноль шотов с исполнителем — всё равно клип исполнителя"),
    (R, "    if getattr(spec, \"lipsync\", None) is not None:\n        return bool(spec.lipsync)\n", "",
     "lipsync: false не убирает губы"),
    (R, "            стиллов = (0 if свои_фото else 1) + прочие\n", "            стиллов = прочие\n",
     "без фото исполнителя нет референса"),
    (PN, "    if r17.PERFORMER_REF_STEP in имена:\n        return имена\n", "",
     "губы и оживление сворачиваются в аватар"),
    (BS, "    _поля_r17(raw, поля, ошибки)\n", "", "поля семнадцатого круга не разбираются"),
    # 3. 3D-реконструкция
    (R, "    if isinstance(поле, bool):\n        return поле\n    форматы", "    if поле:\n        return True\n    форматы",
     "reconstruct_3d: false уступает словам"),
    (R, "    if форматы & set(SPLAT_FORMATS):\n        return True\n", "", "формат сплата не решает"),
    (R, "    return bool(W_SCENE_3D.search(_words(spec, text)))\n", "    return False\n", "слова 3D-тура не читаются"),
    (R, '    {"оживление", "генерация_видео", "перенос_движения", "оборот_360", "модель_3d", "видео_по_референсу", "генерация_изображения"}',
     '    {"генерация_видео", "перенос_движения", "оборот_360", "модель_3d", "видео_по_референсу", "генерация_изображения"}',
     "видеомодель оживляет снимки вместо сплата"),
    (R, "            acc.assembly.append(GAP_SPLAT_COMPUTE)\n", "", "пробел цены сплата не назван"),
    # 5. замена человека целиком
    (R, "    if EDIT_REPLACE_PERSON in set(spec.edit):\n        return True\n", "", "replace-person не решает"),
    (R, '    if _named(spec, "edit") and spec.edit:\n        return False\n', "", "названная правка уступает словам"),
    (R, "    return bool(W_WHOLE_PERSON.search(_words(spec, text)))\n", "    return False\n",
     "слова о замене целиком не читаются"),
    (R, '            if "photo" not in set(spec.inputs):\n                новые = ["генерация_изображения", *новые]\n', "",
     "без референса нового персонажа нет"),
    # 6. пачка UGC
    (R, "SHARED_PRESENTER = 1", "SHARED_PRESENTER = 0", "общий ведущий не считается"),
    (R, "UGC_CLIPS_MIN = 3", "UGC_CLIPS_MIN = 2", "два ролика — уже пачка"),
    (R, '    packshots_brought = bool(фото) and (sf.subject(spec, "product", "cosmetic") is not False)\n',
     "    packshots_brought = False\n", "принесённые кадры товара генерируются заново"),
    (R, "    м = W_PRODUCTS.search(_words(spec, text))\n    return int(м.group(1)) if м else None\n",
     "    return None\n", "число товаров словами не читается"),
    # 4. согласованные учения
    (CS, "    return DOMAIN in _strings(spec.get(\"domain\")) and площадки == {PLATFORM}\n",
     "    return DOMAIN in _strings(spec.get(\"domain\")) and PLATFORM in площадки\n",
     "внутренний и публичный показ вместе открывают дверь"),
    (CS, '        and str(person.get("role") or "").lower() in IN_HOUSE_ROLES\n', "", "нанятый актёр проходит как свой"),
    (CS, '        and str(person.get("claim") or "").lower() == LIFTED_CLAIM\n', "", "политическое заявление снимается"),
    (CS, '    if W_KEEP_REFUSED.search(str(brief or "")) or W_MINOR.search(str(brief or "")):\n',
     '    if W_MINOR.search(str(brief or "")):\n', "политика словами не закрывает дверь"),
    (SV, "    просев, политика = consented_simulation.apply(учения, просев, политика)\n", "",
     "согласованные учения отказываются"),
    (R, '        return "security-awareness" in set(getattr(spec, "domain", None) or ())\n', "        return True\n",
     "названная область не учения — оговорка всё равно"),
    (R, "    return bool(W_SECURITY_TRAINING.search(_words(spec, text)))\n", "    return False\n",
     "слова об учениях не читаются"),
    # контракт и вызовы
    (BS, "DECISION_FIELDS = (*DECISION_FIELDS, *DECISION_FIELDS_R17)\n", "", "поля семнадцатого круга не в черновике"),
    (BS, "    прочитано.update(_прочитано_словами_r17(brief))\n", "", "слова не подсказывают поля семнадцатого круга"),
    (RA, "    steps = r17.rewrite(spec, steps, notes, counts, step_seconds, acc, text)\n", "", "маршруты не применяются"),
    (CL, "RULES_R17: tuple[Rule, ...] = RULES_R17_ROUTES + RULES_R17_KNOWLEDGE\n", "RULES_R17: tuple[Rule, ...] = RULES_R17_KNOWLEDGE\n", "оговорки семнадцатого круга не в списке"),
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
