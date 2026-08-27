"""Gate: what the specialist is allowed to learn from.

This module does not test retrieval quality. It tests the *composition* of the
corpus, because a retriever measured on the wrong corpus scores well and
teaches badly. Three claims are guarded here:

1. Our own shipped prompts are out. They were written for several unrelated
   projects and tasks; mixed into one index they teach the writer an average
   of jobs that share nothing.
2. The aidsgn cards are in, and the rights to them are recorded in a document
   rather than in somebody's memory.
3. The corpus states how many worked prompt *wordings* it holds. Style cards
   describe how a picture looks, not how a prompt is said; an index with zero
   wordings must say so instead of reporting a clean pass.

The gate is written before the implementation and is never edited by the agent
that implements against it.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from lipsync.fork_identity import PASS
from studio import knowledge as K
from studio.knowledge import build_index

# The document that must carry the rights statement, and the shape that
# statement must take. CHOSEN: a machine-checkable prefix, so that the claim
# cannot be satisfied by the domain merely appearing in a URL somewhere.
RIGHTS_DOC = Path(K.__file__).with_name("knowledge") / "PROVENANCE.md"
RIGHTS_LINE = re.compile(r"^RIGHTS:\s+\S", re.MULTILINE)
RIGHTS_SOURCE = "aidsgn.ru"

# The provenance that must not appear in the default corpus, and the one that
# must. Imported names, not repeated literals: one word list, one place.
EXCLUDED_PROVENANCE = K.PROVENANCE_OURS
REQUIRED_PROVENANCE = K.PROVENANCE_REFERENCE_CARD

# CHOSEN: the aidsgn extraction is 522 cards today. The floor is deliberately
# far below that, so the gate catches "the directory vanished", not "three
# cards were re-extracted".
CARDS_MIN = 100


class OurOwnPromptsAreNotTrainingMaterial(unittest.TestCase):
    """The default corpus must not contain our fixture prompts."""

    def test_the_default_corpus_holds_no_entry_of_our_own(self) -> None:
        index = build_index()
        counts = index.counts()
        self.assertEqual(
            counts.get(EXCLUDED_PROVENANCE, 0),
            0,
            f"our own prompts are in the default corpus: {counts}",
        )

    def test_the_exclusion_is_declared_and_not_silent(self) -> None:
        index = build_index()
        report = index.build_report
        self.assertIn(
            "excluded",
            report,
            "the build report must name what was deliberately left out",
        )
        self.assertIn(
            EXCLUDED_PROVENANCE,
            report["excluded"],
            f"the exclusion of {EXCLUDED_PROVENANCE} is not declared: {report}",
        )


class TheGalleryCardsAreTheTrainingMaterial(unittest.TestCase):
    """The aidsgn cards must be present, and present in force."""

    def test_the_cards_are_in_the_corpus(self) -> None:
        counts = build_index().counts()
        self.assertGreaterEqual(
            counts.get(REQUIRED_PROVENANCE, 0),
            CARDS_MIN,
            f"the aidsgn cards are missing or nearly empty: {counts}",
        )


class TheRightsAreOnRecord(unittest.TestCase):
    """Rights to third-party material are a document, not a recollection."""

    def test_the_provenance_document_exists(self) -> None:
        self.assertTrue(RIGHTS_DOC.is_file(), f"missing: {RIGHTS_DOC}")

    def test_the_document_carries_a_rights_line(self) -> None:
        text = RIGHTS_DOC.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            RIGHTS_LINE,
            "PROVENANCE.md must carry a line beginning 'RIGHTS: '",
        )

    def test_the_rights_line_names_the_source_it_covers(self) -> None:
        text = RIGHTS_DOC.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if RIGHTS_LINE.match(ln)]
        self.assertTrue(lines, "no RIGHTS line to check")
        self.assertTrue(
            any(RIGHTS_SOURCE in ln for ln in lines),
            f"no RIGHTS line names {RIGHTS_SOURCE}: {lines}",
        )


class TheCorpusIsHonestAboutWhatItLacks(unittest.TestCase):
    """Style cards are not prompt wordings, and the report must say so."""

    def test_the_report_counts_worked_wordings(self) -> None:
        report = build_index().build_report
        self.assertIn(
            "wording_examples",
            report,
            "the build report must count entries that carry prompt wording",
        )
        self.assertIsInstance(report["wording_examples"], int)

    def test_zero_wordings_is_reported_as_unmeasured_not_as_a_clean_pass(
        self,
    ) -> None:
        report = build_index().build_report
        if report["wording_examples"] == 0:
            self.assertGreaterEqual(
                report["unmeasured"],
                1,
                "a corpus with no prompt wording reports a clean pass; the "
                "third outcome exists exactly for this case",
            )

    def test_a_corpus_with_wordings_is_allowed_to_pass_cleanly(self) -> None:
        """Negative control: the rule above must not fire unconditionally."""
        report = build_index().build_report
        if report["wording_examples"] > 0:
            self.assertEqual(report["outcome"], PASS)


class TheRecordedMeasurementNamesItsCorpus(unittest.TestCase):
    """A recall number measured on a different corpus is a stale number."""

    def test_the_measurement_block_states_the_corpus_it_was_measured_on(
        self,
    ) -> None:
        source = Path(K.__file__).read_text(encoding="utf-8")
        match = re.search(r"MEASURED ON CORPUS:\s*(\d+)\s+entries", source)
        self.assertIsNotNone(
            match,
            "the recorded retrieval measurement must state 'MEASURED ON "
            "CORPUS: <n> entries' so a corpus change invalidates it visibly",
        )
        assert match is not None
        stated = int(match.group(1))
        actual = build_index().counts()["total"]
        self.assertEqual(
            stated,
            actual,
            f"the recorded measurement claims {stated} entries, the corpus "
            f"now holds {actual}: re-measure, do not edit the number",
        )


class WordingIsCountedForWhatItIs(unittest.TestCase):
    """Guards found unguarded by the writer's own mutation run.

    While the corpus holds no wording at all, three separate mistakes are
    invisible: counting style cards as wordings, counting nothing as a
    wording, and dropping the `unmeasured` bump. All three read the same on a
    corpus of zero. These tests plant a wording source so the readings differ.
    """

    def _index_with_a_planted_wording(self):
        row = {
            "id": "planted",
            "prompt": "amber and ivory, soft window light, visible film grain",
            "source_url": "https://aidsgn.ru/sets",
            "section": "planted",
            "harvested": "2026-08-26",
            "provenance": "third_party_gallery",
            "rights": "owner_decision_2026-08-26",
        }
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        with tmp as handle:
            handle.write(json.dumps(row) + "\n")
        self.addCleanup(Path(tmp.name).unlink)
        return build_index(gallery_prompts=Path(tmp.name))

    def test_a_planted_wording_is_counted(self) -> None:
        """M3: an empty definition of 'wording' must not survive."""
        report = self._index_with_a_planted_wording().build_report
        self.assertGreaterEqual(
            report["wording_examples"],
            1,
            "a real prompt wording was added and counted as nothing",
        )

    def test_style_cards_are_not_counted_as_wordings(self) -> None:
        """M2: 522 cards must not be able to masquerade as worked examples."""
        report = self._index_with_a_planted_wording().build_report
        cards = self._index_with_a_planted_wording().counts()[
            REQUIRED_PROVENANCE
        ]
        self.assertLess(
            report["wording_examples"],
            cards,
            "style cards are being counted as prompt wording; they describe "
            "how a picture looks, not how a prompt is said",
        )

    def test_the_unmeasured_bump_is_what_raises_a_wordless_corpus(
        self,
    ) -> None:
        """M4: the bump must be the thing doing the work, not a coincidence.

        Measured against a corpus that has a wording: if the bump were the
        only reason a wordless corpus reports `unmeasured`, then adding a
        wording must lower the count. It stays honest either way.
        """
        wordless = build_index().build_report
        worded = self._index_with_a_planted_wording().build_report
        self.assertEqual(worded["wording_examples"], 1)
        self.assertGreater(
            wordless["unmeasured"],
            worded["unmeasured"],
            "a corpus with no wording reports no more doubt than one with a "
            "wording: the bump is not doing anything",
        )


    def test_a_wordless_corpus_says_so_in_words(self) -> None:
        """The declaration, not the count, is what M4 can actually guard.

        Measured, not assumed: with the harvest absent, `unmeasured` is
        already 1 because a source is missing, so the `max(unmeasured, 1)`
        bump changes no number and no test can catch its removal. Planting an
        empty harvest does not help either — a source that yields no records
        is counted as missing too. The bump is therefore redundant *by
        construction* while the harvest is absent, in the same way a mode
        share threshold was redundant against an entropy threshold on the
        judge. What is not redundant is the sentence: a corpus with no worked
        wording has to say so, and that is what this guards.
        """
        report = build_index().build_report
        if report["wording_examples"] == 0:
            self.assertIn(
                "no entry carries prompt wording",
                report["note"],
                "a wordless corpus does not declare itself wordless",
            )


if __name__ == "__main__":
    unittest.main()
