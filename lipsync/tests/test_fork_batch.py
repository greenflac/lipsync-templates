"""Run the batch entirely on a stub stand: no network, not a single cent."""

from __future__ import annotations

import socket
import unittest
from pathlib import Path
from string import ascii_lowercase
from tempfile import TemporaryDirectory
from unittest import mock

from lipsync import fork_batch as B
from lipsync import fork_e2e as E
from lipsync.fork_identity import FAIL, PASS, UNMEASURED


class _Blocked(RuntimeError):
    """The network in this file's tests is forbidden by the runner, not by agreement."""


def _no_network():
    def deny(*a, **k):
        raise _Blocked("network is forbidden in tests: inject a function instead of going outside")

    return mock.patch.object(socket, "socket", deny)


_NOREPLY = object()


def _owner_axes(matrix=None):
    """Build the three axes at the sizes the owner's matrix names.

    Takes `fork_batch.OWNER_MATRIX` rather than repeating its numbers: the
    fixtures below ARE the owner's matrix, and a matrix that moved in the
    module while the fixtures stayed would leave these tests measuring a
    matrix nobody ordered.
    """
    drivings, styles, persons = B.OWNER_MATRIX if matrix is None else matrix
    return (
        [f"work/dr_{i}.mp4" for i in range(1, drivings + 1)],
        [f"work/st_{i}.png" for i in range(1, styles + 1)],
        [f"work/person_{c}.png" for c in ascii_lowercase[:persons]],
    )


DRIVINGS, STYLES, PERSONS = _owner_axes()


class _Runner:
    """Stub `fork_e2e.run`: count the calls and write a 'clip' to disk."""

    def __init__(self, verdicts=None, *, write=True, reply=_NOREPLY):
        self.verdicts = dict(verdicts or {})
        self.calls = []
        self.write = write
        self.reply = reply

    def __call__(self, *, client_photo, style_ref, driving, first, last, out_dir, log=None, **kw):
        self.calls.append(
            {
                "person": client_photo,
                "style": style_ref,
                "driving": driving,
                "window": (first, last),
                "out_dir": out_dir,
            }
        )
        v = self.verdicts.get(len(self.calls), PASS)
        if isinstance(v, Exception):
            raise v
        if self.reply is not _NOREPLY:
            return self.reply
        if v == PASS and self.write:
            p = Path(out_dir) / "final_9x16.mp4"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\x00" * 128)
        return {
            "outcome": v,
            "stopped_at": "all stages" if v == PASS else "6 output acceptance",
            "totals": {
                "checked": 21,
                "violations": 0 if v == PASS else 1,
                "unmeasured": 0 if v != UNMEASURED else 1,
            },
            "exit_code": 0,
        }


def _balance(*values):
    """Stub balance probe: hand out the values in order, then the last one."""
    box = list(values)

    def get():
        return box.pop(0) if len(box) > 1 else box[0]

    return get


class _Log:
    """A log that can be read right in the middle of a run."""

    def __init__(self):
        self.text = ""

    def write(self, s):
        self.text += s

    def flush(self):
        pass


def _batch(tmp, **kw):
    kw.setdefault("drivings", DRIVINGS)
    kw.setdefault("styles", STYLES)
    kw.setdefault("persons", PERSONS)
    kw.setdefault("first", 0)
    kw.setdefault("last", 89)
    kw.setdefault("out_dir", tmp)
    kw.setdefault("log", _Log())
    return B.run_batch(**kw)


class TheFixturesAreTheOwnersMatrixAndNotACopyOfIt(unittest.TestCase):
    """`OWNER_MATRIX` must reach the fixtures, or naming it changes nothing."""

    def test_the_axes_come_out_at_the_sizes_the_owner_ordered(self):
        self.assertEqual([len(DRIVINGS), len(STYLES), len(PERSONS)], [5, 5, 2])

    def test_moving_the_owner_matrix_moves_the_axes_and_the_cell_count(self):
        """Negative control for the wiring: a different matrix must give different numbers."""
        with mock.patch.object(B, "OWNER_MATRIX", (2, 3, 4)):
            drivings, styles, persons = _owner_axes()
        self.assertEqual([len(drivings), len(styles), len(persons)], [2, 3, 4])
        self.assertEqual(len(B.cells(drivings, styles, persons, mode="full")), 24)
        self.assertEqual(len(B.cells(drivings, styles, persons, mode="cover")), 4)


