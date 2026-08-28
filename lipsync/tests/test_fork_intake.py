"""Guard the input intake. Every test catches a defect, not a line."""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from lipsync import fork_intake as fi
from lipsync.fork_identity import FAIL, PASS, UNMEASURED

# C2: evidence is not truncated. Markers sit at BOTH ends because `[:N]` cuts
# the tail and `[-N:]` cuts the head — a test with one marker passes on half
# the defects, which is how the last cut here survived a green suite.
EVIDENCE_HEAD = "HEADMARK_e3f1"
EVIDENCE_TAIL = "TAILMARK_9b27"
LONG_EVIDENCE = EVIDENCE_HEAD + " " + ("filler " * 90) + EVIDENCE_TAIL
SHORT_EVIDENCE = "no such file"


def ends_kept(text: str) -> bool:
    """Return True when both ends of `LONG_EVIDENCE` survived into `text`."""
    return EVIDENCE_HEAD in str(text) and EVIDENCE_TAIL in str(text)


PROBE_JSON = (
    '{"programs":[],"streams":[{"avg_frame_rate":"30/1",'
    '"duration":"10.166667","nb_read_frames":"305"}]}'
)

FFMPEG_STATS = (
    "frame=    0 fps=0.0 q=-0.0 size=       0kB time=00:00:00.00 "
    "bitrate=N/A speed=   0x    \rframe=  307 fps=0.0 q=-0.0 "
    "Lsize=N/A time=00:00:10.20 bitrate=N/A speed=37.6x    "
)


def probe_stub(text=PROBE_JSON, ran=True, why=""):
    def prober(path):
        return {"ran": ran, "code": 0, "out": text, "err": "", "why": why}

    return prober


def decode_stub(plain: int, fixed: int):
    def decoder(path, *, vsync0):
        n = fixed if vsync0 else plain
        return {
            "ran": True,
            "code": 0,
            "out": "",
            "err": f"frame=    0 ...\rframe= {n} Lsize=N/A",
            "why": "",
        }

    return decoder


def pose_point(x, y, vis):
    return (x, y, vis)


CLEAN_POSE = {
    "l_shoulder": pose_point(0.4, 0.3, 0.9),
    "r_shoulder": pose_point(0.6, 0.3, 0.9),
    "l_elbow": pose_point(0.35, 0.5, 0.9),
    "r_elbow": pose_point(0.65, 0.5, 0.9),
    "l_wrist": pose_point(0.3, 0.7, 0.9),
    "r_wrist": pose_point(0.7, 0.7, 0.9),
}

ORPHAN_POSE = {**CLEAN_POSE, "l_elbow": pose_point(0.35, 0.5, 0.2)}


class Timestamps(unittest.TestCase):
    def test_the_selfie_numbers_are_called_a_defect(self):
        """MEASURED on driving_selfie: 305 / 307 / 305. That is a "fail"."""
        v = fi.timestamp_verdict(305, 307, 305)
        self.assertEqual(v["outcome"], "fail")
        self.assertEqual((v["checked"], v["violations"], v["unmeasured"]), (1, 1, 0))
        self.assertEqual(v["gap"], 2)
        self.assertIn("-vsync 0", v["advice"])

    def test_the_arms_numbers_are_clean(self):
        """Run the instrument's negative control: it stays silent on a healthy file."""
        v = fi.timestamp_verdict(373, 373, 373)
        self.assertEqual(v["outcome"], "pass")
        self.assertEqual(v["violations"], 0)
        self.assertEqual(v["advice"], "")

    def test_a_missing_counter_is_the_third_outcome(self):
        for probed, plain, fixed in ((None, 307, 305), (305, None, 305), (305, 307, None)):
            with self.subTest(triple=(probed, plain, fixed)):
                v = fi.timestamp_verdict(probed, plain, fixed)
                self.assertEqual(v["outcome"], "could not measure")
                self.assertEqual(v["checked"], 0)
                self.assertEqual(v["violations"], 0)

    def test_vsync_that_does_not_heal_is_said_out_loud(self):
        v = fi.timestamp_verdict(305, 307, 306)
        self.assertEqual(v["outcome"], "fail")
        self.assertIn("does not heal", v["note"])

    def test_mutating_the_tolerance_both_ways_turns_a_verdict(self):
        """FRAME_COUNT_EXACT is guarded in both directions."""
        was = fi.FRAME_COUNT_EXACT
        try:
            fi.FRAME_COUNT_EXACT = 2
            self.assertEqual(
                fi.timestamp_verdict(305, 307, 305)["outcome"],
                "pass",
                "a tolerance of 2 must let the defect through",
            )
            fi.FRAME_COUNT_EXACT = -1
            self.assertEqual(
                fi.timestamp_verdict(373, 373, 373)["outcome"],
                "fail",
                "a negative tolerance must sink even an exact match",
            )
        finally:
            fi.FRAME_COUNT_EXACT = was
        self.assertEqual(fi.FRAME_COUNT_EXACT, 0)


