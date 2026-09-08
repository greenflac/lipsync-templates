"""The rewriter, and the one property it exists to have: it invents nothing.

Every test here can fail. The ones guarding a threshold move that threshold in
BOTH directions and assert the behaviour changes, because a threshold no test
can move is a threshold nobody is guarding — the module would keep passing with
the number set to anything.

No test opens a socket. `NoNetwork` enforces that rather than assuming it: the
model is always an injected callable, and the one test that would notice a
socket being opened installs a socket that raises.
"""

from __future__ import annotations

import socket
import unittest
from unittest import mock

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.corpus import CorpusRecord
from studio.selfrag.facts import Fact, FactStore
from studio.selfrag.fidelity import audit as fidelity_audit
from studio.selfrag.registry import ModelCard, card_for
from studio.selfrag.rewriter import (
    BOOSTERS,
    SOURCE_DETERMINISTIC,
    SOURCE_MODEL,
    SOURCE_MODEL_REJECTED,
    build_prompt,
    deterministic,
    expands_internally,
    rewrite,
)
import studio.selfrag.rewriter as rewriter


def _card(name: str) -> ModelCard:
    """The registry's card, or a loud failure. `card_for` returns None for a
    name nobody verified, and a test that silently ran against None would be
    testing the None branch while claiming to test the model."""
    card = card_for(name)
    if card is None:
        raise LookupError(f"{name} is not in the registry; this test cannot run")
    return card


FLUX = _card("flux-2")
VEO = _card("veo-3.1")
WAN = _card("wan-2.6-flash")
KLING = _card("kling-3.0")
RUNWAY = _card("runway-gen-4.5")

# The prompt that actually went to flux and lost, in the user's own words. It
# is already in flux-2's slot order, so the correct rewrite of it is itself.
GOOD = (
    "an amber glass serum bottle standing on porous volcanic stone, "
    "warm directional light, soft shadow, product photography"
)

# An intent whose obvious "improvement" is scene detail nobody asked for.
BAIT = "a bottle on a table"

# Long enough to exceed the shortening cap, and written as clauses a person
# would actually write. Both ends of the length range are covered: BAIT is the
# short end, GOOD the middle, this the long end (Т3).
LONG = (
    "a weathered fisherman mending a net on a wooden pier at dawn while the tide comes in, "
    "he turns slowly toward the horizon and lifts the net over his shoulder, "
    "the boats behind him rock gently against their moorings, "
    "cold grey daylight falls across the planks, "
    "the camera pans left along the pier and settles on his hands, "
    "documentary style"
)

ALL_INTENTS = (BAIT, GOOD, LONG)
ALL_CARDS = (FLUX, VEO, WAN, KLING, RUNWAY)


def _words(text: str) -> set[str]:
    """Lowercased word forms of a text, punctuation removed."""
    return {w.strip(".,;:!?()").lower() for w in str(text).split() if w.strip(".,;:!?()")}


def _new_words(prompt: str, intent: str) -> set[str]:
    """Words in `prompt` that are not in `intent`, verbatim.

    Stricter than `fidelity.audit`, which forgives craft vocabulary and vendor
    format. The deterministic path claims something stronger than the audit
    checks — that every character it emits came from the user — so the test of
    that claim has to be stronger than the audit too.
    """
    return _words(prompt) - _words(intent)


class TheHelperItselfCanFail(unittest.TestCase):
    """И5: the instrument gets a negative control before it is trusted.

    Without this, `_new_words` returning an empty set proves nothing — an
    always-empty helper would pass every invention test in this file.
    """

    def test_it_says_no_when_nothing_was_added(self) -> None:
        self.assertEqual(_new_words(GOOD, GOOD), set())

    def test_it_moves_when_something_was_added(self) -> None:
        self.assertEqual(_new_words(GOOD + ", swan, masterpiece", GOOD), {"swan", "masterpiece"})


