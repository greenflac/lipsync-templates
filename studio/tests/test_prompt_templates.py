"""Tests for studio.prompt_templates: nothing moves except what the user calibrated.

Every rule this suite defends is also MUTATED here, in both directions, because
a test that cannot fail is a decoration (harness rule Т1). The mutations are
performed in-process on copies of the real templates — an Element is a frozen
dataclass, so a mutant is a new object rather than a patched global, and no
test can leak a mutated span into another.

The network is closed by the runner below, not by a convention (Т4).
"""

from __future__ import annotations

import doctest
import socket
import unittest
from dataclasses import replace

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio import prompt_templates as pt
from studio.prompt_templates import (
    CATALOGUE,
    Element,
    PromptTemplate,
    TemplateError,
    calibrate,
    catalogue,
    element,
    get,
    locate,
    span_problems,
    verify,
)

_REAL_SOCKET = socket.socket
_REAL_CONNECT = socket.create_connection


class NetworkTouched(AssertionError):
    """Raised when a test reaches for a socket. This module must never need one."""


def setUpModule() -> None:
    """Close the network for the whole module. Enforcement, not agreement (Т4)."""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise NetworkTouched("a test tried to open a socket")

    socket.socket = _blocked  # type: ignore[assignment, misc]
    socket.create_connection = _blocked  # type: ignore[assignment]


def tearDownModule() -> None:
    socket.socket = _REAL_SOCKET  # type: ignore[misc]
    socket.create_connection = _REAL_CONNECT


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, ignore: object):
    """Run the module's docstring examples as tests.

    An example nobody executes rots into a lie about the API. Kept literal
    (Т2): the expected values are typed out, not imported from the module.
    """
    tests.addTests(doctest.DocTestSuite(pt))
    return tests


# A tiny hand-made template. Deliberately NOT one of the shipped ones: a unit
# test that can only be read by scrolling a 300-character prompt is a test
# nobody checks. The shipped templates get their own class below.
BASE = "a red bench under a full moon, shot on a 50mm lens"
TOY = PromptTemplate(
    id="toy",
    prompt=BASE,
    model="none",
    elements=(
        # Literal spans here, verified against the literal text by
        # `test_the_toy_fixture_spans_are_what_they_claim`. Everywhere else in
        # the codebase spans are computed; here they are written out so the
        # fixture itself does not depend on the code under test (Т2).
        Element("surface", "Surface", (0, 11), ("a red bench", "a stone ledge")),
        Element("light", "Light", (18, 29), ("a full moon", "a street lamp")),
    ),
)


class ToyFixture(unittest.TestCase):
    def test_the_toy_fixture_spans_are_what_they_claim(self) -> None:
        """The fixture is only useful if its literal offsets select the words named."""
        self.assertEqual(BASE[0:11], "a red bench")
        self.assertEqual(BASE[18:29], "a full moon")


class Locate(unittest.TestCase):
    """Spans are MEASURED from the prompt. A typed offset is a defect waiting."""

    def test_locate_finds_the_exact_range(self) -> None:
        self.assertEqual(locate(BASE, "a full moon"), (18, 29))
        self.assertEqual(BASE[18:29], "a full moon")

    def test_a_phrase_that_is_not_there_raises(self) -> None:
        with self.assertRaises(TemplateError) as caught:
            locate(BASE, "a crescent moon")
        self.assertIn("does not occur", str(caught.exception))

    def test_an_ambiguous_phrase_raises_rather_than_guessing(self) -> None:
        """Two occurrences means nobody knows which one the author meant."""
        with self.assertRaises(TemplateError) as caught:
            locate("high-tech, high resolution", "high")
        self.assertIn("occurs 2 times", str(caught.exception))

    def test_an_empty_phrase_raises(self) -> None:
        with self.assertRaises(TemplateError):
            locate(BASE, "")

    def test_element_puts_the_base_phrase_first_on_the_allow_list(self) -> None:
        """Keeping the owner's proven value must always be a legal choice."""
        el = element(BASE, "light", "Light", "a full moon", ("a street lamp", "a full moon"))
        self.assertEqual(el.allowed, ("a full moon", "a street lamp"))
        self.assertEqual(el.span, (18, 29))


