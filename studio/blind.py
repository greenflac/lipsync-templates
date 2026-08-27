"""Blind A/B instrument for the acceptance criterion: agent prompt against human prompt.

The owner accepts the prompt agent only if, on the same briefs, its prompts beat
hand-written ones under a judge who does not know which prompt is whose. This
module is that comparison instrument — it builds the pairs, hides the
authorship, checks that the hiding held, and unwinds the assignment when the
verdicts come back. It knows nothing about the agent and nothing about the
judge, so it can be built and proved before either exists.

Public surface: `make_pair`, `judge_payload`, `leak_check`, `score`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

__all__ = [
    "AUTHORSHIP_PHRASE",
    "BANNED_KEYS",
    "DECISIVE_MIN",
    "Pair",
    "SAMPLE_MIN",
    "SIDE_WORDS",
    "VERDICTS",
    "WIN_SHARE_MIN",
    "judge_payload",
    "leak_check",
    "make_pair",
    "score",
]

# CHOSEN (this module's author, 2026-08-26, to match the acceptance gate).
# Why: a sign test on fewer judged pairs cannot separate a real preference from
# a coin, so a short run must not be allowed to look like a verdict at all.
SAMPLE_MIN = 20

# CALCULATED (one-sided sign test, not measured on data): a unanimous run of n
# decisive pairs has p = 0.5**n; 0.5**5 = 0.031 < 0.05 while 0.5**4 = 0.063 is
# already above it. Why it exists at all: pairs the judge called a tie carry no
# direction, so a sample can clear SAMPLE_MIN and still hold no evidence.
DECISIVE_MIN = 5

# CHOSEN (this module's author, 2026-08-26). Why not 0.50: at parity the agent
# has not beaten anybody, and the owner's criterion is "beats the human", not
# "is not obviously worse". The band between the two sides is deliberately not
# a third verdict — it is measured non-acceptance, which is a FAIL, while
# UNMEASURED stays reserved for "we could not look".
WIN_SHARE_MIN = 0.55

VERDICTS = ("a", "b", "tie")

# Bare values that name an arm of the comparison. A payload field whose whole
# value is one of these is a label, whatever the field is called.
SIDE_WORDS = frozenset(
    {"agent", "human", "ai", "model", "machine", "handwritten", "baseline", "bot"}
)

# Field names that carry the assignment by convention rather than by wording.
BANNED_KEYS = frozenset(
    {
        "a_is_agent",
        "arm",
        "assignment",
        "author",
        "authored_by",
        "b_is_agent",
        "condition",
        "is_agent",
        "origin",
        "provenance",
        "side",
        "source",
        "written_by",
    }
)

# Why a phrase and not the bare word "agent": a prompt may legitimately talk
# about an agent, a human face, or a model — measured on the gate's own
# fixtures, whose prompt bodies contain the word "agent" in every clean pair.
# A bare-substring rule would call every honest payload a leak and would
# therefore never be trusted. What is banned is a *claim of authorship*.
AUTHORSHIP_PHRASE = re.compile(
    r"\b(?:written|authored|produced|generated|composed|created|made)\s+by\s+"
    r"(?:the\s+|a\s+|an\s+)?(?:" + "|".join(sorted(SIDE_WORDS)) + r")\b"
    r"|\b(?:this|prompt|side|option|variant)\s+(?:is|was)\s+"
    r"(?:the\s+|a\s+|an\s+)?(?:" + "|".join(sorted(SIDE_WORDS)) + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Pair:
    """One blinded comparison: two prompts for the same brief, sides already drawn.

    `a_is_agent` is the key to the blinding and never reaches the judge.
    """

    pair_id: str
    brief_id: str
    a: str
    b: str
    a_is_agent: bool


def _digest(brief_id: str, salt: str) -> str:
    """Return the hex digest that decides one pair's side and id.

    Why a hash and not `random`: a run that cannot be replayed cannot be
    audited, and a run keyed on the clock cannot be replayed. The salt is the
    only knob, so re-blinding a whole batch is one changed string.
    """
    material = f"{salt}\x00{brief_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def make_pair(*, brief_id: str, agent_prompt: str, human_prompt: str, salt: str) -> Pair:
    """Draw the A/B sides for one brief, deterministically from (brief_id, salt).

    Args:
        brief_id: identifier of the brief both prompts answer.
        agent_prompt: the prompt written by the agent under test.
        human_prompt: the hand-written prompt it is measured against.
        salt: run-scoped string; the same salt reproduces the same assignment,
            a different salt re-draws every side.

    Returns:
        A `Pair` whose `a`/`b` are the two prompts in drawn order.

    Example:
        >>> p = make_pair(brief_id="b1", agent_prompt="A", human_prompt="H", salt="s")
        >>> (p.a, p.b) == (("A", "H") if p.a_is_agent else ("H", "A"))
        True
    """
    if not brief_id:
        raise ValueError("brief_id is required: a pair with no brief cannot be scored")
    if not salt:
        raise ValueError("salt is required: an unsalted run cannot be re-blinded")
    digest = _digest(brief_id, salt)
    a_is_agent = int(digest[:8], 16) % 2 == 0
    return Pair(
        pair_id=f"{brief_id}-{digest[8:20]}",
        brief_id=brief_id,
        a=agent_prompt if a_is_agent else human_prompt,
        b=human_prompt if a_is_agent else agent_prompt,
        a_is_agent=a_is_agent,
    )


def judge_payload(pairs: Iterable[Pair]) -> list[dict[str, str]]:
    """Render the pairs as the records handed to the judge, authorship removed.

    Args:
        pairs: pairs from `make_pair`.

    Returns:
        A list of dicts with exactly `pair_id`, `brief_id`, `a`, `b`.

    Example:
        >>> item = judge_payload([make_pair(brief_id="b1", agent_prompt="A",
        ...     human_prompt="H", salt="s")])[0]
        >>> sorted(item)
        ['a', 'b', 'brief_id', 'pair_id']
    """
    # Built by naming the four fields, not by stripping fields off the Pair: a
    # later field added to Pair must not travel to the judge by default.
    return [
        {"pair_id": p.pair_id, "brief_id": p.brief_id, "a": p.a, "b": p.b}
        for p in pairs
    ]


def _leaks_in(key: str, value: Any) -> list[str]:
    """Return the leak descriptions found in one payload field."""
    found: list[str] = []
    if key.strip().lower() in BANNED_KEYS:
        found.append(f"field {key!r} names the assignment")
    if isinstance(value, bool):
        # A bare boolean next to two prompts is an assignment in disguise.
        found.append(f"field {key!r} carries a bare flag")
        return found
    if isinstance(value, str):
        bare = value.strip().strip(".,:;!?-()[]").lower()
        if bare in SIDE_WORDS:
            found.append(f"field {key!r} is the bare label {value.strip()!r}")
        match = AUTHORSHIP_PHRASE.search(value)
        if match:
            found.append(f"field {key!r} claims authorship: {match.group(0)!r}")
    return found


def leak_check(payload: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Judge whether a judge-payload still hides who wrote what.

    Args:
        payload: the records produced by `judge_payload`, or any list of dicts.

    Returns:
        `{"outcome": PASS|FAIL|UNMEASURED, "checked": int, "violations": int,
          "unmeasured": int, "leaks": list[str], "note": str}`, where `checked`
        counts the fields actually inspected. Zero inspected fields is
        UNMEASURED, never PASS.

    Example:
        >>> leak_check(judge_payload([make_pair(brief_id="b1", agent_prompt="A",
        ...     human_prompt="H", salt="s")]))["outcome"]
        'pass'
    """
    checked = 0
    unmeasured = 0
    leaks: list[str] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            unmeasured += 1
            leaks.append(f"record {index} is not a mapping, so it was not read")
            continue
        if not {"a", "b"} <= set(item):
            # A record without both prompts is not the thing this check judges.
            unmeasured += 1
            leaks.append(f"record {index} has no a/b prompts, so it was not read")
        for key, value in item.items():
            checked += 1
            leaks.extend(f"record {index}: {why}" for why in _leaks_in(str(key), value))
    violations = len(leaks) - unmeasured
    if checked == 0:
        outcome = UNMEASURED
        note = "no field was inspected, so blinding is unproven"
    elif violations:
        outcome = FAIL
        note = f"{violations} field(s) name the author"
    elif unmeasured:
        outcome = UNMEASURED
        note = f"{unmeasured} record(s) could not be read"
    else:
        outcome = PASS
        note = f"{checked} field(s) inspected, none names the author"
    return {
        "outcome": outcome,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
        "leaks": leaks,
        "note": note,
    }


