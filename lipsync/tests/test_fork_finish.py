"""Guard the final assembly: crop, audio return, and the three outcomes."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from lipsync import fork_finish as ff
from lipsync.fork_identity import FAIL, PASS, UNMEASURED


DRIVING_JSON = """{
 "streams": [
  {"index": 0, "codec_name": "h264", "codec_type": "video", "width": 720,
   "height": 1280, "r_frame_rate": "30/1", "avg_frame_rate": "30/1",
   "duration": "12.433333", "nb_frames": "373"},
  {"index": 1, "codec_name": "aac", "codec_type": "audio",
   "r_frame_rate": "0/0", "avg_frame_rate": "0/0", "duration": "12.492245",
   "nb_frames": "269"}
 ],
 "format": {"duration": "12.492245", "size": "2825859"}
}"""

KLING_JSON = """{
 "streams": [
  {"index": 0, "codec_name": "h264", "codec_type": "video", "width": 960,
   "height": 960, "r_frame_rate": "30/1", "avg_frame_rate": "30/1",
   "duration": "3.300000", "nb_frames": "99"}
 ],
 "format": {"duration": "3.300000", "size": "5207169"}
}"""

RESULT_JSON = """{
 "streams": [
  {"index": 0, "codec_name": "h264", "codec_type": "video", "width": 540,
   "height": 960, "r_frame_rate": "30/1", "avg_frame_rate": "30/1",
   "duration": "3.300000", "nb_frames": "99"},
  {"index": 1, "codec_name": "aac", "codec_type": "audio",
   "r_frame_rate": "0/0", "avg_frame_rate": "0/0", "duration": "3.300000",
   "nb_frames": "144"}
 ],
 "format": {"duration": "3.300000", "size": "1735695"}
}"""


# MEASURED 2026-08-26: 768x1376 = 0.5581 is what the styliser returns for a
# 9:16 request, and 1536x2752 is the same ratio from the outpaint route. Kept
# as a written result so the finisher can be asked about a real off-plan clip.
RESULT_OFF_PLAN_JSON = RESULT_JSON.replace(
    '"width": 540,\n   "height": 960', '"width": 768,\n   "height": 1376'
)


# A tiny frame where the crop plan itself lands off the plan: 20x20 gives a
# 10x20 window (0.5000), because evening the side down moves the ratio. The
# written file then matches the plan exactly and is still not 9:16 — only a
# measurement of the file itself can see this.
KLING_TINY_JSON = KLING_JSON.replace(
    '"width": 960,\n   "height": 960', '"width": 20,\n   "height": 20'
)
RESULT_TINY_JSON = RESULT_JSON.replace(
    '"width": 540,\n   "height": 960', '"width": 10,\n   "height": 20'
)

RESULT_SILENT_JSON = RESULT_JSON.replace(
    """,
  {"index": 1, "codec_name": "aac", "codec_type": "audio",
   "r_frame_rate": "0/0", "avg_frame_rate": "0/0", "duration": "3.300000",
   "nb_frames": "144"}""",
    "",
)

DRIVING_SILENT_JSON = DRIVING_JSON.replace(
    """,
  {"index": 1, "codec_name": "aac", "codec_type": "audio",
   "r_frame_rate": "0/0", "avg_frame_rate": "0/0", "duration": "12.492245",
   "nb_frames": "269"}""",
    "",
)

REAL_COLUMNS = [
    5.33,
    5.1,
    4.87,
    5.08,
    6.53,
    9.06,
    10.25,
    18.58,
    26.34,
    27.9,
    32.57,
    33.45,
    33.33,
    32.42,
    38.37,
    39.81,
    35.84,
    29.22,
    34.86,
    38.12,
    38.49,
    36.32,
    31.91,
    30.63,
    30.67,
    29.46,
    30.35,
    30.77,
    34.37,
    36.36,
    35.47,
    33.59,
    32.75,
    31.82,
    27.61,
    25.91,
    27.57,
    28.73,
    27.18,
    22.66,
    16.04,
    12.96,
    13.44,
    13.14,
    7.93,
    4.6,
    2.88,
    1.45,
]


def prober_of(mapping):
    """Substitute ffprobe: path -> answer text. Not a single process."""

    def _prober(path):
        answer = mapping.get(Path(path).name)
        if answer is None:
            return {
                "ran": False,
                "code": None,
                "out": "",
                "err": "",
                "why": "ffprobe not found: nothing to ask with",
            }
        if isinstance(answer, int):
            return {
                "ran": True,
                "code": answer,
                "out": "{\n\n}\n",
                "err": "moov atom not found",
                "why": "",
            }
        return {"ran": True, "code": 0, "out": answer, "err": "", "why": ""}

    return _prober


class Runner:
    """Substitute ffmpeg. Remembers argv, answers with the ordered outcome."""

    def __init__(self, *, ran=True, code=0, err=""):
        self.ran, self.code, self.err, self.calls = ran, code, err, []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if not self.ran:
            return {
                "ran": False,
                "code": None,
                "out": "",
                "err": "",
                "why": "ffmpeg not found: nothing to assemble with",
            }
        return {"ran": True, "code": self.code, "out": "", "err": self.err, "why": ""}


def _files(*names):
    """Put stubs on disk: `fork_video.probe` must see that the file exists."""
    tmp = Path(tempfile.mkdtemp(prefix="fork_finish_"))
    out = []
    for n in names:
        p = tmp / n
        p.write_bytes(b"\x00" * 64)
        out.append(p)
    return out


class CropIsCountedAndNotGuessed(unittest.TestCase):
    def test_the_square_from_kling_becomes_nine_by_sixteen(self):
        g = ff.crop_geometry(960, 960)
        self.assertEqual(g["outcome"], PASS)
        self.assertEqual((g["w"], g["h"]), (540, 960))
        self.assertEqual((g["x"], g["y"]), (210, 0))

    def test_the_lost_area_is_the_number_and_not_an_impression(self):
        self.assertEqual(540 * 960, 518400)
        self.assertEqual(960 * 960, 921600)
        self.assertEqual(round(100 * 518400 / 921600, 2), 56.25)
        g = ff.crop_geometry(960, 960)
        self.assertEqual(g["lost_percent"], 43.75)
        self.assertEqual(g["kept_percent"], 56.25)
        self.assertEqual(round(g["lost_percent"] + g["kept_percent"], 2), 100.0)

    def test_a_frame_already_nine_by_sixteen_loses_nothing(self):
        g = ff.crop_geometry(720, 1280)
        self.assertEqual(g["outcome"], PASS)
        self.assertEqual((g["w"], g["h"], g["x"], g["y"]), (720, 1280, 0, 0))
        self.assertEqual(g["lost_percent"], 0.0)

    def test_a_frame_taller_than_asked_is_cut_along_the_other_axis(self):
        g = ff.crop_geometry(540, 1200)
        self.assertEqual(g["outcome"], PASS)
        self.assertEqual((g["w"], g["h"]), (540, 960))
        self.assertEqual((g["x"], g["y"]), (0, 120))

    def test_odd_sides_are_snapped_down_because_x264_refuses_them(self):
        g = ff.crop_geometry(961, 961)
        self.assertEqual(g["outcome"], PASS)
        for name in ("w", "h", "x", "y"):
            with self.subTest(field=name):
                self.assertEqual(g[name] % 2, 0)
        self.assertEqual((g["w"], g["h"]), (540, 960))

    def test_the_window_never_leaves_the_frame_at_either_bias(self):
        for width, height, bias in (
            (960, 960, -1.0),
            (960, 960, 0.0),
            (960, 960, 1.0),
            (961, 961, 1.0),
            (540, 1200, 1.0),
            (540, 1200, -1.0),
        ):
            with self.subTest(size=(width, height), bias=bias):
                g = ff.crop_geometry(width, height, bias=bias)
                self.assertEqual(g["outcome"], PASS)
                self.assertLessEqual(g["x"] + g["w"], width)
                self.assertLessEqual(g["y"] + g["h"], height)
                self.assertGreaterEqual(min(g["x"], g["y"]), 0)

    def test_bias_moves_the_window_to_the_edges_and_to_the_middle(self):
        self.assertEqual(ff.crop_geometry(960, 960, bias=-1.0)["x"], 0)
        self.assertEqual(ff.crop_geometry(960, 960, bias=1.0)["x"], 420)
        self.assertEqual(ff.crop_geometry(960, 960, bias=0.0)["x"], 210)
        self.assertEqual(ff.crop_geometry(960, 960, bias=0.5)["x"], 314)

    def test_nonsense_sizes_are_refused_and_missing_sizes_are_not_refused(self):
        self.assertEqual(ff.crop_geometry(0, 960)["outcome"], FAIL)
        self.assertEqual(ff.crop_geometry(-960, 960)["outcome"], FAIL)
        self.assertEqual(ff.crop_geometry(960.0, 960)["outcome"], FAIL)
        self.assertEqual(ff.crop_geometry(None, 960)["outcome"], UNMEASURED)
        self.assertEqual(ff.crop_geometry(960, None)["outcome"], UNMEASURED)
        self.assertEqual(ff.crop_geometry(960, 960)["outcome"], PASS)

    def test_a_bias_outside_the_band_is_refused_and_the_edge_is_not(self):
        self.assertEqual(ff.crop_geometry(960, 960, bias=1.5)["outcome"], FAIL)
        self.assertEqual(ff.crop_geometry(960, 960, bias=-1.5)["outcome"], FAIL)
        self.assertEqual(ff.crop_geometry(960, 960, bias="left")["outcome"], FAIL)
        self.assertEqual(ff.crop_geometry(960, 960, bias=1.0)["outcome"], PASS)
        self.assertEqual(ff.crop_geometry(960, 960, bias=-1.0)["outcome"], PASS)

    def test_a_degenerate_frame_cannot_produce_a_window(self):
        self.assertEqual(ff.crop_geometry(2, 2)["outcome"], FAIL)
        self.assertEqual(ff.crop_geometry(960, 960, ratio_w=0)["outcome"], FAIL)
        self.assertEqual(ff.crop_geometry(960, 960, ratio_h=-16)["outcome"], FAIL)

    def test_the_target_ratio_is_nine_by_sixteen(self):
        self.assertEqual((ff.TARGET_RATIO_W, ff.TARGET_RATIO_H), (9, 16))


class CropConstantsAreMutatedInBothDirections(unittest.TestCase):
    """Swap the constant stricter and looser; the test must turn red."""

    def test_the_even_multiple_guards_the_window(self):
        was = ff.DIM_MULTIPLE
        try:
            ff.DIM_MULTIPLE = 1
            self.assertEqual(ff.crop_geometry(961, 961)["h"], 961)
            ff.DIM_MULTIPLE = 4
            self.assertEqual(ff.crop_geometry(961, 961)["w"], 540)
            self.assertEqual(ff.crop_geometry(961, 961)["h"], 960)
            self.assertEqual(ff.crop_geometry(962, 962)["h"], 960)
        finally:
            ff.DIM_MULTIPLE = was
        self.assertEqual(ff.crop_geometry(961, 961)["h"], 960)

    def test_the_ratio_constants_change_the_window_both_ways(self):
        self.assertEqual(ff.crop_geometry(960, 960, ratio_w=16, ratio_h=9)["h"], 540)
        self.assertEqual(ff.crop_geometry(960, 960, ratio_w=1, ratio_h=1)["w"], 960)


class BiasIsChosenOnlyWhenThereIsSomethingToChooseFrom(unittest.TestCase):
    def test_a_flat_map_gives_no_bias_and_says_so(self):
        r = ff.bias_from_columns([7.0] * 48)
        self.assertEqual(r["outcome"], UNMEASURED)
        self.assertEqual(r["bias"], 0.0)
        self.assertEqual(r["gain"], 1.0)

    def test_an_empty_map_gives_no_bias_either(self):
        r = ff.bias_from_columns([0.0] * 48)
        self.assertEqual(r["outcome"], UNMEASURED)
        self.assertEqual(r["bias"], 0.0)

    def test_the_real_material_puts_the_person_in_the_middle(self):
        r = ff.bias_from_columns(REAL_COLUMNS)
        self.assertEqual(r["outcome"], UNMEASURED)
        self.assertEqual(r["bias"], 0.0)
        self.assertLess(r["gain"], 1.01)
        self.assertGreater(r["gain"], 1.0)

    def test_a_person_standing_aside_moves_the_window_there(self):
        left = [100.0] * 20 + [0.0] * 28
        right = [0.0] * 28 + [100.0] * 20
        rl, rr = ff.bias_from_columns(left), ff.bias_from_columns(right)
        self.assertEqual((rl["outcome"], rr["outcome"]), (PASS, PASS))
        self.assertLess(rl["bias"], 0.0)
        self.assertGreater(rr["bias"], 0.0)
        self.assertEqual(rl["bias"], -1.0)
        self.assertEqual(rr["bias"], 1.0)

    def test_a_person_a_little_off_centre_still_moves_the_window(self):
        r = ff.bias_from_columns([100.0] * 24 + [40.0] * 24)
        self.assertEqual(r["outcome"], PASS)
        self.assertEqual(r["gain"], 1.3125)
        self.assertLess(r["bias"], 0.0)

    def test_a_broken_map_is_refused_and_a_missing_one_is_not(self):
        self.assertEqual(ff.bias_from_columns([1.0, -1.0] * 24)["outcome"], FAIL)
        self.assertEqual(ff.bias_from_columns(["left"] * 48)["outcome"], FAIL)
        self.assertEqual(ff.bias_from_columns(None)["outcome"], UNMEASURED)
        self.assertEqual(ff.bias_from_columns([])["outcome"], UNMEASURED)
        self.assertEqual(ff.bias_from_columns([1.0])["outcome"], UNMEASURED)

    def test_the_gain_threshold_is_mutated_in_both_directions(self):
        was = ff.BIAS_GAIN_MIN
        try:
            ff.BIAS_GAIN_MIN = 1.0001
            self.assertEqual(ff.bias_from_columns(REAL_COLUMNS)["outcome"], PASS)
            ff.BIAS_GAIN_MIN = 100.0
            self.assertEqual(ff.bias_from_columns([100.0] * 20 + [0.0] * 28)["outcome"], UNMEASURED)
        finally:
            ff.BIAS_GAIN_MIN = was
        self.assertEqual(ff.bias_from_columns(REAL_COLUMNS)["outcome"], UNMEASURED)


class TheWindowIsCountedInclusively(unittest.TestCase):
    def test_frames_one_hundred_to_one_hundred_ninety_nine_are_one_hundred(self):
        r = ff.window_frames(100, 199)
        self.assertEqual(r["outcome"], PASS)
        self.assertEqual(r["frames"], 100)

    def test_a_single_frame_window_is_one_frame(self):
        self.assertEqual(ff.window_frames(7, 7)["frames"], 1)

    def test_a_reversed_or_negative_window_is_refused(self):
        self.assertEqual(ff.window_frames(199, 100)["outcome"], FAIL)
        self.assertEqual(ff.window_frames(-1, 10)["outcome"], FAIL)
        self.assertEqual(ff.window_frames(1.5, 10)["outcome"], FAIL)
        self.assertEqual(ff.window_frames(None, 10)["outcome"], UNMEASURED)
        self.assertEqual(ff.window_frames(100, 199)["outcome"], PASS)


class TheToleranceIsTimeAndNotFrames(unittest.TestCase):
    def test_the_tolerance_at_our_rates(self):
        self.assertEqual(ff.drift_tolerance_frames(30), 1)
        self.assertEqual(ff.drift_tolerance_frames(24), 1)
        self.assertEqual(ff.drift_tolerance_frames(60), 2)
        self.assertEqual(ff.drift_tolerance_frames(120), 5)

    def test_an_unknown_rate_gives_no_tolerance_at_all(self):
        for bad in (None, 0, -30, "thirty"):
            with self.subTest(fps=bad):
                self.assertIsNone(ff.drift_tolerance_frames(bad))
        self.assertEqual(ff.drift_tolerance_frames(30), 1)

    def test_the_perception_threshold_is_mutated_in_both_directions(self):
        was = ff.LIPSYNC_AUDIO_AHEAD_MS
        try:
            ff.LIPSYNC_AUDIO_AHEAD_MS = 30
            self.assertEqual(ff.drift_tolerance_frames(30), 0)
            self.assertEqual(ff.audio_drift(100, 99, fps=30)["outcome"], FAIL)
            ff.LIPSYNC_AUDIO_AHEAD_MS = 70
            self.assertEqual(ff.drift_tolerance_frames(30), 2)
            self.assertEqual(ff.audio_drift(90, 88, fps=30)["outcome"], PASS)
        finally:
            ff.LIPSYNC_AUDIO_AHEAD_MS = was
        self.assertEqual(ff.drift_tolerance_frames(30), 1)


class TheFourMeasuredKlingRunsAreJudgedCorrectly(unittest.TestCase):
    """MEASURED 2026-08-22: four real runs, four verdicts."""

    def test_one_hundred_frames_came_back_as_ninety_nine(self):
        r = ff.audio_drift(100, 99, fps=30)
        self.assertEqual(r["outcome"], PASS)
        self.assertTrue(r["glue"])
        self.assertEqual(r["drift_frames"], -1)
        self.assertEqual(r["drift_ms"], -33.3)
        self.assertEqual(r["tolerance"], 1)

    def test_eighty_eight_frames_came_back_as_ninety_one(self):
        r = ff.audio_drift(88, 91, fps=30)
        self.assertEqual(r["outcome"], FAIL)
        self.assertFalse(r["glue"])
        self.assertEqual(r["drift_frames"], 3)
        self.assertEqual(r["drift_ms"], 100.0)

    def test_ninety_frames_came_back_as_eighty_eight(self):
        r = ff.audio_drift(90, 88, fps=30)
        self.assertEqual(r["outcome"], FAIL)
        self.assertFalse(r["glue"])
        self.assertEqual(r["drift_frames"], -2)

    def test_one_hundred_eighty_frames_came_back_exactly(self):
        r = ff.audio_drift(180, 180, fps=30)
        self.assertEqual(r["outcome"], PASS)
        self.assertTrue(r["glue"])
        self.assertEqual(r["drift_frames"], 0)
        self.assertEqual(r["drift_ms"], 0.0)


class TheAudioVerdictHasThreeOutcomes(unittest.TestCase):
    def test_the_boundary_is_symmetric_and_it_is_a_boundary(self):
        self.assertEqual(ff.audio_drift(100, 101, fps=30)["outcome"], PASS)
        self.assertEqual(ff.audio_drift(100, 99, fps=30)["outcome"], PASS)
        self.assertEqual(ff.audio_drift(100, 102, fps=30)["outcome"], FAIL)
        self.assertEqual(ff.audio_drift(100, 98, fps=30)["outcome"], FAIL)

    def test_the_same_two_frames_pass_at_sixty_and_fail_at_thirty(self):
        self.assertEqual(ff.audio_drift(200, 202, fps=60)["outcome"], PASS)
        self.assertEqual(ff.audio_drift(200, 202, fps=30)["outcome"], FAIL)

    def test_an_unreadable_duration_is_neither_pass_nor_fail(self):
        for expected, actual, fps in (
            (100, None, 30),
            (None, 99, 30),
            (100, 99, None),
            (100, 99, "no"),
        ):
            with self.subTest(expected=expected, actual=actual, fps=fps):
                r = ff.audio_drift(expected, actual, fps=fps)
                self.assertEqual(r["outcome"], UNMEASURED)
                self.assertFalse(r["glue"])
        self.assertEqual(ff.audio_drift(100, 99, fps=30)["outcome"], PASS)

    def test_nonsense_frame_counts_are_refused(self):
        self.assertEqual(ff.audio_drift(0, 99, fps=30)["outcome"], FAIL)
        self.assertEqual(ff.audio_drift(100, -1, fps=30)["outcome"], FAIL)

    def test_glue_never_travels_with_a_bad_verdict(self):
        for expected in range(90, 111):
            r = ff.audio_drift(expected, 100, fps=30)
            with self.subTest(expected=expected, outcome=r["outcome"]):
                self.assertEqual(r["glue"], r["outcome"] == PASS)
        self.assertTrue(ff.audio_drift(100, 100, fps=30)["glue"])
        self.assertFalse(ff.audio_drift(100, 90, fps=30)["glue"])


class TheAudioPlanReadsTheRealFilesShape(unittest.TestCase):
    def setUp(self):
        self.drv, self.kln = _files("driving_arms.mp4", "kling.mp4")

    def test_the_real_run_is_pass_with_a_named_warning(self):
        p = ff.audio_plan(
            self.drv,
            (100, 199),
            self.kln,
            prober=prober_of({"driving_arms.mp4": DRIVING_JSON, "kling.mp4": KLING_JSON}),
        )
        self.assertEqual(p["outcome"], PASS)
        self.assertTrue(p["glue"])
        self.assertEqual((p["expected"], p["actual"]), (100, 99))
        self.assertEqual(p["drift_frames"], -1)
        self.assertEqual(p["start_seconds"], 3.333333)
        self.assertEqual(p["seconds"], 3.3)

    def test_a_driving_without_sound_is_refused_with_the_reason(self):
        p = ff.audio_plan(
            self.drv,
            (100, 199),
            self.kln,
            prober=prober_of({"driving_arms.mp4": DRIVING_SILENT_JSON, "kling.mp4": KLING_JSON}),
        )
        self.assertEqual(p["outcome"], FAIL)
        self.assertFalse(p["glue"])

    def test_a_window_outside_the_driving_is_refused(self):
        p = ff.audio_plan(
            self.drv,
            (300, 399),
            self.kln,
            prober=prober_of({"driving_arms.mp4": DRIVING_JSON, "kling.mp4": KLING_JSON}),
        )
        self.assertEqual(p["outcome"], FAIL)
        ok = ff.audio_plan(
            self.drv,
            (273, 372),
            self.kln,
            prober=prober_of({"driving_arms.mp4": DRIVING_JSON, "kling.mp4": KLING_JSON}),
        )
        self.assertEqual(ok["outcome"], PASS)

    def test_different_rates_cannot_be_compared_in_frames(self):
        p = ff.audio_plan(
            self.drv,
            (100, 199),
            self.kln,
            prober=prober_of(
                {
                    "driving_arms.mp4": DRIVING_JSON,
                    "kling.mp4": KLING_JSON.replace('"30/1"', '"24/1"'),
                }
            ),
        )
        self.assertEqual(p["outcome"], FAIL)

    def test_no_ffprobe_is_not_a_bad_file(self):
        p = ff.audio_plan(
            self.drv,
            (100, 199),
            self.kln,
            prober=prober_of({"driving_arms.mp4": None, "kling.mp4": None}),
        )
        self.assertEqual(p["outcome"], UNMEASURED)
        self.assertFalse(p["glue"])

    def test_a_broken_file_is_not_an_absent_tool(self):
        p = ff.audio_plan(
            self.drv,
            (100, 199),
            self.kln,
            prober=prober_of({"driving_arms.mp4": DRIVING_JSON, "kling.mp4": 1}),
        )
        self.assertEqual(p["outcome"], FAIL)

    def test_every_step_is_named_and_none_is_silent(self):
        p = ff.audio_plan(
            self.drv,
            (100, 199),
            self.kln,
            prober=prober_of({"driving_arms.mp4": DRIVING_JSON, "kling.mp4": KLING_JSON}),
        )
        self.assertGreaterEqual(len(p["steps"]), 4)
        for name, outcome, note in p["steps"]:
            with self.subTest(step=name):
                self.assertIn(outcome, (PASS, FAIL, UNMEASURED))
                self.assertGreater(len(note), 10)


class TheCommandIsADecisionAndIsCheckedApartFromItsRun(unittest.TestCase):
    GEOM = {"w": 540, "h": 960, "x": 210, "y": 0}

    def test_the_crop_filter_carries_the_planned_window(self):
        argv = ff.mux_argv("k.mp4", "out.mp4", self.GEOM)
        self.assertIn("[0:v]crop=540:960:210:0[v]", argv)

    def test_the_sound_is_cut_from_the_input_and_not_from_the_output(self):
        argv = ff.mux_argv(
            "k.mp4", "out.mp4", self.GEOM, driving_path="d.mp4", start_seconds=3.333333, seconds=3.3
        )
        self.assertIn("-ss", argv)
        self.assertLess(argv.index("-ss"), argv.index("d.mp4"))
        self.assertLess(argv.index("-t"), argv.index("d.mp4"))
        self.assertEqual(argv[argv.index("-ss") + 1], "3.333333")
        self.assertEqual(argv[argv.index("-t") + 1], "3.300000")
        self.assertIn("1:a", argv)
        self.assertNotIn("-an", argv)

    def test_without_a_driving_the_file_is_written_deliberately_mute(self):
        argv = ff.mux_argv("k.mp4", "out.mp4", self.GEOM)
        self.assertIn("-an", argv)
        self.assertNotIn("1:a", argv)
        self.assertNotIn("-shortest", argv)
        self.assertNotIn("-ss", argv)

    def test_the_streams_are_mapped_explicitly(self):
        argv = ff.mux_argv(
            "k.mp4", "out.mp4", self.GEOM, driving_path="d.mp4", start_seconds=0.0, seconds=1.0
        )
        self.assertIn("-map", argv)
        self.assertIn("[v]", argv)
        self.assertEqual(argv[-1], "out.mp4")
        self.assertIn("yuv420p", argv)

    def test_the_quality_keys_are_the_ones_we_chose(self):
        argv = ff.mux_argv(
            "k.mp4", "out.mp4", self.GEOM, driving_path="d.mp4", start_seconds=0.0, seconds=1.0
        )
        self.assertEqual(argv[argv.index("-crf") + 1], "18")
        self.assertEqual(argv[argv.index("-b:a") + 1], "128k")
        self.assertIn("libx264", argv)
        self.assertIn("aac", argv)

    def test_no_filter_ever_stretches_the_sound(self):
        argv = ff.mux_argv(
            "k.mp4", "out.mp4", self.GEOM, driving_path="d.mp4", start_seconds=0.0, seconds=1.0
        )
        joined = " ".join(argv)
        for forbidden in ("atempo", "asetrate", "rubberband", "setpts"):
            with self.subTest(filter=forbidden):
                self.assertNotIn(forbidden, joined)


class TheAssemblyReportsWhatActuallyHappened(unittest.TestCase):
    def setUp(self):
        self.drv, self.kln, self.out = _files("driving_arms.mp4", "kling.mp4", "finish.mp4")
        self.answers = {
            "driving_arms.mp4": DRIVING_JSON,
            "kling.mp4": KLING_JSON,
            "finish.mp4": RESULT_JSON,
        }

    def _finish(self, runner, **over):
        answers = dict(self.answers, **over.pop("answers", {}))
        return ff.finish(
            self.drv,
            self.kln,
            self.out,
            window=(100, 199),
            prober=prober_of(answers),
            runner=runner,
            **over,
        )

    def test_the_real_case_assembles_with_sound_and_says_the_numbers(self):
        run = Runner()
        rep = self._finish(run)
        self.assertEqual(rep["outcome"], PASS)
        self.assertTrue(rep["written"])
        self.assertTrue(rep["audio"])
        self.assertEqual((rep["crop"]["w"], rep["crop"]["h"]), (540, 960))
        self.assertEqual(rep["crop"]["lost_percent"], 43.75)
        self.assertEqual(rep["audio_plan"]["drift_frames"], -1)
        self.assertEqual(len(run.calls), 1)
        self.assertIn("[0:v]crop=540:960:210:0[v]", run.calls[0])

    def test_a_drift_beyond_tolerance_writes_a_mute_file_and_says_not_good(self):
        run = Runner()
        rep = ff.finish(
            self.drv,
            self.kln,
            self.out,
            window=(100, 187),
            prober=prober_of(dict(self.answers, **{"finish.mp4": RESULT_SILENT_JSON})),
            runner=run,
        )
        self.assertEqual(rep["outcome"], FAIL)
        self.assertTrue(rep["written"])
        self.assertFalse(rep["audio"])
        self.assertEqual(rep["audio_plan"]["expected"], 88)
        self.assertEqual(rep["audio_plan"]["actual"], 99)
        self.assertIn("-an", run.calls[0])
        self.assertNotIn("1:a", run.calls[0])

    def test_an_unreadable_duration_writes_nothing_at_all(self):
        run = Runner()
        rep = self._finish(run, answers={"driving_arms.mp4": None})
        self.assertEqual(rep["outcome"], UNMEASURED)
        self.assertFalse(rep["written"])
        self.assertEqual(len(run.calls), 0)

    def test_an_absent_ffmpeg_is_not_a_bad_file(self):
        rep = self._finish(Runner(ran=False))
        self.assertEqual(rep["outcome"], UNMEASURED)
        self.assertFalse(rep["written"])

    def test_a_failing_ffmpeg_is_not_a_missing_ffmpeg(self):
        rep = self._finish(Runner(code=1, err="Invalid argument"))
        self.assertEqual(rep["outcome"], FAIL)
        self.assertFalse(rep["written"])

    def test_the_verdict_comes_from_the_file_and_not_from_the_intention(self):
        run = Runner()
        rep = self._finish(run, answers={"finish.mp4": KLING_JSON})
        self.assertEqual(rep["outcome"], FAIL)
        self.assertTrue(rep["written"])

    def test_a_promised_sound_that_did_not_arrive_is_caught(self):
        run = Runner()
        rep = self._finish(run, answers={"finish.mp4": RESULT_SILENT_JSON})
        self.assertEqual(rep["outcome"], FAIL)
        self.assertFalse(rep["audio"])

    def test_a_broken_kling_output_stops_before_any_ffmpeg_runs(self):
        run = Runner()
        rep = self._finish(run, answers={"kling.mp4": 1})
        self.assertEqual(rep["outcome"], FAIL)
        self.assertEqual(len(run.calls), 0)

    def test_every_step_is_named_with_its_own_outcome(self):
        rep = self._finish(Runner())
        names = [n for n, _, _ in rep["steps"]]
        self.assertGreaterEqual(len(names), 6)
        for name, outcome, note in rep["steps"]:
            with self.subTest(step=name):
                self.assertIn(outcome, (PASS, FAIL, UNMEASURED))
                self.assertGreater(len(note), 10)
        self.assertIn("crop", names)
        self.assertIn("audio", names)
        self.assertIn("assembly", names)

    def test_the_elapsed_time_of_the_run_is_printed(self):
        rep = self._finish(Runner())
        self.assertIsInstance(rep["elapsed"], float)
        self.assertGreaterEqual(rep["elapsed"], 0.0)


class TheModuleDoesNotReinventWhatAlreadyExists(unittest.TestCase):
    SRC = Path(ff.__file__).read_text(encoding="utf-8")

    def test_the_outside_world_is_touched_only_through_the_neighbour(self):
        tree = ast.parse(self.SRC)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in ("subprocess", "shutil", "os"):
            with self.subTest(module=forbidden):
                self.assertNotIn(forbidden, imported)

    def test_the_probe_answer_is_not_parsed_a_second_time(self):
        self.assertNotIn("json.loads", self.SRC)
        self.assertNotIn("avg_frame_rate", self.SRC)

    def test_the_verdict_words_are_not_reinvented(self):
        self.assertEqual((PASS, FAIL, UNMEASURED), ("pass", "fail", "could not measure"))

    def test_the_three_outcomes_map_to_three_different_exit_codes(self):
        self.assertEqual(ff.EXIT_BY_OUTCOME[PASS], 0)
        self.assertEqual(ff.EXIT_BY_OUTCOME[FAIL], 1)
        self.assertEqual(ff.EXIT_BY_OUTCOME[UNMEASURED], 2)
        self.assertEqual(len(set(ff.EXIT_BY_OUTCOME.values())), 3)

    def test_the_injection_points_are_resolved_in_the_body(self):
        self.assertIn("runner = fork_video.run_decode if runner is None", self.SRC)

    def test_every_decision_constant_declares_where_it_came_from(self):
        # A word boundary is required: a bare substring test would accept
        # the "MEASURED" hiding inside the imported name "UNMEASURED".
        import re

        lines = self.SRC.splitlines()
        names = (
            "TARGET_RATIO_W",
            "DIM_MULTIPLE",
            "LIPSYNC_AUDIO_AHEAD_MS",
            "BIAS_GAIN_MIN",
            "BIAS_LIMIT",
            "VIDEO_CRF",
        )
        for name in names:
            with self.subTest(constant=name):
                i = next(k for k, ln in enumerate(lines) if ln.startswith(name))
                above = "\n".join(lines[max(0, i - 20) : i])
                self.assertTrue(
                    any(
                        re.search(rf"\b{mark}\b", above)
                        for mark in ("MEASURED", "DERIVED", "CHOSEN")
                    ),
                    f"{name}: provenance not marked",
                )


class TheShippedRatioIsMeasuredAndNotAssumed(unittest.TestCase):
    """Д7: nothing measured the ratio of the file that leaves for the client."""

    def setUp(self):
        self.drv, self.kln, self.out = _files("driving_arms.mp4", "kling.mp4", "finish.mp4")
        self.answers = {
            "driving_arms.mp4": DRIVING_JSON,
            "kling.mp4": KLING_JSON,
            "finish.mp4": RESULT_JSON,
        }

    def _finish(self, runner=None, **over):
        answers = dict(self.answers, **over.pop("answers", {}))
        return ff.finish(
            self.drv,
            self.kln,
            self.out,
            window=(100, 199),
            prober=prober_of(answers),
            runner=Runner() if runner is None else runner,
            **over,
        )

    # --- the instrument itself, three outcomes -------------------------------

    def test_an_exact_frame_is_the_yes_of_the_instrument(self):
        for width, height in ((720, 1280), (540, 960), (1080, 1920)):
            with self.subTest(size=(width, height)):
                axis = ff.shipped_ratio_axis(width, height)
                self.assertEqual(axis["outcome"], "pass", axis["note"])
                self.assertEqual(axis["ratio"], 0.5625)
                self.assertEqual((axis["checked"], axis["violations"]), (1, 0))

    def test_the_measured_square_from_kling_is_the_no_of_the_instrument(self):
        """Negative control: 960x960 is the MEASURED Kling return on eight orders."""
        axis = ff.shipped_ratio_axis(960, 960)
        self.assertEqual(axis["outcome"], "fail", axis["note"])
        self.assertEqual(axis["ratio"], 1.0)
        self.assertEqual((axis["checked"], axis["violations"], axis["unmeasured"]), (1, 1, 0))

    def test_the_measured_route_drift_does_not_pass(self):
        """0.5581 is what both routes return; it must not read as 9:16."""
        for width, height in ((768, 1376), (1536, 2752)):
            with self.subTest(size=(width, height)):
                axis = ff.shipped_ratio_axis(width, height)
                self.assertEqual(axis["outcome"], "fail", axis["note"])
                self.assertEqual(axis["ratio"], 0.5581)

    def test_an_unmeasured_side_is_neither_good_nor_bad(self):
        for width, height in ((None, None), (540, None), (None, 960)):
            with self.subTest(size=(width, height)):
                axis = ff.shipped_ratio_axis(width, height)
                self.assertEqual(axis["outcome"], "could not measure", axis["note"])
                self.assertEqual((axis["checked"], axis["unmeasured"]), (0, 1))

    def test_a_meaningless_side_is_a_violation_and_not_a_silence(self):
        for bad in (0, -540, 5.5, "540", True):
            with self.subTest(width=bad):
                axis = ff.shipped_ratio_axis(bad, 960)
                self.assertEqual(axis["outcome"], "fail", axis["note"])
                self.assertEqual(axis["violations"], 1)

    def test_the_instrument_judges_by_the_plan_and_not_by_its_own_band(self):
        """The tolerance is read from fork_plan at call time, not copied here."""
        axis = ff.shipped_ratio_axis(540, 960)
        self.assertEqual(axis["tolerance"], 0.001)
        self.assertEqual(axis["plan"], 0.5625)

    def test_the_band_edge_is_guarded_on_both_sides(self):
        """A ratio just inside 0.001 passes, one just outside does not."""
        height = 10_000
        inside = round(height * (0.5625 + 0.0009))
        outside = round(height * (0.5625 + 0.0011))
        self.assertEqual(ff.shipped_ratio_axis(inside, height)["outcome"], "pass")
        self.assertEqual(ff.shipped_ratio_axis(outside, height)["outcome"], "fail")

    # --- the report carries it -----------------------------------------------

    def test_the_report_keys_are_declared_as_data_and_the_report_obeys(self):
        rep = self._finish()
        self.assertEqual(tuple(rep), ff.FINISH_REPORT_KEYS)
        self.assertIn("shipped_ratio", ff.FINISH_REPORT_KEYS)

    def test_the_good_run_carries_the_measurement_of_what_it_wrote(self):
        rep = self._finish()
        self.assertEqual(rep["outcome"], PASS)
        self.assertEqual(rep["shipped_ratio"]["outcome"], PASS)
        self.assertEqual(rep["shipped_ratio"]["ratio"], 0.5625)
        self.assertEqual(
            (rep["shipped_ratio"]["width"], rep["shipped_ratio"]["height"]), (540, 960)
        )

    def test_an_off_plan_file_does_not_pass_acceptance(self):
        """The whole point: 0.5581 written to disk must not report a clean pass."""
        rep = self._finish(answers={"finish.mp4": RESULT_OFF_PLAN_JSON})
        self.assertEqual(rep["outcome"], FAIL)
        self.assertTrue(rep["written"])
        self.assertEqual(rep["shipped_ratio"]["ratio"], 0.5581)
        self.assertGreaterEqual(rep["violations"], 1)

    def test_a_file_matching_its_own_plan_is_still_judged_against_the_plan(self):
        """The planned window can itself be off 9:16, and the old check compared
        the file only with that plan — agreeing with a wrong plan is not a pass.
        """
        geom = ff.crop_geometry(20, 20)
        self.assertEqual((geom["w"], geom["h"]), (10, 20))
        rep = self._finish(answers={"kling.mp4": KLING_TINY_JSON, "finish.mp4": RESULT_TINY_JSON})
        self.assertEqual((rep["shipped_ratio"]["width"], rep["shipped_ratio"]["height"]), (10, 20))
        self.assertEqual(rep["shipped_ratio"]["ratio"], 0.5)
        self.assertEqual(rep["shipped_ratio"]["outcome"], FAIL)
        self.assertEqual(rep["outcome"], FAIL, rep["note"])
        self.assertGreaterEqual(rep["violations"], 1)

    def test_a_file_that_could_not_be_probed_is_not_a_silent_success(self):
        rep = self._finish(answers={"finish.mp4": None})
        self.assertEqual(rep["outcome"], UNMEASURED)
        self.assertEqual(rep["shipped_ratio"]["outcome"], UNMEASURED)
        self.assertGreaterEqual(rep["unmeasured"], 1)

    def test_the_shipped_ratio_is_a_named_step_of_the_run(self):
        rep = self._finish()
        self.assertIn("shipped ratio", [name for name, _, _ in rep["steps"]])

    def test_the_numbers_stand_next_to_every_verdict(self):
        rep = self._finish()
        self.assertEqual(rep["checked"], len(rep["steps"]))
        self.assertGreater(rep["checked"], 0)
        self.assertEqual(rep["violations"], 0)
        self.assertEqual(rep["unmeasured"], 0)

    def test_a_run_that_wrote_nothing_still_reports_the_ratio_as_unknown(self):
        rep = self._finish(Runner(ran=False))
        self.assertEqual(rep["outcome"], UNMEASURED)
        self.assertFalse(rep["written"])
        self.assertEqual(rep["shipped_ratio"]["outcome"], UNMEASURED)

    def test_a_key_the_declaration_does_not_know_is_refused(self):
        """The tuple governs the report; it is not a comment about it."""
        self.assertNotIn("smuggled", ff.FINISH_REPORT_KEYS)


class TheRatioIsKnownInOnePlaceOnly(unittest.TestCase):
    """Д5: 9 and 16 were declared here as well as 0.5625 in the plan."""

    def test_the_whole_sides_are_the_plan(self):
        self.assertEqual((ff.TARGET_RATIO_W, ff.TARGET_RATIO_H), (9, 16))
        self.assertEqual(ff.TARGET_RATIO_W / ff.TARGET_RATIO_H, 0.5625)

    def test_the_sides_are_computed_from_the_plan_and_not_written_down(self):
        """Move the plan and the crop must move with it, with no edit here."""
        import importlib
        from unittest import mock

        from lipsync import fork_plan

        try:
            with mock.patch.object(fork_plan, "PLAN_RATIO", 0.75):
                moved = importlib.reload(ff)
                sides = (moved.TARGET_RATIO_W, moved.TARGET_RATIO_H)
        finally:
            # The reload rewrites the module in place, so the plan must be back
            # before anything else in the suite reads it.
            importlib.reload(ff)
        self.assertEqual(sides, (3, 4))
        self.assertEqual((ff.TARGET_RATIO_W, ff.TARGET_RATIO_H), (9, 16))

    def test_the_crop_of_the_measured_square_follows_the_plan(self):
        g = ff.crop_geometry(960, 960)
        self.assertEqual((g["w"], g["h"]), (540, 960))
        self.assertEqual(ff.shipped_ratio_axis(g["w"], g["h"])["outcome"], "pass")


class TheAreaLostIsTheOneMeasuredOnRealOutput(unittest.TestCase):
    """The showcase quotes 0% lost; the MEASURED Kling return loses 43.75%."""

    def test_the_zero_percent_claim_holds_only_for_an_already_vertical_frame(self):
        self.assertEqual(ff.crop_geometry(720, 1280)["lost_percent"], 0.0)

    def test_the_measured_kling_square_loses_forty_three_percent_of_the_width(self):
        g = ff.crop_geometry(960, 960)
        self.assertEqual(g["lost_percent"], 43.75)
        self.assertEqual(g["w"], 540)
        self.assertEqual(round(100.0 * (960 - 540) / 960, 2), 43.75)


if __name__ == "__main__":
    unittest.main()
