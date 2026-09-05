"""Ask the operator to pay for a measurement, and never decide it yourself.

THE CORRECTION THIS MODULE IS

The base can be grown for free up to a point. Past that point the only way to
learn something is to run the generation and look at it, and running the
generation costs money on somebody's account. The owner's ruling, 2026-08-27:

    реальные замеры будем делать под конкретные задачи и с одобрения оператора

So a paid measurement is neither forbidden nor budgeted in advance. It is
PROPOSED — against a concrete task, with the exact test written out and the
price named — and then it waits. The agent files; a human decides.

WHY THE APPROVAL IS NOT A TOOL

`server.py` exposes `propose_measurement` and `measurement_proposals`. It does
NOT expose approval, and it never will: an agent that can approve its own
proposal has not been asked for permission, it has been given a wallet. The
only door to `approve` is `scripts/measurement.py`, run by the person whose
account is charged.

That is the same shape as `probe.py`'s absurd-value guard — the property
"it could not have spent this on its own" is something a reader can check in
the code rather than something a prompt promised.

WHAT A PROPOSAL MUST CARRY, AND WHY EACH PART IS REFUSED WHEN MISSING

`gap`      — what the base cannot answer today. Without it the measurement is
             a habit, not a question.
`test`     — the exact request to send and what to look at afterwards. A
             proposal nobody else could execute is a request for trust.
`cost_usd` — the price. "Name the price" was the instruction; an unnamed price
             is an unbounded one.
`cost_basis` — where that number came from (a published rate, a prior
             invoice). A price with no basis is a guess wearing a decimal
             point, and house rule I4 applies to it like any other constant.
`decides`  — what the two possible results would each mean. If both answers
             lead to the same next step, the measurement buys nothing.

AND ONE REFUSAL THAT IS NOT ABOUT PAPERWORK

A proposal for a claim the base already holds, freshly and uncontested, is
refused before it reaches the operator. Money spent re-learning a standing
fact is the failure this whole package was built to make visible.

WHAT HAPPENS TO AN OVERSPEND

If the measurement runs and costs more than was approved, the fact is STILL
written — the money is already gone and withholding the result wastes it
twice — but the outcome is `fail` and the violation names the overspend. A
guard that quietly swallowed it would report a clean ledger over a surprised
operator.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.mcp import advice
from studio.selfrag.facts import TIER_PROBE

__all__ = [
    "propose",
    "decide",
    "record_result",
    "proposals",
    "STATES",
    "STATE_PROPOSED",
    "STATE_APPROVED",
    "STATE_DECLINED",
    "STATE_RECORDED",
    "DEFAULT_LEDGER_PATH",
]

DEFAULT_LEDGER_PATH = (
    Path(__file__).resolve().parents[2] / "studio" / "knowledge" / "measurements.jsonl"
)

STATE_PROPOSED = "proposed"
STATE_APPROVED = "approved"
STATE_DECLINED = "declined"
STATE_RECORDED = "recorded"

#: The whole ladder a proposal can walk. Kept as a tuple so a typo in a
#: decision is refused rather than creating a fourth state nobody reads.
STATES: tuple[str, ...] = (
    STATE_PROPOSED,
    STATE_APPROVED,
    STATE_DECLINED,
    STATE_RECORDED,
)

#: The decisions the operator may hand down. `recorded` is not among them —
#: that state is reached by a result arriving, never by somebody saying so.
DECISIONS: tuple[str, ...] = (STATE_APPROVED, STATE_DECLINED)

#: CHOSEN. A test description shorter than this cannot name a request, a
#: model and a thing to look at. Not measured — it is a floor against the
#: one-line proposal ("try kling and see"), which is the shape that would make
#: this whole gate ceremonial.
MIN_TEST_CHARS = 60

#: CHOSEN, same reasoning, for the sentence explaining where the price came
#: from and for what the result would decide.
MIN_BASIS_CHARS = 12
MIN_DECIDES_CHARS = 20

#: CHOSEN. A proposal must be for a real task, so the task reference is
#: required and must be more than a word.
MIN_TASK_CHARS = 8


def _identity(model: str, attribute: str, test: str) -> str:
    """A proposal IS its (model, attribute, test). Filing the same one twice
    returns the standing row instead of a second one, so an agent that retries
    does not put three identical asks in front of the operator."""
    seed = "|".join(
        (
            str(model or "").strip().lower(),
            str(attribute or "").strip().lower(),
            " ".join(str(test or "").split()).lower(),
        )
    )
    return "mp-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10]


def _rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("id"):
            out.append(row)
    return out


def _latest(path: Path) -> dict[str, dict]:
    """The ledger is a log; the last row for an id is its current state."""
    latest: dict[str, dict] = {}
    for row in _rows(path):
        latest[str(row["id"])] = row
    return latest


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _already_known(model: str, attribute: str, facts_path: Path | None) -> str:
    """ "" when the base cannot answer this. A sentence when it can.

    Only a SETTLED answer blocks a proposal, and settled means three things at
    once: the sources agree (`pass` — `fail` is contradiction, which is one of
    the better reasons to go and measure), none of them is stale, and the best
    of them stands above blog tier (`claims` already reports blog-only as
    `could not measure`).
    """
    verdict = advice.store_for(facts_path).claims(model, attribute)
    if verdict.get("outcome") != PASS:
        return ""
    if verdict.get("unmeasured"):
        return ""
    rows = verdict.get("claims") or []
    best = rows[0] if rows else {}
    return (
        f"the base already answers {model}.{attribute} as {best.get('value')!r} at tier "
        f"{best.get('best_tier')}, from {verdict.get('checked')} agreeing source(s), none "
        "of them stale — withdraw or contest that claim if it is wrong, rather than paying "
        "to re-learn it"
    )


def propose(
    model: str,
    attribute: str,
    *,
    task: str,
    gap: str,
    test: str,
    cost_usd: float,
    cost_basis: str,
    decides: str,
    path: Path | None = None,
    facts_path: Path | None = None,
) -> dict:
    """File one paid measurement for the operator to approve or decline.

    Writes nothing to the fact base. The outcome is never `pass`: a filed
    proposal has measured nothing, so it reports `could not measure` with the
    id the operator will quote back.

    :param task: the concrete job that needs this. Approval is per task.
    :param cost_usd: what running it will cost, in dollars. 0.0 is allowed and
        means the test is free — it still goes past the operator, because a
        free test can still burn a rate limit on their account.
    """
    fields = {
        "model": str(model or "").strip(),
        "attribute": str(attribute or "").strip(),
        "task": str(task or "").strip(),
        "gap": str(gap or "").strip(),
        "test": " ".join(str(test or "").split()),
        "cost_basis": str(cost_basis or "").strip(),
        "decides": str(decides or "").strip(),
    }
    violations: list[str] = []
    for name, text in fields.items():
        if not text:
            violations.append(f"{name} is empty")
    try:
        price = float(cost_usd)
    except (TypeError, ValueError):
        price = -1.0
        violations.append("cost_usd is not a number — name the price")
    if price < 0:
        violations.append("cost_usd is negative")
    if fields["test"] and len(fields["test"]) < MIN_TEST_CHARS:
        violations.append(
            f"test is {len(fields['test'])} characters; under {MIN_TEST_CHARS} it cannot "
            "name a request, a model and a thing to look at"
        )
    if fields["cost_basis"] and len(fields["cost_basis"]) < MIN_BASIS_CHARS:
        violations.append("cost_basis does not say where the price came from")
    if fields["decides"] and len(fields["decides"]) < MIN_DECIDES_CHARS:
        violations.append("decides does not say what each result would mean")
    if fields["task"] and len(fields["task"]) < MIN_TASK_CHARS:
        violations.append("task does not name a concrete job")

    if violations:
        return {
            "outcome": FAIL,
            "checked": len(fields) + 1,
            "violations": len(violations),
            "unmeasured": 0,
            "id": "",
            "note": "not filed: " + "; ".join(violations),
        }

    settled = _already_known(fields["model"], fields["attribute"], facts_path)
    if settled:
        return {
            "outcome": FAIL,
            "checked": len(fields) + 2,
            "violations": 1,
            "unmeasured": 0,
            "id": "",
            "note": "not filed: " + settled,
        }

    ledger = path or DEFAULT_LEDGER_PATH
    identity = _identity(fields["model"], fields["attribute"], fields["test"])
    standing = _latest(ledger).get(identity)
    if standing is not None:
        return {
            "outcome": UNMEASURED,
            "checked": 1,
            "violations": 0,
            "unmeasured": 1,
            "id": identity,
            "state": str(standing.get("state", "")),
            "note": (
                f"already filed as {identity}, state {standing.get('state')!r} — "
                "not filed twice, so the operator sees one ask"
            ),
        }

    row = {
        "id": identity,
        "state": STATE_PROPOSED,
        "model": fields["model"],
        "attribute": fields["attribute"],
        "task": fields["task"],
        "gap": fields["gap"],
        "test": fields["test"],
        "cost_usd": round(price, 4),
        "cost_basis": fields["cost_basis"],
        "decides": fields["decides"],
        "filed_on": date.today().isoformat(),
    }
    _append(ledger, row)
    return {
        "outcome": UNMEASURED,
        "checked": 1,
        "violations": 0,
        "unmeasured": 1,
        "id": identity,
        "state": STATE_PROPOSED,
        "note": (
            f"filed {identity}: {fields['model']}.{fields['attribute']} for ${price:.2f}. "
            "Nothing has been measured and nothing will run until the operator approves it "
            "with `python scripts/measurement.py approve " + identity + "`."
        ),
    }


def decide(
    proposal_id: str,
    decision: str,
    *,
    operator: str,
    note: str = "",
    path: Path | None = None,
) -> dict:
    """Record the operator's answer. NOT reachable from the MCP server.

    Kept in this module rather than in the script so the state machine has one
    home, but the only caller is `scripts/measurement.py`, which a person runs.
    """
    ledger = path or DEFAULT_LEDGER_PATH
    verdict = str(decision or "").strip().lower()
    who = str(operator or "").strip()
    if verdict not in DECISIONS:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": f"{decision!r} is not one of {', '.join(DECISIONS)}",
        }
    if not who:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": "an approval with nobody's name on it is not an approval",
        }
    standing = _latest(ledger).get(str(proposal_id).strip())
    if standing is None:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": f"no proposal {proposal_id!r} in {ledger}",
        }
    if standing.get("state") == STATE_RECORDED:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": (
                f"{proposal_id} has already been measured and recorded; approving it now "
                "would say the spend was authorised before it happened"
            ),
        }
    row = dict(standing)
    row["state"] = verdict
    row["decided_by"] = who
    row["decided_on"] = date.today().isoformat()
    row["decision_note"] = str(note or "").strip()
    _append(ledger, row)
    return {
        "outcome": PASS,
        "checked": 1,
        "violations": 0,
        "unmeasured": 0,
        "id": row["id"],
        "state": verdict,
        "note": f"{proposal_id} is {verdict} by {who}",
    }


def record_result(
    proposal_id: str,
    value: str,
    source_url: str,
    measured_on: str,
    *,
    evidence: str,
    actual_cost_usd: float,
    path: Path | None = None,
    facts_path: Path | None = None,
) -> dict:
    """Put an approved measurement's result into the base at `probe` tier.

    Refuses outright unless the proposal stands `approved`. That refusal is
    the whole mechanism: an agent that ran the generation anyway has no door
    through which to make the result look sanctioned.

    :param source_url: where the result can be seen — the API response saved to
        the repository, the job URL, the rendered file. `probe` is a method
        rung and taken as stated, but the URL still has to exist so somebody
        else can go and disagree.
    :param actual_cost_usd: what it really cost. Over the approved figure the
        fact is still written and the outcome is `fail`, so the overspend is
        reported rather than absorbed.
    """
    ledger = path or DEFAULT_LEDGER_PATH
    standing = _latest(ledger).get(str(proposal_id).strip())
    if standing is None:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": f"no proposal {proposal_id!r} in {ledger}",
        }
    state = str(standing.get("state", ""))
    if state != STATE_APPROVED:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": (
                f"{proposal_id} stands {state!r}, not {STATE_APPROVED!r} — a result cannot "
                "be recorded against a spend nobody authorised"
            ),
        }
    fields = {
        "value": str(value or "").strip(),
        "source_url": str(source_url or "").strip(),
        "measured_on": str(measured_on or "").strip(),
        "evidence": str(evidence or "").strip(),
    }
    missing = [name for name, text in fields.items() if not text]
    if missing:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": len(missing),
            "unmeasured": 0,
            "note": "not recorded: empty " + ", ".join(missing),
        }

    written = advice.record(
        str(standing["model"]),
        str(standing["attribute"]),
        fields["value"],
        fields["source_url"],
        TIER_PROBE,
        fields["measured_on"],
        note=(
            f"MEASURED under approved proposal {proposal_id} for task "
            f"{standing.get('task')!r}; test: {standing.get('test')}; observed: "
            f"{fields['evidence']}"
        ),
        read_directly=True,
        path=facts_path,
    )
    if written.get("outcome") != PASS:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": "the fact base refused the result: " + str(written.get("note", "")),
        }

    try:
        spent = float(actual_cost_usd)
    except (TypeError, ValueError):
        spent = -1.0
    approved = float(standing.get("cost_usd") or 0.0)
    overspent = spent < 0 or spent > approved

    row = dict(standing)
    row["state"] = STATE_RECORDED
    row["value"] = fields["value"]
    row["result_url"] = fields["source_url"]
    row["measured_on"] = fields["measured_on"]
    row["evidence"] = fields["evidence"]
    row["actual_cost_usd"] = round(spent, 4)
    row["overspent"] = bool(overspent)
    _append(ledger, row)

    if overspent:
        return {
            "outcome": FAIL,
            "checked": 2,
            "violations": 1,
            "unmeasured": 0,
            "id": row["id"],
            "state": STATE_RECORDED,
            "note": (
                f"the fact IS recorded — the money is already spent and withholding the "
                f"result would waste it twice — but ${spent:.2f} was charged against an "
                f"approval for ${approved:.2f}"
            ),
        }
    return {
        "outcome": PASS,
        "checked": 2,
        "violations": 0,
        "unmeasured": 0,
        "id": row["id"],
        "state": STATE_RECORDED,
        "note": (
            f"{standing['model']}.{standing['attribute']} = {fields['value']!r} recorded at "
            f"tier {TIER_PROBE} for ${spent:.2f}"
        ),
    }


def proposals(*, state: str = "", path: Path | None = None) -> dict:
    """What is filed, and what is waiting on a person.

    `pass` when something stands, `could not measure` when the ledger is empty
    — never `pass` on nothing, because "no proposals" and "no pending
    proposals" are answers a reader would otherwise confuse.
    """
    ledger = path or DEFAULT_LEDGER_PATH
    wanted = str(state or "").strip().lower()
    if wanted and wanted not in STATES:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "proposals": [],
            "note": f"{state!r} is not one of {', '.join(STATES)}",
        }
    rows = sorted(_latest(ledger).values(), key=lambda row: str(row.get("id", "")))
    shown = [row for row in rows if not wanted or str(row.get("state")) == wanted]
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.get("state"))] = counts.get(str(row.get("state")), 0) + 1
    if not rows:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "proposals": [],
            "by_state": {},
            "note": f"no measurement proposals have ever been filed ({ledger})",
        }
    waiting = counts.get(STATE_PROPOSED, 0)
    return {
        "outcome": PASS,
        "checked": len(rows),
        "violations": 0,
        "unmeasured": 0,
        "proposals": shown,
        "by_state": counts,
        "note": (
            f"{len(rows)} proposal(s); {waiting} waiting on the operator; "
            f"${sum(float(r.get('actual_cost_usd') or 0.0) for r in rows):.2f} spent so far"
        ),
    }
