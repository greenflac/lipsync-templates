"""Tests for studio.template_lint: it must catch damage AND stay quiet otherwise.

Two halves, and the second is the one that makes the tool usable:

* a planted defect per check, which the linter must find;
* a NEGATIVE CONTROL per check — a base that ALREADY has the defect, where no
  value makes it worse and the linter must say nothing at all (harness rule
  И5). A linter with no negative control is an instrument that has never been
  shown to be capable of silence, and the measurement behind this whole module
  is 34 raw repetitions on the shipped catalogue against 2 real ones.

Every constant that decides a verdict is mutated in BOTH directions by the
session that wrote this file, and the mutation log is in the handoff (Т1). The
tests named `..._is_the_upper_mutation_guard` / `..._is_the_lower_mutation_guard`
are the ones that go red for a given direction; they are named so the next
person can mutate without re-deriving which test to watch.

The network is closed by the runner below, not by a convention (Т4).
"""

from __future__ import annotations

import doctest
import socket
import unittest

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio import template_lint as tl
from studio.prompt_templates import CATALOGUE, Element, PromptTemplate, element, get
from studio.selfrag.reflect import SEVERITY_RISK, SEVERITY_VIOLATION
from studio.template_lint import (
    CHECK_ARTICLE,
    CHECK_CROSS_ELEMENT,
    CHECK_DUPLICATE_VALUE,
    CHECK_IDENTITY_ONLY,
    CHECK_REPETITION,
    CHECK_SEAM,
    Finding,
    lint,
    lint_catalogue,
    main,
)

_REAL_SOCKET = socket.socket
_REAL_CONNECT = socket.create_connection


class NetworkTouched(AssertionError):
    """Raised when a test reaches for a socket. This module must never need one."""


def setUpModule() -> None:
    def _blocked(*args: object, **kwargs: object) -> None:
        raise NetworkTouched("a test tried to open a socket")

    socket.socket = _blocked  # type: ignore[assignment, misc]
    socket.create_connection = _blocked  # type: ignore[assignment]


def tearDownModule() -> None:
    socket.socket = _REAL_SOCKET  # type: ignore[misc]
    socket.create_connection = _REAL_CONNECT


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, ignore: object):
    """Run the module's docstring examples. An example nobody runs rots into a lie."""
    tests.addTests(doctest.DocTestSuite(tl))
    return tests


class Doctests(unittest.TestCase):
    """The doctests again, as an ordinary test, and this is not belt-and-braces.

    `load_tests` is a unittest protocol and **pytest does not honour it**. The
    suite is run both ways here, so under pytest the docstring examples went
    unexecuted — OBSERVED 2026-08-26, when `lint`'s example claimed 25
    combinations for `winter_jacket_moonlight` and the real number is 24. It
    was green under `pytest -q` and red under `python -m unittest` for as long
    as it existed. A test nobody runs is not a passing test (harness rule Т6).
    """

    def test_the_docstring_examples_all_run_and_pass(self) -> None:
        results = doctest.testmod(tl, verbose=False)
        self.assertEqual(results.failed, 0)
        self.assertGreaterEqual(results.attempted, 4)


# --------------------------------------------------------------------------
# Helpers. Expected values below are LITERALS, never imported from the module
# under test (Т2) — an expectation that moves with the code proves nothing.
# --------------------------------------------------------------------------


def checks(report: dict) -> list[str]:
    """The check name of every finding, in report order."""
    return [f.check for f in report["findings"]]


def findings_for(report: dict, value: str) -> list[Finding]:
    return [f for f in report["findings"] if f.value == value]


# --------------------------------------------------------------------------
# THE NEGATIVE CONTROL. The base repeats "bright" and "brass" inside the
# window; no value on the allow-list adds a repetition. The linter must be
# silent — this is the 10-lies-in-12 case from `studio/LINTER_CONTRACT.md`.
# --------------------------------------------------------------------------

