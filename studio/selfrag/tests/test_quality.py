"""Judging a prompt against the corpus rather than against a rule table."""

from __future__ import annotations

import unittest

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.corpus import load_corpus
from studio.selfrag.evaluate import DEMO_CORPUS_PATH
from studio.selfrag.quality import MIN_CORPUS, calibrate, compare, features_of, score

PROSE = (
    "The quarterly filing deadline falls on the last working day of the month. "
    "Submit the return through the portal and keep the confirmation number."
)


def corpus_like(n: int) -> list[str]:
    """Prompts with the shape this corpus has: many clauses, craft words, numbers."""
    return [
        f"a hero product on a sculptural plinth, cinematic editorial product photography, "
        f"shot on a 50mm lens at f/{n % 8 + 1}.4, soft directional studio light, "
        f"warm slightly desaturated editorial tones, shallow depth of field, "
        f"polished reflective surface, sharp natural daylight, take {n}"
        for n in range(n)
    ]


class Calibration(unittest.TestCase):
    def test_a_handful_of_rows_is_not_a_standard(self) -> None:
        out = calibrate(corpus_like(MIN_CORPUS - 1))
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIsNone(out["model"])

    def test_enough_rows_calibrate(self) -> None:
        out = calibrate(corpus_like(MIN_CORPUS + 10))
        self.assertEqual(out["outcome"], PASS)
        self.assertIsNotNone(out["model"])

    def test_a_scorer_that_accepts_unrelated_prose_is_refused(self) -> None:
        """The control is not decoration. A scorer that likes everything
        measures nothing, and this project has already been bitten once by a
        metric that could not tell two very different inputs apart."""
        # Make the "corpus" out of prose, so prose looks normal to it.
        out = calibrate([PROSE] * (MIN_CORPUS + 5))
        self.assertEqual(out["outcome"], FAIL)
        self.assertIsNone(out["model"])
        self.assertIn("negative control", out["note"])

    def test_the_controls_separate(self) -> None:
        out = calibrate(corpus_like(MIN_CORPUS + 10))
        self.assertLess(out["controls"]["negative"], out["controls"]["positive"])


class Scoring(unittest.TestCase):
    def model(self):
        out = calibrate(corpus_like(MIN_CORPUS + 10))
        self.assertEqual(out["outcome"], PASS)
        return out["model"]

    def test_prose_scores_below_a_prompt(self) -> None:
        model = self.model()
        prompt = corpus_like(1)[0]
        self.assertLess(score(PROSE, model=model)["score"], score(prompt, model=model)["score"])

    def test_a_short_prompt_is_failed_on_length_and_says_so(self) -> None:
        model = self.model()
        out = score("a bottle, soft light", model=model)
        self.assertEqual(out["outcome"], FAIL)
        self.assertIn(out["weakest"], ("words", "clauses"))
        self.assertIn("percentile", out["note"])

    def test_nothing_to_score_is_unmeasured(self) -> None:
        self.assertEqual(score("", model=self.model())["outcome"], UNMEASURED)

    def test_features_are_computable_and_bounded(self) -> None:
        f = features_of("a bottle, shot on a 50mm lens, soft directional light")
        self.assertEqual(f["clauses"], 3.0)
        self.assertGreater(f["words"], 0)
        for name in ("craft_density", "craft_clauses", "specificity"):
            with self.subTest(name=name):
                self.assertGreaterEqual(f[name], 0.0)
                self.assertLessEqual(f[name], 1.0)

    def test_compare_ranks_and_keeps_every_score(self) -> None:
        model = self.model()
        out = compare({"long": corpus_like(1)[0], "short": "a bottle"}, model=model)
        self.assertEqual(out["ranked"][0], "long")
        self.assertIn("short", out["scores"])


class AgainstTheShippedCorpus(unittest.TestCase):
    def test_the_demo_corpus_is_too_small_to_be_a_standard(self) -> None:
        """Ten records cannot define a distribution, and the module says so
        rather than producing percentiles nobody should trust."""
        records = load_corpus(paths=[DEMO_CORPUS_PATH])["records"]
        out = calibrate([r.prompt for r in records])
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIn(str(MIN_CORPUS), out["note"])


if __name__ == "__main__":
    unittest.main()
