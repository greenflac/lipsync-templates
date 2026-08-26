"""Reflection rules, cache invalidation, replay feedback, the journal, and the
evaluation harness's own refusal to score itself dishonestly."""

from __future__ import annotations

import unittest

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.cache import PromptCache, fingerprint
from studio.selfrag.corpus import CorpusRecord
from studio.selfrag.evaluate import evaluate
from studio.selfrag.monitor import Journal, RunRecord
from studio.selfrag.reflect import (
    RULES,
    SEVERITY_RISK,
    grade_context,
    grade_draft,
    judge,
    reflect,
)
from studio.selfrag.replay import FEEDBACK_CEILING, FEEDBACK_FLOOR, ReplayBuffer
from studio.selfrag.retrieval import Hit, build_corpus_index
from studio.selfrag.spec import GenSpec, MODE_I2V, MODE_T2V, assemble
from studio.style import StyleSpec

STYLE = StyleSpec(("teal", "gold"), "golden-hour", "film-grain", "calm", "a rooftop at dusk")


def hit(record_id: str, *, channels=("bm25", "phrase", "tag"), term_hits=3) -> Hit:
    return Hit(CorpusRecord(record_id, "a prompt"), 0.1, tuple(channels), term_hits)


class GradeContext(unittest.TestCase):
    def test_nothing_retrieved_is_unmeasured_not_a_failure(self) -> None:
        out = grade_context([])
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertEqual(out["kept"], [])

    def test_a_strong_set_passes_and_is_kept(self) -> None:
        out = grade_context([hit("r1")])
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual(len(out["kept"]), 1)

    def test_a_weak_set_is_dropped_not_downweighted(self) -> None:
        """Conditioning on near-miss examples is worse than conditioning on
        none, so a weak set leaves with nothing kept."""
        out = grade_context([hit("r1", channels=("bm25",), term_hits=1)], rewrite_step=3)
        self.assertEqual(out["outcome"], FAIL)
        self.assertEqual(out["kept"], [])

    def test_the_floor_is_mutable_in_both_directions(self) -> None:
        """A mid-strength set: one channel, one term. Its confidence is 1/3, so
        a floor either side of that has to flip the verdict, and a floor that
        cannot flip it is a floor nothing is guarding."""
        hits = [hit("r1", channels=("bm25",), term_hits=1)]
        self.assertAlmostEqual(grade_context(hits, floor=0.0)["confidence"], 0.3333, places=3)
        self.assertEqual(grade_context(hits, floor=0.2)["outcome"], PASS)
        self.assertEqual(grade_context(hits, floor=0.5)["outcome"], FAIL)


class GradeDraft(unittest.TestCase):
    def bad_kling(self) -> GenSpec:
        """A spec that breaks a rule with a mechanical answer: Seedance's
        camera_fixed parameter controls what the camera clause is trying to."""
        return GenSpec(
            model="seedance-2.0",
            mode=MODE_T2V,
            style=STYLE,
            subject="a table",
            motion="leaning in slowly",
            camera="gentle handheld drift",
        )

    def test_a_known_bad_draft_is_caught(self) -> None:
        spec = self.bad_kling()
        out = grade_draft(spec, assemble(spec))
        self.assertEqual(out["outcome"], FAIL)
        self.assertGreaterEqual(out["violations"], 1)

    def test_dropping_the_rule_stops_it_being_caught(self) -> None:
        """The mutation that proves the rule is load-bearing: with its rule
        removed from the table, the same known-bad draft stops failing."""
        spec = self.bad_kling()
        draft = assemble(spec)
        every = sorted(name for name, _ in RULES)
        without = [name for name in every if name != "parameter_beats_prose"]
        self.assertEqual(grade_draft(spec, draft, rules=every)["outcome"], FAIL)
        self.assertNotEqual(grade_draft(spec, draft, rules=without)["outcome"], FAIL)

    def test_zero_rules_is_never_a_pass(self) -> None:
        spec = self.bad_kling()
        out = grade_draft(spec, assemble(spec), rules=[])
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertEqual(out["checked"], 0)

    def test_a_standing_caveat_does_not_change_the_verdict(self) -> None:
        """The defect this separation fixed: 'the cards are second-hand' is
        true on every run forever, and while it counted as unmeasured it made
        every single run unmeasurable, hiding the real ones."""
        spec = GenSpec(
            model="veo-3.1",
            mode=MODE_T2V,
            style=STYLE,
            subject="a cyclist",
            action="rides slowly past",
            camera="slow dolly in",
            audio="wind",
        )
        out = grade_draft(spec, assemble(spec))
        self.assertEqual(out["outcome"], PASS)
        self.assertGreaterEqual(out["caveats"], 1)
        self.assertIn("standing caveats", out["note"])

    def test_documented_failure_modes_are_flagged_as_risks(self) -> None:
        cases = {
            "on-screen text": GenSpec(
                model="veo-3.1",
                mode=MODE_T2V,
                style=STYLE,
                subject="a neon sign reading OPEN",
                action="flickers slowly",
            ),
            "object permanence": GenSpec(
                model="veo-3.1",
                mode=MODE_T2V,
                style=STYLE,
                subject="a fox",
                action="walks behind a tree slowly",
            ),
            "unstated motion rate": GenSpec(
                model="wan-2.6-flash",
                mode=MODE_T2V,
                style=STYLE,
                subject="gulls",
                motion="drifting over the water",
            ),
            "too many chained actions": GenSpec(
                model="veo-3.1",
                mode=MODE_T2V,
                style=STYLE,
                subject="a cyclist",
                action="rides slowly then stops and then waves",
            ),
        }
        for name, spec in cases.items():
            with self.subTest(case=name):
                findings = grade_draft(spec, assemble(spec))["findings"]
                self.assertTrue(
                    any(f.severity == SEVERITY_RISK for f in findings),
                    f"{name} produced no risk finding",
                )

    def test_an_i2v_prompt_that_repeats_appearance_is_flagged(self) -> None:
        spec = GenSpec(
            model="kling-3.0", mode=MODE_I2V, style=STYLE, motion="turns her head slowly"
        )
        draft = assemble(spec)
        draft = {**draft, "prompt": (draft["prompt"] or "") + ", a teal coat"}
        findings = grade_draft(spec, draft)["findings"]
        self.assertTrue(any(f.rule == "i2v_appearance" for f in findings))


