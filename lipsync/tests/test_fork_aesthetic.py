"""Gates for the template author's step. Expected numbers are literals."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from lipsync import fork_aesthetic as A
from lipsync import fork_plan
from lipsync.fork_identity import FAIL, PASS, UNMEASURED

DEMO = "assets/fork_plan_woman_fullbody.png"

# C2: evidence is not truncated. Markers sit at BOTH ends because `[:N]` cuts
# the tail and `[-N:]` cuts the head — a test with one marker passes on half
# the defects.
EVIDENCE_HEAD = "HEADMARK_e3f1"
EVIDENCE_TAIL = "TAILMARK_9b27"
LONG_EVIDENCE = EVIDENCE_HEAD + " " + ("filler " * 90) + EVIDENCE_TAIL
SHORT_EVIDENCE = "no such file"


def ends_kept(text: str) -> bool:
    """Return True when both ends of `LONG_EVIDENCE` survived into `text`."""
    return EVIDENCE_HEAD in str(text) and EVIDENCE_TAIL in str(text)


def base_with(*aesthetics):
    return {"aesthetics": list(aesthetics)}


PLAIN = {"id": "plain", "kind": "scene", "prompt": "a woman in a red coat"}
BRANDED = {
    "id": "branded",
    "kind": "scene",
    "prompt": "a woman in a Balenciaga trench and Adidas sneakers",
}


class TheOwnersBaseIsShippedWhole(unittest.TestCase):
    """The base is the template author's material. The module reads it, it does not retell it."""

    def test_all_six_aesthetics_are_present_by_name(self):
        self.assertEqual(
            sorted(A.ids()), ["country", "fisheye", "icecream", "midcentury", "tomatoes", "y2k"]
        )

    def test_the_prompts_are_stored_verbatim_and_not_trimmed(self):
        self.assertEqual(len(A.load("y2k")["prompt"].split()), 211)
        self.assertEqual(len(A.load("fisheye")["prompt"].split()), 49)
        self.assertIn("Adidas", A.load("y2k")["prompt"])

    def test_the_two_kinds_are_marked(self):
        self.assertEqual(A.load("y2k")["kind"], "scene")
        self.assertEqual(A.load("icecream")["kind"], "transform")

    def test_an_unknown_name_is_refused_with_the_list_of_what_exists(self):
        with self.assertRaises(KeyError) as e:
            A.load("nosuch")
        self.assertIn("y2k", str(e.exception))

    def test_a_missing_base_is_refused_not_silently_empty(self):
        with TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                A.load_base(Path(td) / "missing.json")

    def test_an_empty_base_is_refused_not_treated_as_no_aesthetics(self):
        with TemporaryDirectory() as td:
            p = Path(td) / "empty.json"
            p.write_text(json.dumps({"aesthetics": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                A.load_base(p)


class TheBrandListIsASpravkaNotAGate(unittest.TestCase):
    """By the template author's decision brands stay in the prompts, so there is no conflict."""

    def test_a_branded_prompt_is_no_longer_a_third_outcome(self):
        got = A.brand_conflict(BRANDED)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(sorted(got["brands"]), ["Adidas", "Balenciaga"])
        self.assertIn("ALLOWED", got["note"])

    def test_the_note_says_out_loud_that_the_mark_is_judged_by_eye(self):
        self.assertIn("JUDGED BY EYE", A.brand_conflict(BRANDED)["note"])

    def test_a_clean_prompt_is_NOT_accused(self):
        got = A.brand_conflict(PLAIN)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["brands"], [])

    def test_the_shipped_base_really_carries_the_conflict(self):
        self.assertEqual(A.brand_conflict(A.load("y2k"))["brands"], ["Adidas"])
        self.assertEqual(A.brand_conflict(A.load("fisheye"))["brands"], ["Balenciaga"])
        self.assertEqual(A.brand_conflict(A.load("country"))["brands"], [])

    def test_the_prompt_itself_is_never_edited_by_the_check(self):
        before = A.load("y2k")["prompt"]
        A.brand_conflict(A.load("y2k"))
        self.assertEqual(A.load("y2k")["prompt"], before)


class TheIdentityClauseResolvesTheConflictExplicitly(unittest.TestCase):
    """The prompts describe someone else's looks; identity must come from the image."""

    def test_the_owner_prompt_comes_first(self):
        """Rewrite for the decision to cut the anthropometry: the template author's material comes first."""
        got = A.compose(PLAIN)
        self.assertEqual(got["outcome"], PASS)
        self.assertTrue(got["prompt"].startswith("A person in a red coat"), got["prompt"][:80])
        self.assertLess(got["prompt"].index("red coat"), got["prompt"].index("wins on identity"))

    def test_the_owner_prompt_survives_whole_when_the_cut_is_off(self):
        got = A.compose(PLAIN, cut_body=False)
        self.assertTrue(got["prompt"].startswith("a woman in a red coat"), got["prompt"][:80])

    def test_the_identity_clause_is_in_and_names_what_wins(self):
        got = A.compose(PLAIN)["prompt"]
        self.assertIn("the input image wins on identity", got)
        self.assertIn("same face", got)
        self.assertIn("same hair colour", got)

    def test_hairstyling_and_wardrobe_are_left_to_the_prompt(self):
        got = A.compose(PLAIN)["prompt"]
        self.assertIn("hairstyling", got)
        self.assertIn("wardrobe", got)

    def test_removing_the_identity_clause_is_visible_in_the_prompt(self):
        with mock.patch.object(A, "IDENTITY_CLAUSE", ""):
            self.assertNotIn("wins on identity", A.compose(PLAIN)["prompt"])

    def test_the_lettering_ban_comes_from_the_shared_clause_not_a_local_copy(self):
        from lipsync import clauses

        with mock.patch.object(clauses, "NO_BRANDS_CLAUSE", "SWAPPED-BAN"):
            self.assertIn("SWAPPED-BAN", A.compose(PLAIN)["prompt"])

    def test_turning_the_ban_off_is_LOUD_in_the_note(self):
        got = A.compose(PLAIN, with_ban=False)
        self.assertNotIn("no logos", got["prompt"])
        self.assertIn("DISABLED", got["note"])

    def test_an_aesthetic_without_a_prompt_is_UNMEASURED_not_failed(self):
        for bad in ({"id": "empty"}, None, "nosuch-as-a-string-not-in-base"):
            with self.subTest(bad=bad):
                if isinstance(bad, str):
                    with self.assertRaises(KeyError):
                        A.compose(bad)
                else:
                    self.assertEqual(A.compose(bad)["outcome"], UNMEASURED)

    def test_composing_by_name_reads_the_shipped_base(self):
        got = A.compose("country")
        self.assertEqual(got["outcome"], PASS)
        self.assertIn("Scottish landscape", got["prompt"])


class TheOnlyMeasurableAxisIsTheDemoIdentity(unittest.TestCase):
    """Check whether OUR demo identity survived on the aesthetic. One ladder per project."""

    @staticmethod
    def _at(median, outcome=PASS):
        def distances(frames, anchor, **kw):
            return {
                "outcome": outcome,
                "median": median,
                "inside": 1,
                "judged": 1,
                "note": "stub instrument",
            }

        return distances

    def test_the_demo_survived_is_plainly_good(self):
        got = A.accept(made="aes.png", demo=DEMO, distances=self._at(0.0652))
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["median"], 0.0652)

    def test_the_middle_band_is_UNMEASURED_not_failed(self):
        got = A.accept(made="aes.png", demo=DEMO, distances=self._at(0.5))
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn("NOT THE JUDGE", got["note"])

    def test_a_repainted_person_is_a_real_defect(self):
        got = A.accept(made="aes.png", demo=DEMO, distances=self._at(0.9))
        self.assertEqual(got["outcome"], FAIL)
        self.assertIn("REPAINTED", got["note"])

    def test_the_bar_is_the_project_one_and_not_a_copy(self):
        from lipsync import fork_identity

        self.assertEqual(fork_identity.SAME_PERSON_MAX, 0.35)
        self.assertIs(A.SAME_PERSON_MAX, fork_identity.SAME_PERSON_MAX)

    def test_mutating_the_bar_both_ways_turns_the_verdict(self):
        """Mutate the bar stricter and looser on the MEASURED value 0.2753."""
        was = A.SAME_PERSON_MAX
        try:
            A.SAME_PERSON_MAX = 0.1
            self.assertEqual(
                A.accept(made="aes.png", demo=DEMO, distances=self._at(0.2753))["outcome"],
                UNMEASURED,
            )
            A.SAME_PERSON_MAX = 0.5
            self.assertEqual(
                A.accept(made="aes.png", demo=DEMO, distances=self._at(0.2753))["outcome"], PASS
            )
        finally:
            A.SAME_PERSON_MAX = was
        self.assertEqual(A.SAME_PERSON_MAX, 0.35)

    def test_an_instrument_that_fell_is_UNMEASURED_not_failed(self):
        def broken(*a, **k):
            raise RuntimeError("the model failed to load")

        got = A.accept(made="aes.png", demo=DEMO, distances=broken)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn("RuntimeError", got["note"])

    def test_the_verdict_says_out_loud_that_taste_is_not_measured(self):
        got = A.accept(made="aes.png", demo=DEMO, distances=self._at(0.0652))
        self.assertIn("JUDGED BY THE TEMPLATE AUTHOR", got["note"])

    def test_the_plan_is_explicitly_NOT_required_here(self):
        got = A.accept(made="aes.png", demo=DEMO, distances=self._at(0.0652))
        self.assertIn("NOT REQUIRED", got["note"])


if __name__ == "__main__":
    unittest.main()


class TheAnthropometryIsCutOutAndTheCutIsReadable(unittest.TestCase):
    """The template author's decision: cut all the anthropometry."""

    def test_a_body_clause_is_carried_away_whole(self):
        got = A.strip_anthropometry(A.load("y2k")["prompt"])
        cut = [d["clause"] for d in got["dropped"]]
        self.assertIn("she has warm tanned skin with visible freckles", cut)
        self.assertIn("green eyes", cut)
        self.assertNotIn("freckles", got["prompt"])
        self.assertNotIn("green eyes", got["prompt"])

    def test_the_POSE_survives_even_though_it_names_a_body_part(self):
        got = A.strip_anthropometry(A.load("y2k")["prompt"])
        self.assertIn("lip gloss applicator", got["prompt"])
        self.assertIn("holding the gloss bottle", got["prompt"])

    def test_the_RENDER_QUALITY_clauses_survive_the_word_skin(self):
        got = A.strip_anthropometry(A.load("y2k")["prompt"])["prompt"]
        self.assertIn("natural skin texture", got)
        self.assertIn("textures of fabric skin and accessories", got)

    def test_the_SCENE_survives_when_only_an_adjective_was_anthropometric(self):
        got = A.strip_anthropometry(A.load("country")["prompt"])["prompt"]
        self.assertNotIn("beautiful", got)
        self.assertIn("Scottish landscape", got)
        self.assertIn("grazing cows", got)
        self.assertIn("minimal armchair", got)

    def test_hair_COLOUR_goes_but_hair_STYLING_stays(self):
        got = A.strip_anthropometry(A.load("y2k")["prompt"])["prompt"]
        self.assertNotIn("brunette", got)
        self.assertIn("messy bun", got)
        self.assertIn("soft bangs", got)

    def test_the_gender_is_neutralised_because_the_client_may_be_anyone(self):
        got = A.strip_anthropometry(A.load("y2k")["prompt"])["prompt"]
        self.assertNotIn(" woman ", got)
        self.assertNotIn(" she ", got)
        self.assertIn("the person leaning forward", got)

    def test_ethnicity_goes_too(self):
        got = A.strip_anthropometry(A.load("fisheye")["prompt"])["prompt"]
        self.assertNotIn("Slavic", got)
        self.assertNotIn("platinum", got)
        self.assertIn("14mm lens", got)
        self.assertIn("lavender and golden hues", got)

    def test_a_clean_prompt_comes_back_BYTE_FOR_BYTE(self):
        for aid in ("tomatoes", "icecream"):
            with self.subTest(aid=aid):
                was = A.load(aid)["prompt"]
                got = A.strip_anthropometry(was)
                self.assertEqual(got["prompt"], was)
                self.assertEqual(got["dropped"], [])
                self.assertEqual(got["cut_share"], 0.0)

    def test_the_cut_is_reported_in_numbers_not_only_done(self):
        got = A.strip_anthropometry(A.load("y2k")["prompt"])
        self.assertEqual(len(got["dropped"]), 2)
        self.assertIn("clauses removed 2", got["note"])
        self.assertGreater(got["cut_share"], 0)

    def test_the_traces_of_the_operation_are_cleaned_up(self):
        country = A.strip_anthropometry(A.load("country")["prompt"])["prompt"]
        self.assertIn("of a person seated", country)
        self.assertNotIn("an person", country)
        fisheye = A.strip_anthropometry(A.load("fisheye")["prompt"])["prompt"]
        self.assertIn("lens. Person with", fisheye)
        self.assertNotIn("  ", fisheye)
        self.assertNotIn(" ,", fisheye)

    def test_the_owners_base_on_disk_is_NEVER_touched_by_the_cut(self):
        before = A.load("y2k")["prompt"]
        A.strip_anthropometry(before)
        self.assertEqual(A.load("y2k")["prompt"], before)
        self.assertIn("brunette", A.load("y2k")["prompt"])

    def test_an_empty_prompt_is_UNMEASURED_not_an_empty_result(self):
        for bad in ("", "   ", None, 42):
            with self.subTest(bad=bad):
                got = A.strip_anthropometry(bad)
                self.assertEqual(got["outcome"], UNMEASURED)
                self.assertIsNone(got["prompt"])

    def test_mutating_the_clause_list_both_ways_moves_what_is_cut(self):
        """Mutate the pattern list stricter and looser."""
        was = A.ANTHROPOMETRY_CLAUSES
        try:
            A.ANTHROPOMETRY_CLAUSES = ()
            self.assertEqual(A.strip_anthropometry(A.load("y2k")["prompt"])["dropped"], [])
            A.ANTHROPOMETRY_CLAUSES = (r"\bcamera\b",)
            got = A.strip_anthropometry(A.load("y2k")["prompt"])
            self.assertGreater(len(got["dropped"]), 0)
        finally:
            A.ANTHROPOMETRY_CLAUSES = was
        self.assertEqual(len(A.strip_anthropometry(A.load("y2k")["prompt"])["dropped"]), 2)


class TheCutDoesNotWeldTheWordsAroundIt(unittest.TestCase):
    """An optional intensifier must not swallow the space in front of its word.

    MEASURED 01.09.2026 on the shipped cutter: 'a beautiful woman standing in
    the room' came back as 'Awoman standing in the room'. The pattern shape
    `(?:very|...)?\\s*<word>` matches the space BEFORE <word> whenever the
    intensifier is absent, so the article and the noun weld into one token,
    the word boundary the gender swap needs is gone, and 'woman' rides on into
    the model. The report called that run clean: dropped=[], genders=[],
    outcome=pass -- the repair masked the breakage, so the numbers are
    asserted here next to the text.
    """

    #: T3: both edges and the middle. The intensifier is ABSENT in the first
    #: block (the half that carries the defect), PRESENT in the second (the
    #: half that always worked and must keep working), and the third block has
    #: nothing at all in front of the word -- the one case where eating the
    #: leading space is harmless, so it separates "cut too much" from "cut in
    #: the wrong place". Expected strings are literals (T2).
    WELDING = (
        ("a beautiful woman standing in the room", "A person standing in the room"),
        ("the beautiful woman walks", "The person walks"),
        ("a gorgeous woman walks", "A person walks"),
        ("the pretty girl runs", "The person runs"),
        ("a stunning lady waits", "A person waits"),
    )
    INTENSIFIED = (
        ("a very beautiful woman walks", "A person walks"),
        ("an extremely beautiful woman walks", "A person walks"),
        ("a very gorgeous woman walks", "A person walks"),
    )
    NOTHING_IN_FRONT = (
        ("beautiful woman walks", "Person walks"),
        ("pretty girl runs", "Person runs"),
    )

    def _one(self, prompt, want):
        got = A.strip_anthropometry(prompt)
        self.assertEqual(
            got["prompt"],
            want,
            f"the cut welded the neighbours: {prompt!r} -> {got['prompt']!r}, "
            f"wanted {want!r}. Culprit: an ANTHROPOMETRY_WORDS pattern of the "
            f"shape `(?:...)?\\s*word` eats the space in FRONT of the word "
            f"when the optional group matches empty",
        )
        return got

    def test_the_words_on_both_sides_of_the_cut_stay_separate(self):
        for prompt, want in self.WELDING:
            with self.subTest(prompt=prompt):
                self._one(prompt, want)

    def test_an_intensified_phrase_keeps_working(self):
        for prompt, want in self.INTENSIFIED:
            with self.subTest(prompt=prompt):
                self._one(prompt, want)

    def test_a_word_at_the_very_start_is_still_cut_whole(self):
        for prompt, want in self.NOTHING_IN_FRONT:
            with self.subTest(prompt=prompt):
                self._one(prompt, want)

    def test_the_gender_swap_still_fires_after_the_cut_and_is_COUNTED(self):
        """The welded token hid the noun, and the report then claimed a clean run."""
        for prompt, _ in self.WELDING:
            with self.subTest(prompt=prompt):
                got = A.strip_anthropometry(prompt)
                self.assertEqual(
                    [(g["from"], g["times"]) for g in got["genders"]][:1],
                    [(prompt.split()[2], 1)],
                    f"{prompt!r}: the gendered noun was not swapped, and the "
                    f"report says genders={got['genders']} -- a silent leak of "
                    f"the noun into the model",
                )

    def test_no_output_carries_a_token_that_exists_in_no_dictionary(self):
        welded = ("awoman", "thewoman", "agirl", "thegirl", "alady", "aperson")
        for prompt, _ in self.WELDING + self.INTENSIFIED:
            with self.subTest(prompt=prompt):
                low = A.strip_anthropometry(prompt)["prompt"].lower()
                for bad in welded:
                    self.assertNotIn(bad, low, f"{prompt!r} -> {low!r}")

    def test_mutating_the_word_list_both_ways_moves_what_is_cut(self):
        """T1: stricter and looser, on the list this class guards."""
        was = A.ANTHROPOMETRY_WORDS
        try:
            A.ANTHROPOMETRY_WORDS = ()
            loose = A.strip_anthropometry("a beautiful woman walks")
            self.assertEqual(loose["words"], [])
            self.assertEqual(loose["prompt"], "A beautiful person walks")
            A.ANTHROPOMETRY_WORDS = (r"\bwalks\b",)
            strict = A.strip_anthropometry("a beautiful woman walks")
            self.assertEqual(strict["prompt"], "A beautiful person")
        finally:
            A.ANTHROPOMETRY_WORDS = was
        self.assertEqual(
            A.strip_anthropometry("a beautiful woman walks")["prompt"], "A person walks"
        )


class TheCutIsWiredIntoTheComposedPrompt(unittest.TestCase):
    """A cutter that is written but never called looks working until a run."""

    def test_the_composed_prompt_carries_no_anthropometry_by_default(self):
        got = A.compose("y2k")["prompt"]
        self.assertNotIn("brunette", got)
        self.assertNotIn("freckles", got)
        self.assertNotIn("green eyes", got)
        self.assertIn("messy bun", got)
        self.assertIn("lip gloss applicator", got)

    def test_the_identity_clause_KEEPS_its_own_body_words(self):
        got = A.compose("y2k")["prompt"]
        self.assertIn("same face", got)
        self.assertIn("same skin tone", got)
        self.assertIn("same hair colour", got)

    def test_turning_the_cut_off_is_LOUD_and_restores_the_owner_text(self):
        got = A.compose("y2k", cut_body=False)
        self.assertIn("brunette", got["prompt"])
        self.assertIn("CUT DISABLED", got["note"])

    def test_the_cut_report_travels_with_the_prompt(self):
        got = A.compose("y2k")
        self.assertEqual(len(got["cut"]["dropped"]), 2)
        self.assertIn("clauses removed 2", got["note"])


class TheAssembledReferenceTakesTheLookButNeverTheFace(unittest.TestCase):
    """The role line for the aesthetic is the inverse of the stand line, and deliberately so."""

    def test_the_new_clause_asks_for_the_wardrobe_the_old_one_forbade(self):
        new = A.assemble_prompt()
        self.assertIn("take the wardrobe", new)
        self.assertIn("accessories", new)
        self.assertIn("pose", new)

    def test_the_face_stays_forbidden_in_BOTH_editions(self):
        self.assertIn("never copy the face", A.assemble_prompt())
        self.assertIn("same face", A.assemble_prompt(legacy=True))

    def test_the_legacy_clause_is_the_shared_one_and_not_a_copy(self):
        from lipsync import clauses

        legacy = A.assemble_prompt(legacy=True)
        self.assertIn(clauses.ROLE_CLAUSE, legacy)
        self.assertIn(clauses.NO_LOOK_TRANSFER_CLAUSE, legacy)

    def test_the_two_editions_really_differ(self):
        self.assertNotEqual(A.assemble_prompt(), A.assemble_prompt(legacy=True))


class TheLeakIsMeasuredFromBOTHSides(unittest.TestCase):
    """The similarity measure can say 'similar', but not 'similar to this one'."""

    CLIENT = "assets/fork_plan_man_fullbody.png"
    DEMO_W = "assets/fork_plan_woman_fullbody.png"

    @classmethod
    def _pair(cls, to_client, to_demo):
        def distances(frames, anchor, **kw):
            median = {cls.CLIENT: to_client, cls.DEMO_W: to_demo}[str(anchor)]
            return {
                "outcome": PASS,
                "median": median,
                "inside": 1,
                "judged": 1,
                "note": "stub instrument",
            }

        return distances

    def _run(self, to_client, to_demo):
        return A.leak_verdict(
            made="ref.png",
            client=self.CLIENT,
            demo=self.DEMO_W,
            distances=self._pair(to_client, to_demo),
        )

    def test_the_measured_good_case_is_good(self):
        got = self._run(0.2506, 0.9436)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["gap"], 0.693)

    def test_a_leaked_demo_is_a_REAL_defect_not_a_third_outcome(self):
        got = self._run(0.8, 0.1)
        self.assertEqual(got["outcome"], FAIL)
        self.assertIn("LEAKED", got["note"])
        self.assertEqual(got["gap"], -0.7)

    def test_the_measured_middle_case_is_UNMEASURED(self):
        got = self._run(0.3727, 0.9258)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn("OPERATOR JUDGES", got["note"])

    def test_both_close_is_UNMEASURED_because_the_gap_means_nothing_then(self):
        got = self._run(0.20, 0.30)
        self.assertEqual(got["outcome"], UNMEASURED)

    def test_a_missing_distance_is_UNMEASURED_not_a_pass(self):
        def half(frames, anchor, **kw):
            return {
                "outcome": PASS,
                "median": None if str(anchor) == self.DEMO_W else 0.2,
                "inside": 1,
                "judged": 1,
                "note": "half an instrument",
            }

        got = A.leak_verdict(made="ref.png", client=self.CLIENT, demo=self.DEMO_W, distances=half)
        self.assertEqual(got["outcome"], UNMEASURED)

    def test_an_instrument_that_fell_is_UNMEASURED(self):
        def broken(*a, **k):
            raise RuntimeError("the model failed to load")

        got = A.leak_verdict(made="ref.png", client="man.png", demo="woman.png", distances=broken)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn("RuntimeError", got["note"])


