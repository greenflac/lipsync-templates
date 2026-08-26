"""End-to-end stand: the whole path on stub functions, no network and no money."""

from __future__ import annotations

import io
import socket
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from lipsync import fork_e2e as E
from lipsync import fork_plan
from lipsync.fork_identity import FAIL, PASS, UNMEASURED


class _Blocked(RuntimeError):
    """The runner, not an agreement, bans the network in this file's tests."""


def _no_network():
    def deny(*a, **k):
        raise _Blocked("network is banned in tests: substitute a function instead of going outside")

    return mock.patch.object(socket, "socket", deny)


def _files(root: Path) -> dict:
    """Create the three inputs: real files on disk, but tiny and contentless."""
    paths = {}
    for name in ("client.png", "style.png", "driving.mp4"):
        p = root / name
        p.write_bytes(b"\x00" * 64)
        paths[name.split(".")[0]] = p
    return paths


def _probe_ok(path):
    return {
        "outcome": PASS,
        "fps": 30.0,
        "frames": 373,
        "width": 960,
        "height": 960,
        "note": "stub probe",
    }


def _cutter_ok(src, dst):
    Path(dst).write_bytes(b"\x00" * 32)
    return {"path": str(dst), "frames": 100}


def _decode_ok(video, out_dir):
    return {"paths": [f"{out_dir}/{i:05d}.png" for i in range(99)], "note": "stub frame layout"}


def _distances_ok(frames, anchor, **kw):
    return {
        "outcome": PASS,
        "median": 0.0652,
        "inside": len(frames),
        "judged": len(frames),
        "note": "stub identity instrument",
    }


def _cuts_ok(paths, **kw):
    return {"outcome": PASS, "cuts": [], "note": "stub cuts instrument"}


def _similarity_ok(a, b):
    return 0.8801 if "styled" in str(b) else 0.6409


def _upload_ok(path):
    return f"https://example.invalid/{Path(path).name}"


def _kling_ok(*, video_url, image_url, character_orientation, out_path):
    Path(out_path).write_bytes(b"\x00" * 128)
    return str(out_path)


def _intake_ok(*, client_photo, style_ref, driving):
    return {"outcome": PASS, "note": "stub intake"}


def _finish_ok(*, driving_path, kling_path, out_path, window):
    Path(out_path).write_bytes(b"\x00" * 64)
    return {"outcome": PASS, "path": str(out_path), "note": f"stub assembly, window {window}"}


def _stylize_ok(*, person, style, prompt, out_path):
    Path(out_path).write_bytes(b"\x00" * 64)
    return str(out_path)


def _pose_ok(path):
    """Return a stub pose inside the plan: the stage test is not about mediapipe."""
    return {
        "l_shoulder": (0.58, 0.32, 0.99),
        "r_shoulder": (0.42, 0.32, 0.99),
        "l_ankle": (0.55, 0.92, 0.96),
        "r_ankle": (0.45, 0.92, 0.96),
    }


class _PlanOk:
    """Stub plan neighbour: it does not touch the disk and does not pull in PIL."""

    @staticmethod
    def to_plan(src, dst, **kw):
        Path(dst).write_bytes(b"\x00" * 64)
        return {
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "path": str(dst),
            # The normal case since the styliser is asked for the plan itself:
            # the source already IS 9:16, so the canvas adds nothing.
            "source": {"width": 720, "height": 1280},
            "plan": {"added_share": 0.0},
            "note": "stub 9:16 plan",
        }

    @staticmethod
    def extend_to_plan(src, dst, **kw):
        Path(dst).write_bytes(b"\x00" * 64)
        return {
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "path": str(dst),
            "extended": True,
            "note": "stub margin outpaint",
        }

    ANKLES_BAND = fork_plan.ANKLES_BAND
    CENTRE_TOL = fork_plan.CENTRE_TOL
    SHOULDERS_BAND = fork_plan.SHOULDERS_BAND
    WIDTH_MAX = fork_plan.WIDTH_MAX
    person_box = staticmethod(fork_plan.person_box)
    ratio_axis = staticmethod(fork_plan.ratio_axis)


def _run(root: Path, log, **over):
    f = _files(root)
    kw = dict(
        client_photo=f["client"],
        style_ref=f["style"],
        driving=f["driving"],
        first=100,
        last=199,
        out_dir=root / "out",
        intake=_intake_ok,
        stylize=_stylize_ok,
        similarity=_similarity_ok,
        distances=_distances_ok,
        probe=_probe_ok,
        cutter=_cutter_ok,
        decode=_decode_ok,
        cuts=_cuts_ok,
        upload=_upload_ok,
        kling=_kling_ok,
        finish=_finish_ok,
        plan=_PlanOk,
        pose=_pose_ok,
        log=log,
    )
    kw.update(over)
    return E.run(**kw)


class WholePathOnFakes(unittest.TestCase):
    def test_every_stage_passes_and_nothing_touches_the_network(self):
        log = io.StringIO()
        with TemporaryDirectory() as td, _no_network():
            got = _run(Path(td), log)
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(got["exit_code"], 0)
        self.assertEqual(len(got["stages"]), 8)
        self.assertEqual([s["outcome"] for s in got["stages"]], ["pass"] * 8)
        self.assertEqual(got["totals"]["stages_passed"], 7)
        self.assertEqual(got["totals"]["violations"], 0)
        self.assertEqual(got["totals"]["unmeasured"], 0)

    def test_the_stage_names_are_the_declared_order(self):
        log = io.StringIO()
        with TemporaryDirectory() as td, _no_network():
            got = _run(Path(td), log)
        self.assertEqual(
            [s["stage"] for s in got["stages"]],
            [
                "1 intake of three inputs",
                "2 client photo stylization",
                "3 styled photo acceptance",
                "4 driving window and cutting",
                "5 upload inputs and call Kling",
                "6 output acceptance",
                "7 final assembly",
                "8 report",
            ],
        )

    def test_stages_are_printed_while_the_run_is_still_going(self):
        """Printing happens during the run — observed, not taken on faith."""
        log = io.StringIO()
        seen = {}

        def watching_stylize(*, person, style, prompt, out_path):
            seen["log"] = log.getvalue()
            return _stylize_ok(person=person, style=style, prompt=prompt, out_path=out_path)

        with TemporaryDirectory() as td, _no_network():
            _run(Path(td), log, stylize=watching_stylize)
        self.assertIn("1 intake of three inputs", seen["log"])
        self.assertNotIn("6 output acceptance", seen["log"])


class ThirdOutcomeIsNotCollapsed(unittest.TestCase):
    def test_a_falling_kling_is_unmeasured_and_not_a_defect(self):
        def falling(*, video_url, image_url, character_orientation, out_path):
            raise RuntimeError("the fal queue returned 503")

        log = io.StringIO()
        with TemporaryDirectory() as td, _no_network():
            got = _run(Path(td), log, kling=falling)
        self.assertEqual(got["outcome"], "could not measure")
        self.assertEqual(got["exit_code"], 2)
        self.assertEqual(got["stopped_at"], "5 upload inputs and call Kling")
        self.assertEqual(got["stopped_index"], 5)
        self.assertNotEqual(got["outcome"], "fail")

    def test_a_real_defect_is_a_defect_and_stops_the_run_naming_the_stage(self):
        def stranger(frames, anchor, **kw):
            return {
                "outcome": FAIL,
                "median": 1.0217,
                "inside": 0,
                "judged": len(frames),
                "note": "a stranger",
            }

        log = io.StringIO()
        with TemporaryDirectory() as td, _no_network():
            got = _run(Path(td), log, distances=stranger)
        self.assertEqual(got["outcome"], "fail")
        self.assertEqual(got["exit_code"], 1)
        self.assertEqual(got["stopped_at"], "3 styled photo acceptance")
        self.assertEqual(
            [s["stage"] for s in got["stages"]],
            [
                "1 intake of three inputs",
                "2 client photo stylization",
                "3 styled photo acceptance",
                "8 report",
            ],
        )
        self.assertIn("TOTAL: fail at stage '3 styled photo acceptance'", log.getvalue())

    def test_the_three_exit_codes_are_deliberately_different(self):
        self.assertEqual(
            [
                E.EXIT_BY_OUTCOME["pass"],
                E.EXIT_BY_OUTCOME["fail"],
                E.EXIT_BY_OUTCOME["could not measure"],
            ],
            [0, 1, 2],
        )

    def test_zero_checks_is_not_a_success(self):
        self.assertEqual(E.verdict(0, 0, 0), "could not measure")
        self.assertEqual(E.verdict(1, 0, 0), "pass")
        self.assertEqual(E.verdict(1, 1, 0), "fail")
        self.assertEqual(E.verdict(1, 0, 1), "could not measure")
        self.assertEqual(E.verdict(2, 1, 1), "fail")


