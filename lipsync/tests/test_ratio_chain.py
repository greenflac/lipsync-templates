"""Gate: 9:16 is exact everywhere, and the instrument can see when it is not.

Written before the implementation. Never edited by the agent implementing it.

WHY THIS EXISTS, measured 2026-08-26:

  nanobanana-2 has no exact 9:16 point on its vertical grid. Asked for 9:16
  through `compose` (720x1280 and 864x1536) it returns 768x1376 = 0.5581;
  asked through `images_edit` (1080x1920) it returns 1536x2752 = 0.5581. Three
  requests, two routes, one answer. No request fixes this — the six shipped
  templates and both client fixtures are all 1536x2752, which is that same
  0.5581 frozen into the product.

  The drift is 0.5625 - 0.5581 = 0.0044. The instrument's tolerance was 0.015,
  three times coarser, so every stage reported `pass` on a frame that was not
  the plan. Mutation proved the threshold was guarded on one side only:
  loosening to 0.2 reddened 2 tests, tightening to 0.004 reddened none — and
  the real defect lies on the unguarded side.

WHAT THIS GATE FIXES IN THE DESIGN:

  Two different questions were being answered by one number. They are split:
  `ratio_axis` asks "is this exactly the plan?" and is tight; the stage asks
  "can this be trimmed into the plan?" and carries a trim budget. A frame that
  is off-plan but trimmable is neither a pass nor a failure — it is a frame
  that gets trimmed, and the run says so.
"""

from __future__ import annotations

import unittest

from lipsync import fork_e2e as E, fork_finish as F, fork_plan as P

# CHOSEN. One pixel of rounding at our working sizes (768..2752 px tall) moves
# the ratio by under 0.0005, so this admits an exact crop and nothing else. The
# measured defect is 0.0044 — nine times this bound — so it can no longer pass.
PLAN_TOLERANCE = 0.001

# CHOSEN. The largest share of one side that may be trimmed to reach the plan.
# The measured drift costs 0.8% of the height; the 3:4 fossil the route used to
# return would cost 24.7%, which is a face rather than a rounding. 2% sits an
# order of magnitude from both.
TRIM_MAX_SHARE = 0.02

PLAN = 0.5625

# MEASURED 2026-08-26. What each route actually returns for a 9:16 request.
STYLISER_RETURNS = (768, 1376)
OUTPAINT_RETURNS = (1536, 2752)
# MEASURED. The 3:4 fossil, kept as the negative control: it must NOT be
# trimmed, because trimming it would cut the subject.
THREE_BY_FOUR = (896, 1200)


def _exact(width: int, height: int) -> bool:
    return abs(width / height - PLAN) <= PLAN_TOLERANCE


class TheInstrumentCanSeeTheDefect(unittest.TestCase):
    """A tolerance three times coarser than the error measures nothing."""

    def test_the_tolerance_is_a_named_constant_not_a_literal(self) -> None:
        self.assertTrue(
            hasattr(P, "PLAN_TOLERANCE"),
            "the plan tolerance must be a named, importable constant",
        )
        self.assertLessEqual(P.PLAN_TOLERANCE, PLAN_TOLERANCE)

    def test_the_measured_styliser_return_is_not_the_plan(self) -> None:
        axis = P.ratio_axis(*STYLISER_RETURNS)
        self.assertNotEqual(
            axis["outcome"],
            "pass",
            f"0.5581 still reads as the plan: {axis['note']}",
        )

    def test_the_measured_outpaint_return_is_not_the_plan(self) -> None:
        axis = P.ratio_axis(*OUTPAINT_RETURNS)
        self.assertNotEqual(axis["outcome"], "pass", axis["note"])

    def test_an_exact_frame_still_passes(self) -> None:
        """Negative control: the instrument must still be able to say yes."""
        for size in ((720, 1280), (774, 1376), (1530, 2720)):
            with self.subTest(size=size):
                self.assertEqual(P.ratio_axis(*size)["outcome"], "pass")