def score(pairs: Iterable[Pair], verdicts: Mapping[str, str]) -> dict[str, Any]:
    """Unwind the blinding and report the comparison as counts, never as a flag.

    Args:
        pairs: the pairs the judge was shown.
        verdicts: mapping of `pair_id` to `"a"`, `"b"` or `"tie"`. A missing or
            unusable entry is counted as unmeasured, never as a tie.

    Returns:
        `{"outcome": PASS|FAIL|UNMEASURED, "agent_wins": int, "human_wins": int,
          "ties": int, "checked": int, "unmeasured": int, "violations": int,
          "decisive": int, "agent_share": float|None, "note": str}`.

    Example:
        >>> pairs = [make_pair(brief_id=f"b{i}", agent_prompt="A",
        ...     human_prompt="H", salt="s") for i in range(3)]
        >>> score(pairs, {})["outcome"]
        'could not measure'
    """
    pairs = list(pairs)
    agent_wins = human_wins = ties = 0
    unjudged = 0
    violations = 0
    seen: set[str] = set()
    for pair in pairs:
        if pair.pair_id in seen:
            # Two pairs under one id means one verdict is being counted twice.
            violations += 1
            continue
        seen.add(pair.pair_id)
        verdict = verdicts.get(pair.pair_id)
        if verdict is None:
            unjudged += 1
            continue
        if not isinstance(verdict, str) or verdict.strip().lower() not in VERDICTS:
            violations += 1
            continue
        verdict = verdict.strip().lower()
        if verdict == "tie":
            ties += 1
        elif (verdict == "a") == pair.a_is_agent:
            agent_wins += 1
        else:
            human_wins += 1
    violations += sum(1 for pair_id in verdicts if pair_id not in seen)

    checked = agent_wins + human_wins + ties
    decisive = agent_wins + human_wins
    # The floor is part of what was not measured: 19 judged pairs are not a
    # sample with one pair missing, they are a sample that decides nothing. The
    # two shortfalls are combined with max, not added: they describe the same
    # missing evidence seen from two sides.
    unmeasured = unjudged + violations + max(
        0, SAMPLE_MIN - checked, DECISIVE_MIN - decisive
    )
    share = (agent_wins / decisive) if decisive else None

    if checked < SAMPLE_MIN:
        outcome = UNMEASURED
        note = f"{checked} judged pairs, the floor is {SAMPLE_MIN}"
    elif decisive < DECISIVE_MIN:
        outcome = UNMEASURED
        note = (
            f"{decisive} pair(s) carried a direction, the floor is "
            f"{DECISIVE_MIN}; {ties} tie(s) decide nothing either way"
        )
    elif share is not None and share >= WIN_SHARE_MIN:
        outcome = PASS
        note = f"the agent took {share:.0%} of {decisive} decisive pairs"
    else:
        outcome = FAIL
        note = (
            f"the agent took {share:.0%} of {decisive} decisive pairs, "
            f"below the acceptance share {WIN_SHARE_MIN:.0%} (CHOSEN, not "
            f"measured, and not yet confirmed by the owner)"
        )
    return {
        "outcome": outcome,
        "agent_wins": agent_wins,
        "human_wins": human_wins,
        "ties": ties,
        "checked": checked,
        "unmeasured": unmeasured,
        "violations": violations,
        "decisive": decisive,
        "agent_share": share,
        "note": note,
    }
