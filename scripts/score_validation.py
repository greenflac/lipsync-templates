#!/usr/bin/env python3
"""Score what the blind readers guessed, and refuse to flatter the number.

    python scripts/score_validation.py work/casebank/ANSWERS.json

WHAT IS BEING MEASURED

Whether this agent can tell, from the picture alone, which generator made it.
Nobody has that number; until now it was established by the owner correcting me.

SIX WAYS THE NUMBER COULD LIE, AND WHAT IS DONE ABOUT EACH

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

5. A SOURCE WITH ONLY ONE RIGHT ANSWER. Found 2026-08-30 by looking at a result
   that was too good: with the Kling watermark cropped away the readers still
   scored 16/16 on family, at confidence 0.3, saying in their own words "a strip
   of six frames means video, and among the video candidates I take kling". They
   were right every time because every video in the bank IS kling — the format
   of the sheet announced the source, and no input existed where the correct
   answer was "not kling". That is a missing negative control (rule I5), and a
   rate measured without one is not a measurement of discrimination.

   The test is per MEDIUM, not per source, and the first version got that wrong.
   It asked how many families a SOURCE holds, which was right while Kling was the
   only video in the bank and wrong the moment Civitai was added: Kling still
   holds one family, but a reader looking at a strip now chooses between three
   video families, so those cases discriminate again. Keying on the source threw
   real data away — MEASURED 2026-08-31, nine answered Kling cases scoring 0.4444
   were discarded, and 0.4444 is what a removed prop sounds like: the very same
   cases scored 1.00 while the bank held no other video.

   So a source is `различимо: false` when its MEDIUM holds fewer than two
   families — that is exactly when the medium alone gives the answer away. Its
   rate is printed but never headlined, and the verdict is computed over the
   discriminating part.

6. A TRUTH NOBODY'S MACHINE WROTE DOWN. The fix for (5) needed video that is not
   Kling, and the material available is Civitai, where the model is typed by the
   person who uploaded the clip. MEASURED 2026-08-30 over 191 clips: 11 carry a
   model field their own tooling wrote, 180 rest on the page's caption. The
   owner accepted that grade 2026-08-31 on one condition — it is named. So every
   case carries `truth_grade`, the report splits by it, and a verdict computed
   over uploader-labelled cases prints the warning above the number. What the
   noise costs is the PRECISION of the percentage; the discrimination it makes
   possible is real either way.
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

#: A truth nobody's machine wrote down. Cases from Civitai are labelled by the
#: person who uploaded the clip, and the owner accepted them 2026-08-31 for one
#: specific job: breaking a bank in which every video was Kling. What a noisy
#: label costs is the PRECISION of the percentage, not the existence of the
#: measurement — so they are counted, and counted apart, and the split is
#: printed above the number rather than beside it.
UNVERIFIED_GRADE = "uploader_claim"


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
        "minimax",
        "ltx",
        "hunyuan",
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

    # КАЖДЫЙ разбор становится строкой, а не только тот, на который пришёл
    # ответ. Найдено разбором 2026-08-31: строки строились из `seen`, то есть
    # из ответов, и разбор, на который читатель просто ничего не прислал,
    # исчезал из ВСЕХ знаменателей сразу — не попадая ни в «отвечено», ни в
    # «не смогли», ни в `cases`. Меньший знаменатель льстит каждому проценту
    # над ним, и это ровно та форма, против которой в этом же файле уже стоит
    # отчёт по `не_сошлись_идентификаторы`.
    rows: list[dict] = []
    for cid in by_id:
        answer = seen.get(cid, {"outcome": "нет ответа", "guess": {}})
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
                "truth_grade": str(case.get("truth_grade") or "vendor_log"),
                "no_answer": cid not in seen,
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

    # How many DIFFERENT right answers a MEDIUM offers. One is not a choice: a
    # reader that sees a strip and always says the same word scores 100% there,
    # having discriminated nothing (rule I5). Medium, not source, because the
    # medium is what a reader can tell for free just by looking.
    families_per_source: dict[str, set[str]] = {}
    families_per_medium: dict[str, set[str]] = {}
    medium_of_source: dict[str, str] = {}
    for case in cases:
        real = str(case["truth"].get("model") or "")
        if case["source"] == "kling":
            real = f"kling-{case['truth'].get('kling_version')}"
        medium = str(case.get("media") or "?")
        families_per_source.setdefault(case["source"], set()).add(family_of(real))
        families_per_medium.setdefault(medium, set()).add(family_of(real))
        medium_of_source[case["source"]] = medium
    blind_sources = sorted(
        source
        for source, medium in medium_of_source.items()
        if len(families_per_medium.get(medium, set())) < 2
    )
    discriminating = [r for r in rows if r["source"] not in blind_sources]

    by_uploader = [r for r in rows if r["truth_grade"] == UNVERIFIED_GRADE]
    by_machine = [r for r in rows if r["truth_grade"] != UNVERIFIED_GRADE]
    restricted = [r for r in rows if not r["commercial_ok"]]
    clean = [r for r in rows if r["commercial_ok"]]
    recognised = [r for r in rows if r["recognised"]]
    without_memory = [r for r in rows if not r["recognised"]]

    overall = tally(rows)
    honest = tally(discriminating)

    # ТРИ ИСХОДА, А НЕ ДВА. Найдено разбором 2026-08-31: `FAIL` импортировался
    # и не возвращался этой функцией НИКОГДА, поэтому чтение на уровне монетки
    # печаталось как «годно» — прибор физически не мог сказать «не годно».
    # Порог — сам случайный базис: узнавание не лучше угадывания это не слабый
    # результат, это отсутствие умения, и называть его успехом нельзя.
    rate = honest["family_rate"]
    if honest["answered"] < MIN_ANSWERED:
        outcome = UNMEASURED
    elif rate is not None and rate <= baseline:
        outcome = FAIL
    else:
        outcome = PASS

    if outcome is UNMEASURED:
        note = (
            f"различающих ответов {honest['answered']} < {MIN_ANSWERED}: числа "
            "печатаются, но процент по такой выборке — слух, а не измерение"
        )
    elif outcome is FAIL:
        note = (
            f"семейство {rate} НЕ ВЫШЕ случайного {baseline}: на этой выборке "
            "агент не отличает генераторы, и называть это успехом нельзя"
        )
    else:
        note = f"семейство {rate} против случайного {baseline}"
        if blind_sources:
            note += (
                f"; считано без источников, у которых в среде одно семейство "
                f"({', '.join(blind_sources)}) — там отличать не от чего"
            )
    return {
        "outcome": outcome,
        "checked": len(rows),
        "violations": 0,
        "не_сошлись_идентификаторы": unmatched,
        "без_ответа": sorted(r["case_id"] for r in rows if r["no_answer"]),
        "unmeasured": overall["could_not"],
        "baseline_random": baseline,
        "families_in_bank": sorted(families),
        "overall": overall,
        "по_источнику": {
            src: dict(
                tally([r for r in rows if r["source"] == src]),
                семейств_в_источнике=len(families_per_source.get(src, set())),
                семейств_в_среде=len(
                    families_per_medium.get(medium_of_source.get(src, "?"), set())
                ),
                различимо=src not in blind_sources,
            )
            for src in sorted({r["source"] for r in rows})
        },
        "источники_без_выбора": blind_sources,
        "различающая_часть": honest,
        "коммерчески_чистые": tally(clean),
        "ограниченные_non_commercial": tally(restricted),
        "истина_от_загрузчика": tally(by_uploader),
        "истина_записана_машиной": tally(by_machine),
        "грейды_в_вердикте": sorted({r["truth_grade"] for r in discriminating}),
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

    unverified = out["истина_от_загрузчика"]
    if UNVERIFIED_GRADE in out["грейды_в_вердикте"]:
        print("=" * 68)
        print(f"ИСТИНУ НАПИСАЛ ЧЕЛОВЕК: {unverified['cases']} из {out['checked']} разборов")
        print("помечены загрузчиком, а не записаны машиной (Civitai). Принято")
        print("владельцем 2026-08-31 ради негативного контроля. Величина процента")
        print("по ним шумная; сам факт различения — нет.")
        print("=" * 68)

    if out["источники_без_выбора"]:
        print("=" * 68)
        print("ЕДИНСТВЕННОЕ СЕМЕЙСТВО В СРЕДЕ: " + ", ".join(out["источники_без_выбора"]))
        print("Среду читатель различает бесплатно, просто посмотрев. Если в ней одно")
        print("семейство, ответ известен без чтения, и процент там не измеряет")
        print("различение. Итог считается по остальным (правило И5).")
        print("=" * 68)

    o = out["overall"]
    h = out["различающая_часть"]
    print(f"\nразборов {o['cases']} | отвечено {o['answered']} | не смогли {o['could_not']}")
    print(
        f"ИТОГ (различающая часть): семейство {h['family_hits']}/{h['answered']} = "
        f"{h['family_rate']}, модель {h['exact_hits']}/{h['answered']} = {h['exact_rate']}"
    )
    print(
        f"всё вместе, для справки:  семейство {o['family_hits']}/{o['answered']} = "
        f"{o['family_rate']}, модель {o['exact_hits']}/{o['answered']} = {o['exact_rate']}"
    )
    print(
        f"случайное угадывание при {len(out['families_in_bank'])} семействах = {out['baseline_random']}"
    )
    print("\nпо источнику:")
    for src, t in out["по_источнику"].items():
        mark = "" if t["различимо"] else "  ← одно семейство в среде, не измерение"
        print(
            f"  {src:10} отвечено {t['answered']:3}/{t['cases']:3}  "
            f"семейство {t['family_rate']}{mark}"
        )
    print("\nпо грейду истины:")
    for name, t in (
        ("записана машиной", out["истина_записана_машиной"]),
        ("написана человеком", out["истина_от_загрузчика"]),
    ):
        print(
            f"  {name:19} отвечено {t['answered']:3}/{t['cases']:3}  семейство {t['family_rate']}"
        )
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
