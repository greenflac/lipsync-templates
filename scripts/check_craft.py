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


def _checkable(item: dict) -> bool:
    """Can somebody go and see this for themselves?

    Two shapes qualify, and the second was nearly rejected by the first version
    of this gate. An `http` URL is the common case. A `file://` pointer into this
    repository is the OTHER case, and it is stronger evidence rather than weaker:
    the harvest's best record counts which lighting terms actually occur in our
    own 5074 prompts — `soft light` 171, `beauty dish` 0 — a measurement anybody
    can re-run, unlike a page that can be edited or go dark. Rejecting it for
    lacking a URL would have discarded the one record in the set whose numbers
    are marked ИЗМЕРЕНО from first-hand counting.

    The pointer still has to resolve: a `file://` naming something that is not
    here is not evidence, it is a claim about a file.
    """
    url = str(item.get("url", ""))
    if url.startswith("http"):
        return True
    if not url.startswith("file://"):
        return False
    root = Path(__file__).resolve().parents[1]
    # One pointer may name several files joined by '+', as the corpus count does.
    names = [n.strip() for n in url[len("file://") :].split("+") if n.strip()]
    return bool(names) and all((root / name).exists() for name in names)


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

    checked = unreadable = 0
    problems: list[str] = []
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
            if not any(_checkable(e) for e in evidence if isinstance(e, dict)):
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
    return {
        "outcome": FAIL if problems else PASS,
        "checked": checked,
        "violations": len(problems),
        "unmeasured": unreadable,
        "problems": problems,
        "note": (
            f"{len(problems)} нарушений в {checked} записях"
            if problems
            else f"{checked} записей: у каждой источник, тир из лестницы и ни одного "
            f"дословного фрагмента длиннее {VERBATIM_MAX_WORDS} слов"
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
