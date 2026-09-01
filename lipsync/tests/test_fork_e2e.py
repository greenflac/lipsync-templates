"""End-to-end stand: the whole path on stub functions, no network and no money."""

from __future__ import annotations

import io
import json
import socket
import unittest
import urllib.request
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


# MEASURED 2026-08-26, written as literals rather than imported so that a change
# in the module cannot quietly move the expectation with it: what the styliser
# returns on a 9:16 request, what the outpainter returns, the 3:4 fossil, and an
# exact frame kept as the negative control.
STYLISER_RETURNS = (768, 1376)
OUTPAINT_RETURNS = (1536, 2752)
THREE_BY_FOUR = (896, 1200)
EXACT_RETURN = (720, 1280)
LANDSCAPE = (1920, 1080)


class _PlanOk:
    """Stub plan neighbour with a fake image filesystem: paths mapped to sizes.

    `fit_to_plan`, `ratio_axis` and `person_box` are the REAL functions on
    purpose — the geometry under test is the product's, not the stub's. The
    previous version of this stub answered with a hardcoded `source` of
    720x1280 and `added_share` 0.0, a size the route has not returned since it
    was measured, so every stage test that used it was green on a frame that
    does not exist. Now the arriving size is stated by the test, and each
    written file remembers the size it was written at.
    """

    ANKLES_BAND = fork_plan.ANKLES_BAND
    CENTRE_TOL = fork_plan.CENTRE_TOL
    SHOULDERS_BAND = fork_plan.SHOULDERS_BAND
    WIDTH_MAX = fork_plan.WIDTH_MAX
    PERSON_AXES = fork_plan.PERSON_AXES
    composition_card = staticmethod(fork_plan.composition_card)
    in_card = staticmethod(fork_plan.in_card)
    person_box = staticmethod(fork_plan.person_box)
    tally = staticmethod(fork_plan.tally)
    plan_verdict = staticmethod(fork_plan.plan_verdict)
    ratio_axis = staticmethod(fork_plan.ratio_axis)
    fit_to_plan = staticmethod(fork_plan.fit_to_plan)

    def __init__(self, arrived=STYLISER_RETURNS, outpainted=OUTPAINT_RETURNS):
        self.arrived = arrived
        self.outpainted = outpainted
        self.sizes: dict = {}
        self.extends: list = []

    def sizer(self, path):
        """Size reader injected into the stage: unwritten files are the arriving frame."""
        return self.sizes.get(str(path), self.arrived)

    def cropper(self, src, dst, box):
        """Crop stub: writes a file and remembers the size the box asked for."""
        Path(dst).write_bytes(b"\x00" * 64)
        self.sizes[str(dst)] = (int(box["width"]), int(box["height"]))

    def to_plan(self, src, dst, **kw):
        plan = fork_plan.canvas_for(*self.sizer(src))
        Path(dst).write_bytes(b"\x00" * 64)
        self.sizes[str(dst)] = (plan["width"], plan["height"])
        return {
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "path": str(dst),
            "plan": plan,
            "note": "stub 9:16 padding",
        }

    def extend_to_plan(self, src, dst, **kw):
        self.extends.append((str(src), str(dst)))
        Path(dst).write_bytes(b"\x00" * 64)
        # MEASURED: the outpainter answers on its own grid, 1536x2752, whatever
        # size it was asked for. The stage has to trim that too.
        self.sizes[str(dst)] = self.outpainted
        return {
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "path": str(dst),
            "extended": True,
            "note": "stub margin outpaint",
        }


def _stylize_stage(out_path, *, plan=None, **over):
    """Call the stylise stage on stubs, with the plan neighbour's own fake filesystem wired in."""
    neighbour = _PlanOk() if plan is None else plan
    kw = dict(
        client_photo="c.png",
        style_ref="s.png",
        out_path=out_path,
        stylize=_stylize_ok,
        plan=neighbour,
        pose=_pose_ok,
        prompt="a look, " + E.NO_BRANDS_CLAUSE,
        sizer=getattr(neighbour, "sizer", None),
        cropper=getattr(neighbour, "cropper", None),
        operator_ok_styliser_size=True,
    )
    kw.update(over)
    return E.stage_stylize(**kw)