class TheGenderPairIsAMachineGateNotANote(unittest.TestCase):
    """The template author's decision: right, aesthetics go by gender."""

    def test_both_demos_are_the_universal_plan_assets(self):
        self.assertEqual(sorted(A.GENDERS), ["f", "m"])
        self.assertEqual(A.demo_for("m"), "assets/fork_plan_man_fullbody.png")
        self.assertEqual(A.demo_for("f"), "assets/fork_plan_woman_fullbody.png")

    def test_an_unknown_gender_is_refused_not_defaulted(self):
        for bad in ("", "w", None, "x"):
            with self.subTest(bad=bad), self.assertRaises(KeyError):
                A.demo_for(bad)

    def test_the_gender_lives_in_the_file_name(self):
        self.assertTrue(str(A.aesthetic_file("y2k", "m")).endswith("y2k_m.png"))
        self.assertTrue(str(A.aesthetic_file("y2k", "f")).endswith("y2k_f.png"))

    def test_a_matching_pair_passes(self):
        got = A.pair_check(client_gender="m", aesthetic_gender="m")
        self.assertEqual(got["outcome"], PASS)

    def test_a_mismatched_pair_is_a_REAL_defect(self):
        got = A.pair_check(client_gender="m", aesthetic_gender="f")
        self.assertEqual(got["outcome"], FAIL)
        self.assertIn("MISMATCH", got["note"])

    def test_an_unnamed_gender_is_NOT_permission_to_continue(self):
        got = A.pair_check(client_gender="", aesthetic_gender="m")
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn("NOT permission", got["note"])

    def test_the_gate_is_case_and_space_insensitive(self):
        self.assertEqual(A.pair_check(client_gender=" M ", aesthetic_gender="m")["outcome"], PASS)


