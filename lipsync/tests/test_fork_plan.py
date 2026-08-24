"""Gates for the universal plan. Each guards a defect, not a line of code."""

import unittest
from unittest import mock

from lipsync import fork_plan as P
from lipsync.fork_identity import FAIL, PASS, UNMEASURED

GOOD = {
    "l_shoulder": (0.58, 0.32, 0.99),
    "r_shoulder": (0.42, 0.32, 0.99),
    "l_elbow": (0.63, 0.48, 0.98),
    "r_elbow": (0.37, 0.48, 0.98),
    "l_wrist": (0.66, 0.62, 0.97),
    "r_wrist": (0.34, 0.62, 0.97),
    "l_hip": (0.55, 0.60, 0.99),
    "r_hip": (0.45, 0.60, 0.99),
    "l_knee": (0.55, 0.75, 0.98),
    "r_knee": (0.45, 0.75, 0.98),
    "l_ankle": (0.55, 0.92, 0.96),
    "r_ankle": (0.45, 0.92, 0.96),
}


def shifted(pose, dx=0.0, dy=0.0):
    return {k: (v[0] + dx, v[1] + dy, v[2]) for k, v in pose.items()}


class ThePlanNumbersComeFromTheMeasuredDrivings(unittest.TestCase):
    """The bands are derived from the driving plans, not from taste."""

    def test_the_shipped_numbers_are_the_chosen_ones(self):
        self.assertEqual(P.PLAN_RATIO, 0.5625)
        self.assertEqual(P.SHOULDERS_BAND, (0.20, 0.42))
        self.assertEqual(P.ANKLES_BAND, (0.86, 0.99))
        self.assertEqual(P.CENTRE_TOL, 0.08)
        self.assertEqual(P.WIDTH_MAX, 0.72)

    def test_the_face_bar_is_imported_not_copied(self):
        from lipsync import fork_intake

        self.assertIs(P.MIN_FACE_PX, fork_intake.MIN_FACE_PX)

    def test_the_measured_styliser_size_is_recorded(self):
        self.assertEqual(P.STYLED_SIZE_MEASURED, (896, 1200))

    def test_the_measured_driving_plans_land_where_the_bands_say(self):
        """Run the negative control of the bands: they must tell drivings apart."""
        lo, hi = P.SHOULDERS_BAND
        self.assertTrue(lo <= 0.375 <= hi, "b2 must land inside")
        self.assertFalse(lo <= 0.531 <= hi, "b4 must land outside")
        a_lo, a_hi = P.ANKLES_BAND
        self.assertTrue(a_lo <= 0.940 <= a_hi, "b2 must land inside")
        self.assertFalse(a_lo <= 0.625 <= a_hi, "b5 must land outside")


class ThePersonBoxIgnoresUnconfidentJoints(unittest.TestCase):
    """A defect, not a line: mediapipe extrapolates joints beyond the frame edge."""

    def test_a_confident_pose_gives_a_box(self):
        box = P.person_box(GOOD)
        self.assertEqual(box["outcome"], PASS)
        self.assertEqual(box["centre"], 0.5)
        self.assertEqual(box["shoulders"], 0.32)
        self.assertEqual(box["ankles"], 0.92)
        self.assertEqual(box["joints"], 12)

    def test_a_joint_beyond_the_frame_does_not_stretch_the_box(self):
        dirty = dict(GOOD, l_ankle=(-0.6, 1.7, 0.03))
        self.assertEqual(P.person_box(dirty)["x0"], 0.34)

    def test_no_confident_joints_is_UNMEASURED_not_failed(self):
        faint = {k: (v[0], v[1], 0.01) for k, v in GOOD.items()}
        got = P.person_box(faint)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn("12", got["note"])

    def test_no_pose_at_all_is_UNMEASURED(self):
        for empty in ({}, None, "pose"):
            with self.subTest(empty=empty):
                self.assertEqual(P.person_box(empty)["outcome"], UNMEASURED)

    def test_mutating_the_visibility_bar_both_ways_moves_the_box(self):
        """Mutate the visibility bar stricter and looser."""
        dirty = dict(GOOD, l_ankle=(-0.6, 1.7, 0.4))
        loose = P.person_box(dirty, min_visibility=0.3)
        self.assertEqual(loose["x0"], -0.6)
        strict = P.person_box(dirty, min_visibility=0.5)
        self.assertEqual(strict["x0"], 0.34)