class TheControlThatMattersMost(unittest.TestCase):
    def test_an_already_good_prompt_comes_back_unchanged(self) -> None:
        """If the agent cannot leave a good prompt alone, everything else it
        does is downside. GOOD is written in flux-2's own slot order, so
        reordering it into that order must be the identity."""
        out = rewrite(GOOD, card=FLUX)
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual(out["prompt"], GOOD)
        self.assertEqual(out["dropped"], [])
        self.assertEqual(out["source"], SOURCE_DETERMINISTIC)

    def test_it_does_not_take_the_invention_bait(self) -> None:
        out = rewrite(BAIT, card=FLUX)
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual(_new_words(out["prompt"], BAIT), set())
        for booster in BOOSTERS:
            self.assertNotIn(booster, out["prompt"].lower())


class DeterministicCannotInvent(unittest.TestCase):
    def test_no_card_and_no_intent_produces_a_word_the_user_did_not_write(self) -> None:
        """The by-construction claim, checked across every card and both ends
        of the length range."""
        for card in ALL_CARDS:
            for intent in ALL_INTENTS:
                with self.subTest(model=card.model_id, intent=intent[:20]):
                    out = rewrite(intent, card=card)
                    self.assertEqual(out["outcome"], PASS)
                    self.assertEqual(_new_words(out["prompt"], intent), set())
                    self.assertEqual(out["invented"], [])
                    self.assertEqual(fidelity_audit(out["prompt"], [intent])["outcome"], PASS)

    def test_every_dropped_clause_is_reported_and_absent(self) -> None:
        """A clause with nowhere to go must be named, not swallowed. flux-2 is
        an image model with no audio slot, so an audio clause has no home."""
        intent = "an amber bottle on volcanic stone, a low hum of music in the background sound"
        out = rewrite(intent, card=FLUX)
        self.assertIn("a low hum of music in the background sound", out["dropped"])
        self.assertNotIn("hum", out["prompt"])

    def test_a_clause_the_card_can_carry_is_not_dropped(self) -> None:
        """The negative control for the test above: the same clause against a
        card that HAS an audio slot must survive. Otherwise 'dropped' would be
        measuring the cue list, not the card."""
        intent = "an amber bottle on volcanic stone, a low hum of music in the background sound"
        out = rewrite(intent, card=VEO)
        self.assertEqual(out["dropped"], [])
        self.assertIn("hum", out["prompt"])

    def test_slot_order_is_the_cards_order_not_the_users(self) -> None:
        """Reordering is the whole permitted job, so it has to be visible.

        Both clauses here are classified — a light clause and a camera clause —
        and veo-3.1's skeleton puts camera (4th) before ambiance (7th), so the
        user's order has to lose."""
        out = rewrite("soft rim light, handheld medium shot", card=VEO)
        self.assertEqual(out["prompt"], "handheld medium shot, soft rim light")

    def test_an_unclassified_clause_stays_where_the_user_put_it(self) -> None:
        """The rule that makes 'leave a good prompt alone' the default rather
        than a case to detect. The cue lists recognise the first clause of a
        run and nothing after it, so an unclassified clause follows its
        neighbour instead of being sent to the front of the prompt."""
        intent = "handheld medium shot, a slow push in, a red kite over a beach"
        self.assertEqual(rewrite(intent, card=VEO)["prompt"], intent)

    def test_a_kling_camera_clause_survives_its_packed_style_slot(self) -> None:
        """kling-3.0's card packs camera, light and texture into one 'style'
        slot. Reading `slot_sources` is what keeps a camera clause out of
        `dropped` on that card — the same clause is dropped by a card whose
        skeleton has no camera anywhere."""
        intent = "a red kite over a beach, the camera pans left"
        self.assertEqual(rewrite(intent, card=KLING)["dropped"], [])