class TheCoverageModesGiveTheNumbersTheyPromise(unittest.TestCase):
    def test_full_on_the_owner_matrix_is_fifty_cells(self):
        self.assertEqual(len(B.cells(DRIVINGS, STYLES, PERSONS, mode="full")), 50)

    def test_cover_on_the_owner_matrix_is_five_cells(self):
        self.assertEqual(len(B.cells(DRIVINGS, STYLES, PERSONS, mode="cover")), 5)

    def test_cover_touches_every_value_of_every_axis_at_least_once(self):
        """Otherwise `cover` sells a subset as coverage."""
        st3, pe2 = STYLES[:3], PERSONS
        got = B.cells(DRIVINGS, st3, pe2, mode="cover")
        self.assertEqual(len(got), 5)
        self.assertEqual(sorted({c["driving"] for c in got}), sorted(DRIVINGS))
        self.assertEqual(sorted({c["style"] for c in got}), sorted(st3))
        self.assertEqual(sorted({c["person"] for c in got}), sorted(pe2))

    def test_full_touches_every_value_too_and_every_combination_once(self):
        got = B.cells(DRIVINGS, STYLES, PERSONS, mode="full")
        self.assertEqual(len({(c["driving"], c["style"], c["person"]) for c in got}), 50)

    def test_an_unknown_mode_is_a_refusal_and_not_a_guess(self):
        with self.assertRaises(ValueError) as e:
            B.cells(DRIVINGS, STYLES, PERSONS, mode="almost_full")
        self.assertIn("almost_full", str(e.exception))

    def test_an_empty_axis_is_a_refusal(self):
        """Run the matrix negative control: an empty axis leaves nothing to order."""
        with self.assertRaises(ValueError) as e:
            B.cells(DRIVINGS, [], PERSONS, mode="cover")
        self.assertIn("styles", str(e.exception))

    def test_the_clip_name_says_what_is_on_the_video(self):
        self.assertEqual(
            B.cell_name("work/dr_1.mp4", "a/st_blue.png", "b/person_a.jpg"),
            "dr_1__st_blue__person_a",
        )


class TheMoneyGuardHasThreeOutcomes(unittest.TestCase):
    def test_fifty_cells_cost_seventeen_fifty(self):
        self.assertEqual(B.plan_cost(50), 17.5)

    def test_five_cells_cost_one_seventy_five(self):
        self.assertEqual(B.plan_cost(5), 1.75)

    def test_the_matrix_we_actually_ship_does_fit_ten_dollars(self):
        self.assertEqual(B.plan_cost(20), 7.0)
        self.assertEqual(B.afford(20, 10.1490375)["outcome"], PASS)

    def test_an_empty_wallet_against_the_full_cross_names_the_shortfall(self):
        got = B.afford(50, 0.0)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(got["short"], 17.5)

    def test_the_real_balance_of_the_shift_against_the_full_cross(self):
        """$0.8490 is the account balance at the time the module was written."""
        got = B.afford(50, 0.8490)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(got["short"], 16.651)

    def test_enough_money_is_a_pass_the_guard_can_move(self):
        """Run the instrument's negative control: it can also say yes."""
        got = B.afford(5, 2.0)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["need"], 1.75)

    def test_exactly_enough_is_a_pass_and_not_a_rounding_refusal(self):
        got = B.afford(4, 1.4)
        self.assertEqual(got["outcome"], PASS)

    def test_one_cent_short_is_a_refusal(self):
        got = B.afford(4, 1.39)
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(got["short"], 0.01)

    def test_an_unknown_balance_is_unmeasured_and_not_a_refusal(self):
        for value in (None, "not a number"):
            with self.subTest(value=value):
                self.assertEqual(B.afford(5, value)["outcome"], UNMEASURED)

    def test_the_price_is_imported_and_not_copied(self):
        """Check the price lives in the stand and mutate it both ways."""
        with mock.patch.object(E, "KLING_PRICE_USD", 0.42):
            self.assertEqual(B.plan_cost(5), 2.1)
            self.assertEqual(B.afford(5, 2.0)["outcome"], FAIL)
        with mock.patch.object(E, "KLING_PRICE_USD", 0.05):
            self.assertEqual(B.plan_cost(5), 0.25)
            self.assertEqual(B.afford(5, 2.0)["outcome"], PASS)