class ParsingTheInstruments(unittest.TestCase):
    def test_count_frames_json_is_parsed_from_a_recorded_answer(self):
        r = fi.parse_count_frames(PROBE_JSON)
        self.assertTrue(r["ok"])
        self.assertEqual(r["frames"], 305)
        self.assertEqual(r["fps"], 30.0)

    def test_garbage_is_not_a_frame_count(self):
        """Run the parser's negative control: garbage must give "could not"."""
        for text in (
            "",
            "not json",
            "{}",
            '{"streams":[{}]}',
            '{"streams":[{"nb_read_frames":"N/A"}]}',
            '{"streams":[{"nb_read_frames":"0"}]}',
        ):
            with self.subTest(text=text):
                r = fi.parse_count_frames(text)
                self.assertFalse(r["ok"])
                self.assertIsNone(r["frames"])
                self.assertTrue(r["why"])

    def test_the_last_frame_number_wins_not_the_first(self):
        """The defect this test was written for: the first hit is `frame= 0`."""
        r = fi.parse_decoded_frames(FFMPEG_STATS)
        self.assertTrue(r["ok"])
        self.assertEqual(r["frames"], 307)

    def test_stats_without_a_frame_line_is_unmeasured(self):
        r = fi.parse_decoded_frames("Output file is empty, nothing was encoded")
        self.assertFalse(r["ok"])
        self.assertIsNone(r["frames"])


class Scenes(unittest.TestCase):
    def test_no_cuts_is_one_scene_over_the_whole_clip(self):
        self.assertEqual(fi.scenes(373, []), [{"start": 0, "end": 372, "frames": 373}])

    def test_a_cut_after_frame_k_splits_between_k_and_k_plus_one(self):
        self.assertEqual(
            fi.scenes(10, [3]),
            [{"start": 0, "end": 3, "frames": 4}, {"start": 4, "end": 9, "frames": 6}],
        )

    def test_two_cuts_give_three_scenes_and_the_frames_add_up(self):
        got = fi.scenes(100, [29, 59])
        self.assertEqual([s["frames"] for s in got], [30, 30, 40])
        self.assertEqual(sum(s["frames"] for s in got), 100)

    def test_scene_shorter_than_three_seconds_is_refused(self):
        """An acceptance criterion. 89 frames at 30 fps is 2.967 s."""
        v = fi.scene_length_verdict(fi.scenes(200, [88]), 30.0)
        self.assertEqual(v["outcome"], "fail")
        self.assertEqual(v["short"], [0])
        self.assertEqual(v["seconds"][0], 2.967)
        self.assertEqual((v["checked"], v["violations"]), (2, 1))

    def test_exactly_three_seconds_passes(self):
        """The boundary is inclusive: 90 frames at 30 fps is exactly 3.0 s."""
        v = fi.scene_length_verdict(fi.scenes(200, [89]), 30.0)
        self.assertEqual(v["outcome"], "pass")
        self.assertEqual(v["seconds"][0], 3.0)

    def test_without_fps_the_length_is_the_third_outcome(self):
        v = fi.scene_length_verdict(fi.scenes(200, [88]), None)
        self.assertEqual(v["outcome"], "could not measure")
        self.assertEqual(v["checked"], 0)
        self.assertEqual(v["violations"], 0)
        v0 = fi.scene_length_verdict(fi.scenes(200, [88]), 0)
        self.assertEqual(v0["outcome"], "could not measure")

    def test_mutating_the_scene_bar_both_ways_turns_the_verdict(self):
        """MIN_SCENE_SECONDS is guarded stricter and looser."""
        scene_list = fi.scenes(200, [89])
        self.assertEqual(
            fi.scene_length_verdict(scene_list, 30.0, min_seconds=3.5)["outcome"], "fail"
        )
        self.assertEqual(
            fi.scene_length_verdict(scene_list, 30.0, min_seconds=2.5)["outcome"], "pass"
        )
        was = fi.MIN_SCENE_SECONDS
        try:
            fi.MIN_SCENE_SECONDS = 3.5
            self.assertEqual(
                fi.scene_length_verdict(scene_list, 30.0)["outcome"],
                "fail",
                "swapping the constant itself must turn the verdict, not only the parameter",
            )
            fi.MIN_SCENE_SECONDS = 2.5
            self.assertEqual(fi.scene_length_verdict(scene_list, 30.0)["outcome"], "pass")
        finally:
            fi.MIN_SCENE_SECONDS = was
        self.assertEqual(fi.MIN_SCENE_SECONDS, 3.0)

    def test_the_bar_is_the_owners_three_seconds(self):
        self.assertEqual(fi.MIN_SCENE_SECONDS, 3.0)


