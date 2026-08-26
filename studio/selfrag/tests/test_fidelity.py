"""The product rule, made checkable: the agent invents nothing."""

from __future__ import annotations

import unittest

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.fidelity import audit, invented
from studio.selfrag.pipeline import PromptEngineer, PromptRequest

REQUEST = (
    "an amber glass serum bottle standing on porous volcanic stone, "
    "warm directional light, soft shadow, product photography"
)


class Audit(unittest.TestCase):
    def test_the_defect_that_cost_a_real_generation(self) -> None:
        """A synonym read the user's "stone" as the palette colour "sand" and
        the model drew sand. Nobody mentioned texture and a default supplied
        "matte". Both shipped, and both would have been stopped here."""
        lost = (
            "an amber glass serum bottle, standing on porous volcanic stone, soft shadow, "
            "soft light, matte texture, a palette of amber, sand, calm mood"
        )
        out = audit(lost, [REQUEST])
        self.assertEqual(out["outcome"], FAIL)
        self.assertIn("sand", out["invented"])
        self.assertIn("calm", out["invented"])

    def test_the_users_own_sentence_passes_untouched(self) -> None:
        """The control that matters most. If the agent cannot leave a good
        prompt alone, everything else it does is downside."""
        self.assertEqual(audit(REQUEST, [REQUEST])["outcome"], PASS)

    def test_an_invented_object_is_caught(self) -> None:
        out = audit(REQUEST + ", a swan drifting past a marble fountain", [REQUEST])
        self.assertEqual(out["outcome"], FAIL)
        self.assertIn("swan", out["invented"])
        self.assertIn("fountain", out["invented"])

    def test_craft_vocabulary_is_how_not_what(self) -> None:
        """ "Optimised for the model" has to mean something, and this is where
        the line is drawn: rearranging into the vendor's idiom is optimisation,
        adding a swan is not."""
        out = audit(REQUEST + ", shot on a 50mm lens, shallow depth of field", [REQUEST])
        self.assertEqual(out["outcome"], PASS)

    def test_inflection_does_not_count_as_invention(self) -> None:
        self.assertEqual(invented("reflections and shadows", ["reflection and shadow"]), [])

    def test_no_source_is_unmeasured_not_a_pass(self) -> None:
        """An unchecked prompt is not a faithful one, and the two must never
        print the same."""
        out = audit("anything at all here", [])
        self.assertEqual(out["outcome"], UNMEASURED)

    def test_nothing_to_audit_is_unmeasured(self) -> None:
        self.assertEqual(audit("", [REQUEST])["outcome"], UNMEASURED)

    def test_allowing_a_phrase_is_recorded_not_silent(self) -> None:
        """A caller may decide a corpus phrase belongs. That decision is passed
        in explicitly; there is no way to switch the rule off."""
        text = REQUEST + ", cinematic editorial product photography"
        self.assertEqual(audit(text, [REQUEST])["outcome"], PASS)
        loud = REQUEST + ", a swan"
        self.assertEqual(audit(loud, [REQUEST])["outcome"], FAIL)
        self.assertEqual(audit(loud, [REQUEST], extra_allowed=["a swan"])["outcome"], PASS)


class ItBlocksTheRun(unittest.TestCase):
    def test_corpus_phrases_are_off_unless_asked_for(self) -> None:
        engineer = PromptEngineer(state_path=":memory:")
        self.addCleanup(engineer.close)
        plain = engineer.write(
            PromptRequest(text=REQUEST, model="flux", mode="t2i", subject="a serum bottle")
        )
        asked = engineer.write(
            PromptRequest(
                text=REQUEST,
                model="flux",
                mode="t2i",
                subject="a serum bottle",
                use_corpus_phrases=True,
            )
        )
        self.assertEqual(plain["stages"]["fidelity"]["outcome"], PASS)
        self.assertEqual(asked["stages"]["fidelity"]["outcome"], PASS)
        # Whatever the corpus contributed, it only appears when asked for.
        self.assertLessEqual(len(plain["prompt"]), len(asked["prompt"]))

    def test_the_run_reports_what_was_invented(self) -> None:
        engineer = PromptEngineer(state_path=":memory:")
        self.addCleanup(engineer.close)
        out = engineer.write(
            PromptRequest(text=REQUEST, model="flux", mode="t2i", subject="a serum bottle")
        )
        self.assertIn("invented", out)
        self.assertEqual(out["invented"], [])


if __name__ == "__main__":
    unittest.main()