class ThreeOutcomes(unittest.TestCase):
    def test_an_empty_intent_is_could_not_measure_not_a_prompt(self) -> None:
        out = rewrite("", card=FLUX)
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIsNone(out["prompt"])

    def test_nonsense_punctuation_is_could_not_measure(self) -> None:
        out = rewrite("??? ...", card=FLUX)
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIsNone(out["prompt"])

    def test_unmeasured_never_reports_a_clean_check(self) -> None:
        """Р2: zero checks is not a pass, and the dict must say so."""
        out = rewrite("", card=FLUX)
        self.assertEqual(out["violations"], 0)
        self.assertGreaterEqual(out["unmeasured"], 1)

    def test_every_return_carries_every_key(self) -> None:
        keys = {
            "outcome",
            "checked",
            "violations",
            "unmeasured",
            "note",
            "prompt",
            "dropped",
            "invented",
            "source",
            "rounds",
        }
        for out in (
            rewrite("", card=FLUX),
            rewrite(GOOD, card=FLUX),
            rewrite(GOOD, card=FLUX, model=lambda _p: "a swan"),
            rewrite(GOOD, card=FLUX, model=lambda _p: GOOD),
        ):
            self.assertEqual(keys - set(out), set())


class TheModelPath(unittest.TestCase):
    def test_a_faithful_model_answer_is_accepted_on_the_first_round(self) -> None:
        out = rewrite(GOOD, card=FLUX, model=lambda _p: "warm directional light, an amber bottle")
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual(out["source"], SOURCE_MODEL)
        self.assertEqual(out["rounds"], 1)

    def test_an_inventing_model_is_told_which_words_and_retried(self) -> None:
        sent: list[str] = []

        def liar(prompt: str) -> str:
            sent.append(prompt)
            if len(sent) == 1:
                return GOOD + ", a swan drifting past a marble fountain"
            return GOOD

        out = rewrite(GOOD, card=FLUX, model=liar)
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual(out["rounds"], 2)
        self.assertEqual(out["source"], SOURCE_MODEL)
        # The correction is specific: the words themselves, not "be faithful".
        self.assertIn("swan", sent[1])
        self.assertIn("fountain", sent[1])
        self.assertNotIn("swan", sent[0])

    def test_a_model_that_keeps_inventing_is_rejected_and_the_user_still_gets_a_prompt(
        self,
    ) -> None:
        out = rewrite(GOOD, card=FLUX, model=lambda _p: "a swan on a marble fountain")
        self.assertEqual(out["outcome"], FAIL)
        self.assertEqual(out["source"], SOURCE_MODEL_REJECTED)
        self.assertEqual(out["rounds"], 2)  # literal, not MAX_ROUNDS: Т2
        self.assertEqual(out["prompt"], deterministic(GOOD, FLUX)["prompt"])
        self.assertIn("swan", out["invented"])

    def test_a_third_attempt_is_never_made(self) -> None:
        """The mutation MAX_ROUNDS 2 -> 3 survived the first version of this
        file: every test patched the constant, so nothing observed its actual
        value and the module would have paid for a third round unnoticed. This
        model would come good on round three, and must never be asked."""
        state = {"n": 0}

        def stubborn(_prompt: str) -> str:
            state["n"] += 1
            return GOOD if state["n"] > 2 else GOOD + ", a swan"

        out = rewrite(GOOD, card=FLUX, model=stubborn)
        self.assertEqual(out["outcome"], FAIL)
        self.assertEqual(state["n"], 2)
        self.assertEqual(out["source"], SOURCE_MODEL_REJECTED)

    def test_a_silent_model_is_could_not_measure_not_a_failure(self) -> None:
        out = rewrite(GOOD, card=FLUX, model=lambda _p: "   ")
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertEqual(out["prompt"], deterministic(GOOD, FLUX)["prompt"])
        self.assertEqual(out["violations"], 0)

    def test_a_model_that_raises_is_could_not_measure(self) -> None:
        def broken(_prompt: str) -> str:
            raise TimeoutError("the vendor did not answer")

        out = rewrite(GOOD, card=FLUX, model=broken)
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIn("TimeoutError", out["note"])
        self.assertEqual(out["prompt"], deterministic(GOOD, FLUX)["prompt"])

    def test_no_model_argument_means_no_round_was_run(self) -> None:
        """`rounds` is the record of what was spent. Zero is the only honest
        value when nothing was called, and it is asserted rather than assumed
        because a non-zero default here would report a paid call that never
        happened."""
        out = rewrite(GOOD, card=FLUX)
        self.assertEqual(out["rounds"], 0)
        self.assertEqual(out["source"], SOURCE_DETERMINISTIC)


