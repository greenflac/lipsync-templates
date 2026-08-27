"""The one rule the agent must not be able to lose: it answers for the field.

WHY THIS FILE EXISTS

Asked which stack would put a new character into an existing scene at
photographic realism, the assistant recommended `lipsync/fork_e2e.py`. That
module is in this repository, it does motion transfer onto a character IMAGE,
and it therefore cannot preserve the original scene — which was the whole
requirement. It was reached for because it was near, and presented as a
conclusion rather than as one candidate.

The owner's correction: the agent is a universal fighter and must not
prioritise what is in the repo.

A rule like that, written only in a docstring or a handoff, drifts back the
first time somebody shortens the prompt. So it lives in the instructions string
every MCP client reads, and this file is the gate on it (house rule C7: what
must always hold is a test, not a sentence).

The assertions are deliberately about MEANING, not wording: they check that the
clause still forbids the specific failure, so a rewrite that keeps the rule
passes and a rewrite that quietly drops it does not.
"""

from __future__ import annotations

import unittest

from studio.mcp.server import server

#: Phrases the clause must still carry. Literals (house rule T2) — importing
#: them from the module under test would check nothing. Each one is a distinct
#: half of the rule, so dropping any single one goes red.
MUST_SAY: tuple[tuple[str, str], ...] = (
    ("survey", "the agent has to look at the whole field, not answer from what is near"),
    ("NEITHER is a default", "the repo's engine and corpus are candidates, not starting points"),
    ("compare", "a recommendation is the result of a comparison or it is not a recommendation"),
    ("win only if they win", "this project's tools have to earn it against the alternatives"),
    ("have not looked outside", "not having surveyed must be said, not papered over"),
    ("every candidate", "the base is consulted for all of them, not only the favourite"),
    ("CAPABILITY", "an API accepting the input is not the same claim as the result holding up"),
    ("APPLICABILITY", "the second claim comes from the corpus, not from a parameter list"),
    ("record_model_fact", "what the survey finds goes back into the base"),
)


class TheAgentAnswersForTheField(unittest.TestCase):
    def test_the_universality_clause_is_still_in_the_instructions(self) -> None:
        text = str(server.instructions or "")
        for phrase, why in MUST_SAY:
            assert phrase in text, f"the instructions no longer say {phrase!r} — {why}"

    def test_the_clause_comes_before_the_job_description(self) -> None:
        """Order is not decoration. A model reading a long instruction weights
        the opening; a universality rule buried under two job descriptions is a
        rule that loses to the job in front of it."""
        text = str(server.instructions or "")
        assert text.lstrip().startswith("WHOSE SIDE YOU ARE ON"), text[:80]
        assert text.index("survey") < text.index("Write lipsync prompts")

    def test_the_instructions_still_describe_both_jobs(self) -> None:
        """The negative control. A clause that swallowed the rest of the prompt
        would pass every test above while breaking the server for its callers.

        It checks the job DESCRIPTIONS and not just the tool names: a mutation
        that deleted "Advise on what a generation model can and cannot do" left
        the string `model_advice` standing further down, and an earlier version
        of this test went green on it.
        """
        text = str(server.instructions or "")
        assert "Advise on what a generation model can and cannot do" in text
        assert "Write lipsync prompts" in text
        assert "model_advice" in text
        assert "write_lipsync_prompt" in text
        assert "search_web" in text
        # A prompt this short cannot still be carrying two jobs and four rules.
        assert len(text) > 1500, f"the instructions shrank to {len(text)} characters"

    def test_the_refusal_to_route_around_a_policy_is_untouched(self) -> None:
        """The other rule that must survive every prompt edit."""
        text = str(server.instructions or "")
        assert "routed around" in text
        assert "no mirror, no cache, no read-through proxy" in text


if __name__ == "__main__":
    unittest.main()
