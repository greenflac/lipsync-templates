"""Re-tier `model_facts.jsonl` onto the owner's ladder, and record what was read.

ONE-OFF, kept in the repository because a migration that ran once from a chat
window is a migration nobody can check. Re-running it is safe: it is a pure
function of the file plus the two evidence sources below, so a second run
changes nothing.

WHAT IT DECIDES, AND FROM WHAT

`tier` — for the identity rungs only (`vendor`, `portal`, `blog`), from
`source_hosts.classify`. Rows already declaring a METHOD rung (`probe`,
`paper`, `benchmark`) keep it: no URL can tell you whether an API was asked or
whether a method was published, so those are the recorder's to state and not
this script's to overwrite.

`read_directly` — False only where there is evidence it was NOT read:

    1. the note says so ("read via summary")
    2. the host is recorded in `denied_hosts.jsonl` as refused by the egress
       policy, so nothing in this environment could have opened it

    plus: the one `probe` row is True — the API answered us, which is the
    reading.

Everything else stays None. Not recorded is not the same as not read, and
guessing either way would invent evidence.

Run:  python scripts/retier_facts.py [--write]
Without `--write` it only prints what it would change.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.mcp.fetch import DENIED_PATH  # noqa: E402
from studio.selfrag import source_hosts  # noqa: E402
from studio.selfrag.facts import (  # noqa: E402
    DEFAULT_FACTS_PATH,
    TIER_BLOG,
    TIER_PORTAL,
    TIER_PROBE,
    TIER_VENDOR,
)

#: Rungs decided by how the fact was obtained, which this script never rewrites.
METHOD_TIERS = ("probe", "paper", "benchmark")

#: The phrase the earlier session used when it recorded a vendor page it had
#: only seen quoted. Matched as a substring, lowercased.
SUMMARY_MARKER = "read via summary"


def refused_hosts() -> set[str]:
    """Hosts measured refused by the egress policy, from the recorded refusals."""
    if not DENIED_PATH.is_file():
        return set()
    hosts = set()
    for line in DENIED_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            hosts.add(str(json.loads(line).get("host", "")).lower())
        except ValueError:
            continue
    return {h for h in hosts if h}


def decide(row: dict, refused: set[str]) -> dict:
    """The row as it should read. Pure: same inputs, same output, every run."""
    out = dict(row)
    tier = str(row.get("tier", "")).strip().lower()
    if tier not in METHOD_TIERS:
        out["tier"] = source_hosts.classify(
            str(row.get("model", "")),
            str(row.get("source_url", "")),
            vendor_tier=TIER_VENDOR,
            portal_tier=TIER_PORTAL,
            blog_tier=TIER_BLOG,
        )

    host = source_hosts.host_of(str(row.get("source_url", "")))
    if tier == TIER_PROBE:
        out["read_directly"] = True
    elif SUMMARY_MARKER in str(row.get("note", "")).lower():
        out["read_directly"] = False
    elif host and host in refused:
        out["read_directly"] = False
    else:
        out["read_directly"] = row.get("read_directly")
    return out


def main() -> int:
    write = "--write" in sys.argv[1:]
    refused = refused_hosts()
    print(f"hosts measured refused: {len(refused)}")

    lines = DEFAULT_FACTS_PATH.read_text(encoding="utf-8").splitlines()
    out_lines: list[str] = []
    moved: Counter[str] = Counter()
    read_flags: Counter[str] = Counter()
    changed = 0

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            out_lines.append(line)
            continue
        row = json.loads(stripped)
        new = decide(row, refused)
        if new["tier"] != row.get("tier"):
            moved[f"{row.get('tier')} -> {new['tier']}"] += 1
            changed += 1
            print(
                f"  {row['model']:16} {row['attribute']:24} "
                f"{row.get('tier'):8} -> {new['tier']:8} "
                f"{source_hosts.host_of(str(row.get('source_url', '')))}"
            )
        read_flags[str(new.get("read_directly"))] += 1
        out_lines.append(json.dumps(new, ensure_ascii=False))

    print(
        f"\nrows {len([x for x in lines if x.strip() and not x.startswith('//')])}, "
        f"tier changed {changed}"
    )
    for move, n in sorted(moved.items()):
        print(f"  {move:24} {n}")
    print("read_directly:", dict(sorted(read_flags.items())))

    if write:
        DEFAULT_FACTS_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        print(f"\nwritten to {DEFAULT_FACTS_PATH}")
    else:
        print("\ndry run; pass --write to apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
