#!/usr/bin/env python3
"""What did the readers who were RIGHT see that the readers who were WRONG did not?

    python scripts/find_signals.py
    python scripts/find_signals.py --check   # без сети: связен ли снятый прогон

THE POINT OF THE WHOLE BENCH

A score says whether the agent can read a creative. It does not say WHAT to look
at, and that is the thing worth keeping. Every reader recorded `observed` — the
concrete things it saw, before it guessed — so the material for the answer is
already collected and was collected blind.

WHAT THIS DOES AND DOES NOT CLAIM

It counts which words appear in the observations of correct readings against
wrong ones. That is a POINTER, never a finding: with forty cases, a word
appearing four times against one is well inside coincidence. So the output is
explicitly a shortlist for testing against the held-out cases, and it says so —
a shortlist mistaken for a result is how a bench starts manufacturing signals to
look productive.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

BANK = Path(__file__).resolve().parents[1] / "work" / "casebank"

#: Below this a word appearing more on one side is noise. ВЫБРАНО: three is the
#: smallest count where a lopsided split is worth a second look, and the script
#: says out loud that even then it is a pointer.
MIN_MENTIONS = 3

_WORD = re.compile(r"[а-яёa-z][а-яёa-z-]{3,}")
STOP = frozenset(
    """это того тоже есть быть было один одна одно кадр кадре кадра кадров
    видно виден видна цвет цвета свет света план плане фон фоне что как для при
    без над под над the and with this that from image video frame""".split()
)


#: Во сколько раз доля у верных обязана превысить долю у неверных. ВЫБРАНО:
#: полуторный перевес на такой выборке — это подсказка, а не признак, и скрипт
#: говорит об этом вслух в своём же выводе.
ПЕРЕВЕС = 1.5


def перекошенные(
    hit_words: collections.Counter[str],
    miss_words: collections.Counter[str],
    hits: int,
    misses: int,
) -> list[tuple[str, int, int, float]]:
    """Слова, встречающиеся у верных чтений заметно чаще, чем у неверных.

    ВЫНЕСЕНО ИЗ `main` (Т5): развилка жила внутри точки входа и была достижима
    только через настоящий прогон банка — то есть через файлы, которых в
    репозитории нет. ИЗМЕРЕНО 2026-09-06: `MIN_MENTIONS = 1` держал все три
    набора тестов зелёными, а это значит «одно упоминание — уже подсказка», то
    есть список подсказок, целиком состоящий из совпадений.

    Доли, а не счётчики: слово может быть перекошено только ОТНОСИТЕЛЬНО того,
    сколько чтений было на каждой стороне.
    """
    найдено: list[tuple[str, int, int, float]] = []
    for word, count in hit_words.most_common(200):
        against = miss_words[word]
        if count < MIN_MENTIONS:
            continue
        share_hit = count / max(hits, 1)
        share_miss = against / max(misses, 1)
        if share_hit > share_miss * ПЕРЕВЕС:
            найдено.append((word, count, against, round(share_hit - share_miss, 3)))
    return найдено


#: Файлы прогона, без которых короткий список не из чего строить. Имена ровно
#: те, что читает `main` ниже: второй список имён разъехался бы с первым.
ФАЙЛЫ_БАНКА: tuple[str, ...] = ("TRUTH.json", "ANSWERS.json", "SCORE.json", "BLIND_MAP.json")


def проверить_собранное(bank: Path | None = None) -> dict[str, Any]:
    """Офлайн: связен ли УЖЕ СНЯТЫЙ прогон банка. Сети здесь нет.

    БАНКА В РЕПОЗИТОРИИ НЕТ (`work/` в `.gitignore`), поэтому на чистом клоне и
    в CI честный исход ровно один — «не смогли». Ноль проверенных разборов при
    нуле нарушений успехом не считается (правило Р2).

    ЧТО ЛОВИТ. Короткий список строится СКЛЕЙКОЙ трёх файлов: счёт знает разбор
    под настоящим именем, ответы — под слепым, а карта `BLIND_MAP` связывает
    одно с другим. Разъехалась карта — и `answers.get(...)` молча не находит
    ничего: `hits + misses` падает, скрипт печатает короткий список по
    оставшимся разборам и НЕ говорит, что половину он не нашёл. Здесь эта
    склейка проверяется по числам до того, как из неё что-то посчитано.

    Нарушения (M):
      * файл банка не разобрался как JSON или лежит не тем типом;
      * строка счёта без обязательных полей (`case_id`, `answered`, `family_hit`);
      * два слепых имени указывают на один и тот же разбор;
      * ОТВЕЧЕННАЯ строка счёта, которой не соответствует ни один ответ, —
        это и есть разъехавшаяся склейка.

    Не смогли (K): нет банка; или в банке нет ни одного отвеченного разбора —
    считать не из чего, и это не «годно».
    """
    каталог = BANK if bank is None else bank
    нет = [и for и in ФАЙЛЫ_БАНКА if not (каталог / и).is_file()]
    if нет:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": len(нет),
            "note": (
                f"прогона банка нет: в {каталог} не найдено {', '.join(нет)} "
                "(каталог work/ не коммитится) — проверять нечего, и это НЕ «годно»"
            ),
        }
    прочитано: dict[str, Any] = {}
    for имя in ФАЙЛЫ_БАНКА:
        try:
            прочитано[имя] = json.loads((каталог / имя).read_text(encoding="utf-8"))
        except ValueError:
            return {
                "outcome": FAIL,
                "checked": 0,
                "violations": 1,
                "unmeasured": 0,
                "note": f"{имя} не разобрался как JSON",
            }
    счёт = прочитано["SCORE.json"]
    ответы = прочитано["ANSWERS.json"]
    карта = прочитано["BLIND_MAP.json"]
    if not isinstance(счёт, dict) or not isinstance(счёт.get("rows"), list):
        return {
            "outcome": FAIL,
            "checked": 0,
            "violations": 1,
            "unmeasured": 0,
            "note": "SCORE.json без списка rows",
        }
    if not isinstance(ответы, list) or not isinstance(карта, dict):
        return {
            "outcome": FAIL,
            "checked": 0,
            "violations": 1,
            "unmeasured": 0,
            "note": "ANSWERS.json обязан быть списком, BLIND_MAP.json — объектом",
        }

    нарушения: list[str] = []
    настоящие: dict[str, dict] = {}
    for ответ in ответы:
        слепое = str((ответ or {}).get("case_id") or "")
        настоящее = str(карта.get(слепое, слепое))
        if настоящее in настоящие:
            нарушения.append(f"два слепых имени указывают на один разбор {настоящее}")
        настоящие[настоящее] = ответ if isinstance(ответ, dict) else {}

    отвеченных = 0
    for строка in счёт["rows"]:
        if not isinstance(строка, dict) or not all(
            п in строка for п in ("case_id", "answered", "family_hit")
        ):
            нарушения.append(f"строка счёта без обязательных полей: {str(строка)[:60]}")
            continue
        if not строка["answered"]:
            continue
        отвеченных += 1
        ответ = настоящие.get(str(строка["case_id"]))
        if ответ is None:
            нарушения.append(f"отвеченный разбор {строка['case_id']} без ответа в ANSWERS")
        elif not (ответ.get("observed") or []):
            нарушения.append(f"ответ {строка['case_id']} без observed — считать не из чего")

    проверено = len(счёт["rows"])
    # НАРУШЕНИЕ СИЛЬНЕЕ НЕИЗМЕРИМОСТИ. Битые строки счёта не дают ни одного
    # отвеченного разбора, и без этой ветки «файл испорчен» вышло бы наружу
    # как «считать не из чего» — то есть Р1 наоборот: не годно свернулось бы
    # в не смогли.
    if not отвеченных and not нарушения:
        return {
            "outcome": UNMEASURED,
            "checked": проверено,
            "violations": len(нарушения),
            "unmeasured": 1,
            "note": f"строк счёта {проверено}, отвеченных 0 — считать не из чего",
        }
    заметка = (
        f"строк счёта {проверено}, отвеченных {отвеченных}, "
        f"ответов {len(ответы)}, слепых имён в карте {len(карта)}"
    )
    if нарушения:
        заметка += "\n  " + "\n  ".join(нарушения[:10])
    return {
        "outcome": FAIL if нарушения else PASS,
        "checked": проверено,
        "violations": len(нарушения),
        "unmeasured": 0,
        "note": заметка,
    }


def main() -> int:
    if "--check" in sys.argv[1:]:
        итог = проверить_собранное()
        print(итог["note"])
        print(
            f"\nпроверено {итог['checked']}\nнарушений {итог['violations']}\n"
            f"не смогли {итог['unmeasured']}"
        )
        return 0 if итог["outcome"] == PASS else (1 if итог["outcome"] == FAIL else 2)

    truth_path, answers_path, score_path = (
        BANK / "TRUTH.json",
        BANK / "ANSWERS.json",
        BANK / "SCORE.json",
    )
    if not all(p.is_file() for p in (truth_path, answers_path, score_path)):
        print(f"\nпроверено 0\nнарушений 0\nне смогли 1\n\n{UNMEASURED}: нет прогона")
        return 2
    score = json.loads(score_path.read_text(encoding="utf-8"))
    blind = json.loads((BANK / "BLIND_MAP.json").read_text(encoding="utf-8"))
    answers = {
        blind.get(a["case_id"], a["case_id"]): a
        for a in json.loads(answers_path.read_text(encoding="utf-8"))
    }

    hit_words: collections.Counter[str] = collections.Counter()
    miss_words: collections.Counter[str] = collections.Counter()
    hits = misses = 0
    for row in score["rows"]:
        answer = answers.get(row["case_id"])
        if not answer or not row["answered"]:
            continue
        words = set()
        for line in answer.get("observed") or []:
            words |= {w for w in _WORD.findall(str(line).lower()) if w not in STOP}
        if row["family_hit"]:
            hits += 1
            hit_words.update(words)
        else:
            misses += 1
            miss_words.update(words)

    if hits + misses == 0:
        print(
            f"\nпроверено 0\nнарушений 0\nне смогли 1\n\n{UNMEASURED}: ни одного отвеченного разбора"
        )
        return 2

    shortlist = перекошенные(hit_words, miss_words, hits, misses)

    print(f"верных чтений {hits}, неверных {misses}")
    print("\nСЛОВА, ЧАЩЕ ВСТРЕЧАЮЩИЕСЯ У ВЕРНЫХ (это ПОДСКАЗКА, не находка):")
    for word, count, against, gap in shortlist[:20]:
        print(f"   {word:22} у верных {count:3}  у неверных {against:3}  разрыв {gap:+.3f}")

    print(f"\nпроверено {hits + misses}\nнарушений 0\nне смогли 0")
    print(
        f"\n{PASS}: {len(shortlist)} слов в коротком списке. НИ ОДНО из них не является "
        "признаком, пока не проверено на отложенных разборах: при такой выборке "
        "перекос в три-четыре упоминания лежит внутри совпадения."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
