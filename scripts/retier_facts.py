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

APPEND-ONLY SINCE 2026-10-15. `--write` used to rewrite the whole file, and
the file is a log guarded by `scripts/check_append_only.py` («прежние на
месте»). A rewrite would also have stamped a tier onto the 581 withdrawal rows
(`"withdrawn": true` rows carry no tier) and re-tiered `operator` rows, a
method rung this script predates. Now: only the LATEST live row of each claim
(the row `load_facts` reads) is decided, and where the decision differs, the
decided row is APPENDED — the latest row wins, so the claim moves and the
history stays. A second run appends nothing. `read_directly` is only filled
in (None -> False); an explicit True stated by the recorder is not flipped by
a refusal measured later.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.mcp import fetch  # noqa: E402
from studio.selfrag import source_hosts  # noqa: E402
from studio.selfrag.facts import (  # noqa: E402
    DEFAULT_FACTS_PATH,
    TIER_BLOG,
    TIER_PORTAL,
    TIER_PROBE,
    TIER_VENDOR,
)

#: The only rungs a URL decides. Anything else — the method rungs (`probe`,
#: `paper`, `benchmark`), `operator`, and whatever the ladder gains later — is
#: the recorder's to state. NAMED BY WHAT IS REWRITTEN since 2026-10-15: the
#: earlier list of rungs NOT to rewrite (`METHOD_TIERS`) predated `operator`,
#: and a dry run would have moved 9 operator rows to `blog`.
IDENTITY_TIERS = (TIER_VENDOR, TIER_PORTAL, TIER_BLOG)

#: Appended to the note of a re-tiered row, so the duplicate says why it exists.
RETIER_NOTE = "[retier: source_hosts]"

#: The phrase the earlier session used when it recorded a vendor page it had
#: only seen quoted. Matched as a substring, lowercased.
SUMMARY_MARKER = "read via summary"


def refused_hosts() -> set[str]:
    """Хосты, закрытые политикой ПО ПОСЛЕДНЕМУ записанному состоянию.

    ЖУРНАЛ ОТКАЗОВ — ЖУРНАЛ СОСТОЯНИЙ, А НЕ СПИСОК УПОМИНАНИЙ. Строка `open`
    снимает прежний отказ; собирать хосты по любому упоминанию значит считать
    закрытым всё, что когда-либо отказало хоть раз.

    ИЗМЕРЕНО 2026-09-06: в журнале 274 хоста, закрыты по последнему состоянию
    210. Прежний разбор возвращал все 274, и на живой базе это 1007 строк,
    которым повторный прогон поставил бы `read_directly = False` ЗРЯ — при
    том, что шапка этого файла обещает: «повторный прогон безопасен, это
    чистая функция файла». Обещание не выполнялось.

    Тот же класс дефекта независимая проверка нашла накануне в собственном
    подсчёте и записала числом: «закрыт» без учёта поздних проб завысил ответ
    в 983 раза. Здесь он вторым местом (правило И7: нашёл дефект — грепни по
    его форме), и разбор теперь ОДИН на весь проект (Е1).
    """
    состояния = fetch.последние_состояния()
    return {h for h, с in состояния.items() if с == fetch.STATE_REFUSED}


def decide(row: dict, refused: set[str]) -> dict:
    """The row as it should read. Pure: same inputs, same output, every run."""
    out = dict(row)
    if row.get("withdrawn"):
        return out
    tier = str(row.get("tier", "")).strip().lower()
    if tier in IDENTITY_TIERS or not tier:
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
    elif host and host in refused and row.get("read_directly") is not True:
        out["read_directly"] = False
    else:
        out["read_directly"] = row.get("read_directly")
    return out


def claim_key(row: dict) -> tuple[str, str, str, str]:
    """The key `load_facts` reads a claim by (model, attribute, value, URL)."""
    return (
        str(row.get("model", "")).strip().lower(),
        str(row.get("attribute", "")).strip().lower(),
        str(row.get("value", "")),
        str(row.get("source_url", "")),
    )


def plan(lines: list[str], refused: set[str]) -> list[tuple[dict, dict]]:
    """(latest row, decided row) for every live claim whose decision differs."""
    latest: dict[tuple[str, str, str, str], dict] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        row = json.loads(stripped)
        latest[claim_key(row)] = row
    out: list[tuple[dict, dict]] = []
    for row in latest.values():
        if row.get("withdrawn"):
            continue
        new = decide(row, refused)
        if new.get("tier") != row.get("tier") or new.get("read_directly") != row.get(
            "read_directly"
        ):
            note = str(new.get("note") or "")
            if RETIER_NOTE not in note:
                new["note"] = f"{note} {RETIER_NOTE}".strip()
            out.append((row, new))
    return out


def main() -> int:
    write = "--write" in sys.argv[1:]
    refused = refused_hosts()
    print(f"hosts measured refused: {len(refused)}")

    text = DEFAULT_FACTS_PATH.read_text(encoding="utf-8")
    changes = plan(text.splitlines(), refused)
    moved: Counter[str] = Counter()
    for row, new in changes:
        what = (
            f"{row.get('tier')} -> {new.get('tier')}"
            if new.get("tier") != row.get("tier")
            else f"read_directly {row.get('read_directly')} -> {new.get('read_directly')}"
        )
        moved[what] += 1
        print(
            f"  {str(row.get('model')):16} {str(row.get('attribute')):24} {what:24} "
            f"{source_hosts.host_of(str(row.get('source_url', '')))}"
        )
    print(f"\nclaims to re-state: {len(changes)}")
    for move, n in sorted(moved.items()):
        print(f"  {move:32} {n}")

    if write and changes:
        tail = "" if text.endswith("\n") else "\n"
        with DEFAULT_FACTS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(
                tail + "".join(json.dumps(new, ensure_ascii=False) + "\n" for _, new in changes)
            )
        print(f"\nappended {len(changes)} row(s) to {DEFAULT_FACTS_PATH}")
    elif not write:
        print("\ndry run; pass --write to append")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
