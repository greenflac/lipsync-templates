"""Tests for studio.blind: the comparison instrument must be able to say no.

Every expected value here is a literal. Importing the module's own constants
would make the test move whenever the module moves, and a test that agrees
with the code by construction guards nothing.

The network is closed by the runner below, not by a convention.
"""

from __future__ import annotations

import json
import socket
import unittest

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.blind import Pair, judge_payload, leak_check, make_pair, score

_REAL_SOCKET = socket.socket
_REAL_CONNECT = socket.create_connection


class NetworkTouched(AssertionError):
    """Raised when a test reaches for a socket. A test that needs one is broken."""


def setUpModule() -> None:
    """Close the network for the whole module. Enforcement, not agreement (T4)."""

    def _refuse(*args: object, **kwargs: object) -> None:
        raise NetworkTouched("a test in test_blind reached for the network")

    socket.socket = _refuse  # type: ignore[assignment]
    socket.create_connection = _refuse  # type: ignore[assignment]


def tearDownModule() -> None:
    socket.socket = _REAL_SOCKET  # type: ignore[assignment]
    socket.create_connection = _REAL_CONNECT  # type: ignore[assignment]


def _pairs(count: int, salt: str = "run-1") -> list[Pair]:
    return [
        make_pair(
            brief_id=f"brief-{i:03d}",
            agent_prompt=f"agent wording for brief {i}",
            human_prompt=f"human wording for brief {i}",
            salt=salt,
        )
        for i in range(count)
    ]


def _all_agent(pairs: list[Pair]) -> dict[str, str]:
    return {p.pair_id: ("a" if p.a_is_agent else "b") for p in pairs}


def _all_human(pairs: list[Pair]) -> dict[str, str]:
    return {p.pair_id: ("b" if p.a_is_agent else "a") for p in pairs}


def _mixed(pairs: list[Pair], agent_wins: int) -> dict[str, str]:
    """Give the first `agent_wins` pairs to the agent and the rest to the human."""
    verdicts = _all_human(pairs)
    for pair in pairs[:agent_wins]:
        verdicts[pair.pair_id] = "a" if pair.a_is_agent else "b"
    return verdicts


class TheAssignmentIsDrawnNotRolled(unittest.TestCase):
    def test_the_prompts_land_on_the_drawn_sides(self) -> None:
        pair = make_pair(
            brief_id="b1", agent_prompt="AGENT", human_prompt="HUMAN", salt="s"
        )
        if pair.a_is_agent:
            self.assertEqual((pair.a, pair.b), ("AGENT", "HUMAN"))
        else:
            self.assertEqual((pair.a, pair.b), ("HUMAN", "AGENT"))

    def test_the_same_inputs_reproduce_the_pair_exactly(self) -> None:
        first = make_pair(brief_id="b1", agent_prompt="A", human_prompt="H", salt="s")
        second = make_pair(brief_id="b1", agent_prompt="A", human_prompt="H", salt="s")
        self.assertEqual(first, second)

    def test_a_missing_salt_or_brief_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            make_pair(brief_id="", agent_prompt="A", human_prompt="H", salt="s")
        with self.assertRaises(ValueError):
            make_pair(brief_id="b1", agent_prompt="A", human_prompt="H", salt="")

    def test_pair_ids_are_distinct_across_briefs(self) -> None:
        pairs = _pairs(40)
        self.assertEqual(len({p.pair_id for p in pairs}), 40)


class ThePayloadCarriesNoAuthorship(unittest.TestCase):
    def test_the_payload_has_exactly_four_fields(self) -> None:
        for item in judge_payload(_pairs(5)):
            self.assertEqual(sorted(item), ["a", "b", "brief_id", "pair_id"])

    def test_the_payload_never_carries_the_assignment_flag(self) -> None:
        text = json.dumps(judge_payload(_pairs(40)), ensure_ascii=False)
        self.assertNotIn("a_is_agent", text)
        self.assertNotIn("assignment", text)


