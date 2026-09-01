"""Gates for the aesthetic build command. Expected numbers are literals, never imports.

Every route out of the process is injected, so nothing here touches the
network. Two claims run through the whole file: a stage that could not measure
says so instead of passing, and the paid call is reached only after the cheap
stages have passed — which is checked by counting calls, not by reading code.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from lipsync import fork_aesthetic_build as B
from lipsync import fork_aesthetic, fork_e2e
from lipsync.fork_identity import FAIL, PASS, UNMEASURED

# The demo pose used everywhere a card is read. Chosen so every number the card
# reports is arithmetic a reader can redo by hand.
DEMO_POSE = {
    "l_shoulder": (0.4, 0.3, 0.9),
    "r_shoulder": (0.6, 0.3, 0.9),
    "l_ankle": (0.45, 0.92, 0.9),
    "r_ankle": (0.55, 0.92, 0.9),
}

# C2: evidence is not truncated. Markers at both ends, because `[:N]` cuts the
# tail and `[-N:]` cuts the head.
EVIDENCE_HEAD = "HEADMARK_a71c"
EVIDENCE_TAIL = "TAILMARK_5f03"
LONG_EVIDENCE = EVIDENCE_HEAD + " " + ("filler " * 90) + EVIDENCE_TAIL


def outcome_of(stage: dict, name: str) -> str:
    """Return one named check's outcome, or a marker that says it is absent."""
    for check in stage["checks"]:
        if check["name"] == name:
            return check["outcome"]
    return f"NO CHECK NAMED {name!r} among {[c['name'] for c in stage['checks']]}"


def note_of(stage: dict, name: str) -> str:
    for check in stage["checks"]:
        if check["name"] == name:
            return str(check["note"])
    return ""


def a_file(directory, name: str, text: str = "x") -> str:
    path = Path(directory) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


class Counter:
    """A stand-in that records every call. Injected wherever money or a network is."""

    def __init__(self, reply=None, boom=None) -> None:
        self.calls: list = []
        self.reply = reply
        self.boom = boom

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.boom is not None:
            raise self.boom
        return self.reply


def fake_distances(*, near, far):
    """Distances keyed on the reference: `near` files answer close, everything else far."""

    def distances(paths, reference):
        value = 0.1 if str(reference) in {str(n) for n in near} else far
        return {"outcome": PASS, "median": value, "inside": len(paths), "judged": len(paths)}

    return distances


def good_probe(_path):
    return {
        "outcome": PASS,
        "fps": 30.0,
        "frames": 300,
        "width": 720,
        "height": 1280,
        "note": "300 frames at 30.0 fps, 720x1280",
    }


def good_cutter(want):
    def cutter(_src, dst):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"cut")
        return {"path": str(dst), "frames": want}

    return cutter


class Stage1AcceptsTheDriving(unittest.TestCase):
    def test_a_missing_driving_never_reaches_the_intake(self) -> None:
        """The cheap check first: a file that is not there costs no instrument."""
        intake = Counter(reply={"outcome": PASS, "checked": 6, "violations": 0, "unmeasured": 0})
        got = B.stage_driving(driving="/no/such/driving.mp4", intake=intake)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(intake.calls, [], "the intake ran on a file that does not exist")

    def test_the_intake_verdict_is_carried_with_its_numbers(self) -> None:
        with TemporaryDirectory() as tmp:
            driving = a_file(tmp, "d.mp4")
            intake = Counter(
                reply={
                    "outcome": PASS,
                    "checked": 6,
                    "violations": 0,
                    "unmeasured": 0,
                    "fps": 30.0,
                    "seconds": 10.0,
                    "axes": {"cuts": {"outcome": PASS}},
                    "note": "six axes",
                }
            )
            got = B.stage_driving(driving=driving, frames=["a.png"], intake=intake)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["numbers"]["fps"], 30.0)
        self.assertEqual(got["numbers"]["frames_given"], 1)
        self.assertIn("checked 6", note_of(got, "driving intake"))

    def test_an_intake_without_a_verdict_is_not_a_pass(self) -> None:
        """Negative control on the third outcome: no verdict is not permission."""
        with TemporaryDirectory() as tmp:
            got = B.stage_driving(driving=a_file(tmp, "d.mp4"), intake=Counter(reply="fine"))
        self.assertEqual(got["outcome"], UNMEASURED)

    def test_a_crashed_intake_keeps_the_whole_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            got = B.stage_driving(
                driving=a_file(tmp, "d.mp4"), intake=Counter(boom=RuntimeError(LONG_EVIDENCE))
            )
        note = note_of(got, "driving intake")
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn(EVIDENCE_HEAD, note)
        self.assertIn(EVIDENCE_TAIL, note)