BASE_ALREADY_REPEATS = "a bright brass lamp beside a bright brass door, seen from above"
ALREADY_REPEATS = PromptTemplate(
    id="base_already_repeats",
    prompt=BASE_ALREADY_REPEATS,
    model="none",
    elements=(
        element(
            BASE_ALREADY_REPEATS,
            "subject",
            "What stands there",
            "lamp",
            ("stool", "kettle"),
        ),
    ),
)


class NegativeControl(unittest.TestCase):
    """Silence is a capability, and it has to be demonstrated, not assumed."""

    def test_the_base_really_does_repeat_a_word(self) -> None:
        """Without this, silence below would only prove the detector is blind (И5)."""
        signals = tl._detect_repetition(BASE_ALREADY_REPEATS, ())
        self.assertIn(("repetition", "bright"), signals)
        self.assertIn(("repetition", "brass"), signals)

    def test_a_base_that_already_repeats_produces_no_findings(self) -> None:
        report = lint(ALREADY_REPEATS)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["outcome"], PASS)
        self.assertEqual(report["combinations"], 3)

    def test_every_value_still_contains_the_repeated_words(self) -> None:
        """Proof the words did not simply leave: the calibrated prompts still have them."""
        from studio.prompt_templates import calibrate

        for value in ("stool", "kettle"):
            out = calibrate(ALREADY_REPEATS, {"subject": value})["prompt"]
            self.assertEqual(out.count("bright"), 2, out)
            self.assertIn(("repetition", "bright"), tl._detect_repetition(out, ()))


# --------------------------------------------------------------------------
# 1. repetition
# --------------------------------------------------------------------------

WINTER_BASE = "a tailored deep burgundy jacket, folded once and left on a bench"
REPETITION_PLANTED = PromptTemplate(
    id="repetition_planted",
    prompt=WINTER_BASE,
    model="none",
    elements=(
        element(
            WINTER_BASE,
            "subject",
            "What is on the bench",
            "deep burgundy jacket",
            ("folded ivory linen suit", "worn leather satchel"),
        ),
    ),
)

# The 4-letter word is on purpose: it is the guard on
# REPETITION_MIN_WORD_LETTERS. "moon" repeats at distance 3.
SHORT_WORD_BASE = "a pale moon over a still lake"
SHORT_WORD_PLANTED = PromptTemplate(
    id="short_word_planted",
    prompt=SHORT_WORD_BASE,
    model="none",
    elements=(
        element(SHORT_WORD_BASE, "surface", "The water", "still lake", ("moon pool", "salt flat")),
    ),
)


