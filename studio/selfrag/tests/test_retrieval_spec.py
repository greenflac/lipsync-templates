"""Retrieval, the rewrite ladder, and prompt assembly per vendor skeleton."""

from __future__ import annotations

import unittest

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.corpus import CorpusRecord
from studio.selfrag.retrieval import (
    build_corpus_index,
    confidence,
    rating_prior,
    rewrite_query,
    search,
    search_with_fallback,
)
from studio.selfrag.spec import GenSpec, MODE_I2V, MODE_T2V, assemble, gate_spec
from studio.style import StyleSpec

STYLE = StyleSpec(("teal", "gold"), "golden-hour", "film-grain", "calm", "a rooftop at dusk")


def records() -> list[CorpusRecord]:
    """Fixtures from both ends of the range and the middle: a long jargon-heavy
    prompt, a bare one, and several ordinary ones."""
    return [
        CorpusRecord(
            "r1",
            "a rain-slick rooftop at dusk in golden-hour light with film-grain "
            "texture and a nostalgic mood, slow dolly in",
            model="veo-3.1",
            tags=("rooftop", "dusk"),
            rating=9,
        ),
        CorpusRecord(
            "r2",
            "crimson neon alley, hazy texture, mysterious mood, handheld tracking",
            model="kling-3.0",
            tags=("neon", "night"),
            rating=7,
        ),
        CorpusRecord("r3", "gulls", model="wan-2.6-flash", tags=("harbour",), rating=None),
        CorpusRecord(
            "r4",
            "emerald forest floor in low-key light, smoky texture, serene mood",
            model="veo-3.1",
            tags=("forest",),
            rating=10,
        ),
        CorpusRecord(
            "r5",
            "charcoal studio backdrop, hard light, metallic texture, dramatic mood",
            model="flux-2",
            tags=("studio",),
            rating=3,
        ),
    ]


class Search(unittest.TestCase):
    def setUp(self) -> None:
        self.index = build_corpus_index(records())
        self.addCleanup(self.index.close)

    def test_an_empty_index_is_unmeasured_not_a_miss(self) -> None:
        empty = build_corpus_index([])
        self.addCleanup(empty.close)
        out = search("anything", index=empty)
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertEqual(out["checked"], 0)

    def test_a_real_query_finds_its_record(self) -> None:
        out = search("rooftop at dusk golden-hour film-grain", index=self.index)
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual(out["hits"][0].record.record_id, "r1")

    def test_the_negative_control_returns_nothing(self) -> None:
        """The instrument must be able to say no. Without this, every recall
        number below is the number a machine that always answers would get."""
        out = search("kubernetes ingress certificate rotation runbook", index=self.index)
        self.assertEqual(out["outcome"], FAIL)
        self.assertEqual(out["hits"], [])

    def test_the_positive_control_moves(self) -> None:
        """The other half of a negative control: an input it must react to."""
        out = search("charcoal studio backdrop hard light metallic", index=self.index)
        self.assertEqual(out["hits"][0].record.record_id, "r5")

    def test_dropping_a_channel_changes_the_answer(self) -> None:
        """A fusion nobody can turn off is a fusion nobody has measured."""
        # No word here is a corpus tag or an allow-list style word, so the
        # tag channel has nothing to fire on. ("neon" would have matched: it is
        # on the LIGHT allow-list as well as being an r2 tag.)
        query = "alley handheld tracking"
        full = search(query, index=self.index)
        tag_only = search(query, index=self.index, channels=("tag",))
        bm25_only = search(query, index=self.index, channels=("bm25",))
        self.assertEqual(full["outcome"], PASS)
        self.assertEqual(full["hits"][0].record.record_id, "r2")
        # The tag channel alone knows nothing about these words: the query
        # carries no tag from the corpus, so the channel nominates nobody.
        self.assertEqual(tag_only["hits"], [])
        self.assertEqual(tag_only["unmeasured"], 3)
        # And the lexical channel alone still finds it, which is the honest
        # reading: at this size BM25 is carrying the retrieval.
        self.assertEqual(bm25_only["hits"][0].record.record_id, "r2")

    def test_the_rating_channel_never_nominates_on_its_own(self) -> None:
        """A well-rated record that matches nothing is a popular answer to a
        different question. The rating orders candidates, it never admits them."""
        out = search("kubernetes ingress certificate", index=self.index, channels=("rating",))
        self.assertEqual(out["hits"], [])

    def test_cross_model_examples_rank_below_in_model_ones(self) -> None:
        both = search("light texture mood", index=self.index)
        veo = search("light texture mood", index=self.index, model="veo-3.1")
        if veo["hits"] and both["hits"]:
            self.assertEqual(veo["hits"][0].record.model, "veo-3.1")

    def test_boost_reorders_and_can_be_mutated_both_ways(self) -> None:
        query = "light texture mood"
        plain = search(query, index=self.index)
        lifted = search(
            query, index=self.index, boost=lambda r: 5.0 if r.record_id == "r5" else 1.0
        )
        buried = search(
            query,
            index=self.index,
            boost=lambda r: 0.0 if r.record_id == plain["hits"][0].record.record_id else 1.0,
        )
        self.assertEqual(lifted["hits"][0].record.record_id, "r5")
        self.assertLess(
            buried["hits"][-1].score,
            plain["hits"][0].score,
        )