class TheBatchDoesNotStartWithoutMoney(unittest.TestCase):
    def test_the_full_cross_on_an_empty_wallet_orders_nothing_at_all(self):
        run = _Runner()
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="full", balance=_balance(0.0), cell_runner=run)
        self.assertEqual(run.calls, [], "an order went out on an empty account")
        self.assertEqual(got["attempted"], 0)
        self.assertEqual(got["planned"], 50)
        self.assertEqual(got["exit_code"], 1)
        self.assertEqual(got["money"]["short"], 17.5)
        self.assertEqual(got["spent_expected"], 0.0)

    def test_an_unknown_balance_stops_the_batch_with_code_two(self):
        """Neither 'probably enough' nor 'assume empty': the third outcome."""
        run = _Runner()
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="cover", balance=_balance(None), cell_runner=run)
        self.assertEqual(run.calls, [])
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertEqual(got["exit_code"], 2)

    def test_the_default_balance_probe_reads_the_operator_number(self):
        with mock.patch.dict("os.environ", {B.BALANCE_ENV: "0.8490"}):
            self.assertEqual(B.live_balance(), 0.849)
        with mock.patch.dict("os.environ", {B.BALANCE_ENV: "garbage"}):
            self.assertIsNone(B.live_balance())
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(B.live_balance())

    def test_a_pro_endpoint_is_refused_before_the_balance_is_even_asked(self):
        """The `pro` guard stands before the money: $0.8960 versus $0.0700 per second."""
        run = _Runner()
        asked = []
        with _no_network(), TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                _batch(
                    td,
                    mode="cover",
                    cell_runner=run,
                    balance=lambda: asked.append(1) or 100.0,
                    endpoint="fal-ai/kling-video/v2.6/pro/motion-control",
                )
        self.assertEqual(run.calls, [])
        self.assertEqual(asked, [])


class TheBatchRunsCellsOneByOne(unittest.TestCase):
    def test_cover_with_enough_money_passes_and_leaves_five_named_clips(self):
        run = _Runner()
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="cover", balance=_balance(2.0, 0.95), cell_runner=run)
            names = sorted(p.name for p in (Path(td) / "clips").glob("*.mp4"))
        self.assertEqual(got["exit_code"], 0)
        self.assertEqual((got["passed"], got["failed"], got["unmeasured"]), (5, 0, 0))
        self.assertEqual(len(run.calls), 5)
        self.assertEqual(
            names,
            [
                "dr_1__st_1__person_a.mp4",
                "dr_2__st_2__person_b.mp4",
                "dr_3__st_3__person_a.mp4",
                "dr_4__st_4__person_b.mp4",
                "dr_5__st_5__person_a.mp4",
            ],
        )

    def test_the_cell_gets_its_three_inputs_and_its_own_directory(self):
        run = _Runner()
        with _no_network(), TemporaryDirectory() as td:
            _batch(td, mode="cover", balance=_balance(2.0), cell_runner=run)
        first = run.calls[0]
        self.assertEqual(
            (first["driving"], first["style"], first["person"]),
            ("work/dr_1.mp4", "work/st_1.png", "work/person_a.png"),
        )
        self.assertEqual(first["window"], (0, 89))
        self.assertNotEqual(first["out_dir"], run.calls[1]["out_dir"])

    def test_a_per_driving_window_overrides_the_default(self):
        run = _Runner()
        with _no_network(), TemporaryDirectory() as td:
            _batch(
                td,
                mode="cover",
                balance=_balance(2.0),
                cell_runner=run,
                windows={"work/dr_2.mp4": (100, 199)},
            )
        self.assertEqual(run.calls[0]["window"], (0, 89))
        self.assertEqual(run.calls[1]["window"], (100, 199))

    def test_a_failing_third_cell_does_not_stop_the_batch(self):
        run = _Runner({3: FAIL})
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="cover", balance=_balance(2.0, 0.95), cell_runner=run)
        self.assertEqual(len(run.calls), 5, "the batch stalled on one bad pair")
        self.assertEqual((got["passed"], got["failed"], got["unmeasured"]), (4, 1, 0))
        self.assertFalse(got["stopped_early"])
        self.assertEqual(got["exit_code"], 1)

    def test_each_cell_is_printed_before_the_next_one_starts(self):
        """A silent run has already carried away everything measured."""
        log = _Log()
        seen = []

        def runner(*, out_dir, **kw):
            seen.append(log.text.count("] cell"))
            p = Path(out_dir) / "final_9x16.mp4"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\x00" * 16)
            return {
                "outcome": PASS,
                "stopped_at": "all stages",
                "totals": {"checked": 21, "violations": 0, "unmeasured": 0},
            }

        with _no_network(), TemporaryDirectory() as td:
            _batch(td, mode="cover", balance=_balance(2.0), cell_runner=runner, log=log)
        self.assertEqual(seen, [0, 1, 2, 3, 4])
        self.assertIn("money before start", log.text.split("] cell")[0])


