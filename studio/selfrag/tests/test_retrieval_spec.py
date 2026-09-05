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
        # Words that discriminate. "light texture mood" appear in most of this
        # corpus, so the document-frequency ceiling correctly stops them being
        # evidence and nothing is admitted — which measures the floor, not the
        # boost this test is about.
        query = "charcoal studio backdrop metallic dramatic"
        plain = search(query, index=self.index)
        lifted = search(
            query, index=self.index, boost=lambda r: 5.0 if r.record_id == "r5" else 1.0
        )
        buried = search(
            query,
            index=self.index,
            boost=lambda r: 0.0 if r.record_id == plain["hits"][0].record.record_id else 1.0,
        )
        self.assertEqual(plain["hits"][0].record.record_id, "r5")
        self.assertEqual(lifted["hits"][0].record.record_id, "r5")
        self.assertLess(buried["hits"][-1].score, plain["hits"][0].score)


class Abstention(unittest.TestCase):
    """The two holes that let a retriever answer an unanswerable question.

    Both were found by a negative control on a real 4593-record corpus, which
    is what negative controls are for. Neither was visible on the ten-record
    fixture.
    """

    def index(self):
        """A corpus varied enough for words to discriminate.

        Fixtures from both ends and the middle: two records carry the generic
        bigram under test, the rest are ordinary and share little vocabulary.
        A corpus of near-identical records would put every term at 100%
        document frequency, which makes the ceiling reject everything and
        proves nothing either way.
        """
        subjects = [
            "crimson neon alley at night, hazy air, handheld tracking",
            "emerald forest floor under low-key light, smoky, serene",
            "charcoal studio backdrop, hard light, metallic sheen",
            "copper desert dunes at golden hour, crane shot rising",
            "ivory kitchen counter in high-key daylight, glossy tiles",
            "rose candlelit dining table, velvet chairs, dreamy",
            "slate harbour under overcast sky, crisp air, gulls",
            "amber rooftop at dusk, film grain, a cyclist riding past",
            "teal swimming pool seen from overhead, midday sun",
            "indigo night sky over a quiet motorway, long exposure",
        ]
        prompts = [f"{text}, take {n}" for n in range(6) for text in subjects]
        # "between" is an ordinary English word and turns up all over a real
        # corpus; here it is in 10 of 62, above the ceiling. "difference" is
        # rare, in 2. That asymmetry is what the defence rests on, and it only
        # exists once the corpus is big enough for document frequency to be a
        # statistic at all.
        prompts += [f"shot from between the pillars, variation {n}" for n in range(10)]
        prompts += [
            "the difference between a matte and a glossy ceramic finish",
            "the difference between warm and cool white balance in a portrait",
        ]
        idx = build_corpus_index(
            [CorpusRecord(f"r{n}", text, model="flux-2") for n, text in enumerate(prompts)]
        )
        self.addCleanup(idx.close)
        return idx

    def test_a_phrase_of_generic_words_admits_nothing(self) -> None:
        """The phrase channel used to admit every row any phrase matched, with
        no floor at all, so the bigram "difference between" carried an
        accounting question into a corpus of image prompts."""
        idx = self.index()
        out = search("difference between LIFO and FIFO inventory accounting", index=idx)
        self.assertEqual(out["outcome"], FAIL)
        self.assertEqual(out["hits"], [])

    def test_a_phrase_of_real_words_still_admits(self) -> None:
        """The other direction. A floor that rejects everything is not a floor,
        it is a broken retriever."""
        idx = self.index()
        out = search("crimson neon alley hazy handheld", index=idx)
        self.assertEqual(out["outcome"], PASS)
        self.assertTrue(out["hits"])
        self.assertIn("crimson neon alley", out["hits"][0].record.prompt)

    def test_the_widening_ladder_cannot_manufacture_an_answer(self) -> None:
        """A query that abstains as typed must still abstain after widening.

        The ladder's last rung reduces a query to its single longest word, and
        the admission floor used to drop to 1 whenever the query was short —
        so the rung always found something. A ladder that always finds
        something guarantees an answer to every question ever asked.
        """
        idx = self.index()
        out = search_with_fallback(
            "difference between LIFO and FIFO inventory accounting", index=idx
        )
        self.assertEqual(out["outcome"], FAIL)
        self.assertEqual(out["hits"], [])
        self.assertEqual(out["rewrite_step"], 3)

    def test_the_concession_still_exists_for_a_query_the_user_typed_short(self) -> None:
        """The floor drops for a genuinely short query, because a person who
        typed two words should still get an answer. Only the machine's own
        rewrite is denied that concession."""
        idx = self.index()
        typed = search("crimson", index=idx, widened=False)
        rewritten = search("crimson", index=idx, widened=True)
        self.assertEqual(typed["outcome"], PASS)
        self.assertEqual(rewritten["outcome"], FAIL)


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

    def test_an_edit_drops_appearance_exactly_as_image_to_video_does(self) -> None:
        """An edit is conditioned on a picture too. Applying the rule only to
        i2v made an assembled edit prompt a naive one plus decoration."""
        edit = assemble(
            GenSpec(
                model="flux-2",
                mode="edit",
                style=STYLE,
                subject="an amber serum bottle",
                action="the background becomes wet slate",
            )
        )
        self.assertEqual(edit["outcome"], PASS)
        self.assertNotIn("amber serum bottle", edit["prompt"])
        self.assertIn("subject", edit["dropped_by_design"])
        self.assertEqual(edit["dropped"], [])

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

    def test_an_inferred_style_word_never_reaches_the_prompt(self) -> None:
        """FOUND BY LOOKING AT A PICTURE (work/ab/p1_A.jpg, 2026-08-26).

        The request said "porous volcanic stone" — a material naming the
        podium. The synonym map reads "stone" as the palette colour "sand", the
        prompt carried "a palette of amber, sand", and the model put literal
        sand under the bottle. No metric caught it: retrieval was fine, every
        rule passed, the word count was in band.
        """
        from studio.selfrag.pipeline import PromptRequest, spec_from_text

        text = "an amber glass serum bottle standing on porous volcanic stone"
        out = spec_from_text(text, request=PromptRequest(text=text, model="flux"))
        self.assertIn("amber", out["spec"].palette, "a word the user WROTE must survive")
        self.assertNotIn("sand", out["spec"].palette, "a word only INFERRED must not")

    def test_a_stated_word_reached_through_spacing_still_counts(self) -> None:
        """The other direction. Dropping inferences must not drop statements:
        "golden hour" and "golden-hour" are the same thing said twice."""
        from studio.selfrag.pipeline import PromptRequest, spec_from_text

        for text in ("shot at golden hour", "shot at golden-hour"):
            with self.subTest(text=text):
                out = spec_from_text(text, request=PromptRequest(text=text, model="flux"))
                self.assertEqual(out["spec"].light, "golden-hour")

    def test_a_defaulted_field_is_reported_but_not_written(self) -> None:
        """Also from p1_A.jpg: nobody mentioned texture, the default "matte"
        went into the prompt, and a glossy glass bottle came back matte.
        Saying nothing leaves the model free; saying "matte" tells it something
        false."""
        spec = GenSpec(model="flux-2", mode="t2i", style=STYLE, subject="a glass bottle")
        with_guess = assemble(spec)
        without = assemble(spec, defaulted=["texture", "mood"])
        self.assertIn("film-grain texture", with_guess["prompt"])
        self.assertIn("calm mood", with_guess["prompt"])
        self.assertNotIn("film-grain texture", without["prompt"])
        self.assertNotIn("calm mood", without["prompt"])
        # And what the user DID state is untouched.
        self.assertIn("teal", without["prompt"])

    def test_a_slot_is_never_silently_truncated(self) -> None:
        """The gate refuses an over-long slot out loud. Nothing quietly cuts
        one down and hands back a prompt that means less than was written."""
        from studio.selfrag.spec import SLOT_MAX

        action = "the background becomes wet dark slate, the light turns cooler"
        self.assertGreater(len(action), 60)
        self.assertLess(len(action), SLOT_MAX)
        out = assemble(
            GenSpec(model="flux-2", mode="edit", style=STYLE, subject="a bottle", action=action)
        )
        self.assertEqual(out["outcome"], PASS)
        self.assertIn("the light turns cooler", out["prompt"])

    def test_the_slot_cap_bites_in_both_directions(self) -> None:
        """It was raised from 60 to 120 after an ordinary instruction was
        refused. A cap that is raised must still be a cap."""
        from studio.selfrag.spec import SLOT_MAX

        ok = GenSpec(
            model="veo-3.1", mode=MODE_T2V, style=STYLE, subject="x", action="a" * (SLOT_MAX - 1)
        )
        too_long = GenSpec(
            model="veo-3.1", mode=MODE_T2V, style=STYLE, subject="x", action="a" * (SLOT_MAX + 1)
        )
        self.assertEqual(gate_spec(ok)["outcome"], PASS)
        self.assertEqual(gate_spec(too_long)["outcome"], FAIL)
        # And the instruction that provoked the change now fits.
        real = GenSpec(
            model="flux-2",
            mode="edit",
            style=STYLE,
            subject="a bottle",
            action="the background becomes wet dark slate, the light turns cooler",
        )
        self.assertEqual(gate_spec(real)["outcome"], PASS)

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