class RewriteLadder(unittest.TestCase):
    def test_each_step_widens_deterministically(self) -> None:
        text = "a navy jumper in harsh light on a cinematic rooftop"
        self.assertEqual(rewrite_query(text, 0), text)
        self.assertIn("indigo", rewrite_query(text, 1))
        self.assertIn("hard", rewrite_query(text, 1))
        self.assertLessEqual(len(rewrite_query(text, 2).split()), 3)
        self.assertEqual(len(rewrite_query(text, 3).split()), 1)

    def test_the_step_the_answer_came_from_is_reported(self) -> None:
        index = build_corpus_index(records())
        self.addCleanup(index.close)
        out = search_with_fallback("kubernetes ingress certificate rotation", index=index)
        self.assertEqual(out["outcome"], FAIL)
        self.assertEqual(out["rewrite_step"], 3)

    def test_widening_decays_confidence(self) -> None:
        index = build_corpus_index(records())
        self.addCleanup(index.close)
        hits = search("rooftop dusk golden-hour film-grain", index=index)["hits"]
        self.assertGreater(confidence(hits, rewrite_step=0), confidence(hits, rewrite_step=2))

    def test_an_unrated_record_is_neutral_not_bad(self) -> None:
        self.assertEqual(rating_prior(CorpusRecord("x", "p")), 1.0)
        self.assertLess(rating_prior(CorpusRecord("x", "p", rating=1)), 1.0)
        self.assertGreater(rating_prior(CorpusRecord("x", "p", rating=10)), 1.0)


