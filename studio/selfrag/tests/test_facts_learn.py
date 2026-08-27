"""What the agent knows about models, and what it learns from its own output."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.evaluate import DEMO_CORPUS_PATH
from studio.selfrag.corpus import load_corpus
from studio.selfrag.facts import (
    TIER_BLOG,
    TIER_PAPER,
    TIER_VENDOR,
    Fact,
    FactStore,
    load_facts,
)
from studio.selfrag.learn import (
    MIN_PER_ARM,
    effects,
    export_pairs,
    features,
    preference_pairs,
)
from studio.selfrag.pipeline import PromptEngineer, PromptRequest


def fact(model: str, attribute: str, value: str, tier: str = TIER_BLOG, url: str = "u") -> Fact:
    return Fact(model=model, attribute=attribute, value=value, source_url=url, tier=tier)


class Facts(unittest.TestCase):
    def test_disagreement_is_reported_not_resolved(self) -> None:
        """The failure this whole module exists to prevent: three sources say
        15s, 10s and 3min, and a summary of them confidently says 5min — a
        number none of them gave."""
        store = FactStore(
            [
                fact("kling-3.0", "max_seconds", "15", TIER_VENDOR),
                fact("kling-3.0", "max_seconds", "10", TIER_BLOG),
            ]
        )
        out = store.claims("kling-3.0", "max_seconds")
        self.assertEqual(out["outcome"], FAIL)
        self.assertEqual(sorted(out["values"]), ["10", "15"])
        self.assertIn("disagree", out["note"])

    def test_agreement_above_blog_tier_passes(self) -> None:
        store = FactStore(
            [
                fact("veo-3.1", "max_seconds", "8", TIER_VENDOR),
                fact("veo-3.1", "max_seconds", "8", TIER_BLOG),
            ]
        )
        self.assertEqual(store.claims("veo-3.1", "max_seconds")["outcome"], PASS)

    def test_blogs_alone_never_establish_a_fact(self) -> None:
        """Ten blogs quoting each other are one source. Volume is not evidence."""
        store = FactStore([fact("x", "max_seconds", "9", TIER_BLOG, f"u{n}") for n in range(10)])
        out = store.claims("x", "max_seconds")
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIn("Repetition is not corroboration", out["note"])

    def test_a_list_is_not_a_contradiction(self) -> None:
        """A model has many failure modes and one maximum duration. Treating
        them the same made every failure mode read as a dispute between
        sources."""
        store = FactStore(
            [
                fact("k", "failure_mode", "hands mangle", TIER_PAPER),
                fact("k", "failure_mode", "background warps", TIER_PAPER),
            ]
        )
        self.assertEqual(store.claims("k", "failure_mode")["outcome"], PASS)
        self.assertEqual(store.contested(), [])

    def test_two_limitations_are_a_list_and_two_durations_are_a_dispute(self) -> None:
        """The negative control on the list rule, and the reason it is narrow.

        `limitation` and `degrades_when` joined `MULTI_VALUED` on 2026-08-27
        after a harvest made the base report 38 contested pairs of which 24
        were not disputes at all — a card that says both "faces may not be
        generated properly" and "no text control" is listing two limitations.

        The other half has to hold or the rule is just "never disagree":
        `max_seconds` must STILL contradict, because a model has one maximum
        duration and flattening two answers into a list is how a caller ends
        up billing against a number nobody published.
        """
        listed = FactStore(
            [
                fact("k", "limitation", "faces may not render properly", TIER_PAPER),
                fact("k", "limitation", "no text control", TIER_PAPER),
                fact("k", "degrades_when", "the prompt runs long", TIER_PAPER),
                fact("k", "degrades_when", "the take passes six seconds", TIER_PAPER),
                # These two joined the list an hour after the other two, and
                # only because the data said so: every contested
                # `holds_identity` pair turned out to be two readings that
                # agree, and every `benchmark_score` pair names a DIFFERENT
                # benchmark. A model has one maximum duration and many scores.
                fact("k", "benchmark_score", "VBench-2.0 Human Identity 75.67%", TIER_PAPER),
                fact("k", "benchmark_score", "GenEval Position 0.22", TIER_PAPER),
                fact("k", "holds_identity", "the face survives a reworded edit", TIER_PAPER),
                fact("k", "holds_identity", "voice identity does not persist", TIER_PAPER),
            ]
        )
        for attribute in ("limitation", "degrades_when", "benchmark_score", "holds_identity"):
            with self.subTest(attribute=attribute):
                self.assertEqual(listed.claims("k", attribute)["outcome"], PASS)
        self.assertEqual(listed.contested(), [])

        disputed = FactStore(
            [
                fact("k", "max_seconds", "5", TIER_PAPER),
                fact("k", "max_seconds", "10", TIER_PAPER),
            ]
        )
        self.assertEqual(disputed.claims("k", "max_seconds")["outcome"], FAIL)
        self.assertEqual(disputed.contested(), [("k", "max_seconds")])

    def test_what_breaks_is_answered_from_every_word_for_breaking(self) -> None:
        """A caller asking what breaks does not know which word the vendor's
        sentence earned. MEASURED 2026-08-27: reading only `failure_mode` hid
        89 `limitation` and 41 `degrades_when` rows on the day a harvest wrote
        them.

        `metric_blind_spot` stays out, and that is the control: it says a
        MEASUREMENT cannot see something, which is a claim about the benchmark
        and not about the model breaking."""
        store = FactStore(
            [
                fact("k", "failure_mode", "hands mangle", TIER_PAPER),
                fact("k", "limitation", "faces may not render properly", TIER_PAPER),
                fact("k", "degrades_when", "the take passes six seconds", TIER_PAPER),
                fact("k", "metric_blind_spot", "consistency rewards a static video", TIER_PAPER),
                fact("k", "max_seconds", "5", TIER_PAPER),
            ]
        )
        values = {f.value for f in store.failure_modes("k")}
        self.assertEqual(
            values,
            {"hands mangle", "faces may not render properly", "the take passes six seconds"},
        )

    def test_a_class_finding_reaches_every_model_and_a_family_one_does_not(self) -> None:
        """The scope is not decoration.

        26 rows sat in the base under `*` and `elevenlabs-*` and NOTHING ever
        returned them, because every query starts with a model name
        (MEASURED 2026-08-27). They come back now — but the narrow scope has
        to stay narrow, or "a voice clone never reproduces the source
        acoustics" gets said about Veo, which is a different kind of wrong.
        """
        store = FactStore(
            [
                fact("*", "metric_blind_spot", "FVD barely moves under corruption", TIER_PAPER),
                fact("eleven-*", "limitation", "a clone loses the source acoustics", TIER_PAPER),
                fact("veo-3.1", "max_seconds", "8", TIER_PAPER),
            ]
        )
        everyone = {f.value for f in store.class_claims("veo-3.1")}
        self.assertEqual(everyone, {"FVD barely moves under corruption"})

        family = {f.value for f in store.class_claims("eleven_v3")}
        self.assertEqual(
            family,
            {"FVD barely moves under corruption", "a clone loses the source acoustics"},
        )

    def test_a_class_finding_never_becomes_a_claim_about_one_model(self) -> None:
        """The control. Folding the class into the model's own answer would
        make a statement about a benchmark read as a measurement of this
        model, and would let it vote in a contradiction."""
        store = FactStore(
            [
                fact("*", "max_seconds", "5", TIER_PAPER),
                fact("veo-3.1", "max_seconds", "8", TIER_PAPER),
            ]
        )
        self.assertEqual(store.claims("veo-3.1", "max_seconds")["values"], ["8"])
        self.assertEqual(store.contested(), [])

    def test_a_near_miss_id_points_at_what_the_base_actually_holds(self) -> None:
        """Found by a blind evaluation, 2026-08-27. Asked about
        `omnihuman-1.5`, a caller was shown the REGISTRY's list of seven
        models and concluded in writing that "the fact base contains no
        dedicated lip-sync model" — while the base held 214 ids, `omnihuman-1`
        among them. A near-miss id is the commonest way to be told nothing is
        known about something that is."""
        store = FactStore(
            [
                fact("omnihuman-1", "max_seconds", "10"),
                fact("kling-lipsync-audio-to-video", "max_seconds", "60"),
                fact("veo-3.1", "max_seconds", "8"),
            ]
        )
        assert store.near("omnihuman-1.5") == ["omnihuman-1"]
        assert store.near("kling-avatar") == ["kling-lipsync-audio-to-video"]
        assert store.model_count() == 3

    def test_a_stranger_gets_no_suggestions_rather_than_a_bad_one(self) -> None:
        """The negative control: four shared characters is the floor, so an id
        with nothing in common comes back empty. A suggester that always
        suggests sends the caller to the wrong model with confidence."""
        store = FactStore([fact("omnihuman-1", "max_seconds", "10")])
        assert store.near("flux-2") == []
        assert store.near("") == []
        # One shared letter is not a near miss. Without this the floor could
        # be 1 and every test above would still pass, while a caller asking
        # about `okapi-2` would be pointed at a human-video model.
        assert store.near("okapi-2") == []
        # Four is the floor and it is reached exactly here.
        assert store.near("omni-thing") == ["omnihuman-1"]

    def test_an_unknown_attribute_is_unmeasured(self) -> None:
        store = FactStore([fact("k", "max_seconds", "9")])
        self.assertEqual(store.claims("k", "nothing_recorded")["outcome"], UNMEASURED)

    def test_an_empty_fact_base_knows_nothing_it_can_cite(self) -> None:
        out = FactStore([]).audit()
        self.assertEqual(out["outcome"], UNMEASURED)

    def test_a_blog_only_fact_base_audits_as_unestablished(self) -> None:
        store = FactStore([fact(f"m{n}", "best_for", "x", TIER_BLOG) for n in range(20)])
        out = store.audit()
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIn("nothing here is established", out["note"])

    def test_the_shipped_fact_file_parses_and_is_honest_about_itself(self) -> None:
        facts = load_facts()
        self.assertTrue(facts, "the shipped fact file produced no facts")
        store = FactStore(facts)
        audit = store.audit()
        # It is mostly blog tier and it contains real contradictions. Both are
        # true of the world it describes, and the audit must say so rather than
        # present a tidy picture.
        self.assertNotEqual(audit["outcome"], PASS)
        self.assertTrue(store.contested())
        for f in facts:
            with self.subTest(model=f.model, attribute=f.attribute):
                self.assertTrue(f.source_url, "a fact with no source cannot be checked")


class Learn(unittest.TestCase):
    def rows(self, n: int, *, rating_for) -> list[dict]:
        out = []
        for i in range(n):
            out.append(
                {
                    "run_id": f"r{i}",
                    "model": "veo-3.1",
                    "mode": "t2v",
                    "request": f"request {i % 3}",
                    "fields": {"camera": "slow dolly"} if i % 2 == 0 else {},
                    "style": {
                        "palette": ["amber"],
                        "light": "soft",
                        "texture": "matte",
                        "mood": "calm",
                        "setting": "",
                    },
                    "prompt": "a prompt " * 10,
                    "negative": "",
                    "parameters": {},
                    "outcome": PASS,
                    "findings": [],
                    "precedents": ["p1"],
                    "rating": rating_for(i),
                    "artifact": "out/x.mp4",
                }
            )
        return out

    def test_nothing_can_be_learned_from_output_nobody_looked_at(self) -> None:
        out = effects(self.rows(50, rating_for=lambda i: None))
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIn("the ratings are the whole signal", out["note"])

    def test_a_thin_comparison_is_skipped_not_reported(self) -> None:
        rows = self.rows(6, rating_for=lambda i: 8)
        out = effects(rows)
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertEqual(out["effects"], [])
        self.assertTrue(out["skipped"])

    def test_an_effect_is_reported_with_both_sample_sizes(self) -> None:
        rows = self.rows(40, rating_for=lambda i: 9 if i % 2 == 0 else 4)
        out = effects(rows)
        # Both arms of a binary feature are reported, so the value matters:
        # has_camera=True is +5 and has_camera=False is -5, the same fact twice.
        with_camera = [
            e for e in out["effects"] if e["feature"] == "has_camera" and e["value"] == "True"
        ]
        without = [
            e for e in out["effects"] if e["feature"] == "has_camera" and e["value"] == "False"
        ]
        self.assertTrue(with_camera, "the planted effect was not found")
        self.assertGreaterEqual(with_camera[0]["n_with"], MIN_PER_ARM)
        self.assertGreaterEqual(with_camera[0]["n_without"], MIN_PER_ARM)
        self.assertGreater(with_camera[0]["difference"], 0)
        self.assertLess(without[0]["difference"], 0)

    def test_a_small_sample_is_labelled_untrustworthy_even_when_it_reports(self) -> None:
        rows = self.rows(40, rating_for=lambda i: 9 if i % 2 == 0 else 4)
        out = effects(rows)
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIn("directions to investigate", out["note"])

    def test_features_are_things_somebody_could_change_tomorrow(self) -> None:
        f = features(self.rows(1, rating_for=lambda i: 8)[0])
        self.assertEqual(f["has_camera"], "True")
        self.assertEqual(f["model"], "veo-3.1")
        self.assertIn("prompt_length", f)

    def test_export_writes_the_file_even_when_it_is_too_small_to_train_on(self) -> None:
        """The count in the note is the honest answer to 'can we train yet';
        an absent file is not."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "pairs.jsonl"
            out = export_pairs(self.rows(5, rating_for=lambda i: None), target)
            self.assertEqual(out["outcome"], UNMEASURED)
            self.assertTrue(target.is_file())
            self.assertEqual(target.read_text(), "")

    def test_export_writes_rated_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "pairs.jsonl"
            out = export_pairs(self.rows(4, rating_for=lambda i: 7), target)
            self.assertEqual(out["outcome"], PASS)
            lines = [json.loads(x) for x in target.read_text().splitlines()]
            self.assertEqual(len(lines), 4)
            self.assertIn("request", lines[0])
            self.assertIn("prompt", lines[0])

    def test_preference_pairs_need_the_same_question_answered_twice(self) -> None:
        one_each = [
            {**row, "request": f"unique {i}"}
            for i, row in enumerate(self.rows(6, rating_for=lambda i: i + 2))
        ]
        out = preference_pairs(one_each)
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIn("asking each question once", out["note"])

    def test_a_narrow_margin_teaches_a_preference_nobody_holds(self) -> None:
        rows = self.rows(6, rating_for=lambda i: 5 if i % 2 else 6)
        self.assertEqual(preference_pairs(rows, margin=3)["outcome"], UNMEASURED)
        self.assertEqual(preference_pairs(rows, margin=1)["outcome"], PASS)