class OneSourceOfTruthForTheRatio(unittest.TestCase):
    """The ratio was declared twice, independently, in two modules."""

    def test_the_finisher_does_not_redeclare_the_ratio(self) -> None:
        derived = F.TARGET_RATIO_W / F.TARGET_RATIO_H
        self.assertAlmostEqual(
            derived,
            P.PLAN_RATIO,
            places=9,
            msg="fork_finish and fork_plan disagree about what 9:16 is",
        )

    def test_changing_the_plan_moves_the_finisher_with_it(self) -> None:
        """Imported, not copied: one edit must move both.

        The first version of this test looked for the string "fork_plan" in
        the module source. It stayed green with the sides re-declared as
        literals, because the module imports fork_plan for other reasons —
        green on the very defect it names. That is the second time today a
        source-text assertion turned out to prove nothing, and the writer
        found it and reported rather than editing the gate.

        This version moves the plan and checks the finisher moved with it.
        """
        import importlib
        from unittest import mock

        with mock.patch.object(P, "PLAN_RATIO", 0.75):
            moved = importlib.reload(F)
            sides = (moved.TARGET_RATIO_W, moved.TARGET_RATIO_H)
        importlib.reload(F)  # put the module back for every other test

        self.assertEqual(
            sides,
            (3, 4),
            "the plan was moved to 3:4 and the finisher stayed at "
            f"{sides}: it knows the ratio a second, independent way",
        )


class AnOffPlanFrameIsTrimmedNotPadded(unittest.TestCase):
    def test_the_trim_budget_is_declared(self) -> None:
        self.assertTrue(hasattr(P, "TRIM_MAX_SHARE"))
        self.assertAlmostEqual(P.TRIM_MAX_SHARE, TRIM_MAX_SHARE, places=6)

    def test_the_styliser_return_is_trimmed_to_exact(self) -> None:
        fit = P.fit_to_plan(*STYLISER_RETURNS)
        self.assertEqual(fit["action"], "crop", fit)
        self.assertTrue(
            _exact(fit["width"], fit["height"]),
            f"trimmed to {fit['width']}x{fit['height']} and still off-plan",
        )
        self.assertLessEqual(fit["width"], STYLISER_RETURNS[0])
        self.assertLessEqual(fit["height"], STYLISER_RETURNS[1])

    def test_the_outpaint_return_is_trimmed_to_exact(self) -> None:
        fit = P.fit_to_plan(*OUTPAINT_RETURNS)
        self.assertEqual(fit["action"], "crop", fit)
        self.assertTrue(_exact(fit["width"], fit["height"]))

    def test_the_trim_is_small_and_counted(self) -> None:
        fit = P.fit_to_plan(*STYLISER_RETURNS)
        self.assertIn("trimmed_share", fit)
        self.assertGreater(fit["trimmed_share"], 0.0)
        self.assertLessEqual(fit["trimmed_share"], TRIM_MAX_SHARE)

    def test_a_frame_already_exact_is_left_alone(self) -> None:
        fit = P.fit_to_plan(720, 1280)
        self.assertEqual(fit["action"], "none", fit)
        self.assertEqual((fit["width"], fit["height"]), (720, 1280))

    def test_a_frame_far_from_the_plan_is_not_trimmed(self) -> None:
        """Negative control: trimming 3:4 would cut the subject, not a margin."""
        fit = P.fit_to_plan(*THREE_BY_FOUR)
        self.assertNotEqual(
            fit["action"],
            "crop",
            "a 3:4 frame was trimmed into 9:16; that is a face, not a rounding",
        )

    def test_the_band_either_side_of_the_budget_behaves_differently(
        self,
    ) -> None:
        height = 1000
        inside = round(height * PLAN / (1 - TRIM_MAX_SHARE / 2))
        outside = round(height * PLAN / (1 - TRIM_MAX_SHARE * 2))
        self.assertEqual(P.fit_to_plan(inside, height)["action"], "crop")
        self.assertNotEqual(P.fit_to_plan(outside, height)["action"], "crop")