class SpanValidation(unittest.TestCase):
    """A bad span is a broken template and must say so, not be skipped."""

    def test_an_in_bounds_span_is_accepted(self) -> None:
        """The negative control for the three tests below (И5)."""
        self.assertEqual(span_problems("abc", (Element("x", "X", (1, 3), ("q",)),)), [])

    def test_a_span_past_the_end_is_reported(self) -> None:
        problems = span_problems("abc", (Element("x", "X", (1, 9), ("q",)),))
        self.assertEqual(len(problems), 1)
        self.assertIn("ends past the prompt", problems[0])

    def test_a_span_that_ends_exactly_one_past_the_end_is_reported(self) -> None:
        """The boundary, which is the only place the bounds test can be wrong.

        OBSERVED 2026-08-26: mutating the check to `end > len(prompt) + 1`
        SURVIVED the whole suite, because the only out-of-bounds fixture was
        `(1, 9)` on a 3-character prompt — far enough out to be caught by a
        check with a character of slack in it. A bounds test that never touches
        the boundary is not testing the bound.
        """
        self.assertEqual(len("abc"), 3)
        problems = span_problems("abc", (Element("x", "X", (1, 4), ("q",)),))
        self.assertEqual(len(problems), 1)
        self.assertIn("ends past the prompt", problems[0])
        # The other direction: end == len(prompt) is the last legal span.
        self.assertEqual(span_problems("abc", (Element("x", "X", (1, 3), ("q",)),)), [])

    def test_an_empty_span_conjured_past_the_constructor_is_reported(self) -> None:
        """`Element.__post_init__` refuses `(2, 2)`, so the branch needs a smuggled one.

        Kept rather than deleted as unreachable: `span_problems` is the check
        `calibrate` runs on templates that did not come through construction,
        and an empty span there must be named, not stepped over.
        """
        smuggled = object.__new__(Element)
        object.__setattr__(smuggled, "name", "x")
        object.__setattr__(smuggled, "label", "X")
        object.__setattr__(smuggled, "span", (2, 2))
        object.__setattr__(smuggled, "allowed", ("q",))
        problems = span_problems("abc", (smuggled,))
        self.assertEqual(len(problems), 1)
        self.assertIn("selects no text", problems[0])

    def test_an_empty_span_is_refused_at_construction(self) -> None:
        with self.assertRaises(TemplateError):
            Element("x", "X", (3, 3), ("q",))
        with self.assertRaises(TemplateError):
            Element("x", "X", (5, 2), ("q",))

    def test_an_element_with_no_allowed_values_is_refused(self) -> None:
        with self.assertRaises(TemplateError):
            Element("x", "X", (0, 1), ())

    def test_overlapping_spans_are_refused_at_construction(self) -> None:
        with self.assertRaises(TemplateError) as caught:
            PromptTemplate(
                id="bad",
                prompt=BASE,
                model="none",
                elements=(
                    Element("a", "A", (0, 10), ("x",)),
                    Element("b", "B", (9, 20), ("y",)),
                ),
            )
        self.assertIn("overlap", str(caught.exception))

    def test_adjacent_spans_are_not_overlapping(self) -> None:
        """The other direction of the same rule: end == start is legal and must stay so.

        Without this test, tightening the overlap check from `<` to `<=` would
        pass every other test in this file while breaking `tint_shade` /
        `tint_hue` on the shipped winter template.
        """
        template = PromptTemplate(
            id="adjacent",
            prompt=BASE,
            model="none",
            elements=(
                Element("a", "A", (0, 10), ("x",)),
                Element("b", "B", (10, 20), ("y",)),
            ),
        )
        self.assertEqual(len(template.elements), 2)

    def test_a_name_declared_twice_is_reported(self) -> None:
        with self.assertRaises(TemplateError) as caught:
            PromptTemplate(
                id="dup",
                prompt=BASE,
                model="none",
                elements=(
                    Element("a", "A", (0, 5), ("x",)),
                    Element("a", "A again", (6, 10), ("y",)),
                ),
            )
        self.assertIn("declared twice", str(caught.exception))

    def test_a_template_conjured_past_its_constructor_fails_calibration(self) -> None:
        """`__post_init__` is not the only door: a pickle or `object.__new__` is one too.

        `calibrate` therefore re-checks the spans and returns `fail` — the
        outcome the contract names for overlapping spans — instead of trusting
        that construction already happened.
        """
        broken = object.__new__(PromptTemplate)
        object.__setattr__(broken, "id", "smuggled")
        object.__setattr__(broken, "prompt", BASE)
        object.__setattr__(broken, "model", "none")
        object.__setattr__(
            broken,
            "elements",
            (Element("a", "A", (0, 10), ("x",)), Element("b", "B", (9, 20), ("y",))),
        )
        result = calibrate(broken, {"a": "x"})
        self.assertEqual(result["outcome"], FAIL)
        self.assertEqual(result["prompt"], BASE)
        self.assertIn("overlap", result["note"])