class TrainingPairsAreRecorded(unittest.TestCase):
    """The gap that made every kind of training impossible: the system stored
    what it produced and how it scored, and never what it was asked."""

    def test_a_run_stores_its_input_alongside_its_output(self) -> None:
        records = load_corpus(paths=[DEMO_CORPUS_PATH])["records"]
        engineer = PromptEngineer(records=records, state_path=":memory:")
        self.addCleanup(engineer.close)
        out = engineer.write(
            PromptRequest(
                text="amber golden-hour rooftop, film grain, nostalgic",
                model="veo",
                mode="t2v",
                subject="a cyclist",
                action="rides slowly past",
                camera="slow dolly in",
            )
        )
        rows = engineer.replay.training_rows(rated_only=False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["request"], "amber golden-hour rooftop, film grain, nostalgic")
        self.assertEqual(rows[0]["fields"]["subject"], "a cyclist")
        self.assertEqual(rows[0]["prompt"], out["prompt"])
        self.assertIsNone(rows[0]["rating"])

    def test_rating_an_unknown_run_is_unmeasured_not_a_failure(self) -> None:
        """The rating is real; the run it names is simply not filed here.
        Discarding it as an error would lose the scarcest thing in the system."""
        records = load_corpus(paths=[DEMO_CORPUS_PATH])["records"]
        engineer = PromptEngineer(records=records, state_path=":memory:")
        self.addCleanup(engineer.close)
        out = engineer.replay.judge_run(run_id="never-happened", rating=8, artifact="x.mp4")
        self.assertEqual(out["outcome"], UNMEASURED)

    def test_a_rating_with_no_artifact_is_a_claim_not_an_observation(self) -> None:
        records = load_corpus(paths=[DEMO_CORPUS_PATH])["records"]
        engineer = PromptEngineer(records=records, state_path=":memory:")
        self.addCleanup(engineer.close)
        run = engineer.write(
            PromptRequest(
                text="emerald forest, low-key, serene",
                model="veo",
                mode="t2v",
                subject="a deer",
                action="steps slowly",
            )
        )
        self.assertEqual(
            engineer.replay.judge_run(run_id=run["run_id"], rating=9)["outcome"], UNMEASURED
        )
        self.assertEqual(
            engineer.replay.judge_run(run_id=run["run_id"], rating=9, artifact="out/deer.mp4")[
                "outcome"
            ],
            PASS,
        )