class TheGenderSplitDidNotFixTheWardrobeAndItIsRecorded(unittest.TestCase):
    """A MEASURED negative result, not a forgotten guess."""

    def test_the_owner_prompt_itself_names_the_gendered_garment(self):
        prompt = A.load("y2k")["prompt"]
        self.assertIn("denim mini skirt", prompt)
        self.assertIn("denim mini skirt", A.compose("y2k")["prompt"])

    def test_the_cut_deliberately_leaves_the_wardrobe_alone(self):
        got = A.strip_anthropometry(A.load("y2k")["prompt"])
        self.assertIn("sweatshirt", got["prompt"])
        self.assertIn("mini skirt", got["prompt"])


class TheTemplateGenderIsTheAestheticGender(unittest.TestCase):
    """The template author's decision: keep the prompts' gender, the templates themselves are gendered."""

    def test_every_shipped_aesthetic_names_its_gender(self):
        for aid in A.ids():
            with self.subTest(aid=aid):
                self.assertIn(A.gender_of(aid), A.GENDERS)

    def test_the_shipped_assignment_is_the_one_chosen(self):
        self.assertEqual(A.gender_of("y2k"), "f")
        self.assertEqual(A.gender_of("midcentury"), "f")
        self.assertEqual(A.gender_of("fisheye"), "m")
        self.assertEqual(A.gender_of("tomatoes"), "m")

    def test_an_aesthetic_without_a_gender_is_refused_not_defaulted(self):
        with self.assertRaises(KeyError) as e:
            A.gender_of({"id": "nogender", "prompt": "x"})
        self.assertIn("nogender", str(e.exception))

    def test_the_file_name_follows_the_base_without_being_told(self):
        self.assertTrue(str(A.aesthetic_file("y2k")).endswith("y2k_f.png"))
        self.assertTrue(str(A.aesthetic_file("fisheye")).endswith("fisheye_m.png"))

    def test_a_client_of_the_other_gender_is_stopped_before_generation(self):
        got = A.pair_check(client_gender="m", aesthetic_gender=A.gender_of("y2k"))
        self.assertEqual(got["outcome"], FAIL)

    def test_a_client_of_the_same_gender_passes(self):
        got = A.pair_check(client_gender="m", aesthetic_gender=A.gender_of("fisheye"))
        self.assertEqual(got["outcome"], PASS)


