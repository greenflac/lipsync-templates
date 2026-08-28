"""Flow A: the anchor is the raw photo, and the medoid is banned BY CODE."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lipsync import fork_identity as fi

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "demo" / "lora_dataset"
MANIFEST = DATASET / "manifest.json"


def _weights_ready() -> bool:
    try:
        from lipsync.identity_arcface import face_detail

        return face_detail(DATASET / "img" / "real_0000.png") is not None
    except Exception:  # noqa: BLE001
        return False


class _FakeInstrument:
    """Provide a stub instrument: distances come from a table, no weights needed."""

    def __init__(self, table: dict, sizes: dict | None = None):
        self.table = table
        self.sizes = sizes or {}

    def face_detail(self, path):
        name = Path(path).name
        if name not in self.table:
            return None
        return {"embedding": (self.table[name],), "face_px": self.sizes.get(name, 200)}

    @staticmethod
    def cosine_distance(a, b):
        return round(abs(a[0] - b[0]), 4)

    @staticmethod
    def _quantile(vals, q):
        from lipsync.identity_arcface import _quantile

        return _quantile(vals, q)


def _verdict_of(text: str) -> str:
    """Return the head of a verdict line, up to the colon."""
    return text.split(":", 1)[0].strip()


def _with_instrument(inst):
    """Swap the instrument for the duration of a call. Return a restorer."""
    original = fi._instrument
    fi._instrument = lambda name: inst
    return lambda: setattr(fi, "_instrument", original)


class TheMedoidIsBannedByCodeNotByAgreement(unittest.TestCase):
    """An agreement already existed and lasted until the first convenient moment."""

    def test_an_anchor_from_the_judged_list_is_refused(self):
        frames = ["/x/a.png", "/x/b.png"]
        with self.assertRaises(fi.DerivedAnchor) as caught:
            fi.refuse_derived_anchor("/x/a.png", frames)
        self.assertIn("a.png", str(caught.exception))

    def test_an_anchor_listed_in_the_manifest_is_refused_even_if_not_judged(self):
        """Exactly the live case: the medoid is in the set, 21 generated frames are judged."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "img").mkdir()
            (root / "manifest.json").write_text(
                json.dumps(
                    {"samples": [{"path": "img/real_0000.png"}, {"path": "img/gen_0000.png"}]}
                ),
                encoding="utf-8",
            )
            with self.assertRaises(fi.DerivedAnchor) as caught:
                fi.refuse_derived_anchor(
                    root / "img" / "real_0000.png",
                    [root / "img" / "gen_0000.png"],
                    manifest=root / "manifest.json",
                )
            self.assertIn("samples", str(caught.exception))

    def test_a_manifest_that_calls_the_anchor_a_medoid_is_enough(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "samples": [{"path": "img/gen_0000.png"}],
                        "identity_reference": "outside.png — MEDOID of the generated",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaises(fi.DerivedAnchor):
                fi.refuse_derived_anchor(
                    root / "outside.png",
                    [root / "img" / "gen_0000.png"],
                    manifest=root / "manifest.json",
                )

    def test_an_honest_uploaded_photo_passes(self):
        """Run the negative control for the ban: the guard must let someone through."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(
                json.dumps({"samples": [{"path": "img/gen_0000.png"}]}), encoding="utf-8"
            )
            fi.refuse_derived_anchor(
                root / "upload.jpg",
                [root / "img" / "gen_0000.png"],
                manifest=root / "manifest.json",
            )

    def test_the_ban_reaches_axis_and_is_not_only_a_helper(self):
        """A branch no call reaches degrades silently."""
        with self.assertRaises(fi.DerivedAnchor):
            fi.axis(["/x/a.png"], raw_photo="/x/a.png")

    def test_the_reference_anchor_is_banned_too(self):
        with self.assertRaises(fi.DerivedAnchor):
            fi.axis(["/x/a.png"], raw_photo="/x/raw.png", upscaled_reference="/x/a.png")


class TheVerdictRestsOnTheRawPhotoAndNothingElse(unittest.TestCase):
    def setUp(self):
        self.table = {
            "raw.png": 0.0,
            "ref.png": 0.45,
            "alien.png": 5.0,
            "f1.png": 0.5,
            "f2.png": 0.52,
            "f3.png": 0.48,
        }
        self.restore = _with_instrument(_FakeInstrument(self.table))
        self.frames = ["/x/f1.png", "/x/f2.png", "/x/f3.png"]

    def tearDown(self):
        self.restore()

    def test_a_good_reference_does_not_rescue_a_failing_raw(self):
        got = fi.axis(self.frames, raw_photo="/x/raw.png", upscaled_reference="/x/ref.png")
        self.assertEqual(
            got["d_ref"]["outcome"],
            fi.PASS,
            "the fixture is designed so the reference is close",
        )
        self.assertEqual(
            got["verdict"],
            fi.FAIL,
            "the verdict followed the reference — the medoid defect is back",
        )

    def test_the_note_marks_the_reference_as_not_the_verdict(self):
        got = fi.axis(self.frames, raw_photo="/x/raw.png", upscaled_reference="/x/ref.png")
        self.assertIn("NOT THE VERDICT", got["note"])

    def test_a_close_raw_photo_passes(self):
        """Run the negative control: the axis can do more than fail things."""
        self.table.update({"f1.png": 0.05, "f2.png": 0.1, "f3.png": 0.2})
        got = fi.axis(self.frames, raw_photo="/x/raw.png")
        self.assertEqual(got["verdict"], fi.PASS)

    def test_the_bar_is_the_projects_own_and_not_a_local_copy(self):
        from lipsync.identity_arcface import SAME_PERSON_MAX

        self.assertEqual(fi.axis(self.frames, raw_photo="/x/raw.png")["bar"], SAME_PERSON_MAX)


class DRefAsksWhatTheUpscaleDidAndNotWhatAGeneratorDid(unittest.TestCase):
    """HANDOFF §2 and §6 A: the reference is the raw photo plus the FACE UPSCALE."""

    def tearDown(self):
        if hasattr(self, "restore"):
            self.restore()

    def _axis(self, table, **kw):
        self.restore = _with_instrument(_FakeInstrument(table))
        return fi.axis(["/x/f1.png", "/x/f2.png"], raw_photo="/x/raw.png", **kw)

    def test_the_old_argument_name_is_refused_and_not_silently_aliased(self):
        with self.assertRaises(TypeError):
            fi.axis(["/x/f1.png"], raw_photo="/x/raw.png", reference="/x/ref.png")

    def test_the_signature_names_the_upscale(self):
        import inspect

        params = inspect.signature(fi.axis).parameters
        self.assertIn("upscaled_reference", params)
        self.assertNotIn("reference", params)

    def test_an_upscale_that_left_identity_alone_passes(self):
        got = self._axis(
            {"raw.png": 0.0, "ref.png": 0.02, "f1.png": 0.30, "f2.png": 0.32},
            upscaled_reference="/x/ref.png",
        )
        self.assertEqual(_verdict_of(got["upscale"]), fi.PASS)
        self.assertIn("the upscale did not move identity", got["upscale"])

    def test_a_reference_the_upscaler_repainted_is_a_finding_not_a_success(self):
        """Frames closer to the reference are an alarm, not an improvement."""
        got = self._axis(
            {"raw.png": 0.0, "ref.png": 0.30, "f1.png": 0.30, "f2.png": 0.32},
            upscaled_reference="/x/ref.png",
        )
        self.assertEqual(_verdict_of(got["upscale"]), fi.FAIL)
        self.assertIn("repainted", got["upscale"])

    def test_an_upscaler_that_spoiled_the_face_is_caught_too(self):
        got = self._axis(
            {"raw.png": 0.0, "ref.png": 0.9, "f1.png": 0.30, "f2.png": 0.32},
            upscaled_reference="/x/ref.png",
        )
        self.assertEqual(_verdict_of(got["upscale"]), fi.FAIL)
        self.assertIn("spoiled", got["upscale"])

    def test_the_drift_bar_is_guarded_in_both_directions(self):
        """Mutate the decision constant both stricter and weaker."""
        pair = ({"median": 0.30}, {"median": 0.22})
        self.assertEqual(_verdict_of(fi.upscale_drift_verdict(*pair, drift_max=0.01)), fi.FAIL)
        self.assertEqual(
            _verdict_of(fi.upscale_drift_verdict(*pair, drift_max=0.5)),
            fi.PASS,
            "the threshold was raised above the divergence, yet the verdict did not change",
        )

    def test_a_missing_median_is_unmeasured_not_harmless(self):
        got = fi.upscale_drift_verdict({"median": 0.3}, {"median": None})
        self.assertEqual(_verdict_of(got), fi.UNMEASURED)
        self.assertIn('NOT "the upscale is harmless"', got)

    def test_a_run_without_a_reference_says_the_check_did_not_happen(self):
        got = self._axis({"raw.png": 0.0, "f1.png": 0.3, "f2.png": 0.32})
        self.assertEqual(got["upscale"], "NOT CHECKED")
        self.assertIsNone(got["d_ref"])

    def test_the_note_says_the_reference_is_the_upscaled_photo(self):
        got = self._axis(
            {"raw.png": 0.0, "ref.png": 0.02, "f1.png": 0.30, "f2.png": 0.32},
            upscaled_reference="/x/ref.png",
        )
        self.assertIn("THE FACE UPSCALE", got["note"])
        self.assertIn("WHAT THE UPSCALE DID", got["note"])

    def test_the_upscale_verdict_never_becomes_the_identity_verdict(self):
        """The upscale is perfect, identity has failed — the verdict must be FAIL."""
        got = self._axis(
            {"raw.png": 0.0, "ref.png": 0.0, "f1.png": 0.50, "f2.png": 0.52},
            upscaled_reference="/x/ref.png",
        )
        self.assertEqual(_verdict_of(got["upscale"]), fi.PASS)
        self.assertEqual(got["verdict"], fi.FAIL)


class ThereAreThreeOutcomesNotTwo(unittest.TestCase):
    """The "could not measure" outcome collapses in neither direction."""

    def tearDown(self):
        if hasattr(self, "restore"):
            self.restore()

    def test_no_faces_at_all_is_unmeasured_not_a_different_person(self):
        self.restore = _with_instrument(_FakeInstrument({"raw.png": 0.0}))
        got = fi.axis(["/x/f1.png", "/x/f2.png"], raw_photo="/x/raw.png")
        self.assertEqual(got["verdict"], fi.UNMEASURED)
        self.assertNotEqual(got["verdict"], fi.FAIL)
        self.assertIn('NOT "a different person"', got["d_raw"]["note"])

    def test_a_missing_face_on_the_anchor_is_unmeasured(self):
        self.restore = _with_instrument(_FakeInstrument({"f1.png": 0.1}))
        got = fi.axis(["/x/f1.png"], raw_photo="/x/raw.png")
        self.assertEqual(got["verdict"], fi.UNMEASURED)

    def test_thin_coverage_is_unmeasured_even_when_the_judged_ones_pass(self):
        """Zero violations with only one check having run is not a success."""
        self.restore = _with_instrument(_FakeInstrument({"raw.png": 0.0, "f1.png": 0.05}))
        got = fi.axis(["/x/f1.png", "/x/f2.png", "/x/f3.png", "/x/f4.png"], raw_photo="/x/raw.png")
        self.assertEqual(got["d_raw"]["inside"], 1)
        self.assertEqual(
            got["verdict"], fi.UNMEASURED, "coverage of 25% was passed off as a success"
        )

    def test_the_note_prints_checked_inside_and_unmeasured_as_numbers(self):
        self.restore = _with_instrument(
            _FakeInstrument({"raw.png": 0.0, "f1.png": 0.05, "f2.png": 0.9})
        )
        got = fi.axis(["/x/f1.png", "/x/f2.png"], raw_photo="/x/raw.png")
        for piece in ("median", "inside the bar", "unmeasured"):
            self.assertIn(piece, got["note"])


class TheNegativeControlIsPartOfTheMeasurement(unittest.TestCase):
    """Without an input where the instrument must say "no", the number means nothing."""

    def tearDown(self):
        self.restore()

    def _axis(self, table, **kw):
        self.restore = _with_instrument(_FakeInstrument(table))
        return fi.axis(["/x/f1.png", "/x/f2.png"], raw_photo="/x/raw.png", **kw)

    def test_a_run_without_a_control_says_so_and_does_not_claim_success(self):
        got = self._axis({"raw.png": 0.0, "f1.png": 0.05, "f2.png": 0.06})
        self.assertEqual(got["control"], "NOT RUN")
        self.assertIn("NOT RUN", got["note"])

    def test_a_control_the_instrument_mistakes_for_the_subject_voids_the_run(self):
        got = self._axis(
            {"raw.png": 0.0, "f1.png": 0.05, "f2.png": 0.06, "alien.png": 0.1},
            foreign="/x/alien.png",
        )
        self.assertEqual(_verdict_of(got["control"]), fi.FAIL)
        self.assertIn("invalid", got["control"])

    def test_a_weak_control_is_unmeasured_not_a_pass(self):
        """A 0.70 is "a different person" but not the "definitely a stranger" band."""
        got = self._axis(
            {"raw.png": 0.0, "f1.png": 0.05, "f2.png": 0.06, "alien.png": 0.5},
            foreign="/x/alien.png",
        )
        self.assertEqual(_verdict_of(got["control"]), fi.UNMEASURED)

    def test_a_proper_control_passes(self):
        got = self._axis(
            {"raw.png": 0.0, "f1.png": 0.05, "f2.png": 0.06, "alien.png": 1.0},
            foreign="/x/alien.png",
        )
        self.assertEqual(_verdict_of(got["control"]), fi.PASS)


class TheFourthNumberSeparatesTwoDifferentIllnesses(unittest.TestCase):
    """`d_drv`: "looks like the driving" and "looks like the driving ACTOR" differ."""

    def tearDown(self):
        if hasattr(self, "restore"):
            self.restore()

    def _axis(self, table, **kw):
        self.restore = _with_instrument(_FakeInstrument(table))
        return fi.axis(["/x/f1.png", "/x/f2.png"], raw_photo="/x/raw.png", **kw)

    def test_a_run_without_the_actor_says_the_check_did_not_happen(self):
        got = self._axis({"raw.png": 0.0, "f1.png": 0.05, "f2.png": 0.06})
        self.assertEqual(got["leak_to_actor"], "NOT CHECKED")
        self.assertIsNone(got["d_drv"])

    def test_frames_closer_to_the_actor_than_to_the_client_is_a_leak(self):
        got = self._axis(
            {"raw.png": 0.0, "actor.png": 0.6, "f1.png": 0.55, "f2.png": 0.56},
            driving_actor="/x/actor.png",
        )
        self.assertEqual(_verdict_of(got["leak_to_actor"]), fi.FAIL)
        self.assertIn("leaked", got["leak_to_actor"])

    def test_frames_closer_to_the_client_are_clean(self):
        """Run the negative control: the axis can also find no leak."""
        got = self._axis(
            {"raw.png": 0.0, "actor.png": 0.9, "f1.png": 0.1, "f2.png": 0.12},
            driving_actor="/x/actor.png",
        )
        self.assertEqual(_verdict_of(got["leak_to_actor"]), fi.PASS)

    def test_it_compares_two_distances_rather_than_using_a_bar(self):
        """Both are far from the bar, but the actor is closer — this must be caught."""
        got = self._axis(
            {"raw.png": 0.0, "actor.png": 0.7, "f1.png": 0.65, "f2.png": 0.66},
            driving_actor="/x/actor.png",
        )
        self.assertEqual(_verdict_of(got["leak_to_actor"]), fi.FAIL)

    def test_a_missing_distance_is_unmeasured(self):
        got = fi.actor_leak_verdict({"median": None}, {"median": 0.5})
        self.assertEqual(_verdict_of(got), fi.UNMEASURED)

    def test_the_leak_verdict_reaches_the_note(self):
        got = self._axis(
            {"raw.png": 0.0, "actor.png": 0.6, "f1.png": 0.55, "f2.png": 0.56},
            driving_actor="/x/actor.png",
        )
        self.assertIn("LEAK TO THE DRIVING ACTOR", got["note"])


class TheFaceRestorerItselfNeedsANegativeControl(unittest.TestCase):
    """Apply it to the RESTORER: the generator stands before the instrument."""

    def tearDown(self):
        if hasattr(self, "restore"):
            self.restore()

    def _control(self, table, **kw):
        self.restore = _with_instrument(_FakeInstrument(table))
        return fi.restore_negative_control(
            ["/x/fx1.png", "/x/fx2.png"], raw_photo="/x/raw.png", **kw
        )

    def test_a_run_that_never_happened_is_unmeasured_and_says_so(self):
        got = fi.restore_negative_control(raw_photo="/x/raw.png")
        self.assertEqual(got["outcome"], fi.UNMEASURED)
        self.assertIn("UNVERIFIED", got["note"])
        self.assertIn('NOT "the restorer is honest"', got["note"])

    def test_a_stranger_pulled_inside_the_bar_kills_the_measurement(self):
        """The main outcome: the restorer prints the reference — the axis after it is dead."""
        got = self._control({"raw.png": 0.0, "fx1.png": 0.20, "fx2.png": 0.22})
        self.assertEqual(got["outcome"], fi.FAIL)
        self.assertIn("PRINTS THE REFERENCE", got["note"])
        self.assertIn("INVALID", got["note"])

    def test_a_stranger_that_stayed_a_stranger_passes(self):
        """Run the negative control for the control: it must also be able to pass."""
        got = self._control({"raw.png": 0.0, "fx1.png": 0.68, "fx2.png": 0.70})
        self.assertEqual(got["outcome"], fi.PASS)
        self.assertIn("THE PULL WAS NOT MEASURED", got["note"])

    def test_an_early_stage_pull_is_caught_before_it_reaches_the_bar(self):
        got = self._control(
            {"raw.png": 0.0, "fb1.png": 0.68, "fb2.png": 0.70, "fx1.png": 0.50, "fx2.png": 0.52},
            foreign_frames_before=["/x/fb1.png", "/x/fb2.png"],
        )
        self.assertEqual(got["outcome"], fi.FAIL)
        self.assertEqual(got["pull"], 0.18)
        self.assertIn("PULLED", got["note"])

    def test_a_pull_within_instrument_noise_passes(self):
        got = self._control(
            {"raw.png": 0.0, "fb1.png": 0.68, "fb2.png": 0.70, "fx1.png": 0.67, "fx2.png": 0.69},
            foreign_frames_before=["/x/fb1.png", "/x/fb2.png"],
        )
        self.assertEqual(got["outcome"], fi.PASS)
        self.assertEqual(got["pull"], 0.01)

    def test_the_pull_bar_is_guarded_in_both_directions(self):
        """Mutate the decision constant both stricter and weaker."""
        table = {"raw.png": 0.0, "fb1.png": 0.68, "fb2.png": 0.70, "fx1.png": 0.60, "fx2.png": 0.62}
        before = ["/x/fb1.png", "/x/fb2.png"]
        self.assertEqual(
            self._control(table, foreign_frames_before=before, pull_max=0.02)["outcome"], fi.FAIL
        )
        self.restore()
        self.assertEqual(
            self._control(table, foreign_frames_before=before, pull_max=0.5)["outcome"],
            fi.PASS,
            "the threshold was raised above the pull, yet the verdict did not change",
        )

    def test_no_judgeable_stranger_frames_is_unmeasured_not_a_pass(self):
        got = self._control({"raw.png": 0.0})
        self.assertEqual(got["outcome"], fi.UNMEASURED)
        self.assertIn('NOT "the restorer is honest"', got["note"])

    def test_an_unjudgeable_before_half_is_unmeasured_not_a_pass(self):
        got = self._control(
            {"raw.png": 0.0, "fx1.png": 0.68, "fx2.png": 0.70},
            foreign_frames_before=["/x/fb1.png", "/x/fb2.png"],
        )
        self.assertEqual(got["outcome"], fi.UNMEASURED)
        self.assertIsNone(got["pull"])

    def test_the_stranger_fixture_is_one_place_for_the_whole_project(self):
        """Both the axis and the restore control take the foreign face from one place."""
        self.assertTrue(
            fi.FOREIGN_FACE_FIXTURE.exists(),
            f"{fi.FOREIGN_FACE_FIXTURE} is missing: nothing to run the negative control with",
        )
        self.assertEqual(fi.FOREIGN_FACE_FIXTURE.name, "foreign_face.png")


class TheAcceptanceSaysHowManyRowsItActuallyReproduced(unittest.TestCase):
    """Report "1 of 3" as a number, not an aggregate flag and not prose."""

    def test_exactly_one_row_of_three_is_reproduced(self):
        got = fi.acceptance_report()
        self.assertEqual((got["reproduced"], got["of"]), (1, 3))

    def test_the_unclosed_acceptance_is_not_reported_as_a_pass(self):
        got = fi.acceptance_report()
        self.assertEqual(got["outcome"], fi.UNMEASURED)
        self.assertNotEqual(got["outcome"], fi.PASS)
        self.assertIn("NOT CLOSED", got["note"])

    def test_the_two_gaps_are_named_and_not_merged_into_one_excuse(self):
        got = fi.acceptance_report()
        self.assertEqual(sorted(got["unmeasured"]), ["against the raw photo", "negative control"])
        self.assertEqual(got["failed"], [])

    def test_each_gap_carries_its_number_and_its_reason(self):
        rows = fi.ACCEPTANCE_ROWS
        self.assertIsNone(
            rows["against the raw photo"]["reproduced"],
            "the row is declared reproduced — the raw photo is not in the tree, "
            "nothing to measure against",
        )
        self.assertEqual(rows["against the raw photo"]["target"]["median"], 0.5067)
        self.assertEqual(rows["negative control"]["reproduced"]["median"], 0.6809)
        self.assertEqual(rows["negative control"]["target"]["band"], (0.96, 1.05))
        for name, row in rows.items():
            self.assertIn(row["outcome"], (fi.PASS, fi.FAIL, fi.UNMEASURED), name)
            self.assertGreater(len(row["why"]), 40, name)

    def test_the_reproduced_row_is_the_instrument_not_the_product(self):
        """The medoid row reproduces, but it says nothing about the product."""
        row = fi.ACCEPTANCE_ROWS["against the medoid"]
        self.assertEqual(row["outcome"], fi.PASS)
        self.assertIn("generated against generated", row["why"])

    def test_the_report_would_redden_if_someone_declared_it_done(self):
        """Mutate the other way: "everything reproduced" must be caught."""
        row = fi.ACCEPTANCE_ROWS["against the raw photo"]
        original = row["outcome"]
        row["outcome"] = fi.PASS
        try:
            self.assertEqual(
                fi.acceptance_report()["outcome"],
                fi.UNMEASURED,
                "two rows are declared closed, and the report is still not PASS "
                "— the guard is not guarding",
            )
            row["reproduced"] = row["target"]
            fi.ACCEPTANCE_ROWS["negative control"]["outcome"] = fi.PASS
            self.assertEqual(fi.acceptance_report()["outcome"], fi.PASS)
            self.assertEqual(fi.acceptance_report()["reproduced"], 3)
            self.assertNotIn("NOT CLOSED", fi.acceptance_report()["note"])
        finally:
            row["outcome"] = original
            row["reproduced"] = None
            fi.ACCEPTANCE_ROWS["negative control"]["outcome"] = fi.UNMEASURED


class TheInstrumentIsAParameterAndItsLicenceIsSpoken(unittest.TestCase):
    def test_an_unknown_instrument_is_refused_rather_than_stubbed(self):
        with self.assertRaises(ValueError) as caught:
            fi._instrument("auraface")
        self.assertIn("voids", str(caught.exception))

    def test_the_non_commercial_licence_reaches_the_report_without_blocking(self):
        restore = _with_instrument(_FakeInstrument({"raw.png": 0.0, "f1.png": 0.05}))
        try:
            got = fi.axis(["/x/f1.png"], raw_photo="/x/raw.png")
        finally:
            restore()
        self.assertIn("non-commercial", got["note"].lower())
        self.assertIn("recalibration of all thresholds", got["note"].lower())
        self.assertIn(
            "does not block work",
            got["note"],
            "the licence is presented as a blocker — HANDOFF §10 says it does "
            "not block during development; it is a shipping question",
        )


class TheSizeFilterChangesTheNumberAndSaysSo(unittest.TestCase):
    """Both numbers are correct, and they are different numbers. The mode must stand next to them."""

    def tearDown(self):
        self.restore()

    def test_filtering_drops_frames_and_the_note_names_the_mode(self):
        table = {"raw.png": 0.0, "f1.png": 0.05, "f2.png": 0.06}
        self.restore = _with_instrument(_FakeInstrument(table, sizes={"f1.png": 200, "f2.png": 40}))
        off = fi.distances(["/x/f1.png", "/x/f2.png"], "/x/raw.png")
        on = fi.distances(["/x/f1.png", "/x/f2.png"], "/x/raw.png", min_face_px=100)
        self.assertEqual((off["judged"], on["judged"]), (2, 1))
        self.assertIn("off", off["note"])
        self.assertIn("100px", on["note"])

    def test_a_dropped_frame_is_counted_as_unmeasured_not_as_drift(self):
        table = {"raw.png": 0.0, "f1.png": 0.05, "f2.png": 0.06}
        self.restore = _with_instrument(_FakeInstrument(table, sizes={"f1.png": 200, "f2.png": 40}))
        on = fi.distances(["/x/f1.png", "/x/f2.png"], "/x/raw.png", min_face_px=100)
        self.assertEqual(on["too_small"], ["f2.png"])
        self.assertEqual(on["inside"], 1)


@unittest.skipUnless(
    MANIFEST.exists() and _weights_ready(),
    "no buffalo_l weights or demo/lora_dataset — nothing to reproduce the numbers with",
)
class TheMeasuredRowsAreReproduced(unittest.TestCase):
    """Accept the flow: reproduce what is reproducible and only that."""

    @classmethod
    def setUpClass(cls):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.generated = [DATASET / s["path"] for s in data["samples"] if s["origin"] == "generated"]
        cls.medoid = DATASET / "img" / "real_0000.png"

    def test_there_are_twenty_one_generated_frames(self):
        self.assertEqual(len(self.generated), 21)

    def test_the_medoid_row_reproduces_to_the_fourth_decimal(self):
        got = fi.distances(self.generated, self.medoid)
        self.assertEqual(got["median"], 0.2579)
        self.assertEqual((got["inside"], got["judged"]), (19, 21))

    def test_the_recorded_medoid_row_equals_what_the_run_gives(self):
        """Check the record in `ACCEPTANCE_ROWS` against the run, not against memory."""
        got = fi.distances(self.generated, self.medoid)
        row = fi.ACCEPTANCE_ROWS["against the medoid"]["reproduced"]
        self.assertEqual(
            (row["median"], row["inside"], row["judged"]),
            (got["median"], got["inside"], got["judged"]),
        )

    def test_the_medoid_anchor_is_refused_by_the_ban_when_asked_for_a_verdict(self):
        """The same measurement through `axis` must FAIL rather than report success."""
        with self.assertRaises(fi.DerivedAnchor):
            fi.axis(self.generated, raw_photo=self.medoid, manifest=MANIFEST)

    def test_the_raw_photo_is_genuinely_absent_and_this_test_will_notice(self):
        text = MANIFEST.read_text(encoding="utf-8")
        self.assertIn(
            "MEDOID of the generated",
            text,
            "the manifest stopped calling the anchor a medoid — check whether "
            "a real raw photo appeared, and if so add a d_raw row to the "
            "flow A acceptance",
        )

    def test_no_sample_claims_to_be_the_uploaded_photo(self):
        """A second guard for the same hole, from the other side — by set composition."""
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(data["by_origin"]),
            ["augmented", "generated", "real"],
            "a new origin appeared in the set — if it is the uploaded "
            "photo, the d_raw acceptance is finally measurable: "
            "lift UNMEASURED from ACCEPTANCE_ROWS",
        )
        self.assertEqual(data["by_origin"]["real"], 1)
        self.assertEqual(
            [s["path"] for s in data["samples"] if s["origin"] == "real"],
            ["img/real_0000.png"],
            'the only "real" frame is that very medoid, and it is banned as the anchor',
        )

    def test_the_unmeasurable_row_is_recorded_as_unmeasured_not_as_success(self):
        got = fi.acceptance_report()
        row = got["rows"]["against the raw photo"]
        self.assertEqual(row["outcome"], fi.UNMEASURED)
        self.assertIsNone(row["reproduced"])
        self.assertIn("against the raw photo", got["unmeasured"])

    ALIEN = fi.FOREIGN_FACE_FIXTURE

    def test_the_control_fixture_is_present_and_absence_is_a_failure(self):
        """A skip is not a pass. The frame lives in the repository, and if it is missing,"""
        self.assertTrue(
            self.ALIEN.exists(),
            f"{self.ALIEN} is missing: the negative control was not run, and that "
            f'is NOT "the control passed"',
        )

    def test_the_negative_control_says_different_person(self):
        got = fi.distances(self.generated, self.ALIEN)
        self.assertEqual(
            got["inside"],
            0,
            "a stranger was taken for the subject — the run's numbers are invalid",
        )
        self.assertGreater(got["median"], fi.HARD_DRIFT_MAX)

    def test_the_control_does_not_reach_the_band_it_was_recorded_at(self):
        """Record a negative result as a NUMBER rather than smoothing it over."""
        got = fi.distances(self.generated, self.ALIEN)
        self.assertEqual(
            got["median"],
            0.6809,
            "the control number changed — what is recorded in "
            "ACCEPTANCE_ROWS is no longer what the run gives",
        )
        self.assertLess(
            got["median"],
            0.96,
            "the control reached the recorded band — update the research "
            "repository's measurement log and drop this caveat",
        )

    def test_the_recorded_control_row_equals_what_the_run_gives(self):
        got = fi.distances(self.generated, self.ALIEN)
        row = fi.ACCEPTANCE_ROWS["negative control"]["reproduced"]
        self.assertEqual(
            (row["median"], row["min"], row["max"], row["inside"], row["judged"]),
            (got["median"], got["min"], got["max"], got["inside"], got["judged"]),
        )
        lo, hi = fi.ACCEPTANCE_ROWS["negative control"]["target"]["band"]
        self.assertFalse(
            lo <= got["median"] <= hi,
            "the control is inside the target band — the acceptance row can be "
            "closed; lift UNMEASURED",
        )

    def test_two_different_statements_about_the_control_stay_separate(self):
        """ "The control fired" and "the acceptance row is closed" are DIFFERENT."""
        d = fi.distances(self.generated, self.ALIEN)
        self.assertEqual(_verdict_of(fi.control_verdict(d)), fi.PASS)
        self.assertEqual(
            fi.ACCEPTANCE_ROWS["negative control"]["outcome"],
            fi.UNMEASURED,
            "a passing control was passed off as the reproduced 0.96–1.05 band",
        )


if __name__ == "__main__":
    unittest.main()