class OrphanWrists(unittest.TestCase):
    def test_a_visible_wrist_without_its_elbow_is_an_orphan(self):
        self.assertIs(fi.is_orphan_wrist(ORPHAN_POSE), True)

    def test_a_whole_arm_is_not_an_orphan(self):
        """Run the negative control: an instrument that always cries measures nothing."""
        self.assertIs(fi.is_orphan_wrist(CLEAN_POSE), False)

    def test_an_invisible_wrist_is_not_an_orphan(self):
        """An orphan is about a visible wrist. An invisible wrist is not a violation."""
        pts = {
            **CLEAN_POSE,
            "l_wrist": pose_point(0.3, 0.7, 0.1),
            "l_elbow": pose_point(0.35, 0.5, 0.1),
        }
        self.assertIs(fi.is_orphan_wrist(pts), False)

    def test_a_wrist_outside_the_frame_is_not_counted(self):
        pts = {
            **CLEAN_POSE,
            "l_wrist": pose_point(1.4, 0.7, 0.9),
            "l_elbow": pose_point(0.35, 0.5, 0.1),
        }
        self.assertIs(fi.is_orphan_wrist(pts), False)

    def test_a_missing_shoulder_orphans_the_wrist_too(self):
        pts = {**CLEAN_POSE, "r_shoulder": pose_point(0.6, 0.3, 0.2)}
        self.assertIs(fi.is_orphan_wrist(pts), True)

    def test_no_pose_is_the_third_outcome_not_false(self):
        self.assertIsNone(fi.is_orphan_wrist(None))
        self.assertIsNone(fi.is_orphan_wrist({}))

    def test_mutating_visibility_both_ways_changes_who_is_an_orphan(self):
        """MIN_VISIBILITY is guarded in both directions."""
        was = fi.MIN_VISIBILITY
        try:
            fi.MIN_VISIBILITY = 0.1
            self.assertIs(
                fi.is_orphan_wrist(ORPHAN_POSE),
                False,
                "a loose bar must stop seeing the orphan",
            )
            fi.MIN_VISIBILITY = 0.95
            self.assertIs(
                fi.is_orphan_wrist(ORPHAN_POSE),
                False,
                "a strict bar must put out the wrist as well",
            )
        finally:
            fi.MIN_VISIBILITY = was
        self.assertEqual(fi.MIN_VISIBILITY, 0.5)

    def test_the_soft_axis_never_says_not_good(self):
        """The key property of this axis: it is not a refusal criterion."""
        for share in (0.0, 0.04, 0.21, 0.99, 1.0):
            with self.subTest(share=share):
                v = fi.orphan_verdict(share, 100, 0)
                self.assertNotEqual(v["outcome"], "fail")
                self.assertEqual(v["violations"], 0)

    def test_the_measured_share_warns_and_a_small_one_does_not(self):
        self.assertTrue(fi.orphan_verdict(0.21, 99, 0)["warn"])
        self.assertFalse(fi.orphan_verdict(0.04, 373, 0)["warn"])

    def test_mutating_the_warning_bar_both_ways_turns_the_warning(self):
        """ORPHAN_WRIST_WARN, stricter and looser, on the MEASURED points 4% and 21%."""
        was = fi.ORPHAN_WRIST_WARN
        try:
            fi.ORPHAN_WRIST_WARN = 0.30
            self.assertFalse(
                fi.orphan_verdict(0.21, 99, 0)["warn"],
                "a 30% bar must lift the warning off 21%",
            )
            fi.ORPHAN_WRIST_WARN = 0.01
            self.assertTrue(
                fi.orphan_verdict(0.04, 373, 0)["warn"],
                "a 1% bar must raise the warning on 4%",
            )
        finally:
            fi.ORPHAN_WRIST_WARN = was
        self.assertEqual(fi.ORPHAN_WRIST_WARN, 0.10)

    def test_no_pose_anywhere_is_unmeasured_not_zero_orphans(self):
        v = fi.orphan_verdict(None, 0, 12)
        self.assertEqual(v["outcome"], "could not measure")
        self.assertIsNone(v["share"])
        self.assertFalse(v["warn"])


