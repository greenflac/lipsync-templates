"""Tests for session state: partial writes, isolation between sessions, three outcomes.

Each test owns a fresh temporary database file, so the suite is
order-independent, and the network is cut off by the runner, not by a
convention that a future edit could forget.
"""

from __future__ import annotations

import socket
import tempfile
import threading
import unittest
from dataclasses import dataclass
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio import ledger, store


@dataclass(frozen=True)
class FakeStyleSpec:
    """Stands in for studio.style.StyleSpec, which agent B owns; shape is what matters."""

    palette: tuple[str, ...]
    light: str
    texture: str
    mood: str
    setting: str
    refusal: str | None


class NoNetwork(socket.socket):
    def connect(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("a test tried to open a network connection")


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "state.sqlite3"
        self._real_socket = socket.socket
        socket.socket = NoNetwork  # type: ignore[misc]
        self.addCleanup(self._restore_socket)
        self.addCleanup(self._tmp.cleanup)

    def _restore_socket(self) -> None:
        socket.socket = self._real_socket  # type: ignore[misc]

    def new_session(self, user_id: str = "ann") -> str:
        return store.create_session(user_id, db_path=self.db)


class TestCreateAndGet(StoreTestCase):
    def test_create_returns_a_uuid_and_an_empty_session(self) -> None:
        session_id = self.new_session("ann")
        self.assertEqual(len(session_id), 36, session_id)
        session = store.get(session_id, db_path=self.db)
        assert session is not None
        self.assertEqual(session["user_id"], "ann")
        self.assertEqual(session["stage"], store.STAGE_NEW)
        for field in ("template", "selfie_path", "style_spec", "last_job_id"):
            self.assertIsNone(session[field], field)

    def test_two_sessions_get_different_ids(self) -> None:
        ids = {self.new_session() for _ in range(20)}
        self.assertEqual(len(ids), 20)

    def test_unknown_session_is_none_not_an_exception(self) -> None:
        self.assertIsNone(store.get("no-such-session", db_path=self.db))


class TestPartialUpdate(StoreTestCase):
    """`update` writes only what it was handed; everything else keeps its value."""

    def test_only_named_fields_move(self) -> None:
        session_id = self.new_session()
        store.update(session_id, template="wave", selfie_path="/tmp/me.png", db_path=self.db)
        result = store.update(session_id, stage="styled", db_path=self.db)

        self.assertEqual(result["outcome"], PASS, result["note"])
        session = result["session"]
        self.assertEqual(session["stage"], "styled")
        self.assertEqual(session["template"], "wave", "an untouched field must not be cleared")
        self.assertEqual(session["selfie_path"], "/tmp/me.png")
        self.assertIsNone(session["last_job_id"])

    def test_explicit_none_does_clear_the_field(self) -> None:
        session_id = self.new_session()
        store.update(session_id, last_job_id="job-1", db_path=self.db)
        store.update(session_id, last_job_id=None, db_path=self.db)
        session = store.get(session_id, db_path=self.db)
        assert session is not None
        self.assertIsNone(session["last_job_id"])

    def test_one_session_does_not_touch_another(self) -> None:
        first = self.new_session("ann")
        second = self.new_session("bo")
        store.update(first, template="wave", db_path=self.db)
        other = store.get(second, db_path=self.db)
        assert other is not None
        self.assertIsNone(other["template"])

    def test_update_survives_a_reopen(self) -> None:
        """State is on disk, not in a process-local dict."""
        session_id = self.new_session()
        store.update(session_id, template="wave", stage="picked", db_path=self.db)
        reread = store.get(session_id, db_path=self.db)
        assert reread is not None
        self.assertEqual((reread["template"], reread["stage"]), ("wave", "picked"))


class TestStyleSpecRoundTrip(StoreTestCase):
    def test_dataclass_spec_comes_back_as_a_dict(self) -> None:
        session_id = self.new_session()
        spec = FakeStyleSpec(
            palette=("teal", "gold"),
            light="soft",
            texture="film grain",
            mood="calm",
            setting="a quiet rooftop, dusk",
            refusal=None,
        )
        result = store.update(session_id, style_spec=spec, db_path=self.db)
        self.assertEqual(result["outcome"], PASS, result["note"])
        stored = result["session"]["style_spec"]
        self.assertEqual(stored["light"], "soft")
        self.assertEqual(stored["setting"], "a quiet rooftop, dusk")
        self.assertIsNone(stored["refusal"])
        # JSON has no tuples; the round trip is honest about that.
        self.assertEqual(stored["palette"], ["teal", "gold"])

    def test_mapping_spec_round_trips(self) -> None:
        session_id = self.new_session()
        store.update(session_id, style_spec={"mood": "calm"}, db_path=self.db)
        session = store.get(session_id, db_path=self.db)
        assert session is not None
        self.assertEqual(session["style_spec"], {"mood": "calm"})

    def test_a_spec_of_the_wrong_type_is_fail_not_a_crash(self) -> None:
        session_id = self.new_session()
        result = store.update(session_id, style_spec=object(), db_path=self.db)
        self.assertEqual(result["outcome"], FAIL, result["note"])
        self.assertEqual(result["violations"], 1)
        self.assertIsNone(store.get(session_id, db_path=self.db)["style_spec"])


class TestThreeOutcomes(StoreTestCase):
    """pass / fail / could not measure, with the numbers beside the verdict."""

    def test_pass_counts_the_fields_it_wrote(self) -> None:
        session_id = self.new_session()
        result = store.update(session_id, template="wave", stage="picked", db_path=self.db)
        self.assertEqual(result["outcome"], PASS)
        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["violations"], 0)
        self.assertEqual(result["unmeasured"], 0)

    def test_unknown_field_is_fail_and_writes_nothing(self) -> None:
        session_id = self.new_session()
        result = store.update(session_id, tmeplate="wave", db_path=self.db)
        self.assertEqual(result["outcome"], FAIL, result["note"])
        self.assertEqual(result["violations"], 1)
        self.assertIn("tmeplate", result["note"])
        session = store.get(session_id, db_path=self.db)
        assert session is not None
        self.assertIsNone(session["template"], "a typo must not half-write the row")

    def test_missing_session_is_fail(self) -> None:
        result = store.update("no-such-session", stage="styled", db_path=self.db)
        self.assertEqual(result["outcome"], FAIL, result["note"])
        self.assertIsNone(result["session"])

    def test_no_fields_is_never_pass(self) -> None:
        session_id = self.new_session()
        result = store.update(session_id, db_path=self.db)
        self.assertNotEqual(result["outcome"], PASS, "zero checks is never pass")
        self.assertEqual(result["checked"], 0)

    def test_unreachable_store_is_unmeasured(self) -> None:
        unreachable = Path(self._tmp.name) / "no-such-dir" / "state.sqlite3"
        result = store.update("any", stage="styled", db_path=unreachable)
        self.assertEqual(result["outcome"], UNMEASURED, result["note"])
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["unmeasured"], 1)


