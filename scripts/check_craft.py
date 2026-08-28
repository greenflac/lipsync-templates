#!/usr/bin/env python3
"""The knowledge lane's gate: does every record carry a source, and stay legal?

    python scripts/check_craft.py           # report
    python scripts/check_craft.py --check   # 0 годно / 1 не годно / 2 не смогли

WHY THIS EXISTS

Four agents collected 130 knowledge records on 2026-08-28 under one rule the
owner set that day: store a RETELLING WITH A LINK, never a third party's prose,
because this repository is public. The rule held — measured below — but it held
because four agents each remembered it. That is exactly the kind of rule that
decays, so it is a gate now rather than a paragraph (house rule C7).

The critic reviewing the record design found the door this closes. The design
capped the `verbatim` field at a few words and left `evidence[].token_seen`
unguarded — and a record was already carrying a full sentence of somebody's
README through it. One field was watched, its twin was not.

WHAT IS CHECKED, AND THE THIRD OUTCOME

Three things per record: a source URL, a tier on every piece of evidence, and no
quoted fragment longer than the cap. A file that cannot be read AT ALL is exit 2,
never exit 0 — zero violations out of zero records is not a pass (rule R2), and
this package has already been bitten once by that shape.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

from studio.selfrag.facts import TIERS  # noqa: E402

CRAFT_GLOB = "craft_*.jsonl"
KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "studio" / "knowledge"

#: The longest quoted fragment a record may carry. ВЫБРАНО, and the choice has a
#: measurement under it: across the 1020 fragments in the first harvest the
#: median is 1 word and the longest is 13 — a ComfyUI node's one-line docstring
#: and a few parameter signatures, which are the technical tokens the owner
#: allowed. 15 leaves those alone and stops a paragraph. It is not a legal
#: threshold and nobody should read it as one; it is a tripwire that fires long
#: before anything resembling a copied page.
VERBATIM_MAX_WORDS = 15


def _fragments(record: dict) -> list[tuple[str, str]]:
    """Every place a record can carry somebody else's words. Both doors."""
    out: list[tuple[str, str]] = []
    for value in record.get("verbatim") or []:
        out.append(("verbatim", str(value)))
    for item in record.get("evidence") or []:
        if isinstance(item, dict) and item.get("token_seen"):
            out.append(("evidence.token_seen", str(item["token_seen"])))
    return out


#: What one piece of evidence turns out to be. Three answers, because the two-
#: answer version of this function turned CI red the hour it was written.
CITED = "cited"  # an http URL, or a file:// pointer that resolves here
ABSENT = "absent"  # a file:// pointer whose target is not on THIS machine
NOT_EVIDENCE = "not evidence"  # neither shape


def _checkable(item: dict) -> str:
    """Can somebody go and see this for themselves — and if not, why not?

    An `http` URL is the common case. A `file://` pointer into this repository is
    the other one, and it is stronger evidence rather than weaker: the harvest's
    best record counts which lighting terms actually occur in our own 5074
    prompts — `soft light` 171, `beauty dish` 0 — a measurement anybody can
    re-run, unlike a page that can be edited or go dark.

    THE DEFECT THIS FUNCTION WAS WRITTEN TWICE FOR. The first version answered
    yes/no and called an unresolved pointer a violation. It went green here and
    RED IN CI within the hour, because the corpora those pointers name are
    deliberately not committed — the owner's decision of 2026-08-28, this
    repository being public. The pointer was fine and the file was absent on
    purpose, which is neither "verified" nor "wrong". It is the third outcome,
    and collapsing it into the second is the exact mistake this package has a
    rule against (R1). So: absent is reported, counted, and never a violation.
    """
    url = str(item.get("url", ""))
    if url.startswith("http"):
        return CITED
    if not url.startswith("file://"):
        return NOT_EVIDENCE
    root = Path(__file__).resolve().parents[1]
    # One pointer may name several files joined by '+', as the corpus count does.
    names = [n.strip() for n in url[len("file://") :].split("+") if n.strip()]
    if not names:
        return NOT_EVIDENCE
    return CITED if all((root / name).exists() for name in names) else ABSENT


def audit(directory: Path | None = None) -> dict:
    """Judge the knowledge lane. Three outcomes, and counts beside the verdict."""
    target = directory or KNOWLEDGE_DIR
    files = sorted(target.glob(CRAFT_GLOB))
    if not files:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "problems": [],
            "note": (
                f"no {CRAFT_GLOB} in {target}. Nothing was audited, which is not the "
                "same as nothing being wrong."
            ),
        }

    checked = unreadable = unverifiable = 0
    problems: list[str] = []
    notes: list[str] = []
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError as error:
                unreadable += 1
                problems.append(f"{path.name}:{number} не разобралось: {error}")
                continue
            checked += 1
            where = f"{path.name}:{number} {record.get('id', '?')}"

            evidence = record.get("evidence") or []
            answers = [_checkable(e) for e in evidence if isinstance(e, dict)]
            if not any(a == CITED for a in answers):
                if ABSENT in answers:
                    # The evidence may be perfectly good; this machine simply
                    # cannot see the file. Counted, printed, not a violation.
                    unverifiable += 1
                    notes.append(
                        f"{where}: источник — файл, которого нет на этой машине "
                        "(корпус намеренно не коммитится); проверить не смогли"
                    )
                else:
                    problems.append(f"{where}: нет ни одного проверяемого источника")
            for item in evidence:
                if isinstance(item, dict) and item.get("tier") not in TIERS:
                    problems.append(f"{where}: тир {item.get('tier')!r} не из лестницы")

            for field, text in _fragments(record):
                words = len(text.split())
                if words > VERBATIM_MAX_WORDS:
                    problems.append(
                        f"{where}: {field} несёт {words} слов дословно "
                        f"(предел {VERBATIM_MAX_WORDS}) — это уже чужой текст, а не токен"
                    )

    if unreadable and not checked:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": unreadable,
            "problems": problems,
            "note": "ни одной читаемой записи: судить было не о чем",
        }
    # A record whose pointer could not be resolved is NOT a reason to fail the
    # build — but it is a reason to print a number, so that "everything checks
    # out" can never be read over the top of "we could not look" (rule E3).
    return {
        "outcome": FAIL if problems else PASS,
        "checked": checked,
        "violations": len(problems),
        "unmeasured": unreadable + unverifiable,
        "problems": problems + notes,
        "note": (
            f"{len(problems)} нарушений в {checked} записях"
            if problems
            else f"{checked} записей: у каждой источник, тир из лестницы и ни одного "
            f"дословного фрагмента длиннее {VERBATIM_MAX_WORDS} слов"
            + (
                f"; {unverifiable} из них ссылаются на файл, которого нет на этой "
                "машине — эти не проверены"
                if unverifiable
                else ""
            )
        ),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    out = audit()
    for line in out["problems"][:15]:
        print(f"  {line}")
    print(
        f"\nпроверено {out['checked']}\nнарушений {out['violations']}\nне смогли {out['unmeasured']}"
    )
    print(f"\n{out['outcome']}: {out['note']}")
    if not args.check:
        return 0
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[out["outcome"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