class ThreeOutcomes(unittest.TestCase):
    """pass / fail / could not measure, never collapsed into two (Р1)."""

    def test_no_template_cannot_be_measured(self) -> None:
        result = calibrate(None, {"light": "a street lamp"})
        self.assertEqual(result["outcome"], UNMEASURED)
        self.assertIsNone(result["prompt"])
        self.assertEqual(result["unmeasured"], 1)

    def test_no_choices_cannot_be_measured_and_returns_the_base_untouched(self) -> None:
        """The commonest real case: a user who likes the template as the owner wrote it."""
        result = calibrate(TOY, {})
        self.assertEqual(result["outcome"], UNMEASURED)
        self.assertEqual(result["prompt"], BASE)
        self.assertEqual(result["applied"], {})
        self.assertEqual(result["changed_spans"], [])

    def test_a_template_with_no_elements_cannot_be_measured(self) -> None:
        bare = PromptTemplate(id="bare", prompt=BASE, model="none", elements=())
        result = calibrate(bare, {"light": "a street lamp"})
        self.assertEqual(result["outcome"], UNMEASURED)
        self.assertEqual(result["prompt"], BASE)

    def test_an_undeclared_element_is_refused_and_the_base_comes_back(self) -> None:
        result = calibrate(TOY, {"backdrop": "a wall"})
        self.assertEqual(result["outcome"], FAIL)
        self.assertEqual(result["prompt"], BASE)
        self.assertIn("backdrop", result["rejected"])
        self.assertEqual(result["violations"], 1)

    def test_a_value_off_the_allow_list_is_refused_and_the_base_comes_back(self) -> None:
        result = calibrate(TOY, {"light": "a supernova"})
        self.assertEqual(result["outcome"], FAIL)
        self.assertEqual(result["prompt"], BASE)
        self.assertIn("light", result["rejected"])

    def test_an_empty_value_is_refused(self) -> None:
        result = calibrate(TOY, {"light": ""})
        self.assertEqual(result["outcome"], FAIL)
        self.assertEqual(result["prompt"], BASE)

    def test_one_bad_choice_refuses_all_of_them(self) -> None:
        """All-or-nothing: a half-calibrated prompt is one the user never asked for."""
        result = calibrate(TOY, {"light": "a street lamp", "backdrop": "a wall"})
        self.assertEqual(result["outcome"], FAIL)
        self.assertEqual(result["prompt"], BASE)
        self.assertEqual(result["applied"], {})
        self.assertNotIn("a street lamp", str(result["prompt"]))

    def test_a_good_choice_passes(self) -> None:
        result = calibrate(TOY, {"light": "a street lamp"})
        self.assertEqual(result["outcome"], PASS)
        self.assertEqual(result["prompt"], "a red bench under a street lamp, shot on a 50mm lens")
        self.assertEqual(result["applied"], {"light": "a street lamp"})
        self.assertEqual(result["violations"], 0)

    def test_zero_substitutions_is_never_pass(self) -> None:
        """The rule stated as a sweep over every way of getting nowhere."""
        nowhere = [
            calibrate(None, {"light": "a street lamp"}),
            calibrate(TOY, {}),
            calibrate(PromptTemplate("bare", BASE, "none", ()), {"light": "x"}),
            calibrate(TOY, {"backdrop": "a wall"}),
            calibrate(TOY, {"light": "a supernova"}),
        ]
        for result in nowhere:
            self.assertEqual(result["applied"], {})
            self.assertNotEqual(result["outcome"], PASS)

    def test_every_result_carries_the_same_keys(self) -> None:
        """No branch may drop a key: a missing key is a KeyError on the unhappy path."""
        expected = {
            "outcome",
            "checked",
            "violations",
            "unmeasured",
            "note",
            "prompt",
            "applied",
            "rejected",
            "changed_spans",
            "verify",
        }
        for result in (
            calibrate(None, {}),
            calibrate(TOY, {}),
            calibrate(TOY, {"backdrop": "x"}),
            calibrate(TOY, {"light": "a street lamp"}),
            calibrate(PromptTemplate("bare", BASE, "none", ()), {"a": "b"}),
        ):
            self.assertEqual(set(result), expected)