class TestNegativeControl(StoreTestCase):
    """One input where update must refuse, one where it must move (harness И5)."""

    def test_it_must_refuse(self) -> None:
        session_id = self.new_session()
        verdict = store.update(session_id, balance=999, db_path=self.db)
        self.assertEqual(verdict["outcome"], FAIL, "an unknown column must be refused")

    def test_it_must_move(self) -> None:
        session_id = self.new_session()
        verdict = store.update(session_id, stage="styled", db_path=self.db)
        self.assertEqual(verdict["outcome"], PASS, verdict["note"])
        self.assertEqual(verdict["session"]["stage"], "styled")


class TestSharedFile(StoreTestCase):
    """Sessions and the credit journal live in one file and do not disturb each other."""

    def test_journal_and_sessions_coexist(self) -> None:
        session_id = self.new_session("ann")
        funded = ledger.refund("ann", 10, key="top-up", reason="top-up", db_path=self.db)
        self.assertEqual(funded["outcome"], PASS, funded["note"])
        charged = ledger.charge(
            "ann", 1, key=f"{session_id}:frame", reason="frame", db_path=self.db
        )
        self.assertEqual(charged["outcome"], PASS, charged["note"])
        store.update(session_id, stage="frame-shown", db_path=self.db)

        self.assertEqual(ledger.balance("ann", db_path=self.db), 9)
        session = store.get(session_id, db_path=self.db)
        assert session is not None
        self.assertEqual(session["stage"], "frame-shown")

    def test_concurrent_updates_all_land(self) -> None:
        session_ids = [self.new_session(f"u{index}") for index in range(8)]
        barrier = threading.Barrier(len(session_ids))
        results: dict[str, dict] = {}
        lock = threading.Lock()

        def write(session_id: str) -> None:
            barrier.wait()
            result = store.update(session_id, template=session_id[:8], db_path=self.db)
            with lock:
                results[session_id] = result

        threads = [threading.Thread(target=write, args=(sid,)) for sid in session_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        for session_id in session_ids:
            self.assertEqual(results[session_id]["outcome"], PASS, results[session_id]["note"])
            session = store.get(session_id, db_path=self.db)
            assert session is not None
            self.assertEqual(session["template"], session_id[:8])


class TestSchema(StoreTestCase):
    def test_known_fields_match_the_columns(self) -> None:
        conn = store.connect(self.db)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        finally:
            conn.close()
        self.assertTrue(
            set(store.SESSION_FIELDS) <= columns,
            f"SESSION_FIELDS names a column that does not exist: "
            f"{sorted(set(store.SESSION_FIELDS) - columns)}",
        )
        self.assertEqual(
            columns - set(store.SESSION_FIELDS),
            {"session_id", "user_id", "created_at", "updated_at"},
        )


if __name__ == "__main__":
    unittest.main()