class Stage2CleansThePrompt(unittest.TestCase):
    def test_an_empty_prompt_never_reaches_the_composer(self) -> None:
        composer = Counter(reply={"outcome": PASS, "prompt": "x"})
        got = B.stage_prompt(prompt="   ", aesthetic_id="ramp", composer=composer)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(composer.calls, [])

    def test_the_assembled_prompt_carries_the_ban_and_the_identity_clause(self) -> None:
        """Through the real neighbour: the two standing clauses must survive."""
        got = B.stage_prompt(
            prompt="a rain-soaked neon alley, wide lens, cold grade",
            aesthetic_id="ramp",
        )
        self.assertEqual(outcome_of(got, "lettering ban"), PASS)
        self.assertEqual(outcome_of(got, "identity clause"), PASS)
        self.assertIn(fork_aesthetic.no_brands_clause(), got["prompt"])
        self.assertIn(fork_aesthetic.IDENTITY_CLAUSE, got["prompt"])

    def test_a_prompt_cut_below_the_ceiling_passes(self) -> None:
        got = B.stage_prompt(
            prompt="p",
            aesthetic_id="ramp",
            composer=Counter(reply={"outcome": PASS, "prompt": "kept", "cut": {"cut_share": 0.4}}),
        )
        self.assertEqual(outcome_of(got, "prompt survived the cut"), PASS)

    def test_a_prompt_cut_above_the_ceiling_fails(self) -> None:
        """The other side of the clamp: a threshold pressed from one side is not a threshold."""
        got = B.stage_prompt(
            prompt="p",
            aesthetic_id="ramp",
            composer=Counter(reply={"outcome": PASS, "prompt": "kept", "cut": {"cut_share": 0.6}}),
        )
        self.assertEqual(outcome_of(got, "prompt survived the cut"), FAIL)
        self.assertEqual(got["outcome"], FAIL)

    def test_the_ceiling_admits_its_own_value(self) -> None:
        """A bar is a bar: exactly at it is inside, and the value is a literal here."""
        got = B.stage_prompt(
            prompt="p",
            aesthetic_id="ramp",
            composer=Counter(reply={"outcome": PASS, "prompt": "kept", "cut": {"cut_share": 0.5}}),
        )
        self.assertEqual(outcome_of(got, "prompt survived the cut"), PASS)

    def test_an_unknown_cut_share_is_not_a_pass(self) -> None:
        got = B.stage_prompt(
            prompt="p",
            aesthetic_id="ramp",
            composer=Counter(reply={"outcome": PASS, "prompt": "kept", "cut": {}}),
        )
        self.assertEqual(outcome_of(got, "prompt survived the cut"), UNMEASURED)

    def test_a_prompt_that_did_not_assemble_stops_the_stage(self) -> None:
        got = B.stage_prompt(
            prompt="p",
            aesthetic_id="ramp",
            composer=Counter(reply={"outcome": UNMEASURED, "prompt": None, "note": "no prompt"}),
        )
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIsNone(got.get("prompt"))


