"""Normalise a harvested gallery file into the knowledge-base row format.

The harvester runs in another repository and emits whatever shape its own
parser produces. This script is the boundary: it validates what arrived,
stamps the origin fields the knowledge base requires, and reports numbers
next to its verdict instead of failing silently on a shape it did not expect.

    python studio/knowledge/ingest_gallery.py <harvested.jsonl>

Writes studio/knowledge/gallery_prompts.jsonl and prints the counts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

#: CHOSEN with the owner (2026-08-25). Stamped on every row that arrives
#: without them, so the material stays identifiable wherever the file travels
#: and an exact removal stays possible if the gallery's owner asks for one.
PROVENANCE = "third_party_gallery"
RIGHTS = "owner_decision_2026-08-25"

#: A row without wording is not a row: the whole point of this file is the
#: wording. Anything shorter is a parse failure upstream, not a short prompt.
MIN_WORDS = 3

OUT = Path(__file__).resolve().parent / "gallery_prompts.jsonl"


def normalise(row: dict) -> dict | None:
    """Return the row in knowledge-base shape, or None when it carries no wording."""
    text = str(row.get("prompt") or row.get("text") or row.get("wording") or "").strip()
    if len(text.split()) < MIN_WORDS:
        return None
    # The source URL is not decoration: it is the mechanism by which an exact
    # removal stays possible if the gallery's owner asks for one. A harvester
    # that calls the field `page` used to lose it here silently.
    source_url = row.get("source_url") or row.get("url") or row.get("page")
    kind = row.get("kind") or ""
    image_url = row.get("image_url") or ""
    return {
        "id": row.get("id") or row.get("reference_id"),
        "prompt": text,
        "source_url": source_url,
        "section": row.get("section") or row.get("category"),
        "harvested": row.get("harvested") or row.get("retrieved") or "2026-08-25",
        "provenance": row.get("provenance") or PROVENANCE,
        "rights": row.get("rights") or RIGHTS,
        # Position on the source page. PROVENANCE.md calls this pair the
        # card's identity, so it travels with the row rather than being
        # recomputed later by something heuristic.
        "record": row.get("record"),
        "element": row.get("element"),
        "ordinal": row.get("ordinal"),
        "kind": kind,
        "image_url": image_url,
        "date": row.get("date"),
        # `result` and `tags` are what studio/selfrag/corpus.py reads. The
        # picture a prompt produced IS its result, so this is a rename, not a
        # new claim.
        "result": image_url,
        "tags": [t for t in (row.get("section") or row.get("category"), kind) if t],
        # Only the Midjourney flag syntax (--ar, --v, --sref) is evidence of a
        # target model, and the harvester already decided that when it set
        # `kind`. Prose rows get no model rather than a guessed one: the source
        # is half Midjourney and half nano-banana, and inventing a label for
        # the half nobody marked would be a claim, not a reading.
        "model": "midjourney" if kind == "flagged" else "",
        "model_marker": row.get("model"),
    }


def ingest(path: str | Path) -> dict:
    """Read a harvested file and write the normalised one. Three outcomes, with numbers."""
    src = Path(path)
    if not src.exists():
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"no harvested file at {src}: nothing was read, which is not 'no prompts'",
        }

    kept: list[dict] = []
    seen: set[tuple[str, str]] = set()
    checked = dropped = duplicates = 0
    for line in src.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        checked += 1
        try:
            row = json.loads(line)
        except ValueError:
            dropped += 1
            continue
        out = normalise(row)
        if out is None:
            dropped += 1
            continue
        # Deduplicate on (wording, image), not on wording alone. The same
        # prompt shown against two different results is two records on purpose
        # — for --sref and --cref that distinction is the entire point — and
        # collapsing them here would silently discard 539 of this corpus's
        # 4601 rows. Only a pair reprinted verbatim collapses.
        key = (out["prompt"], str(out.get("image_url") or ""))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        kept.append(out)

    if not kept:
        return {
            "outcome": FAIL,
            "checked": checked,
            "violations": dropped,
            "unmeasured": 0,
            "note": f"read {checked} lines, kept none: the shape is not what this boundary expects",
        }

    OUT.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8"
    )
    words = sorted(len(r["prompt"].split()) for r in kept)
    matched = sum(1 for r in kept if r["id"])
    return {
        "outcome": PASS,
        "checked": checked,
        "violations": dropped,
        "unmeasured": 0,
        "note": (
            f"kept {len(kept)}, dropped {dropped}, duplicates {duplicates}, "
            f"matched to a card {matched}, median words {words[len(words) // 2]}"
        ),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    report = ingest(sys.argv[1])
    print(f"{report['outcome']}: {report['note']}")
    raise SystemExit(0 if report["outcome"] == PASS else 1)