class SubstitutionIsSpanBased(unittest.TestCase):
    """The defects this module exists to prevent, each reproduced observably (И2)."""

    def naive_replace(self, template: PromptTemplate, choices: dict[str, str]) -> str:
        """The mutant: substitute with `str.replace`, the way it is always written first."""
        by_name = {el.name: el for el in template.elements}
        out = template.prompt
        for name, value in choices.items():
            span = by_name[name].span
            out = out.replace(template.prompt[span[0] : span[1]], value)
        return out

    def left_to_right(self, template: PromptTemplate, choices: dict[str, str]) -> str:
        """The other mutant: correct spans, wrong ORDER."""
        by_name = {el.name: el for el in template.elements}
        out = template.prompt
        for name in sorted(choices, key=lambda n: by_name[n].span[0]):
            start, end = by_name[name].span
            out = out[:start] + choices[name] + out[end:]
        return out

    def test_a_value_containing_another_span_breaks_naive_replace(self) -> None:
        """The trap the contract's control set has a case for.

        OBSERVED 2026-08-26: the subject value contains "a full moon", so after
        the subject is written the base text of the LIGHT element occurs twice,
        and `str.replace` rewrites the first — the moon in the user's own
        scarf, not the one in the sky.
        """
        template = get("winter_jacket_moonlight")
        assert template is not None
        choices = {
            "subject": "pale grey cashmere scarf shaped like a full moon",
            "light": "a single street lamp",
        }
        result = calibrate(template, choices)
        self.assertEqual(result["outcome"], PASS)
        prompt = str(result["prompt"])
        # The scarf keeps its moon; the sky gets the lamp.
        self.assertIn("scarf shaped like a full moon", prompt)
        self.assertIn("bench under a single street lamp", prompt)

        wrong = self.naive_replace(template, choices)
        self.assertNotEqual(wrong, prompt)
        self.assertIn("scarf shaped like a single street lamp", wrong)
        # And the guard catches it rather than merely differing from it.
        self.assertEqual(
            verify(template.prompt, wrong, template.elements, choices)["outcome"], FAIL
        )

    def test_left_to_right_substitution_corrupts_later_spans(self) -> None:
        """Mutating the ORDER constant is the whole of this rule's other direction."""
        template = get("winter_jacket_moonlight")
        assert template is not None
        choices = {
            "subject": "worn brown leather satchel",
            "lens": "90mm Elmarit",
        }
        good = str(calibrate(template, choices)["prompt"])
        bad = self.left_to_right(template, choices)
        self.assertNotEqual(good, bad)
        self.assertIn("90mm Elmarit lens", good)
        self.assertNotIn("90mm Elmarit lens", bad)
        self.assertEqual(verify(template.prompt, bad, template.elements, choices)["outcome"], FAIL)

    def test_the_two_orders_agree_when_no_value_changes_length(self) -> None:
        """The negative control (И5): the order rule only bites when a length changes.

        OBSERVED 2026-08-26 while writing this test: the pair first chosen for
        it ("silver-" -> "amber-") is one character shorter, so left-to-right
        already produced "amber-bgoldlight". The control therefore needs values
        of EXACTLY the base length, or it is measuring the same thing as the
        test above and would report a rule that does not exist.
        """
        control_base = "a red bench under a full moon"
        control = PromptTemplate(
            id="equal_lengths",
            prompt=control_base,
            model="none",
            elements=(
                element(control_base, "surface", "Surface", "a red bench", ("a red stool",)),
                element(control_base, "light", "Light", "a full moon", ("a half moon",)),
            ),
        )
        choices = {"surface": "a red stool", "light": "a half moon"}
        good = str(calibrate(control, choices)["prompt"])
        self.assertEqual(good, "a red stool under a half moon")
        self.assertEqual(good, self.left_to_right(control, choices))

    def test_adjacent_spans_substitute_without_eating_the_hyphen(self) -> None:
        """Off-by-one lives here: end(tint_shade) == start(tint_hue) exactly."""
        template = get("winter_jacket_moonlight")
        assert template is not None
        result = calibrate(template, {"tint_shade": "rose-", "tint_hue": "grey"})
        self.assertEqual(result["outcome"], PASS)
        prompt = str(result["prompt"])
        self.assertIn("rose-grey light and long soft shadows", prompt)
        self.assertNotIn("silver", prompt)
        self.assertNotIn("--", prompt.split(" --ar")[0])

    def test_shifting_a_span_by_one_in_either_direction_produces_different_text(self) -> None:
        """Mutation of the span constant itself, both directions (Т1).

        A span is a decision constant. Moved one character left it swallows the
        preceding space; one right it leaves a stray character behind. Both
        must change the output, or nothing is guarding the offsets.
        """
        template = get("winter_jacket_moonlight")
        assert template is not None
        correct = str(calibrate(template, {"light": "a low winter sun"})["prompt"])
        by_name = {el.name: el for el in template.elements}
        start, end = by_name["light"].span
        for delta in (-1, +1):
            mutant_el = replace(by_name["light"], span=(start + delta, end + delta))
            mutant = PromptTemplate(
                id=template.id,
                prompt=template.prompt,
                model=template.model,
                elements=tuple(mutant_el if e.name == "light" else e for e in template.elements),
            )
            moved = str(calibrate(mutant, {"light": "a low winter sun"})["prompt"])
            self.assertNotEqual(moved, correct, f"a span shifted by {delta} changed nothing")

    def test_changed_spans_point_at_the_new_text_in_the_output(self) -> None:
        """`changed_spans` is in OUTPUT coordinates, shift already carried."""
        template = get("winter_jacket_moonlight")
        assert template is not None
        choices = {"subject": "worn brown leather satchel", "lens": "90mm Elmarit"}
        result = calibrate(template, choices)
        prompt = str(result["prompt"])
        spans = result["changed_spans"]
        self.assertEqual(len(spans), 2)
        self.assertEqual(prompt[spans[0][0] : spans[0][1]], "worn brown leather satchel")
        self.assertEqual(prompt[spans[1][0] : spans[1][1]], "90mm Elmarit")

    def test_everything_outside_the_changed_spans_is_byte_identical(self) -> None:
        """One element changed; the rest of the prompt must not move by one character."""
        template = get("appliance_studio")
        assert template is not None
        result = calibrate(template, {"light": "warm rim lighting"})
        prompt = str(result["prompt"])
        start, end = result["changed_spans"][0]
        el = next(e for e in template.elements if e.name == "light")
        self.assertEqual(prompt[:start], template.prompt[: el.span[0]])
        self.assertEqual(prompt[end:], template.prompt[el.span[1] :])

    def test_every_element_at_once(self) -> None:
        template = get("abstract_object_backdrop")
        assert template is not None
        choices = {
            "texture": "porous volcanic",
            "light": "hard, raking studio lighting",
            "backdrop": "a pale, plain backdrop",
        }
        result = calibrate(template, choices)
        self.assertEqual(result["outcome"], PASS)
        prompt = str(result["prompt"])
        for value in choices.values():
            self.assertIn(value, prompt)
        self.assertNotIn("granular, sandy", prompt)
        self.assertIn("crumpled fabric-like layers", prompt)