class FaceSize(unittest.TestCase):
    def test_the_selfie_range_passes_the_bar(self):
        """MEASURED: driving_selfie 234..369 px — the bar does not get in the way."""
        v = fi.face_size_verdict([234, 300, 369], 0, 0)
        self.assertEqual(v["outcome"], "pass")
        self.assertEqual((v["checked"], v["violations"]), (3, 0))

    def test_the_yogaball_range_is_counted_but_no_longer_sinks_the_run(self):
        """Rewritten for the template author's decision: this axis is a warning."""
        v = fi.face_size_verdict([87, 90, 96], 0, 0)
        self.assertEqual(v["outcome"], "pass")
        self.assertEqual(v["small"], 3)
        self.assertEqual(v["hurt"], 3)
        self.assertIn("warning", v["note"])
        self.assertIn("operator", v["note"])

    def test_a_frame_without_a_face_is_counted_not_excused(self):
        v = fi.face_size_verdict([234], 5, 0)
        self.assertEqual(v["outcome"], "pass")
        self.assertEqual(v["hurt"], 5)
        self.assertEqual(v["no_face"], 5)
        self.assertIn("warning", v["note"])

    def test_a_clean_set_gets_NO_warning(self):
        v = fi.face_size_verdict([234, 369], 0, 0)
        self.assertEqual(v["outcome"], "pass")
        self.assertEqual(v["hurt"], 0)
        self.assertNotIn("warning", v["note"])

    def test_a_detector_that_could_not_be_asked_is_the_third_outcome(self):
        v = fi.face_size_verdict([], 0, 7)
        self.assertEqual(v["outcome"], "could not measure")
        self.assertEqual(v["checked"], 0)
        self.assertEqual(v["violations"], 0)

    def test_mutating_the_face_bar_both_ways_moves_the_counted_numbers(self):
        """MIN_FACE_PX stricter and looser. The verdict no longer moves."""
        loose = fi.face_size_verdict([87, 96], 0, 0, min_face_px=80)
        self.assertEqual(loose["small"], 0)
        self.assertNotIn("warning", loose["note"])
        strict = fi.face_size_verdict([234, 369], 0, 0, min_face_px=400)
        self.assertEqual(strict["small"], 2)
        self.assertIn("warning", strict["note"])
        was = fi.MIN_FACE_PX
        try:
            fi.MIN_FACE_PX = 80
            self.assertEqual(fi.face_size_verdict([87, 96], 0, 0)["hurt"], 0)
            fi.MIN_FACE_PX = 400
            self.assertEqual(fi.face_size_verdict([234, 369], 0, 0)["hurt"], 2)
        finally:
            fi.MIN_FACE_PX = was
        self.assertEqual(fi.MIN_FACE_PX, 100)


class Window(unittest.TestCase):
    def test_the_window_is_in_frame_numbers_and_sits_in_the_middle(self):
        scene_list = [{"start": 0, "end": 199, "frames": 200}]
        v = fi.window(scene_list, 5.0, 30.0)
        self.assertEqual(v["outcome"], "pass")
        self.assertEqual((v["start"], v["end"], v["frames"]), (25, 174, 150))
        self.assertEqual(v["scene"], 0)

    def test_the_longest_scene_wins(self):
        scene_list = [
            {"start": 0, "end": 99, "frames": 100},
            {"start": 100, "end": 399, "frames": 300},
        ]
        v = fi.window(scene_list, 5.0, 30.0)
        self.assertEqual(v["scene"], 1)
        self.assertEqual((v["start"], v["end"]), (175, 324))

    def test_a_window_that_does_not_fit_is_refused_not_shrunk(self):
        scene_list = [{"start": 0, "end": 89, "frames": 90}]
        v = fi.window(scene_list, 5.0, 30.0)
        self.assertEqual(v["outcome"], "fail")
        self.assertIsNone(v["start"])
        self.assertEqual(v["violations"], 1)

    def test_without_fps_the_window_is_unmeasured_not_thirty(self):
        v = fi.window([{"start": 0, "end": 199, "frames": 200}], 5.0, None)
        self.assertEqual(v["outcome"], "could not measure")
        self.assertIsNone(v["start"])

    def test_without_a_markup_the_window_is_unmeasured(self):
        v = fi.window([], 5.0, 30.0)
        self.assertEqual(v["outcome"], "could not measure")


class ThreeOutcomesAndThreeNumbers(unittest.TestCase):
    def test_zero_violations_over_zero_checks_is_not_success(self):
        """Verbatim: zero violations over zero checks is not a "pass"."""
        self.assertEqual(fi.tally(0, 0, 0)["outcome"], "could not measure")

    def test_a_partly_measured_run_does_not_round_up_to_good(self):
        self.assertEqual(fi.tally(10, 0, 3)["outcome"], "could not measure")

    def test_a_violation_beats_an_unmeasured(self):
        self.assertEqual(fi.tally(10, 1, 3)["outcome"], "fail")

    def test_a_clean_full_run_is_good(self):
        self.assertEqual(fi.tally(10, 0, 0)["outcome"], "pass")

    def test_the_three_outcomes_are_the_projects_three(self):
        self.assertEqual((PASS, FAIL, UNMEASURED), ("pass", "fail", "could not measure"))