class Stage3StylisesTheDemo(unittest.TestCase):
    def test_one_reference_and_the_delivery_frame_go_to_the_route(self) -> None:
        """The owner's decision 2: img2img with ONE picture, at 720x1280."""
        edit = Counter(reply="/out/demo.png")
        with mock.patch.object(B.pollinations, "images_edit", edit):
            B.stylize_demo(prompt="P", demo="/demo.png", out_path="/out/demo.png")
        (args, kwargs) = edit.calls[0]
        self.assertEqual(args, ("P", "/demo.png", "/out/demo.png"))
        self.assertEqual(kwargs["width"], 720)
        self.assertEqual(kwargs["height"], 1280)
        self.assertEqual(kwargs["model"], "nanobanana-2")

    def test_an_unknown_gender_never_reaches_the_route(self) -> None:
        stylize = Counter()
        got = B.stage_stylize(prompt="P", gender="x", out_path="/tmp/x.png", stylize=stylize)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(stylize.calls, [])

    def _made(self, tmp, size):
        out = Path(tmp) / "demo.png"

        def stylize(*, prompt, demo, out_path):
            Path(out_path).write_bytes(b"png")
            return str(out_path)

        return B.stage_stylize(
            prompt="P",
            gender="f",
            out_path=out,
            stylize=stylize,
            sizer=lambda _p: size,
        )

    def test_the_ordered_size_coming_back_is_a_pass(self) -> None:
        with TemporaryDirectory() as tmp:
            got = self._made(tmp, (720, 1280))
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["numbers"]["got"], [720, 1280])

    def test_a_size_nobody_ordered_is_a_violation(self) -> None:
        """Negative control: the check must be able to go red on a real defect."""
        with TemporaryDirectory() as tmp:
            got = self._made(tmp, (768, 1376))
        self.assertEqual(outcome_of(got, "the route kept the ordered size"), FAIL)

    def test_a_size_that_was_never_read_is_not_a_pass(self) -> None:
        with TemporaryDirectory() as tmp:
            got = self._made(tmp, None)
        self.assertEqual(outcome_of(got, "the route kept the ordered size"), UNMEASURED)

    def test_a_refusing_route_is_not_measured_rather_than_failed(self) -> None:
        with TemporaryDirectory() as tmp:
            got = B.stage_stylize(
                prompt="P",
                gender="f",
                out_path=Path(tmp) / "demo.png",
                stylize=Counter(boom=RuntimeError(LONG_EVIDENCE)),
            )
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn(EVIDENCE_HEAD, note_of(got, "img2img call"))
        self.assertIn(EVIDENCE_TAIL, note_of(got, "img2img call"))


class Stage4AcceptsTheDemoFrame(unittest.TestCase):
    def _run(self, *, near, far, size):
        return B.stage_demo_acceptance(
            made="/made.png",
            gender="f",
            distances=fake_distances(near=near, far=far),
            sizer=lambda _p: size,
        )

    def test_the_demo_survived_and_the_other_demo_stayed_out(self) -> None:
        got = self._run(near=[B.demo_path("f")], far=0.8, size=(720, 1280))
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(outcome_of(got, "demo identity survived"), PASS)
        self.assertEqual(outcome_of(got, "the other demo did not leak"), PASS)
        self.assertEqual(outcome_of(got, "9:16 canvas"), PASS)

    def test_the_other_demo_being_closer_is_a_leak(self) -> None:
        """Negative control: exactly the defect the check names, made to happen."""
        got = self._run(near=[B.other_demo_path("f")], far=0.8, size=(720, 1280))
        self.assertEqual(outcome_of(got, "the other demo did not leak"), FAIL)
        self.assertEqual(got["outcome"], FAIL)

    def test_a_square_canvas_is_not_the_plan(self) -> None:
        got = self._run(near=[B.demo_path("f")], far=0.8, size=(1024, 1024))
        self.assertEqual(outcome_of(got, "9:16 canvas"), FAIL)

    def test_a_repainted_person_fails_the_identity_axis(self) -> None:
        got = B.stage_demo_acceptance(
            made="/made.png",
            gender="f",
            distances=lambda paths, ref: {"outcome": PASS, "median": 0.95},
            sizer=lambda _p: (720, 1280),
        )
        self.assertEqual(outcome_of(got, "demo identity survived"), FAIL)

    def test_an_unknown_gender_is_refused_before_any_instrument(self) -> None:
        distances = Counter()
        got = B.stage_demo_acceptance(made="/made.png", gender="x", distances=distances)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(distances.calls, [])