def _run(root: Path, log, **over):
    """Drive the whole path on stubs. The default frame is the MEASURED 768x1376.

    That size is not what the styliser was asked for, so the run only reaches
    the paid call with the operator's admission — which is the point of the
    check and is asserted on its own below.
    """
    f = _files(root)
    p = over.pop("plan", None) or _PlanOk()
    kw = dict(
        sizer=getattr(p, "sizer", None),
        cropper=getattr(p, "cropper", None),
        operator_ok_styliser_size=True,
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
        plan=p,
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


class TheStyleVerdictNamesTheDeviceThatProducedIt(unittest.TestCase):
    """`shipped_similarity` repairs a missing external package by falling back.

    A repair that hides the breakage is how a defect ships: two runs measured by
    two different devices report the same-looking number. The stage must say
    which one answered. Both controls are run here, so the test does not depend
    on whether `creative_eval` happens to be installed on the machine.
    """

    def _hidden_external(self):
        """Make the lazy import fail the way a machine without the package would."""
        import sys

        return mock.patch.dict(sys.modules, {"creative_eval.style": None})

    def _present_external(self):
        """Put a working `creative_eval.style` where the lazy import will find it."""
        import sys
        import types

        pkg = types.ModuleType("creative_eval")
        style = types.ModuleType("creative_eval.style")
        style.similarity = lambda a, b: 0.9
        pkg.style = style
        return mock.patch.dict(sys.modules, {"creative_eval": pkg, "creative_eval.style": style})

    def _acceptance(self, **kw):
        return E.stage_style_acceptance(
            styled="styled.png",
            style_ref="s.png",
            client_photo="c.png",
            distances=_distances_ok,
            **kw,
        )

    def test_the_fallback_device_is_named_in_the_numbers_and_in_the_note(self):
        with self._hidden_external():
            got = self._acceptance()
        self.assertIn("fallback", got["numbers"]["style_instrument"])
        self.assertIn("palette_similarity", got["numbers"]["style_instrument"])
        self.assertIn(
            got["numbers"]["style_instrument"],
            " ".join(c["note"] for c in got["checks"]),
        )

    def test_the_shipped_device_is_named_when_the_package_is_there(self):
        """Negative control: the same call, the only difference being the package."""
        with self._present_external():
            got = self._acceptance()
        self.assertEqual(
            got["numbers"]["style_instrument"],
            "creative_eval.style.similarity (external, shipped)",
        )
        self.assertNotIn("fallback", got["numbers"]["style_instrument"])

    def test_the_two_devices_do_not_report_the_same_name(self):
        with self._hidden_external():
            without = self._acceptance()["numbers"]["style_instrument"]
        with self._present_external():
            within = self._acceptance()["numbers"]["style_instrument"]
        self.assertNotEqual(without, within)

    def _broken_external(self):
        """The case that ships: the package imports and then throws on the call."""
        import sys
        import types

        def _throws(a, b):
            raise RuntimeError(self.BOOM)

        pkg = types.ModuleType("creative_eval")
        style = types.ModuleType("creative_eval.style")
        style.similarity = _throws
        pkg.style = style
        return mock.patch.dict(sys.modules, {"creative_eval": pkg, "creative_eval.style": style})

    BOOM = "model weights corrupt: checksum mismatch on style.bin"

    def test_a_broken_external_is_named_as_the_fallback_and_says_why(self):
        """Breakage and repair are two facts, and the stage must carry both."""
        with self._broken_external():
            got = self._acceptance()
        instrument = got["numbers"]["style_instrument"]
        self.assertIn("palette_similarity", instrument)
        self.assertNotIn("creative_eval", instrument)
        self.assertIn(self.BOOM, instrument)
        self.assertIn(instrument, " ".join(c["note"] for c in got["checks"]))

    def test_a_broken_external_does_not_read_as_an_absent_one(self):
        """Three outcomes, not two: broken and missing are different repairs."""
        with self._broken_external():
            broken = self._acceptance()["numbers"]["style_instrument"]
        with self._hidden_external():
            absent = self._acceptance()["numbers"]["style_instrument"]
        self.assertNotEqual(broken, absent)
        self.assertNotIn(self.BOOM, absent)

    def test_an_injected_device_is_never_reported_as_the_shipped_one(self):
        """The name comes from what will run, not from what the default would be."""
        got = self._acceptance(similarity=_similarity_ok)
        self.assertIn("injected", got["numbers"]["style_instrument"])
        self.assertIn("_similarity_ok", got["numbers"]["style_instrument"])
        self.assertNotIn("palette_similarity", got["numbers"]["style_instrument"])


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

    def test_a_frame_narrower_than_the_floor_is_a_defect(self):
        """The branch, not the constant: removing the check must be seen.

        Mutating OUT_RATIO_MIN alone reddened only the constant's own tests;
        deleting the branch that reads it left the suite green, so the wiring
        had no guard. This drives the stage and reads its verdict.
        """
        too_tall = lambda p: {
            "outcome": PASS,
            "fps": 30.0,
            "frames": 99,
            "width": 360,
            "height": 1280,
            "note": "",
        }
        got = self._accept(probe=too_tall)
        self.assertEqual(got["outcome"], "fail")
        self.assertIn(str(E.OUT_RATIO_MIN), str(got))

    def test_the_plan_ratio_itself_is_not_refused_by_the_floor(self):
        """The other side: the floor must not reject what the product delivers."""
        on_plan = lambda p: {
            "outcome": PASS,
            "fps": 30.0,
            "frames": 99,
            "width": 720,
            "height": 1280,
            "note": "",
        }
        self.assertEqual(self._accept(probe=on_plan)["outcome"], "pass")

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
            got = _stylize_stage(Path(td) / "styled.png", prompt="just make it look nice")
            self.assertEqual(got["outcome"], "fail")
            self.assertEqual(got["checks"][0]["outcome"], "fail")
            ok = _stylize_stage(Path(td) / "styled.png")
            self.assertEqual(ok["outcome"], "pass")

    def test_the_ban_text_itself_is_a_decision_constant(self):
        with mock.patch.object(E, "NO_BRANDS_CLAUSE", "no logos whatsoever"):
            with TemporaryDirectory() as td:
                got = _stylize_stage(
                    Path(td) / "styled.png", prompt="a look, no brand names, no logos"
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
        """The size travels on the real gateway attribute, not only on an injected one."""
        from lipsync import pollinations

        seen = {}

        def images_edit(prompt, ref_path, out_path, **kw):
            seen.update(kw)
            seen["refs"] = [str(ref_path)]
            return str(out_path)

        with mock.patch.object(pollinations, "images_edit", images_edit):
            E.live_stylize(person="c.png", style="s.png", prompt="p", out_path="o.png")
        self.assertEqual((seen.get("width"), seen.get("height")), E.STYLED_SIZE)
        self.assertEqual(seen.get("model"), E.STYLE_MODEL)
        self.assertEqual(len(seen["refs"]), E.STYLE_IMAGES)
        self.assertEqual(seen["refs"], ["c.png"])

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
                    "--aesthetic",
                    "icecream",
                    "--client-gender",
                    "f",
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
                    "--aesthetic",
                    "icecream",
                    "--client-gender",
                    "f",
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
                    "--aesthetic",
                    "icecream",
                    "--client-gender",
                    "f",
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
            got = _stylize_stage(Path(td) / "styled.png")
        self.assertTrue(got["styled"].endswith("_9x16.png"), got["styled"])
        names = [c["name"] for c in got["checks"]]
        self.assertIn("styliser returned the plan", names)

    def test_the_outpaint_is_NOT_called_when_nothing_was_padded(self):
        """A no-op outpaint is a paid generation that can repaint the person."""
        with TemporaryDirectory() as td:
            got = _stylize_stage(
                Path(td) / "styled.png",
                extend=lambda *a, **k: self.fail("the outpainter must not be called"),
            )
        outpaint = [c for c in got["checks"] if c["name"] == "margin outpaint"]
        self.assertEqual([c["outcome"] for c in outpaint], [PASS])
        self.assertIn("not called", outpaint[0]["note"])
        self.assertTrue(got["styled"].endswith("_9x16.png"), got["styled"])

    def test_a_plan_that_could_not_be_laid_is_UNMEASURED_not_a_defect(self):
        class Broken:
            @staticmethod
            def fit_to_plan(width, height):
                raise OSError("the image did not open")

        with TemporaryDirectory() as td:
            got = _stylize_stage(Path(td) / "styled.png", plan=Broken, pose=_pose_ok)
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

        @staticmethod
        def card_of(_aid):
            """The card this aesthetic carries: the composition `_pose_ok` stands in."""
            return {
                "shoulders": 0.32,
                "ankles": 0.92,
                "centre": 0.50,
                "width": 0.16,
                "tolerances": {
                    "shoulders": 0.05,
                    "ankles": 0.05,
                    "centre": 0.1837,
                    "width": 0.1326,
                },
            }

    def test_a_mismatched_gender_stops_before_the_styliser_is_called(self):
        seen = []

        def counting(**kw):
            seen.append(kw)
            return kw["out_path"]

        with TemporaryDirectory() as td:
            got = _stylize_stage(
                Path(td) / "styled.png",
                stylize=counting,
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
            got = _stylize_stage(
                Path(td) / "styled.png",
                style_ref="foreign.png",
                stylize=counting,
                aesthetic="y2k",
                client_gender="f",
                aesthetic_mod=self._A,
            )
        self.assertEqual(got["outcome"], PASS)
        self.assertIn("y2k_f.png", seen["style"])
        self.assertNotIn("foreign", seen["style"])
        self.assertIn("aesthetic in words", seen["prompt"])


# The class that stood here, `TheTemplateFlagsReachRunFromTheCommandLine`, is
# gone: every case it held is now in `TheOrderTakesAnAestheticAndNothingElse`,
# which asks the same questions of the command line the contract of 2026-09-01
# leaves — one order, one aesthetic. Its last case, "the old style path still
# works without an aesthetic", was decision 8 itself and is not replaced.


class TheOutpaintFixesTheLetterboxWithoutLosingTheRun(unittest.TestCase):
    """The plan margins show as bands. The instrument says "pass": it checks the canvas."""

    class _PlanNoExtend(_PlanOk):
        """The 3:4 fossil arriving, and an outpainter that does not answer.

        The hardcoded `source: {896, 1200}` and `added_share: 0.2469` of the
        previous version are gone: 896x1200 is now the size the fake filesystem
        reports for the arriving frame, so the padding decision is made by the
        real `fit_to_plan` rather than asserted by the stub.
        """

        def __init__(self):
            super().__init__(arrived=THREE_BY_FOUR)

        def extend_to_plan(self, src, dst, *, extender=None, **kw):
            self.extends.append((str(src), str(dst)))
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "path": str(src),
                "extended": False,
                "note": "the outpainter did not answer",
            }

    def _padded(self, **over):
        with TemporaryDirectory() as td:
            return _stylize_stage(Path(td) / "styled.png", plan=self._PlanNoExtend(), **over)

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


class TheDrivingCardIsMeasuredAndNotWaitedFor(unittest.TestCase):
    """`framing_clause` and `in_card` were wired to a card nothing ever produced.

    The stand accepted `card=` from a caller and `main` never passed one, so
    every shipped run framed the reference by the template's own words and
    checked the person against the global bands instead of against the driving.
    The card is now measured from the driving frames.
    """

    _P = fork_plan
    FRAMES = [f"{i:05d}.png" for i in range(96)]

    def test_a_readable_driving_gives_a_measured_card(self):
        card = E.driving_card(self.FRAMES, pose=_pose_ok)
        self.assertEqual(card["outcome"], PASS)
        self.assertEqual(card["centre"], 0.5)
        self.assertEqual(card["ankles"], 0.92)

    def test_an_unreadable_driving_gives_no_card_and_says_so(self):
        """Negative control: the card is never guessed when the pose does not read."""
        card = E.driving_card(self.FRAMES, pose=lambda p: {})
        self.assertEqual(card["outcome"], UNMEASURED)
        self.assertNotIn("centre", card)

    def test_no_frames_at_all_is_could_not_measure_and_not_an_empty_card(self):
        card = E.driving_card(None, pose=_pose_ok)
        self.assertEqual(card["outcome"], UNMEASURED)
        self.assertIn("NOT MEASURED", card["note"])

    def test_a_thrown_reader_is_reported_and_does_not_sink_the_run(self):
        def broken(_):
            raise RuntimeError("mediapipe did not load")

        card = E.driving_card(self.FRAMES, pose=broken)
        self.assertEqual(card["outcome"], UNMEASURED)
        self.assertIn("mediapipe did not load", card["note"])

    def test_the_sample_is_spread_over_the_clip_and_bounded(self):
        seen = []

        def watching(path):
            seen.append(path)
            return _pose_ok(path)

        E.driving_card(self.FRAMES, pose=watching)
        # The sample size as a LITERAL: imported it would travel with a change
        # to the module and the change would go unseen.
        self.assertEqual(len(seen), 24)
        self.assertEqual(seen[0], self.FRAMES[0])
        self.assertGreater(seen[-1], self.FRAMES[len(self.FRAMES) // 2])

    def test_the_sample_size_moved_both_ways_moves_the_reading(self):
        seen = []

        def watching(path):
            seen.append(path)
            return _pose_ok(path)

        with mock.patch.object(E, "CARD_SAMPLE_FRAMES", 4):
            E.driving_card(self.FRAMES, pose=watching)
        self.assertEqual(len(seen), 4)
        seen.clear()
        with mock.patch.object(E, "CARD_SAMPLE_FRAMES", 96):
            E.driving_card(self.FRAMES, pose=watching)
        self.assertEqual(len(seen), 96)


class TheCardBuiltFromTheDrivingReachesThePromptAndTheCheck(unittest.TestCase):
    def _stylize(self, **over):
        with TemporaryDirectory() as td:
            return _stylize_stage(Path(td) / "styled.png", **over)

    def _card(self):
        return E.driving_card([f"{i:05d}.png" for i in range(48)], pose=_pose_ok)

    def test_the_run_builds_a_card_when_the_caller_hands_none_in(self):
        log = io.StringIO()
        with TemporaryDirectory() as td, _no_network():
            got = _run(Path(td), log, driving_frames=[f"{i:05d}.png" for i in range(48)])
        stage = got["stages"][1]
        self.assertEqual(stage["driving_card"]["outcome"], PASS)
        self.assertIn("driving card: pass", log.getvalue())

    def test_without_frames_the_card_is_could_not_measure_and_the_run_still_passes(self):
        """Negative control: the wiring must not turn a narrower run into a defect."""
        log = io.StringIO()
        with TemporaryDirectory() as td, _no_network():
            got = _run(Path(td), log)
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(got["stages"][1]["driving_card"]["outcome"], UNMEASURED)

    def test_the_measured_card_is_what_the_prompt_builders_are_handed(self):
        """Link one: the stage passes the card on instead of dropping it."""
        seen = {}

        class _A:
            @staticmethod
            def gender_of(aid):
                return "f"

            @staticmethod
            def pair_check(*, client_gender, aesthetic_gender):
                return {"outcome": PASS, "note": "stub gate"}

            @staticmethod
            def aesthetic_file(aid):
                return f"assets/aesthetics/{aid}_f.png"

            @staticmethod
            def compose(aid, *, card=None):
                seen["compose"] = card
                return {"prompt": "aesthetic in words"}

            @staticmethod
            def assemble_prompt(*, card=None):
                seen["assemble"] = card
                return "roles, " + E.NO_BRANDS_CLAUSE

        card = self._card()
        self._stylize(prompt=None, aesthetic="y2k", client_gender="f", aesthetic_mod=_A, card=card)
        self.assertEqual(seen["compose"], card)
        self.assertEqual(seen["assemble"], card)

    def test_the_real_prompt_builder_turns_that_card_into_a_framing_clause(self):
        """Link two: and an unmeasured card is the negative control, giving no clause."""
        from lipsync import fork_aesthetic

        measured = fork_aesthetic.assemble_prompt(card=self._card())
        blank = fork_aesthetic.assemble_prompt(card=E.driving_card(None, pose=_pose_ok))
        self.assertIn("FRAMING, this outranks", measured)
        self.assertNotIn("FRAMING, this outranks", blank)

    def test_a_measured_card_changes_which_question_the_person_check_asks(self):
        without = self._stylize(card=None)
        withcard = self._stylize(card=self._card())
        names = lambda r: [c["name"] for c in r["checks"]]  # noqa: E731
        self.assertIn("person in plan", names(without))
        self.assertIn("person in the driving card", names(withcard))

    def test_an_unmeasured_card_leaves_the_plan_bands_in_charge(self):
        """Negative control: an object that is not a measurement must not take over."""
        blank = E.driving_card(None, pose=_pose_ok)
        got = self._stylize(card=blank)
        self.assertIn("person in plan", [c["name"] for c in got["checks"]])
        self.assertNotIn("person in the driving card", [c["name"] for c in got["checks"]])


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

    def test_every_named_axis_is_one_the_judge_actually_returns(self):
        """Clamps PERSON_AXES from above; the per-axis tests clamp it below.

        An auditor showed the list was guarded on one side only: removing an
        axis reddened, but adding `elbows` — an axis no judge produces — left
        all 956 tests green, and the filter would then have selected nothing
        under that name while still reading as a checked axis.
        """
        produced = {a["name"] for a in self._P.plan_verdict(points=self.GOOD)["axes"]}
        self.assertTrue(produced, "the judge returned no axes at all")
        unknown = [n for n in self._P.PERSON_AXES if n not in produced]
        self.assertEqual(unknown, [], f"PERSON_AXES names axes no judge produces: {unknown}")

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

    @staticmethod
    def _axis(name, violations, note):
        return {
            "name": name,
            "checked": 1,
            "violations": violations,
            "unmeasured": 0,
            "note": note,
        }

    def _with_verdict(self, axes, points):
        """Run the check with `plan_verdict` replaced by a stub that returns `axes`."""
        seen = {}

        def fake(**kw):
            seen.update(kw)
            return {"axes": axes}

        with mock.patch.object(self._P, "plan_verdict", fake):
            got = E._person_in_plan("k.png", plan=self._P, pose=lambda p: points)
        return got, seen

    def test_the_pose_reaches_plan_verdict_and_its_answer_is_the_answer(self):
        """Negative control on the wiring: silence the judge and the check goes silent.

        A second copy of the bands here would ignore the stub and keep
        answering on its own — which is exactly the defect this replaced.
        """
        got, seen = self._with_verdict([self._axis("centre", 1, "SENTINEL-OFF-CENTRE")], self.GOOD)
        self.assertEqual(seen, {"points": self.GOOD})
        self.assertEqual(got[1], FAIL)
        self.assertIn("SENTINEL-OFF-CENTRE", got[2])

    def test_a_pose_the_bands_would_refuse_passes_when_the_judge_says_pass(self):
        """The other direction: nothing here re-judges what the judge admitted."""
        refused = dict(self.GOOD, l_ankle=(0.55, 0.10, 0.96), r_ankle=(0.45, 0.10, 0.96))
        self.assertEqual(self._check(refused)[1], FAIL)
        got, _ = self._with_verdict(
            [self._axis(name, 0, f"{name} SENTINEL-OK") for name in self._P.PERSON_AXES],
            refused,
        )
        self.assertEqual(got[1], PASS)
        self.assertIn("SENTINEL-OK", got[2])

    def test_each_of_the_four_axes_can_sink_the_check_on_its_own(self):
        """Without this the axis list is clamped from one side only.

        Widening it goes red at once; dropping an axis went unnoticed, because
        no case made that axis the only violation. The axis names are written
        out as literals so the tuple cannot move the expectation with it.
        """
        cases = {
            "shoulders": dict(
                self.GOOD, l_shoulder=(0.58, 0.50, 0.99), r_shoulder=(0.42, 0.50, 0.99)
            ),
            "ankles": dict(self.GOOD, l_ankle=(0.55, 0.60, 0.96), r_ankle=(0.45, 0.60, 0.96)),
            "centre": {k: (v[0] + 0.20, v[1], v[2]) for k, v in self.GOOD.items()},
            "width": dict(self.GOOD, l_shoulder=(0.90, 0.32, 0.99), r_shoulder=(0.10, 0.32, 0.99)),
        }
        for axis, points in cases.items():
            with self.subTest(axis=axis):
                name, outcome, note = self._check(points)
                self.assertEqual(outcome, FAIL, f"{axis} alone did not sink the check")
                self.assertIn(axis, note)

    def test_the_good_pose_is_the_negative_control_for_all_four(self):
        """Each case above must differ from this one on its own axis and nothing else."""
        self.assertEqual(self._check(self.GOOD)[1], PASS)

    def test_only_the_person_axes_are_read_and_the_canvas_is_left_to_the_caller(self):
        """The real verdict cannot measure the canvas here, and that must not sink the check."""
        canvas = [
            a for a in self._P.plan_verdict(points=self.GOOD)["axes"] if a["name"] == "canvas"
        ]
        self.assertEqual([a["unmeasured"] for a in canvas], [1])
        self.assertEqual(self._check(self.GOOD)[1], PASS)


# The plan, and the bound around it, as LITERALS. Imported from the module they
# would travel with a mutation and the mutation would stay invisible.
PLAN = 0.5625
EXACT_BOUND = 0.001
TRIM_BUDGET = 0.02


def _is_exact(size) -> bool:
    return abs(size[0] / size[1] - PLAN) <= EXACT_BOUND


class TheStyliserIsJudgedAgainstWhatWasAsked(unittest.TestCase):
    """Д2: the check named for the request compared against a tolerance band.

    MEASURED 2026-08-26: on 768x1376 the old check said `pass`, the stage said
    `pass`, and the run went on to the one paid call. Vertical is not the same
    question as "the size we ordered", and one number was answering both.
    """

    def test_the_asked_size_is_itself_the_plan(self):
        self.assertTrue(_is_exact(E.STYLED_SIZE), E.STYLED_SIZE)
        self.assertEqual(tuple(E.STYLED_SIZE), (720, 1280))

    def test_the_measured_return_is_not_a_pass(self):
        got = E.styliser_kept_the_plan(asked=(720, 1280), got=STYLISER_RETURNS)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(got["violations"], 1)
        self.assertEqual(got["checked"], 1)
        self.assertEqual(got["unmeasured"], 0)

    def test_the_two_sizes_are_carried_as_data_not_only_as_prose(self):
        got = E.styliser_kept_the_plan(asked=(720, 1280), got=(768, 1376))
        self.assertEqual(tuple(got["asked"]), (720, 1280))
        self.assertEqual(tuple(got["got"]), (768, 1376))

    def test_a_frame_that_is_exactly_9x16_but_NOT_what_was_asked_still_fails(self):
        """The heart of the defect: the old check would have passed this one.

        1440x2560 is exactly the plan, so a ratio band says yes. It is still
        not the size that was ordered, and a route that answers with a size
        nobody ordered is a route whose next answer cannot be predicted.
        """
        other = (1440, 2560)
        self.assertTrue(_is_exact(other), "the fixture must be exactly 9:16")
        got = E.styliser_kept_the_plan(asked=(720, 1280), got=other)
        self.assertEqual(got["outcome"], FAIL)

    def test_the_asked_size_returned_unchanged_passes(self):
        got = E.styliser_kept_the_plan(asked=(720, 1280), got=(720, 1280))
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual((got["checked"], got["violations"], got["unmeasured"]), (1, 0, 0))

    def test_a_size_that_was_never_measured_is_the_third_outcome(self):
        for missing in (None, (), (0, 1280), ("wide", 1280), {"width": None, "height": 1280}):
            with self.subTest(missing=missing):
                got = E.styliser_kept_the_plan(asked=(720, 1280), got=missing)
                self.assertEqual(got["outcome"], UNMEASURED)
                self.assertEqual((got["checked"], got["violations"], got["unmeasured"]), (0, 0, 1))
                self.assertIsNone(got["got"])

    def test_a_nonsense_request_is_also_the_third_outcome_not_a_pass(self):
        got = E.styliser_kept_the_plan(asked=None, got=(720, 1280))
        self.assertEqual(got["outcome"], UNMEASURED)

    def test_a_size_may_arrive_as_a_mapping(self):
        got = E.styliser_kept_the_plan(
            asked={"width": 720, "height": 1280}, got={"width": 720, "height": 1280}
        )
        self.assertEqual(got["outcome"], PASS)

    def test_both_numbers_are_in_the_note_a_human_reads(self):
        note = E.styliser_kept_the_plan(asked=(720, 1280), got=(896, 1200))["note"]
        self.assertIn("720x1280", note)
        self.assertIn("896x1200", note)


class TheFrameIsBroughtOntoThePlanOnDisk(unittest.TestCase):
    """Both edges of the range and the middle, plus two frames that must NOT be trimmed."""

    def _fit(self, arrived, **over):
        plan = _PlanOk(arrived=arrived)
        with TemporaryDirectory() as td:
            src, dst = Path(td) / "in.png", Path(td) / "out.png"
            src.write_bytes(b"\x00" * 64)
            kw = dict(plan=fork_plan, sizer=plan.sizer, cropper=plan.cropper)
            kw.update(over)
            got = E.fit_frame_to_plan(src, dst, **kw)
            got["wrote"] = Path(got["path"]).exists()
        return got

    def test_the_measured_styliser_return_is_trimmed_to_exact(self):
        got = self._fit(STYLISER_RETURNS)
        self.assertEqual(got["action"], "crop")
        self.assertEqual(got["outcome"], PASS)
        self.assertTrue(_is_exact(got["shipped"]), got["shipped"])
        self.assertTrue(0.0 < got["trimmed_share"] <= TRIM_BUDGET, got["trimmed_share"])
        self.assertTrue(got["wrote"])

    def test_the_measured_outpaint_return_is_trimmed_to_exact(self):
        got = self._fit(OUTPAINT_RETURNS)
        self.assertEqual(got["action"], "crop")
        self.assertTrue(_is_exact(got["shipped"]), got["shipped"])

    def test_an_exact_frame_is_left_where_it_is(self):
        """Negative control: nothing is rewritten when there is nothing to do."""
        got = self._fit(EXACT_RETURN)
        self.assertEqual(got["action"], "none")
        self.assertEqual(tuple(got["shipped"]), (720, 1280))
        self.assertTrue(got["path"].endswith("in.png"), got["path"])

    def test_the_three_by_four_fossil_is_padded_and_NOT_trimmed(self):
        """Negative control: trimming 3:4 to 9:16 cuts a quarter of the width off a person."""
        got = self._fit(THREE_BY_FOUR, plan=_PlanOk(arrived=THREE_BY_FOUR))
        self.assertEqual(got["action"], "pad")
        self.assertEqual(got["trimmed_share"], 0.0)

    def test_padding_is_counted_as_a_violation_and_not_as_a_repair(self):
        """The owner's criterion, 2026-08-26: 9:16 with no padding in 100% of cases."""
        got = self._fit(THREE_BY_FOUR, plan=_PlanOk(arrived=THREE_BY_FOUR))
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual((got["checked"], got["violations"], got["unmeasured"]), (1, 1, 0))

    def test_a_trimmed_frame_is_NOT_counted_as_a_violation(self):
        """Negative control of the rule above: it must not condemn every frame."""
        got = self._fit(STYLISER_RETURNS)
        self.assertEqual((got["checked"], got["violations"], got["unmeasured"]), (1, 0, 0))

    def test_a_landscape_frame_is_padded_and_NOT_trimmed(self):
        got = self._fit(LANDSCAPE, plan=_PlanOk(arrived=LANDSCAPE))
        self.assertEqual(got["action"], "pad")

    def test_a_size_that_could_not_be_read_is_UNMEASURED_not_a_defect(self):
        got = self._fit(STYLISER_RETURNS, sizer=lambda p: None)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertEqual((got["checked"], got["violations"], got["unmeasured"]), (0, 0, 1))
        self.assertIsNone(got["arrived"])

    def test_a_crop_that_could_not_be_carried_out_is_UNMEASURED_not_a_pass(self):
        def broken(src, dst, box):
            raise OSError("no space left on device")

        got = self._fit(STYLISER_RETURNS, cropper=broken)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertTrue(got["path"].endswith("in.png"), "a frame that was not cut must not be sold")

    def test_a_plan_neighbour_that_throws_is_UNMEASURED(self):
        class Broken:
            @staticmethod
            def fit_to_plan(width, height):
                raise RuntimeError("the decision blew up")

        got = self._fit(STYLISER_RETURNS, plan=Broken)
        self.assertEqual(got["outcome"], UNMEASURED)


class TheStageTellsBothFactsAboutTheFrame(unittest.TestCase):
    """ "The route ignored the order" and "we trimmed it back" are two facts."""

    def _named(self, got):
        return {c["name"]: c for c in got["checks"]}

    def _stage(self, arrived=STYLISER_RETURNS, **over):
        plan = _PlanOk(arrived=arrived)
        with TemporaryDirectory() as td:
            got = _stylize_stage(Path(td) / "styled.png", plan=plan, **over)
            got["shipped"] = plan.sizer(got["styled"])
            got["extends"] = list(plan.extends)
        return got

    def test_the_mismatch_stops_the_stage_when_nobody_has_looked(self):
        got = self._stage(operator_ok_styliser_size=False)
        self.assertEqual(got["outcome"], FAIL)
        named = self._named(got)
        self.assertEqual(named["styliser returned the plan"]["outcome"], FAIL)
        self.assertIn("768x1376", named["styliser returned the plan"]["note"])

    def test_the_repair_is_reported_even_while_the_mismatch_is_red(self):
        """Neither fact is allowed to swallow the other."""
        got = self._stage(operator_ok_styliser_size=False)
        named = self._named(got)
        self.assertEqual(named["9:16 frame"]["outcome"], PASS)
        note = named["9:16 frame"]["note"]
        self.assertIn("arrived 768x1376", note)
        self.assertIn("trimmed", note)
        self.assertIn("leaving", note)

    def test_the_operators_admission_does_not_erase_the_mismatch_from_the_report(self):
        got = self._stage(operator_ok_styliser_size=True)
        self.assertEqual(got["outcome"], PASS)
        note = self._named(got)["styliser returned the plan"]["note"]
        self.assertIn("768x1376", note)
        self.assertIn("720x1280", note)
        self.assertIn("OPERATOR", note)

    def test_the_file_that_goes_to_the_paid_call_is_exactly_the_plan(self):
        got = self._stage()
        self.assertTrue(_is_exact(got["shipped"]), got["shipped"])
        self.assertEqual(self._named(got)["frame going to the paid call"]["outcome"], PASS)

    def test_an_exact_return_needs_no_admission_at_all(self):
        got = self._stage(arrived=EXACT_RETURN, operator_ok_styliser_size=False)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(self._named(got)["styliser returned the plan"]["outcome"], PASS)
        self.assertEqual(got["extends"], [], "nothing was padded, so nothing was outpainted")

    def test_the_admission_does_NOT_cover_a_frame_that_was_padded(self):
        """Negative control: 3:4 padded with bands is a different photograph."""
        got = self._stage(arrived=THREE_BY_FOUR, operator_ok_styliser_size=True)
        self.assertEqual(got["outcome"], FAIL)
        named = self._named(got)
        self.assertEqual(named["styliser returned the plan"]["outcome"], FAIL)
        self.assertEqual(named["9:16 frame"]["outcome"], FAIL, "padding reported as a clean repair")

    def test_the_outpainters_own_answer_is_trimmed_before_anything_is_paid_for(self):
        """MEASURED: the outpainter answers 1536x2752 whatever it is asked for."""
        got = self._stage(arrived=THREE_BY_FOUR, operator_ok_styliser_size=True)
        named = self._named(got)
        self.assertEqual(len(got["extends"]), 1, "the padded frame was not sent to the outpainter")
        self.assertEqual(named["9:16 frame after the outpaint"]["outcome"], PASS)
        self.assertIn("arrived 1536x2752", named["9:16 frame after the outpaint"]["note"])
        self.assertTrue(_is_exact(got["shipped"]), got["shipped"])

    def test_a_frame_whose_size_cannot_be_read_is_UNMEASURED_not_a_pass(self):
        got = self._stage(sizer=lambda p: None)
        self.assertEqual(got["outcome"], UNMEASURED)
        named = self._named(got)
        self.assertEqual(named["styliser returned the plan"]["outcome"], UNMEASURED)
        self.assertEqual(named["9:16 frame"]["outcome"], UNMEASURED)


class TheRunDoesNotReachThePaidCallOnAnUnadmittedFrame(unittest.TestCase):
    """The whole point of the defect: 0.5581 sailed through to the one paid call."""

    def test_the_run_stops_at_stage_two_and_kling_is_never_called(self):
        called = []

        def kling_must_not_run(**kw):
            called.append(kw)
            raise AssertionError("the paid call was made on an unadmitted frame")

        log = io.StringIO()
        with TemporaryDirectory() as td, _no_network():
            got = _run(
                Path(td),
                log,
                operator_ok_styliser_size=False,
                kling=kling_must_not_run,
            )
        self.assertEqual(called, [])
        self.assertNotEqual(got["exit_code"], 0)
        self.assertEqual([s["stage"] for s in got["stages"]][:2], list(E.STAGES[:2]))
        self.assertEqual(got["stages"][1]["outcome"], FAIL)

    def test_with_the_admission_the_run_completes_on_an_exact_frame(self):
        log = io.StringIO()
        with TemporaryDirectory() as td, _no_network():
            got = _run(Path(td), log)
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(got["exit_code"], 0)

    def test_the_flag_travels_from_the_command_line_into_the_run(self):
        """A flag parsed and dropped looks functional until a paid run."""
        seen = {}

        def fake_run(**kw):
            seen.update(kw)
            return {"exit_code": 0}

        with mock.patch.object(E, "run", fake_run):
            E.main(
                [
                    "--client",
                    "c.png",
                    "--aesthetic",
                    "icecream",
                    "--client-gender",
                    "f",
                    "--operator-ok-styliser-size",
                ]
            )
        self.assertIs(seen["operator_ok_styliser_size"], True)

    def test_without_the_flag_the_run_is_told_so(self):
        seen = {}

        def fake_run(**kw):
            seen.update(kw)
            return {"exit_code": 0}

        with mock.patch.object(E, "run", fake_run):
            E.main(["--client", "c.png", "--aesthetic", "icecream", "--client-gender", "f"])
        self.assertIs(seen["operator_ok_styliser_size"], False)


class EvidenceReachesTheReaderWhole(unittest.TestCase):
    """A truncated reason produced a wrong diagnosis and a spent balance once.

    Every note in this module is the reason behind a verdict, and the cause of
    a failure sits at the end of the text at least as often as at the front:
    an ffmpeg or an API answer opens with a banner and closes with the line
    that says what went wrong. Each test below carries a sentinel past the
    limit the code used to cut at, and each is paired with a short input on
    which it must stay silent — otherwise it would pass on any note at all.
    """

    from lipsync import fork_plan as _P

    GOOD = ThePersonMustBeInPlanNotJustTheCanvas.GOOD

    @staticmethod
    def _long(sentinel: str, width: int = 500) -> str:
        """A note whose only distinguishing word sits past `width` characters."""
        return "banner " * (width // 7) + sentinel

    def test_a_neighbours_reason_is_not_cut_at_four_hundred(self):
        note = self._long("CAUSE-AT-THE-END")
        self.assertGreater(len(note), 400)
        self.assertIn(
            "CAUSE-AT-THE-END", E.outcome_of({"outcome": FAIL, "note": note}, what="x")[1]
        )

    def test_a_short_reason_is_handed_over_unchanged(self):
        """Negative control: nothing is appended or reworded, so a short note stays itself."""
        self.assertEqual(E.outcome_of({"outcome": FAIL, "note": "short"}, what="x")[1], "short")

    def _with_verdict(self, axes):
        def fake(**kw):
            return {"axes": axes}

        with mock.patch.object(self._P, "plan_verdict", fake):
            return E._person_in_plan("k.png", plan=self._P, pose=lambda p: self.GOOD)

    @staticmethod
    def _axis(name, *, violations=0, unmeasured=0, note=""):
        return {
            "name": name,
            "checked": 0 if unmeasured else 1,
            "violations": violations,
            "unmeasured": unmeasured,
            "note": note,
        }

    def test_an_unmeasured_axis_keeps_the_tail_of_its_reason(self):
        note = self._long("WHY-IT-DID-NOT-READ")
        got = self._with_verdict([self._axis("centre", unmeasured=1, note=note)])
        self.assertEqual(got[1], UNMEASURED)
        self.assertIn("WHY-IT-DID-NOT-READ", got[2])

    def test_an_unmeasured_axis_with_a_short_reason_says_exactly_it(self):
        """Negative control: the short path is a pass-through, not a formatting stage."""
        got = self._with_verdict([self._axis("centre", unmeasured=1, note="no pose")])
        self.assertEqual(got[2], "no pose")

    def test_the_passing_axes_keep_the_tail_of_their_joined_reasons(self):
        axes = [
            self._axis(n, note=self._long(f"AXIS-{n.upper()}", 200)) for n in ("centre", "width")
        ]
        got = self._with_verdict(axes)
        self.assertEqual(got[1], PASS)
        self.assertIn("AXIS-CENTRE", got[2])
        self.assertIn("AXIS-WIDTH", got[2])

    def test_two_short_passing_axes_are_joined_and_nothing_else(self):
        """Negative control: the join is the whole transformation on the short path."""
        axes = [self._axis("centre", note="a"), self._axis("width", note="b")]
        self.assertEqual(self._with_verdict(axes)[2], "a; b")

    def test_the_driving_card_verdict_keeps_the_tail_of_its_reason(self):
        note = self._long("CARD-SAID-THIS")

        def in_card(points, card):
            return {"outcome": FAIL, "note": note}

        with mock.patch.object(self._P, "in_card", in_card):
            got = E._person_in_plan(
                "k.png", plan=self._P, pose=lambda p: self.GOOD, card={"outcome": PASS}
            )
        self.assertEqual(got[1], FAIL)
        self.assertIn("CARD-SAID-THIS", got[2])

    def test_a_short_card_verdict_is_reported_as_it_stands(self):
        """Negative control."""

        def in_card(points, card):
            return {"outcome": PASS, "note": "inside"}

        with mock.patch.object(self._P, "in_card", in_card):
            got = E._person_in_plan(
                "k.png", plan=self._P, pose=lambda p: self.GOOD, card={"outcome": PASS}
            )
        self.assertEqual(got[2], "inside")

    def _window(self, note):
        return E.stage_window(
            driving="d.mp4", out_path="w.mp4", first=0, last=9, probe=lambda p: {"note": note}
        )

    def test_a_probe_that_could_not_measure_keeps_the_tail_of_its_reason(self):
        got = self._window(self._long("FFPROBE-TAIL"))
        self.assertEqual(got["checks"][0]["outcome"], UNMEASURED)
        self.assertIn("FFPROBE-TAIL", got["checks"][0]["note"])

    def test_a_short_probe_reason_is_reported_as_it_stands(self):
        """Negative control."""
        self.assertEqual(self._window("no such file")["checks"][0]["note"], "no such file")

    def test_the_paid_orders_reply_is_quoted_whole_when_it_carries_no_video(self):
        """The fal answer is the only evidence of a call that was already paid for."""
        reply = {"detail": self._long("REASON-FAL-REFUSED")}
        answers = [{"request_id": "r1"}, {"status": "COMPLETED"}, reply]

        class _Fh:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout=None):
            return _Fh(answers.pop(0))

        with (
            mock.patch.dict("os.environ", {"FAL_KEY": "k"}),
            mock.patch.object(urllib.request, "urlopen", urlopen),
            mock.patch.object(E.time, "sleep", lambda s: None),
        ):
            with self.assertRaises(RuntimeError) as caught:
                E.live_kling(
                    video_url="v",
                    image_url="i",
                    character_orientation="portrait",
                    out_path="o.mp4",
                    poll_s=0,
                )
        self.assertIn("REASON-FAL-REFUSED", str(caught.exception))

    # -- the reason a cut did not happen ------------------------------------

    def _cut_failing_with(self, stderr: str) -> dict:
        """Run the real ffmpeg branch of `stage_window` with a failing cut."""

        class _Run:
            returncode = 1
            # Declared on the class, not stuck on the instance afterwards:
            # the typechecker is part of `scripts/check`, and an attribute
            # that only exists at runtime fails it.
            stderr = ""

        run = _Run()
        run.stderr = stderr
        with (
            mock.patch("shutil.which", lambda name: "/usr/bin/ffmpeg"),
            mock.patch.object(E.subprocess, "run", lambda *a, **kw: run),
        ):
            return E.stage_window(
                driving="d.mp4",
                out_path="w.mp4",
                first=0,
                last=149,
                probe=lambda p: {"fps": 30.0, "frames": 1000, "note": "probed"},
            )

    def test_the_opening_of_a_long_ffmpeg_reason_is_not_dropped(self):
        """This cut kept the LAST 300 characters, so the half it lost was the opening.

        ffmpeg names the option it would not accept in its first lines and
        reports the failure near the end; a tail-only note reads as if the
        command had been fine up to the moment it stopped.
        """
        stderr = "OPENING-OPTION-NAMED " + "filler " * 200 + "and then it stopped"
        cut = [c for c in self._cut_failing_with(stderr)["checks"] if c["name"] == "cut"][0]
        self.assertEqual(cut["outcome"], UNMEASURED)
        self.assertIn("OPENING-OPTION-NAMED", cut["note"])

    def test_the_closing_of_a_long_ffmpeg_reason_is_kept_too(self):
        """The end was never the side this call dropped: this holds it so it cannot become one."""
        cut = [
            c
            for c in self._cut_failing_with(self._long("FILTER-REJECTED-HERE"))["checks"]
            if c["name"] == "cut"
        ][0]
        self.assertIn("FILTER-REJECTED-HERE", cut["note"])

    def test_a_short_ffmpeg_reason_is_reported_as_it_stands(self):
        """Negative control: a device that always finds its sentinel measures nothing."""
        cut = [c for c in self._cut_failing_with("no such file")["checks"] if c["name"] == "cut"][0]
        self.assertEqual(cut["note"], "RuntimeError: ffmpeg returned 1: no such file")

    # -- the axis that did not read, not the first one ----------------------

    def test_the_unmeasured_axis_is_the_one_quoted(self):
        """`axes[0]` quoted an axis that had read, under a "could not measure" verdict."""
        got = self._with_verdict(
            [
                self._axis("centre", note="CENTRE-READ-FINE"),
                self._axis("width", unmeasured=1, note="WIDTH-HAD-NO-POINTS"),
            ]
        )
        self.assertEqual(got[1], UNMEASURED)
        self.assertIn("WIDTH-HAD-NO-POINTS", got[2])
        self.assertNotIn("CENTRE-READ-FINE", got[2])

    def test_every_axis_that_did_not_read_is_quoted(self):
        got = self._with_verdict(
            [
                self._axis("centre", unmeasured=1, note="CENTRE-BLIND"),
                self._axis("width", unmeasured=1, note="WIDTH-BLIND"),
            ]
        )
        self.assertIn("CENTRE-BLIND", got[2])
        self.assertIn("WIDTH-BLIND", got[2])

    def test_axes_that_all_read_do_not_reach_the_unmeasured_branch(self):
        """Negative control: the branch must stay shut when every axis answered."""
        got = self._with_verdict([self._axis("centre", note="a"), self._axis("width", note="b")])
        self.assertEqual(got[1], PASS)

    # -- every reason the pose reader gave, and the sample against the whole -

    FRAMES = [f"{i:05d}.png" for i in range(300)]

    def _card_with_breakages(self, how_many: int) -> dict:
        seen = []

        def reader(path):
            seen.append(path)
            if len(seen) <= how_many:
                raise RuntimeError(f"FRAME-{len(seen)}-BROKE")
            return _pose_ok(path)

        return E.driving_card(self.FRAMES, pose=reader)

    def test_every_frame_that_threw_is_named_not_only_the_first(self):
        note = self._card_with_breakages(3)["note"]
        for n in (1, 2, 3):
            self.assertIn(f"FRAME-{n}-BROKE", note)

    def test_a_card_read_without_breakage_says_nothing_about_throwing(self):
        """Negative control: the tail is added only when there is something to add."""
        self.assertNotIn("threw", self._card_with_breakages(0)["note"])

    def test_a_reader_that_threw_on_every_frame_names_every_reason(self):
        note = E.driving_card(self.FRAMES, pose=self._always_throwing())["note"]
        self.assertIn("FRAME-1-BROKE", note)
        self.assertIn("FRAME-24-BROKE", note)
        self.assertIn("frames sampled from 300", note)

    @staticmethod
    def _always_throwing():
        seen = []

        def reader(path):
            seen.append(path)
            raise RuntimeError(f"FRAME-{len(seen)}-BROKE")

        return reader

    def test_a_card_measured_on_a_sample_says_the_sample_and_the_whole(self):
        """A partial result printed as numbers, so 24 frames cannot read as the clip."""
        self.assertIn(
            "sampled 24 of 300 frames", E.driving_card(self.FRAMES, pose=_pose_ok)["note"]
        )

    def test_a_card_measured_on_every_frame_claims_no_sampling(self):
        """Negative control: with nothing skipped there is no sample to declare."""
        note = E.driving_card(self.FRAMES[:10], pose=_pose_ok)["note"]
        self.assertNotIn("sampled", note)
        self.assertIn("over 10 frames of 10", note)


class TwoDecisionConstantsNobodyWasWatching(unittest.TestCase):
    """Both survived every mutation of their value with the suite still green.

    A constant no test moves with is a decision nobody guards: `FRAME_SUFFIXES`
    could be cut to `.png` alone and every jpeg driving would have gone
    unreadable in silence, and `KLING_OUT_SIZE` could be set to any pair at all
    without the note it exists to phrase saying anything different.
    """

    def test_a_jpeg_frame_directory_is_read_as_frames(self):
        with TemporaryDirectory() as td:
            for name in ("a.jpg", "b.JPEG", "c.png"):
                (Path(td) / name).write_bytes(b"")
            got = E.frame_paths(td)
        self.assertEqual([Path(p).name for p in got], ["a.jpg", "b.JPEG", "c.png"])

    def test_a_directory_of_something_else_is_refused_by_name(self):
        """Negative control, and the other side of the bar.

        The wanted list is matched with its opening words attached, so that a
        FOURTH suffix moves this too: a set clamped only against shrinking is
        not clamped.
        """
        with TemporaryDirectory() as td:
            (Path(td) / "report.json").write_bytes(b"{}")
            with self.assertRaises(ValueError) as caught:
                E.frame_paths(td)
        self.assertIn("expected files .jpeg, .jpg, .png", str(caught.exception))

    @staticmethod
    def _geometry_note(w, h):
        res = E.stage_output_acceptance(
            produced="p.mp4",
            client_photo="c.png",
            frames_dir="d",
            probe=lambda p: {"width": w, "height": h, "fps": 30.0, "frames": 99},
            decode=_decode_ok,
            distances=lambda fr, an: {"outcome": PASS, "median": 0.20, "inside": 99, "judged": 99},
            cuts=lambda p: {"outcome": PASS, "cuts": [], "note": ""},
        )
        return [c for c in res["checks"] if c["name"] == "output geometry"][0]

    def test_the_recorded_geometry_is_recognised_as_the_familiar_one(self):
        self.assertEqual(self._geometry_note(960, 960)["outcome"], PASS)
        self.assertIn("as on previous orders", self._geometry_note(960, 960)["note"])

    def test_an_unfamiliar_vertical_geometry_still_passes_but_is_named_as_new(self):
        """The record is a record, not a bar: 816x1104 passed and had to keep passing."""
        note = self._geometry_note(816, 1104)
        self.assertEqual(note["outcome"], PASS)
        self.assertIn("new geometry", note["note"])
        self.assertIn("960x960", note["note"])


class TheAestheticModeReachesEveryStage(unittest.TestCase):
    """MEASURED on a live run of 2026-09-01: `--aesthetic` died in stage 1 with
    `TypeError: expected str, bytes or os.PathLike object, not NoneType`.

    The mode is advertised by the CLI (`--style` is "not needed with --aesthetic"),
    and stage 2 resolves the aesthetic to its file itself. Stages 1 and 3 are handed
    the raw `style_ref`, which is `None` in that mode, so the one place that knows
    which file the style reference is cannot be read by the two stages that need it.
    """

    class _A:
        """Aesthetic neighbour with the real signature and no disk of its own."""

        @staticmethod
        def gender_of(_aid):
            return "f"

        @staticmethod
        def pair_check(*, client_gender, aesthetic_gender):
            ok = client_gender == aesthetic_gender
            return {"outcome": "pass" if ok else "fail", "note": "gender"}

        @staticmethod
        def aesthetic_file(aid):
            return f"assets/aesthetics/{aid}_f.png"

        @staticmethod
        def compose(_aid, *, card=None):
            return {"prompt": "aesthetic in words"}

        @staticmethod
        def assemble_prompt(*, card=None):
            return E.NO_BRANDS_CLAUSE

        @staticmethod
        def driving_of(_aid):
            return "README.md"

        @staticmethod
        def window_of(_aid):
            return (0, 99)

        @staticmethod
        def card_of(_aid):
            return None

    def test_stage_one_is_handed_the_aesthetic_file_not_none(self):
        seen = {}

        def intake(*, client_photo, style_ref, driving, driving_frames=None, card_reader=None):
            seen["style_ref"] = style_ref
            return {"outcome": "pass", "checked": 1, "violations": 0, "unmeasured": 0}

        got = E.stage_intake(
            client_photo="assets/fork_client_selfie_f.png",
            style_ref=E.aesthetic_style_ref("y2k", aesthetic_mod=self._A),
            driving="d.mp4",
            intake=intake,
        )
        self.assertEqual(seen["style_ref"], "assets/aesthetics/y2k_f.png")
        self.assertNotEqual(got["outcome"], "could not measure")

    def test_stage_three_measures_against_the_aesthetic_file_not_none(self):
        asked = []

        def similarity(a, b):
            asked.append((a, b))
            return 0.9 if "styled" in str(b) else 0.1

        got = E.stage_style_acceptance(
            styled="styled.png",
            style_ref=E.aesthetic_style_ref("y2k", aesthetic_mod=self._A),
            client_photo="assets/fork_client_selfie_f.png",
            similarity=similarity,
            distances=lambda *_a, **_k: {"outcome": "pass", "median": 0.1},
        )
        self.assertTrue(asked, "the style instrument was never called")
        self.assertTrue(
            all(a == "assets/aesthetics/y2k_f.png" for a, _b in asked),
            f"the floor and the hit must be taken against the aesthetic file: {asked}",
        )
        self.assertNotEqual(got["outcome"], "could not measure")

    def test_run_hands_stage_one_the_resolved_reference_not_none(self):
        """The seam itself: `run` in aesthetic mode, not the stages called by hand.

        This is the test the previous three were missing — they proved the helper
        and the stages, which is exactly the shape of coverage that let the defect
        live: every part green, the join untested.
        """
        seen = {}

        def intake(*, client_photo, style_ref, driving, driving_frames=None, card_reader=None):
            seen["style_ref"] = style_ref
            return {"outcome": "pass", "checked": 1, "violations": 0, "unmeasured": 0}

        def stylize(**_kw):
            raise RuntimeError("stop here: stage 1 is what this test watches")

        with TemporaryDirectory() as tmp:
            E.run(
                client_photo="assets/fork_client_selfie_f.png",
                out_dir=tmp,
                aesthetic="y2k",
                client_gender="f",
                aesthetic_mod=self._A,
                intake=intake,
                stylize=stylize,
                pose=lambda _p: {},
                log=io.StringIO(),
            )

        self.assertEqual(
            seen.get("style_ref"),
            "assets/aesthetics/y2k_f.png",
            "run must resolve the aesthetic before stage 1, not inside stage 2",
        )


class _AestheticStub:
    """Aesthetic neighbour of the shape the contract gives it, with no disk of its own.

    The four fields the order now reads — the demo frame, the driving copy, the
    window and the composition card — are answered here as literals so that a
    change in the base cannot move the expectation with the code.
    """

    DEMO = "assets/aesthetics/icecream_f.png"
    DRIVING = "assets/drivings/icecream_f.mp4"
    WINDOW = (150, 299)
    # The card of a template that seats the person on an ice cream scoop: the
    # ankles sit near the middle of the frame, which the global plan bands call
    # a defect and the aesthetic calls its own composition.
    CARD = {
        "shoulders": 0.30,
        "ankles": 0.4873,
        "centre": 0.53,
        "width": 0.31,
        "tolerances": {
            "shoulders": 0.05,
            "ankles": 0.05,
            "centre": 0.1837,
            "width": 0.1326,
        },
    }

    def __init__(self, *, card=CARD, driving=DRIVING, window=WINDOW):
        self._card = card
        self._driving = driving
        self._window = window

    def gender_of(self, _aid):
        return "f"

    def pair_check(self, *, client_gender, aesthetic_gender):
        ok = client_gender == aesthetic_gender
        return {
            "outcome": PASS if ok else FAIL,
            "checked": 1,
            "violations": 0 if ok else 1,
            "unmeasured": 0,
            "note": "stub gate",
        }

    def aesthetic_file(self, aid):
        return f"assets/aesthetics/{aid}_f.png"

    def compose(self, _aid, *, card=None):
        return {"prompt": "aesthetic in words"}

    def assemble_prompt(self, *, card=None):
        return "roles, " + E.NO_BRANDS_CLAUSE

    def driving_of(self, _aid):
        return self._driving

    def window_of(self, _aid):
        return self._window

    def card_of(self, _aid):
        return self._card


def _pose_on_the_ice_cream(_path):
    """A pose the ICECREAM template produces: ankles 0.4873, in the middle of the frame.

    MEASURED on the live paid run of 2026-09-01, where the global plan band
    0.86..0.99 called this correct frame a defect and stopped stage 2.
    """
    return {
        "l_shoulder": (0.685, 0.30, 0.99),
        "r_shoulder": (0.375, 0.30, 0.99),
        "l_ankle": (0.60, 0.4873, 0.96),
        "r_ankle": (0.46, 0.4873, 0.96),
    }


def _pose_off_the_card(_path):
    """The same person shoved to the right edge: off the aesthetic card on `centre`."""
    return {
        "l_shoulder": (0.99, 0.30, 0.99),
        "r_shoulder": (0.80, 0.30, 0.99),
        "l_ankle": (0.95, 0.4873, 0.96),
        "r_ankle": (0.85, 0.4873, 0.96),
    }


class TheOrderTakesAnAestheticAndNothingElse(unittest.TestCase):
    """Decisions 8 and 4: `--style` is gone, and the driving and the window are not asked for.

    Every case here is the command line's behaviour, not the text of the module.
    """

    def _seen(self, argv):
        seen = {}

        def fake_run(**kw):
            seen.update(kw)
            return {"exit_code": 0}

        with mock.patch.object(E, "run", fake_run):
            E.main(argv)
        return seen

    ORDER = ["--client", "c.png", "--aesthetic", "icecream", "--client-gender", "f"]

    def _refusal(self, argv) -> str:
        """Return what the parser said when it refused. The reason is the assertion.

        A bare `SystemExit` is not enough here: a flag that is still accepted
        while another required one is missing exits too, and the test would be
        green on the defect it names.
        """
        said = io.StringIO()
        with mock.patch("sys.stderr", said), self.assertRaises(SystemExit):
            self._seen(argv)
        return said.getvalue()

    def test_a_bare_order_is_accepted_and_carries_the_aesthetic(self):
        got = self._seen(list(self.ORDER))
        self.assertEqual(got["aesthetic"], "icecream")
        self.assertEqual(got["client_gender"], "f")

    def test_an_order_without_an_aesthetic_is_refused(self):
        said = self._refusal(["--client", "c.png", "--client-gender", "f"])
        self.assertIn("the following arguments are required: --aesthetic", said)

    def test_an_order_without_a_client_gender_is_refused(self):
        said = self._refusal(["--client", "c.png", "--aesthetic", "icecream"])
        self.assertIn("the following arguments are required: --client-gender", said)

    def test_the_style_flag_is_gone(self):
        self.assertIn(
            "unrecognized arguments: --style", self._refusal([*self.ORDER, "--style", "s.png"])
        )

    def test_the_driving_flag_is_gone(self):
        self.assertIn(
            "unrecognized arguments: --driving", self._refusal([*self.ORDER, "--driving", "d.mp4"])
        )

    def test_the_window_flag_is_gone(self):
        self.assertIn(
            "unrecognized arguments: --window", self._refusal([*self.ORDER, "--window", "150:299"])
        )


class TheDrivingAndTheWindowComeFromTheAesthetic(unittest.TestCase):
    """Decision 4: the aesthetic keeps its driving copy and its window; nobody retypes them."""

    def _run_to_the_window(self, stub=None, **over):
        """Drive `run` on stubs as far as stage 4 and return the whole reply.

        The driving the stub names is written to disk inside the run's own
        temporary directory, because stage 1 checks the file before anything
        else — a stub path that does not exist would stop the run at intake and
        the window would never be reached.
        """
        seen: dict = {}

        def probe(path):
            seen.setdefault("probed", []).append(str(path))
            return _probe_ok(path)

        def cutter(src, dst):
            seen["cut_from"] = str(src)
            Path(dst).write_bytes(b"\x00" * 32)
            first, last = _AestheticStub.WINDOW
            return {"path": str(dst), "frames": last - first + 1}

        def intake(*, client_photo, style_ref, driving, driving_frames=None, card_reader=None):
            seen["driving"] = str(driving)
            return {"outcome": PASS, "checked": 1, "violations": 0, "unmeasured": 0}

        plan = _PlanOk(arrived=EXACT_RETURN)
        with TemporaryDirectory() as td, _no_network():
            root = Path(td)
            client = root / "client.png"
            client.write_bytes(b"\x00" * 64)
            driving = root / Path(_AestheticStub.DRIVING).name
            driving.write_bytes(b"\x00" * 64)
            stub = _AestheticStub(driving=str(driving)) if stub is None else stub
            seen["names"] = {"driving": str(driving)}
            kw = dict(
                client_photo=client,
                out_dir=Path(td) / "out",
                aesthetic="icecream",
                client_gender="f",
                aesthetic_mod=stub,
                intake=intake,
                stylize=_stylize_ok,
                similarity=_similarity_ok,
                distances=_distances_ok,
                probe=probe,
                cutter=cutter,
                decode=_decode_ok,
                cuts=_cuts_ok,
                upload=_upload_ok,
                kling=_kling_ok,
                finish=_finish_ok,
                plan=plan,
                sizer=plan.sizer,
                cropper=plan.cropper,
                pose=_pose_on_the_ice_cream,
                log=io.StringIO(),
            )
            kw.update(over)
            got = E.run(**kw)
        return got, seen

    def test_the_driving_the_aesthetic_names_is_the_one_that_is_cut(self):
        got, seen = self._run_to_the_window()
        named = seen["names"]["driving"]
        self.assertEqual(seen.get("driving"), named)
        self.assertEqual(seen.get("cut_from"), named)
        self.assertEqual(got["outcome"], PASS, got["stopped_at"])

    def test_the_window_the_aesthetic_names_is_the_one_that_is_cut(self):
        got, _seen = self._run_to_the_window()
        numbers = got["stages"][3]["numbers"]
        self.assertEqual((numbers["first"], numbers["last"]), _AestheticStub.WINDOW)

    def test_a_window_handed_in_next_to_an_aesthetic_is_refused(self):
        """Two answers to one question: the operator's window and the aesthetic's."""
        with self.assertRaises(ValueError):
            self._run_to_the_window(first=0, last=99)

    def test_a_driving_handed_in_next_to_an_aesthetic_is_refused(self):
        with self.assertRaises(ValueError):
            self._run_to_the_window(driving="other.mp4")


class TheStyliserIsGivenOnePicture(unittest.TestCase):
    """Decision 2: photo plus prompt through `images_edit`, never `compose` with two."""

    def test_the_client_photo_is_the_only_image_that_goes_out(self):
        sent: list = []

        def edit(prompt, ref_path, out_path, **kw):
            sent.append({"prompt": prompt, "ref": str(ref_path), "size": kw})
            Path(out_path).write_bytes(b"\x00" * 8)
            return str(out_path)

        def refuse(*_a, **_k):
            raise AssertionError("compose() is the two-image route and must not be called")

        with TemporaryDirectory() as td, mock.patch.object(E.pollinations, "compose", refuse):
            E.live_stylize(
                person="client.png",
                style="aesthetic_demo.png",
                prompt="a look",
                out_path=Path(td) / "styled.png",
                edit=edit,
            )
        self.assertEqual(len(sent), E.STYLE_IMAGES, f"images sent: {sent}")
        self.assertEqual(len(sent), 1, f"exactly one picture goes to the styliser: {sent}")
        self.assertEqual(sent[0]["ref"], "client.png")
        self.assertEqual(sent[0]["prompt"], "a look")

    def test_the_asked_size_is_still_the_frame(self):
        sent: dict = {}

        def edit(prompt, ref_path, out_path, **kw):
            sent.update(kw)
            return str(out_path)

        with TemporaryDirectory() as td:
            E.live_stylize(
                person="client.png",
                style=None,
                prompt="a look",
                out_path=Path(td) / "styled.png",
                edit=edit,
            )
        self.assertEqual((sent.get("width"), sent.get("height")), tuple(E.STYLED_SIZE))


class TheCompositionIsJudgedByTheAestheticCard(unittest.TestCase):
    """Decision 3, and the defect it repairs.

    MEASURED on the live paid run of 2026-09-01: the `icecream` template seats
    the person on a scoop, the ankles came out at 0.4873 against the global plan
    band 0.86..0.99, and stage 2 stopped on a CORRECT frame. The plan bands are
    not the aesthetic's criterion; the aesthetic's own card is.
    """

    def _stage(self, stub, pose, **over):
        with TemporaryDirectory() as td:
            return _stylize_stage(
                Path(td) / "styled.png",
                plan=_PlanOk(arrived=EXACT_RETURN),
                aesthetic="icecream",
                client_gender="f",
                aesthetic_mod=stub,
                prompt=None,
                pose=pose,
                **over,
            )

    def _person_checks(self, got):
        return [c for c in got["checks"] if c["name"].startswith("person in")]

    def test_a_frame_on_the_aesthetic_card_passes_though_the_plan_bands_refuse_it(self):
        got = self._stage(_AestheticStub(), _pose_on_the_ice_cream)
        checks = self._person_checks(got)
        self.assertEqual(len(checks), 1, [c["name"] for c in got["checks"]])
        self.assertEqual(checks[0]["name"], "person in the aesthetic card")
        self.assertEqual(checks[0]["outcome"], PASS, checks[0]["note"])
        self.assertEqual(got["outcome"], PASS, [c for c in got["checks"] if c["outcome"] != PASS])

    def test_a_frame_off_the_aesthetic_card_is_still_a_defect(self):
        got = self._stage(_AestheticStub(), _pose_off_the_card)
        checks = self._person_checks(got)
        self.assertEqual(checks[0]["name"], "person in the aesthetic card")
        self.assertEqual(checks[0]["outcome"], FAIL, checks[0]["note"])

    def test_an_aesthetic_without_a_card_is_unmeasured_and_not_judged_by_the_bands(self):
        """The third outcome: no card is "could not measure", never the global bands."""
        got = self._stage(_AestheticStub(card=None), _pose_on_the_ice_cream)
        checks = self._person_checks(got)
        self.assertEqual(len(checks), 1, [c["name"] for c in got["checks"]])
        self.assertEqual(checks[0]["outcome"], UNMEASURED, checks[0]["note"])
        self.assertNotEqual(checks[0]["outcome"], FAIL)
        self.assertNotEqual(checks[0]["outcome"], PASS)

    def test_without_an_aesthetic_the_plan_bands_still_judge(self):
        """The negative control: the bands are not deleted, they are scoped."""
        with TemporaryDirectory() as td:
            got = _stylize_stage(
                Path(td) / "styled.png",
                plan=_PlanOk(arrived=EXACT_RETURN),
                pose=_pose_on_the_ice_cream,
            )
        checks = self._person_checks(got)
        self.assertEqual(checks[0]["name"], "person in plan")
        self.assertEqual(checks[0]["outcome"], FAIL, checks[0]["note"])
