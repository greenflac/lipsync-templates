"""Gates for the publish step. The write is irreversible, so the refusals are what is tested hardest.

No test writes into the repository's own assets: every publish here goes into a
temporary tree, and one test stands guard over that.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from lipsync import fork_aesthetic as A
from lipsync import fork_aesthetic_publish as P
from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from lipsync.frame import FRAME

#: The size the demo frame must be, written as a literal (T2) so the test does
#: not travel with the constant it is guarding.
DELIVERY_FRAME = (720, 1280)

EMPTY_BASE = {"_": "a base for the tests", "aesthetics": [{"id": "taken", "demo": "f"}]}

MANIFEST = {
    "id": "ramp",
    "name": "Ramp",
    "kind": "transform",
    "prompt": "a ramp at dusk",
    "demo": "f",
    "demo_why": "the wardrobe is neutral",
    "window": [150, 299],
    "card": {
        "shoulders": 0.53,
        "ankles": 0.92,
        "centre": 0.53,
        "width": 0.31,
        "tolerances": {"shoulders": 0.05, "ankles": 0.05, "centre": 0.1837, "width": 0.1326},
    },
}


def sizer_of(size):
    """Return a sizer that reports one size, so no test needs a real picture or PIL."""

    def sizer(_path):
        return size

    return sizer


GOOD_SIZER = sizer_of(DELIVERY_FRAME)


def real_png(size) -> bytes:
    """Return a real PNG of that size, for the tests that must exercise the default sizer."""
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def snapshot(root) -> dict:
    """Return every file under the tree with its bytes, so 'nothing was written' can be proved."""
    root = Path(root)
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


class Tree:
    """A temporary repository plus a draft in it, built fresh for each test."""

    def __init__(self, stack, *, manifest=None, files=None, base=None):
        self.root = Path(stack.enter_context(TemporaryDirectory()))
        base_path = self.root / "assets" / "fork_aesthetics.json"
        base_path.parent.mkdir(parents=True)
        base_path.write_text(
            json.dumps(EMPTY_BASE if base is None else base, ensure_ascii=False), encoding="utf-8"
        )
        self.base_path = base_path
        self.draft = self.root / "draft"
        self.draft.mkdir()
        got = MANIFEST if manifest is None else manifest
        (self.draft / P.DRAFT_MANIFEST).write_text(
            json.dumps(got, ensure_ascii=False), encoding="utf-8"
        )
        for name, body in (files or {}).items():
            (self.draft / name).write_bytes(body)

    def base(self) -> dict:
        return json.loads(self.base_path.read_text(encoding="utf-8"))


WHOLE_DRAFT = {P.DRAFT_DEMO: b"png bytes", P.DRAFT_DRIVING: b"mp4 bytes", P.DRAFT_TRIAL: b"trial"}


class TheDraftIsCarriedIntoTheBase(unittest.TestCase):
    """The one path where publishing is allowed to write."""

    def setUp(self):
        import contextlib

        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.tree = Tree(self.stack, files=WHOLE_DRAFT)

    def test_a_whole_draft_publishes_and_says_what_it_wrote(self):
        got = P.publish(self.tree.draft, root=self.tree.root, sizer=GOOD_SIZER)
        self.assertEqual(got["outcome"], PASS, got["note"])
        self.assertEqual(got["violations"], 0)
        self.assertEqual(got["unmeasured"], 0)
        self.assertEqual(len(got["written"]), 4)
        self.assertIn("published 'ramp'", got["note"])

    def test_the_three_files_land_where_the_contract_says(self):
        P.publish(self.tree.draft, root=self.tree.root, sizer=GOOD_SIZER)
        for rel, body in (
            ("assets/aesthetics/ramp_f.png", b"png bytes"),
            ("assets/drivings/ramp_f.mp4", b"mp4 bytes"),
            ("docs/trials/ramp_f.mp4", b"trial"),
        ):
            with self.subTest(rel=rel):
                self.assertEqual((self.tree.root / rel).read_bytes(), body)

    def test_the_element_appended_is_READY_FOR_AN_ORDER(self):
        """Publishing an aesthetic no order could use is the thing this whole gate is for."""
        P.publish(self.tree.draft, root=self.tree.root, sizer=GOOD_SIZER)
        published = self.tree.base()["aesthetics"][-1]
        self.assertEqual(published["id"], "ramp")
        self.assertEqual(A.order_ready(published)["outcome"], PASS)
        self.assertEqual(A.driving_of(published), Path("assets/drivings/ramp_f.mp4"))
        self.assertEqual(A.window_of(published), (150, 299))
        self.assertEqual(A.card_of(published)["tolerances"]["centre"], 0.1837)
        self.assertEqual(A.trial_of(published), Path("docs/trials/ramp_f.mp4"))
        self.assertEqual(A.gender_of(published), "f")

    def test_the_stored_paths_point_at_the_files_that_were_really_copied(self):
        """E2: the path is derived from where the file went, not from what the draft claimed."""
        P.publish(self.tree.draft, root=self.tree.root, sizer=GOOD_SIZER)
        published = self.tree.base()["aesthetics"][-1]
        for path in (A.driving_of(published), A.trial_of(published)):
            with self.subTest(path=path):
                self.assertTrue((self.tree.root / path).is_file())

    def test_the_aesthetics_already_in_the_base_are_left_alone(self):
        P.publish(self.tree.draft, root=self.tree.root, sizer=GOOD_SIZER)
        got = self.tree.base()
        self.assertEqual([a["id"] for a in got["aesthetics"]], ["taken", "ramp"])
        self.assertEqual(got["_"], EMPTY_BASE["_"])

    def test_publishing_the_same_draft_twice_is_refused_the_second_time(self):
        first = P.publish(self.tree.draft, root=self.tree.root, sizer=GOOD_SIZER)
        self.assertEqual(first["outcome"], PASS)
        after = snapshot(self.tree.root)
        second = P.publish(self.tree.draft, root=self.tree.root, sizer=GOOD_SIZER)
        self.assertEqual(second["outcome"], FAIL)
        self.assertEqual(snapshot(self.tree.root), after)


class ARefusalLeavesTheTreeExactlyAsItWas(unittest.TestCase):
    """The write is irreversible, so a refusal must not write a single byte."""

    def setUp(self):
        import contextlib

        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)

    def refusal(self, *, manifest=None, files=None, base=None, sizer=GOOD_SIZER, want=FAIL):
        """Publish a draft that must be refused, and prove the tree did not move."""
        tree = Tree(self.stack, manifest=manifest, files=files, base=base)
        before = snapshot(tree.root)
        got = P.publish(tree.draft, root=tree.root, sizer=sizer)
        self.assertEqual(got["outcome"], want, got["note"])
        self.assertEqual(got["written"], [])
        self.assertIn("NOTHING WAS WRITTEN", got["note"])
        self.assertEqual(
            snapshot(tree.root),
            before,
            "the refused publish still changed the tree, and publishing is irreversible",
        )
        return got

    def test_an_id_already_in_the_base_is_refused(self):
        got = self.refusal(manifest={**MANIFEST, "id": "taken"}, files=WHOLE_DRAFT)
        self.assertIn("already in the base", got["problems"][0])

    def test_a_draft_WITHOUT_THE_TRIAL_CLIP_is_refused(self):
        """Decision 5: without the paid trial the aesthetic is not fit, so it is not published."""
        got = self.refusal(files={k: v for k, v in WHOLE_DRAFT.items() if k != P.DRAFT_TRIAL})
        self.assertIn(P.DRAFT_TRIAL, got["problems"][0])
        self.assertIn("decision 5", got["problems"][0])

    def test_an_EMPTY_trial_clip_is_no_trial_at_all(self):
        self.refusal(files={**WHOLE_DRAFT, P.DRAFT_TRIAL: b""})

    def test_a_draft_without_the_driving_or_the_demo_is_refused(self):
        for absent in (P.DRAFT_DRIVING, P.DRAFT_DEMO):
            with self.subTest(absent=absent):
                got = self.refusal(files={k: v for k, v in WHOLE_DRAFT.items() if k != absent})
                self.assertIn(absent, got["problems"][0])

    def test_a_demo_frame_that_is_not_the_product_frame_is_refused(self):
        # 1080x1920 and 720x1281 were here until 2026-09-01 and both sit ON the
        # plan ratio: they encoded pixel equality, which is not the product's
        # standard — every shipped aesthetic is 1530x2720. What must be refused
        # is a frame off the RATIO.
        for wrong in ((1280, 720), (512, 512), (900, 1200), (720, 1600)):
            with self.subTest(wrong=wrong):
                got = self.refusal(files=WHOLE_DRAFT, sizer=sizer_of(wrong))
                self.assertIn(f"{wrong[0]}x{wrong[1]}", got["problems"][0])
                self.assertIn("720x1280", got["problems"][0])

    def test_the_frame_it_demands_is_the_PROJECTS_and_not_a_second_copy(self):
        self.assertEqual(FRAME, DELIVERY_FRAME)

    def test_a_manifest_WITHOUT_A_CARD_is_refused(self):
        got = self.refusal(
            manifest={k: v for k, v in MANIFEST.items() if k != "card"}, files=WHOLE_DRAFT
        )
        self.assertIn("card", got["problems"][0])

    def test_a_manifest_without_a_window_is_refused(self):
        got = self.refusal(
            manifest={k: v for k, v in MANIFEST.items() if k != "window"}, files=WHOLE_DRAFT
        )
        self.assertIn("window", got["problems"][0])

    def test_a_BROKEN_card_or_window_is_refused_even_though_the_field_is_there(self):
        for field, value in (("window", [300, 299]), ("card", {"tolerances": {}})):
            with self.subTest(field=field):
                got = self.refusal(manifest={**MANIFEST, field: value}, files=WHOLE_DRAFT)
                self.assertIn("not be ready for an order", " ".join(got["problems"]))

    def test_an_unknown_gender_is_refused(self):
        for bad in ("x", "", "female", None):
            with self.subTest(bad=bad):
                self.refusal(manifest={**MANIFEST, "demo": bad}, files=WHOLE_DRAFT)

    def test_an_id_that_would_write_outside_the_asset_directories_is_refused(self):
        for bad in ("../escape", "a/b", "Ramp", "ramp.f", "", "-ramp", "ra mp"):
            with self.subTest(bad=bad):
                got = self.refusal(manifest={**MANIFEST, "id": bad}, files=WHOLE_DRAFT)
                self.assertTrue(
                    any("not a name this may write" in p for p in got["problems"]), got["problems"]
                )

    def test_a_destination_file_that_already_exists_is_never_overwritten(self):
        tree = Tree(self.stack, files=WHOLE_DRAFT)
        squatter = tree.root / "assets" / "drivings" / "ramp_f.mp4"
        squatter.parent.mkdir(parents=True)
        squatter.write_bytes(b"someone else's driving")
        before = snapshot(tree.root)
        got = P.publish(tree.draft, root=tree.root, sizer=GOOD_SIZER)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(snapshot(tree.root), before)
        self.assertEqual(squatter.read_bytes(), b"someone else's driving")


class ADraftThatCannotBeREADIsTheThirdOutcome(unittest.TestCase):
    """Not fit and not readable are different facts, and neither is a pass."""

    def setUp(self):
        import contextlib

        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)

    def test_a_draft_directory_that_is_not_there_is_UNMEASURED(self):
        tree = Tree(self.stack, files=WHOLE_DRAFT)
        got = P.publish(tree.root / "no-such-draft", root=tree.root, sizer=GOOD_SIZER)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertEqual(got["checked"], 0)
        self.assertEqual(got["violations"], 0)
        self.assertIn("NOT permission to publish", got["note"])

    def test_a_draft_without_a_manifest_is_UNMEASURED_and_says_what_it_found(self):
        tree = Tree(self.stack, files=WHOLE_DRAFT)
        (tree.draft / P.DRAFT_MANIFEST).unlink()
        got = P.publish(tree.draft, root=tree.root, sizer=GOOD_SIZER)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn(P.DRAFT_DEMO, got["note"])

    def test_a_manifest_that_is_not_json_is_UNMEASURED_not_FAIL(self):
        tree = Tree(self.stack, files=WHOLE_DRAFT)
        (tree.draft / P.DRAFT_MANIFEST).write_text("{not json", encoding="utf-8")
        got = P.publish(tree.draft, root=tree.root, sizer=GOOD_SIZER)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertEqual(got["checked"], 0)

    def test_a_demo_frame_whose_size_CANNOT_BE_TAKEN_is_not_a_pass(self):
        """R1: could not measure is not folded into either of the other two."""

        def broken(_path):
            raise OSError("the picture could not be opened")

        tree = Tree(self.stack, files=WHOLE_DRAFT)
        before = snapshot(tree.root)
        got = P.publish(tree.draft, root=tree.root, sizer=broken)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertEqual(got["violations"], 0)
        self.assertEqual(got["unmeasured"], 1)
        self.assertGreater(got["checked"], 0)
        self.assertEqual(got["written"], [])
        self.assertEqual(snapshot(tree.root), before)

    def test_zero_checks_is_never_a_pass(self):
        tree = Tree(self.stack, files=WHOLE_DRAFT)
        got = P.inspect(tree.root / "nope", root=tree.root, sizer=GOOD_SIZER)
        self.assertEqual(got["checked"], 0)
        self.assertNotEqual(got["outcome"], PASS)


class AFallenPublishPutsBackWhatItTookAway(unittest.TestCase):
    """All the checks pass and the copying still falls over: the tree must not be left half-moved."""

    def setUp(self):
        import contextlib

        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)

    def test_a_failure_while_appending_to_the_base_removes_the_copied_files(self):
        tree = Tree(self.stack, files=WHOLE_DRAFT)
        before = snapshot(tree.root)
        was = P._append_to_base
        try:
            P._append_to_base = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
            got = P.publish(tree.draft, root=tree.root, sizer=GOOD_SIZER)
        finally:
            P._append_to_base = was
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertEqual(got["written"], [])
        self.assertIn("ROLLED BACK", got["note"])
        self.assertEqual(snapshot(tree.root), before)

    def test_a_failure_while_copying_removes_the_files_already_copied(self):
        """The third copy falls after two have really landed, so there IS something to roll back."""
        tree = Tree(self.stack, files=WHOLE_DRAFT)
        before = snapshot(tree.root)
        # The real function is captured BEFORE the patch and called directly:
        # reaching for it through the patched name again makes `falls` call
        # itself, and the test then passes without a byte ever being copied.
        real_copy2 = P.shutil.copy2
        calls = []

        def falls(src, dst):
            calls.append(dst)
            if len(calls) == 3:
                raise OSError("disk full")
            return real_copy2(src, dst)

        with mock.patch.object(P.shutil, "copy2", falls):
            got = P.publish(tree.draft, root=tree.root, sizer=GOOD_SIZER)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertEqual(len(calls), 3)
        self.assertIn("ROLLED BACK", got["note"])
        self.assertEqual(snapshot(tree.root), before)

    def test_that_rollback_test_really_had_two_files_to_remove(self):
        """S8/S1: the control above is worthless if the copies never happened."""
        tree = Tree(self.stack, files=WHOLE_DRAFT)
        real_copy2 = P.shutil.copy2
        landed = []

        def falls(src, dst):
            if len(landed) == 2:
                raise OSError("disk full")
            real_copy2(src, dst)
            landed.append(Path(dst))

        with mock.patch.object(P.shutil, "copy2", falls):
            P.publish(tree.draft, root=tree.root, sizer=GOOD_SIZER)
        self.assertEqual(len(landed), 2)
        for path in landed:
            with self.subTest(path=path):
                self.assertFalse(path.exists(), "the rollback left a copied file behind")

    def test_the_base_is_never_left_half_written(self):
        tree = Tree(self.stack, files=WHOLE_DRAFT)
        P.publish(tree.draft, root=tree.root, sizer=GOOD_SIZER)
        self.assertEqual(list(tree.base_path.parent.glob("*.publishing")), [])
        json.loads(tree.base_path.read_text(encoding="utf-8"))


class TheCommandLineSaysTheOutcomeInItsExitCode(unittest.TestCase):
    """T5: the outcome is decided in a function, and main only prints it and returns the code."""

    def setUp(self):
        import contextlib

        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)

    def test_a_refusal_exits_1_and_an_unreadable_draft_exits_2(self):
        tree = Tree(self.stack, manifest={**MANIFEST, "id": "taken"}, files=WHOLE_DRAFT)
        self.assertEqual(P.main([str(tree.draft), "--root", str(tree.root)]), 1)
        self.assertEqual(P.main([str(tree.root / "nope"), "--root", str(tree.root)]), 2)

    def test_a_dry_run_checks_everything_and_writes_NOTHING(self):
        """A real picture, so the default sizer is exercised once instead of always injected."""
        tree = Tree(self.stack, files={**WHOLE_DRAFT, P.DRAFT_DEMO: real_png(DELIVERY_FRAME)})
        before = snapshot(tree.root)
        self.assertEqual(P.main([str(tree.draft), "--root", str(tree.root), "--dry-run"]), 0)
        self.assertEqual(snapshot(tree.root), before)

    def test_a_publish_from_the_command_line_exits_0_and_writes(self):
        tree = Tree(self.stack, files={**WHOLE_DRAFT, P.DRAFT_DEMO: real_png(DELIVERY_FRAME)})
        self.assertEqual(P.main([str(tree.draft), "--root", str(tree.root)]), 0)
        self.assertEqual([a["id"] for a in tree.base()["aesthetics"]], ["taken", "ramp"])

    def test_the_default_sizer_really_REFUSES_a_picture_of_the_wrong_size(self):
        """The injected sizer could agree with a defect the real one would catch."""
        tree = Tree(self.stack, files={**WHOLE_DRAFT, P.DRAFT_DEMO: real_png((1280, 720))})
        before = snapshot(tree.root)
        self.assertEqual(P.main([str(tree.draft), "--root", str(tree.root)]), 1)
        self.assertEqual(snapshot(tree.root), before)


class TheTestsNeverTouchTheShippedAssets(unittest.TestCase):
    """A publish test that wrote into the repository would be found by the next agent, not by us."""

    def test_the_shipped_base_still_holds_exactly_the_six(self):
        self.assertEqual(len(A.ids()), 6)
        self.assertNotIn("ramp", A.ids())

    def test_no_aesthetic_or_driving_was_left_behind_by_a_test(self):
        for rel in ("assets/aesthetics/ramp_f.png", "assets/drivings/ramp_f.mp4"):
            with self.subTest(rel=rel):
                self.assertFalse((P.REPO_ROOT / rel).exists())

    def test_the_default_root_is_the_repository_the_base_lives_in(self):
        self.assertEqual(P.base_path_under(None), A.BASE_PATH)
        self.assertEqual(
            P.base_path_under("/somewhere"), Path("/somewhere/assets/fork_aesthetics.json")
        )


class TheElementIsPROVEDReadableBeforeItIsWritten(unittest.TestCase):
    """The stored path and the copied file are built by different code, and they can drift apart."""

    def setUp(self):
        import contextlib

        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)

    def test_a_reader_that_would_be_sent_to_another_path_is_refused(self):
        """The comparison bites on the READER: the element is built from the destinations.

        Probing it by moving the destinations proves nothing — the stored path
        is derived from them and follows along. What it really couples is the
        accessor a reader calls to the file this module copies, so the control
        is an accessor that disagrees.
        """
        for name, reader in (("driving", "driving_of"), ("trial", "trial_of")):
            with self.subTest(name=name):
                tree = Tree(self.stack, files=WHOLE_DRAFT)
                before = snapshot(tree.root)
                with mock.patch.object(A, reader, return_value=Path("assets/OTHER.mp4")):
                    got = P.publish(tree.draft, root=tree.root, sizer=GOOD_SIZER)
                self.assertEqual(got["outcome"], FAIL)
                self.assertIn("is not where the file is copied to", " ".join(got["problems"]))
                self.assertEqual(got["written"], [])
                self.assertEqual(snapshot(tree.root), before)

    def test_the_readback_really_goes_through_the_public_accessors(self):
        """If it did not, an element only this module can read would still publish."""
        tree = Tree(self.stack, files=WHOLE_DRAFT)
        with mock.patch.object(A, "card_of", side_effect=ValueError("unreadable card")) as spy:
            got = P.publish(tree.draft, root=tree.root, sizer=GOOD_SIZER)
        self.assertTrue(spy.called)
        self.assertEqual(got["outcome"], FAIL)
        self.assertIn("unreadable card", " ".join(got["problems"]))
        self.assertEqual(got["written"], [])

    def test_a_window_that_does_not_read_back_the_same_is_refused(self):
        tree = Tree(self.stack, files=WHOLE_DRAFT)
        with mock.patch.object(A, "window_of", return_value=(1, 2)):
            got = P.publish(tree.draft, root=tree.root, sizer=GOOD_SIZER)
        self.assertEqual(got["outcome"], FAIL)
        self.assertIn("reads back as 1:2", " ".join(got["problems"]))

    def test_the_readback_check_counts_as_a_check_and_is_not_free(self):
        tree = Tree(self.stack, files=WHOLE_DRAFT)
        got = P.inspect(tree.draft, root=tree.root, sizer=GOOD_SIZER)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["checked"], 9)


class TheFrameGateAgreesWithTheProductItGuards(unittest.TestCase):
    """MEASURED 2026-09-01: publish refused a demo frame the whole pipeline accepts.

    Every aesthetic already shipped in `assets/aesthetics` is 1530x2720, and the
    product frame is 720x1280. A gate that demands pixel equality would refuse all
    six of them, so pixel equality is not the product's standard — the plan ratio
    is, and that is what the order path measures with its own tolerance.
    """

    def _draft_with_frame(self, tmp, size):
        from PIL import Image

        draft = Path(tmp) / "draft"
        draft.mkdir(parents=True)
        Image.new("RGB", size, "white").save(draft / "demo.png")
        (draft / "driving.mp4").write_bytes(b"driving")
        (draft / "trial.mp4").write_bytes(b"trial")
        (draft / "aesthetic.json").write_text(
            json.dumps(
                {
                    "id": "probe",
                    "name": "Probe",
                    "kind": "transform",
                    "prompt": "a prompt",
                    "demo": "f",
                    "demo_why": "why",
                    "driving": "assets/drivings/probe_f.mp4",
                    "window": [0, 149],
                    "card": {
                        "shoulders": 0.3,
                        "ankles": 0.9,
                        "centre": 0.5,
                        "width": 0.4,
                        "tolerances": {
                            "shoulders": 0.05,
                            "ankles": 0.05,
                            "centre": 0.05,
                            "width": 0.05,
                        },
                    },
                    "trial": "docs/trials/probe_f.mp4",
                }
            ),
            encoding="utf-8",
        )
        return draft

    def _root(self, tmp):
        root = Path(tmp) / "root"
        (root / "assets").mkdir(parents=True)
        (root / "assets" / "fork_aesthetics.json").write_text(
            json.dumps(
                {
                    "aesthetics": [
                        {
                            "id": "other",
                            "name": "Other",
                            "kind": "scene",
                            "prompt": "p",
                            "demo": "m",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return root

    def test_a_frame_on_the_plan_ratio_is_admitted_at_the_shipped_size(self):
        with TemporaryDirectory() as tmp:
            draft = self._draft_with_frame(tmp, (1530, 2720))
            got = P.publish(draft, root=self._root(tmp))
        self.assertNotEqual(
            got["outcome"],
            "fail",
            f"1530x2720 is the size of every aesthetic already shipped: {got.get('note')}",
        )

    def test_a_frame_off_the_plan_ratio_is_still_refused(self):
        with TemporaryDirectory() as tmp:
            draft = self._draft_with_frame(tmp, (1280, 720))
            got = P.publish(draft, root=self._root(tmp))
        self.assertEqual(got["outcome"], "fail", "a landscape frame must not publish")