class Judge(unittest.TestCase):
    def test_the_judge_may_not_be_the_writer(self) -> None:
        same = lambda _: "GOOD"  # noqa: E731
        out = judge({"prompt": "x"}, judge_model=same, writer_model=same)
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIn("that is not a measurement", out["note"])

    def test_the_three_answers_map_to_the_three_outcomes(self) -> None:
        for answer, expected in (("GOOD", PASS), ("WEAK", FAIL), ("maybe?", UNMEASURED)):
            with self.subTest(answer=answer):
                out = judge({"prompt": "x"}, judge_model=lambda _: answer)
                self.assertEqual(out["outcome"], expected)

    def test_a_judge_that_raises_is_unmeasured(self) -> None:
        def boom(_: str) -> str:
            raise RuntimeError("no")

        self.assertEqual(judge({"prompt": "x"}, judge_model=boom)["outcome"], UNMEASURED)


class Reflect(unittest.TestCase):
    def test_a_reviser_that_changes_nothing_stops_the_loop(self) -> None:
        spec = GenSpec(
            model="seedance-2.0",
            mode=MODE_T2V,
            style=STYLE,
            subject="a table",
            camera="gentle drift",
        )
        out = reflect(spec, reviser=lambda s, f: s, rounds=3)
        self.assertEqual(out["rounds_used"], 1)
        self.assertIn("changed nothing", out["history"][-1]["note"])

    def test_running_out_of_rounds_is_said_out_loud(self) -> None:
        bump = lambda s, f: GenSpec(**{**s.__dict__, "subject": s.subject + "!"})  # noqa: E731
        spec = GenSpec(
            model="seedance-2.0",
            mode=MODE_T2V,
            style=STYLE,
            subject="a table",
            camera="gentle drift",
        )
        out = reflect(spec, reviser=bump, rounds=2)
        self.assertEqual(out["rounds_used"], 2)
        self.assertIn("did not converge", out["note"])


class Cache(unittest.TestCase):
    def test_a_changed_corpus_expires_the_entry(self) -> None:
        """The way a request-keyed cache goes wrong: the request is identical
        and the world that shaped the answer is not."""
        before = fingerprint([CorpusRecord("r1", "p", rating=5)])
        after = fingerprint([CorpusRecord("r1", "p", rating=9)])
        self.assertNotEqual(before, after)

        cache = PromptCache(path=":memory:", fingerprint_value=before)
        self.addCleanup(cache.close)
        cache.put({"model": "veo-3.1"}, {"prompt": "old"})
        self.assertEqual(cache.get({"model": "veo-3.1"})["outcome"], PASS)
        cache.fingerprint = after
        self.assertEqual(cache.get({"model": "veo-3.1"})["outcome"], UNMEASURED)

    def test_a_miss_is_unmeasured_not_a_failure(self) -> None:
        cache = PromptCache(path=":memory:", fingerprint_value="abc")
        self.addCleanup(cache.close)
        out = cache.get({"model": "nope"})
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertEqual(out["note"], "cache miss")

    def test_a_cache_without_a_fingerprint_refuses_to_answer(self) -> None:
        cache = PromptCache(path=":memory:", fingerprint_value="")
        self.addCleanup(cache.close)
        self.assertEqual(cache.get({"a": 1})["outcome"], UNMEASURED)

    def test_sweeping_drops_only_the_stale(self) -> None:
        cache = PromptCache(path=":memory:", fingerprint_value="one")
        self.addCleanup(cache.close)
        cache.put({"a": 1}, {"prompt": "x"})
        cache.fingerprint = "two"
        cache.put({"a": 2}, {"prompt": "y"})
        out = cache.sweep()
        self.assertEqual(out["dropped"], 1)
        self.assertEqual(cache.stats()["entries"], 1)


