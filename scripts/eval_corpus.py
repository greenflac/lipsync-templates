#!/usr/bin/env python3
"""Measure retrieval against a gold set DERIVED from the corpus that is loaded.

    python scripts/eval_corpus.py            # report
    python scripts/eval_corpus.py --check    # 0 pass / 1 fail / 2 could not measure

WHY THIS EXISTS, AND WHAT IT REPLACES

`studio/knowledge/eval_set.jsonl` scores 0.4342 recall@5 and both its positive
controls come back `pass` with five examples and recall 0. MEASURED 2026-08-28:
its target phrases are not in any loaded corpus. `amber cream premium palette`
occurs in exactly one file in this repository — eval_set.jsonl itself. That set
was written against `our_prompts` and `reference_cards`, which `build_index`
reports absent. It is not wrong; it is an instrument for corpora nobody has
produced yet, and a number it prints is a fact about a missing file.

So this is not a replacement of that set. It is a second instrument, for the
corpus that IS here, and the two answer different questions.

WHY THE SET IS DERIVED AND NEVER COMMITTED

Two reasons, and the second one is the load-bearing one.

1. The gold rows would carry verbatim fragments of a third party's prompts, and
   the owner's decision of 2026-08-28 is that this material is not published
   from a public repository. Deriving it at run time keeps the measurement and
   leaves the wording where it lives.
2. A committed gold set can be edited until it passes. One derived by a fixed
   rule from a fixed seed cannot: to change the score you have to change the
   retriever or the corpus, which is the whole point of having a score.

HOW A ROW IS BUILT, AND WHY IT CANNOT CONTAIN ITS OWN ANSWER

For a sampled corpus row: find a contiguous phrase in its text that occurs in
exactly ONE row of the whole corpus, and make that the target. Build the query
out of the row's OTHER words, with every word of the target removed. So the
query never quotes the answer, and a retriever that merely echoes its input
scores zero.

WHAT ACCEPTANCE MEANS HERE (decision C3, 2026-08-28)

A number alone proves nothing — a set where every query is trivially answerable
scores 1.0 against a retriever that is not working. So the set is accepted only
if the real retriever beats two random baselines, each taken as the MAXIMUM over
20 seeds rather than the mean, so the margin cannot be won by luck:

  ADMISSION  real recall@5 must exceed, by >= ADMISSION_MARGIN, the best recall
             of drawing 5 rows uniformly at random from the whole corpus.
             This asks whether the retriever admits the right things at all.
  RANKING    real recall@5 must exceed, by >= RANKING_MARGIN, the best recall of
             shuffling the retriever's OWN admitted candidates. This asks
             whether the ordering carries information, or whether the score
             comes entirely from admission.

Both margins are CHOSEN, not measured. They are the smallest gaps that would
still read as a difference rather than as noise on a set of this size, and the
report prints the observed margins next to them so the choice stays arguable.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

import studio.knowledge as K  # noqa: E402


def _as_row(entry: object) -> dict:
    """One index Entry as the mapping the scorer reads.

    `index.entries` holds dataclasses while `retrieve` hands back dicts, and
    `_haystack` reads a mapping. Converting in one place keeps the two shapes
    from being confused at four call sites.
    """
    return {
        "kind": getattr(entry, "kind", ""),
        "text": getattr(entry, "text", ""),
        "palette": list(getattr(entry, "palette", ()) or ()),
        "light": getattr(entry, "light", ""),
        "texture": getattr(entry, "texture", ""),
        "mood": getattr(entry, "mood", ""),
    }


#: CHOSEN. Enough rows that one lucky query cannot move the number much, few
#: enough that the whole run stays inside a gate step.
GOLD_ROWS = 60

#: CHOSEN. The seed is fixed so the set is the same file-for-file on every run
#: and on every machine; a moving gold set measures the weather.
SEED = 20260828

#: CHOSEN. A target shorter than this is a word, not a phrase, and words repeat.
TARGET_WORDS = 4

#: CHOSEN. How many of the row's remaining words go into the query. Short enough
#: that the query is a brief and not the document.
QUERY_WORDS = 10

#: CHOSEN margins over the random baselines. See the module docstring.
ADMISSION_MARGIN = 0.10
RANKING_MARGIN = 0.05

#: CHOSEN. Twenty seeds, and the MAXIMUM over them, not the mean.
BASELINE_SEEDS = 20

_WORD = re.compile(r"[a-z][a-z'-]{2,}")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def build_gold(entries: list, *, rows: int = GOLD_ROWS, seed: int = SEED) -> list[dict]:
    """Derive gold rows from the corpus. Deterministic for a given seed."""
    corpus = [_as_row(e) for e in entries]
    corpus = [e for e in corpus if e["kind"] == K.KIND_GALLERY_PROMPT]
    texts = [str(e.get("text", "")).lower() for e in corpus]
    rng = random.Random(seed)
    order = list(range(len(corpus)))
    rng.shuffle(order)

    gold: list[dict] = []
    for i in order:
        if len(gold) >= rows:
            break
        words = _words(texts[i])
        if len(words) < TARGET_WORDS + QUERY_WORDS:
            continue
        # Find a contiguous phrase that appears in exactly one row.
        target = ""
        for start in range(0, len(words) - TARGET_WORDS):
            phrase = " ".join(words[start : start + TARGET_WORDS])
            if sum(1 for t in texts if phrase in t) == 1:
                target = phrase
                break
        if not target:
            continue
        banned = set(target.split())
        rest = [w for w in words if w not in banned]
        if len(rest) < QUERY_WORDS:
            continue
        query = " ".join(rng.sample(rest, QUERY_WORDS))
        gold.append(
            {
                "query": query,
                "must_retrieve": [target],
                "must_not_retrieve": [],
                "control": None,
            }
        )
    return gold


def _recall(examples: list[dict], must: list[str]) -> float:
    blob = " ".join(K._haystack(e) for e in examples)
    return sum(1 for p in must if p in blob) / len(must) if must else 0.0


#: Во сколько раз шире пул просить у того же ретривера ради ранжирующего
#: базиса. ВЫБРАНО 4: достаточно, чтобы перемешивание что-то меняло, и мало,
#: чтобы «случайные пять из двадцати» оставались осмысленным сравнением.
#:
#: ЗАЧЕМ ЭТО ЗДЕСЬ. Разбор 2026-08-31: критерий RANKING не мог сработать НИ НА
#: ОДНОМ входе. Базис считался по тем же пяти записям, что ретривер и вернул —
#: `retrieve` держит `if len(lane) >= k: continue`, значит отдаёт РОВНО k, — а
#: перемешать пять и взять пять это те же пять. Условие `wider > 0` не
#: выполнялось никогда, `ranking_measurable` был вечно False, и шаг молча
#: печатал «не смогли 1», годами не проверяя ничего.
WIDER_POOL = 4


def _real_score(
    index: K.KnowledgeIndex, gold: list[dict]
) -> tuple[float, list[list[dict]], list[list[dict]]]:
    """Recall@5 ретривера, что он вернул на каждой строке, и ШИРОКИЙ пул.

    Широкий пул берётся у того же ретривера тем же запросом, только с большим
    `k`. Это и есть «что он допустил, но не выдал» — единственное, на чём
    перемешивание вообще способно что-то показать.
    """
    answers: list[list[dict]] = []
    pools: list[list[dict]] = []
    total = 0.0
    for row in gold:
        out = K.retrieve(row["query"], index=index)
        examples = out.get("examples", [])
        answers.append(examples)
        wide = K.retrieve(row["query"], index=index, k=K.DEFAULT_K * WIDER_POOL)
        pools.append(wide.get("examples", []))
        total += _recall(examples, row["must_retrieve"])
    return total / len(gold), answers, pools


def _admission_baseline(entries: list, gold: list[dict]) -> float:
    """Best recall over BASELINE_SEEDS draws of 5 rows from the whole corpus."""
    corpus = [r for r in (_as_row(e) for e in entries) if r["kind"] == K.KIND_GALLERY_PROMPT]
    best = 0.0
    for s in range(BASELINE_SEEDS):
        rng = random.Random(SEED + s)
        total = sum(_recall(rng.sample(corpus, 5), row["must_retrieve"]) for row in gold)
        best = max(best, total / len(gold))
    return best


def _ranking_baseline(answers: list[list[dict]], gold: list[dict]) -> float:
    """Best recall over BASELINE_SEEDS shuffles of the retriever's own answers.

    С пятью выданными и пятью оцениваемыми перемешать те же пять — это те же
    пять, поэтому базис осмыслен только там, где ретривер ДОПУСТИЛ больше, чем
    выдал. Пул берётся у него же с `k = DEFAULT_K * WIDER_POOL`; если и там
    строк не больше пяти, ряд честно остаётся неизмеримым, а не печатается
    проходным нулём.
    """
    best = 0.0
    for s in range(BASELINE_SEEDS):
        rng = random.Random(SEED + 1000 + s)
        total = 0.0
        for examples, row in zip(answers, gold):
            pool = list(examples)
            rng.shuffle(pool)
            total += _recall(pool[: K.DEFAULT_K], row["must_retrieve"])
        best = max(best, total / len(gold))
    return best


def report(*, index: K.KnowledgeIndex | None = None) -> dict:
    """Score the shipped retriever against a gold set derived from `index`.

    The index is a parameter rather than something built inside, so the
    absent-corpus branch below is reachable from a test (rule T5). A fork that
    lives only inside an entry point degrades unwatched.
    """
    index = index if index is not None else K.build_index()
    per_source = index.build_report["per_source"]
    if per_source.get("gallery", 0) == 0:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                "the gallery corpus is not on this machine, so no gold set can be "
                "derived and no recall can be measured. This is not a pass: "
                "studio/knowledge/gallery_prompts.jsonl is deliberately not "
                "committed (see .gitignore), so a run without it measures nothing."
            ),
        }

    gold = build_gold(index.entries)
    if len(gold) < GOLD_ROWS:
        return {
            "outcome": UNMEASURED,
            "checked": len(gold),
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"only {len(gold)} of {GOLD_ROWS} gold rows could be derived: not enough "
                "rows carry a phrase unique to one document. A smaller set would be a "
                "different instrument, so nothing is scored."
            ),
        }

    real, answers, pools = _real_score(index, gold)
    admission = _admission_baseline(index.entries, gold)
    ranking = _ranking_baseline(pools, gold)

    # Считается по ШИРОКОМУ пулу, а не по выдаче: у выдачи длина ровно k по
    # построению, поэтому прежнее `len(a) > DEFAULT_K` было тождественно нулю.
    wider = sum(1 for pool in pools if len(pool) > K.DEFAULT_K)
    failures = []
    if real < admission + ADMISSION_MARGIN:
        failures.append(
            f"ADMISSION: real {real:.4f} does not clear random {admission:.4f} "
            f"by {ADMISSION_MARGIN}"
        )
    ranking_measurable = wider > 0
    if ranking_measurable and real < ranking + RANKING_MARGIN:
        failures.append(
            f"RANKING: real {real:.4f} does not clear shuffled {ranking:.4f} by {RANKING_MARGIN}"
        )

    return {
        "outcome": FAIL if failures else PASS,
        "checked": len(gold),
        "violations": len(failures),
        "unmeasured": 0 if ranking_measurable else 1,
        "recall_at_5": round(real, 4),
        "admission_baseline": round(admission, 4),
        "ranking_baseline": round(ranking, 4),
        "rows_with_a_wider_pool": wider,
        "note": (
            "; ".join(failures)
            if failures
            else (
                f"recall@5 {real:.4f} clears the random-admission baseline "
                f"{admission:.4f} by {real - admission:.4f}"
                + (
                    ""
                    if ranking_measurable
                    else "; the RANKING baseline could not be measured — no row admitted "
                    "more candidates than it returned, so a shuffle is a no-op"
                )
            )
        ),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    out = report()
    for key in (
        "recall_at_5",
        "admission_baseline",
        "ranking_baseline",
        "rows_with_a_wider_pool",
    ):
        if key in out:
            print(f"{key:26} {out[key]}")
    print(
        f"\nпроверено {out['checked']}\nнарушений {out['violations']}\nне смогли {out['unmeasured']}"
    )
    print(f"\n{out['outcome']}: {out['note']}")

    if not args.check:
        return 0
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[out["outcome"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
