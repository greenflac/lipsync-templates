"""The paid-measurement gate: can the agent spend money without being told to?

Every test writes to a temporary ledger and a temporary fact file, so nothing
here touches the repository's own knowledge and nothing reaches the network
(house rule T4).

The tests that carry the weight are the negative controls (I5): a gate that
approved everything and a gate that approved nothing would both pass a suite
that only ever files well-formed proposals.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.mcp import proposal

GOOD = {
    "task": "recreate the competitor template with a new character in the same set",
    "gap": "no source states whether wan-animate-replace holds a face across a 6s take",
    "test": (
        "send one 6s 720p job to fal.ai/wan-animate with the reference face and the plate, "
        "then measure identity drift between frame 1 and frame 144 with ArcFace cosine"
    ),
    "cost_usd": 0.42,
    "cost_basis": "fal.ai published rate $0.07/s of output, 6s",
    "decides": "under 0.25 drift the plate-edit route stands; over it we fall back to a reshoot",
}


class Filing(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.ledger = self.tmp / "measurements.jsonl"
        self.facts = self.tmp / "facts.jsonl"
        self.facts.write_text("", encoding="utf-8")

    def _file(self, **over: object) -> dict:
        kwargs = dict(GOOD)
        kwargs.update(over)
        return proposal.propose(
            str(kwargs.pop("model", "wan-animate-replace")),
            str(kwargs.pop("attribute", "holds_identity")),
            path=self.ledger,
            facts_path=self.facts,
            **kwargs,  # type: ignore[arg-type]
        )

    def test_a_filed_proposal_is_never_pass_because_nothing_was_measured(self) -> None:
        out = self._file()
        assert out["outcome"] == UNMEASURED, out["note"]
        assert out["unmeasured"] == 1
        assert out["state"] == proposal.STATE_PROPOSED
        assert out["id"].startswith("mp-")

    def test_the_price_must_be_named(self) -> None:
        out = self._file(cost_usd="ask them")
        assert out["outcome"] == FAIL
        assert "name the price" in out["note"]
        assert not self.ledger.exists(), "a refused proposal must not reach the ledger"

    def test_a_price_with_no_basis_is_refused(self) -> None:
        out = self._file(cost_basis="cheap")
        assert out["outcome"] == FAIL
        assert "cost_basis" in out["note"]

    def test_a_test_nobody_could_execute_is_refused(self) -> None:
        out = self._file(test="try kling and see")
        assert out["outcome"] == FAIL
        assert "test is" in out["note"]

    def test_a_measurement_that_decides_nothing_is_refused(self) -> None:
        out = self._file(decides="good")
        assert out["outcome"] == FAIL
        assert "decides" in out["note"]

    def test_a_proposal_with_no_task_is_refused(self) -> None:
        """Approval is per task — the owner's ruling. A standing budget is
        exactly what this is not."""
        out = self._file(task="")
        assert out["outcome"] == FAIL
        assert "task is empty" in out["note"]

    def test_a_one_word_task_is_not_a_concrete_job(self) -> None:
        """Found by mutation: dropping MIN_TASK_CHARS to 0 stayed green,
        because the only fixture here was an EMPTY task, which the presence
        check already catches. `видео` is a category, not a job."""
        out = self._file(task="видео")
        assert out["outcome"] == FAIL
        assert "concrete job" in out["note"]

    def test_a_STALE_settled_fact_may_be_re_measured(self) -> None:
        """Found by mutation: deleting the staleness clause from the
        already-known gate stayed green. A vendor page from two years ago is
        agreed-upon and worthless, and re-measuring it is exactly the spend
        this mechanism exists to authorise."""
        from datetime import date, timedelta

        from studio.mcp import advice
        from studio.selfrag.facts import STALE_AFTER_DAYS

        long_ago = (date.today() - timedelta(days=STALE_AFTER_DAYS + 30)).isoformat()
        advice.record(
            "wan-animate-replace",
            "max_seconds",
            "5",
            "https://huggingface.co/Wan-AI/Wan2.2-Animate-14B",
            "vendor",
            long_ago,
            read_directly=True,
            path=self.facts,
        )
        out = self._file(attribute="max_seconds")
        assert out["outcome"] == UNMEASURED, out["note"]

    def test_a_free_test_still_goes_past_the_operator(self) -> None:
        """The negative control on the price gate: $0 must be ALLOWED, or the
        gate is measuring 'is there a number' rather than 'was it named'."""
        out = self._file(cost_usd=0.0)
        assert out["outcome"] == UNMEASURED, out["note"]

    def test_filing_the_same_ask_twice_puts_one_thing_in_front_of_the_person(self) -> None:
        first = self._file()
        second = self._file()
        assert second["id"] == first["id"]
        assert "already filed" in second["note"]
        rows = [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1

    def test_a_different_test_for_the_same_attribute_is_a_different_proposal(self) -> None:
        """The other half: identity must move with the test, or a second,
        better-designed measurement would be silently swallowed by the first."""
        first = self._file()
        second = self._file(
            test=(
                "send one 6s 720p job to replicate.com/wan-animate instead, same reference "
                "and plate, and measure the same ArcFace cosine drift for comparison"
            )
        )
        assert second["id"] != first["id"]
        assert second["outcome"] == UNMEASURED

    def test_paying_to_re_learn_a_settled_fact_is_refused(self) -> None:
        from studio.mcp import advice

        advice.record(
            "wan-animate-replace",
            "max_seconds",
            "5",
            "https://huggingface.co/Wan-AI/Wan2.2-Animate-14B",
            "vendor",
            "2026-08-01",
            read_directly=True,
            path=self.facts,
        )
        out = self._file(attribute="max_seconds")
        assert out["outcome"] == FAIL
        assert "already answers" in out["note"]

    def test_a_CONTESTED_fact_is_exactly_when_measuring_is_worth_paying_for(self) -> None:
        """The negative control on the gate above. Without it, a rule that
        blocked every attribute anybody had ever mentioned would pass."""
        from studio.mcp import advice

        for value, url in (
            ("5", "https://huggingface.co/Wan-AI/Wan2.2-Animate-14B"),
            ("10", "https://fal.ai/models/fal-ai/wan-animate"),
        ):
            advice.record(
                "wan-animate-replace",
                "max_seconds",
                value,
                url,
                "vendor" if "huggingface" in url else "portal",
                "2026-08-01",
                read_directly=True,
                path=self.facts,
            )
        out = self._file(attribute="max_seconds")
        assert out["outcome"] == UNMEASURED, out["note"]


class TheOperatorDecides(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.ledger = self.tmp / "measurements.jsonl"
        self.facts = self.tmp / "facts.jsonl"
        self.facts.write_text("", encoding="utf-8")
        filed = proposal.propose(
            "wan-animate-replace",
            "holds_identity",
            path=self.ledger,
            facts_path=self.facts,
            **GOOD,  # type: ignore[arg-type]
        )
        self.proposal_id = str(filed["id"])

    def test_a_result_cannot_be_recorded_against_an_unapproved_proposal(self) -> None:
        """The whole mechanism in one assertion."""
        out = proposal.record_result(
            self.proposal_id,
            "0.19 cosine drift",
            "https://fal.ai/dashboard/requests/abc123",
            "2026-08-27",
            evidence="frame 1 to frame 144 ArcFace cosine 0.19",
            actual_cost_usd=0.42,
            path=self.ledger,
            facts_path=self.facts,
        )
        assert out["outcome"] == FAIL
        assert "nobody authorised" in out["note"]
        assert self.facts.read_text(encoding="utf-8").strip() == ""

    def test_a_result_after_a_DECLINE_is_still_refused(self) -> None:
        proposal.decide(self.proposal_id, "declined", operator="owner", path=self.ledger)
        out = proposal.record_result(
            self.proposal_id,
            "0.19",
            "https://fal.ai/dashboard/requests/abc123",
            "2026-08-27",
            evidence="observed drift",
            actual_cost_usd=0.42,
            path=self.ledger,
            facts_path=self.facts,
        )
        assert out["outcome"] == FAIL

    def test_an_approval_with_nobody_s_name_on_it_is_not_an_approval(self) -> None:
        out = proposal.decide(self.proposal_id, "approved", operator="  ", path=self.ledger)
        assert out["outcome"] == FAIL

    def test_recorded_is_not_a_decision_the_operator_can_hand_down(self) -> None:
        out = proposal.decide(self.proposal_id, "recorded", operator="owner", path=self.ledger)
        assert out["outcome"] == FAIL
        assert "not one of" in out["note"]

    def test_an_approved_measurement_lands_in_the_base_at_probe_tier(self) -> None:
        assert (
            proposal.decide(self.proposal_id, "approved", operator="owner", path=self.ledger)[
                "outcome"
            ]
            == PASS
        )
        out = proposal.record_result(
            self.proposal_id,
            "0.19 cosine drift over 144 frames",
            "https://fal.ai/dashboard/requests/abc123",
            "2026-08-27",
            evidence="ArcFace cosine between frame 1 and frame 144 read 0.19",
            actual_cost_usd=0.42,
            path=self.ledger,
            facts_path=self.facts,
        )
        assert out["outcome"] == PASS, out["note"]
        written = self.facts.read_text(encoding="utf-8")
        assert '"tier": "probe"' in written
        assert "holds_identity" in written
        assert self.proposal_id in written, "the fact cites the approval it was paid for"

    def test_an_overspend_is_reported_and_the_fact_is_still_written(self) -> None:
        """Both halves matter. Withholding a result already paid for wastes the
        money twice; swallowing the overspend surprises the person paying."""
        proposal.decide(self.proposal_id, "approved", operator="owner", path=self.ledger)
        out = proposal.record_result(
            self.proposal_id,
            "0.19",
            "https://fal.ai/dashboard/requests/abc123",
            "2026-08-27",
            evidence="ArcFace cosine read 0.19 across the take",
            actual_cost_usd=3.10,
            path=self.ledger,
            facts_path=self.facts,
        )
        assert out["outcome"] == FAIL
        assert "$3.10 was charged against an approval for $0.42" in out["note"]
        assert "holds_identity" in self.facts.read_text(encoding="utf-8")

    def test_spending_UNDER_the_approval_is_not_an_overspend(self) -> None:
        """The negative control on the ceiling — otherwise a comparison written
        the wrong way round would pass every test above."""
        proposal.decide(self.proposal_id, "approved", operator="owner", path=self.ledger)
        out = proposal.record_result(
            self.proposal_id,
            "0.19",
            "https://fal.ai/dashboard/requests/abc123",
            "2026-08-27",
            evidence="ArcFace cosine read 0.19 across the take",
            actual_cost_usd=0.30,
            path=self.ledger,
            facts_path=self.facts,
        )
        assert out["outcome"] == PASS, out["note"]

    def test_approving_something_already_measured_is_refused(self) -> None:
        proposal.decide(self.proposal_id, "approved", operator="owner", path=self.ledger)
        proposal.record_result(
            self.proposal_id,
            "0.19",
            "https://fal.ai/dashboard/requests/abc123",
            "2026-08-27",
            evidence="ArcFace cosine read 0.19 across the take",
            actual_cost_usd=0.42,
            path=self.ledger,
            facts_path=self.facts,
        )
        out = proposal.decide(self.proposal_id, "approved", operator="owner", path=self.ledger)
        assert out["outcome"] == FAIL
        assert "already been measured" in out["note"]

    def test_a_result_with_no_evidence_is_refused(self) -> None:
        proposal.decide(self.proposal_id, "approved", operator="owner", path=self.ledger)
        out = proposal.record_result(
            self.proposal_id,
            "0.19",
            "https://fal.ai/dashboard/requests/abc123",
            "2026-08-27",
            evidence="",
            actual_cost_usd=0.42,
            path=self.ledger,
            facts_path=self.facts,
        )
        assert out["outcome"] == FAIL
        assert "evidence" in out["note"]


class Listing(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.ledger = self.tmp / "measurements.jsonl"
        self.facts = self.tmp / "facts.jsonl"
        self.facts.write_text("", encoding="utf-8")

    def test_an_empty_ledger_is_could_not_measure_and_never_pass(self) -> None:
        """`no proposals` and `no pending proposals` are different answers."""
        out = proposal.proposals(path=self.ledger)
        assert out["outcome"] == UNMEASURED
        assert out["proposals"] == []

    def test_the_listing_reports_the_current_state_not_every_row(self) -> None:
        filed = proposal.propose(
            "wan-animate-replace",
            "holds_identity",
            path=self.ledger,
            facts_path=self.facts,
            **GOOD,  # type: ignore[arg-type]
        )
        proposal.decide(str(filed["id"]), "approved", operator="owner", path=self.ledger)
        out = proposal.proposals(path=self.ledger)
        assert out["outcome"] == PASS
        assert len(out["proposals"]) == 1
        assert out["by_state"] == {"approved": 1}
        assert "0 waiting on the operator" in out["note"]

    def test_an_unknown_state_filter_is_refused(self) -> None:
        out = proposal.proposals(state="maybe", path=self.ledger)
        assert out["outcome"] == FAIL


class ApprovalIsNotSomethingTheAgentCanReach(unittest.TestCase):
    """The mechanical half of the mechanism, and the reason it is not prose.

    The agent may file a proposal and read the ledger. If it could also approve
    one, the operator was never asked — the account was simply handed over. So
    the MCP surface is asserted here rather than promised in an instruction
    string, because an instruction string is what drifts (house rule C7).
    """

    def test_the_server_offers_filing_and_looking(self) -> None:
        import asyncio

        from studio.mcp.server import server

        names = sorted(tool.name for tool in asyncio.run(server.list_tools()))
        assert "propose_measurement" in names
        assert "measurement_proposals" in names

    def test_the_server_offers_NO_way_to_approve_decide_or_enter_a_result(self) -> None:
        """Literal forbidden names (T2). A tool added later under any of these
        spellings goes red here rather than quietly opening the door."""
        import asyncio

        from studio.mcp.server import server

        names = sorted(tool.name for tool in asyncio.run(server.list_tools()))
        for forbidden in (
            "approve_measurement",
            "decide_measurement",
            "record_measurement",
            "record_measurement_result",
            "measurement_decide",
            "approve",
        ):
            assert forbidden not in names, (
                f"{forbidden!r} is exposed — an agent that can approve its own spend "
                "has not asked the operator for anything"
            )
        for name in names:
            assert "approve" not in name, f"{name!r} looks like an approval door"


if __name__ == "__main__":
    unittest.main()