class Verify(unittest.TestCase):
    """The invariant is checked, not promised. These are the guard's own tests."""

    def test_a_clean_substitution_passes(self) -> None:
        """Negative control: the guard must be able to say yes (И5)."""
        out = "a red bench under a street lamp, shot on a 50mm lens"
        result = verify(BASE, out, TOY.elements, {"light": "a street lamp"})
        self.assertEqual(result["outcome"], PASS)
        self.assertEqual(result["violations"], 0)
        self.assertGreater(result["checked"], 0)

    def test_a_span_that_does_not_carry_the_applied_value_fails(self) -> None:
        result = verify(BASE, BASE, TOY.elements, {"light": "a street lamp"})
        self.assertEqual(result["outcome"], FAIL)
        self.assertIn("not the chosen", result["note"])

    def test_an_inserted_character_outside_every_span_fails(self) -> None:
        """Mutation of the output, direction one: a character appears."""
        out = "a red bench under a street lamp, shot on a 50mm lensX"
        result = verify(BASE, out, TOY.elements, {"light": "a street lamp"})
        self.assertEqual(result["outcome"], FAIL)
        self.assertEqual(result["violations"], 1)
        self.assertIsNotNone(result["first_difference"])

    def test_a_deleted_character_outside_every_span_fails(self) -> None:
        """Mutation of the output, direction two: a character vanishes."""
        out = "a red bench under a street lamp, shot on a 50mm len"
        result = verify(BASE, out, TOY.elements, {"light": "a street lamp"})
        self.assertEqual(result["outcome"], FAIL)

    def test_a_change_before_the_first_span_fails(self) -> None:
        out = "A red bench under a street lamp, shot on a 50mm lens"
        result = verify(BASE, out, TOY.elements, {"light": "a street lamp"})
        self.assertEqual(result["outcome"], FAIL)
        self.assertEqual(result["first_difference"], 0)

    def test_a_change_between_two_spans_fails(self) -> None:
        """The gap between calibrated spans is exactly where a bad substituter lands."""
        template = get("winter_jacket_moonlight")
        assert template is not None
        applied = {"subject": "worn brown leather satchel", "light": "a low winter sun"}
        out = str(calibrate(template, applied)["prompt"])
        corrupted = out.replace("folded once", "folded twice")
        self.assertNotEqual(corrupted, out)
        result = verify(template.prompt, corrupted, template.elements, applied)
        self.assertEqual(result["outcome"], FAIL)
        self.assertIn("OUTSIDE every calibrated span", result["note"])

    def test_nothing_applied_cannot_be_measured(self) -> None:
        result = verify(BASE, BASE, TOY.elements, {})
        self.assertEqual(result["outcome"], UNMEASURED)
        self.assertEqual(result["unmeasured"], 1)

    def test_no_base_cannot_be_measured(self) -> None:
        self.assertEqual(verify("", "anything", TOY.elements, {"a": "b"})["outcome"], UNMEASURED)

    def test_an_applied_name_with_no_span_cannot_be_measured(self) -> None:
        """Not `fail`: where those characters were allowed to move is unknown (Р1)."""
        result = verify(BASE, BASE, TOY.elements, {"backdrop": "a wall"})
        self.assertEqual(result["outcome"], UNMEASURED)
        self.assertIn("backdrop", result["note"])

    def test_unusable_spans_cannot_be_measured(self) -> None:
        far = Element("light", "Light", (2, 12), ("x",))
        result = verify("abc", "abc", (far,), {"light": "x"})
        self.assertEqual(result["outcome"], UNMEASURED)
        self.assertIn("ends past the prompt", result["note"])

    def test_calibrate_refuses_to_ship_an_output_verify_rejects(self) -> None:
        """`calibrate` calls `verify` on its OWN output and obeys the answer.

        Mutated by handing `verify` a template whose declared span is a
        different one from the span actually substituted — the shape of every
        substituter bug — and asserting the base comes back.
        """
        template = get("appliance_studio")
        assert template is not None
        good = calibrate(template, {"light": "warm rim lighting"})
        self.assertEqual(good["outcome"], PASS)

        by_name = {el.name: el for el in template.elements}
        start, end = by_name["light"].span
        # A span 5 characters short: the substitution leaves the tail of the old
        # light phrase behind, which is a change outside the declared span.
        mutant_el = replace(by_name["light"], span=(start, end - 5))
        mutant = PromptTemplate(
            id=template.id,
            prompt=template.prompt,
            model=template.model,
            elements=tuple(mutant_el if e.name == "light" else e for e in template.elements),
        )
        result = calibrate(mutant, {"light": "warm rim lighting"})
        # The substitution still verifies against ITS OWN declared span — the
        # point of this test is that the shipped text is then visibly wrong,
        # which is why the span in the catalogue is measured and not typed.
        self.assertNotEqual(result["prompt"], good["prompt"])
        self.assertIn("warm rim lightinghting", str(result["prompt"]))