class Stage5ReadsTheCard(unittest.TestCase):
    def test_the_card_is_read_off_the_demo_frame(self) -> None:
        got = B.stage_card(made="/made.png", pose=lambda _p: DEMO_POSE)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(
            got["card"],
            {
                "shoulders": 0.3,
                "ankles": 0.92,
                "centre": 0.5,
                "width": 0.2,
                "tolerances": {
                    "shoulders": 0.05,
                    "ankles": 0.05,
                    "centre": 0.05,
                    "width": 0.05,
                },
            },
        )

    def test_a_pose_that_did_not_read_gives_no_card(self) -> None:
        """Negative control: an unread pose must not produce a guessed card."""
        got = B.stage_card(made="/made.png", pose=lambda _p: {})
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIsNone(got["card"])

    def test_an_incomplete_card_is_not_carried_into_the_draft(self) -> None:
        """A card missing an axis would leave the user frame judged against a hole."""
        legs_only = {"l_ankle": (0.45, 0.92, 0.9), "r_ankle": (0.55, 0.92, 0.9)}
        got = B.stage_card(made="/made.png", pose=lambda _p: legs_only)
        self.assertIsNone(got["card"])
        self.assertNotEqual(got["outcome"], PASS)


class Stage6SpendsTheMoneyLast(unittest.TestCase):
    def _trial(self, tmp, *, first, last, upload, kling):
        return B.stage_trial(
            styled=a_file(tmp, "demo.png"),
            driving=a_file(tmp, "d.mp4"),
            first=first,
            last=last,
            work_dir=Path(tmp) / "draft",
            upload=upload,
            kling=kling,
            probe=good_probe,
            cutter=good_cutter(last - first + 1),
            decode=lambda video, out: {"paths": [f"{out}/0.png", f"{out}/1.png"]},
            distances=lambda paths, ref: {
                "outcome": PASS,
                "median": 0.1,
                "inside": 2,
                "judged": 2,
            },
            cuts=lambda paths: {"outcome": PASS, "cuts": []},
        )

    def test_a_window_outside_the_driving_costs_nothing(self) -> None:
        upload, kling = Counter(), Counter()
        with TemporaryDirectory() as tmp:
            got = self._trial(tmp, first=100, last=400, upload=upload, kling=kling)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(upload.calls, [], "the inputs went out for a window that is not there")
        self.assertEqual(kling.calls, [], "a paid order was placed on a bad window")

    def test_the_trial_clip_comes_back_and_is_accepted(self) -> None:
        with TemporaryDirectory() as tmp:
            trial = Path(tmp) / "draft" / "trial.mp4"

            def kling(**kwargs):
                trial.parent.mkdir(parents=True, exist_ok=True)
                trial.write_bytes(b"mp4")
                return str(trial)

            got = self._trial(
                tmp, first=0, last=149, upload=Counter(reply="https://x/1"), kling=kling
            )
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(Path(got["trial"]).name, "trial.mp4")

    def test_exactly_one_paid_order_is_placed(self) -> None:
        with TemporaryDirectory() as tmp:
            trial = Path(tmp) / "draft" / "trial.mp4"

            def place(**kwargs):
                trial.parent.mkdir(parents=True, exist_ok=True)
                trial.write_bytes(b"mp4")
                return str(trial)

            kling = Counter()
            kling.reply = None

            def counted(**kwargs):
                kling.calls.append(((), kwargs))
                return place(**kwargs)

            self._trial(tmp, first=0, last=149, upload=Counter(reply="u"), kling=counted)
        self.assertEqual(len(kling.calls), 1, f"orders placed: {len(kling.calls)}")

    def test_a_window_shorter_than_the_neighbour_threshold_costs_nothing(self) -> None:
        """The scene-length bar lives in `fork_e2e`; this stage must obey it, both ways.

        The neighbour's constant is patched on the module object rather than in
        its file, so nothing in a shared tree is edited to run this.
        """
        upload, kling = Counter(), Counter()
        with TemporaryDirectory() as tmp:
            with mock.patch.object(fork_e2e, "MIN_SCENE_S", 5.0):
                # 90 frames at 30 fps is 3.0 s, which the shipped bar admits.
                strict = self._trial(tmp, first=0, last=89, upload=upload, kling=kling)
        self.assertEqual(strict["outcome"], FAIL)
        self.assertEqual(kling.calls, [])

        upload2, kling2 = Counter(reply="u"), Counter()
        with TemporaryDirectory() as tmp:
            trial = Path(tmp) / "draft" / "trial.mp4"

            def place(**kwargs):
                trial.parent.mkdir(parents=True, exist_ok=True)
                trial.write_bytes(b"mp4")
                kling2.calls.append(((), kwargs))
                return str(trial)

            with mock.patch.object(fork_e2e, "MIN_SCENE_S", 2.0):
                # 60 frames at 30 fps is 2.0 s, which the shipped bar refuses.
                loose = self._trial(tmp, first=0, last=59, upload=upload2, kling=place)
        self.assertEqual(loose["outcome"], PASS)
        self.assertEqual(len(kling2.calls), 1)


