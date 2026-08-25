"""Tests for the credit journal. Real money moves here, so idempotency is the centre.

Every test owns a fresh temporary database file, so no test can see another
test's rows and the suite is order-independent. Nothing here touches the
network: sqlite3 is a local file and the module imports nothing that dials out.
"""

from __future__ import annotations

import socket
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio import ledger

# CHOSEN by the test author, mirroring the contract's VIDEO_CREDITS scale.
START_CREDITS = 10
FRAME_COST = 1
VIDEO_COST = 10


class NoNetwork(socket.socket):
    """A socket that refuses to connect, installed by the runner, not by convention."""

    def connect(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("a test tried to open a network connection")


class LedgerTestCase(unittest.TestCase):
    """Base case: a private database file per test, and the network cut off."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "journal.sqlite3"
        self._real_socket = socket.socket
        socket.socket = NoNetwork  # type: ignore[misc]
        self.addCleanup(self._restore_socket)
        self.addCleanup(self._tmp.cleanup)

    def _restore_socket(self) -> None:
        socket.socket = self._real_socket  # type: ignore[misc]

    def fund(self, user_id: str, credits: int = START_CREDITS) -> None:
        """Put starting credits into the journal the only way credits ever appear."""
        result = ledger.refund(
            user_id, credits, key=f"top-up:{user_id}", reason="top-up", db_path=self.db
        )
        self.assertEqual(result["outcome"], PASS, result["note"])

    def rows(self, user_id: str) -> list[dict]:
        return ledger.entries(user_id, db_path=self.db)


class TestIdempotency(LedgerTestCase):
    """The central property: one key, one row, one deduction — however often it is called."""

    def test_same_key_charges_once(self) -> None:
        self.fund("ann")
        first = ledger.charge("ann", VIDEO_COST, key="job-7", reason="video", db_path=self.db)
        second = ledger.charge("ann", VIDEO_COST, key="job-7", reason="video", db_path=self.db)

        self.assertEqual(first["outcome"], PASS, first["note"])
        self.assertEqual(second["outcome"], PASS, second["note"])

        charges = [row for row in self.rows("ann") if row["idempotency_key"] == "job-7"]
        self.assertEqual(len(charges), 1, f"the key wrote {len(charges)} rows, expected 1")
        self.assertEqual(charges[0]["delta"], -VIDEO_COST)

        # The balance moved exactly one charge's worth, not two.
        self.assertEqual(ledger.balance("ann", db_path=self.db), 0)
        self.assertEqual(first["balance"], 0)
        self.assertEqual(second["balance"], 0)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])

        # The replay above is the fast path; underneath it the database itself
        # must refuse a second row, or two racing writers would both insert.
        conn = ledger.connect(self.db)
        try:
            with self.assertRaises(
                sqlite3.IntegrityError, msg="idempotency_key is not UNIQUE in the schema"
            ):
                conn.execute(
                    "INSERT INTO ledger_entries "
                    "(user_id, delta, reason, idempotency_key, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("ann", -VIDEO_COST, "video", "job-7", "2026-08-25T00:00:00+00:00"),
                )
        finally:
            conn.close()

    def test_replay_returns_the_same_delta(self) -> None:
        self.fund("bo")
        first = ledger.charge("bo", FRAME_COST, key="frame-1", reason="frame", db_path=self.db)
        third = ledger.charge("bo", FRAME_COST, key="frame-1", reason="frame", db_path=self.db)
        fourth = ledger.charge("bo", FRAME_COST, key="frame-1", reason="frame", db_path=self.db)
        self.assertEqual(first["delta"], -FRAME_COST)
        self.assertEqual(third["delta"], -FRAME_COST)
        self.assertEqual(fourth["delta"], -FRAME_COST)
        self.assertEqual(len(self.rows("bo")), 2, "top-up plus one charge")

    def test_same_key_across_users_is_refused(self) -> None:
        self.fund("ann")
        self.fund("bo")
        ledger.charge("ann", FRAME_COST, key="shared", reason="frame", db_path=self.db)
        stolen = ledger.charge("bo", FRAME_COST, key="shared", reason="frame", db_path=self.db)
        self.assertEqual(stolen["outcome"], FAIL, stolen["note"])
        self.assertEqual(ledger.balance("bo", db_path=self.db), START_CREDITS)


class TestCompensation(LedgerTestCase):
    """A refund is a new row, never an erased one."""

    def test_refund_restores_balance_and_leaves_two_rows(self) -> None:
        self.fund("cai")
        before = ledger.balance("cai", db_path=self.db)

        charged = ledger.charge("cai", VIDEO_COST, key="job-9", reason="video", db_path=self.db)
        self.assertEqual(charged["outcome"], PASS, charged["note"])
        self.assertEqual(ledger.balance("cai", db_path=self.db), before - VIDEO_COST)

        refunded = ledger.refund(
            "cai", VIDEO_COST, key="job-9:refund", reason="engine failed", db_path=self.db
        )
        self.assertEqual(refunded["outcome"], PASS, refunded["note"])
        self.assertEqual(ledger.balance("cai", db_path=self.db), before)

        movement = [row for row in self.rows("cai") if row["reason"] != "top-up"]
        self.assertEqual(len(movement), 2, "the charge and its compensation must both stay")
        self.assertEqual([row["delta"] for row in movement], [-VIDEO_COST, VIDEO_COST])

    def test_refund_is_idempotent_too(self) -> None:
        self.fund("cai")
        ledger.charge("cai", VIDEO_COST, key="job-9", reason="video", db_path=self.db)
        ledger.refund("cai", VIDEO_COST, key="job-9:refund", reason="failed", db_path=self.db)
        ledger.refund("cai", VIDEO_COST, key="job-9:refund", reason="failed", db_path=self.db)
        self.assertEqual(ledger.balance("cai", db_path=self.db), START_CREDITS)
        self.assertEqual(len(self.rows("cai")), 3, "top-up, charge, one compensation")


class TestThreeOutcomes(LedgerTestCase):
    """pass / fail / could not measure, each with its numbers beside the verdict."""

    def test_pass_carries_numbers(self) -> None:
        self.fund("dee")
        result = ledger.charge("dee", FRAME_COST, key="ok", reason="frame", db_path=self.db)
        self.assertEqual(result["outcome"], PASS)
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["violations"], 0)
        self.assertEqual(result["unmeasured"], 0)
        self.assertEqual(result["balance"], START_CREDITS - FRAME_COST)

    def test_insufficient_funds_is_fail_with_numbers_not_an_exception(self) -> None:
        self.fund("dee", 3)
        result = ledger.charge("dee", VIDEO_COST, key="too-big", reason="video", db_path=self.db)
        self.assertEqual(result["outcome"], FAIL)
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["violations"], 1)
        self.assertEqual(result["unmeasured"], 0)
        self.assertEqual(result["balance"], 3)
        self.assertEqual(result["delta"], 0, "a refused charge moves nothing")
        self.assertIn("3", result["note"])
        self.assertIn("10", result["note"])
        # A refused charge writes no row and burns no key.
        self.assertEqual(len(self.rows("dee")), 1, "only the top-up")
        self.assertEqual(ledger.balance("dee", db_path=self.db), 3)

    def test_unreachable_journal_is_unmeasured_not_fail(self) -> None:
        unreachable = Path(self._tmp.name) / "no-such-dir" / "journal.sqlite3"
        result = ledger.charge("dee", FRAME_COST, key="k", reason="frame", db_path=unreachable)
        self.assertEqual(result["outcome"], UNMEASURED, result["note"])
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["unmeasured"], 1)

    def test_zero_checks_is_never_pass(self) -> None:
        for result in (
            ledger.charge("dee", 0, key="k0", reason="frame", db_path=self.db),
            ledger.charge("dee", -5, key="k-", reason="frame", db_path=self.db),
            ledger.refund("dee", 0, key="r0", reason="frame", db_path=self.db),
            ledger.charge("dee", FRAME_COST, key="", reason="frame", db_path=self.db),
        ):
            self.assertNotEqual(result["outcome"], PASS, result["note"])


class TestNegativeControl(LedgerTestCase):
    """The instrument must say no on one input and move on the other (harness И5)."""

    def test_it_must_say_no(self) -> None:
        self.fund("eve", 1)
        verdict = ledger.charge("eve", 2, key="over", reason="video", db_path=self.db)
        self.assertEqual(verdict["outcome"], FAIL, "a charge over the balance must be refused")
        self.assertEqual(ledger.balance("eve", db_path=self.db), 1)

    def test_it_must_move(self) -> None:
        self.fund("eve", 1)
        verdict = ledger.charge("eve", 1, key="exact", reason="frame", db_path=self.db)
        self.assertEqual(verdict["outcome"], PASS, "spending the exact balance must succeed")
        self.assertEqual(ledger.balance("eve", db_path=self.db), 0)


class TestConcurrentWrites(LedgerTestCase):
    """Two different keys are two rows; neither is lost."""

    def test_distinct_keys_both_land(self) -> None:
        self.fund("fin")
        first = ledger.charge("fin", FRAME_COST, key="a", reason="frame", db_path=self.db)
        second = ledger.charge("fin", FRAME_COST, key="b", reason="frame", db_path=self.db)
        self.assertEqual(first["outcome"], PASS, first["note"])
        self.assertEqual(second["outcome"], PASS, second["note"])
        charges = [row for row in self.rows("fin") if row["reason"] == "frame"]
        self.assertEqual(len(charges), 2)
        self.assertEqual(sorted(row["idempotency_key"] for row in charges), ["a", "b"])
        self.assertEqual(ledger.balance("fin", db_path=self.db), START_CREDITS - 2 * FRAME_COST)

    def test_threads_with_distinct_keys_lose_nothing(self) -> None:
        """Eight writers race on one file; every distinct key must end up as a row."""
        self.fund("fin", 8)
        keys = [f"k{index}" for index in range(8)]
        results: dict[str, dict] = {}
        barrier = threading.Barrier(len(keys))

        def spend(key: str) -> None:
            barrier.wait()  # start together, so the writes actually overlap
            results[key] = ledger.charge(
                "fin", FRAME_COST, key=key, reason="frame", db_path=self.db
            )

        threads = [threading.Thread(target=spend, args=(key,)) for key in keys]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        passed = [key for key, result in results.items() if result["outcome"] == PASS]
        self.assertEqual(sorted(passed), sorted(keys), [r["note"] for r in results.values()])
        self.assertEqual(ledger.balance("fin", db_path=self.db), 0)
        self.assertEqual(len(self.rows("fin")), len(keys) + 1)

    def test_threads_with_one_key_charge_once(self) -> None:
        """The same key raced by eight writers still deducts exactly one charge."""
        self.fund("fin")
        barrier = threading.Barrier(8)
        results: list[dict] = []
        lock = threading.Lock()

        def spend() -> None:
            barrier.wait()
            result = ledger.charge(
                "fin", VIDEO_COST, key="one-key", reason="video", db_path=self.db
            )
            with lock:
                results.append(result)

        threads = [threading.Thread(target=spend) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        written = [row for row in self.rows("fin") if row["idempotency_key"] == "one-key"]
        self.assertEqual(len(written), 1, f"{len(written)} rows written under one key")
        self.assertEqual(ledger.balance("fin", db_path=self.db), 0)
        self.assertTrue(all(r["outcome"] == PASS for r in results), [r["note"] for r in results])


class TestJournalShape(LedgerTestCase):
    """The append-only guarantees the balance rests on."""

    def test_balance_is_the_sum_of_rows_and_nothing_else(self) -> None:
        self.fund("gus")
        ledger.charge("gus", 4, key="c1", reason="video", db_path=self.db)
        ledger.refund("gus", 2, key="r1", reason="partial", db_path=self.db)
        rows = self.rows("gus")
        self.assertEqual(ledger.balance("gus", db_path=self.db), sum(row["delta"] for row in rows))

    def test_no_balance_column_exists(self) -> None:
        conn = ledger.connect(self.db)
        try:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(ledger_entries)").fetchall()
            }
        finally:
            conn.close()
        self.assertNotIn("balance", columns, "the balance is the sum of rows, never a column")
        self.assertEqual(
            columns,
            {"id", "user_id", "delta", "reason", "idempotency_key", "created_at"},
        )

    def test_balance_of_an_unknown_user_is_zero(self) -> None:
        self.assertEqual(ledger.balance("nobody", db_path=self.db), 0)


if __name__ == "__main__":
    unittest.main()