class DrivingIntake(unittest.TestCase):
    def _run(self, *, plain, fixed, poses, faces, n=95, cut_at=None, product=None):
        paths = [f"{i:05d}.png" for i in range(n)]
        cut_at = [] if cut_at is None else cut_at

        def gray(path):
            import numpy as np

            k = int(str(path).split(".")[0])
            base = sum(100 for c in cut_at if k > c) + k
            return np.full((4, 4), float(base))

        def pose_reader(path):
            return {"points": poses.get(str(path), CLEAN_POSE), "why": "", "people": None}

        def face_prober(path):
            return faces.get(str(path), {"face_px": 300})

        return fi.driving_intake(
            "clip.mp4",
            paths,
            product_seconds=product,
            prober=probe_stub(),
            decoder=decode_stub(plain, fixed),
            gray=gray,
            pose_reader=pose_reader,
            face_prober=face_prober,
        )

    def test_the_intake_reports_six_axes_of_which_two_are_soft(self):
        """The docstring said five axes and one soft while the code ran six and two."""
        r = self._run(plain=305, fixed=305, poses={}, faces={})
        self.assertEqual(
            sorted(r["axes"]),
            ["cuts", "face_size", "orphan_wrists", "scenes", "timestamps", "window"],
        )
        self.assertEqual(sorted(r["soft"]), ["orphan_wrists", "window"])

    def test_a_clean_clip_passes_and_the_soft_axis_is_outside_the_verdict(self):
        r = self._run(plain=305, fixed=305, poses={"00002.png": ORPHAN_POSE}, faces={})
        self.assertEqual(r["axes"]["timestamps"]["outcome"], "pass")
        self.assertEqual(r["axes"]["orphan_wrists"]["outcome"], "pass")
        self.assertGreater(r["axes"]["orphan_wrists"]["share"], 0.0)
        self.assertIn("orphan_wrists", r["soft"])
        self.assertEqual(r["outcome"], "pass")

    def test_the_timestamp_defect_alone_sinks_the_verdict(self):
        r = self._run(plain=307, fixed=305, poses={}, faces={})
        self.assertEqual(r["axes"]["timestamps"]["outcome"], "fail")
        self.assertEqual(r["outcome"], "fail")
        self.assertIn("-vsync 0", r["axes"]["timestamps"]["note"])

    def test_orphan_wrists_alone_never_sink_the_verdict(self):
        """Guard the template author's decision: 100% orphans is a warning, not a refusal."""
        r = self._run(
            plain=305, fixed=305, poses={f"{i:05d}.png": ORPHAN_POSE for i in range(95)}, faces={}
        )
        self.assertEqual(r["axes"]["orphan_wrists"]["share"], 1.0)
        self.assertTrue(r["axes"]["orphan_wrists"]["warn"])
        self.assertEqual(r["outcome"], "pass")
        self.assertIn("orphan_wrists", r["warnings"])

    def test_small_faces_warn_but_no_longer_sink_the_run(self):
        r = self._run(
            plain=305,
            fixed=305,
            poses={},
            faces={f"{i:05d}.png": {"face_px": 90} for i in range(95)},
        )
        self.assertEqual(r["axes"]["face_size"]["outcome"], "pass")
        self.assertEqual(r["axes"]["face_size"]["small"], 95)
        self.assertIn("warning", r["axes"]["face_size"]["note"])

    def test_a_cut_is_marked_up_and_short_scenes_are_refused(self):
        r = self._run(plain=305, fixed=305, poses={}, faces={}, n=6, cut_at=[2])
        self.assertEqual(r["axes"]["cuts"]["cuts"], [2])
        self.assertEqual([s["frames"] for s in r["scenes"]], [3, 3])
        self.assertEqual(r["axes"]["scenes"]["outcome"], "fail")
        self.assertEqual(r["axes"]["scenes"]["short"], [0, 1])

    def test_without_frames_the_frame_axes_are_unmeasured_not_clean(self):
        """No frames means "could not", not "no seams, no orphans"."""
        r = fi.driving_intake("clip.mp4", [], prober=probe_stub(), decoder=decode_stub(305, 305))
        for axis in ("cuts", "scenes", "orphan_wrists", "face_size"):
            with self.subTest(axis=axis):
                self.assertEqual(r["axes"][axis]["outcome"], "could not measure")
        self.assertEqual(r["axes"]["timestamps"]["outcome"], "pass")
        self.assertEqual(r["outcome"], "could not measure")

    def test_a_dead_prober_does_not_become_a_bad_file(self):
        def dead(path):
            return {"ran": False, "code": None, "out": "", "err": "", "why": "ffprobe not found"}

        r = fi.driving_intake("clip.mp4", [], prober=dead, decoder=decode_stub(305, 305))
        self.assertEqual(r["axes"]["timestamps"]["outcome"], "could not measure")
        self.assertNotEqual(r["axes"]["timestamps"]["outcome"], "fail")


