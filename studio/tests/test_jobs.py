"""Tests for the background job runner. No network: the socket is disarmed below."""

from __future__ import annotations

import socket
import threading
import unittest

from studio import jobs

_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_CREATE_CONNECTION = socket.create_connection


def setUpModule() -> None:
    """Disarm outbound connections: the runner enforces "no network", not a convention.

    Creating a socket is left alone because the event loop the test client
    starts needs a local socketpair; reaching *out* is what must be impossible.
    """

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a test tried to reach the network")

    socket.socket.connect = refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = refuse  # type: ignore[method-assign]
    socket.create_connection = refuse  # type: ignore[assignment]


def tearDownModule() -> None:
    socket.socket.connect = _REAL_CONNECT  # type: ignore[method-assign]
    socket.socket.connect_ex = _REAL_CONNECT_EX  # type: ignore[method-assign]
    socket.create_connection = _REAL_CREATE_CONNECTION  # type: ignore[assignment]


class JobStates(unittest.TestCase):
    def setUp(self) -> None:
        jobs.reset()

    def test_successful_runner_ends_done_and_passes(self) -> None:
        job_id = jobs.submit("s1", "frame", runner=lambda **kw: {"image": "frame.png"})
        state = jobs.wait(job_id)
        self.assertEqual(state["state"], "done")
        self.assertEqual(state["outcome"], "pass")
        self.assertEqual(state["result"], {"image": "frame.png"})

    def test_raising_runner_ends_failed(self) -> None:
        def boom(**_kw: object) -> dict:
            raise RuntimeError("the model returned garbage")

        state = jobs.wait(jobs.submit("s1", "video", runner=boom))
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["outcome"], "fail")
        self.assertIn("garbage", state["note"])

    def test_silent_provider_ends_unknown_not_failed_and_not_done(self) -> None:
        # The third outcome: no answer means the money may already be gone.
        def silent(**_kw: object) -> dict:
            raise jobs.ProviderSilent("read timeout after 120 s")

        state = jobs.wait(jobs.submit("s1", "video", runner=silent))
        self.assertEqual(state["state"], "unknown")
        self.assertNotEqual(state["state"], "failed")
        self.assertNotEqual(state["state"], "done")
        self.assertEqual(state["outcome"], "could not measure")

    def test_runner_reporting_unmeasured_also_ends_unknown(self) -> None:
        state = jobs.wait(
            jobs.submit(
                "s1",
                "video",
                runner=lambda **kw: {"outcome": "could not measure", "note": "no reply parsed"},
            )
        )
        self.assertEqual(state["state"], "unknown")
        self.assertEqual(state["outcome"], "could not measure")

    def test_runner_reporting_fail_ends_failed(self) -> None:
        state = jobs.wait(
            jobs.submit("s1", "frame", runner=lambda **kw: {"outcome": "fail", "note": "rejected"})
        )
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["outcome"], "fail")

    def test_request_id_is_stored_before_the_call_and_given_to_the_runner(self) -> None:
        seen: dict = {}
        started = threading.Event()

        def slow(**kw: object) -> dict:
            seen["request_id"] = kw["request_id"]
            started.set()
            return {"ok": True}

        job_id = jobs.submit("s1", "video", runner=slow)
        started.wait(2.0)
        jobs.wait(job_id)
        self.assertTrue(seen["request_id"])
        # The record carries the same handle an operator would quote to the provider.
        self.assertEqual(jobs.status(job_id)["request_id"], seen["request_id"])

    def test_request_id_survives_a_silent_provider(self) -> None:
        def silent(**_kw: object) -> dict:
            raise jobs.ProviderSilent("connection reset")

        state = jobs.wait(jobs.submit("s7", "video", runner=silent, attempt=3))
        self.assertTrue(state["request_id"].startswith("s7:video:3:"))

    def test_unknown_job_id_is_unmeasured_not_a_crash(self) -> None:
        state = jobs.status("nothing-was-submitted-under-this")
        self.assertEqual(state["state"], "unknown")
        self.assertEqual(state["outcome"], "could not measure")
        self.assertIsNone(state["result"])

    def test_on_settle_receives_the_terminal_record(self) -> None:
        seen: list = []
        jobs.wait(
            jobs.submit(
                "s1", "frame", runner=lambda **kw: {"image": "a.png"}, on_settle=seen.append
            )
        )
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["state"], "done")

    def test_broken_compensator_does_not_hide_the_job(self) -> None:
        def explode(_record: dict) -> None:
            raise ValueError("the compensator itself is broken")

        state = jobs.wait(
            jobs.submit("s1", "frame", runner=lambda **kw: {"ok": 1}, on_settle=explode)
        )
        self.assertEqual(state["state"], "done")
        self.assertIn("the compensator itself is broken", state["settle_error"])


class JobRefusals(unittest.TestCase):
    """Negative control: inputs on which submit is obliged to say no."""

    def setUp(self) -> None:
        jobs.reset()

    def test_unknown_kind_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            jobs.submit("s1", "hologram", runner=lambda **kw: {})

    def test_missing_runner_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            jobs.submit("s1", "frame")

    def test_known_kinds_are_accepted(self) -> None:
        # The other half of the negative control: the guard must let real work through.
        for kind in ("frame", "video"):
            state = jobs.wait(jobs.submit("s1", kind, runner=lambda **kw: {"ok": 1}))
            self.assertEqual(state["state"], "done")


if __name__ == "__main__":
    unittest.main()