class Repetition(unittest.TestCase):
    def test_the_motivating_defect_is_caught(self) -> None:
        """The exact case from LINTER_CONTRACT.md, four words apart."""
        report = lint(REPETITION_PLANTED)
        self.assertEqual(report["outcome"], FAIL)
        bad = findings_for(report, "folded ivory linen suit")
        self.assertEqual([f.check for f in bad], [CHECK_REPETITION])
        self.assertEqual(bad[0].severity, SEVERITY_VIOLATION)
        self.assertEqual(bad[0].element, "subject")
        self.assertIn("'folded'", bad[0].message)

    def test_the_window_reaches_seven_words_is_the_lower_mutation_guard(self) -> None:
        """Two real defects, at 4 and at 7 words apart. Narrowing the window kills these.

        The 4-apart one is the motivating defect (a window of 3 MISSED it,
        OBSERVED 2026-08-26). The 7-apart one came from agent B's control set,
        written without sight of the linter, and it is why the window is 8 and
        not 5: a window tuned to exactly one known defect is fitted to its own
        example (И1).
        """
        four_apart = "a tailored folded ivory linen suit, folded once and left on a bench"
        seven_apart = "a folded paper lantern set down on a folded linen cloth, soft north light"
        self.assertIn(("repetition", "folded"), tl._detect_repetition(four_apart, ()))
        self.assertIn(("repetition", "folded"), tl._detect_repetition(seven_apart, ()))

    def test_an_echo_thirteen_words_apart_is_not_reported(self) -> None:
        """The upper mutation guard: widening the window past ~8 starts inventing.

        The shipped catalogue offers "a pale grey cashmere scarf shaped like a
        full moon" against a base that ends "under a full moon". That reads as
        an echo across a whole sentence, not as damage, and the author put it
        on the list on purpose.
        """
        report = lint(get("winter_jacket_moonlight"))
        repeats = [f for f in report["findings"] if f.check == CHECK_REPETITION]
        self.assertEqual([f.value for f in repeats], ["folded ivory linen suit"])

    def test_a_four_letter_word_still_counts(self) -> None:
        """Guards REPETITION_MIN_WORD_LETTERS from being raised."""
        report = lint(SHORT_WORD_PLANTED)
        bad = findings_for(report, "moon pool")
        self.assertEqual([f.check for f in bad], [CHECK_REPETITION])

    def test_a_two_letter_token_is_not_a_repetition(self) -> None:
        """The lower guard on REPETITION_MIN_WORD_LETTERS: "50mm" and "35mm" share "mm"."""
        base = "a small lamp on a 50mm mount"
        template = PromptTemplate(
            id="short_token_clean",
            prompt=base,
            model="none",
            elements=(element(base, "subject", "Lamp", "small lamp", ("35mm lamp", "brass lamp")),),
        )
        self.assertEqual(lint(template)["findings"], [])

    def test_stop_words_do_not_hide_a_content_word(self) -> None:
        """The stop list must stay a list of function words, not of nouns."""
        for word in ("folded", "raking", "moon", "linen", "bright", "lighting", "brass"):
            self.assertNotIn(word, tl.REPETITION_STOP_WORDS)
        self.assertLessEqual(len(tl.REPETITION_STOP_WORDS), 40)


# --------------------------------------------------------------------------
# 2. article
# --------------------------------------------------------------------------

A_BASE = "a folded linen napkin on a plain table"
ARTICLE_A_PLANTED = PromptTemplate(
    id="article_a_planted",
    prompt=A_BASE,
    model="none",
    elements=(
        element(A_BASE, "material", "Fabric", "folded linen", ("ivory silk", "brushed cotton")),
    ),
)

AN_BASE = "an ivory silk napkin on a plain table"
ARTICLE_AN_PLANTED = PromptTemplate(
    id="article_an_planted",
    prompt=AN_BASE,
    model="none",
    elements=(
        element(AN_BASE, "material", "Fabric", "ivory silk", ("folded linen", "oak-brown wool")),
    ),
)

# NEGATIVE CONTROL for the article check: the base is already wrong, and the
# element being calibrated is nowhere near it.
ARTICLE_BASE_ALREADY_WRONG = "a ivory silk napkin on a plain table"
ARTICLE_ALREADY_WRONG = PromptTemplate(
    id="article_already_wrong",
    prompt=ARTICLE_BASE_ALREADY_WRONG,
    model="none",
    elements=(
        element(
            ARTICLE_BASE_ALREADY_WRONG,
            "surface",
            "Table",
            "plain table",
            ("pine table", "steel bench"),
        ),
    ),
)


