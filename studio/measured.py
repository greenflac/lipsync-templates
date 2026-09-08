"""Numbers this project measured about ITSELF, one per line, with how.

WHY THIS FILE EXISTS, AND WHAT IT REPLACES

The handoff had become the archive. One branch's `HANDOFF_*.md` reached 2330
lines and ~39 000 tokens, and every session read all of it to find three numbers
— paying that cost in context and in drift on every single turn. The owner
called it what it is, and the project's own harness rules already said so:
facts about the project do not go in the handoff, they have their own address.

This is that address for one specific kind of fact: a number we measured about
our own instruments, corpus or pipeline. Not what a vendor claims about a model
— that is `model_facts.jsonl`, keyed by tier and source URL. Not a request to
spend money on a probe — that is `measurements.jsonl`, the proposal ledger,
whose name collides with this one and whose purpose does not.

WHAT A RECORD HAS TO CARRY, AND WHY EACH FIELD IS MANDATORY

`origin` marks where the number came from: ИЗМЕРЕНО (a run, and `method` says
which), РАСЧЁТ (derived from documentation, not from a run) or ВЫБРАНО (a
judgement, and `method` says whose and out of what). A chosen number presented
as a measured one is the defect this field exists to stop: nobody dares touch
it afterwards.

`outcome` is three-valued. A negative result is a first-class record here, with
its number and its conditions — a series of failures is a measured boundary, and
without it the next session turns the same knobs again.

`script` or `method` — a number nobody can re-derive is a rumour with a date on
it. One of the two is required and the gate refuses a record without either.

`supersedes` keeps the file a LOG rather than a mutable table. A number that
replaced an earlier one names it, so the correction stays visible instead of
quietly overwriting what somebody may have quoted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STORE = Path(__file__).with_name("knowledge") / "measured.jsonl"

#: Rule И4, as data. A number's provenance is one of exactly these.
ORIGINS = ("ИЗМЕРЕНО", "РАСЧЁТ", "ВЫБРАНО")

#: Rule Р1, as data. Three outcomes, and the third is not a failure.
OUTCOMES = ("годно", "не годно", "не смогли")

#: Every record carries these or it does not land. A row that travels without
#: its origin is a row whose origin gets forgotten.
REQUIRED = ("id", "subject", "origin", "outcome", "measured_on", "note")


@dataclass(frozen=True)
class Problem:
    """One thing wrong with one record, named precisely enough to fix."""

    record_id: str
    field: str
    said: str


def problems(record: dict[str, Any]) -> list[Problem]:
    """What is wrong with this record. Empty means nothing is.

    Kept out of any entry point (rule T5) so the gate's decision is reachable
    from a test without a file on disk.
    """
    rid = str(record.get("id") or "<без id>")
    found: list[Problem] = []
    for field in REQUIRED:
        if not str(record.get(field) or "").strip():
            found.append(Problem(rid, field, "обязательное поле пустое или отсутствует"))
    origin = str(record.get("origin") or "")
    if origin and origin not in ORIGINS:
        found.append(Problem(rid, "origin", f"{origin!r} не из {ORIGINS}"))
    outcome = str(record.get("outcome") or "")
    if outcome and outcome not in OUTCOMES:
        found.append(Problem(rid, "outcome", f"{outcome!r} не из {OUTCOMES}"))
    if not str(record.get("script") or "").strip() and not str(record.get("method") or "").strip():
        found.append(
            Problem(rid, "script/method", "ни скрипта, ни метода — число нельзя перепроверить")
        )
    if origin == "ВЫБРАНО" and not str(record.get("method") or "").strip():
        found.append(
            Problem(rid, "method", "ВЫБРАНО без method: не сказано, кем и из чего выбрано")
        )
    return found


def load(path: Path = STORE) -> list[dict[str, Any]]:
    """Every record, oldest first. Comment lines start with `//`, as elsewhere here."""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("//"):
            continue
        rows.append(json.loads(text))
    return rows


def current(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The records nothing later has superseded.

    A log, not a table: a corrected number does not overwrite the one it
    replaced, so a reader who quoted the old value can still find out what
    happened to it.
    """
    replaced = {str(r.get("supersedes")) for r in rows if r.get("supersedes")}
    return [r for r in rows if str(r.get("id")) not in replaced]


def find(rows: list[dict[str, Any]], term: str) -> list[dict[str, Any]]:
    """Records whose subject or note mentions `term`, case-insensitively.

    The whole point of this store over the handoff: a session reads the three
    records it needs instead of forty thousand tokens of prose.
    """
    needle = term.strip().lower()
    if not needle:
        return rows
    return [
        r
        for r in rows
        if needle in f"{r.get('subject', '')} {r.get('note', '')} {r.get('script', '')}".lower()
    ]
