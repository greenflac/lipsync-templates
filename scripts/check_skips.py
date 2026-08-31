#!/usr/bin/env python3
"""Пропущенный тест — не пройденный. Гейт обязан их назвать, а не проглотить.

    python scripts/check_skips.py --check

ЧТО СЛОМАНО БЕЗ ЭТОГО

`python -m unittest` печатает `OK (skipped=12)` и возвращает 0. Правило Т6
говорит обратное: пропуск красит сборку, и красное «не запускалось» помечается
ОТДЕЛЬНО от красного «упало» — иначе оба снимут одним способом. ИЗМЕРЕНО
2026-08-31: 770 тестов, 12 пропущено, код возврата 0.

ДВА ВИДА ПРОПУСКА, И ОНИ НЕ РАВНЫ

`не смогли` — данных нет в этом окружении, и это правда: весов `buffalo_l` и
`demo/lora_dataset` в CI не будет никогда, а тесты, которые воспроизводят по ним
числа, честно говорят, что воспроизводить нечего. Такой пропуск ПЕЧАТАЕТСЯ
числом и сборку не красит.

`не годно` — любая другая причина. Тест, выключенный по любому иному поводу,
это тест, который кто-то выключил, и Т7 запрещает превращать «не смогли» в
«прошло». Такой пропуск красит гейт, и в отчёте видно, какой именно.

ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ СКРИПТ, А НЕ ПРАВКА ТЕСТОВ

`lipsync/**` заморожен: в studio/CONTRACTS.md у него владелец NOBODY. Чужие
тесты не трогаются даже ради однострочной правки (Ц2). Сделать пропуск видимым
можно снаружи, и это ровно тот случай.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

#: Наборы, которые гейт и так гоняет. Список явный: «найти все тесты» однажды
#: подхватило бы чужой каталог и объявило его пропуски нашими.
SUITES = ("lipsync/tests", "studio/mcp/tests", "studio/selfrag/tests")

#: Причины, по которым пропуск — честное «не смогли», а не выключенный тест.
#: Каждая строка ищется как подстрока в тексте причины. ВЫБРАНО по единственной
#: причине, встречавшейся на 2026-08-31 (12 пропусков из 770): весов и датасета
#: в CI нет и не будет. Всё, чего здесь нет, считается выключенным тестом.
ABSENT_DATA = (
    "no buffalo_l weights",
    "numpy not installed",
    "rewriter missing",
)

_SKIPPED = re.compile(r"\.\.\. skipped ['\"](.+?)['\"]")


def classify(
    reasons: list[str], allowed: tuple[str, ...] = ABSENT_DATA
) -> tuple[list[str], list[str]]:
    """(данных нет — честно, выключено — нарушение).

    Вынесено из точки входа (Т5): развилка, решающая «годно / не годно», обязана
    быть достижима тестом без запуска unittest.
    """
    honest: list[str] = []
    switched_off: list[str] = []
    for reason in reasons:
        if any(known in reason for known in allowed):
            honest.append(reason)
        else:
            switched_off.append(reason)
    return honest, switched_off


def run_suite(path: str) -> tuple[int, list[str]]:
    """(сколько тестов прошло, причины пропусков). Пустой набор — не ошибка здесь."""
    done = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", path, "-t", ".", "-v"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    text = done.stderr + done.stdout
    ran = re.search(r"^Ran (\d+) test", text, re.MULTILINE)
    return (int(ran.group(1)) if ran else 0), _SKIPPED.findall(text)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    total = 0
    reasons: list[str] = []
    for suite in SUITES:
        if not (REPO / suite).is_dir():
            print(f"  НЕТ НАБОРА {suite}")
            continue
        ran, skipped = run_suite(suite)
        total += ran
        reasons.extend(skipped)
        print(f"  {suite:24} прогнано {ran:4}, пропущено {len(skipped)}")

    honest, switched_off = classify(reasons)
    for reason in sorted(set(switched_off)):
        print(f"  ВЫКЛЮЧЕН ТЕСТ: {reason}")
    for reason in sorted(set(honest)):
        print(f"  данных нет ({honest.count(reason)}×): {reason}")

    outcome = FAIL if switched_off else (PASS if total else UNMEASURED)
    print(f"\nпроверено {total}\nнарушений {len(switched_off)}\nне смогли {len(honest)}")
    print(
        f"\n{outcome}: "
        + (
            f"{len(switched_off)} тестов выключено по причине, которой нет в списке «данных нет»"
            if switched_off
            else f"{total} тестов прогнано, {len(honest)} не смогли — данных для них нет в этом окружении"
            if total
            else "ни одного теста не прогнано"
        )
    )
    if not args.check:
        return 0
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[outcome]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