class Article(unittest.TestCase):
    def test_a_before_a_vowel_is_a_violation(self) -> None:
        report = lint(ARTICLE_A_PLANTED)
        self.assertEqual(report["outcome"], FAIL)
        bad = findings_for(report, "ivory silk")
        self.assertEqual([f.check for f in bad], [CHECK_ARTICLE])
        self.assertIn("'ivory'", bad[0].message)

    def test_an_before_a_consonant_is_a_violation(self) -> None:
        report = lint(ARTICLE_AN_PLANTED)
        self.assertEqual(report["outcome"], FAIL)
        self.assertEqual([f.check for f in findings_for(report, "folded linen")], [CHECK_ARTICLE])

    def test_a_correct_article_is_silent(self) -> None:
        self.assertEqual(findings_for(lint(ARTICLE_A_PLANTED), "brushed cotton"), [])
        self.assertEqual(findings_for(lint(ARTICLE_AN_PLANTED), "oak-brown wool"), [])

    def test_a_base_whose_article_is_already_wrong_is_not_blamed_on_a_value(self) -> None:
        """NEGATIVE CONTROL: the defect is the author's, not the substitution's."""
        report = lint(ARTICLE_ALREADY_WRONG)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["outcome"], PASS)

    def test_a_value_starting_one_piece_is_correct_english(self) -> None:
        """The stricter mutation guard on ARTICLE_TAKES_A_DESPITE_VOWEL.

        "one" is spelled with a vowel and said with a consonant, so "a
        one-piece steel lamp" is right. The value must INTRODUCE the article
        pairing: an earlier version of this test put "a one-piece" in the BASE,
        where the subtraction hid it, and the mutation run showed the test was a
        decoration (OBSERVED 2026-08-26 — removing "one" from the exception list
        turned nothing red, and the exception list was in fact never reached by
        a hyphenated word at all).
        """
        base = "a plain brass lamp beside the door"
        template = PromptTemplate(
            id="article_exception_clean",
            prompt=base,
            model="none",
            elements=(
                element(base, "subject", "Lamp", "plain brass lamp", ("one-piece steel lamp",)),
            ),
        )
        self.assertEqual(lint(template)["findings"], [])

    def test_a_value_starting_with_an_acronym_is_skipped_rather_than_guessed(self) -> None:
        """ "a USB hub" is right because USB is said letter by letter.

        Guards ARTICLE_ACRONYM_MIN_LETTERS from being raised past three. Same
        history as the test above: with the pairing in the base it was silent
        under every mutation.
        """
        base = "a plain brass lamp beside the door"
        template = PromptTemplate(
            id="article_acronym_clean",
            prompt=base,
            model="none",
            elements=(element(base, "subject", "Lamp", "plain brass lamp", ("USB hub",)),),
        )
        self.assertEqual(lint(template)["findings"], [])


# --------------------------------------------------------------------------
# 3. seam
# --------------------------------------------------------------------------

SEAM_COMMA_BASE = "a lamp, bright and warm, on a table"
SEAM_COMMA_PLANTED = PromptTemplate(
    id="seam_comma_planted",
    prompt=SEAM_COMMA_BASE,
    model="none",
    elements=(
        element(SEAM_COMMA_BASE, "mood", "Mood", "bright and warm", ("warm,", "cool and blue")),
    ),
)

SEAM_SPACE_BASE = "a red lamp on a table"
SEAM_SPACE_PLANTED = PromptTemplate(
    id="seam_space_planted",
    prompt=SEAM_SPACE_BASE,
    model="none",
    elements=(element(SEAM_SPACE_BASE, "colour", "Colour", "red", (" blue", "green")),),
)

# The span deliberately swallows the leading space, so a value without one
# welds itself to the previous word: "a tailoredcoat on a bench".
SEAM_EDGE_BASE = "a tailored jacket on a bench"
SEAM_EDGE_PLANTED = PromptTemplate(
    id="seam_edge_planted",
    prompt=SEAM_EDGE_BASE,
    model="none",
    elements=(element(SEAM_EDGE_BASE, "subject", "Garment", " jacket", ("coat", " long coat")),),
)

# NEGATIVE CONTROL for seam: the base already has a doubled space, elsewhere.
SEAM_BASE_ALREADY_DOUBLED = "a red  lamp on a plain table"
SEAM_ALREADY_DOUBLED = PromptTemplate(
    id="seam_already_doubled",
    prompt=SEAM_BASE_ALREADY_DOUBLED,
    model="none",
    elements=(
        element(SEAM_BASE_ALREADY_DOUBLED, "surface", "Table", "plain table", ("pine table",)),
    ),
)