class ExamplesAreFormNotContent(unittest.TestCase):
    EXAMPLES = (
        CorpusRecord(
            record_id="e1",
            prompt="a brass pocket watch on slate, rim light, editorial still life",
            model="flux-2",
            rating=9,
        ),
    )

    def test_the_system_instruction_states_the_rule_and_names_the_boosters(self) -> None:
        text = build_prompt(GOOD, FLUX, self.EXAMPLES)
        self.assertIn("INVENT NOTHING", text)
        for booster in BOOSTERS:
            self.assertIn(booster, text)
        self.assertIn("FORM EXAMPLE", text)
        self.assertIn(GOOD, text)

    def test_a_word_borrowed_from_an_example_is_caught_as_invention(self) -> None:
        """The point of auditing against the intent ALONE. A precedent is not
        a licence to put a brass pocket watch in the user's picture."""
        out = rewrite(
            GOOD,
            card=FLUX,
            examples=self.EXAMPLES,
            model=lambda _p: GOOD + ", a brass pocket watch",
        )
        self.assertEqual(out["outcome"], FAIL)
        self.assertIn("brass", out["invented"])

    def test_the_correction_round_is_only_added_after_a_rejection(self) -> None:
        first = build_prompt(GOOD, FLUX, self.EXAMPLES)
        second = build_prompt(GOOD, FLUX, self.EXAMPLES, invented_words=["swan"])
        self.assertNotIn("REJECTED", first)
        self.assertIn("REJECTED", second)


class Shortening(unittest.TestCase):
    def test_a_model_that_expands_internally_is_handed_less(self) -> None:
        """wan-2.6-flash's own prompt_extend.py rewrites to 80-100 words; the
        vendor fact is the only first-hand one in the fact base."""
        self.assertTrue(expands_internally("wan-2.6-flash"))
        out = rewrite(LONG, card=WAN)
        self.assertLessEqual(len(out["prompt"].split()), 40)  # literal: Т2
        self.assertLess(len(out["prompt"].split()), len(LONG.split()))
        self.assertTrue(out["dropped"])

    def test_a_model_with_no_such_fact_keeps_the_users_words(self) -> None:
        """The negative control. Without it, 'shortened' could be measuring
        nothing but the length of the intent."""
        self.assertFalse(expands_internally("flux-2"))
        self.assertGreater(len(rewrite(LONG, card=KLING)["prompt"].split()), 40)

    def test_a_blog_only_claim_does_not_authorise_dropping_words(self) -> None:
        store = FactStore(
            [
                Fact(
                    model="rumour-1",
                    attribute="expands_internally",
                    value="yes, so they say",
                    source_url="https://example.invalid/post",
                    tier="blog",
                    stated_on="2026-08-26",
                )
            ]
        )
        self.assertFalse(expands_internally("rumour-1", store=store))

    def test_a_vendor_claim_does(self) -> None:
        store = FactStore(
            [
                Fact(
                    model="rumour-1",
                    attribute="expands_internally",
                    value="yes, behind a flag",
                    source_url="https://example.invalid/repo",
                    tier="vendor",
                    stated_on="2026-08-26",
                )
            ]
        )
        self.assertTrue(expands_internally("rumour-1", store=store))


# A request in the voice people actually use: mostly apology, with the subject
# and the one thing they care about buried in the middle. wan-2.6-flash is the
# model whose card says it expands the prompt itself, so this is the case where
# the rewriter has to cut — and what it cuts is the whole question.
RAMBLE = (
    "i will be honest i am not good at this, "
    "what i want is basically a slow pan across a workbench that has been used a lot, "
    "you can see the marks in the wood, "
    "and there is a single lamp on, "
    "that is really all i want"
)


