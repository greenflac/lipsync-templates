"""Gate: the acceptance instrument for the specialist.

The owner's criterion (2026-08-26): the agent is accepted if, on the same
briefs, its prompts beat hand-written prompts in a comparison where the judge
does not know which prompt is whose. This module guards the instrument, not
the agent — the counter is built before the lever it measures.

Four claims are guarded:

1. Nothing the judge receives says which side a prompt came from.
2. The blinding is checkable: a payload that does leak is detected, and the
   detector fires on a planted leak (negative control).
3. The assignment is not constant. An A/B split that always puts the agent on
   side A is not blind, it is a convention the judge can learn.
4. A sample too small to decide reports "could not measure", never a tie.

Written before the implementation, never edited by the agent implementing it.
"""

from __future__ import annotations

import json
import unittest

from lipsync.fork_identity import PASS, UNMEASURED
from studio import blind as B

# CHOSEN: below this many judged pairs the comparison decides nothing. A sign
# test on fewer pairs cannot separate a real preference from a coin.
SAMPLE_MIN = 20

# CHOSEN: neither side may take more than this share of the A slots, or the
# assignment carries information about who wrote what. Same reasoning as the
# judge's near-constant-axis guard: a channel that says one thing is not a
# channel.
SIDE_SHARE_MAX = 0.70

SIDE_LABELS = ("agent", "human")

BRIEFS = [f"brief-{i:03d}" for i in range(40)]


def _pairs(salt: str = "salt-a") -> list:
    return [
        B.make_pair(
            brief_id=b,
            agent_prompt=f"agent wording for {b}",
            human_prompt=f"human wording for {b}",
            salt=salt,
        )
        for b in BRIEFS
    ]


class TheJudgeCannotSeeWhoWroteWhat(unittest.TestCase):
    def test_the_payload_carries_no_side_label(self) -> None:
        text = json.dumps(B.judge_payload(_pairs()), ensure_ascii=False)
        for label in SIDE_LABELS:
            self.assertNotIn(
                f'"{label}"',
                text,
                f"the judge payload names the side {label!r}",
            )

    def test_the_payload_carries_no_assignment_field(self) -> None:
        for item in B.judge_payload(_pairs()):
            self.assertNotIn("assignment", item)
            self.assertNotIn("side", item)


class TheBlindingIsChecked(unittest.TestCase):
    def test_a_clean_payload_passes_the_leak_check(self) -> None:
        self.assertEqual(
            B.leak_check(B.judge_payload(_pairs()))["outcome"], PASS
        )

    def test_a_planted_leak_is_caught(self) -> None:
        """Negative control: the detector must be able to say no."""
        payload = B.judge_payload(_pairs())
        payload[0]["a"] = payload[0]["a"] + " (written by the agent)"
        self.assertNotEqual(
            B.leak_check(payload)["outcome"],
            PASS,
            "the leak check passed a payload that names the author",
        )


class TheAssignmentIsNotAConvention(unittest.TestCase):
    def test_neither_side_monopolises_slot_a(self) -> None:
        pairs = _pairs()
        on_a = sum(1 for p in pairs if p.a_is_agent)
        share = max(on_a, len(pairs) - on_a) / len(pairs)
        self.assertLessEqual(
            share,
            SIDE_SHARE_MAX,
            f"one side holds slot A in {share:.0%} of pairs",
        )

    def test_a_different_salt_gives_a_different_assignment(self) -> None:
        one = [p.a_is_agent for p in _pairs("salt-a")]
        two = [p.a_is_agent for p in _pairs("salt-b")]
        self.assertNotEqual(one, two, "the assignment ignores the salt")

    def test_the_same_salt_reproduces_the_assignment(self) -> None:
        self.assertEqual(
            [p.a_is_agent for p in _pairs("salt-a")],
            [p.a_is_agent for p in _pairs("salt-a")],
            "the assignment is not reproducible, so a run cannot be audited",
        )


class ATooSmallSampleCannotDecide(unittest.TestCase):
    def test_a_short_run_is_unmeasured_not_a_tie(self) -> None:
        pairs = _pairs()[: SAMPLE_MIN - 1]
        verdicts = {p.pair_id: "a" for p in pairs}
        result = B.score(pairs, verdicts)
        self.assertEqual(
            result["outcome"],
            UNMEASURED,
            "a sample below the floor produced a verdict",
        )
        self.assertGreaterEqual(result["unmeasured"], 1)

    def test_a_full_run_reports_counts_not_a_bare_flag(self) -> None:
        pairs = _pairs()
        verdicts = {p.pair_id: ("a" if p.a_is_agent else "b") for p in pairs}
        result = B.score(pairs, verdicts)
        self.assertNotEqual(result["outcome"], UNMEASURED, result)
        for key in ("agent_wins", "human_wins", "ties", "checked"):
            self.assertIn(key, result)
            self.assertIsInstance(result[key], int)
        self.assertEqual(
            result["agent_wins"],
            len(pairs),
            "every pair was judged in the agent's favour and the score "
            "disagrees: the assignment is being unwound wrongly",
        )

    def test_an_unjudged_pair_counts_as_unmeasured_not_as_a_tie(self) -> None:
        pairs = _pairs()
        verdicts = {p.pair_id: "a" for p in pairs[:SAMPLE_MIN]}
        result = B.score(pairs, verdicts)
        self.assertEqual(result["unmeasured"], len(pairs) - SAMPLE_MIN)
        self.assertEqual(result["ties"], 0)


if __name__ == "__main__":
    unittest.main()