class Seam(unittest.TestCase):
    def test_a_value_ending_in_a_comma_doubles_the_comma(self) -> None:
        report = lint(SEAM_COMMA_PLANTED)
        self.assertEqual(report["outcome"], FAIL)
        bad = findings_for(report, "warm,")
        self.assertIn(CHECK_SEAM, [f.check for f in bad])
        self.assertIn("doubled comma", " ".join(f.message for f in bad))

    def test_a_value_with_a_leading_space_doubles_the_space(self) -> None:
        report = lint(SEAM_SPACE_PLANTED)
        bad = findings_for(report, " blue")
        self.assertEqual([f.check for f in bad], [CHECK_SEAM])
        self.assertIn("doubled space", bad[0].message)

    def test_a_span_that_swallowed_its_separator_welds_two_words(self) -> None:
        report = lint(SEAM_EDGE_PLANTED)
        bad = findings_for(report, "coat")
        self.assertEqual([f.check for f in bad], [CHECK_SEAM])
        self.assertIn("missing separator", bad[0].message)
        self.assertIn("subject", bad[0].message)

    def test_the_same_span_with_a_well_formed_value_is_silent(self) -> None:
        """The span is odd, but " long coat" fits it: no value, no finding."""
        self.assertEqual(findings_for(lint(SEAM_EDGE_PLANTED), " long coat"), [])

    def test_a_base_that_already_has_a_doubled_space_is_not_blamed_on_a_value(self) -> None:
        """NEGATIVE CONTROL for seam."""
        report = lint(SEAM_ALREADY_DOUBLED)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["outcome"], PASS)

    def test_a_single_space_is_never_a_seam_is_the_stricter_mutation_guard(self) -> None:
        self.assertEqual(tl._detect_seam("a red lamp on a table", ()), set())


# --------------------------------------------------------------------------
# 4. duplicate_value and 5. identity_only — declaration checks, both RISK.
# The spans here are literal so the fixture does not depend on the code that
# computes spans (Т2); `test_the_literal_spans_are_what_they_claim` proves them.
# --------------------------------------------------------------------------

DECLARATION_BASE = "a red bench under a full moon"
DUPLICATE_VALUE = PromptTemplate(
    id="duplicate_value_planted",
    prompt=DECLARATION_BASE,
    model="none",
    elements=(
        Element("surface", "Surface", (0, 11), ("a red bench", "a stone ledge", "a red bench")),
    ),
)
IDENTITY_ONLY = PromptTemplate(
    id="identity_only_planted",
    prompt=DECLARATION_BASE,
    model="none",
    elements=(Element("light", "Light", (18, 29), ("a full moon",)),),
)
TWO_VALUES_CLEAN = PromptTemplate(
    id="two_values_clean",
    prompt=DECLARATION_BASE,
    model="none",
    elements=(Element("light", "Light", (18, 29), ("a full moon", "a street lamp")),),
)


class Declaration(unittest.TestCase):
    def test_the_literal_spans_are_what_they_claim(self) -> None:
        self.assertEqual(DECLARATION_BASE[0:11], "a red bench")
        self.assertEqual(DECLARATION_BASE[18:29], "a full moon")

    def test_a_value_listed_twice_is_a_risk(self) -> None:
        report = lint(DUPLICATE_VALUE)
        bad = [f for f in report["findings"] if f.check == CHECK_DUPLICATE_VALUE]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0].severity, SEVERITY_RISK)
        self.assertEqual(bad[0].value, "a red bench")

    def test_a_risk_does_not_turn_a_pass_into_a_fail(self) -> None:
        report = lint(DUPLICATE_VALUE)
        self.assertEqual(report["outcome"], PASS)
        self.assertEqual(report["violations"], 0)
        self.assertEqual(report["risks"], 1)

    def test_a_single_allowed_value_is_a_risk(self) -> None:
        report = lint(IDENTITY_ONLY)
        self.assertEqual([f.check for f in report["findings"]], [CHECK_IDENTITY_ONLY])
        self.assertEqual(report["findings"][0].severity, SEVERITY_RISK)
        self.assertEqual(report["outcome"], PASS)

    def test_two_allowed_values_are_not_identity_only(self) -> None:
        """The stricter mutation guard: `<= 2` must not be allowed to creep in."""
        self.assertEqual(lint(TWO_VALUES_CLEAN)["findings"], [])

    def test_distinct_values_are_not_duplicates(self) -> None:
        """The other stricter guard: flagging every value must go red here."""
        self.assertEqual(checks(lint(TWO_VALUES_CLEAN)), [])