class PhotoIntake(unittest.TestCase):
    def test_one_big_face_passes(self):
        r = fi.photo_intake(
            "p.png",
            faces_prober=lambda p: {"faces": [{"face_px": 420, "det_score": 0.9}], "why": ""},
        )
        self.assertEqual(r["outcome"], "pass")
        self.assertEqual(r["axes"]["face_size"]["face_px"], 420)

    def test_no_face_is_a_violation_and_not_the_third_outcome(self):
        r = fi.photo_intake("p.png", faces_prober=lambda p: {"faces": [], "why": ""})
        self.assertEqual(r["axes"]["face_found"]["outcome"], "fail")
        self.assertEqual(r["axes"]["face_size"]["outcome"], "could not measure")
        self.assertEqual(r["outcome"], "fail")

    def test_two_people_are_refused(self):
        r = fi.photo_intake(
            "p.png",
            faces_prober=lambda p: {
                "faces": [{"face_px": 420, "det_score": 0.9}, {"face_px": 200, "det_score": 0.8}],
                "why": "",
            },
        )
        self.assertEqual(r["axes"]["one_person"]["outcome"], "fail")
        self.assertEqual(r["axes"]["face_found"]["outcome"], "pass")
        self.assertEqual(r["outcome"], "fail")

    def test_a_small_face_is_refused(self):
        r = fi.photo_intake(
            "p.png",
            faces_prober=lambda p: {"faces": [{"face_px": 60, "det_score": 0.9}], "why": ""},
        )
        self.assertEqual(r["axes"]["face_size"]["outcome"], "fail")

    def test_a_dead_detector_is_the_third_outcome_on_every_axis(self):
        r = fi.photo_intake(
            "p.png",
            faces_prober=lambda p: {"faces": None, "why": "ModuleNotFoundError: insightface"},
        )
        for axis in ("face_found", "face_size", "one_person"):
            with self.subTest(axis=axis):
                self.assertEqual(r["axes"][axis]["outcome"], "could not measure")
        self.assertEqual(r["outcome"], "could not measure")

    def test_mutating_the_expected_head_count_both_ways(self):
        """PHOTO_PEOPLE_EXPECTED stricter and looser."""
        two = lambda p: {
            "faces": [{"face_px": 420}, {"face_px": 200}],  # noqa: E731
            "why": "",
        }
        one = lambda p: {"faces": [{"face_px": 420}], "why": ""}  # noqa: E731
        was = fi.PHOTO_PEOPLE_EXPECTED
        try:
            fi.PHOTO_PEOPLE_EXPECTED = 2
            self.assertEqual(
                fi.photo_intake("p.png", faces_prober=two)["axes"]["one_person"]["outcome"], "pass"
            )
            self.assertEqual(
                fi.photo_intake("p.png", faces_prober=one)["axes"]["one_person"]["outcome"],
                "fail",
            )
        finally:
            fi.PHOTO_PEOPLE_EXPECTED = was
        self.assertEqual(fi.PHOTO_PEOPLE_EXPECTED, 1)


class StyleIntake(unittest.TestCase):
    GOOD = {
        "colours": ["off white", "steel blue"],
        "value_key": "light",
        "saturation": "muted",
        "texture": "visible grain",
    }

    def test_a_full_card_passes(self):
        r = fi.style_intake("s.png", card_reader=lambda p: {"card": dict(self.GOOD), "why": ""})
        self.assertEqual(r["outcome"], "pass")
        self.assertEqual(r["axes"]["card_readable"]["missing"], [])
        self.assertEqual(r["checked"], 4)

    def test_an_empty_field_is_a_violation(self):
        card = {**self.GOOD, "texture": ""}
        r = fi.style_intake("s.png", card_reader=lambda p: {"card": card, "why": ""})
        self.assertEqual(r["outcome"], "fail")
        self.assertEqual(r["axes"]["card_readable"]["missing"], ["texture"])

    def test_a_missing_package_is_the_third_outcome(self):
        """A missing package is not "the style is bad"."""
        r = fi.style_intake(
            "s.png",
            card_reader=lambda p: {"card": None, "why": "ModuleNotFoundError: creative_eval"},
        )
        self.assertEqual(r["outcome"], "could not measure")
        self.assertEqual(r["violations"], 0)

    def test_the_expected_fields_are_a_literal_here(self):
        """The field list is written here by hand and is not imported."""
        r = fi.style_intake(
            "s.png", card_reader=lambda p: {"card": {"colours": ["red"]}, "why": ""}
        )
        self.assertEqual(
            r["axes"]["card_readable"]["missing"], ["value_key", "saturation", "texture"]
        )


