"""Pose arithmetic on synthetic skeletons, without MediaPipe.

`pose_delta` is declared an instrument in `pose.INSTRUMENTS`: no production path
calls it, and these tests are the reason it may stay. Until 2026-08-31 a second
implementation of the same quantity existed — `fork_looper.pose_gap`, which
normalised once per frame instead of once per call — and the two were held to
the same number on a fixture. The loop finder was deleted as a tool the product
does not run and the fast copy went with it, so the known answer `pose_delta` is
checked against is now arithmetic done on paper alone, below.

`read_pose` is the other half of this file: it is the reader every production
path uses to turn a frame into landmarks, and it moved here from the deleted
module because it wraps `landmarks` and nothing else.
"""

from __future__ import annotations

import unittest
from unittest import mock

try:
    import numpy as np  # noqa: F401

    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


def _skeleton(dx=0.0, dy=0.0, scale=1.0, **moved):
    """A plain standing skeleton, optionally shifted, resized, or bent."""
    base = {
        "l_shoulder": (0.45, 0.30),
        "r_shoulder": (0.55, 0.30),
        "l_elbow": (0.42, 0.40),
        "r_elbow": (0.58, 0.40),
        "l_wrist": (0.40, 0.50),
        "r_wrist": (0.60, 0.50),
        "l_hip": (0.46, 0.55),
        "r_hip": (0.54, 0.55),
        "l_knee": (0.45, 0.70),
        "r_knee": (0.55, 0.70),
        "l_ankle": (0.44, 0.85),
        "r_ankle": (0.56, 0.85),
    }
    out = {}
    for name, (x, y) in base.items():
        out[name] = ((x - 0.5) * scale + 0.5 + dx, (y - 0.5) * scale + 0.5 + dy, 1.0)
    for name, val in moved.items():
        out[name] = val if len(val) == 3 else (val[0], val[1], 1.0)
    return out


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed (live extra)")
class PoseDeltaAgreesWithArithmeticDoneOnPaper(unittest.TestCase):
    """The known answer: every expectation below is computed by hand."""

    def setUp(self):
        from lipsync import pose

        self.p = pose

    def test_one_joint_moved_by_a_known_amount_gives_the_hand_computed_number(self):
        # Shoulder centre (0.50, 0.30), hip centre (0.50, 0.55): torso = 0.25.
        # Moving one wrist 0.02 down is 0.02 / 0.25 = 0.08 torso-lengths, and
        # eleven joints of the twelve did not move: 0.08 / 12 = 0.006667.
        moved = _skeleton(l_wrist=(0.40, 0.52))
        got = self.p.pose_delta(_skeleton(), moved)
        self.assertAlmostEqual(got["worst"], 0.08, places=4)
        self.assertAlmostEqual(got["mean"], 0.0067, places=4)
        self.assertEqual(got["worst_joint"], "l_wrist")
        self.assertEqual(got["compared"], 12)

    def test_identical_poses_are_zero(self):
        got = self.p.pose_delta(_skeleton(), _skeleton())
        self.assertEqual(got["mean"], 0.0)
        self.assertEqual(got["worst"], 0.0)

    def test_moving_the_subject_across_frame_is_not_a_new_pose(self):
        got = self.p.pose_delta(_skeleton(), _skeleton(dx=0.2, dy=-0.1))
        self.assertEqual(got["mean"], 0.0)

    def test_framing_closer_is_not_a_new_pose(self):
        got = self.p.pose_delta(_skeleton(), _skeleton(scale=1.8))
        self.assertEqual(got["mean"], 0.0)

    def test_a_bent_arm_is_diluted_by_the_mean_but_caught_by_the_worst_joint(self):
        bent = _skeleton(l_wrist=(0.30, 0.28), l_elbow=(0.35, 0.34))
        got = self.p.pose_delta(_skeleton(), bent)
        self.assertAlmostEqual(got["mean"], 0.1113, places=4)
        self.assertAlmostEqual(got["worst"], 0.9666, places=4)
        self.assertEqual(got["worst_joint"], "l_wrist")
        self.assertGreater(
            got["worst"],
            got["mean"] * 8,
            "the mean over twelve joints is what hides a change confined to one",
        )


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed (live extra)")
class PoseDeltaSaysHowMuchItCouldNotSee(unittest.TestCase):
    """Three outcomes: a number, a number with coverage, or nothing at all."""

    def setUp(self):
        from lipsync import pose

        self.p = pose

    def test_invisible_joints_are_skipped_and_counted_not_scored(self):
        hidden_a = _skeleton(l_wrist=(0.40, 0.50, 0.1))
        hidden_b = _skeleton(l_wrist=(0.99, 0.99, 0.1))
        got = self.p.pose_delta(hidden_a, hidden_b)
        self.assertEqual(got["mean"], 0.0)
        self.assertEqual(got["compared"], 11)
        self.assertEqual(got["measurable"], 12)
        self.assertEqual(got["coverage"], 0.917)

    def test_a_pose_without_hips_cannot_be_normalised(self):
        no_hips = _skeleton(l_hip=(0.46, 0.55, 0.0), r_hip=(0.54, 0.55, 0.0))
        self.assertIsNone(self.p.pose_delta(_skeleton(), no_hips))

    def test_a_missing_pose_raises_rather_than_scoring_zero(self):
        with self.assertRaises(ValueError) as caught:
            self.p.pose_delta(None, _skeleton())
        self.assertIn("first", str(caught.exception))

    def test_the_refusal_names_a_cause_that_exists_in_this_product(self):
        """Regression: it used to send the reader to a sidecar file of another stack.

        The words themselves cannot be spelled here — a gate forbids them in
        this package — so the shape is checked instead: an operator following
        this message must not be sent to a file, and must be told what to do.
        """
        with self.assertRaises(ValueError) as caught:
            self.p.pose_delta(_skeleton(), None)
        text = str(caught.exception)
        self.assertIn("second", text)
        self.assertNotIn(".json", text)
        self.assertNotIn(".py", text)
        self.assertIn("Compare", text)


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed (live extra)")
class TheInstrumentCanSayNoAndCanSayYes(unittest.TestCase):
    """Negative control: a measure that answers the same on every input is not one."""

    def setUp(self):
        from lipsync import pose

        self.p = pose

    def test_three_different_pairs_give_three_different_numbers(self):
        base = _skeleton()
        means = [
            self.p.pose_delta(base, _skeleton(l_wrist=(0.40, 0.52)))["mean"],
            self.p.pose_delta(base, _skeleton(l_wrist=(0.40, 0.60)))["mean"],
            self.p.pose_delta(base, _skeleton(l_wrist=(0.40, 0.70)))["mean"],
        ]
        self.assertEqual(len(set(means)), 3, f"the measure did not move: {means}")
        self.assertEqual(means, sorted(means), f"further is not larger: {means}")

    def test_the_measure_is_silent_when_nothing_moved(self):
        self.assertEqual(self.p.pose_delta(_skeleton(), _skeleton())["mean"], 0.0)


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