class ShorteningCutsTheApologyNotTheLamp(unittest.TestCase):
    """The defect this ranking was written after, kept as a test.

    OBSERVED: cutting clauses off the END of the prompt kept "i will be honest
    i am not good at this" and cut "and there is a single lamp on". The user's
    subject was being spent to preserve their apology.
    """

    def test_the_subject_survives_and_the_apology_does_not(self) -> None:
        out = rewrite(RAMBLE, card=WAN)
        self.assertEqual(out["outcome"], PASS)
        self.assertIn("lamp", out["prompt"])
        self.assertIn("workbench", out["prompt"])
        self.assertNotIn("i am not good at this", out["prompt"])
        self.assertLessEqual(len(out["prompt"].split()), 40)  # literal: Т2

    def test_what_was_cut_is_named(self) -> None:
        """A clause that vanished silently is the failure `dropped` exists for."""
        out = rewrite(RAMBLE, card=WAN)
        self.assertTrue(out["dropped"])
        for clause in out["dropped"]:
            self.assertIn(clause, RAMBLE)

    def test_density_not_count_decides(self) -> None:
        """A long clause of mostly filler must lose to a short clause of pure
        subject, however many scene words the long one accumulates."""
        self.assertGreater(
            rewriter._scene_share("it is stainless steel"),
            rewriter._scene_share(
                "and i would love it if we could just see the shot pouring into the cup"
            ),
        )


class UnreadableIntent(unittest.TestCase):
    def test_nonsense_words_are_could_not_measure_not_a_prompt(self) -> None:
        out = rewrite("asdkjhasd qwoieu zxcmnv", card=KLING)
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIsNone(out["prompt"])

    def test_ordinary_english_is_not_mistaken_for_nonsense(self) -> None:
        """The negative control. A gate that refuses everything measures
        nothing, and 'strengths' and 'rhythms' are the kind of real word that
        trips a consonant-run rule."""
        for intent in (GOOD, BAIT, LONG, "a drummer, strong rhythms, tight framing"):
            with self.subTest(intent=intent[:24]):
                self.assertEqual(rewrite(intent, card=VEO)["outcome"], PASS)