class BarsAreImportedNotCopied(unittest.TestCase):
    """The bar lives in one place, and here there is only a reference to it."""

    def test_the_person_bar_is_the_one_from_fork_identity(self):
        from lipsync import fork_identity

        self.assertIs(fi.SAME_PERSON_MAX, fork_identity.SAME_PERSON_MAX)
        self.assertEqual(fi.SAME_PERSON_MAX, 0.35)

    def test_the_cut_bar_is_the_one_from_fork_looper(self):
        from lipsync import fork_looper

        self.assertIs(fi.CUT_JUMP, fork_looper.CUT_JUMP)
        self.assertEqual(fi.CUT_JUMP, 4.0)

    def test_the_visibility_bar_is_the_one_from_pose(self):
        from lipsync import pose

        self.assertIs(fi.MIN_VISIBILITY, pose.MIN_VISIBILITY)
        self.assertEqual(fi.MIN_VISIBILITY, 0.5)

    def test_the_face_bar_is_the_one_the_identity_axis_uses(self):
        from lipsync import identity_arcface

        self.assertIs(fi.MIN_FACE_PX, identity_arcface.MIN_FACE_PX)
        self.assertEqual(fi.MIN_FACE_PX, 100)

    def test_the_module_does_not_redefine_a_bar_it_borrowed(self):
        """Guard the defect: a copy of the bar as a number in the module text."""
        import ast
        from pathlib import Path

        src = Path(fi.__file__).read_text(encoding="utf-8")
        borrowed = {"SAME_PERSON_MAX", "CUT_JUMP", "MIN_VISIBILITY", "MIN_FACE_PX"}
        offenders = []
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id in borrowed:
                        offenders.append(t.id)
        self.assertEqual(offenders, [], f"bars redefined in the module: {offenders}")


