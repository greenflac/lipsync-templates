#!/usr/bin/env python3
"""Score what the blind readers guessed, and refuse to flatter the number.

    python scripts/score_validation.py work/casebank/ANSWERS.json

WHAT IS BEING MEASURED

Whether this agent can tell, from the picture alone, which generator made it.
Nobody has that number; until now it was established by the owner correcting me.

FOUR WAYS THE NUMBER COULD LIE, AND WHAT IS DONE ABOUT EACH

1. GUESSING. A reader pushed to answer will answer, and a corpus of twelve
   candidates rewards a coin-flip 8% of the time. So `не смогли` is a first-class
   answer, counted apart and never folded into wrong — and the report prints the
   random baseline beside the score, because "better than nothing" is the only
   comparison that means anything (rules R1, R2).

2. RECOGNITION. A reader may simply remember a famous image. That is a correct
   answer and not a READ one, so recognised cases are scored twice: once in and
   once out. If the two differ, the honest number is the one without them.

3. LICENCE. The owner's ruling 2026-08-30: non-commercial material is used and
   NAMED. So the flag is not a field somebody might notice — the report is split
   by it, and a verdict computed over restricted cases carries the marker at the
   top, where it cannot be scrolled past.

4. THE EASY HALF. Telling a video model from an image model is nearly free and
   would carry the average on its own. Family accuracy and exact-model accuracy
   are reported apart, and per source, so a good number cannot hide behind an
   easy split.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

BANK = Path(__file__).resolve().parents[1] / "work" / "casebank"
TRUTH = BANK / "TRUTH.json"
BLIND_MAP = BANK / "BLIND_MAP.json"

#: Below this the score is a rumour. ВЫБРАНО: with twelve candidates and a 1/12
#: baseline, fewer than twenty answered cases cannot separate a real signal from
#: a lucky run, and printing a percentage over ten would invite exactly that.
MIN_ANSWERED = 20


def family_of(name: str) -> str:
    """The vendor line a model belongs to. Cheap on purpose: exact-model
    accuracy is reported separately, and this is the easier question."""
    text = str(name or "").lower().replace("_", "-")
    for family in (
        "veo",
        "sora",
        "midjourney",
        "nano-banana",
        "gpt-image",
        "seedream",
        "wan",
        "recraft",
        "ideogram",
        "z-image",
        "flux",
        "kling",
        "imagen",
    ):
        if family in text:
            return family
    return text.split("-")[0] if text else "?"


def score(cases: list[dict], answers: list[dict], blind: dict[str, str] | None = None) -> dict:
    """Join answers to truth through the blinding map.

    The readers never saw a real case id — the first version of the bank named
    its files `kv-…` for Kling and `of-…` for OpenFake, which handed over the
    source before a reader opened anything. The files are `case-001.jpg` now, in
    shuffled order, and this is where the two halves are put back together.
    """
    blind = blind or {}
    by_id = {c["case_id"]: c for c in cases}
    seen: dict[str, dict] = {}
    unmatched: list[str] = []
    for answer in answers:
        said_id = str(answer.get("case_id") or "")
        real = blind.get(said_id, said_id)
        if real in by_id:
            seen[real] = answer
        else:
            unmatched.append(said_id)

    rows: list[dict] = []
    for cid, answer in seen.items():
        case = by_id[cid]
        truth = case["truth"]
        real = str(truth.get("model") or truth.get("kling_version") or "")
        if case["source"] == "kling":
            real = f"kling-{truth.get('kling_version')}"
        guess = answer.get("guess") or {}
        said = str(guess.get("exact") or guess.get("family") or "")
        answered = answer.get("outcome") == "назвал" and bool(said)
        rows.append(
            {
                "case_id": cid,
                "source": case["source"],
                "commercial_ok": case["commercial_ok"],
                "truth": real,
                "said": said,
                "answered": answered,
                "family_hit": answered and family_of(said) == family_of(real),
                "exact_hit": answered and said.strip().lower() == real.strip().lower(),
                "recognised": bool(answer.get("recognised")),
                "confidence": answer.get("confidence"),
            }
        )

    def tally(subset: list[dict]) -> dict:
        answered = [r for r in subset if r["answered"]]
        return {
            "cases": len(subset),
            "answered": len(answered),
            "could_not": len(subset) - len(answered),
            "family_hits": sum(1 for r in answered if r["family_hit"]),
            "exact_hits": sum(1 for r in answered if r["exact_hit"]),
            "family_rate": round(sum(1 for r in answered if r["family_hit"]) / len(answered), 4)
            if answered
            else None,
            "exact_rate": round(sum(1 for r in answered if r["exact_hit"]) / len(answered), 4)
            if answered
            else None,
        }

    families = {family_of(str(c["truth"].get("model") or "kling")) for c in cases}
    baseline = round(1 / max(len(families), 1), 4)

    restricted = [r for r in rows if not r["commercial_ok"]]
    clean = [r for r in rows if r["commercial_ok"]]
    recognised = [r for r in rows if r["recognised"]]
    without_memory = [r for r in rows if not r["recognised"]]

    overall = tally(rows)
    outcome = UNMEASURED if overall["answered"] < MIN_ANSWERED else PASS
    note = (
        f"отвечено {overall['answered']} < {MIN_ANSWERED}: числа печатаются, но "
        "процент по такой выборке — слух, а не измерение"
        if outcome is UNMEASURED
        else f"семейство {overall['family_rate']} против случайного {baseline}"
    )
    return {
        "outcome": outcome,
        "checked": len(rows),
        "violations": 0,
        "не_сошлись_идентификаторы": unmatched,
        "unmeasured": overall["could_not"],
        "baseline_random": baseline,
        "families_in_bank": sorted(families),
        "overall": overall,
        "по_источнику": {
            src: tally([r for r in rows if r["source"] == src])
            for src in sorted({r["source"] for r in rows})
        },
        "коммерчески_чистые": tally(clean),
        "ограниченные_non_commercial": tally(restricted),
        "узнал_по_памяти": len(recognised),
        "без_узнавания": tally(without_memory),
        "rows": rows,
        "note": note,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("answers", nargs="?", default=str(BANK / "ANSWERS.json"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if not TRUTH.is_file() or not Path(args.answers).is_file():
        print(f"\nпроверено 0\nнарушений 0\nне смогли 1\n\n{UNMEASURED}: нет истины или ответов")
        return 2
    cases = json.loads(TRUTH.read_text(encoding="utf-8"))
    answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    blind = json.loads(BLIND_MAP.read_text(encoding="utf-8")) if BLIND_MAP.is_file() else {}
    out = score(cases, answers, blind)

    restricted = out["ограниченные_non_commercial"]
    if restricted["cases"]:
        print("=" * 68)
        print("NON-COMMERCIAL: часть результата посчитана по материалу с ограниченной")
        print(f"лицензией — {restricted['cases']} из {out['checked']} разборов (OpenFake,")
        print("cc-by-nc-4.0). Любой вывод отсюда несёт эту пометку дальше.")
        print("=" * 68)

    o = out["overall"]
    print(f"\nразборов {o['cases']} | отвечено {o['answered']} | не смогли {o['could_not']}")
    print(f"семейство угадано  {o['family_hits']}/{o['answered']}  = {o['family_rate']}")
    print(f"модель угадана     {o['exact_hits']}/{o['answered']}  = {o['exact_rate']}")
    print(
        f"случайное угадывание при {len(out['families_in_bank'])} семействах = {out['baseline_random']}"
    )
    print("\nпо источнику:")
    for src, t in out["по_источнику"].items():
        print(f"  {src:10} отвечено {t['answered']:3}/{t['cases']:3}  семейство {t['family_rate']}")
    print(f"\nузнал по памяти, а не прочитал: {out['узнал_по_памяти']}")
    bm = out["без_узнавания"]
    print(f"без них: отвечено {bm['answered']}, семейство {bm['family_rate']}")
    print(
        f"\nпроверено {out['checked']}\nнарушений {out['violations']}\nне смогли {out['unmeasured']}"
    )
    print(f"\n{out['outcome']}: {out['note']}")

    (BANK / "SCORE.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if not args.check:
        return 0
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[out["outcome"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