class TheStageComparesAgainstWhatWasAsked(unittest.TestCase):
    """The check is named for the request; it must judge against the request."""

    def test_the_asked_size_is_carried_as_data_not_only_as_prose(self) -> None:
        self.assertTrue(hasattr(E, "STYLED_SIZE"))
        self.assertTrue(
            _exact(*E.STYLED_SIZE),
            f"we are asking for {E.STYLED_SIZE}, which is not the plan",
        )

    def test_a_return_that_is_not_what_was_asked_is_reported_as_such(
        self,
    ) -> None:
        verdict = E.styliser_kept_the_plan(asked=E.STYLED_SIZE, got=STYLISER_RETURNS)
        self.assertIn("asked", verdict)
        self.assertEqual(tuple(verdict["asked"]), tuple(E.STYLED_SIZE))
        self.assertEqual(tuple(verdict["got"]), STYLISER_RETURNS)
        self.assertNotEqual(
            verdict["outcome"],
            "pass",
            "a return that is not the asked size reported a clean pass",
        )

    def test_a_return_equal_to_what_was_asked_passes(self) -> None:
        verdict = E.styliser_kept_the_plan(asked=E.STYLED_SIZE, got=E.STYLED_SIZE)
        self.assertEqual(verdict["outcome"], "pass", verdict)


class WhatShipsIsExact(unittest.TestCase):
    """The end of the pipeline is measured, not assumed."""

    def test_the_finisher_reports_the_ratio_of_what_it_wrote(self) -> None:
        """Behavioural, not textual: the report must carry the measurement.

        Same lesson as the outpaint test above — searching the source for a
        name proves nothing about whether the measurement happens.
        """
        self.assertTrue(
            hasattr(F, "FINISH_REPORT_KEYS"),
            "finish() must declare, as data, that it reports the shipped ratio",
        )
        self.assertIn(
            "shipped_ratio",
            F.FINISH_REPORT_KEYS,
            "the shipped aspect ratio is measured nowhere in the pipeline",
        )

    def test_the_shipped_ratio_axis_exists_and_is_tight(self) -> None:
        self.assertTrue(hasattr(F, "shipped_ratio_axis"))
        self.assertNotEqual(F.shipped_ratio_axis(*STYLISER_RETURNS)["outcome"], "pass")
        self.assertEqual(F.shipped_ratio_axis(720, 1280)["outcome"], "pass")


class TheOutpaintAsksForWhatItWants(unittest.TestCase):
    """Asserted on the real call, not on the source text.

    The first version of this test looked for the word "width" in the source
    of `extend_to_plan`, and was green before the fix because the word already
    appeared in a result key. A test that cannot fail on the defect it names
    is worse than no test: it reports a guard that is not there. The writer
    found this and reported it instead of editing the gate.
    """

    def test_the_outpaint_call_carries_a_size_that_is_the_plan(self) -> None:
        from unittest import mock

        seen: dict = {}

        def fake_edit(*args, **kwargs):
            seen.update(kwargs)
            return "/dev/null/out.png"

        # `fork_plan` now imports the gateway at module level, so the patch
        # goes on the gateway itself; a second patch of the plan's own
        # attribute would replace the module and swallow the call.
        with mock.patch("lipsync.pollinations.images_edit", side_effect=fake_edit):
            try:
                P.extend_to_plan("in.png", "out.png", sizer=lambda _: (1152, 2048))
            except Exception:  # noqa: BLE001 - the call is what is under test
                pass

        self.assertIn(
            "width",
            seen,
            "extend_to_plan called the outpainter without a size and took the "
            "route default, the same mistake compose was fixed for",
        )
        self.assertIn("height", seen)
        self.assertTrue(
            _exact(int(seen["width"]), int(seen["height"])),
            f"the outpainter was asked for {seen['width']}x{seen['height']}, which is not the plan",
        )


