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

ВТОРОЙ ЗАХОД 2026-09-02, после починки цены и бюджета: добавлено десять
мутантов на новые константы-решения (`DEFAULT_PER`, `PRICE_ORDER`, `_MONEY`,
`BUDGET_CUES`, `PRICE_ASKED` и место цены в ключе отбора). Итог: 28 мутантов,
промолчали на 0.

ТРЕТИЙ ЗАХОД 2026-09-02: добавлено девять мутантов на константы строки о
вытесненном проверенном кандидате (`RIVAL_MIN_APPLICABILITY`, `RIVAL_MARK`,
`NO_RIVAL_MARK`, порядок выбора вытесненного и сама развилка `rival_line`).
Итог: 37 мутантов, промолчали на 0.

ЧЕТВЁРТЫЙ ЗАХОД 2026-09-02: добавлено восемь мутантов на константы перевода
«за что» (`SECONDS_IN_MINUTE` в обе стороны, `PER_CONVERSION`, `CONVERTED_MARK`,
проверка единицы в `to_budget_per` и передача потолка валидатору). Итог: 45
мутантов, промолчали на 0.

ПЯТЫЙ ЗАХОД 2026-09-02: добавлено двенадцать мутантов на константы поданного
кадра (`FIT_ORDER`, `LIMIT_ATTRIBUTE_MARKER`, `LIMIT_ATTRIBUTES_EXCLUDED`,
тексты положений, `REJECTED_BY_FRAME_MARK`, `CUSTOMER_KEYS`, место кадра в
ключе и правило сведения строк в `fit_stance`). Итог: 57 мутантов, промолчали
на 0.