class TheLeakCheckCanSayNo(unittest.TestCase):
    """Negative control: an input it must pass, and inputs it must refuse."""

    def test_a_clean_payload_passes_and_reports_what_it_inspected(self) -> None:
        result = leak_check(judge_payload(_pairs(3)))
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["checked"], 12)
        self.assertEqual(result["violations"], 0)
        self.assertEqual(result["unmeasured"], 0)

    def test_an_authorship_claim_inside_a_prompt_is_caught(self) -> None:
        payload = judge_payload(_pairs(3))
        payload[1]["b"] = payload[1]["b"] + " (written by the human)"
        result = leak_check(payload)
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["violations"], 1)

    def test_an_added_side_field_is_caught(self) -> None:
        payload = judge_payload(_pairs(3))
        payload[0]["side"] = "left"
        self.assertEqual(leak_check(payload)["outcome"], "fail")

    def test_a_bare_label_value_is_caught_whatever_the_field_is_called(self) -> None:
        payload = judge_payload(_pairs(3))
        payload[0]["note"] = "Agent"
        self.assertEqual(leak_check(payload)["outcome"], "fail")

    def test_a_bare_flag_beside_the_prompts_is_caught(self) -> None:
        payload = judge_payload(_pairs(3))
        payload[2]["first"] = True
        self.assertEqual(leak_check(payload)["outcome"], "fail")

    def test_an_empty_payload_is_unmeasured_not_a_pass(self) -> None:
        result = leak_check([])
        self.assertEqual(result["outcome"], "could not measure")
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["violations"], 0)

    def test_an_unreadable_record_is_unmeasured_not_a_pass(self) -> None:
        payload = judge_payload(_pairs(3))
        payload.append({"pair_id": "x"})
        result = leak_check(payload)
        self.assertEqual(result["outcome"], "could not measure")
        self.assertEqual(result["unmeasured"], 1)

    def test_the_word_agent_inside_ordinary_wording_is_not_a_leak(self) -> None:
        """The detector must also be able to say yes, or nobody will keep it on."""
        pair = make_pair(
            brief_id="b1",
            agent_prompt="a travel agent at a desk, warm light",
            human_prompt="a human face in close-up, warm light",
            salt="s",
        )
        self.assertEqual(leak_check(judge_payload([pair]))["outcome"], "pass")