class TheBrandBanWasNarrowedByTheOwner(unittest.TestCase):
    """Let the brands stay, just add no logo to every style prompt."""

    def test_the_ban_forbids_the_drawn_mark_not_the_word(self):
        from lipsync import clauses

        ban = clauses.NO_BRANDS_CLAUSE
        self.assertIn("no logo", ban)
        self.assertIn("no lettering", ban)
        self.assertNotIn("no brand names", ban)

    def test_the_owners_own_brand_words_now_survive_into_the_prompt(self):
        built = A.compose("y2k")["prompt"]
        self.assertIn("Adidas", built)
        self.assertIn("no logo", built)

    def test_the_ban_reaches_every_aesthetic_prompt(self):
        for aid in A.ids():
            with self.subTest(aid=aid):
                self.assertIn("no logo", A.compose(aid)["prompt"])


class EvidenceMarkers(unittest.TestCase):
    """Negative control for the instrument the whole-evidence tests use."""

    def test_the_marker_check_notices_a_cut_at_either_end(self):
        self.assertGreater(len(LONG_EVIDENCE), 200)
        self.assertTrue(ends_kept(LONG_EVIDENCE))
        self.assertFalse(ends_kept(LONG_EVIDENCE[:200]), "a cut tail must be seen")
        self.assertFalse(ends_kept(LONG_EVIDENCE[-120:]), "a cut head must be seen")

    def test_a_short_reason_carries_neither_marker_and_the_check_stays_silent(self):
        self.assertFalse(ends_kept(SHORT_EVIDENCE))