class ThereAreThreeOutcomesPerCellAndNotTwo(unittest.TestCase):
    def test_a_crashed_cell_is_unmeasured_and_not_a_product_defect(self):
        run = _Runner({2: _Blocked("the fal queue went down")})
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="cover", balance=_balance(2.0, 0.95), cell_runner=run)
        bad = got["cells"][1]
        self.assertEqual(bad["outcome"], UNMEASURED)
        self.assertIn("the fal queue went down", bad["note"])
        self.assertEqual((got["passed"], got["failed"], got["unmeasured"]), (4, 0, 1))
        self.assertEqual(got["exit_code"], 2)

    def test_a_reply_without_a_verdict_is_unmeasured_and_not_a_pass(self):
        for reply in (None, "done", {"outcome": "kinda fine"}):
            with self.subTest(reply=reply):
                run = _Runner(reply=reply)
                with _no_network(), TemporaryDirectory() as td:
                    got = _batch(td, mode="cover", balance=_balance(2.0), cell_runner=run)
                self.assertEqual(got["unmeasured"], 5)
                self.assertEqual(got["passed"], 0)

    def test_a_pass_without_a_clip_on_disk_is_downgraded_to_unmeasured(self):
        """Trust the evidence, not the flag. No clip means nothing to watch."""
        run = _Runner(write=False)
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="cover", balance=_balance(2.0), cell_runner=run)
        self.assertEqual(got["passed"], 0)
        self.assertEqual(got["unmeasured"], 5)
        self.assertEqual(got["clips"], [])
        self.assertIn("clip is missing", got["cells"][0]["note"])

    def test_an_empty_clip_file_is_not_a_clip(self):
        """Run the collector's negative control: a zero-byte file must be a refusal."""
        with TemporaryDirectory() as td:
            src = Path(td) / "final_9x16.mp4"
            src.write_bytes(b"")
            path, why = B.copy_clip(src, Path(td) / "out.mp4")
            self.assertIsNone(path)
            self.assertIn("empty", why)

    def test_the_collector_can_also_say_yes(self):
        with TemporaryDirectory() as td:
            src = Path(td) / "final_9x16.mp4"
            src.write_bytes(b"\x00" * 8)
            path, why = B.copy_clip(src, Path(td) / "clips" / "a__b__c.mp4")
            self.assertIsNone(why)
            self.assertTrue(Path(path).is_file())


class AStreakOfFailuresStopsTheBatch(unittest.TestCase):
    def test_three_failures_in_a_row_stop_it_and_the_rest_are_unmeasured(self):
        run = _Runner({2: FAIL, 3: FAIL, 4: FAIL})
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="cover", balance=_balance(2.0, 1.16), cell_runner=run)
        self.assertEqual(len(run.calls), 4, "the batch kept burning money past the streak")
        self.assertTrue(got["stopped_early"])
        self.assertEqual((got["passed"], got["failed"], got["unmeasured"]), (1, 3, 1))
        self.assertEqual(got["cells"][4]["outcome"], UNMEASURED)
        self.assertIn("not launched", got["cells"][4]["note"])

    def test_two_failures_in_a_row_do_not_stop_it(self):
        """Run the guard's negative control: it can also stay silent."""
        run = _Runner({2: FAIL, 3: FAIL})
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="cover", balance=_balance(2.0), cell_runner=run)
        self.assertEqual(len(run.calls), 5)
        self.assertFalse(got["stopped_early"])

    def test_failures_split_by_a_pass_do_not_add_up(self):
        """A streak means in a row. A pass between failures resets the counter."""
        run = _Runner({1: FAIL, 2: FAIL, 3: PASS, 4: FAIL, 5: FAIL})
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="cover", balance=_balance(2.0), cell_runner=run)
        self.assertEqual(len(run.calls), 5)
        self.assertFalse(got["stopped_early"])

    def test_unmeasured_cells_count_into_the_streak_too(self):
        """Money burns the same however the cell ends."""
        run = _Runner({1: _Blocked("network"), 2: _Blocked("network"), 3: _Blocked("network")})
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="cover", balance=_balance(2.0), cell_runner=run)
        self.assertEqual(len(run.calls), 3)
        self.assertTrue(got["stopped_early"])

    def test_the_streak_constant_is_guarded_in_both_directions(self):
        """Swap the constant stricter and looser, observably both times."""
        self.assertEqual(B.MAX_STREAK, 3)
        for value, expect_calls, expect_stop in ((2, 3, True), (5, 5, False)):
            with self.subTest(MAX_STREAK=value):
                run = _Runner({2: FAIL, 3: FAIL, 4: FAIL})
                with (
                    mock.patch.object(B, "MAX_STREAK", value),
                    _no_network(),
                    TemporaryDirectory() as td,
                ):
                    got = B.run_batch(
                        drivings=DRIVINGS,
                        styles=STYLES,
                        persons=PERSONS,
                        mode="cover",
                        first=0,
                        last=89,
                        out_dir=td,
                        balance=_balance(2.0),
                        cell_runner=run,
                        max_streak=B.MAX_STREAK,
                        log=_Log(),
                    )
                self.assertEqual(len(run.calls), expect_calls)
                self.assertIs(got["stopped_early"], expect_stop)


