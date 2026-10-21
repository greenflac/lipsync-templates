#!/usr/bin/env python3
"""Т1: мутация констант-решений ВОСЕМНАДЦАТОГО КРУГА (специальные знания и остатки цен) — в обе стороны.

    python scripts/mutate_round18_knowledge.py          # все мутанты
    python scripts/mutate_round18_knowledge.py 0 10     # мутанты с 0 по 9 (прогон частями)

Что мутируется: пакет СДО (формат старше слов, слова); медицина и наука (область старше слов, слова);
язык жестов (поле доступности старше слов, имена, заметка в пробеле, тег не версия); громкость
(площадка решает, цели площадок, звук в результате); замена реплик и неречевые звуки; CJK
(вертикальные локали, названный китайский), RTL-графика; мастер без титров (версии, смешанная
дорожка, поле старше слов, дубляж); одежда, стекло и жидкость; отрисовка из данных; вариант
языка голоса; смешанная озвучка без перевода; сжатая нарезка и одна программа дважды.

Устройство — как у `scripts/mutate_round17_knowledge.py`: файл правится на диске, набор гоняется
через `python -B` со снесённым `__pycache__`, файл ВОЗВРАЩАЕТСЯ как был. Первой строкой —
ЗДОРОВЫЙ прогон.

ТРИ ИСХОДА (Р1): годно — здоровый зелёный и покраснели все мутанты; не годно — здоровый красный
или хоть один промолчал; не смогли — цели мутанта нет в файле.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_round18_knowledge",)

X18 = "studio/expert_r18.py"
X17 = "studio/expert_r17.py"
X15 = "studio/expert_r15.py"
CL = "studio/recipes/checklist.py"
PN = "studio/planner.py"
BS = "studio/brief_spec.py"

#: (файл, было, стало, что ломается)
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- 1. пакет СДО
    (X18, 'ELEARNING_FORMATS: tuple[str, ...] = ("scorm", "xapi")', 'ELEARNING_FORMATS: tuple[str, ...] = ("scorm",)',
     "xapi не пакет"),
    (X18, 'ELEARNING_FORMATS: tuple[str, ...] = ("scorm", "xapi")', 'ELEARNING_FORMATS: tuple[str, ...] = ("scorm", "xapi", "mp4")',
     "любой mp4 — пакет СДО"),
    (X18, "    if форматы is not None:\n        return bool(set(форматы) & set(ELEARNING_FORMATS))\n", "",
     "формат не старше слов"),
    (X18, r'    r"|\bсдо\b|систем', r'    r"|систем', "СДО по-русски не читается"),
    (X18, r'    r"\bscorm\b|\bxapi\b|', r'    r"\bscorm\b|training|\bxapi\b|', "любое обучение — SCORM"),
    # --- 2. медицина и наука
    (X18, 'SCIENCE_DOMAINS: tuple[str, ...] = ("medical", "science")', 'SCIENCE_DOMAINS: tuple[str, ...] = ("medical",)',
     "наука без проверки"),
    (X18, 'SCIENCE_DOMAINS: tuple[str, ...] = ("medical", "science")',
     'SCIENCE_DOMAINS: tuple[str, ...] = ("medical", "science", "education")', "любое обучение — медицина"),
    (X18, "    поле = sf.domain(spec, *SCIENCE_DOMAINS)\n    if поле is not None:\n        return поле\n", "",
     "область не старше слов"),
    (X18, r"|для пациентов|", r"|", "«для пациентов» не читается"),
    (X18, r'    r"|molecul\w*|cell biology"', r'    r"|molecul\w*|cell biology|app\b"', "любое приложение — медицина"),
    # --- 3. язык жестов
    (BS, "    if \"accessibility\" in spec.source:\n        return ACCESSIBILITY_SIGN_LANGUAGE in spec.accessibility\n", "",
     "поле доступности не старше слов"),
    (BS, "        return ACCESSIBILITY_SIGN_LANGUAGE in spec.accessibility\n", "        return False\n",
     "поле sign-language не открывает пробел"),
    (X18, '"ase": "ASL", "bfi": "BSL",', '"ase": "ASL", "bfi": "ASL",', "BSL назван как ASL"),
    (X18, '"gsg": "DGS", "jsl": "JSL",', '"gsg": "DGS",', "японский жестовый не назван"),
    (PN, '    заметки = [н for н in rc.notes(понято, [], по_английски, text=brief) if н["id"] == "sign_language_access"]',
     "    заметки = []", "пробел без заметки"),
    (CL, "        return out - NOT_A_VERSION_LANGS - bs.SIGN_LANGUAGE_CODES\n", "        return out - NOT_A_VERSION_LANGS\n",
     "язык жестов — версия"),
    (CL, 'NOT_A_VERSION_LANGS: frozenset[str] = frozenset({"mul"})', "NOT_A_VERSION_LANGS: frozenset[str] = frozenset()",
     "mul — версия"),
    # --- 4. громкость
    (X18, '    "youtube": ("YouTube: about -14 LUFS integrated', '    "youtube": ("YouTube: about -16 LUFS integrated',
     "YouTube не -14"),
    (X18, '("game audio (Sony ASWG-R001): -24 LUFS', '("game audio (Sony ASWG-R001): -23 LUFS', "игра как эфир"),
    (X18, '    "web": ("web / e-learning video', '    "web-x": ("web / e-learning video', "веб без цели"),
    (X18, "                return LOUDNESS_TARGETS[п]\n        return None\n",
     "                return LOUDNESS_TARGETS[п]\n        return LOUDNESS_ASK\n", "печать с целью громкости"),
    (X18, "    if площадки:\n        for п in площадки:", "    if False:\n        for п in площадки:", "площадка не решает"),
    (X18, r'|ebu ?r ?128|громкост\w*", re.I)', r'|ebu ?r ?128", re.I)', "громкость по-русски не читается"),
    (CL, '    return c.video and "video" in c.spec.inputs and c.spec.audio != "none"', "    return c.video",
     "немой ролик с целью громкости"),
    (CL, '    return c.video and "video" in c.spec.inputs and c.spec.audio != "none"', "    return False",
     "свой ролик без цели громкости"),
    # --- 5. замена реплик, неречевые звуки
    (CL, '    if "липсинк" in c.steps and c.jobs & (SPEECH_MAKE | {"dub"}):\n        return True\n', "",
     "дубляж с губами без рум-тона"),
    (CL, '    if "video" not in c.spec.inputs:\n        return False\n    if "липсинк" in c.steps', '    if "липсинк" in c.steps',
     "рум-тон без своего дубля"),
    (X18, r"|переозвуч\w*|рум-?тон\w*|", r"|переозвуч\w*|", "рум-тон по-русски не читается"),
    (X18, r'    r"\badr\b|re-?record', r'    r"\badr\b|voice|re-?record', "любой голос — замена реплики"),
    (CL, '    if sf.platform(c.spec, "game-engine") or sf.domain(c.spec, "entertainment"):',
     '    if sf.domain(c.spec, "entertainment"):', "игра без неречевых"),
    (CL, "    if c.speakers >= MULTI_VOICE_MIN:\n        return True\n    return bool(x18.W_NONVERBAL", "    return bool(x18.W_NONVERBAL",
     "диалог без неречевых"),
    (CL, '    if not c.jobs & (SPEECH_MAKE | {"avatar"}):\n        return False\n    if sf.platform(c.spec, "game-engine")',
     '    if sf.platform(c.spec, "game-engine")', "неречевые на картинке"),
    (X18, r"|кряхт\w*|", r"|", "кряхтение не читается"),
    # --- 6. типографика
    (X18, 'VERTICAL_CJK: frozenset[str] = frozenset({"ja", "zh-TW",', 'VERTICAL_CJK: frozenset[str] = frozenset({"zh-TW",',
     "японский без вертикали"),
    (X18, 'VERTICAL_CJK: frozenset[str] = frozenset({"ja", "zh-TW",', 'VERTICAL_CJK: frozenset[str] = frozenset({"ja", "ko", "zh-TW",',
     "корейский вертикально"),
    (X18, '"zh-Hans", "zh-TW", "zh-HK", "zh-Hant", "zh-MO"})', '"zh-Hans", "zh-HK", "zh-Hant", "zh-MO"})',
     "zh-TW — голый китайский"),
    (CL, "    if rtl and c.visual:\n        return {\"langs\"", "    if rtl:\n        return {\"langs\"", "RTL-графика без картинки"),
    # --- 7. мастер без титров
    (X18, "TEXTLESS_MIN_VERSIONS = 2", "TEXTLESS_MIN_VERSIONS = 3", "две версии без чистого мастера"),
    (X18, "TEXTLESS_MIN_VERSIONS = 2", "TEXTLESS_MIN_VERSIONS = 1", "одна версия — чистый мастер"),
    (X18, "    языки = 1 if mixed else len(", "    языки = len(", "смешанная дорожка — версии"),
    (X18, '    if названо.get("languages") == "spec" or рынки:\n        return False\n', "", "поле языков не старше слов"),
    (X18, "    if dub:\n        return True\n    языки", "    языки", "дубляж без чистого мастера"),
    (X18, r"|чист\w* (?:версия|мастер)|текстлесс|", r"|чист\w* (?:версия|мастер)|", "текстлесс не читается"),
    # --- 8. одежда, стекло
    (X18, "    if try_on:\n        return True\n", "", "примерка без оговорки"),
    (X18, '    поле = sf.subject(spec, "garment")\n    if поле is not None:\n        return поле\n', "",
     "предмет не старше слов (одежда)"),
    (CL, '    if not c.jobs & (VIDEO_GEN | STILL_GEN | {"char_replace", "turntable"}):\n        return False\n', "",
     "одежда в озвучке"),
    (X18, r'|футболк\w*|куртк\w*|принт\w*",', r'|футболк\w*|куртк\w*",', "принт не читается"),
    (X18, 'GLASS_SUBJECTS: tuple[str, ...] = ("transparent",)', 'GLASS_SUBJECTS: tuple[str, ...] = ("transparent", "reflective")',
     "хром — стекло"),
    (X18, "    поле = sf.subject(spec, *GLASS_SUBJECTS)\n    if поле is not None:\n        return поле\n", "",
     "предмет не старше слов (стекло)"),
    (X18, r"|духи\b|", r"|", "духи не читаются"),
    (X18, r'    r"\bglass\w*|liquid|', r'    r"\bglass\w*|rock|liquid|', "камень — стекло"),
    # --- 9. из данных
    (X18, 'DATA_SUBJECTS: tuple[str, ...] = ("chart", "map")', 'DATA_SUBJECTS: tuple[str, ...] = ("chart",)', "карта не данные"),
    (X18, 'DATA_SUBJECTS: tuple[str, ...] = ("chart", "map")', 'DATA_SUBJECTS: tuple[str, ...] = ("chart", "map", "product")',
     "товар — данные"),
    (X18, r"|\bmaps? (?:of|animation)\b", r"|\bmaps?\b", "карта глубины — данные"),
    (X18, r"|статистик\w*|дашборд\w*", r"|статистик\w*", "дашборд не читается"),
    (BS, 'DATA_SUBJECTS: tuple[str, ...] = ("chart", "map")', 'DATA_SUBJECTS: tuple[str, ...] = ("chart",)',
     "subject map не принят"),
    # --- 10. вариант языка, смешанная озвучка
    (X18, 'BARE_UNDECIDED: frozenset[str] = frozenset({"es", "pt", "ar", "zh"})',
     'BARE_UNDECIDED: frozenset[str] = frozenset({"es", "pt", "ar", "zh", "en"})', "голый en — вариант"),
    (X18, 'BARE_UNDECIDED: frozenset[str] = frozenset({"es", "pt", "ar", "zh"})',
     'BARE_UNDECIDED: frozenset[str] = frozenset({"es", "ar", "zh"})', "голый pt без варианта"),
    (X18, 'PLURICENTRIC: frozenset[str] = frozenset({"es", "pt", "en", "fr", "ar", "zh", "de"})',
     'PLURICENTRIC: frozenset[str] = frozenset({"es", "pt", "en", "fr", "ar", "zh"})', "de-AT без варианта"),
    (X18, "    if not названо and W_ACCENT.search(", "    if W_ACCENT.search(", "названные языки — слова акцента"),
    (X18, r"|canadian french|акцент\w*|диалект\w*|", r"|canadian french|акцент\w*|", "диалект не читается"),
    (CL, "    if _mixed_voice_only(c):\n        return None\n", "", "смешанная озвучка — перевод"),
    (CL, '    if "dub" in c.jobs or c.jobs & {"transcribe", "captions", "shorts"} or not c.jobs & SPEECH_MAKE:',
     '    if "dub" in c.jobs or not c.jobs & SPEECH_MAKE:', "расшифровка смешанной речи без перевода"),
    # --- 11. остатки цен
    (X18, "CONDENSE_SHARE = 0.5", "CONDENSE_SHARE = 0.6", "порог сжатия шире"),
    (X18, "CONDENSE_SHARE = 0.5", "CONDENSE_SHARE = 0.4", "порог сжатия уже"),
    (X18, '    if getattr(spec, "edit", None) or getattr(spec, "edit_target", None) is not None:\n        return False\n    материал',
     "    материал", "названная правка — нарезка"),
    (X17, "    if x18.condensed_cut(spec):\n        return True\n", "", "сжатая нарезка — генеративная правка"),
    (CL, ' or (x18.condensed_cut(c.spec) and "правка_видео" not in c.steps)', "", "сжатая нарезка без выбора моментов"),
    (X18, "        if з.get(\"kind\") == \"audio\" and длина and (длина, штук) in видео:\n            continue\n", "",
     "звук видео — второй материал (x18)"),
    (X15, "            if з.get(\"kind\") == \"audio\" and запись in видео:\n                continue\n", "",
     "звук видео — вторая расшифровка"),
    (X17, "    всего = min(всего, x18.programme_seconds(spec)) if всего else всего\n", "", "паузы тифлокомментария по двум входам"),
    # --- поля и черновик
    (BS, '    if x18.W_ELEARNING.search(низ):\n        п["delivery.format"] = ["scorm"]\n', "", "черновик без формата СДО"),
    (BS, 'ELEARNING_FORMATS: tuple[str, ...] = ("scorm", "xapi")', 'ELEARNING_FORMATS: tuple[str, ...] = ("scorm",)',
     "формат xapi не принят"),
)


def clean() -> None:
    for p in ROOT.rglob("__pycache__"):
        if ".claude" not in p.relative_to(ROOT).parts:
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