class WholeEvidence(unittest.TestCase):
    """C2: why the identity axis could not be measured arrives whole."""

    @staticmethod
    def _unmeasured(note):
        def distances(frames, anchor, **kw):
            return {
                "outcome": UNMEASURED,
                "median": None,
                "inside": 0,
                "judged": 0,
                "note": note,
            }

        return distances

    def test_an_unmeasured_identity_carries_the_whole_instrument_note(self):
        got = A.accept(made="aes.png", demo=DEMO, distances=self._unmeasured(LONG_EVIDENCE))
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertTrue(ends_kept(got["note"]), got["note"])

    def test_a_short_instrument_note_arrives_unchanged(self):
        got = A.accept(made="aes.png", demo=DEMO, distances=self._unmeasured(SHORT_EVIDENCE))
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertTrue(got["note"].endswith(SHORT_EVIDENCE), got["note"])


READY = {
    "id": "ramp",
    "name": "Ramp",
    "kind": "transform",
    "prompt": "a ramp at dusk",
    "demo": "f",
    "demo_why": "the wardrobe is neutral",
    "driving": "assets/drivings/ramp_f.mp4",
    "window": [150, 299],
    "card": {
        "shoulders": 0.53,
        "ankles": 0.92,
        "centre": 0.53,
        "width": 0.31,
        "tolerances": {"shoulders": 0.05, "ankles": 0.05, "centre": 0.1837, "width": 0.1326},
    },
    "trial": "docs/trials/ramp_f.mp4",
}