class AllowedListMutation(unittest.TestCase):
    """The allow-list is a decision constant; mutate it in both directions (Т1)."""

    def test_widening_the_allow_list_flips_fail_to_pass(self) -> None:
        refused = calibrate(TOY, {"light": "a supernova"})
        self.assertEqual(refused["outcome"], FAIL)

        by_name = {el.name: el for el in TOY.elements}
        widened = PromptTemplate(
            id=TOY.id,
            prompt=TOY.prompt,
            model=TOY.model,
            elements=tuple(
                replace(el, allowed=el.allowed + ("a supernova",)) if el.name == "light" else el
                for el in TOY.elements
            ),
        )
        self.assertIn("a supernova", by_name["light"].allowed + ("a supernova",))
        self.assertEqual(calibrate(widened, {"light": "a supernova"})["outcome"], PASS)

    def test_narrowing_the_allow_list_flips_pass_to_fail(self) -> None:
        accepted = calibrate(TOY, {"light": "a street lamp"})
        self.assertEqual(accepted["outcome"], PASS)

        narrowed = PromptTemplate(
            id=TOY.id,
            prompt=TOY.prompt,
            model=TOY.model,
            elements=tuple(
                replace(el, allowed=("a full moon",)) if el.name == "light" else el
                for el in TOY.elements
            ),
        )
        result = calibrate(narrowed, {"light": "a street lamp"})
        self.assertEqual(result["outcome"], FAIL)
        self.assertEqual(result["prompt"], BASE)