if __name__ == "__main__":
    unittest.main()


class ReadingIsNotOwnership(unittest.TestCase):
    """Whose page it is, and whether anybody opened it, are two questions.

    Added 2026-08-27 with the owner's ladder. Most vendor hosts are refused by
    this environment, so a `vendor` row is often a summary of a page nobody
    could open — and a note that does not say so lets the summary read as the
    vendor speaking.
    """

    def _store(self, **over: object) -> FactStore:
        row = Fact(
            model="m",
            attribute="a",
            value="v",
            source_url="https://vendor.test/docs",
            tier=TIER_VENDOR,
            stated_on=date.today().isoformat(),
        )
        return FactStore([replace(row, **over)])  # type: ignore[arg-type]

    def test_an_unread_source_is_counted_and_said_out_loud(self) -> None:
        out = self._store(read_directly=False).claims("m", "a")
        assert out["outcome"] == "pass"
        assert out["sources_not_read"] == 1
        assert "NOT read" in out["note"], "a caller reading only the note must see it"

    def test_a_read_source_says_nothing_about_not_being_read(self) -> None:
        out = self._store(read_directly=True).claims("m", "a")
        assert out["sources_not_read"] == 0
        assert "NOT read" not in out["note"]

    def test_no_record_is_a_third_state_and_not_a_no(self) -> None:
        out = self._store(read_directly=None).claims("m", "a")
        assert out["sources_not_read"] == 0, "nobody recorded it is not nobody read it"
        assert out["sources_reading_unrecorded"] == 1
        assert "no reading recorded" in out["note"]

    def test_the_flag_reaches_the_caller_per_source_not_only_as_a_count(self) -> None:
        out = self._store(read_directly=False).claims("m", "a")
        assert out["claims"][0]["sources"][0]["read_directly"] is False

    def test_a_row_written_before_the_field_existed_reads_as_unrecorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "facts.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "model": "m",
                        "attribute": "a",
                        "value": "v",
                        "source_url": "https://vendor.test/d",
                        "tier": TIER_VENDOR,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            loaded = load_facts(path)
        assert loaded[0].read_directly is None, "absent is unrecorded, never False"
