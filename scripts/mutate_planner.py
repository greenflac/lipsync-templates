#!/usr/bin/env python3
"""Т1: мутация каждой константы-решения планировщика в обе стороны.

    python scripts/mutate_planner.py

Правило дома Т1: константу-решение проверяют подменой — строже и слабее. Не
покраснел ни один тест и ни один гейт — константу никто не сторожит, и это
дефект, а не мелочь: значение, которое ничто не держит, съедет молча.

Скрипт правит файл на диске, гоняет тесты и гейт, ВОЗВРАЩАЕТ файл как был и
сносит `__pycache__` между прогонами (иначе мутант остаётся в скомпилированном
виде и таблица врёт в сторону «покраснело»). Сети здесь нет.

ИЗМЕРЕНО 2026-09-02, первый прогон: 17 мутантов, промолчали на 5. Два из них
были настоящими находками, а не недосмотром тестов:

* `APPLICABILITY_FIRST` — флаг, за которым не стояло ветвления: следующий ключ
  порядка давал ровно тот же результат. Константа УДАЛЕНА, а не покрыта тестом;
* `CANDIDATES_SHOWN` и `EVIDENCE_SHOWN` — границы печати, которых не видел ни
  один тест. Заведён класс `ГраницыПечати`.

После правок: 18 мутантов, промолчали на 0.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MUTANTS = [
    # (файл, что заменить, на что, подпись)
    (
        "studio/planner.py",
        'NOT_MEASURED_MARK = "применимость не измерена"',
        'NOT_MEASURED_MARK = "применимость измерена"',
        "NOT_MEASURED_MARK -> слабее: пометка перестаёт предупреждать",
    ),
    (
        "studio/planner.py",
        'NOT_MEASURED_MARK = "применимость не измерена"',
        'NOT_MEASURED_MARK = "ПРИМЕНИМОСТЬ НЕ ИЗМЕРЕНА НИКЕМ"',
        "NOT_MEASURED_MARK -> строже: другая формулировка",
    ),
    (
        "studio/planner.py",
        'NO_PRICE = "цена не записана"',
        'NO_PRICE = "0"',
        "NO_PRICE -> слабее: ноль читается как «бесплатно»",
    ),
    (
        "studio/planner.py",
        'NO_PRICE = "цена не записана"',
        'NO_PRICE = "цены в базе нет вовсе"',
        "NO_PRICE -> строже: другая формулировка",
    ),
    (
        "studio/planner.py",
        "CANDIDATES_SHOWN = 3",
        "CANDIDATES_SHOWN = 1",
        "CANDIDATES_SHOWN 3 -> 1 (строже)",
    ),
    (
        "studio/planner.py",
        "CANDIDATES_SHOWN = 3",
        "CANDIDATES_SHOWN = 9",
        "CANDIDATES_SHOWN 3 -> 9 (слабее)",
    ),
    (
        "studio/planner.py",
        "EVIDENCE_SHOWN = 3",
        "EVIDENCE_SHOWN = 0",
        "EVIDENCE_SHOWN 3 -> 0 (строже: доказательства не печатаются)",
    ),
    (
        "studio/planner.py",
        "EVIDENCE_SHOWN = 3",
        "EVIDENCE_SHOWN = 9",
        "EVIDENCE_SHOWN 3 -> 9 (слабее)",
    ),
    (
        "studio/planner.py",
        "return (-c.applicability, -c.anchored,",
        "return (-c.anchored, -c.applicability,",
        "by_evidence: применимость больше не первый ключ порядка",
    ),
    (
        "studio/planner.py",
        "return (-c.applicability, -c.anchored,",
        "return (c.applicability, -c.anchored,",
        "by_evidence: применимость перевёрнута (измеренное вниз)",
    ),
    (
        "studio/planner.py",
        'CLASS_NAME_MARKER = "*"',
        'CLASS_NAME_MARKER = "\\u0000"',
        "CLASS_NAME_MARKER -> слабее: находка о классе идёт в кандидаты",
    ),
    (
        "studio/planner.py",
        'CLASS_NAME_MARKER = "*"',
        'CLASS_NAME_MARKER = "-"',
        "CLASS_NAME_MARKER -> строже: половина имён объявлена не-моделями",
    ),
    (
        "studio/planner.py",
        'HAVE_VIDEO_CUES: tuple[str, ...] = (\n    "готов",',
        'HAVE_VIDEO_CUES: tuple[str, ...] = (\n    "готов-нет-такого-слова",',
        "HAVE_VIDEO_CUES -> строже: «готовый ролик» больше не вход плана",
    ),
    (
        "studio/planner.py",
        'HAVE_VIDEO_CUES: tuple[str, ...] = (\n    "готов",',
        'HAVE_VIDEO_CUES: tuple[str, ...] = (\n    "",\n    "готов",',
        "HAVE_VIDEO_CUES -> слабее: любой бриф объявляет видео входом плана",
    ),
    (
        "studio/planner.py",
        '        name="звук_фон",\n        cues=("фоновые звук", "фоновый звук", "foley", "шумы", "звуковые эффект", "sfx"),',
        '        name="звук_фон",\n        cues=(),',
        "OPERATIONS: у звук_фон отняты слова заказчика (шаг перестаёт выводиться)",
    ),
    (
        "studio/planner.py",
        '        anchors=("foley", "sound-effects", "sfx", "ambient-sound"),',
        '        anchors=("foley", "sound-effects", "sfx", "video"),',
        "OPERATIONS: у звук_фон расширен якорь (шаг перестаёт быть пустым)",
    ),
    (
        "scripts/check_planner.py",
        'TODAY = "2026-09-02"',
        'TODAY = "2025-07-01"',
        "TODAY -> раньше (2025-07-01): база перестаёт быть старой",
    ),
    (
        "scripts/check_planner.py",
        'TODAY = "2026-09-02"',
        'TODAY = "2027-09-02"',
        "TODAY -> позже: вся база становится старше порога",
    ),
]


def clean() -> None:
    for d in ROOT.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    хвост = (p.stdout + p.stderr).strip().splitlines()
    return p.returncode, (хвост[-1] if хвост else "")


def main() -> int:
    clean()
    базовый_т = run([sys.executable, "-m", "unittest", "studio.tests.test_planner"])
    базовый_г = run([sys.executable, "scripts/check_planner.py", "--check"])
    print(
        f"ЗДОРОВЫЙ | тесты rc={базовый_т[0]} {базовый_т[1]} | гейт rc={базовый_г[0]} {базовый_г[1]}"
    )
    print()
    print(f"{'мутация':70} | тесты | гейт | покраснело")
    print("-" * 108)
    молчали = []
    for файл, старое, новое, подпись in MUTANTS:
        путь = ROOT / файл
        было = путь.read_text(encoding="utf-8")
        if старое not in было:
            print(f"{подпись:70} | НЕ НАЙДЕНО В {файл}")
            молчали.append(подпись)
            continue
        путь.write_text(было.replace(старое, новое, 1), encoding="utf-8")
        clean()
        тк, тс = run([sys.executable, "-m", "unittest", "studio.tests.test_planner"])
        гк, гс = run([sys.executable, "scripts/check_planner.py", "--check"])
        путь.write_text(было, encoding="utf-8")
        clean()
        краснота = []
        if тк != 0:
            краснота.append("тесты")
        if гк != 0:
            краснота.append("гейт")
        print(
            f"{подпись:70} | rc={тк}  | rc={гк}  | "
            f"{', '.join(краснота) or 'НИКТО — константу не сторожат'}"
        )
        if not краснота:
            молчали.append(подпись)
    print()
    print(f"мутантов {len(MUTANTS)}, промолчали на {len(молчали)}")
    for m in молчали:
        print(f"  ПРОМОЛЧАЛИ: {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
