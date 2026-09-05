#!/usr/bin/env python3
"""What did the readers who were RIGHT see that the readers who were WRONG did not?

    python scripts/find_signals.py

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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import PASS, UNMEASURED  # noqa: E402

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


def main() -> int:
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

    shortlist = []
    for word, count in hit_words.most_common(200):
        against = miss_words[word]
        if count < MIN_MENTIONS:
            continue
        # Normalise: a word can only be lopsided relative to how many readings
        # were on each side.
        share_hit = count / max(hits, 1)
        share_miss = against / max(misses, 1)
        if share_hit > share_miss * 1.5:
            shortlist.append((word, count, against, round(share_hit - share_miss, 3)))

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