class ThresholdsAreGuarded(unittest.TestCase):
    """Т1: each threshold is moved in BOTH directions and the behaviour has to
    change. A constant no test can move is a constant nobody is guarding."""

    def test_max_rounds_decides_whether_a_second_attempt_happens(self) -> None:
        def invents_once() -> object:
            state = {"n": 0}

            def model(_prompt: str) -> str:
                state["n"] += 1
                return GOOD if state["n"] > 1 else GOOD + ", a swan"

            return model

        with mock.patch.object(rewriter, "MAX_ROUNDS", 1):
            tight = rewrite(GOOD, card=FLUX, model=invents_once())  # type: ignore[arg-type]
        self.assertEqual(tight["outcome"], FAIL)
        self.assertEqual(tight["source"], SOURCE_MODEL_REJECTED)
        self.assertEqual(tight["rounds"], 1)

        with mock.patch.object(rewriter, "MAX_ROUNDS", 2):
            asis = rewrite(GOOD, card=FLUX, model=invents_once())  # type: ignore[arg-type]
        self.assertEqual(asis["outcome"], PASS)
        self.assertEqual(asis["rounds"], 2)

        def invents_twice() -> object:
            state = {"n": 0}

            def model(_prompt: str) -> str:
                state["n"] += 1
                return GOOD if state["n"] > 2 else GOOD + ", a swan"

            return model

        with mock.patch.object(rewriter, "MAX_ROUNDS", 2):
            two = rewrite(GOOD, card=FLUX, model=invents_twice())  # type: ignore[arg-type]
        self.assertEqual(two["outcome"], FAIL)
        with mock.patch.object(rewriter, "MAX_ROUNDS", 3):
            three = rewrite(GOOD, card=FLUX, model=invents_twice())  # type: ignore[arg-type]
        self.assertEqual(three["outcome"], PASS)
        self.assertEqual(three["rounds"], 3)

    def test_shorten_max_words_decides_how_much_is_cut(self) -> None:
        baseline = len(rewrite(LONG, card=WAN)["prompt"].split())

        with mock.patch.object(rewriter, "SHORTEN_MAX_WORDS", 500):
            loose = rewrite(LONG, card=WAN)
        self.assertEqual(loose["dropped"], [])
        self.assertGreater(len(loose["prompt"].split()), baseline)

        with mock.patch.object(rewriter, "SHORTEN_MAX_WORDS", 10):
            tight = rewrite(LONG, card=WAN)
        self.assertLess(len(tight["prompt"].split()), baseline)
        self.assertGreater(len(tight["dropped"]), 0)

    def test_min_intent_content_words_decides_what_is_refusable(self) -> None:
        one_word = "bottle"
        two_words = "amber bottle"
        self.assertEqual(rewrite(one_word, card=FLUX)["outcome"], UNMEASURED)
        self.assertEqual(rewrite(two_words, card=FLUX)["outcome"], PASS)

        with mock.patch.object(rewriter, "MIN_INTENT_CONTENT_WORDS", 1):
            self.assertEqual(rewrite(one_word, card=FLUX)["outcome"], PASS)
        with mock.patch.object(rewriter, "MIN_INTENT_CONTENT_WORDS", 3):
            self.assertEqual(rewrite(two_words, card=FLUX)["outcome"], UNMEASURED)

    def test_cue_share_decides_what_is_filed_by_its_cue(self) -> None:
        """The clause that named the defect: 'matte' is one word inside a
        clause whose subject is a speaker, and veo-3.1 has no texture slot, so
        filing it by that one cue drops the user's subject."""
        subject = "a matte black bluetooth speaker on a desk"
        intent = f"{subject}, soft window light"

        # As it stands: one texture cue in five content words is a mention, the
        # clause is the subject, and it keeps its place at the front.
        self.assertIsNone(rewriter._category(subject))
        self.assertEqual(rewrite(intent, card=FLUX)["prompt"], intent)

        # Loosened: the same clause is read as a texture clause and flux-2's
        # texture slot comes after its lighting slot, so the user's subject is
        # shuffled behind the light.
        with mock.patch.object(rewriter, "CUE_SHARE", 0.05):
            self.assertEqual(rewriter._category(subject), "texture")
            self.assertEqual(rewrite(intent, card=FLUX)["prompt"], f"soft window light, {subject}")

        with mock.patch.object(rewriter, "CUE_SHARE", 1.01):
            # Nothing can clear a share above 1, so nothing is filed by cue and
            # every clause simply keeps its place.
            self.assertEqual(rewriter._category("handheld medium shot"), None)
            self.assertEqual(
                rewrite("soft rim light, handheld medium shot", card=VEO)["prompt"],
                "soft rim light, handheld medium shot",
            )

    def test_gibberish_share_decides_what_is_unreadable(self) -> None:
        mostly = "asdkjhasd zxcmnv on a table"  # 2 of 4 content words unreadable
        self.assertEqual(rewrite(mostly, card=FLUX)["outcome"], UNMEASURED)

        with mock.patch.object(rewriter, "GIBBERISH_SHARE", 0.9):
            self.assertEqual(rewrite(mostly, card=FLUX)["outcome"], PASS)
        with mock.patch.object(rewriter, "GIBBERISH_SHARE", 0.1):
            self.assertEqual(rewrite(GOOD, card=FLUX)["outcome"], PASS)
            self.assertEqual(rewrite("a zxcmnv bottle on stone", card=FLUX)["outcome"], UNMEASURED)


class NoNetwork(unittest.TestCase):
    """Т4: enforced by the runner, not by agreement between authors."""

    def test_neither_path_opens_a_socket(self) -> None:
        def forbidden(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("a test opened a socket")

        with mock.patch.object(socket, "socket", forbidden):
            self.assertEqual(rewrite(GOOD, card=FLUX)["outcome"], PASS)
            self.assertEqual(rewrite(GOOD, card=FLUX, model=lambda _p: GOOD)["outcome"], PASS)


if __name__ == "__main__":
    unittest.main()