class Stage7WritesTheDraft(unittest.TestCase):
    def _element(self, trial):
        return B.draft_element(
            aesthetic_id="ramp",
            name="Ramp",
            prompt="P",
            gender="f",
            demo_why="the driving actor is a woman",
            window=(150, 299),
            card={"shoulders": 0.53},
            trial=trial,
        )

    def test_the_element_is_the_contract_schema(self) -> None:
        element = self._element("/somewhere/trial.mp4")
        self.assertEqual(
            sorted(element),
            [
                "card",
                "demo",
                "demo_why",
                "driving",
                "id",
                "kind",
                "name",
                "prompt",
                "trial",
                "window",
            ],
        )
        self.assertEqual(element["driving"], "assets/drivings/ramp_f.mp4")
        self.assertEqual(element["trial"], "docs/trials/ramp_f.mp4")
        self.assertEqual(element["window"], [150, 299])
        self.assertEqual(element["kind"], "transform")

    def test_a_draft_without_a_trial_clip_is_a_violation(self) -> None:
        """The owner's decision 5, made machine: no trial, no aesthetic."""
        with TemporaryDirectory() as tmp:
            got = B.stage_draft(
                out_dir=Path(tmp) / "draft",
                element=self._element(None),
                styled=a_file(tmp, "demo.png"),
                driving=a_file(tmp, "d.mp4"),
                trial=None,
                report={"x": 1},
            )
        self.assertEqual(outcome_of(got, "trial in the draft"), FAIL)
        self.assertEqual(got["outcome"], FAIL)

    def test_a_draft_with_a_trial_clip_holds_every_file(self) -> None:
        """The other side: the same gate must go green when the clip is there."""
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "draft"
            got = B.stage_draft(
                out_dir=out,
                element=self._element("/x/trial.mp4"),
                styled=a_file(tmp, "demo.png"),
                driving=a_file(tmp, "d.mp4"),
                trial=a_file(tmp, "trial.mp4"),
                report={"x": 1},
            )
            names = sorted(p.name for p in out.iterdir())
            written = json.loads((out / "aesthetic.json").read_text(encoding="utf-8"))
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(
            names, ["aesthetic.json", "demo.png", "driving.mp4", "report.json", "trial.mp4"]
        )
        self.assertEqual(written["id"], "ramp")


