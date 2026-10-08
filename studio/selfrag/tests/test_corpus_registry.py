"""Corpus loading and the model registry: the two places a silent default hurts."""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.corpus import load_corpus, parse_row
from studio.selfrag.registry import (
    GATHERED_ON,
    STALE_AFTER_DAYS,
    availability,
    card_for,
    fits_duration,
    known_models,
)


class LoadCorpus(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name: str, rows: list) -> Path:
        path = self.dir / name
        path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n")
        return path

    def test_no_file_is_unmeasured_not_an_empty_corpus(self) -> None:
        """The defect this whole module was written after: a missing corpus that
        reads as an empty one ships an agent with no examples and no warning."""
        out = load_corpus(paths=[self.dir / "nope.jsonl"])
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertEqual(out["records"], [])
        self.assertIn("not an empty corpus", out["note"])

    def test_records_load_and_normalise(self) -> None:
        path = self.write(
            "c.jsonl",
            [
                {
                    "prompt": "a  rooftop   at dusk",
                    "model": "VEO-3.1",
                    "tags": ["Dusk", "dusk"],
                    "rating": 9,
                    "result": "out/a.mp4",
                },
            ],
        )
        out = load_corpus(paths=[path])
        self.assertEqual(out["outcome"], PASS)
        record = out["records"][0]
        self.assertEqual(record.prompt, "a rooftop at dusk")
        self.assertEqual(record.model, "veo-3.1")
        self.assertEqual(record.tags, ("dusk",))
        self.assertEqual(record.rating, 9)

    def test_unreadable_rows_are_counted_not_dropped_in_silence(self) -> None:
        path = self.write(
            "c.jsonl",
            [
                {"prompt": "good one"},
                "{not json",
                {"result": "no prompt here"},
                {"prompt": "bad rating", "rating": 99},
            ],
        )
        out = load_corpus(paths=[path])
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual(len(out["records"]), 1)
        self.assertEqual(out["violations"], 3)
        self.assertEqual(out["checked"], 4)

    def test_every_row_unreadable_is_fail_not_unmeasured(self) -> None:
        """A file that exists and is garbage is a failure; a file that is absent
        is not. Collapsing the two hides which one you have."""
        path = self.write("c.jsonl", ["{bad", "{also bad"])
        out = load_corpus(paths=[path])
        self.assertEqual(out["outcome"], FAIL)
        self.assertEqual(out["violations"], 2)

    def test_rating_outside_the_documented_scale_is_rejected(self) -> None:
        for bad in (0, 11, -3, "high"):
            with self.subTest(rating=bad):
                record, why = parse_row({"prompt": "p", "rating": bad}, source="s", line_no=1)
                self.assertIsNone(record)
                self.assertIn("rating", why or "")

    def test_absent_rating_is_none_not_zero(self) -> None:
        record, _ = parse_row({"prompt": "p"}, source="s", line_no=1)
        assert record is not None
        self.assertIsNone(record.rating)

    def test_duplicate_ids_keep_the_first(self) -> None:
        path = self.write(
            "c.jsonl",
            [{"id": "x", "prompt": "first"}, {"id": "x", "prompt": "second"}],
        )
        out = load_corpus(paths=[path])
        self.assertEqual(len(out["records"]), 1)
        self.assertEqual(out["records"][0].prompt, "first")
        self.assertEqual(out["violations"], 1)


class Registry(unittest.TestCase):
    def test_aliases_resolve_and_unverified_names_do_not(self) -> None:
        kling = card_for("KLING")
        veo = card_for("veo3")
        assert kling is not None and veo is not None
        self.assertEqual(kling.model_id, "kling-3.0")
        self.assertEqual(veo.model_id, "veo-3.1")
        # The live example: no evidence 'kling-3.1' exists. Resolving it to 3.0
        # would build a prompt against limits nobody checked.
        self.assertIsNone(card_for("kling-3.1"))
        self.assertIsNone(card_for(""))

    def test_unknown_model_is_unmeasured_not_a_failure(self) -> None:
        out = availability("kling-3.1", today=GATHERED_ON)
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertEqual(out["checked"], 0)

    def test_end_of_life_is_a_failure_only_after_the_date(self) -> None:
        before = availability("sora-2", today=date(2026, 9, 23))
        after = availability("sora-2", today=date(2026, 9, 24))
        self.assertNotEqual(before["outcome"], FAIL)
        self.assertEqual(after["outcome"], FAIL)
        self.assertIn("end of life", after["note"])

    def test_a_stale_card_stops_claiming_to_be_current(self) -> None:
        fresh = availability("veo-3.1", today=GATHERED_ON)
        stale = availability(
            "veo-3.1", today=date.fromordinal(GATHERED_ON.toordinal() + STALE_AFTER_DAYS + 1)
        )
        self.assertEqual(fresh["outcome"], PASS)
        self.assertEqual(stale["outcome"], UNMEASURED)

    def test_duration_limits_have_three_outcomes(self) -> None:
        self.assertEqual(fits_duration("runway", 5)["outcome"], PASS)
        self.assertEqual(fits_duration("runway", 15)["outcome"], FAIL)
        # No sourced maximum is not permission.
        self.assertEqual(fits_duration("sora-2", 5)["outcome"], UNMEASURED)
        self.assertEqual(fits_duration("flux-2", 5)["outcome"], FAIL)

    def test_every_card_carries_its_evidence(self) -> None:
        """A card with no source is a claim nobody can check later."""
        for model_id in known_models():
            with self.subTest(model=model_id):
                card = card_for(model_id)
                assert card is not None
                self.assertTrue(card.sources, f"{model_id} cites nothing")
                self.assertIn(card.confidence, ("weak", "strong"))


if __name__ == "__main__":
    unittest.main()