def without(field):
    """Return the complete aesthetic with one field taken out."""
    return {k: v for k, v in READY.items() if k != field}


class AnAestheticWithoutItsDrivingIsNotReadyForAnOrder(unittest.TestCase):
    """The order fields are a gate with three outcomes, and the shipped six do not pass it."""

    def test_the_six_shipped_aesthetics_read_as_NOT_READY_and_say_what_is_absent(self):
        """They predate the contract. Reading them as ready is the defect this gate exists for."""
        for aid in A.ids():
            with self.subTest(aid=aid):
                got = A.order_ready(aid)
                self.assertEqual(got["outcome"], FAIL)
                self.assertEqual(got["checked"], 3)
                self.assertEqual(got["violations"], 3)
                self.assertEqual(got["unmeasured"], 0)
                self.assertEqual(got["missing"], ["driving", "window", "card"])

    def test_the_shipped_base_was_NOT_filled_with_placeholders(self):
        for aid in A.ids():
            with self.subTest(aid=aid):
                raw = A.load(aid)
                for field in ("driving", "window", "card", "trial"):
                    self.assertNotIn(field, raw)

    def test_a_complete_aesthetic_is_ready_and_the_numbers_are_printed(self):
        got = A.order_ready(READY)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual((got["checked"], got["violations"], got["unmeasured"]), (3, 0, 0))
        self.assertEqual(got["missing"], [])
        self.assertIn("checked 3, missing 0, broken 0", got["note"])

    def test_each_order_field_is_guarded_ON_ITS_OWN(self):
        """S8: break exactly one field at a time, or one test can cover for the other two."""
        for field in ("driving", "window", "card"):
            with self.subTest(field=field):
                got = A.order_ready(without(field))
                self.assertEqual(got["outcome"], FAIL)
                self.assertEqual(got["missing"], [field])
                self.assertEqual(got["violations"], 1)
                self.assertEqual(got["checked"], 3)
                self.assertIn(field, got["note"])

    def test_the_TRIAL_is_not_an_order_field_because_it_gates_the_PUBLISH(self):
        """Decision 5 makes the trial a condition of publishing, not of ordering."""
        got = A.order_ready(without("trial"))
        self.assertEqual(got["outcome"], PASS)
        self.assertNotIn("trial", A.ORDER_FIELDS)

    def test_an_empty_field_is_an_ABSENT_field_and_not_a_value(self):
        for field, empty in (("driving", ""), ("window", []), ("card", {})):
            with self.subTest(field=field):
                got = A.order_ready({**READY, field: empty})
                self.assertEqual(got["outcome"], FAIL)
                self.assertEqual(got["missing"], [field])

    def test_an_aesthetic_that_could_not_be_READ_is_the_THIRD_outcome(self):
        for bad in ("no-such-aesthetic", 42, None):
            with self.subTest(bad=bad):
                got = A.order_ready(bad)
                self.assertEqual(got["outcome"], UNMEASURED)
                self.assertEqual(got["checked"], 0)
                self.assertEqual(got["unmeasured"], 1)
                self.assertIn("NOT", got["note"])

    def test_zero_checks_is_never_reported_as_a_pass(self):
        """R2: no violations over no checks is not a success."""
        got = A.order_ready("no-such-aesthetic")
        self.assertEqual(got["violations"], 0)
        self.assertNotEqual(got["outcome"], PASS)

    def test_mutating_the_order_field_list_both_ways_moves_the_verdict(self):
        """T1: looser and stricter on the constant that decides readiness."""
        was = A.ORDER_FIELDS
        try:
            A.ORDER_FIELDS = ()
            loose = A.order_ready(without("driving"))
            self.assertEqual(loose["checked"], 0)
            self.assertEqual(loose["outcome"], UNMEASURED)
            A.ORDER_FIELDS = ("driving", "window", "card", "trial")
            strict = A.order_ready(without("trial"))
            self.assertEqual(strict["outcome"], FAIL)
            self.assertEqual(strict["missing"], ["trial"])
        finally:
            A.ORDER_FIELDS = was
        self.assertEqual(A.order_ready(without("trial"))["outcome"], PASS)