# --------------------------------------------------------------------------
# 6. cross_element — legal, handled correctly by the substituter, still worth
# telling the author about. RISK.
# --------------------------------------------------------------------------

CROSS_BASE = "a red bench in the corner of a bare studio, lit from the side by a full moon"
CROSS_PLANTED = PromptTemplate(
    id="cross_element_planted",
    prompt=CROSS_BASE,
    model="none",
    elements=(
        element(
            CROSS_BASE,
            "surface",
            "Surface",
            "a red bench",
            ("a scarf shaped like a full moon", "a stone ledge"),
        ),
        element(CROSS_BASE, "light", "Light", "a full moon", ("a street lamp",)),
    ),
)

# The clean counterpart, and the guard on CROSS_ELEMENT_MIN_CHARS: "ruby"
# contains "by", which is another element's whole base text. Four characters
# keeps that quiet; two would not.
SHORT_BASE_TEXT = "a brass bowl by pale oak, lit softly"
SHORT_BASE_CLEAN = PromptTemplate(
    id="short_base_text_clean",
    prompt=SHORT_BASE_TEXT,
    model="none",
    elements=(
        element(SHORT_BASE_TEXT, "subject", "Bowl", "brass bowl", ("ruby bowl", "steel bowl")),
        element(SHORT_BASE_TEXT, "relation", "Where", "by", ("near",)),
    ),
)


class CrossElement(unittest.TestCase):
    def test_a_value_carrying_another_elements_text_is_a_risk_not_a_violation(self) -> None:
        report = lint(CROSS_PLANTED)
        bad = [f for f in report["findings"] if f.check == CHECK_CROSS_ELEMENT]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0].severity, SEVERITY_RISK)
        self.assertEqual(bad[0].element, "surface")
        self.assertEqual(bad[0].value, "a scarf shaped like a full moon")
        self.assertIn("'light'", bad[0].message)

    def test_it_does_not_change_the_verdict(self) -> None:
        self.assertEqual(lint(CROSS_PLANTED)["outcome"], PASS)

    def test_the_shipped_catalogue_trap_is_reported(self) -> None:
        """The real one: the scarf that contains the moon (prompt_templates.py)."""
        report = lint(get("winter_jacket_moonlight"))
        bad = [f for f in report["findings"] if f.check == CHECK_CROSS_ELEMENT]
        self.assertEqual(
            [f.value for f in bad], ["pale grey cashmere scarf shaped like a full moon"]
        )

    def test_a_three_letter_base_text_is_below_the_floor(self) -> None:
        """Lowering CROSS_ELEMENT_MIN_CHARS turns "ruby" into an accusation."""
        self.assertEqual(lint(SHORT_BASE_CLEAN)["findings"], [])

    def test_keeping_the_base_value_introduces_nothing(self) -> None:
        """The subtraction for this check: the identity value changes no text."""
        self.assertEqual(findings_for(lint(CROSS_PLANTED), "a red bench"), [])


# --------------------------------------------------------------------------
# Clean templates. The half everybody forgets.
# --------------------------------------------------------------------------

CLEAN_ONE = "a stone bowl set on pale oak, lit softly from the left"
CLEAN_TWO = "product photo of a copper kettle in a bare studio, warm rim lighting"
CLEAN_THREE = "close-up of a woven basket against a deep green backdrop, fine grain"
CLEAN_FOUR = "a slate tile beneath a low winter sun, long shadows across the floor"