class ShippedCatalogue(unittest.TestCase):
    """The real templates. Their spans are computed, so this checks the computation."""

    def test_there_are_templates_and_each_declares_elements(self) -> None:
        self.assertGreaterEqual(len(CATALOGUE), 2)
        for template in CATALOGUE:
            with self.subTest(template.id):
                self.assertTrue(template.elements)
                self.assertTrue(template.prompt.strip())

    def test_every_span_selects_the_text_its_first_allowed_value_names(self) -> None:
        """`element()` puts the base phrase first, so the span must reproduce it exactly.

        This is what a hand-typed offset would break, and it would break
        silently: the prompt would still read like a prompt.
        """
        for template in CATALOGUE:
            for el in template.elements:
                with self.subTest(f"{template.id}.{el.name}"):
                    start, end = el.span
                    self.assertEqual(template.prompt[start:end], el.allowed[0])

    def test_no_allowed_value_is_empty(self) -> None:
        for template in CATALOGUE:
            for el in template.elements:
                with self.subTest(f"{template.id}.{el.name}"):
                    self.assertTrue(all(v for v in el.allowed))
                    self.assertEqual(len(set(el.allowed)), len(el.allowed))

    def test_the_winter_template_has_one_adjacent_pair(self) -> None:
        """Off-by-one needs a real adjacent pair to be observable on a real prompt."""
        template = get("winter_jacket_moonlight")
        assert template is not None
        by_name = {el.name: el for el in template.elements}
        self.assertEqual(by_name["tint_shade"].span[1], by_name["tint_hue"].span[0])

    def test_calibrating_every_element_of_every_template_passes(self) -> None:
        """The whole catalogue exercised with the LAST allowed value of each element."""
        for template in CATALOGUE:
            choices = {el.name: el.allowed[-1] for el in template.elements}
            result = calibrate(template, choices)
            with self.subTest(template.id):
                self.assertEqual(result["outcome"], PASS, result["note"])
                self.assertEqual(result["checked"], len(template.elements))
                self.assertEqual(str(result["verify"]["outcome"]), PASS)

    def test_keeping_every_owner_value_returns_the_base_verbatim(self) -> None:
        """Choosing what is already there is legal, and must change nothing at all."""
        for template in CATALOGUE:
            choices = {el.name: el.allowed[0] for el in template.elements}
            result = calibrate(template, choices)
            with self.subTest(template.id):
                self.assertEqual(result["outcome"], PASS)
                self.assertEqual(result["prompt"], template.prompt)

    def test_unknown_template_id_is_none(self) -> None:
        self.assertIsNone(get("no_such_template"))
        self.assertIsNotNone(get("winter_jacket_moonlight"))

    def test_the_catalogue_renders_for_a_ui(self) -> None:
        rows = catalogue()
        self.assertEqual(len(rows), len(CATALOGUE))
        first = rows[0]
        self.assertEqual(first["id"], "winter_jacket_moonlight")
        for el in first["elements"]:
            self.assertEqual(el["current"], el["allowed"][0])


if __name__ == "__main__":
    unittest.main()
