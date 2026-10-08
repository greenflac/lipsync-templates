"""The corpus's only route into a finished prompt."""

from __future__ import annotations

import unittest

from lipsync.fork_identity import PASS, UNMEASURED
from studio.selfrag.corpus import CorpusRecord
from studio.selfrag.evidence import MIN_SUPPORT, craft_phrases


def rec(n: int, prompt: str) -> CorpusRecord:
    return CorpusRecord(f"r{n}", prompt)


class Evidence(unittest.TestCase):
    def test_a_clause_two_precedents_agree_on_is_taken(self) -> None:
        out = craft_phrases(
            [
                rec(1, "a bottle on stone, cinematic editorial product photography, warm"),
                rec(2, "a watch on rock, cinematic editorial product photography, cool"),
            ],
            avoid="a bottle on stone",
        )
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual(out["phrases"][0]["phrase"], "cinematic editorial product photography")
        self.assertEqual(out["phrases"][0]["support"], 2)
        self.assertEqual(out["phrases"][0]["sources"], ["r1", "r2"])

    def test_one_authors_habit_is_not_a_convention(self) -> None:
        """The support rule does two jobs: a phrase one author used may simply
        be wrong, and a clause lifted from a single third-party prompt is that
        author's expression rather than a fact about the trade."""
        out = craft_phrases(
            [
                rec(1, "a bottle, shot on a vintage anamorphic lens, warm"),
                rec(2, "a watch, softbox key light from the left, cool"),
            ],
            avoid="",
        )
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertEqual(out["phrases"], [])
        self.assertIn("not a convention", out["note"])

    def test_the_support_floor_bites_in_both_directions(self) -> None:
        rows = [
            rec(1, "a bottle, shot on a vintage anamorphic lens, warm"),
            rec(2, "a watch, softbox key light from the left, cool"),
        ]
        self.assertEqual(craft_phrases(rows, min_support=1)["outcome"], PASS)
        self.assertEqual(craft_phrases(rows, min_support=2)["outcome"], UNMEASURED)

    def test_a_clause_with_no_craft_word_is_not_evidence(self) -> None:
        """The subject is the user's to choose. Lifting one from a precedent
        would put somebody else's product in their picture."""
        rows = [
            rec(1, "an Apple Watch Series 9, resting on the table, silver"),
            rec(2, "an Apple Watch Series 9, resting on the table, white"),
        ]
        out = craft_phrases(rows, avoid="")
        self.assertEqual(out["outcome"], UNMEASURED)

    def test_a_clause_the_user_already_wrote_is_repetition(self) -> None:
        rows = [
            rec(1, "x, cinematic editorial product photography, warm"),
            rec(2, "y, cinematic editorial product photography, cool"),
        ]
        self.assertEqual(craft_phrases(rows, avoid="")["outcome"], PASS)
        self.assertEqual(
            craft_phrases(rows, avoid="cinematic editorial product photography")["outcome"],
            UNMEASURED,
        )

    def test_a_craft_word_present_is_not_enough(self) -> None:
        """The defect this rule exists for: "petals softly catching the rim
        light" contains "rim" and "light" and would have put petals into a
        photograph of a serum bottle. That is scene content the user never
        asked for, arriving through the corpus instead of through a synonym
        map — the same failure, a different door."""
        rows = [
            rec(1, "a bottle, petals softly catching the rim light, warm"),
            rec(2, "a watch, petals softly catching the rim light, cool"),
        ]
        self.assertEqual(craft_phrases(rows, avoid="")["outcome"], UNMEASURED)

    def test_a_craft_dominant_clause_is_still_taken(self) -> None:
        """The other direction. A rule that rejects everything is not a filter,
        it is a broken module."""
        rows = [
            rec(1, "a bottle, sharp natural daylight, warm"),
            rec(2, "a watch, sharp natural daylight, cool"),
        ]
        out = craft_phrases(rows, avoid="")
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual(out["phrases"][0]["phrase"], "sharp natural daylight")

    def test_no_precedents_is_unmeasured_not_a_failure(self) -> None:
        out = craft_phrases([], avoid="anything")
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIn("nothing to learn from", out["note"])

    def test_near_duplicate_clauses_are_not_both_taken(self) -> None:
        rows = [
            rec(1, "a, soft directional studio light, b"),
            rec(2, "c, soft directional studio light, d"),
            rec(3, "e, soft directional studio lighting, f"),
            rec(4, "g, soft directional studio lighting, h"),
        ]
        out = craft_phrases(rows, avoid="")
        self.assertEqual(len(out["phrases"]), 1, out["phrases"])

    def test_the_default_support_is_more_than_one(self) -> None:
        """A floor of 1 would make every borrowed clause a copy of one prompt."""
        self.assertGreaterEqual(MIN_SUPPORT, 2)


if __name__ == "__main__":
    unittest.main()