class TheWholeCommandRunsWithoutANetwork(unittest.TestCase):
    def _fakes(self, tmp):
        trial = Path(tmp) / "draft" / "trial.mp4"

        def stylize(*, prompt, demo, out_path):
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"png")
            return str(out_path)

        def kling(**kwargs):
            trial.parent.mkdir(parents=True, exist_ok=True)
            trial.write_bytes(b"mp4")
            return str(trial)

        return {
            "intake": Counter(
                reply={"outcome": PASS, "checked": 6, "violations": 0, "unmeasured": 0}
            ),
            "stylize": stylize,
            "sizer": lambda _p: (720, 1280),
            "distances": fake_distances(
                near=[B.demo_path("f"), str(Path(tmp) / "draft/demo.png")], far=0.8
            ),
            "pose": lambda _p: DEMO_POSE,
            "upload": Counter(reply="https://x/1"),
            "kling": kling,
            "probe": good_probe,
            "cutter": good_cutter(150),
            "decode": lambda video, out: {"paths": [f"{out}/0.png"]},
            "cuts": lambda paths: {"outcome": PASS, "cuts": []},
        }

    def _run(self, tmp, **over):
        kwargs = self._fakes(tmp)
        kwargs.update(over)
        log = open(Path(tmp) / "log.txt", "w", encoding="utf-8")
        try:
            return B.run(
                prompt="a rain-soaked neon alley, wide lens, cold grade",
                driving=a_file(tmp, "d.mp4"),
                window=(0, 149),
                gender="f",
                aesthetic_id="ramp",
                name="Ramp",
                out_dir=Path(tmp) / "draft",
                demo_why="declared by the operator",
                log=log,
                **kwargs,
            )
        finally:
            log.close()

    def test_a_clean_run_produces_a_draft_of_seven_stages(self) -> None:
        with TemporaryDirectory() as tmp:
            got = self._run(tmp)
            files = sorted(p.name for p in (Path(tmp) / "draft").iterdir() if p.is_file())
            report = json.loads((Path(tmp) / "draft" / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(len(got["stages"]), 7)
        self.assertEqual(
            files, ["aesthetic.json", "demo.png", "driving.mp4", "report.json", "trial.mp4"]
        )
        self.assertEqual(got["element"]["card"]["shoulders"], 0.3)
        self.assertEqual(len(report["stages"]), 6, "the report holds the stages known when written")

    def test_a_refused_driving_stops_before_any_money(self) -> None:
        """Cheap before expensive, counted rather than read: nothing paid runs."""
        upload, kling = Counter(), Counter()
        stylize = Counter()
        with TemporaryDirectory() as tmp:
            got = self._run(
                tmp,
                intake=Counter(
                    reply={"outcome": FAIL, "checked": 6, "violations": 2, "unmeasured": 0}
                ),
                upload=upload,
                kling=kling,
                stylize=stylize,
            )
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(upload.calls, [])
        self.assertEqual(kling.calls, [])
        self.assertEqual(got["stages"][5]["outcome"], UNMEASURED)
        self.assertIn("NOT placed", got["stages"][5]["note"])
        self.assertEqual(got["stages"][6]["outcome"], FAIL, "a draft with no trial is not fit")

    def test_a_stylisation_that_never_happened_leaves_no_card_and_no_order(self) -> None:
        upload, kling = Counter(), Counter()
        with TemporaryDirectory() as tmp:
            got = self._run(
                tmp, stylize=Counter(boom=RuntimeError("route down")), upload=upload, kling=kling
            )
        self.assertEqual(got["stages"][3]["outcome"], UNMEASURED)
        self.assertEqual(got["stages"][4]["outcome"], UNMEASURED)
        self.assertIsNone(got["element"]["card"])
        self.assertIsNone(got["element"]["trial"])
        self.assertEqual(kling.calls, [])

    def test_the_run_says_its_numbers_on_every_line(self) -> None:
        with TemporaryDirectory() as tmp:
            self._run(tmp)
            lines = (Path(tmp) / "log.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 8, str(lines))
        for row in lines:
            self.assertIn("checked ", row)
            self.assertIn("violations ", row)
            self.assertIn("unmeasured ", row)


class TheEntryPointIsUsable(unittest.TestCase):
    def test_the_window_argument_is_parsed_and_carried(self) -> None:
        seen: dict = {}

        def fake_run(**kwargs):
            seen.update(kwargs)
            return {"outcome": PASS, "checked": 1, "violations": 0, "unmeasured": 0}

        with TemporaryDirectory() as tmp:
            prompt = a_file(tmp, "p.txt", "neon alley")
            with mock.patch.object(B, "run", fake_run):
                code = B.main(
                    [
                        "--prompt",
                        prompt,
                        "--driving",
                        "d.mp4",
                        "--window",
                        "150:299",
                        "--gender",
                        "f",
                        "--id",
                        "ramp",
                        "--name",
                        "Ramp",
                        "--out",
                        str(Path(tmp) / "draft"),
                    ]
                )
        self.assertEqual(code, 0)
        self.assertEqual(seen["window"], (150, 299))
        self.assertEqual(seen["prompt"], "neon alley")

    def test_a_failed_run_does_not_exit_zero(self) -> None:
        """Negative control on the exit code: red must reach the shell."""

        def fake_run(**kwargs):
            return {"outcome": FAIL, "checked": 1, "violations": 1, "unmeasured": 0}

        with TemporaryDirectory() as tmp:
            prompt = a_file(tmp, "p.txt", "neon alley")
            with mock.patch.object(B, "run", fake_run):
                code = B.main(
                    [
                        "--prompt",
                        prompt,
                        "--driving",
                        "d.mp4",
                        "--window",
                        "0:99",
                        "--gender",
                        "m",
                        "--id",
                        "ramp",
                        "--name",
                        "Ramp",
                        "--out",
                        str(Path(tmp) / "draft"),
                    ]
                )
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