class TheCanvasAlwaysPadsAndNeverCrops(unittest.TestCase):
    """Cropping is exactly the defect this module was written against."""

    def test_the_measured_styled_size_becomes_nine_by_sixteen(self):
        got = P.canvas_for(896, 1200)
        self.assertEqual((got["width"], got["height"]), (896, 1594))
        self.assertAlmostEqual(got["width"] / got["height"], 0.5625, places=2)

    def test_nothing_is_ever_lost(self):
        for w, h in ((896, 1200), (1024, 1024), (620, 1104), (1920, 1080)):
            with self.subTest(size=(w, h)):
                got = P.canvas_for(w, h)
                self.assertGreaterEqual(got["width"], w)
                self.assertGreaterEqual(got["height"], h)
                self.assertGreaterEqual(got["left"], 0)
                self.assertGreaterEqual(got["top"], 0)

    def test_an_image_already_in_plan_is_left_almost_alone(self):
        got = P.canvas_for(1080, 1920)
        self.assertEqual((got["width"], got["height"]), (1080, 1920))
        self.assertEqual(got["added_share"], 0.0)

    def test_a_landscape_image_grows_in_height_not_shrinks_in_width(self):
        got = P.canvas_for(1920, 1080)
        self.assertEqual(got["width"], 1920)
        self.assertEqual(got["height"], 3414)

    def test_the_sides_are_even_because_h264_refuses_odd_ones(self):
        for w, h in ((897, 1201), (895, 1199), (333, 777)):
            with self.subTest(size=(w, h)):
                got = P.canvas_for(w, h)
                self.assertEqual(got["width"] % 2, 0)
                self.assertEqual(got["height"] % 2, 0)

    def test_nonsense_sizes_are_refused_not_guessed(self):
        for bad in ((0, 100), (100, -1)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                P.canvas_for(*bad)
        for bad in (("896", 1200), (896.0, 1200)):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                P.canvas_for(*bad)

    def test_mutating_the_plan_ratio_both_ways_moves_the_canvas(self):
        """Mutate PLAN_RATIO stricter (narrower) and looser (wider)."""
        was = P.PLAN_RATIO
        try:
            P.PLAN_RATIO = 0.5
            self.assertEqual(P.canvas_for(896, 1200)["height"], 1792)
            P.PLAN_RATIO = 0.75
            self.assertEqual(P.canvas_for(896, 1200)["width"], 900)
        finally:
            P.PLAN_RATIO = was
        self.assertEqual(P.PLAN_RATIO, 0.5625)


class TheVerdictHasThreeOutcomesOnEveryAxis(unittest.TestCase):
    def test_a_photo_in_plan_is_plainly_good(self):
        got = P.plan_verdict(width=1080, height=1920, points=GOOD, face_px=140)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertEqual(got["violations"], 0)

    def test_the_wrong_canvas_is_a_defect(self):
        got = P.plan_verdict(width=896, height=1200, points=GOOD, face_px=140)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual([a["outcome"] for a in got["axes"] if a["name"] == "canvas"], [FAIL])

    def test_a_portrait_crop_fails_on_the_ankles(self):
        waist_up = {k: v for k, v in GOOD.items() if "ankle" not in k and "knee" not in k}
        got = P.plan_verdict(width=1080, height=1920, points=waist_up, face_px=300)
        names = {a["name"]: a["outcome"] for a in got["axes"]}
        self.assertEqual(names["ankles"], UNMEASURED)
        self.assertEqual(got["outcome"], UNMEASURED)

    def test_an_off_centre_person_is_a_defect(self):
        got = P.plan_verdict(width=1080, height=1920, points=shifted(GOOD, dx=0.2), face_px=140)
        self.assertEqual(got["outcome"], FAIL)

    def test_a_person_filling_the_width_is_a_defect(self):
        wide = dict(GOOD, l_wrist=(0.95, 0.62, 0.97), r_wrist=(0.05, 0.62, 0.97))
        got = P.plan_verdict(width=1080, height=1920, points=wide, face_px=140)
        self.assertEqual(got["outcome"], FAIL)

    def test_a_small_face_only_warns_and_does_not_sink_the_verdict(self):
        got = P.plan_verdict(width=1080, height=1920, points=GOOD, face_px=61)
        self.assertEqual(got["outcome"], PASS)
        self.assertIn("WARNING", got["note"])

    def test_a_big_face_gets_NO_warning(self):
        got = P.plan_verdict(width=1080, height=1920, points=GOOD, face_px=140)
        self.assertNotIn("WARNING", got["note"])

    def test_a_face_never_asked_about_is_UNMEASURED_not_absent(self):
        got = P.plan_verdict(width=1080, height=1920, points=GOOD)
        names = {a["name"]: a["outcome"] for a in got["axes"]}
        self.assertEqual(names["face"], UNMEASURED)

    def test_a_missing_size_is_UNMEASURED_not_failed(self):
        got = P.plan_verdict(points=GOOD, face_px=140)
        names = {a["name"]: a["outcome"] for a in got["axes"]}
        self.assertEqual(names["canvas"], UNMEASURED)
        self.assertEqual(got["outcome"], UNMEASURED)

    def test_mutating_each_band_both_ways_turns_the_verdict(self):
        """Mutate every band: stricter fails a good input, looser lets a defect pass."""
        ok = dict(width=1080, height=1920, points=GOOD, face_px=140)
        wide = dict(GOOD, l_wrist=(0.95, 0.62, 0.97), r_wrist=(0.05, 0.62, 0.97))
        off_centre = dict(ok, points=shifted(GOOD, dx=0.05))
        cases = (
            (
                "SHOULDERS_BAND",
                (0.40, 0.42),
                (0.0, 1.0),
                ok,
                dict(
                    ok,
                    points=dict(GOOD, l_shoulder=(0.58, 0.55, 0.99), r_shoulder=(0.42, 0.55, 0.99)),
                ),
            ),
            (
                "ANKLES_BAND",
                (0.95, 0.99),
                (0.0, 1.0),
                ok,
                dict(ok, points=dict(GOOD, l_ankle=(0.55, 0.62, 0.96), r_ankle=(0.45, 0.62, 0.96))),
            ),
            ("CENTRE_TOL", 0.0001, 0.5, off_centre, dict(ok, points=shifted(GOOD, dx=0.2))),
            ("WIDTH_MAX", 0.05, 1.0, ok, dict(ok, points=wide)),
        )
        for name, strict, loose, good, bad in cases:
            was = getattr(P, name)
            try:
                setattr(P, name, was)
                self.assertEqual(
                    P.plan_verdict(**good)["outcome"],
                    PASS,
                    f"{name}: a good input must pass on the production band",
                )
                setattr(P, name, strict)
                self.assertEqual(
                    P.plan_verdict(**good)["outcome"], FAIL, f"{name} stricter did not go red"
                )
                setattr(P, name, was)
                self.assertEqual(
                    P.plan_verdict(**bad)["outcome"],
                    FAIL,
                    f"{name}: a defect must go red on the production band",
                )
                setattr(P, name, loose)
                self.assertEqual(
                    P.plan_verdict(**bad)["outcome"], PASS, f"{name} looser did not let it pass"
                )
            finally:
                setattr(P, name, was)


class TheFullBodyPromptIsADecisionNotAString(unittest.TestCase):
    def test_the_prompt_asks_for_head_to_feet_and_keeps_the_person(self):
        got = P.full_body_prompt()
        self.assertIn("FULL HEIGHT", got)
        self.assertIn("head to feet", got)
        self.assertIn("same person", got)

    def test_removing_the_identity_clause_is_visible_in_the_prompt(self):
        with mock.patch.object(P, "KEEP_IDENTITY_CLAUSE", ""):
            self.assertNotIn("same person", P.full_body_prompt())

    def test_the_brand_ban_is_in_the_prompt_and_is_not_a_copy(self):
        from lipsync import fork_e2e

        self.assertIn(fork_e2e.NO_BRANDS_CLAUSE, P.full_body_prompt())
        self.assertIn("no logos", P.full_body_prompt())

    def test_the_ban_comes_from_the_stand_not_from_a_local_copy(self):
        from lipsync import fork_e2e

        with mock.patch.object(fork_e2e, "NO_BRANDS_CLAUSE", "SWAPPED-BAN"):
            self.assertIn("SWAPPED-BAN", P.full_body_prompt())

    def test_extra_words_are_appended_not_substituted(self):
        got = P.full_body_prompt(extra="plain grey studio background")
        self.assertIn("FULL HEIGHT", got)
        self.assertIn("grey studio", got)


class TheDiskIsAnInjectionPoint(unittest.TestCase):
    """The module must be checkable without PIL and without the disk."""

    def test_an_unopenable_image_is_UNMEASURED_not_failed(self):
        def broken(_):
            raise OSError("no such file")

        got = P.to_plan("missing.png", "out.png", opener=broken)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn("OSError", got["note"])
        self.assertIsNone(got["path"])


if __name__ == "__main__":
    unittest.main()


class TheDrivingDictatesThePlanNotAConstant(unittest.TestCase):
    """The template author's architectural decision: the driving frame's composition rules the plan."""

    @staticmethod
    def poses(ankle=0.92, shoulder=0.32, centre=0.5, jitter=0.01, n=20):
        return [
            {
                "l_shoulder": (centre + 0.08, shoulder + i * jitter, 0.99),
                "r_shoulder": (centre - 0.08, shoulder, 0.99),
                "l_ankle": (centre + 0.05, ankle + i * jitter, 0.96),
                "r_ankle": (centre - 0.05, ankle, 0.96),
            }
            for i in range(n)
        ]

    def test_the_card_is_measured_from_the_frames(self):
        got = P.composition_card(self.poses(ankle=0.90, shoulder=0.40))
        self.assertEqual(got["outcome"], PASS)
        self.assertAlmostEqual(got["ankles"], 0.9500, places=3)
        self.assertEqual(got["frames"], 20)

    def test_the_tolerance_comes_from_the_material_not_from_taste(self):
        calm = P.composition_card(self.poses(jitter=0.0))
        wild = P.composition_card(self.poses(jitter=0.02))
        self.assertEqual(calm["tol_ankles"], P.CARD_TOL_MIN)
        self.assertGreater(wild["tol_ankles"], calm["tol_ankles"])

    def test_the_tolerance_is_clamped_at_both_ends(self):
        huge = P.composition_card(self.poses(jitter=0.2))
        self.assertEqual(huge["tol_ankles"], P.CARD_TOL_MAX)
        self.assertEqual((P.CARD_TOL_MIN, P.CARD_TOL_MAX), (0.05, 0.20))

    def test_no_readable_pose_is_UNMEASURED_not_an_empty_card(self):
        self.assertEqual(P.composition_card([{}, {}])["outcome"], UNMEASURED)
        self.assertEqual(P.composition_card([])["outcome"], UNMEASURED)

    def test_the_clause_speaks_photography_not_coordinates(self):
        card = P.composition_card(self.poses(ankle=0.93, shoulder=0.30))
        text = P.framing_clause(card)
        self.assertIn("full-length shot", text)
        self.assertNotIn("0.9", text)

    def test_the_clause_does_NOT_dictate_where_the_feet_are_cut(self):
        """By the template author's decision the ankle crop does not go into the prompt."""
        text = P.framing_clause(P.composition_card(self.poses(ankle=0.95)))
        self.assertNotIn("bottom edge", text)
        self.assertNotIn("feet", text)
        self.assertIn("full-length", text)

    def test_the_clause_says_it_outranks_the_aesthetic_framing(self):
        text = P.framing_clause(P.composition_card(self.poses()))
        self.assertIn("outranks", text)
        self.assertIn("no perspective distortion", text)

    def test_an_off_centre_driving_says_so(self):
        left = P.framing_clause(P.composition_card(self.poses(centre=0.26)))
        self.assertIn("left of centre", left)

    def test_no_card_means_no_clause_and_NOT_a_guess(self):
        self.assertEqual(P.framing_clause(None), "")
        self.assertEqual(P.framing_clause({"outcome": UNMEASURED}), "")

    def test_a_reference_matching_the_card_passes(self):
        card = P.composition_card(self.poses(ankle=0.92, shoulder=0.32))
        got = P.in_card(self.poses()[0], card)
        self.assertEqual(got["outcome"], PASS)

    def test_a_different_ankle_line_is_NOT_a_defect_any_more(self):
        """Rewrite: only the composition axes are judged, centre and width."""
        card = P.composition_card(self.poses(ankle=0.913, shoulder=0.531))
        miss = self.poses(ankle=0.7358, shoulder=0.4846)[0]
        self.assertEqual(P.in_card(miss, card)["outcome"], PASS)

    def test_the_numbers_are_still_MEASURED_even_though_not_judged(self):
        card = P.composition_card(self.poses(ankle=0.913, shoulder=0.531))
        self.assertAlmostEqual(card["shoulders"], 0.5810, places=3)
        got = P.in_card(self.poses(ankle=0.7358)[0], card)
        self.assertIn("NOT JUDGED", got["note"])

    def test_an_off_centre_reference_is_STILL_a_defect(self):
        card = P.composition_card(self.poses(centre=0.5114))
        got = P.in_card(self.poses(centre=0.2601)[0], card)
        self.assertEqual(got["outcome"], FAIL)
        self.assertIn("centre", got["note"])
        self.assertIn("slides off the frame edge", got["note"])

    def test_without_a_card_the_check_is_UNMEASURED_not_a_pass(self):
        self.assertEqual(P.in_card(self.poses()[0], None)["outcome"], UNMEASURED)
