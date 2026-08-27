#!/usr/bin/env python3
"""One model, one id. Merge the spellings that split a model's claims in two.

    python scripts/merge_model_ids.py --dry-run
    python scripts/merge_model_ids.py
    python scripts/merge_model_ids.py --check     # red if a merged spelling returns

THE DEFECT, MEASURED 2026-08-27

The base held 211 model ids and five of them were really one model twice or
three times:

    eleven-v3(6), eleven_v3(1), elevenlabs-eleven-v3(4)
    eleven-flash-v2-5(4), eleven-flash-v2.5(1)
    eleven-multilingual-v2(3), elevenlabs-multilingual-v2(2)
    eleven-turbo-v2-5(1), elevenlabs-turbo-v2.5(1)
    gpt-image-2(13), gpt_image_2(1)

Nobody notices, because nothing goes red. What happens instead is that a
caller asking `model_advice("eleven-v3")` is answered from 6 facts while the
base holds 11, and `model_advice("eleven-turbo-v2.5")` is answered from ZERO
while the base holds two. MEASURED: 23 of 37 facts visible, 14 lost.

An honest negative result belongs here too (rule I6): merging the five groups
revealed NO hidden contradiction — contested pairs stayed at 14 before and
after. The cost of the split is invisibility, not a wrong answer, and saying
so is the difference between a measurement and a scare.

WHICH SPELLING WINS, AND WHY IT IS NOT A MATTER OF TASTE

The vendor's. Rule E2: at a disagreement between a label and the evidence,
believe the evidence. These ids appear inside the quotations already recorded
from elevenlabs.io — `eleven_v3`, `eleven_flash_v2_5`,
`eleven_multilingual_v2`, `eleven_turbo_v2_5`, underscores and all. That is
what their API accepts, so that is the id a claim about it is filed under.

`gpt-image-2` goes the other way for the same reason: OpenAI's own pages
write it with hyphens, and the single `gpt_image_2` row came from Runway's
OpenAPI document, where a reseller spells a key in its own house style.

HOW THE MERGE IS DONE

Through `record` and `withdraw`, never by editing the file. The log then
carries the correction with its reason, which is what makes it reviewable —
and re-running is a no-op, because `record` supersedes an identical row and
`withdraw` refuses what is already withdrawn.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import PASS  # noqa: E402

from studio.mcp import advice  # noqa: E402
from studio.selfrag.facts import DEFAULT_FACTS_PATH, load_facts  # noqa: E402

#: spelling seen in the base -> the id its vendor uses. Every entry is a claim
#: about what a vendor calls its own model, and every one of them was read out
#: of a quotation already in the base rather than guessed (rule C10).
MERGES: dict[str, str] = {
    # ElevenLabs' API ids, quoted from elevenlabs.io/docs in the notes of the
    # rows already recorded. Underscores are theirs, not a typo.
    "eleven-v3": "eleven_v3",
    "elevenlabs-eleven-v3": "eleven_v3",
    "eleven-flash-v2.5": "eleven_flash_v2_5",
    "eleven-flash-v2-5": "eleven_flash_v2_5",
    "eleven-flash-v2": "eleven_flash_v2",
    "eleven-multilingual-v2": "eleven_multilingual_v2",
    "elevenlabs-multilingual-v2": "eleven_multilingual_v2",
    "eleven-multilingual-sts-v2": "eleven_multilingual_sts_v2",
    "eleven-turbo-v2-5": "eleven_turbo_v2_5",
    "elevenlabs-turbo-v2.5": "eleven_turbo_v2_5",
    "eleven-turbo-v2": "eleven_turbo_v2",
    "eleven-v3-conversational": "eleven_v3_conversational",
    # OpenAI writes this one with hyphens on its own pages; the underscore
    # spelling arrived from a reseller's OpenAPI document.
    "gpt_image_2": "gpt-image-2",
    # A SCOPE, not a model — `<family>-*` means "true of this vendor's line".
    # It has to carry the family the vendor's own ids use, or `class_claims`
    # can never match it: `elevenlabs-*` reaches nothing, because every id it
    # is about is spelled `eleven_...`.
    "elevenlabs-*": "eleven-*",
}

WHY = (
    "merged into the id the vendor's own documentation uses; the same claim "
    "stands under that id. Two spellings of one model answer a caller from "
    "half its facts each."
)


def _plan(path: Path | None = None) -> list:
    """Every standing fact filed under a spelling that is not the vendor's."""
    return [f for f in load_facts(path or DEFAULT_FACTS_PATH) if f.model in MERGES]


def _check(path: Path | None = None) -> int:
    stale = _plan(path)
    for fact in stale[:10]:
        print(f"  всё ещё под чужим написанием: {fact.model}.{fact.attribute}")
    print(f"\nпроверено {len(MERGES)} написаний\nне слито {len(stale)}")
    return 1 if stale else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.check:
        return _check()

    moved = kept = failed = 0
    for fact in _plan():
        canonical = MERGES[fact.model]
        if args.dry_run:
            print(f"  {fact.model}.{fact.attribute} -> {canonical}")
            moved += 1
            continue
        written = advice.record(
            canonical,
            fact.attribute,
            fact.value,
            fact.source_url,
            fact.tier,
            fact.stated_on,
            note=fact.note,
            fix=fact.fix,
            read_directly=fact.read_directly,
        )
        if written["outcome"] != PASS:
            failed += 1
            print(f"  НЕ ПЕРЕНЕСЕНО {fact.model}.{fact.attribute}: {written['note'][:120]}")
            continue
        removed = advice.withdraw(fact.model, fact.attribute, fact.value, fact.source_url, WHY)
        if removed["outcome"] != PASS:
            failed += 1
            print(f"  НЕ СНЯТО {fact.model}.{fact.attribute}: {removed['note'][:120]}")
            continue
        if written["written"] is None:
            kept += 1
        moved += 1

    print(f"\nнаписаний в таблице {len(MERGES)}")
    print(f"перенесено {moved}")
    print(f"из них уже стояло под каноническим id {kept}")
    print(f"не смогли {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