class EvidenceMarkers(unittest.TestCase):
    """Negative control for the instrument the whole-evidence tests use."""

    def test_the_marker_check_notices_a_cut_at_either_end(self):
        self.assertGreater(len(LONG_EVIDENCE), 200)
        self.assertTrue(ends_kept(LONG_EVIDENCE))
        self.assertFalse(ends_kept(LONG_EVIDENCE[:200]), "a cut tail must be seen")
        self.assertFalse(ends_kept(LONG_EVIDENCE[-120:]), "a cut head must be seen")

    def test_a_short_reason_carries_neither_marker_and_the_check_stays_silent(self):
        self.assertFalse(ends_kept(SHORT_EVIDENCE))


class ReadPoseAnswersInThreeWays(unittest.TestCase):
    """A pose, no pose, or the reason there is none — never a silent empty."""

    def setUp(self):
        from lipsync import pose

        self.p = pose

    def test_the_points_the_detector_returned_are_what_comes_back(self):
        """The wiring: `read_pose` is `landmarks` plus an answer for failure."""
        points = _skeleton()
        with mock.patch.object(self.p, "landmarks", return_value=points):
            got = self.p.read_pose("frame.png")
        self.assertIs(got["points"], points)
        self.assertEqual(got["why"], "")

    def test_a_frame_with_no_body_is_not_a_failure(self):
        """None from the detector means 'nobody there', and carries no reason."""
        with mock.patch.object(self.p, "landmarks", return_value=None):
            got = self.p.read_pose("frame.png")
        self.assertIsNone(got["points"])
        self.assertEqual(got["why"], "")

    def test_a_pose_reader_crash_carries_the_whole_reason(self):
        """C2: the reason reaches the caller uncut, both ends of it."""
        with mock.patch.object(self.p, "landmarks", side_effect=RuntimeError(LONG_EVIDENCE)):
            got = self.p.read_pose("frame.png")
        self.assertIsNone(got["points"])
        self.assertTrue(ends_kept(got["why"]), got["why"])

    def test_a_short_pose_reader_crash_arrives_unchanged(self):
        with mock.patch.object(self.p, "landmarks", side_effect=RuntimeError(SHORT_EVIDENCE)):
            got = self.p.read_pose("frame.png")
        self.assertTrue(got["why"].endswith(SHORT_EVIDENCE), got["why"])

    def test_the_crash_is_named_and_not_only_described(self):
        """The type is part of the evidence: `ImportError` and `OSError` differ."""
        with mock.patch.object(self.p, "landmarks", side_effect=ImportError("mediapipe")):
            got = self.p.read_pose("frame.png")
        self.assertEqual(got["why"], "ImportError: mediapipe")


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed (live extra)")
class TheInstrumentDeclarationMatchesWhatIsHere(unittest.TestCase):
    def test_pose_delta_is_the_one_declared_instrument(self):
        from lipsync import pose

        self.assertEqual(pose.INSTRUMENTS, ("pose_delta",))

    def test_the_measures_of_the_local_sampling_era_are_gone(self):
        """They judged a clip after sampling it; the product never sees that moment."""
        from lipsync import pose

        for name in ("pose_drift", "limb_consistency", "world_proportions", "pose_distance"):
            self.assertFalse(hasattr(pose, name), f"{name} is back")

    def test_the_second_implementation_of_pose_delta_did_not_move_in_here(self):
        """`pose_gap` was the loop finder's copy of this quantity and went with it.

        Keeping it would mean two ways to compute one number with no production
        caller for either, which is the duplicate `pose_delta` was documented as
        NOT being.
        """
        from lipsync import pose

        self.assertFalse(hasattr(pose, "pose_gap"), "pose_gap is back")


if __name__ == "__main__":
    unittest.main()