class Replay(unittest.TestCase):
    def setUp(self) -> None:
        self.buffer = ReplayBuffer(path=":memory:")
        self.addCleanup(self.buffer.close)

    def test_an_unrated_record_is_neutral(self) -> None:
        self.assertEqual(self.buffer.boost()(CorpusRecord("x", "p")), 1.0)

    def test_feedback_moves_the_multiplier_and_stays_inside_its_bounds(self) -> None:
        for _ in range(20):
            self.buffer.record(
                record_id="bad", prompt="p", model="m", outcome=PASS, rating=1, artifact="out/x.mp4"
            )
            self.buffer.record(
                record_id="good",
                prompt="p",
                model="m",
                outcome=PASS,
                rating=10,
                artifact="out/y.mp4",
            )
        boost = self.buffer.boost()
        self.assertEqual(boost(CorpusRecord("bad", "p")), FEEDBACK_FLOOR)
        self.assertEqual(boost(CorpusRecord("good", "p")), FEEDBACK_CEILING)

    def test_a_middling_rating_is_evidence_for_neither_side(self) -> None:
        self.buffer.record(
            record_id="mid", prompt="p", model="m", outcome=PASS, rating=5, artifact="out/z.mp4"
        )
        self.assertEqual(self.buffer.boost()(CorpusRecord("mid", "p")), 1.0)

    def test_a_report_with_no_artifact_is_a_claim_not_an_observation(self) -> None:
        out = self.buffer.record(record_id="x", prompt="p", model="m", outcome=PASS, rating=9)
        self.assertEqual(out["outcome"], UNMEASURED)

    def test_a_rating_off_the_scale_is_refused(self) -> None:
        out = self.buffer.record(record_id="x", prompt="p", model="m", outcome=PASS, rating=42)
        self.assertEqual(out["outcome"], FAIL)


class JournalReport(unittest.TestCase):
    def test_an_empty_journal_is_not_a_healthy_one(self) -> None:
        journal = Journal(path=":memory:")
        self.addCleanup(journal.close)
        out = journal.report()
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertEqual(out["runs"], 0)

    def test_mostly_unmeasurable_runs_do_not_read_as_passing(self) -> None:
        journal = Journal(path=":memory:")
        self.addCleanup(journal.close)
        journal.append(RunRecord(run_id="a", model="veo-3.1", mode="t2v", outcome=PASS))
        for i in range(3):
            journal.append(
                RunRecord(run_id=f"u{i}", model="veo-3.1", mode="t2v", outcome=UNMEASURED)
            )
        out = journal.report()
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIn("the instrument is the problem", out["note"])

    def test_rates_are_printed_with_their_denominator(self) -> None:
        journal = Journal(path=":memory:")
        self.addCleanup(journal.close)
        journal.append(
            RunRecord(
                run_id="a", model="veo-3.1", mode="t2v", outcome=PASS, cached=True, retrieved=2
            )
        )
        text = journal.render()
        self.assertIn("1/1", text)


class Evaluate(unittest.TestCase):
    def gold(self) -> list[dict]:
        return [
            {
                "id": "g1",
                "query": "crimson neon alley hazy mysterious",
                "expect": "hit",
                "must_retrieve": ["neon alley"],
            },
            {
                "id": "n1",
                "query": "kubernetes ingress certificate rotation",
                "expect": "abstain",
                "must_retrieve": [],
            },
        ]

    def index(self):
        idx = build_corpus_index(
            [
                CorpusRecord(
                    "r1",
                    "crimson neon alley, hazy texture, mysterious mood",
                    model="kling-3.0",
                    tags=("neon",),
                    rating=8,
                ),
                CorpusRecord(
                    "r2",
                    "emerald forest floor, low-key light, serene mood",
                    model="veo-3.1",
                    tags=("forest",),
                    rating=9,
                ),
            ]
        )
        self.addCleanup(idx.close)
        return idx

    def test_a_gold_set_with_no_negative_control_reports_no_numbers(self) -> None:
        """An instrument with no negative control produces a number that will
        be quoted, and that is worse than producing none."""
        positives = [row for row in self.gold() if row["expect"] == "hit"]
        out = evaluate(self.index(), positives)
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertNotIn("recall_at_k", out)

    def test_a_full_gold_set_scores(self) -> None:
        out = evaluate(self.index(), self.gold())
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual(out["recall_at_k"], 1.0)
        self.assertEqual(out["abstention_rate"], 1.0)

    def test_an_empty_index_scores_nothing(self) -> None:
        empty = build_corpus_index([])
        self.addCleanup(empty.close)
        self.assertEqual(evaluate(empty, self.gold())["outcome"], UNMEASURED)


if __name__ == "__main__":
    unittest.main()