class IdentityBarIsGuarded(unittest.TestCase):
    """The identity bar is a decision constant. Mutate it in both directions."""

    def _acceptance(self, median):
        def d(frames, anchor, **kw):
            return {
                "outcome": PASS if median <= 0.35 else FAIL,
                "median": median,
                "inside": 0,
                "judged": 1,
                "note": "",
            }

        return E.stage_style_acceptance(
            styled="styled.png",
            style_ref="s.png",
            client_photo="c.png",
            similarity=_similarity_ok,
            distances=d,
        )

    def test_just_inside_the_bar_passes_and_just_outside_is_UNMEASURED(self):
        self.assertEqual(self._acceptance(0.34)["outcome"], "pass")
        self.assertEqual(self._acceptance(0.36)["outcome"], "could not measure")
        self.assertEqual(self._acceptance(0.80)["outcome"], "fail")

    def test_the_bar_itself_moved_flips_the_verdict_both_ways(self):
        with mock.patch.object(E, "SAME_PERSON_MAX", 0.30):
            self.assertEqual(self._acceptance(0.32)["outcome"], "could not measure")
        with mock.patch.object(E, "SAME_PERSON_MAX", 0.40):
            self.assertEqual(self._acceptance(0.32)["outcome"], "pass")

    def test_an_unmeasured_identity_is_not_a_defect(self):
        def d(frames, anchor, **kw):
            return {"outcome": UNMEASURED, "median": None, "note": "no face in the frame"}

        got = E.stage_style_acceptance(
            styled="styled.png",
            style_ref="s.png",
            client_photo="c.png",
            similarity=_similarity_ok,
            distances=d,
        )
        self.assertEqual(got["outcome"], "could not measure")
        self.assertEqual((got["checked"], got["violations"], got["unmeasured"]), (1, 0, 1))


class StyleFloorIsTheNegativeControl(unittest.TestCase):
    """The floor is computed on the spot, and without it the stage issues no verdict."""

    def _acceptance(self, hit, floor):
        def sim(a, b):
            return hit if "styled" in str(b) else floor

        return E.stage_style_acceptance(
            styled="styled.png",
            style_ref="s.png",
            client_photo="c.png",
            similarity=sim,
            distances=_distances_ok,
        )

    def test_the_measured_winner_passes_and_the_rejected_text_route_fails(self):
        self.assertEqual(self._acceptance(0.8801, 0.6409)["outcome"], "pass")
        self.assertEqual(self._acceptance(0.6773, 0.6409)["outcome"], "fail")

    def test_the_margin_constant_is_guarded_in_both_directions(self):
        with mock.patch.object(E, "STYLE_MARGIN_MIN", 0.02):
            self.assertEqual(self._acceptance(0.6773, 0.6409)["outcome"], "pass")
        with mock.patch.object(E, "STYLE_MARGIN_MIN", 0.30):
            self.assertEqual(self._acceptance(0.8801, 0.6409)["outcome"], "fail")

    def test_without_a_floor_the_stage_says_it_could_not_measure(self):
        def sim(a, b):
            return None

        got = E.stage_style_acceptance(
            styled="styled.png",
            style_ref="s.png",
            client_photo="c.png",
            similarity=sim,
            distances=_distances_ok,
        )
        self.assertEqual(got["checks"][0]["outcome"], "could not measure")
        self.assertEqual(got["outcome"], "could not measure")