class TheScoreCountsAndNeverGuesses(unittest.TestCase):
    def test_a_clean_sweep_for_the_agent_passes(self) -> None:
        pairs = _pairs(40)
        result = score(pairs, _all_agent(pairs))
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["agent_wins"], 40)
        self.assertEqual(result["human_wins"], 0)
        self.assertEqual(result["ties"], 0)
        self.assertEqual(result["checked"], 40)
        self.assertEqual(result["unmeasured"], 0)
        self.assertEqual(result["violations"], 0)

    def test_a_clean_sweep_for_the_human_fails(self) -> None:
        pairs = _pairs(40)
        result = score(pairs, _all_human(pairs))
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["agent_wins"], 0)
        self.assertEqual(result["human_wins"], 40)

    def test_a_mix_at_the_acceptance_share_passes(self) -> None:
        pairs = _pairs(40)
        result = score(pairs, _mixed(pairs, 22))
        self.assertEqual(result["agent_wins"], 22)
        self.assertEqual(result["human_wins"], 18)
        self.assertEqual(result["outcome"], "pass")

    def test_a_mix_just_below_the_acceptance_share_fails(self) -> None:
        pairs = _pairs(40)
        result = score(pairs, _mixed(pairs, 21))
        self.assertEqual(result["agent_wins"], 21)
        self.assertEqual(result["human_wins"], 19)
        self.assertEqual(result["outcome"], "fail")

    def test_all_ties_are_counted_but_decide_nothing(self) -> None:
        pairs = _pairs(40)
        result = score(pairs, {p.pair_id: "tie" for p in pairs})
        self.assertEqual(result["ties"], 40)
        self.assertEqual(result["agent_wins"], 0)
        self.assertEqual(result["human_wins"], 0)
        self.assertEqual(result["outcome"], "could not measure")
        self.assertGreaterEqual(result["unmeasured"], 1)

    def test_four_decisive_pairs_under_a_pile_of_ties_decide_nothing(self) -> None:
        pairs = _pairs(40)
        verdicts = {p.pair_id: "tie" for p in pairs}
        for pair in pairs[:4]:
            verdicts[pair.pair_id] = "a" if pair.a_is_agent else "b"
        result = score(pairs, verdicts)
        self.assertEqual(result["agent_wins"], 4)
        self.assertEqual(result["outcome"], "could not measure")

    def test_five_decisive_pairs_under_a_pile_of_ties_decide(self) -> None:
        pairs = _pairs(40)
        verdicts = {p.pair_id: "tie" for p in pairs}
        for pair in pairs[:5]:
            verdicts[pair.pair_id] = "a" if pair.a_is_agent else "b"
        result = score(pairs, verdicts)
        self.assertEqual(result["agent_wins"], 5)
        self.assertEqual(result["outcome"], "pass")

    def test_an_empty_sample_is_unmeasured_with_no_wins_no_ties(self) -> None:
        result = score([], {})
        self.assertEqual(result["outcome"], "could not measure")
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["ties"], 0)
        self.assertEqual(result["agent_wins"], 0)
        self.assertEqual(result["unmeasured"], 20)

    def test_nineteen_judged_pairs_are_unmeasured_not_a_verdict(self) -> None:
        pairs = _pairs(19)
        result = score(pairs, _all_agent(pairs))
        self.assertEqual(result["checked"], 19)
        self.assertEqual(result["outcome"], "could not measure")
        self.assertEqual(result["unmeasured"], 1)
        self.assertEqual(result["ties"], 0)

    def test_twenty_judged_pairs_are_enough_to_decide(self) -> None:
        pairs = _pairs(20)
        result = score(pairs, _all_agent(pairs))
        self.assertEqual(result["checked"], 20)
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["unmeasured"], 0)

    def test_an_unjudged_pair_is_unmeasured_not_a_tie(self) -> None:
        pairs = _pairs(40)
        verdicts = _all_agent(pairs)
        for pair in pairs[30:]:
            del verdicts[pair.pair_id]
        result = score(pairs, verdicts)
        self.assertEqual(result["checked"], 30)
        self.assertEqual(result["unmeasured"], 10)
        self.assertEqual(result["ties"], 0)

    def test_a_junk_verdict_is_a_violation_not_a_tie(self) -> None:
        pairs = _pairs(40)
        verdicts = _all_agent(pairs)
        verdicts[pairs[0].pair_id] = "maybe"
        verdicts[pairs[1].pair_id] = ""
        result = score(pairs, verdicts)
        self.assertEqual(result["violations"], 2)
        self.assertEqual(result["ties"], 0)
        self.assertEqual(result["checked"], 38)
        self.assertEqual(result["unmeasured"], 2)

    def test_a_verdict_for_an_unknown_pair_is_a_violation(self) -> None:
        pairs = _pairs(40)
        verdicts = _all_agent(pairs)
        verdicts["brief-999-deadbeef"] = "a"
        result = score(pairs, verdicts)
        self.assertEqual(result["violations"], 1)
        self.assertEqual(result["checked"], 40)

    def test_the_side_the_judge_names_is_unwound_not_taken_at_face_value(self) -> None:
        """Everything judged as side A: the score must split by the assignment."""
        pairs = _pairs(40)
        result = score(pairs, {p.pair_id: "a" for p in pairs})
        on_a = sum(1 for p in pairs if p.a_is_agent)
        self.assertEqual(result["agent_wins"], on_a)
        self.assertEqual(result["human_wins"], 40 - on_a)
        self.assertEqual(result["checked"], 40)


if __name__ == "__main__":
    unittest.main()