CLEAN_TEMPLATES = (
    PromptTemplate(
        id="clean_one",
        prompt=CLEAN_ONE,
        model="none",
        elements=(
            element(CLEAN_ONE, "subject", "Object", "stone bowl", ("brass tray", "glass carafe")),
            element(CLEAN_ONE, "surface", "Surface", "pale oak", ("dark walnut", "white marble")),
        ),
    ),
    PromptTemplate(
        id="clean_two",
        prompt=CLEAN_TWO,
        model="none",
        elements=(
            element(
                CLEAN_TWO, "subject", "Product", "copper kettle", ("steel toaster", "clay jug")
            ),
            element(CLEAN_TWO, "light", "Light", "warm rim lighting", ("cool overcast daylight",)),
        ),
    ),
    PromptTemplate(
        id="clean_three",
        prompt=CLEAN_THREE,
        model="none",
        elements=(
            element(CLEAN_THREE, "subject", "Object", "woven basket", ("folded cloth", "clay pot")),
            element(
                CLEAN_THREE, "backdrop", "Backdrop", "deep green", ("dusty rose", "matte black")
            ),
        ),
    ),
    PromptTemplate(
        id="clean_four",
        prompt=CLEAN_FOUR,
        model="none",
        elements=(
            element(CLEAN_FOUR, "subject", "Object", "slate tile", ("birch plank", "copper sheet")),
            element(CLEAN_FOUR, "light", "Light", "a low winter sun", ("a single street lamp",)),
        ),
    ),
)


class Clean(unittest.TestCase):
    def test_a_correct_template_produces_nothing_at_all(self) -> None:
        for template in CLEAN_TEMPLATES:
            with self.subTest(template.id):
                report = lint(template)
                self.assertEqual(report["findings"], [], report["note"])
                self.assertEqual(report["outcome"], PASS)
                self.assertGreater(report["combinations"], 0)

    def test_a_clean_catalogue_passes_as_a_whole(self) -> None:
        report = lint_catalogue(CLEAN_TEMPLATES)
        self.assertEqual(report["outcome"], PASS)
        self.assertEqual(report["violations"], 0)
        self.assertEqual(report["combinations"], 22)


# --------------------------------------------------------------------------
# The three outcomes. `combinations == 0` is never `pass`.
# --------------------------------------------------------------------------


class ThreeOutcomes(unittest.TestCase):
    def test_no_template_is_could_not_measure(self) -> None:
        report = lint(None)
        self.assertEqual(report["outcome"], UNMEASURED)
        self.assertEqual(report["combinations"], 0)
        self.assertEqual(report["unmeasured"], 1)

    def test_a_template_with_no_elements_is_could_not_measure(self) -> None:
        report = lint(PromptTemplate(id="bare", prompt="a red bench", model="none", elements=()))
        self.assertEqual(report["outcome"], UNMEASURED)
        self.assertEqual(report["combinations"], 0)

    def test_nothing_rendered_is_never_a_pass(self) -> None:
        """An empty value is refused by the substituter, so no pair renders."""
        template = PromptTemplate(
            id="all_values_refused",
            prompt="a red bench under a full moon",
            model="none",
            elements=(Element("surface", "Surface", (0, 11), ("",)),),
        )
        report = lint(template)
        self.assertEqual(report["outcome"], UNMEASURED)
        self.assertEqual(report["combinations"], 0)
        self.assertEqual(report["violations"], 0)

    def test_a_partly_rendered_template_is_could_not_measure_not_pass(self) -> None:
        template = PromptTemplate(
            id="one_value_refused",
            prompt="a red bench under a full moon",
            model="none",
            elements=(
                Element("surface", "Surface", (0, 11), ("a red bench", "a stone ledge", "")),
            ),
        )
        report = lint(template)
        self.assertEqual(report["outcome"], UNMEASURED)
        self.assertEqual(report["combinations"], 2)
        self.assertEqual(report["unmeasured"], 1)

    def test_a_violation_outranks_an_unrendered_pair(self) -> None:
        """A defect that WAS seen does not stop being true because another pair was not."""
        base = "a tailored deep burgundy jacket, folded once and left on a bench"
        template = PromptTemplate(
            id="violation_and_unrendered",
            prompt=base,
            model="none",
            elements=(Element("subject", "Subject", (11, 31), ("folded ivory linen suit", "")),),
        )
        report = lint(template)
        self.assertEqual(base[11:31], "deep burgundy jacket")
        self.assertEqual(report["outcome"], FAIL)
        self.assertEqual(report["violations"], 1)
        self.assertEqual(report["unmeasured"], 1)

    def test_an_empty_catalogue_is_could_not_measure(self) -> None:
        report = lint_catalogue([])
        self.assertEqual(report["outcome"], UNMEASURED)
        self.assertEqual(report["combinations"], 0)

    def test_every_return_carries_every_key(self) -> None:
        """A judging dict with a missing key is a KeyError on the path nobody runs."""
        expected = {
            "outcome",
            "checked",
            "violations",
            "unmeasured",
            "note",
            "findings",
            "combinations",
            "risks",
        }
        for report in (
            lint(None),
            lint(PromptTemplate(id="bare", prompt="a red bench", model="none", elements=())),
            lint(CLEAN_TEMPLATES[0]),
            lint_catalogue([]),
            lint_catalogue(CLEAN_TEMPLATES),
        ):
            self.assertLessEqual(expected, set(report))


