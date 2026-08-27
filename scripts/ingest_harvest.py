#!/usr/bin/env python3
"""Put a capability harvest into the fact base, and report what it refuses.

    python scripts/ingest_harvest.py --dry-run     # what would happen
    python scripts/ingest_harvest.py               # do it
    python scripts/ingest_harvest.py --check       # fail if anything is unapplied

WHY A SEPARATE FILE AND NOT MORE ENTRIES IN read_sources.py

`read_sources.py` holds a reading pass as Python literals because each entry
carries a paragraph of reasoning about ONE claim somebody argued over. A
machine-readable harvest is a different shape: 375 rows, each a quoted enum
from a schema, none of them contentious. Inlining them would bury the reasoned
entries in a wall of data and make the file unreadable for its actual purpose.

So the harvest lives in `studio/knowledge/harvest_<date>.jsonl` as its own
record, and this is the boundary that validates it and stamps it in.

WHAT THIS REFUSES, AND WHY THE REFUSALS ARE THE INTERESTING OUTPUT

`advice.record` decides the identity rungs from the URL, so a row claiming
`vendor` on a host that `studio/selfrag/source_hosts.py` does not know as that
model's vendor is REFUSED. With 144 models in one harvest most of those hosts
have never been declared, so a first run refuses a lot — and each refusal names
a vendor family somebody has to add. That list is the point of `--dry-run`:
read it, add the families that are real, run again.

A refusal is never silently downgraded to `portal` to make it fit. The tier is
what the URL earns; quietly relabelling it would put the ladder back where it
was when `blog` held nine vendor pages.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import PASS  # noqa: E402

from studio.mcp import advice  # noqa: E402
from studio.selfrag.facts import (  # noqa: E402
    DEFAULT_FACTS_PATH,
    TIERS,
    claim_key,
    load_facts,
)

# The hand-reasoned reading pass, imported so this bulk ingest can YIELD to it.
from read_sources import READINGS  # noqa: E402

# The canonical-id table, IMPORTED and not restated. It is the same knowledge
# as `ALIASES` below — which spelling of a model the base files a claim under —
# and a second copy would go stale the first time either moved. MEASURED
# 2026-08-27: the merge ran, and this gate went red on 22 rows whose model had
# been filed under the vendor's own id while this file was still looking for
# the old spelling.
from merge_model_ids import MERGES  # noqa: E402

DEFAULT_HARVEST = (
    Path(__file__).resolve().parents[1] / "studio" / "knowledge" / "harvest_2026-08-27.jsonl"
)

#: The date the harvest read its sources. Used as `stated_on` because the
#: harvest captured no per-page publication date — a machine-readable schema
#: usually carries none. Honest and stated rather than inferred: this says WHEN
#: IT WAS READ, and the note on every row says so too, so nobody later mistakes
#: it for the day a vendor published something.
READ_ON = "2026-08-27"

#: Vendor-native ids the harvest returned, mapped to the spelling the fact base
#: ALREADY uses for that same model. Deliberately tiny, and it only grows when
#: the base already holds the model under another name: two spellings of one
#: model split its claims into two models that can never contradict each other,
#: which is the quiet way a contested attribute stops being reported.
#:
#: What this does NOT do is invent a normalised spelling for a model the base
#: has never seen. 144 models came out of one harvest; renaming 140 of them to
#: a scheme nobody has agreed would be guessing at scale. A new model keeps the
#: id its vendor uses.
ALIASES: dict[str, str] = {
    "veo3.1": "veo-3.1",
    "act_two": "runway-act-two",
    "gen4.5": "runway-gen-4.5",
    "aleph2": "runway-aleph2",
}

#: A row without this is not evidence, it is an assertion. The audit already
#: rejected empty ones; this is the second gate, because the audit is another
#: agent and agents are not a substitute for a check that runs every time.
MIN_EVIDENCE_CHARS = 12


def _reading_pass_keys() -> set[tuple[str, str, str]]:
    """Claims `scripts/read_sources.py` states, which this must not overwrite.

    Both files write to the same log and the latest row wins, so a claim
    covered by BOTH ends up flipping its note every time either script runs —
    OBSERVED 2026-08-27, `runway-gen-4.5.max_seconds` oscillated between the
    reading pass's reasoning and this ingest's quoted enum, and the gate that
    checks the reading pass went red.

    The reading pass wins, always. Its entries carry a paragraph about WHY a
    claim was believed, argued against a specific alternative; a harvested row
    carries a quoted enum. Where both describe the same claim the reasoning is
    strictly more, and a bulk pass should never be able to erase it.
    """
    keys: set[tuple[str, str, str]] = set()
    for entry in READINGS:
        model, attribute, _value, url = claim_key(
            str(entry["model"]),
            str(entry["attribute"]),
            str(entry["value"]),
            str(entry["source_url"]),
        )
        keys.add((model, attribute, url))
    return keys


def _yield_key(model: str, attribute: str, value: str, url: str) -> tuple[str, str, str]:
    """The key the yield is decided on: model, attribute, PAGE — not value.

    It used to include the value, and that hole cost something on 2026-08-27.
    The harvest wrote `runway-act-two.architecture` from the same OpenAPI
    document the reading pass had already reasoned about, in different words.
    Different value, different key, no yield — so the base carried the reasoned
    entry AND a paraphrase of it, and reported the two as a DISPUTE between
    sources where there is one source and one reading.

    If the reading pass has reasoned about this attribute from this page, a
    bulk row about the same attribute from the same page has nothing to add.
    """
    model_l, attribute_l, _value, url_l = claim_key(model, attribute, value, url)
    return (model_l, attribute_l, url_l)


def _canonical(model: str) -> str:
    """The id the base files this model's claims under.

    Two steps, and they are different questions. `ALIASES` answers "the
    harvest called it this, what does the base already call it" — a harvest
    problem. `MERGES` answers "what does the vendor call it" — a base
    problem, applied afterwards so a harvest alias that lands on a spelling
    the merge has since retired still ends up in the right place.
    """
    name = ALIASES.get(str(model), str(model))
    return MERGES.get(name, name)


def _rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _malformed(row: dict) -> str:
    """Why this row cannot even be offered to `record`. "" when it can."""
    for field in ("model", "attribute", "value", "source_url", "tier", "evidence"):
        if not str(row.get(field) or "").strip():
            return f"empty {field}"
    if str(row["tier"]).strip().lower() not in TIERS:
        return f"tier {row['tier']!r} is not one of {', '.join(TIERS)}"
    if not str(row["source_url"]).startswith(("http://", "https://")):
        return "source_url is not a URL"
    if len(str(row["evidence"]).strip()) < MIN_EVIDENCE_CHARS:
        return "evidence too short to be a quotation"
    if not row.get("read_directly"):
        return "read_directly is not true"
    return ""


def _note(row: dict) -> str:
    quote = " ".join(str(row.get("evidence", "")).split())
    if len(quote) > 600:
        quote = quote[:597] + "..."
    return (
        f"HARVESTED {READ_ON} from a machine-readable source and quoted: {quote} "
        f"(stated_on is the day it was READ; the source carried no date of its own)"
    )


def _check(path: Path) -> int:
    """Is every harvested row already standing in the base? Reads only.

    Writing to a scratch file to answer this would report every row as
    "written", because the scratch starts empty — which is what the first
    version did, and it made the gate meaningless while looking like a gate.
    """
    reserved = _reading_pass_keys()
    standing = {
        claim_key(f.model, f.attribute, f.value, f.source_url): f
        for f in load_facts(DEFAULT_FACTS_PATH)
    }
    missing: list[str] = []
    yielded = 0
    checked = 0
    for row in _rows(path):
        model = _canonical(str(row.get("model", "")))
        # Two keys, two questions. The yield is decided on model+attribute+page;
        # whether the row STANDS is decided on the full claim, value included,
        # because that is what the base is keyed on. Using the yield key for
        # both reported every row as missing — OBSERVED while widening the
        # yield, 804 of 804.
        if (
            _yield_key(
                model,
                str(row.get("attribute", "")),
                str(row.get("value", "")),
                str(row.get("source_url", "")),
            )
            in reserved
        ):
            yielded += 1
            continue
        key = claim_key(
            model,
            str(row.get("attribute", "")),
            str(row.get("value", "")),
            str(row.get("source_url", "")),
        )
        checked += 1
        if key not in standing:
            missing.append(f"{model}.{row.get('attribute')} <- {row.get('source_url')}")
    for line in missing[:10]:
        print(f"  не в базе: {line}")
    print(f"\nпроверено {checked}\nрасхождений {len(missing)}\nуступлено разбору {yielded}")
    return 1 if missing else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_HARVEST)
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument("--check", action="store_true", help="fail if anything is unapplied")
    args = parser.parse_args(argv)

    if not args.path.is_file():
        print(f"не смогли: {args.path} does not exist")
        return 2

    if args.check:
        return _check(args.path)

    rows = _rows(args.path)
    reserved = _reading_pass_keys()
    written = stood = malformed = refused = yielded = 0
    reasons: collections.Counter[str] = collections.Counter()
    families: collections.Counter[str] = collections.Counter()

    for row in rows:
        row = dict(row)
        row["model"] = _canonical(str(row.get("model", "")))
        key = _yield_key(
            str(row.get("model", "")),
            str(row.get("attribute", "")),
            str(row.get("value", "")),
            str(row.get("source_url", "")),
        )
        if key in reserved:
            yielded += 1
            continue
        why = _malformed(row)
        if why:
            malformed += 1
            reasons[why] += 1
            continue
        if args.dry_run:
            # Offer it to a scratch file so the URL/tier rule is really
            # exercised, rather than guessed at from here.
            out = advice.record(
                str(row["model"]),
                str(row["attribute"]),
                str(row["value"]),
                str(row["source_url"]),
                str(row["tier"]).lower(),
                READ_ON,
                note=_note(row),
                read_directly=True,
                path=args.path.with_suffix(".dryrun.jsonl"),
            )
        else:
            out = advice.record(
                str(row["model"]),
                str(row["attribute"]),
                str(row["value"]),
                str(row["source_url"]),
                str(row["tier"]).lower(),
                READ_ON,
                note=_note(row),
                read_directly=True,
            )
        if out["outcome"] != PASS:
            refused += 1
            note = str(out["note"])
            reasons[note[:90]] += 1
            families[f"{row['model']} @ {row['source_url'].split('/')[2]}"] += 1
        elif out["written"] is None:
            stood += 1
        else:
            written += 1

    scratch = args.path.with_suffix(".dryrun.jsonl")
    if (args.dry_run or args.check) and scratch.exists():
        scratch.unlink()

    print(f"строк {len(rows)}")
    print(f"записано {written}")
    print(f"уже стояло {stood}")
    print(f"отказано {refused}")
    print(f"негодных {malformed}")
    print(f"уступлено разбору {yielded}")
    if reasons:
        print("\nпочему отказано (топ):")
        for reason, count in reasons.most_common(8):
            print(f"  {count:>4}  {reason}")
    if families:
        print("\nмодели и хосты, которым нужен тир vendor в source_hosts.py (топ):")
        for pair, count in families.most_common(15):
            print(f"  {count:>3}  {pair}")

    if malformed:
        print("\nFAIL: malformed rows in the harvest file")
        return 1
    return 0 if written or stood else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