class TheReportCarriesNumbersNextToTheVerdict(unittest.TestCase):
    def test_the_money_actually_spent_comes_from_the_balance_before_and_after(self):
        run = _Runner()
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="cover", balance=_balance(2.0, 0.95), cell_runner=run)
        self.assertEqual(got["balance_before"], 2.0)
        self.assertEqual(got["balance_after"], 0.95)
        self.assertEqual(got["spent_actual"], 1.05)
        self.assertEqual(got["spent_expected"], 1.75)

    def test_an_unknown_balance_after_leaves_the_spend_unmeasured_not_zero(self):
        run = _Runner()
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="cover", balance=_balance(2.0, None), cell_runner=run)
        self.assertIsNone(got["spent_actual"])
        self.assertEqual(got["spent_expected"], 1.75)

    def test_a_stopped_batch_expects_only_what_it_actually_launched(self):
        run = _Runner({2: FAIL, 3: FAIL, 4: FAIL})
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(td, mode="cover", balance=_balance(2.0, 1.16), cell_runner=run)
        self.assertEqual(got["attempted"], 4)
        self.assertEqual(got["spent_expected"], 1.4)

    def test_the_log_prints_the_three_counts_next_to_the_verdict(self):
        log = _Log()
        run = _Runner({3: FAIL})
        with _no_network(), TemporaryDirectory() as td:
            _batch(td, mode="cover", balance=_balance(2.0, 0.95), cell_runner=run, log=log)
        self.assertIn("pass 4, fail 1, unmeasured 0", log.text)
        self.assertIn("actually spent $1.05", log.text)

    def test_the_exit_code_is_zero_one_two_by_the_worst_cell(self):
        cases = ((None, 0), ({3: FAIL}, 1), ({3: _Blocked("network")}, 2))
        for verdicts, code in cases:
            with self.subTest(verdicts=verdicts):
                with _no_network(), TemporaryDirectory() as td:
                    got = _batch(
                        td, mode="cover", balance=_balance(2.0), cell_runner=_Runner(verdicts)
                    )
                self.assertEqual(got["exit_code"], code)

    def test_a_failure_outranks_an_unmeasured_in_the_verdict(self):
        """A found violation does not stop being one because something else went unmeasured."""
        with _no_network(), TemporaryDirectory() as td:
            got = _batch(
                td,
                mode="cover",
                balance=_balance(2.0),
                cell_runner=_Runner({2: FAIL, 4: _Blocked("network")}),
            )
        self.assertEqual(got["outcome"], FAIL)
        self.assertEqual(got["exit_code"], 1)


class TheEntryPointIsThin(unittest.TestCase):
    def test_main_parses_the_matrix_and_returns_the_exit_code(self):
        seen = {}

        def fake_batch(**kw):
            seen.update(kw)
            return {"exit_code": 0}

        with mock.patch.object(B, "run_batch", fake_batch):
            code = B.main(
                [
                    "--driving",
                    "a.mp4",
                    "--driving",
                    "b.mp4",
                    "--style",
                    "s.png",
                    "--person",
                    "p.png",
                    "--mode",
                    "cover",
                    "--window",
                    "100:199",
                    "--out",
                    "work/x",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(seen["drivings"], ["a.mp4", "b.mp4"])
        self.assertEqual(seen["mode"], "cover")
        self.assertEqual((seen["first"], seen["last"]), (100, 199))


if __name__ == "__main__":
    unittest.main()