# --------------------------------------------------------------------------
# The shipped catalogue. This is the regression that would catch a subtraction
# gone too far: the catalogue is KNOWN to hold two substitution-induced
# repetitions, so a clean bill of health here is a bug in the linter.
# --------------------------------------------------------------------------


class ShippedCatalogue(unittest.TestCase):
    def test_the_two_known_repetitions_are_still_found(self) -> None:
        report = lint_catalogue(CATALOGUE)
        repeats = sorted(
            (f.element, f.value) for f in report["findings"] if f.check == "repetition"
        )
        self.assertEqual(
            repeats,
            [
                ("light", "hard, raking studio lighting"),
                ("subject", "folded ivory linen suit"),
            ],
        )

    def test_the_catalogue_fails_and_says_how_much_it_measured(self) -> None:
        report = lint_catalogue(CATALOGUE)
        self.assertEqual(report["outcome"], FAIL)
        self.assertEqual(report["violations"], 2)
        self.assertEqual(report["combinations"], 49)
        self.assertEqual(report["unmeasured"], 0)

    def test_the_catalogue_produces_no_article_or_seam_findings(self) -> None:
        """Six checks running and only the two real ones firing is the whole claim."""
        report = lint_catalogue(CATALOGUE)
        self.assertEqual(
            sorted({f.check for f in report["findings"]}),
            ["cross_element", "repetition"],
        )

    def test_every_finding_names_a_value_the_template_actually_permits(self) -> None:
        report = lint_catalogue(CATALOGUE)
        permitted = {v for t in CATALOGUE for el in t.elements for v in el.allowed}
        for finding in report["findings"]:
            self.assertIn(finding.value, permitted)
            self.assertTrue(finding.message)
            self.assertIn(finding.severity, (SEVERITY_VIOLATION, SEVERITY_RISK))


# --------------------------------------------------------------------------
# The CLI. The owner runs this; the exit code carries the third outcome.
# --------------------------------------------------------------------------


class Cli(unittest.TestCase):
    def test_exit_codes_are_zero_one_two(self) -> None:
        self.assertEqual(main(["appliance_studio"]), 0)
        self.assertEqual(main(["winter_jacket_moonlight"]), 1)
        self.assertEqual(main(["no_such_template"]), 2)

    def test_the_report_leads_with_counts(self) -> None:
        text = tl._render(lint_catalogue(CATALOGUE))
        self.assertIn("outcome: fail", text)
        self.assertIn("rendered 49 combination(s)", text)
        self.assertIn("could not be measured", text)


if __name__ == "__main__":
    unittest.main()