class Assemble(unittest.TestCase):
    def test_slot_order_follows_the_vendor_skeleton(self) -> None:
        veo = assemble(
            GenSpec(
                model="veo-3.1",
                mode=MODE_T2V,
                style=STYLE,
                subject="a cyclist",
                action="rides slowly past",
                camera="slow dolly in",
                audio="wind",
            )
        )
        self.assertEqual(veo["outcome"], PASS)
        prompt = veo["prompt"]
        self.assertLess(prompt.index("a cyclist"), prompt.index("rides slowly past"))
        # Veo is the only card with audio as a slot, and its guide puts it last.
        self.assertTrue(prompt.endswith("wind"))

    def test_an_unknown_model_yields_no_prompt(self) -> None:
        out = assemble(GenSpec(model="kling-3.1", mode=MODE_T2V, style=STYLE, subject="x"))
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIsNone(out["prompt"])

    def test_image_to_video_drops_appearance_on_purpose(self) -> None:
        out = assemble(
            GenSpec(
                model="runway-gen-4.5",
                mode=MODE_I2V,
                style=STYLE,
                subject="a dancer in a red coat",
                motion="turns her head slowly",
            )
        )
        self.assertEqual(out["outcome"], PASS)
        self.assertNotIn("dancer", out["prompt"])
        self.assertIn("subject", out["dropped_by_design"])
        self.assertEqual(out["dropped"], [])

    def test_a_field_with_nowhere_to_go_is_reported(self) -> None:
        """Silent data loss: the caller described something, paid for a render,
        and never learned the words went nowhere."""
        # Kling generates audio, so the gate allows the field — but its
        # documented skeleton has no audio slot, so the words would vanish.
        out = assemble(
            GenSpec(
                model="kling-3.0",
                mode=MODE_T2V,
                style=STYLE,
                subject="a figure",
                action="walks slowly",
                audio="a distant violin",
            )
        )
        self.assertEqual(out["outcome"], PASS)
        self.assertIn("audio", out["dropped"])
        self.assertNotIn("violin", out["prompt"])

    def test_every_branch_of_assemble_returns_the_same_keys(self) -> None:
        """An early return with fewer keys is a KeyError on the unhappy path."""
        good = assemble(GenSpec(model="veo-3.1", mode=MODE_T2V, style=STYLE, subject="x"))
        unknown = assemble(GenSpec(model="kling-3.1", mode=MODE_T2V, style=STYLE, subject="x"))
        refused = assemble(
            GenSpec(
                model="runway-gen-4.5", mode=MODE_T2V, style=STYLE, subject="x", duration_seconds=99
            )
        )
        for other in (unknown, refused):
            self.assertEqual(set(good) - set(other), set())

    def test_identical_clauses_collapse(self) -> None:
        out = assemble(
            GenSpec(
                model="veo-3.1", mode=MODE_T2V, style=STYLE, subject="a cyclist", action="a cyclist"
            )
        )
        self.assertEqual(out["prompt"].count("a cyclist"), 1)

    def test_a_negative_prompt_field_is_used_when_the_vendor_has_one(self) -> None:
        kling = assemble(
            GenSpec(
                model="kling-3.0",
                mode=MODE_T2V,
                style=STYLE,
                subject="a figure",
                action="walks slowly",
                constraints=("warped background",),
            )
        )
        runway = assemble(
            GenSpec(
                model="runway-gen-4.5",
                mode=MODE_T2V,
                style=STYLE,
                subject="a figure",
                action="walks slowly",
                constraints=("warped background",),
            )
        )
        self.assertEqual(kling["negative_prompt"], "warped background")
        self.assertEqual(runway["negative_prompt"], "")
        self.assertIn("warped background", runway["prompt"])

    def test_the_gate_refuses_what_the_vendor_cannot_do(self) -> None:
        cases = {
            "audio on a silent model": GenSpec(
                model="runway-gen-4.5", mode=MODE_T2V, style=STYLE, subject="x", audio="a violin"
            ),
            "over the duration limit": GenSpec(
                model="runway-gen-4.5", mode=MODE_T2V, style=STYLE, subject="x", duration_seconds=30
            ),
            "an aspect ratio it has not got": GenSpec(
                model="runway-gen-4.5", mode=MODE_T2V, style=STYLE, subject="x", aspect_ratio="21:9"
            ),
            "video from an image model": GenSpec(
                model="flux-2", mode=MODE_T2V, style=STYLE, subject="x"
            ),
        }
        for name, spec in cases.items():
            with self.subTest(case=name):
                self.assertEqual(gate_spec(spec)["outcome"], FAIL)

    def test_a_banned_topic_in_a_new_slot_is_still_banned(self) -> None:
        """The new free-text slots go through the studio's existing lists, not
        a second copy of them."""
        from studio.style import VIOLENCE_WORDS

        spec = GenSpec(
            model="veo-3.1",
            mode=MODE_T2V,
            style=STYLE,
            subject="x",
            action=f"someone is {VIOLENCE_WORDS[0]}",
        )
        self.assertEqual(gate_spec(spec)["outcome"], FAIL)

    def test_the_subject_zone_guard_still_bites(self) -> None:
        spec = GenSpec(
            model="veo-3.1",
            mode=MODE_T2V,
            style=STYLE,
            subject="a woman in a red dress",
            action="walks",
            subject_locked=True,
        )
        out = assemble(spec)
        self.assertEqual(out["outcome"], FAIL)
        self.assertIn("subject zone", out["note"])


if __name__ == "__main__":
    unittest.main()