class EveryInjectionPointIsAParameter(unittest.TestCase):
    """Enforced by construction: the test walks only through parameters."""

    def test_the_public_instruments_all_take_their_world_as_an_argument(self):
        import inspect

        expected = {
            "driving_intake": {"prober", "decoder", "gray", "pose_reader", "face_prober"},
            "photo_intake": {"faces_prober"},
            "style_intake": {"card_reader"},
        }
        for name, points in expected.items():
            with self.subTest(fn=name):
                params = set(inspect.signature(getattr(fi, name)).parameters)
                self.assertTrue(
                    points <= params,
                    f"{name}: missing injection points {sorted(points - params)}",
                )

    def test_the_default_style_reader_does_not_import_the_banned_name(self):
        """The gate stands on the name `style`, and it must be passed honestly."""
        import ast
        from pathlib import Path

        for node in ast.walk(ast.parse(Path(fi.__file__).read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "style")
                for a in node.names:
                    self.assertNotEqual(a.name, "style")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    self.assertFalse(a.name == "style" or a.name.endswith(".style"))


if __name__ == "__main__":
    unittest.main()


class EvidenceMarkers(unittest.TestCase):
    """Negative control for the instrument the whole-evidence tests use."""

    def test_the_marker_check_notices_a_cut_at_either_end(self):
        self.assertGreater(len(LONG_EVIDENCE), 200)
        self.assertTrue(ends_kept(LONG_EVIDENCE))
        self.assertFalse(ends_kept(LONG_EVIDENCE[:200]), "a cut tail must be seen")
        self.assertFalse(ends_kept(LONG_EVIDENCE[-120:]), "a cut head must be seen")

    def test_a_short_reason_carries_neither_marker_and_the_check_stays_silent(self):
        self.assertFalse(ends_kept(SHORT_EVIDENCE))


def _fake_style_module(text):
    """Return sys.modules entries whose `style_card` raises `text`."""

    def style_card(path):
        raise RuntimeError(text)

    mod = types.ModuleType("creative_eval.style")
    mod.style_card = style_card
    pkg = types.ModuleType("creative_eval")
    pkg.style = mod
    return {"creative_eval": pkg, "creative_eval.style": mod}


class WholeEvidence(unittest.TestCase):
    """C2: what the outside world said reaches the report head and tail."""

    def _launch_failure(self, fn, text, **kw):
        with (
            mock.patch.object(fi.shutil, "which", return_value="/usr/bin/ff"),
            mock.patch.object(fi.subprocess, "run", side_effect=OSError(text)),
        ):
            return fn("driving.mp4", **kw)

    def test_a_ffprobe_launch_failure_carries_the_whole_reason(self):
        got = self._launch_failure(fi.read_count_frames, LONG_EVIDENCE)
        self.assertFalse(got["ran"])
        self.assertTrue(ends_kept(got["why"]), got["why"])

    def test_a_short_ffprobe_launch_failure_arrives_unchanged(self):
        got = self._launch_failure(fi.read_count_frames, SHORT_EVIDENCE)
        self.assertTrue(got["why"].endswith(SHORT_EVIDENCE), got["why"])

    def test_a_ffmpeg_launch_failure_carries_the_whole_reason(self):
        got = self._launch_failure(fi.read_decoded_frames, LONG_EVIDENCE, vsync0=True)
        self.assertFalse(got["ran"])
        self.assertTrue(ends_kept(got["why"]), got["why"])

    def test_a_short_ffmpeg_launch_failure_arrives_unchanged(self):
        got = self._launch_failure(fi.read_decoded_frames, SHORT_EVIDENCE, vsync0=True)
        self.assertTrue(got["why"].endswith(SHORT_EVIDENCE), got["why"])

    def test_a_face_reader_crash_carries_the_whole_reason(self):
        from lipsync import identity_arcface

        with mock.patch.object(
            identity_arcface, "_analyzer", side_effect=RuntimeError(LONG_EVIDENCE)
        ):
            got = fi.read_faces("photo.png")
        self.assertIsNone(got["faces"])
        self.assertTrue(ends_kept(got["why"]), got["why"])

    def test_a_short_face_reader_crash_arrives_unchanged(self):
        from lipsync import identity_arcface

        with mock.patch.object(
            identity_arcface, "_analyzer", side_effect=RuntimeError(SHORT_EVIDENCE)
        ):
            got = fi.read_faces("photo.png")
        self.assertTrue(got["why"].endswith(SHORT_EVIDENCE), got["why"])

    def test_a_style_card_crash_carries_the_whole_reason(self):
        with mock.patch.dict(sys.modules, _fake_style_module(LONG_EVIDENCE)):
            got = fi.read_style_card("ref.png")
        self.assertIsNone(got["card"])
        self.assertTrue(ends_kept(got["why"]), got["why"])

    def test_a_short_style_card_crash_arrives_unchanged(self):
        with mock.patch.dict(sys.modules, _fake_style_module(SHORT_EVIDENCE)):
            got = fi.read_style_card("ref.png")
        self.assertTrue(got["why"].endswith(SHORT_EVIDENCE), got["why"])

    def test_an_unparsable_ffprobe_answer_is_quoted_whole(self):
        got = fi.parse_count_frames(LONG_EVIDENCE)
        self.assertFalse(got["ok"])
        self.assertTrue(ends_kept(got["why"]), got["why"])

    def test_a_short_unparsable_ffprobe_answer_is_quoted_whole(self):
        got = fi.parse_count_frames(SHORT_EVIDENCE)
        self.assertIn(SHORT_EVIDENCE, got["why"])

    def test_a_ffmpeg_answer_without_a_frame_line_is_quoted_from_its_head(self):
        # This one was cut with `[-120:]`: the HEAD was the missing end, and a
        # test that plants its marker in the tail passes on the defect.
        got = fi.parse_decoded_frames(LONG_EVIDENCE)
        self.assertFalse(got["ok"])
        self.assertTrue(ends_kept(got["why"]), got["why"])

    def test_a_short_ffmpeg_answer_without_a_frame_line_is_quoted_whole(self):
        got = fi.parse_decoded_frames(SHORT_EVIDENCE)
        self.assertIn(SHORT_EVIDENCE, got["why"])


class ShortSceneSample(unittest.TestCase):
    """E3: the note lists a sample and says how big the sample is."""

    def _verdict(self, n_short):
        scene_list = [{"frames": 1} for _ in range(n_short)] + [{"frames": 300}]
        return fi.scene_length_verdict(scene_list, 30.0)

    def test_a_clipped_list_of_short_scenes_says_how_many_of_how_many(self):
        got = self._verdict(25)
        self.assertEqual(got["violations"], 25)
        self.assertIn("first 10 of 25", got["note"])
        self.assertEqual(len(got["short"]), 25)

    def test_a_list_that_fits_is_not_announced_as_a_sample_of_something_bigger(self):
        got = self._verdict(3)
        self.assertIn("first 3 of 3", got["note"])