class ABrokenOrderFieldIsCaughtAndNotJustAnAbsentOne(unittest.TestCase):
    """A field that is present but unusable is a violation, not a pass."""

    BAD_WINDOWS = (
        ([150], "two frame numbers"),
        ([150, 299, 400], "two frame numbers"),
        ("150:299", "two frame numbers"),
        ([150.5, 299.0], "whole numbers"),
        ([True, False], "whole numbers"),
        ([-1, 299], "before the start"),
        ([300, 299], "after the last"),
    )

    def test_a_window_that_is_not_two_ordered_frame_numbers_is_a_violation(self):
        for window, why in self.BAD_WINDOWS:
            with self.subTest(window=window):
                got = A.order_ready({**READY, "window": window})
                self.assertEqual(got["outcome"], FAIL)
                self.assertEqual(got["missing"], [])
                self.assertEqual(len(got["broken"]), 1)
                self.assertIn(why, got["broken"][0])

    def test_a_window_of_ONE_frame_is_allowed_because_first_may_equal_last(self):
        self.assertEqual(A.order_ready({**READY, "window": [7, 7]})["outcome"], PASS)

    def test_a_card_missing_an_axis_says_HOW_MANY_axes_were_missing(self):
        short = {k: v for k, v in READY["card"].items() if k != "ankles"}
        got = A.order_ready({**READY, "card": short})
        self.assertEqual(got["outcome"], FAIL)
        self.assertIn("of 4 axes 1 carry no median", got["broken"][0])
        self.assertIn("ankles", got["broken"][0])

    def test_a_card_missing_a_TOLERANCE_is_broken_too(self):
        tol = {k: v for k, v in READY["card"]["tolerances"].items() if k != "width"}
        got = A.order_ready({**READY, "card": {**READY["card"], "tolerances": tol}})
        self.assertEqual(got["outcome"], FAIL)
        self.assertIn("carry no tolerance", got["broken"][0])

    def test_a_card_with_no_tolerances_object_at_all_is_broken(self):
        got = A.order_ready(
            {**READY, "card": {k: v for k, v in READY["card"].items() if k != "tolerances"}}
        )
        self.assertEqual(got["outcome"], FAIL)
        self.assertIn("tolerances", got["broken"][0])

    def test_more_than_one_broken_field_is_counted_and_not_collapsed(self):
        got = A.order_ready({**READY, "window": [9, 8], "card": {"tolerances": {}}})
        self.assertEqual(got["violations"], 2)
        self.assertEqual(len(got["broken"]), 2)