class PaletteInstrumentHasBothControls(unittest.TestCase):
    """The instrument has an input where it must say no, and one where it must move."""

    def _png(self, root: Path, name: str, colour) -> Path:
        from PIL import Image

        p = root / name
        Image.new("RGB", (64, 64), colour).save(p)
        return p

    def test_same_image_is_one_and_a_different_palette_is_far_below(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            blue = self._png(root, "blue.png", (40, 120, 220))
            red = self._png(root, "red.png", (220, 60, 40))
            self.assertEqual(E.palette_similarity(blue, blue), 1.0)
            self.assertEqual(E.palette_similarity(blue, red), 0.0)

    def test_an_unreadable_input_gives_none_and_not_a_number(self):
        with TemporaryDirectory() as td:
            broken = Path(td) / "broken.png"
            broken.write_bytes(b"not a picture")
            self.assertIsNone(E.palette_similarity(broken, broken))


class SceneLengthIsGuarded(unittest.TestCase):
    """Three seconds is the window acceptance criterion, not a wish (a Kling gate)."""

    def _window(self, first, last, cutter=None):
        return E.stage_window(
            driving="d.mp4",
            first=first,
            last=last,
            out_path="w.mp4",
            probe=_probe_ok,
            cutter=cutter or (lambda s, d: {"path": "w.mp4", "frames": last - first + 1}),
        )

    def test_ninety_frames_at_thirty_fps_pass_and_eighty_nine_fail(self):
        with mock.patch.object(E, "file_fact", lambda p, w: (w, PASS, "stub file check")):
            self.assertEqual(self._window(0, 89)["outcome"], "pass")
            self.assertEqual(self._window(0, 88)["outcome"], "fail")

    def test_the_threshold_moved_flips_the_verdict_both_ways(self):
        with mock.patch.object(E, "file_fact", lambda p, w: (w, PASS, "stub file check")):
            with mock.patch.object(E, "MIN_SCENE_S", 4.0):
                self.assertEqual(self._window(0, 89)["outcome"], "fail")
            with mock.patch.object(E, "MIN_SCENE_S", 2.0):
                self.assertEqual(self._window(0, 88)["outcome"], "pass")

    def test_a_window_outside_the_clip_is_a_defect(self):
        got = self._window(300, 500)
        self.assertEqual(got["outcome"], "fail")
        self.assertIn("373", got["checks"][1]["note"])

    def test_a_cut_that_returned_the_wrong_frame_count_is_a_defect(self):
        with mock.patch.object(E, "file_fact", lambda p, w: (w, PASS, "stub file check")):
            got = self._window(100, 199, cutter=lambda s, d: {"path": "w.mp4", "frames": 373})
        self.assertEqual(got["outcome"], "fail")
        self.assertIn("373 with 100 ordered", [c["note"] for c in got["checks"]][-2])

    def test_a_cut_that_could_not_be_counted_is_not_a_defect(self):
        with mock.patch.object(E, "file_fact", lambda p, w: (w, PASS, "stub file check")):
            got = self._window(100, 199, cutter=lambda s, d: {"path": "w.mp4", "frames": None})
        self.assertEqual(got["outcome"], "could not measure")

    def test_the_cut_command_counts_frames_and_not_seconds(self):
        argv = E.cut_argv("in.mp4", "out.mp4", first=100, last=199, fps=30.0, exe="ffmpeg")
        self.assertIn("-frames:v", argv)
        self.assertEqual(argv[argv.index("-frames:v") + 1], "100")
        self.assertEqual(argv[argv.index("-ss") + 1], "3.333333")
        self.assertNotIn("-t", argv)


class MoneyGuards(unittest.TestCase):
    def test_pro_is_refused_before_any_money_is_spent(self):
        with self.assertRaises(ValueError) as e:
            E.refuse_pro("fal-ai/kling-video/v2.6/pro/motion-control")
        self.assertIn("12.8", str(e.exception))
        self.assertIsNone(E.refuse_pro("fal-ai/kling-video/v2.6/standard/motion-control"))
        self.assertIsNone(E.refuse_pro("fal-ai/proxy-kling/standard/motion-control"))

    def test_a_pro_endpoint_stops_the_stage_before_the_upload(self):
        called = []
        got = E.stage_kling(
            styled="s.png",
            window="w.mp4",
            out_path="o.mp4",
            upload=lambda p: called.append(p),
            kling=_kling_ok,
            endpoint="fal-ai/kling-video/v2.6/pro/motion-control",
        )
        self.assertEqual(got["outcome"], "fail")
        self.assertEqual(called, [])

    def test_the_payload_has_exactly_the_three_measured_fields(self):
        payload = E.kling_payload(video_url="v", image_url="i")
        self.assertEqual(sorted(payload), ["character_orientation", "image_url", "video_url"])
        self.assertEqual(payload["character_orientation"], "video")

    def test_an_orientation_outside_the_two_measured_values_is_refused(self):
        with self.assertRaises(ValueError):
            E.kling_payload(video_url="v", image_url="i", character_orientation="auto")
        for value in ("image", "video"):
            self.assertEqual(
                E.kling_payload(video_url="v", image_url="i", character_orientation=value)[
                    "character_orientation"
                ],
                value,
            )

    def test_a_field_added_to_the_payload_reddens_the_stage(self):
        with mock.patch.object(
            E,
            "kling_payload",
            lambda **kw: {
                "video_url": "v",
                "image_url": "i",
                "character_orientation": "video",
                "prompt": "an extra field",
            },
        ):
            got = E.stage_kling(
                styled="s.png", window="w.mp4", out_path="o.mp4", upload=_upload_ok, kling=_kling_ok
            )
        self.assertEqual(got["outcome"], "fail")
        self.assertIn("extra ['prompt']", [c["note"] for c in got["checks"]][-1])

    def test_a_failed_upload_never_reaches_the_paid_call(self):
        ordered = []

        def bad_upload(path):
            raise OSError("network unavailable")

        def counting_kling(**kw):
            ordered.append(kw)
            return "o.mp4"

        got = E.stage_kling(
            styled="s.png",
            window="w.mp4",
            out_path="o.mp4",
            upload=bad_upload,
            kling=counting_kling,
        )
        self.assertEqual(got["outcome"], "could not measure")
        self.assertEqual(ordered, [])


class OutputAcceptance(unittest.TestCase):
    def _accept(self, **over):
        kw = dict(
            produced="o.mp4",
            client_photo="c.png",
            frames_dir="f",
            probe=_probe_ok,
            decode=_decode_ok,
            distances=_distances_ok,
            cuts=_cuts_ok,
        )
        kw.update(over)
        return E.stage_output_acceptance(**kw)

    def test_any_vertical_geometry_passes_and_landscape_is_a_defect(self):
        self.assertEqual(self._accept()["outcome"], "pass")
        vertical = lambda p: {
            "outcome": PASS,
            "fps": 30.0,
            "frames": 99,
            "width": 720,
            "height": 1280,
            "note": "",
        }
        self.assertEqual(self._accept(probe=vertical)["outcome"], "pass")
        landscape = lambda p: {
            "outcome": PASS,
            "fps": 30.0,
            "frames": 99,
            "width": 1280,
            "height": 720,
            "note": "",
        }
        self.assertEqual(self._accept(probe=landscape)["outcome"], "fail")

    def test_the_ratio_ceiling_moved_flips_the_verdict_both_ways(self):
        square = lambda p: {
            "outcome": PASS,
            "fps": 30.0,
            "frames": 99,
            "width": 960,
            "height": 960,
            "note": "",
        }
        with mock.patch.object(E, "OUT_RATIO_MAX", 0.9):
            self.assertEqual(self._accept(probe=square)["outcome"], "fail")
        with mock.patch.object(E, "OUT_RATIO_MAX", 1.5):
            self.assertEqual(self._accept(probe=square)["outcome"], "pass")

    def test_a_single_cut_on_the_output_is_a_defect(self):
        one = lambda paths, **kw: {"outcome": PASS, "cuts": [37], "note": ""}
        self.assertEqual(self._accept(cuts=one)["outcome"], "fail")
        with mock.patch.object(E, "MAX_CUTS_OUT", 1):
            self.assertEqual(self._accept(cuts=one)["outcome"], "pass")

    def test_cuts_that_could_not_be_looked_for_are_not_zero_cuts(self):
        blind = lambda paths, **kw: {
            "outcome": UNMEASURED,
            "cuts": [],
            "note": "the typical jump equals zero",
        }
        got = self._accept(cuts=blind)
        self.assertEqual(got["outcome"], "could not measure")
        self.assertIsNone(got["numbers"]["cuts"])

    def test_no_frames_decoded_is_unmeasured_and_stops_before_judging(self):
        empty = lambda v, d: {"paths": [], "note": "the layout is empty"}
        got = self._accept(decode=empty)
        self.assertEqual(got["outcome"], "could not measure")
        self.assertEqual([c["name"] for c in got["checks"]], ["output geometry", "frame layout"])


class NeighbourModulesAreSoft(unittest.TestCase):
    """A missing neighbour is "could not measure", and it says who exactly is missing."""

    def test_a_missing_intake_module_is_unmeasured_not_a_defect(self):
        with TemporaryDirectory() as td:
            f = _files(Path(td))
            with mock.patch.object(
                E, "soft_import", lambda name: (None, f"module lipsync.{name} is missing")
            ):
                got = E.stage_intake(
                    client_photo=f["client"], style_ref=f["style"], driving=f["driving"]
                )
        self.assertEqual(got["outcome"], "could not measure")
        self.assertIn("fork_intake", got["note"])
        self.assertEqual((got["checked"], got["violations"], got["unmeasured"]), (3, 0, 1))

    def test_a_missing_input_file_is_a_defect_even_without_the_neighbour(self):
        with TemporaryDirectory() as td:
            f = _files(Path(td))
            f["driving"].unlink()
            with mock.patch.object(E, "soft_import", lambda name: (None, "no neighbour")):
                got = E.stage_intake(
                    client_photo=f["client"], style_ref=f["style"], driving=f["driving"]
                )
        self.assertEqual(got["outcome"], "fail")

    def test_a_neighbour_that_raises_is_unmeasured(self):
        def boom(**kw):
            raise KeyError("not written yet")

        with TemporaryDirectory() as td:
            f = _files(Path(td))
            got = E.stage_intake(
                client_photo=f["client"], style_ref=f["style"], driving=f["driving"], intake=boom
            )
        self.assertEqual(got["outcome"], "could not measure")
        self.assertIn("KeyError", got["checks"][-1]["note"])

    def test_a_neighbour_answering_without_a_verdict_is_not_a_success(self):
        got = E.outcome_of("done", what="fork_finish")
        self.assertEqual(got[0], "could not measure")
        self.assertEqual(E.outcome_of({"outcome": "pass"}, what="x")[0], "pass")

    def test_a_neighbour_taking_positional_arguments_is_still_called(self):
        seen = []

        def positional(a, b, c):
            seen.append((a, b, c))
            return {"outcome": PASS, "note": "positionally"}

        with TemporaryDirectory() as td:
            f = _files(Path(td))
            got = E.stage_intake(
                client_photo=f["client"],
                style_ref=f["style"],
                driving=f["driving"],
                intake=positional,
            )
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(len(seen), 1)

    def test_the_entry_point_refusal_names_what_was_tried(self):
        class Empty:
            __name__ = "lipsync.fork_finish"

        fn, name, why = E.entry_point(Empty(), ("finish", "assemble"))
        self.assertIsNone(fn)
        self.assertIn("['finish', 'assemble']", why)


class FinishSeam(unittest.TestCase):
    """The assembler neighbour takes the driving first. A mixed-up order is not a detail."""

    def test_the_neighbour_gets_the_driving_first_and_the_window_inclusive(self):
        seen = {}

        def finish(*, driving_path, kling_path, out_path, window):
            seen.update(driving_path=driving_path, kling_path=kling_path, window=window)
            Path(out_path).write_bytes(b"\x00")
            return {"outcome": PASS, "path": out_path, "note": ""}

        with TemporaryDirectory() as td:
            got = E.stage_finish(
                produced="kling.mp4",
                driving="drv.mp4",
                out_path=Path(td) / "final.mp4",
                window=(100, 199),
                finish=finish,
            )
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(seen["driving_path"], "drv.mp4")
        self.assertEqual(seen["kling_path"], "kling.mp4")
        self.assertEqual(seen["window"], (100, 199))

    def test_a_neighbour_verdict_of_unmeasured_is_carried_through(self):
        def finish(**kw):
            return {"outcome": UNMEASURED, "note": "the duration could not be read"}

        got = E.stage_finish(
            produced="k.mp4", driving="d.mp4", out_path="f.mp4", window=(0, 99), finish=finish
        )
        self.assertEqual(got["outcome"], "could not measure")


class IntakeSeam(unittest.TestCase):
    """The intake neighbour has three functions, not one. The shape is measured, not guessed."""

    def test_the_three_intake_functions_are_all_called(self):
        seen = []

        class Trio:
            __name__ = "lipsync.fork_intake"

            @staticmethod
            def photo_intake(path, **kw):
                seen.append(("photo", path))
                return {
                    "outcome": PASS,
                    "checked": 3,
                    "violations": 0,
                    "unmeasured": 0,
                    "note": "one face",
                }

            @staticmethod
            def style_intake(path, **kw):
                seen.append(("style", path))
                return {
                    "outcome": PASS,
                    "checked": 1,
                    "violations": 0,
                    "unmeasured": 0,
                    "note": "the card is readable",
                }

            @staticmethod
            def driving_intake(path, frames=None, **kw):
                seen.append(("driving", path))
                return {
                    "outcome": PASS,
                    "checked": 5,
                    "violations": 0,
                    "unmeasured": 0,
                    "note": "cuts 0",
                }

        with TemporaryDirectory() as td:
            f = _files(Path(td))
            with mock.patch.object(E, "soft_import", lambda n: (Trio(), None)):
                got = E.stage_intake(
                    client_photo=f["client"], style_ref=f["style"], driving=f["driving"]
                )
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual([kind for kind, _ in seen], ["photo", "style", "driving"])
        self.assertEqual(got["checked"], 6)
        self.assertIn("checked 5, violations 0, unmeasured 0", got["checks"][-1]["note"])

    def test_one_refused_input_reddens_the_stage_and_the_others_still_ran(self):
        class Trio:
            __name__ = "lipsync.fork_intake"

            @staticmethod
            def photo_intake(path, **kw):
                return {
                    "outcome": FAIL,
                    "checked": 3,
                    "violations": 1,
                    "unmeasured": 0,
                    "note": "two faces in the photo",
                }

            @staticmethod
            def style_intake(path, **kw):
                return {"outcome": PASS, "checked": 1, "violations": 0, "unmeasured": 0, "note": ""}

            @staticmethod
            def driving_intake(path, frames=None, **kw):
                return {
                    "outcome": UNMEASURED,
                    "checked": 1,
                    "violations": 0,
                    "unmeasured": 4,
                    "note": "no frames were supplied",
                }

        with TemporaryDirectory() as td:
            f = _files(Path(td))
            with mock.patch.object(E, "soft_import", lambda n: (Trio(), None)):
                got = E.stage_intake(
                    client_photo=f["client"], style_ref=f["style"], driving=f["driving"]
                )
        self.assertEqual(got["outcome"], "fail")
        self.assertEqual((got["checked"], got["violations"], got["unmeasured"]), (5, 1, 1))

    def test_the_card_reader_is_handed_to_the_style_intake_only(self):
        """Without a card reader the style neighbour honestly halts: this is MEASURED."""
        seen = {}

        class Trio:
            __name__ = "lipsync.fork_intake"

            @staticmethod
            def photo_intake(path, **kw):
                seen["photo_kw"] = kw
                return {"outcome": PASS, "checked": 1, "violations": 0, "unmeasured": 0, "note": ""}

            @staticmethod
            def style_intake(path, card_reader=None, **kw):
                seen["reader"] = card_reader
                return {
                    "outcome": PASS if card_reader else UNMEASURED,
                    "checked": 1 if card_reader else 0,
                    "violations": 0,
                    "unmeasured": 0 if card_reader else 1,
                    "note": "",
                }

            @staticmethod
            def driving_intake(path, frames=None, **kw):
                seen["frames"] = frames
                return {"outcome": PASS, "checked": 1, "violations": 0, "unmeasured": 0, "note": ""}

        reader = lambda p: {"card": {}}
        with TemporaryDirectory() as td:
            f = _files(Path(td))
            with mock.patch.object(E, "soft_import", lambda n: (Trio(), None)):
                with_reader = E.stage_intake(
                    client_photo=f["client"],
                    style_ref=f["style"],
                    driving=f["driving"],
                    card_reader=reader,
                    driving_frames=["a.png"],
                )
                without = E.stage_intake(
                    client_photo=f["client"], style_ref=f["style"], driving=f["driving"]
                )
        self.assertEqual(with_reader["outcome"], "pass")
        self.assertEqual(without["outcome"], "could not measure")
        self.assertEqual(seen["photo_kw"], {})
        self.assertEqual(seen["frames"], None)


class BrandBanIsInThePrompt(unittest.TestCase):
    def test_the_prompt_carries_the_ban_and_the_roles(self):
        built = E.style_prompt("style.png", card_reader=lambda p: {})
        self.assertIn("no logo", built["prompt"])
        self.assertNotIn("no brand names", built["prompt"])
        self.assertIn("FIRST image", built["prompt"])
        self.assertIn("SECOND image", built["prompt"])

    def test_a_readable_style_card_adds_words_but_the_ban_stays(self):
        card = {
            "colours": ["sky blue", "chocolate", "blue"],
            "value_key": "mid",
            "saturation": "saturated",
            "texture": "clean flat surfaces",
        }
        built = E.style_prompt("style.png", card_reader=lambda p: card)
        self.assertIn("sky blue", built["prompt"])
        self.assertIn("no logo", built["prompt"])
        self.assertNotIn("no brand names", built["prompt"])

    def test_a_prompt_without_the_ban_reddens_the_stage(self):
        """Negative control of the guard: without it the check is always green."""
        with TemporaryDirectory() as td:
            got = E.stage_stylize(
                client_photo="c.png",
                style_ref="s.png",
                out_path=Path(td) / "styled.png",
                stylize=_stylize_ok,
                plan=_PlanOk,
                pose=_pose_ok,
                prompt="just make it look nice",
            )
            self.assertEqual(got["outcome"], "fail")
            self.assertEqual(got["checks"][0]["outcome"], "fail")
            ok = E.stage_stylize(
                client_photo="c.png",
                style_ref="s.png",
                out_path=Path(td) / "styled.png",
                stylize=_stylize_ok,
                plan=_PlanOk,
                pose=_pose_ok,
                prompt="a look, " + E.NO_BRANDS_CLAUSE,
            )
            self.assertEqual(ok["outcome"], "pass")

    def test_the_ban_text_itself_is_a_decision_constant(self):
        with mock.patch.object(E, "NO_BRANDS_CLAUSE", "no logos whatsoever"):
            with TemporaryDirectory() as td:
                got = E.stage_stylize(
                    client_photo="c.png",
                    style_ref="s.png",
                    out_path=Path(td) / "styled.png",
                    stylize=_stylize_ok,
                    plan=_PlanOk,
                    pose=_pose_ok,
                    prompt="a look, no brand names, no logos",
                )
        self.assertEqual(got["outcome"], "fail")

    def test_a_stylizer_that_fell_is_unmeasured(self):
        def boom(**kw):
            raise RuntimeError("HTTP 524")

        got = E.stage_stylize(
            client_photo="c.png",
            style_ref="s.png",
            out_path="styled.png",
            stylize=boom,
            card_reader=lambda p: {},
        )
        self.assertEqual(got["outcome"], "could not measure")


class WindowArgument(unittest.TestCase):
    def test_a_window_is_parsed_and_garbage_is_refused(self):
        self.assertEqual(E.parse_window("100:199"), (100, 199))
        for bad in ("100", "100:", "a:b", "199:100", "100:199:2"):
            with self.assertRaises(ValueError, msg=bad):
                E.parse_window(bad)


class ReportIsAlwaysWritten(unittest.TestCase):
    def test_the_report_survives_an_early_stop_and_carries_numbers(self):
        import json

        def falling(**kw):
            raise RuntimeError("503")

        log = io.StringIO()
        with TemporaryDirectory() as td, _no_network():
            got = _run(Path(td), log, kling=falling)
            data = json.loads(Path(got["report"]).read_text(encoding="utf-8"))
        self.assertEqual(got["stages"][-1]["stage"], "8 report")
        self.assertEqual(len(data["stages"]), 5)
        self.assertEqual(data["unmeasured"], 1)
        self.assertEqual(data["violations"], 0)


class TheStyliserIsAskedForThePlanNotForWhateverTheRouteDefaultsTo(unittest.TestCase):
    """MEASURED defect: `pollinations.compose` alone defaulted to 768x1024 while its
    two sibling routes defaulted to 1080x1920, and `live_stylize` passed no size at
    all. So the styliser was asked for 3:4 and honestly returned 3:4 (896x1200) —
    and every padded band downstream was our own request coming back."""

    def test_the_asked_size_is_exactly_9_16(self):
        w, h = E.STYLED_SIZE
        self.assertEqual(w * 16, h * 9, f"{w}x{h} is not 9:16")

    def test_both_sides_sit_on_the_grid_the_model_snaps_to(self):
        """MEASURED: asked 768x1024, the model returned 896x1200 = 56x16 by 75x16.
        An off-grid 9:16 such as 1080x1920 would be snapped sideways and stop
        being 9:16 — which is the whole defect, re-entered through the fix."""
        for side in E.STYLED_SIZE:
            self.assertEqual(side % 16, 0, f"{side} is not a multiple of 16")

    def test_the_asked_size_reaches_the_gateway_call(self):
        from lipsync import pollinations

        seen = {}

        def compose(prompt, urls, out_path, **kw):
            seen.update(kw)
            seen["urls"] = list(urls)
            return str(out_path)

        with (
            mock.patch.object(pollinations, "upload", lambda p: f"u://{p}"),
            mock.patch.object(pollinations, "compose", compose),
        ):
            E.live_stylize(person="c.png", style="s.png", prompt="p", out_path="o.png")
        self.assertEqual((seen.get("width"), seen.get("height")), E.STYLED_SIZE)
        self.assertEqual(seen.get("model"), E.STYLE_MODEL)
        self.assertEqual(len(seen["urls"]), E.STYLE_IMAGES)

    def test_the_gateway_default_no_longer_disagrees_with_its_siblings(self):
        """The trap was that one route out of three defaulted to 3:4. A caller that
        forgets the size must now land on the plan, not on a letterbox."""
        import inspect

        from lipsync import pollinations

        sizes = {}
        for name in ("image", "images_edit", "compose"):
            params = inspect.signature(getattr(pollinations, name)).parameters
            sizes[name] = (params["width"].default, params["height"].default)
        self.assertEqual(len(set(sizes.values())), 1, sizes)
        w, h = sizes["compose"]
        self.assertEqual(w * 16, h * 9, f"the gateway default {w}x{h} is not 9:16")


if __name__ == "__main__":
    unittest.main()


class TheStyliserWasChosenByEyeNotByNumber(unittest.TestCase):
    """The template author's decision: `nanobanana-2`, despite the number."""

    def test_the_chosen_styliser_is_the_one_the_owner_picked(self):
        self.assertEqual(E.STYLE_MODEL, "nanobanana-2")

    def test_the_rejected_styliser_scored_HIGHER_and_is_still_rejected(self):
        self.assertGreater(E.STYLE_HIT_REJECTED, E.STYLE_HIT_REFERENCE)
        self.assertNotEqual(E.STYLE_MODEL, "gpt-image-2")

    def test_the_chosen_styliser_still_beats_the_floor(self):
        self.assertGreater(E.STYLE_HIT_REFERENCE, E.STYLE_FLOOR_REFERENCE)

    def test_the_text_route_stays_below_the_floor_margin(self):
        self.assertLess(E.STYLE_TEXT_ROUTE_REFERENCE - E.STYLE_FLOOR_REFERENCE, 0.05)


class TheStyleReferenceLeaksAppearanceAndItIsGuarded(unittest.TestCase):
    """A live run put the reference's glasses on the client during stylization."""

    def test_the_prompt_forbids_copying_eyewear_from_the_reference(self):
        built = E.style_prompt("any.png", card_reader=lambda p: None)
        for word in ("eyewear", "accessory", "garment", "pose"):
            with self.subTest(word=word):
                self.assertIn(word, built["prompt"])

    def test_the_role_clause_names_what_to_KEEP_not_only_what_to_take(self):
        built = E.style_prompt("any.png", card_reader=lambda p: None)
        for word in ("same clothing", "same pose", "same accessories"):
            with self.subTest(word=word):
                self.assertIn(word, built["prompt"])

    def test_the_two_bans_are_separate_constants_with_separate_histories(self):
        self.assertNotEqual(E.NO_BRANDS_CLAUSE, E.NO_LOOK_TRANSFER_CLAUSE)
        self.assertNotIn(E.NO_BRANDS_CLAUSE, E.NO_LOOK_TRANSFER_CLAUSE)

    def test_removing_the_look_ban_is_visible_in_the_prompt(self):
        built = E.style_prompt("any.png", card_reader=lambda p: None)
        self.assertIn(E.NO_LOOK_TRANSFER_CLAUSE, built["prompt"])


class TheIdentityAxisHasAMiddleBandAndAnOperatorOverride(unittest.TestCase):
    """The template author's decision: glasses from the style are a feature, not a bug."""

    def _stage(self, median, **kw):
        return E.stage_style_acceptance(
            styled="s.png",
            style_ref="r.png",
            client_photo="p.png",
            similarity=lambda a, b: 0.9 if "s.png" in str(b) else 0.2,
            distances=lambda fr, an: {"outcome": E.PASS, "median": median},
            **kw,
        )

    def _axis(self, res):
        return [c for c in res["checks"] if "identity" in c["name"]][0]

    def test_below_the_bar_is_plainly_good(self):
        self.assertEqual(self._axis(self._stage(0.0652))["outcome"], E.PASS)

    def test_the_middle_band_is_UNMEASURED_not_failed(self):
        self.assertEqual(self._axis(self._stage(0.3928))["outcome"], E.UNMEASURED)

    def test_the_middle_band_passes_only_with_an_explicit_operator_flag(self):
        got = self._axis(self._stage(0.3928, operator_ok_identity=True))
        self.assertEqual(got["outcome"], E.PASS)
        self.assertIn("admitted by the operator", got["note"])

    def test_above_the_other_person_rung_stays_FAILED_even_for_the_operator(self):
        got = self._axis(self._stage(0.80, operator_ok_identity=True))
        self.assertEqual(got["outcome"], E.FAIL)

    def test_the_ladder_numbers_are_the_measured_ones(self):
        self.assertEqual(E.LADDER_SAME, 0.0652)
        self.assertEqual(E.LADDER_REJECTED, 0.7137)
        self.assertEqual(E.LADDER_STRANGER, 1.0217)


class TheGeometryCheckGuardsVerticalityNotExactNumbers(unittest.TestCase):
    """A live run returned 816x1104 — vertical — and the instrument rejected it."""

    def _geom(self, w, h, fps=30.0, **kw):
        res = E.stage_output_acceptance(
            produced="p.mp4",
            client_photo="c.png",
            frames_dir="d",
            probe=lambda p: {"width": w, "height": h, "fps": fps, "frames": 99},
            decode=_decode_ok,
            distances=lambda fr, an: {
                "outcome": E.PASS,
                "median": 0.20,
                "inside": 99,
                "judged": 99,
            },
            cuts=lambda p: {"outcome": E.PASS, "cuts": [], "note": ""},
            **kw,
        )
        return [c for c in res["checks"] if "geometry" in c["name"]][0]

    def test_the_new_vertical_output_passes(self):
        got = self._geom(816, 1104)
        self.assertEqual(got["outcome"], E.PASS)
        self.assertIn("new geometry", got["note"])

    def test_the_old_square_output_still_passes(self):
        self.assertEqual(self._geom(960, 960)["outcome"], E.PASS)

    def test_a_landscape_output_is_a_defect(self):
        self.assertEqual(self._geom(1104, 816)["outcome"], E.FAIL)

    def test_a_wrong_fps_is_UNMEASURED_not_failed(self):
        self.assertEqual(self._geom(816, 1104, fps=24.0)["outcome"], E.UNMEASURED)

    def test_the_ratio_ceiling_is_the_chosen_one(self):
        self.assertEqual(E.OUT_RATIO_MAX, 1.0)


class TheOutputIdentityUsesTheSameLadderAsTheStyledPhoto(unittest.TestCase):
    """One knowledge — one place: the ladder on the output is the same as on the photo."""

    def _axis(self, median, **kw):
        res = E.stage_output_acceptance(
            produced="p.mp4",
            client_photo="c.png",
            frames_dir="d",
            probe=lambda p: {"width": 816, "height": 1104, "fps": 30.0, "frames": 99},
            decode=_decode_ok,
            distances=lambda fr, an: {
                "outcome": E.PASS,
                "median": median,
                "inside": 0,
                "judged": 99,
            },
            cuts=lambda p: {"outcome": E.PASS, "cuts": [], "note": ""},
            **kw,
        )
        return [c for c in res["checks"] if "identity" in c["name"]][0]

    def test_the_measured_occluded_case_is_UNMEASURED(self):
        self.assertEqual(self._axis(0.5109)["outcome"], E.UNMEASURED)

    def test_the_operator_can_let_the_occluded_case_through(self):
        got = self._axis(0.5109, operator_ok_identity=True)
        self.assertEqual(got["outcome"], E.PASS)
        self.assertIn("admitted by the operator", got["note"])

    def test_a_real_swap_is_failed_even_for_the_operator(self):
        self.assertEqual(self._axis(0.90, operator_ok_identity=True)["outcome"], E.FAIL)


class TheDeliverableIsBuiltEvenWhenIdentityCannotBeMeasured(unittest.TestCase):
    """Stage 7 is mechanical, and a "could not measure" on stage 6 does not cancel it."""

    @staticmethod
    def _on_output(median):
        def distances(frames, anchor, **kw):
            if len(frames) == 1:
                return {
                    "outcome": PASS,
                    "median": 0.0652,
                    "inside": 1,
                    "judged": 1,
                    "note": "stub identity instrument",
                }
            return {
                "outcome": PASS,
                "median": median,
                "inside": 0,
                "judged": len(frames),
                "note": "output frames",
            }

        return distances

    @property
    def _band(self):
        """Middle band of the ladder: 0.5109 is a live measurement."""
        return self._on_output(0.5109)

    @property
    def _swap(self):
        """Above the "other person" rung 0.7137 — a real swap."""
        return self._on_output(0.9)

    def test_an_unmeasurable_identity_still_yields_the_final_file(self):
        log = io.StringIO()
        with TemporaryDirectory() as td, _no_network():
            root = Path(td)
            got = _run(root, log, distances=self._band)
            final = root / "out" / "final_9x16.mp4"
            self.assertTrue(final.exists(), "the final file is missing — nothing to judge by")
        names = [s["stage"] for s in got["stages"]]
        self.assertIn(E.STAGES[6], names)

    def test_but_the_verdict_is_NOT_whitewashed_into_good(self):
        log = io.StringIO()
        with TemporaryDirectory() as td, _no_network():
            got = _run(Path(td), log, distances=self._band)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertEqual(got["exit_code"], 2)
        self.assertEqual(got["stopped_at"], E.STAGES[5])

    def test_a_real_swap_still_stops_before_the_finish(self):
        log = io.StringIO()
        with TemporaryDirectory() as td, _no_network():
            root = Path(td)
            got = _run(root, log, distances=self._swap)
            self.assertFalse((root / "out" / "final_9x16.mp4").exists())
        self.assertEqual(got["outcome"], FAIL)
        self.assertNotIn(E.STAGES[6], [s["stage"] for s in got["stages"]])

    def test_the_operator_flag_reaches_run_from_the_command_line(self):
        seen = {}

        def fake_run(**kw):
            seen.update(kw)
            return {"exit_code": 0}

        with mock.patch.object(E, "run", fake_run):
            E.main(
                [
                    "--client",
                    "c.png",
                    "--style",
                    "s.png",
                    "--driving",
                    "d.mp4",
                    "--window",
                    "100:199",
                    "--operator-ok-identity",
                ]
            )
        self.assertIs(seen["operator_ok_identity"], True)
        seen.clear()
        with mock.patch.object(E, "run", fake_run):
            E.main(
                [
                    "--client",
                    "c.png",
                    "--style",
                    "s.png",
                    "--driving",
                    "d.mp4",
                    "--window",
                    "100:199",
                ]
            )
        self.assertIs(seen["operator_ok_identity"], False)


class TheFramesChannelReachesRunFromTheCommandLine(unittest.TestCase):
    """A channel that is parsed and lost looks functional until a run."""

    def _seen(self, argv):
        seen = {}

        def fake_run(**kw):
            seen.update(kw)
            return {"exit_code": 0}

        with mock.patch.object(E, "run", fake_run):
            E.main(
                [
                    "--client",
                    "c.png",
                    "--style",
                    "s.png",
                    "--driving",
                    "d.mp4",
                    "--window",
                    "100:199",
                    *argv,
                ]
            )
        return seen

    def test_the_frames_arrive_sorted_and_whole(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            for i in (3, 1, 2):
                (root / f"f{i:05d}.png").write_bytes(b"\x00")
            got = self._seen(["--frames", str(root)])
        self.assertEqual(
            [Path(p).name for p in got["driving_frames"]],
            ["f00001.png", "f00002.png", "f00003.png"],
        )

    def test_without_the_flag_the_frames_are_None_not_an_empty_list(self):
        self.assertIsNone(self._seen([])["driving_frames"])

    def test_a_missing_directory_is_refused_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            E.frame_paths("no-such-directory")

    def test_an_empty_directory_is_refused_not_silently_ignored(self):
        with TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                E.frame_paths(td)

    def test_non_frames_do_not_count_as_frames(self):
        with TemporaryDirectory() as td:
            (Path(td) / "report.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                E.frame_paths(td)


class ThePriceIsPerSecondNotPerCall(unittest.TestCase):
    """The second MEASURED price corrects the first, and a literal guards the number."""

    def test_the_measured_numbers_are_the_ones_shipped(self):
        self.assertEqual(E.KLING_PRICE_PER_SECOND_USD, 0.07)
        self.assertEqual(E.PRODUCT_SECONDS, 5.0)
        self.assertEqual(E.KLING_PRICE_USD, 0.35)
        self.assertEqual(E.KLING_PRICE_3S_USD, 0.21)

    def test_both_measurements_land_on_the_same_per_second_price(self):
        self.assertEqual(E.kling_price(3), 0.21)
        self.assertEqual(E.kling_price(5), 0.35)

    def test_the_owner_matrix_now_costs_seven_dollars_not_four_twenty(self):
        self.assertEqual(round(20 * E.KLING_PRICE_USD, 2), 7.0)
        self.assertEqual(round(20 * E.KLING_PRICE_3S_USD, 2), 4.2)

    def test_a_nonsense_duration_is_refused_not_guessed(self):
        for bad in (0, -5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                E.kling_price(bad)
        for bad in ("5", None, True):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                E.kling_price(bad)


class TheStandActuallyCallsItsNeighbours(unittest.TestCase):
    """The `fork_aesthetic` and `fork_plan` neighbours are actually called, not just written."""

    def test_the_neighbours_are_imported_for_real_not_by_string(self):
        self.assertTrue(hasattr(E._default_aesthetic(), "gender_of"))
        self.assertTrue(hasattr(E._default_plan(), "to_plan"))

    def test_the_plan_step_changes_which_file_goes_on(self):
        with TemporaryDirectory() as td:
            got = E.stage_stylize(
                client_photo="c.png",
                style_ref="s.png",
                out_path=Path(td) / "styled.png",
                stylize=_stylize_ok,
                plan=_PlanOk,
                pose=_pose_ok,
                prompt="a look, " + E.NO_BRANDS_CLAUSE,
            )
        self.assertTrue(got["styled"].endswith("_9x16.png"), got["styled"])
        names = [c["name"] for c in got["checks"]]
        self.assertIn("styliser returned the plan", names)

    def test_the_outpaint_is_NOT_called_when_nothing_was_padded(self):
        """A no-op outpaint is a paid generation that can repaint the person."""
        with TemporaryDirectory() as td:
            got = E.stage_stylize(
                client_photo="c.png",
                style_ref="s.png",
                out_path=Path(td) / "styled.png",
                stylize=_stylize_ok,
                plan=_PlanOk,
                pose=_pose_ok,
                extend=lambda *a, **k: self.fail("the outpainter must not be called"),
                prompt="a look, " + E.NO_BRANDS_CLAUSE,
            )
        outpaint = [c for c in got["checks"] if c["name"] == "margin outpaint"]
        self.assertEqual([c["outcome"] for c in outpaint], [PASS])
        self.assertIn("not called", outpaint[0]["note"])
        self.assertTrue(got["styled"].endswith("_9x16.png"), got["styled"])

    def test_a_plan_that_could_not_be_laid_is_UNMEASURED_not_a_defect(self):
        class Broken:
            @staticmethod
            def to_plan(src, dst, **kw):
                raise OSError("the image did not open")

        with TemporaryDirectory() as td:
            got = E.stage_stylize(
                client_photo="c.png",
                style_ref="s.png",
                out_path=Path(td) / "styled.png",
                stylize=_stylize_ok,
                plan=Broken,
                prompt="a look, " + E.NO_BRANDS_CLAUSE,
            )
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertTrue(got["styled"].endswith("styled.png"))


class TheGenderGateStopsTheRunBeforeAnyGeneration(unittest.TestCase):
    """It is MEASURED how its absence ends: a male client with a female aesthetic."""

    class _A:
        """Stub aesthetic neighbour with the real signature."""

        calls: list = []

        @staticmethod
        def gender_of(aid):
            return "f"

        @staticmethod
        def pair_check(*, client_gender, aesthetic_gender):
            ok = client_gender == aesthetic_gender
            return {
                "outcome": PASS if ok else FAIL,
                "checked": 1,
                "violations": 0 if ok else 1,
                "unmeasured": 0,
                "note": "stub gate",
            }

        @staticmethod
        def aesthetic_file(aid):
            return f"assets/aesthetics/{aid}_f.png"

        @staticmethod
        def compose(aid, *, card=None):
            return {"prompt": "aesthetic in words"}

        @staticmethod
        def assemble_prompt(*, card=None):
            return "roles, " + E.NO_BRANDS_CLAUSE

    def test_a_mismatched_gender_stops_before_the_styliser_is_called(self):
        seen = []

        def counting(**kw):
            seen.append(kw)
            return kw["out_path"]

        with TemporaryDirectory() as td:
            got = E.stage_stylize(
                client_photo="c.png",
                style_ref="s.png",
                out_path=Path(td) / "styled.png",
                stylize=counting,
                plan=_PlanOk,
                pose=_pose_ok,
                aesthetic="y2k",
                client_gender="m",
                aesthetic_mod=self._A,
            )
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(seen, [], "the styliser was called despite the gender mismatch")
        self.assertIn("generation was not started", got["note"])

    def test_a_matching_gender_goes_through_and_uses_the_aesthetic_file(self):
        seen = {}

        def counting(**kw):
            seen.update(kw)
            Path(kw["out_path"]).write_bytes(b"\x00" * 64)
            return kw["out_path"]

        with TemporaryDirectory() as td:
            got = E.stage_stylize(
                client_photo="c.png",
                style_ref="foreign.png",
                out_path=Path(td) / "styled.png",
                stylize=counting,
                plan=_PlanOk,
                pose=_pose_ok,
                aesthetic="y2k",
                client_gender="f",
                aesthetic_mod=self._A,
            )
        self.assertEqual(got["outcome"], PASS)
        self.assertIn("y2k_f.png", seen["style"])
        self.assertNotIn("foreign", seen["style"])
        self.assertIn("aesthetic in words", seen["prompt"])


class TheTemplateFlagsReachRunFromTheCommandLine(unittest.TestCase):
    """A flag that is parsed and lost looks functional until a run."""

    def _seen(self, argv):
        seen = {}

        def fake_run(**kw):
            seen.update(kw)
            return {"exit_code": 0}

        with mock.patch.object(E, "run", fake_run):
            E.main(argv)
        return seen

    def test_the_aesthetic_and_gender_travel_to_run(self):
        got = self._seen(
            [
                "--client",
                "c.png",
                "--driving",
                "d.mp4",
                "--window",
                "100:199",
                "--aesthetic",
                "y2k",
                "--client-gender",
                "f",
            ]
        )
        self.assertEqual(got["aesthetic"], "y2k")
        self.assertEqual(got["client_gender"], "f")

    def test_an_aesthetic_without_a_gender_is_refused(self):
        with self.assertRaises(SystemExit):
            self._seen(
                [
                    "--client",
                    "c.png",
                    "--driving",
                    "d.mp4",
                    "--window",
                    "100:199",
                    "--aesthetic",
                    "y2k",
                ]
            )

    def test_neither_style_nor_aesthetic_is_refused(self):
        with self.assertRaises(SystemExit):
            self._seen(["--client", "c.png", "--driving", "d.mp4", "--window", "100:199"])

    def test_the_old_style_path_still_works_without_an_aesthetic(self):
        got = self._seen(
            ["--client", "c.png", "--style", "s.png", "--driving", "d.mp4", "--window", "100:199"]
        )
        self.assertIsNone(got["aesthetic"])
        self.assertEqual(got["style_ref"], "s.png")


class TheOutpaintFixesTheLetterboxWithoutLosingTheRun(unittest.TestCase):
    """The plan margins show as bands. The instrument says "pass": it checks the canvas."""

    class _PlanNoExtend:
        ANKLES_BAND = fork_plan.ANKLES_BAND
        CENTRE_TOL = fork_plan.CENTRE_TOL
        SHOULDERS_BAND = fork_plan.SHOULDERS_BAND
        WIDTH_MAX = fork_plan.WIDTH_MAX
        person_box = staticmethod(fork_plan.person_box)
        ratio_axis = staticmethod(fork_plan.ratio_axis)

        @staticmethod
        def to_plan(src, dst, **kw):
            Path(dst).write_bytes(b"\x00" * 64)
            return {
                "outcome": PASS,
                "checked": 1,
                "violations": 0,
                "unmeasured": 0,
                "path": str(dst),
                # The old 3:4 return, kept alive on purpose: this is the case the
                # outpaint exists to repair.
                "source": {"width": 896, "height": 1200},
                "plan": {"added_share": 0.2469},
                "note": "plan",
            }

        @staticmethod
        def extend_to_plan(src, dst, *, extender=None, **kw):
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "path": str(src),
                "extended": False,
                "note": "the outpainter did not answer",
            }

    def _padded(self):
        with TemporaryDirectory() as td:
            return E.stage_stylize(
                client_photo="c.png",
                style_ref="s.png",
                out_path=Path(td) / "styled.png",
                stylize=_stylize_ok,
                plan=self._PlanNoExtend,
                pose=_pose_ok,
                prompt="a look, " + E.NO_BRANDS_CLAUSE,
            )

    def test_a_styliser_that_ignored_the_asked_size_reddens_the_stage(self):
        """MEASURED defect: nobody asked this route for a vertical frame, and the
        reference arrived 896x1200. Now the size is asked for explicitly, so a 3:4
        answer is a violation of the request — and it stops the run BEFORE the
        one paid call, not after it."""
        got = self._padded()
        self.assertEqual(got["outcome"], FAIL)
        named = {c["name"]: c for c in got["checks"]}
        self.assertEqual(named["styliser returned the plan"]["outcome"], FAIL)
        self.assertIn("720x1280", named["styliser returned the plan"]["note"])
        self.assertIn("896x1200", named["styliser returned the plan"]["note"])

    def test_the_repair_still_runs_so_a_padded_reference_is_never_shipped_as_is(self):
        """The outpaint is not deleted, it is demoted: it only runs on the repair
        path, and its refusal is visible on its own line."""
        got = self._padded()
        named = {c["name"]: c for c in got["checks"]}
        self.assertEqual(named["margin outpaint"]["outcome"], UNMEASURED)
        self.assertIn("repairing a padded reference", named["margin outpaint"]["note"])
        self.assertTrue(got["styled"].endswith("_9x16.png"), got["styled"])

    def test_the_extend_prompt_forbids_redrawing_the_person(self):
        from lipsync import fork_plan

        self.assertIn("do not move, rescale, recrop or alter the person", fork_plan.extend_prompt())
        self.assertIn("no logo", fork_plan.extend_prompt())

    def test_removing_the_keep_clause_is_visible_in_the_prompt(self):
        from lipsync import fork_plan

        with mock.patch.object(fork_plan, "KEEP_SUBJECT_CLAUSE", ""):
            self.assertNotIn("alter the person", fork_plan.extend_prompt())


class ThePrintedPriceFollowsTheWindowLength(unittest.TestCase):
    """MEASURED: on a ten-second run the stand printed "$0.35" instead of the real price."""

    @staticmethod
    def _probe(frames, fps):
        def prober(path):
            return {
                "width": 816,
                "height": 1104,
                "fps": fps,
                "frames": frames,
                "note": "stub probe",
            }

        return prober

    def test_ten_seconds_is_seventy_cents(self):
        self.assertEqual(E._window_seconds("w.mp4", prober=self._probe(300, 30)), 10.0)
        self.assertEqual(E.kling_price(10.0), 0.7)

    def test_five_seconds_is_thirty_five_cents(self):
        self.assertEqual(E._window_seconds("w.mp4", prober=self._probe(150, 30)), 5.0)
        self.assertEqual(E.kling_price(5.0), 0.35)

    def test_the_stage_prints_the_price_it_will_actually_cost(self):
        with TemporaryDirectory() as td:
            got = E.stage_kling(
                styled="s.png",
                window="w.mp4",
                out_path=Path(td) / "out.mp4",
                upload=_upload_ok,
                kling=_kling_ok,
                probe=self._probe(300, 30),
            )
        self.assertEqual(got["numbers"]["price_usd"], 0.7)
        self.assertEqual(got["numbers"]["seconds"], 10.0)
        self.assertTrue(
            any("$0.7" in str(c["note"]) for c in got["checks"]), [c["note"] for c in got["checks"]]
        )

    def test_an_unmeasurable_window_falls_back_and_does_NOT_guess(self):
        def broken(path):
            raise OSError("the file is missing")

        with TemporaryDirectory() as td:
            got = E.stage_kling(
                styled="s.png",
                window="w.mp4",
                out_path=Path(td) / "out.mp4",
                upload=_upload_ok,
                kling=_kling_ok,
                probe=broken,
            )
        self.assertIsNone(got["numbers"]["seconds"])
        self.assertEqual(got["numbers"]["price_usd"], E.KLING_PRICE_USD)


class ThePersonMustBeInPlanNotJustTheCanvas(unittest.TestCase):
    """The canvas was checked, but the pose on the reference never was, and it cost money."""

    from lipsync import fork_plan as _P

    GOOD = {
        "l_shoulder": (0.58, 0.32, 0.99),
        "r_shoulder": (0.42, 0.32, 0.99),
        "l_wrist": (0.66, 0.62, 0.97),
        "r_wrist": (0.34, 0.62, 0.97),
        "l_ankle": (0.55, 0.92, 0.96),
        "r_ankle": (0.45, 0.92, 0.96),
    }

    def _check(self, points):
        return E._person_in_plan("k.png", plan=self._P, pose=lambda p: points)

    def test_a_reference_in_plan_passes(self):
        self.assertEqual(self._check(self.GOOD)[1], PASS)

    def test_the_measured_y2k_reference_is_caught(self):
        bad = dict(
            self.GOOD,
            l_shoulder=(0.58, 0.4846, 0.99),
            r_shoulder=(0.42, 0.4846, 0.99),
            l_ankle=(0.55, 0.7358, 0.96),
            r_ankle=(0.45, 0.7358, 0.96),
        )
        name, outcome, note = self._check(bad)
        self.assertEqual(outcome, FAIL)
        self.assertIn("0.4846", note)
        self.assertIn("0.7358", note)

    def test_the_measured_tomatoes_reference_is_caught_on_the_centre(self):
        bad = {k: (v[0] - 0.24, v[1], v[2]) for k, v in self.GOOD.items()}
        bad = dict(bad, l_ankle=(0.31, 0.7816, 0.96), r_ankle=(0.21, 0.7816, 0.96))
        self.assertEqual(self._check(bad)[1], FAIL)

    def test_a_pose_that_will_not_read_is_UNMEASURED_not_failed(self):
        self.assertEqual(self._check({})[1], UNMEASURED)

    def test_a_falling_pose_reader_is_UNMEASURED(self):
        def broken(_):
            raise RuntimeError("mediapipe did not load")

        self.assertEqual(E._person_in_plan("k.png", plan=self._P, pose=broken)[1], UNMEASURED)

    def test_the_note_says_WHY_it_matters_not_just_that_it_failed(self):
        bad = dict(self.GOOD, l_ankle=(0.55, 0.70, 0.96), r_ankle=(0.45, 0.70, 0.96))
        self.assertIn("past the frame edge", self._check(bad)[2])