ЗДОРОВЫЙ ПРОГОН ПЕЧАТАЕТСЯ ПЕРВОЙ СТРОКОЙ, и это не украшение. Первые заходы
второй и третьей серий ОБА показали `ЗДОРОВЫЙ | тесты rc=1`: таблица мутаций
строилась поверх красного и не значила ничего. Причина оба раза была одна —
точный литерал числа брифов в `test_контрольный_набор_читается_целиком`, который
краснел просто оттого, что в контрольный набор ДОБАВИЛИ случай. Ловушка
сработала дважды, поэтому её убрали: литерал заменён полом, а равенство
`rows_in() == len(briefs())` — то, ради чего тест писался, — осталось.
Без строки «ЗДОРОВЫЙ» таблица «все покраснели» читалась бы как успех.
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
        "return (кадр, цена, -c.applicability, -c.anchored,",
        "return (кадр, цена, -c.anchored, -c.applicability,",
        "by_evidence: применимость больше не первый ключ порядка",
    ),
    (
        "studio/planner.py",
        "return (кадр, цена, -c.applicability, -c.anchored,",
        "return (кадр, цена, c.applicability, -c.anchored,",
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
    # --- константы цены и бюджета, заведённые 2026-09-02 ---
    (
        "studio/planner.py",
        'DEFAULT_PER: tuple[str, ...] = ("run", "generation")',
        'DEFAULT_PER: tuple[str, ...] = ("second",)',
        "DEFAULT_PER -> «за секунду» (потолок шага читается как посекундный)",
    ),
    (
        "studio/planner.py",
        'DEFAULT_PER: tuple[str, ...] = ("run", "generation")',
        "DEFAULT_PER: tuple[str, ...] = ()",
        "DEFAULT_PER -> пусто (сравнивается с любым «за что», как было до починки)",
    ),
    (
        "studio/planner.py",
        "    PRICE_IN: 0,\n    PRICE_INCOMPARABLE: 1,\n    PRICE_ABSENT: 2,",
        "    PRICE_IN: 2,\n    PRICE_INCOMPARABLE: 1,\n    PRICE_ABSENT: 0,",
        "PRICE_ORDER -> слабее: незаписанная цена обгоняет уложившуюся в бюджет",
    ),
    (
        "studio/planner.py",
        "    PRICE_IN: 0,\n    PRICE_INCOMPARABLE: 1,\n    PRICE_ABSENT: 2,",
        "    PRICE_IN: 0,\n    PRICE_INCOMPARABLE: 0,\n    PRICE_ABSENT: 0,",
        "PRICE_ORDER -> строже: четыре положения сливаются в одно",
    ),
    (
        "studio/planner.py",
        "    return (кадр, цена, -c.applicability,",
        "    return (кадр, -c.applicability, цена,",
        "by_evidence: цена перестаёт быть старшим ключом при названном потолке",
    ),
    (
        "studio/planner.py",
        r'    r"\$\s*(\d+(?:[.,]\d+)?)"'
        "\n"
        r'    r"|(\d+(?:[.,]\d+)?)\s*(?:\$|доллар\w*|долл\.?|usd|бакс\w*)",',
        r'    r"\$\s*(\d+(?:[.,]\d+)?)"' "\n" r'    r"|(\d+(?:[.,]\d+)?)",',
        "_MONEY -> слабее: любое число становится бюджетом (единица не нужна)",
    ),
    (
        "studio/planner.py",
        r'    r"\$\s*(\d+(?:[.,]\d+)?)"'
        "\n"
        r'    r"|(\d+(?:[.,]\d+)?)\s*(?:\$|доллар\w*|долл\.?|usd|бакс\w*)",',
        r'    r"\$\s*(\d+(?:[.,]\d+)?)",',
        "_MONEY -> строже: деньги только со значком $, слово «доллар» не считается",
    ),
    (
        "studio/planner.py",
        'BUDGET_CUES: tuple[str, ...] = (\n    "бюджет",',
        'BUDGET_CUES: tuple[str, ...] = (\n    "бюджет-нет-такого-слова",',
        "BUDGET_CUES -> строже: «бюджет 50» больше не отличим от молчания",
    ),
    (
        "studio/planner.py",
        'PRICE_ASKED = "price"',
        'PRICE_ASKED = "generation_time"',
        "PRICE_ASKED -> другая семья: ценой считается скорость",
    ),
    (
        "studio/planner.py",
        'PRICE_ASKED = "price"',
        'PRICE_ASKED = "price_per_second_usd"',
        "PRICE_ASKED -> одно имя вместо семьи: восемнадцать имён снова невидимы",
    ),
    # --- константы строки о вытесненном проверенном, заведены 2026-09-02 ---
    (
        "studio/planner.py",
        "RIVAL_MIN_APPLICABILITY = 1",
        "RIVAL_MIN_APPLICABILITY = 0",
        "RIVAL_MIN_APPLICABILITY 1 -> 0 (слабее: проверенным считается любой)",
    ),
    (
        "studio/planner.py",
        "RIVAL_MIN_APPLICABILITY = 1",
        "RIVAL_MIN_APPLICABILITY = 2",
        "RIVAL_MIN_APPLICABILITY 1 -> 2 (строже: одна строка перестаёт считаться)",
    ),
    (
        "studio/planner.py",
        'RIVAL_MARK = "ПРОВЕРЕННЫЙ ЕСТЬ, НО ЦЕНА ЕГО ОТОДВИНУЛА"',
        'RIVAL_MARK = "есть и другие кандидаты"',
        "RIVAL_MARK -> слабее: пометка перестаёт называть, что именно случилось",
    ),
    (
        "studio/planner.py",
        'RIVAL_MARK = "ПРОВЕРЕННЫЙ ЕСТЬ, НО ЦЕНА ЕГО ОТОДВИНУЛА"',
        'RIVAL_MARK = "ПРОВЕРЕННЫЙ КАНДИДАТ ВЫТЕСНЕН ЦЕНОЙ"',
        "RIVAL_MARK -> строже: другая формулировка",
    ),
    (
        "studio/planner.py",
        'NO_RIVAL_MARK = "ПРОВЕРЕННЫХ НЕТ ВОВСЕ"',
        'NO_RIVAL_MARK = "ПРОВЕРЕННЫЙ ЕСТЬ, НО ЦЕНА ЕГО ОТОДВИНУЛА"',
        "NO_RIVAL_MARK -> слабее: два разных положения печатаются одним текстом",
    ),
    (
        "studio/planner.py",
        'NO_RIVAL_MARK = "ПРОВЕРЕННЫХ НЕТ ВОВСЕ"',
        'NO_RIVAL_MARK = "ни одного проверенного кандидата не найдено"',
        "NO_RIVAL_MARK -> строже: другая формулировка",
    ),
    (
        "studio/planner.py",
        "    свои.sort(key=lambda c: by_evidence(c)[CUSTOMER_KEYS:])",
        "    свои.sort(key=by_evidence)",
        "proven: цена возвращается в выбор вытесненного (назовёт того же, кого подняла)",
    ),
    (
        "studio/planner.py",
        '    if chosen is None or chosen.measured:\n        return ""',
        '    if chosen is None:\n        return ""',
        "rival_line -> слабее: строка печатается и у проверенного выбранного (шум)",
    ),
    (
        "studio/planner.py",
        '    if chosen is None or chosen.measured:\n        return ""',
        '    if chosen is None or not chosen.measured:\n        return ""',
        "rival_line -> строже: строка молчит ровно там, где она и нужна",
    ),
    # --- константы перевода «за что», заведены 2026-09-02 ---
    (
        "studio/planner.py",
        "SECONDS_IN_MINUTE = 60.0",
        "SECONDS_IN_MINUTE = 1.0",
        "SECONDS_IN_MINUTE 60 -> 1 (слабее: минута равна секунде)",
    ),
    (
        "studio/planner.py",
        "SECONDS_IN_MINUTE = 60.0",
        "SECONDS_IN_MINUTE = 3600.0",
        "SECONDS_IN_MINUTE 60 -> 3600 (строже: минута равна часу)",
    ),
    (
        "studio/planner.py",
        '    if price.amount is None or price.unit != BUDGET_UNIT:\n        return None, ""',
        '    if price.amount is None:\n        return None, ""',
        "to_budget_per -> слабее: единица перестаёт проверяться (кредиты как доллары)",
    ),
    (
        "studio/planner.py",
        '    ("minute", "second"): 1.0 / SECONDS_IN_MINUTE,\n    ("second", "minute"): SECONDS_IN_MINUTE,',
        "",
        "PER_CONVERSION -> строже: таблица пуста, перевода нет вовсе",
    ),
    (
        "studio/planner.py",
        '    ("minute", "second"): 1.0 / SECONDS_IN_MINUTE,',
        '    ("minute", "second"): 1.0 / SECONDS_IN_MINUTE,\n    ("1000_chars", "second"): 1.0,',
        "PER_CONVERSION -> слабее: заведена пара, у которой множитель не определение",
    ),
    (
        "studio/planner.py",
        'CONVERTED_MARK = "ПЕРЕВЕДЕНО НАМИ"',
        'CONVERTED_MARK = "пересчитано"',
        "CONVERTED_MARK -> слабее: пометка перестаёт называть, кто посчитал",
    ),
    (
        "studio/planner.py",
        'CONVERTED_MARK = "ПЕРЕВЕДЕНО НАМИ"',
        'CONVERTED_MARK = "ПОСЧИТАНО ПЛАНИРОВЩИКОМ"',
        "CONVERTED_MARK -> строже: другая формулировка",
    ),
    (
        "studio/planner.py",
        "    пошаговый = бюджет.known and bool(set(бюджет.per or DEFAULT_PER) & set(DEFAULT_PER))",
        "    пошаговый = бюджет.known",
        "потолок за секунду снова уходит в бюджет ШАГА валидатору",
    ),
    # --- константы поданного кадра против предела модели, заведены 2026-09-02 ---
    (
        "studio/planner.py",
        "    FIT_IN: 0,\n    FIT_UNPARSED: 1,\n    FIT_ABSENT: 2,",
        "    FIT_IN: 2,\n    FIT_UNPARSED: 1,\n    FIT_ABSENT: 0,",
        "FIT_ORDER -> слабее: незаписанный предел обгоняет проверенное согласие",
    ),
    (
        "studio/planner.py",
        "    FIT_IN: 0,\n    FIT_UNPARSED: 1,\n    FIT_ABSENT: 2,",
        "    FIT_IN: 0,\n    FIT_UNPARSED: 0,\n    FIT_ABSENT: 0,",
        "FIT_ORDER -> строже: четыре положения по кадру сливаются в одно",
    ),
    (
        "studio/planner.py",
        'LIMIT_ATTRIBUTE_MARKER = "resolution"',
        'LIMIT_ATTRIBUTE_MARKER = "max_resolution"',
        "LIMIT_ATTRIBUTE_MARKER -> строже: native_resolution и прочие перестают считаться",
    ),
    (
        "studio/planner.py",
        'LIMIT_ATTRIBUTE_MARKER = "resolution"',
        'LIMIT_ATTRIBUTE_MARKER = "o"',
        "LIMIT_ATTRIBUTE_MARKER -> слабее: пределом кадра становится почти всё",
    ),
    (
        "studio/planner.py",
        'LIMIT_ATTRIBUTES_EXCLUDED: frozenset[str] = frozenset({"training_resolution"})',
        "LIMIT_ATTRIBUTES_EXCLUDED: frozenset[str] = frozenset()",
        "LIMIT_ATTRIBUTES_EXCLUDED -> слабее: разрешение ОБУЧЕНИЯ снова считается пределом",
    ),
    (
        "studio/planner.py",
        'FIT_ABSENT = "предел кадра не записан"',
        'FIT_ABSENT = "кадр принимается"',
        "FIT_ABSENT -> слабее: «не знаем» печатается тем же текстом, что «принимает»",
    ),
    (
        "studio/planner.py",
        'FIT_OVER = "кадр НЕ принимается"',
        'FIT_OVER = "кадр вне записанного предела"',
        "FIT_OVER -> строже: другая формулировка",
    ),
    (
        "studio/planner.py",
        'REJECTED_BY_FRAME_MARK = "КАДР ОТВЁРГ КАНДИДАТОВ"',
        'REJECTED_BY_FRAME_MARK = "есть и другие кандидаты"',
        "REJECTED_BY_FRAME_MARK -> слабее: строка перестаёт называть, что случилось",
    ),
    (
        "studio/planner.py",
        "CUSTOMER_KEYS = 2",
        "CUSTOMER_KEYS = 1",
        "CUSTOMER_KEYS 2 -> 1 (цена возвращается в выбор вытесненного)",
    ),
    (
        "studio/planner.py",
        "CUSTOMER_KEYS = 2",
        "CUSTOMER_KEYS = 3",
        "CUSTOMER_KEYS 2 -> 3 (применимость выключается из выбора вытесненного)",
    ),
    (
        "studio/planner.py",
        "    return (кадр, цена, -c.applicability,",
        "    return (цена, кадр, -c.applicability,",
        "by_evidence: кадр перестаёт быть старше цены",
    ),
    (
        "studio/planner.py",
        "    if приняли:\n        return FIT_IN,",
        "    if приняли and not отвергли:\n        return FIT_IN,",
        "fit_stance -> строже: один мелкий режим отменяет крупный",
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