class NothingShipsPadded(unittest.TestCase):
    """The owner's acceptance criterion, 2026-08-26, verbatim:

        "our code and both modules included (the template builder and the
         video generator) must give 9:16 with no padding in 100% of cases"

    So padding stops being a repair path and becomes a refusal. A frame that
    cannot be trimmed onto the plan is a frame that must not ship: blurred
    bars in a paid frame are the defect, and quietly repairing them is how
    this survived to production the first time.
    """

    def test_a_padded_fit_is_a_violation_not_a_repair(self) -> None:
        fit = P.fit_to_plan(*THREE_BY_FOUR)
        self.assertEqual(fit["action"], "pad")
        self.assertGreaterEqual(
            fit["violations"],
            1,
            "padding was reported as a clean outcome; under the acceptance "
            "criterion a padded frame is a defect, not a repair",
        )

    def test_a_trimmed_fit_is_not_a_violation(self) -> None:
        """Negative control: the rule above must not condemn everything."""
        fit = P.fit_to_plan(*STYLISER_RETURNS)
        self.assertEqual(fit["action"], "crop")
        self.assertEqual(fit["violations"], 0, fit)

    def test_no_shipped_size_in_the_measured_set_needs_padding(self) -> None:
        """Every size the routes actually return must be reachable by trimming."""
        for size in (STYLISER_RETURNS, OUTPAINT_RETURNS):
            with self.subTest(size=size):
                self.assertEqual(P.fit_to_plan(*size)["action"], "crop")


class TheAssetsThemselvesAreThePlan(unittest.TestCase):
    """The templates are inputs. An input off the plan puts the whole run off it.

    MEASURED: all six templates in assets/aesthetics and all four fixtures in
    assets/ are 1536x2752 = 0.5581 — the model's answer to a 9:16 request,
    frozen into the product and fed back in on every run.
    """

    ASSETS = ("assets/aesthetics", "assets")

    def _images(self):
        from pathlib import Path as _P

        seen = []
        for folder in self.ASSETS:
            for path in sorted(_P(folder).glob("*.png")):
                seen.append(path)
        return seen

    def test_there_are_assets_to_check(self) -> None:
        """Zero violations over zero checks is not a pass."""
        self.assertGreaterEqual(len(self._images()), 6)

    def test_every_shipped_asset_is_exactly_the_plan(self) -> None:
        from PIL import Image

        wrong = []
        for path in self._images():
            width, height = Image.open(path).size
            if not _exact(width, height):
                wrong.append(f"{path.name} {width}x{height} = {width / height:.4f}")
        self.assertEqual(
            wrong,
            [],
            f"{len(wrong)} shipped assets are not 9:16, and every run starts from them: {wrong}",
        )


if __name__ == "__main__":
    unittest.main()


class TheOutputCeilingHasAFloor(unittest.TestCase):
    """A ceiling on one side is not a clamp: the other side lets anything through.

    `OUT_RATIO_MAX = 1.0` refuses landscape, and nothing refused a frame
    narrower than the product's own plan. A 1:3 clip would have passed a gate
    written for vertical video, and the crop that follows would have taken 41%
    of its height — which is a head or a pair of feet, not a rounding.

    The floor is CHOSEN, and what it costs is derivable, which is why 0.5:
    cropping a 0.5 output to the plan's 0.5625 removes 11.1% of the height.
    Measured against every Kling output still on disk — 1.0000 x4, 0.7391 x3,
    0.5625 x8 — this floor refuses nothing that has ever arrived, so it is a
    guard against a shape we have not seen rather than a change of behaviour.
    """

    def test_the_floor_exists_and_sits_below_the_plan(self) -> None:
        self.assertTrue(hasattr(E, "OUT_RATIO_MIN"), "no floor is declared")
        self.assertLess(E.OUT_RATIO_MIN, P.PLAN_RATIO)
        self.assertLess(E.OUT_RATIO_MIN, E.OUT_RATIO_MAX)

    def test_a_frame_narrower_than_the_floor_is_a_defect(self) -> None:
        """The case nothing watched: too tall is as wrong as too wide."""
        self.assertLess(360 / 1280, E.OUT_RATIO_MIN)

    def test_every_ratio_ever_delivered_clears_the_floor(self) -> None:
        """The other side: a floor that refuses real deliveries is not a floor.

        MEASURED by ffprobe over every Kling output on disk, 2026-08-28.
        """
        for w, h in ((960, 960), (816, 1104), (576, 1024), (720, 1280)):
            with self.subTest(size=(w, h)):
                self.assertGreaterEqual(w / h, E.OUT_RATIO_MIN)
                self.assertLessEqual(w / h, E.OUT_RATIO_MAX)