class TheReadersDoNotParseTheBaseThemselves(unittest.TestCase):
    """Every order field has an accessor, so a reader never reaches into the json."""

    def test_the_accessors_return_what_the_contract_stores(self):
        self.assertEqual(A.driving_of(READY), Path("assets/drivings/ramp_f.mp4"))
        self.assertEqual(A.window_of(READY), (150, 299))
        self.assertEqual(A.trial_of(READY), Path("docs/trials/ramp_f.mp4"))

    def test_a_root_prefixes_the_stored_repository_relative_path(self):
        self.assertEqual(
            A.driving_of(READY, root="/base"), Path("/base/assets/drivings/ramp_f.mp4")
        )
        self.assertEqual(A.trial_of(READY, root="/base"), Path("/base/docs/trials/ramp_f.mp4"))

    def test_an_accessor_REFUSES_rather_than_inventing_a_default(self):
        for field, call in (
            ("driving", A.driving_of),
            ("window", A.window_of),
            ("card", A.card_of),
            ("trial", A.trial_of),
        ):
            with self.subTest(field=field):
                with self.assertRaises(KeyError) as caught:
                    call(without(field))
                self.assertIn(field, str(caught.exception))
                self.assertIn("order_ready", str(caught.exception))

    def test_the_accessors_read_the_base_by_NAME_too(self):
        with self.assertRaises(KeyError):
            A.driving_of("y2k")
        self.assertEqual(A.gender_of("y2k"), "f")

    def test_a_broken_window_raises_instead_of_returning_a_wrong_pair(self):
        for window in ([300, 299], "150:299", [1.5, 2.5]):
            with self.subTest(window=window):
                with self.assertRaises(ValueError):
                    A.window_of({**READY, "window": window})

    def test_the_card_comes_back_in_the_NESTED_shape_the_contract_declares(self):
        """One declared shape for a card. Readers that need the plan's flat form convert it."""
        got = A.card_of(READY)
        self.assertEqual(
            got,
            {
                "shoulders": 0.53,
                "ankles": 0.92,
                "centre": 0.53,
                "width": 0.31,
                "tolerances": {
                    "shoulders": 0.05,
                    "ankles": 0.05,
                    "centre": 0.1837,
                    "width": 0.1326,
                },
            },
        )

    def test_the_card_carries_a_tolerance_for_every_axis_the_plan_measures(self):
        got = A.card_of(READY)
        self.assertEqual(sorted(got["tolerances"]), sorted(fork_plan.PERSON_AXES))
        self.assertEqual(sorted(k for k in got if k != "tolerances"), sorted(fork_plan.PERSON_AXES))

    def test_the_card_is_a_COPY_and_editing_it_does_not_reach_the_base(self):
        got = A.card_of(READY)
        got["centre"] = 0.99
        got["tolerances"]["centre"] = 0.99
        self.assertEqual(A.card_of(READY)["centre"], 0.53)
        self.assertEqual(READY["card"]["tolerances"]["centre"], 0.1837)

    def test_load_ALSO_surfaces_the_new_fields_for_a_reader_that_falls_back_to_it(self):
        """A reader that cannot find an accessor reads what load() returned, so load must carry them."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "base.json"
            path.write_text(json.dumps(base_with(READY)), encoding="utf-8")
            got = A.load("ramp", path)
            for field in ("driving", "window", "card", "trial"):
                with self.subTest(field=field):
                    self.assertEqual(got[field], READY[field])
            self.assertEqual(A.window_of("ramp", path), (150, 299))
            self.assertEqual(A.driving_of("ramp", path), Path("assets/drivings/ramp_f.mp4"))
            self.assertEqual(A.card_of("ramp", path)["tolerances"]["centre"], 0.1837)

    def test_the_card_axes_are_the_PLANS_and_not_a_second_copy(self):
        self.assertIs(A.CARD_AXES, fork_plan.PERSON_AXES)
        self.assertEqual(len(A.CARD_AXES), 4)

    def test_a_broken_card_raises_instead_of_returning_half_a_card(self):
        with self.assertRaises(ValueError):
            A.card_of({**READY, "card": {"shoulders": 0.5, "tolerances": {}}})
