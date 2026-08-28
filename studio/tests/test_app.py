"""Tests for the studio web layer, driven end to end on stand-ins.

The store, the ledger, the style extractor, the photo intake and both engine
runners are fakes declared here, so the whole path — session, selfie, style,
frame, consent, video — runs without the sibling modules and without a socket.
"""

from __future__ import annotations

import io
import socket
import unittest
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from studio import jobs
from studio.app import Deps, create_app

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


PASS_ = "pass"
FAIL_ = "fail"
UNMEASURED_ = "could not measure"


class FakeStore:
    """A session store in a dict, with the contract's three functions.

    The writable columns are repeated here as literals on purpose: if the real
    store's set moves, this fake keeps the old one and the tests go red instead
    of agreeing with whatever the code now does.
    """

    SESSION_FIELDS = ("template", "selfie_path", "style_spec", "last_job_id", "stage")

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self._next = 0

    def create_session(self, user_id: str) -> str:
        self._next += 1
        session_id = f"sess{self._next}"
        self.sessions[session_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "stage": "new",
            "template": None,
            "selfie_path": None,
            "style_spec": None,
            "last_job_id": None,
        }
        return session_id

    def get(self, session_id: str) -> dict | None:
        found = self.sessions.get(session_id)
        return dict(found) if found is not None else None

    def update(self, session_id: str, **fields: object) -> dict:
        unknown = sorted(name for name in fields if name not in self.SESSION_FIELDS)
        if unknown:
            return {"outcome": FAIL_, "note": f"unknown session fields {unknown}", "session": None}
        if session_id not in self.sessions:
            return {"outcome": FAIL_, "note": "no such session", "session": None}
        stored = dict(fields)
        spec = stored.get("style_spec")
        # The real store keeps the spec as JSON, so a spec always comes back as
        # a mapping; the fake does the same or the rehydration path is untested.
        if spec is not None and is_dataclass(spec) and not isinstance(spec, type):
            stored["style_spec"] = asdict(spec)
        self.sessions[session_id].update(stored)
        return {"outcome": PASS_, "session": dict(self.sessions[session_id])}


class FakeLedger:
    """A journal in a list: the balance is its sum, keys are honoured once."""

    def __init__(self, opening: int = 100) -> None:
        self.rows: list[dict] = [{"delta": opening, "key": "opening", "reason": "opening"}]
        self.keys: set[str] = {"opening"}
        self.broken = False

    def balance(self, _user_id: str) -> int:
        return sum(int(row["delta"]) for row in self.rows)

    def _append(self, delta: int, key: str, reason: str) -> dict:
        if self.broken:
            return {"outcome": UNMEASURED_, "note": "journal unreachable", "checked": 0}
        if key in self.keys:
            return {"outcome": PASS_, "balance": self.balance("u"), "delta": 0, "duplicate": True}
        if delta < 0 and self.balance("u") + delta < 0:
            return {"outcome": FAIL_, "note": "insufficient credits", "balance": self.balance("u")}
        self.keys.add(key)
        self.rows.append({"delta": delta, "key": key, "reason": reason})
        return {"outcome": PASS_, "balance": self.balance("u"), "delta": delta, "key": key}

    def charge(self, user_id: str, credits: int, *, key: str, reason: str) -> dict:
        return self._append(-credits, key, reason)

    def refund(self, user_id: str, credits: int, *, key: str, reason: str) -> dict:
        return self._append(credits, key, reason)


@dataclass(frozen=True)
class FakeSpec:
    """Stands in for StyleSpec; only the fields the web layer touches."""

    palette: tuple = ("red",)
    light: str = "soft"
    texture: str = "film"
    mood: str = "calm"
    setting: str = "a kitchen"
    refusal: str | None = None


class FakeStyle:
    """Style extraction that answers by keyword, so a test can pick the outcome."""

    StyleSpec = FakeSpec

    def extract(self, text: str, *, model: object = None) -> dict:
        if "silent" in text:
            return {"outcome": UNMEASURED_, "spec": None, "note": "the model did not answer"}
        if "refuse" in text:
            return {"outcome": FAIL_, "spec": None, "note": "not a style description"}
        return {"outcome": PASS_, "spec": FakeSpec(), "note": "extracted"}

    def gate_input(self, spec: FakeSpec) -> dict:
        if spec.refusal:
            return {"outcome": FAIL_, "note": spec.refusal, "checked": 1, "violations": 1}
        return {"outcome": PASS_, "note": "inside the allow-list", "checked": 1, "violations": 0}

    def build_prompt(self, spec: FakeSpec) -> str:
        return f"a portrait, {spec.mood}, {spec.light} light, in {spec.setting}"


def intake_ok(path: str, **_kw: object) -> dict:
    return {"outcome": PASS_, "checked": 3, "violations": 0, "unmeasured": 0, "note": "face found"}


def intake_no_face(path: str, **_kw: object) -> dict:
    return {"outcome": FAIL_, "checked": 3, "violations": 1, "unmeasured": 0, "note": "no face"}


def intake_blind(path: str, **_kw: object) -> dict:
    return {
        "outcome": UNMEASURED_,
        "checked": 0,
        "violations": 0,
        "unmeasured": 3,
        "note": "the detector is silent",
    }


def runner_ok(**kw: object) -> dict:
    return {"path": "work/out.png", "request_id": kw["request_id"]}


def runner_boom(**_kw: object) -> dict:
    raise RuntimeError("the provider rejected the payload")


def runner_silent(**_kw: object) -> dict:
    raise jobs.ProviderSilent("no answer in 120 s")


class StudioCase(unittest.TestCase):
    """Shared wiring: a client whose collaborators the test can swap."""

    def setUp(self) -> None:
        jobs.reset()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = FakeStore()
        self.ledger = FakeLedger()
        self.deps = Deps(
            store=self.store,
            ledger=self.ledger,
            style=FakeStyle(),
            photo_intake=intake_ok,
            frame_runner=runner_ok,
            video_runner=runner_ok,
            uploads_dir=Path(self.tmp.name) / "uploads",
            static_dir=Path(self.tmp.name) / "static",
        )
        self.client = TestClient(create_app(self.deps))

    def open_session(self) -> str:
        reply = self.client.post("/api/session", json={"user_id": "u1"})
        self.assertEqual(reply.status_code, 200)
        return str(reply.json()["session_id"])

    def upload_selfie(self, session_id: str) -> None:
        reply = self.client.post(
            "/api/selfie",
            data={"session_id": session_id},
            files={"file": ("me.png", io.BytesIO(b"not really a png"), "image/png")},
        )
        self.assertEqual(reply.status_code, 200, reply.text)

    def set_style(self, session_id: str, text: str = "warm kitchen, film grain") -> None:
        reply = self.client.post("/api/style", json={"session_id": session_id, "text": text})
        self.assertEqual(reply.status_code, 200, reply.text)

    def make_frame(self, session_id: str) -> str:
        reply = self.client.post(
            "/api/frame", json={"session_id": session_id, "template_id": "dance_hallway"}
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        job_id = str(reply.json()["job_id"])
        jobs.wait(job_id)
        return job_id


class HappyPath(StudioCase):
    def test_whole_path_session_to_video(self) -> None:
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        frame_job = self.make_frame(session_id)
        self.assertEqual(self.client.get(f"/api/job/{frame_job}").json()["state"], "done")

        consent = self.client.post("/api/consent", json={"session_id": session_id})
        self.assertEqual(consent.status_code, 200, consent.text)

        video = self.client.post("/api/video", json={"session_id": session_id})
        self.assertEqual(video.status_code, 200, video.text)
        state = jobs.wait(str(video.json()["job_id"]))
        self.assertEqual(state["state"], "done")
        # Literal prices, not imports: an import would move with the code.
        self.assertEqual(self.ledger.balance("u1"), 100 - 1 - 10)

    def test_frame_charges_one_credit_and_video_charges_ten(self) -> None:
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        frame = self.client.post(
            "/api/frame", json={"session_id": session_id, "template_id": "dance_hallway"}
        )
        self.assertEqual(frame.json()["charged"], 1)
        jobs.wait(str(frame.json()["job_id"]))
        self.client.post("/api/consent", json={"session_id": session_id})
        video = self.client.post("/api/video", json={"session_id": session_id})
        self.assertEqual(video.json()["charged"], 10)

    def test_idempotency_key_is_session_kind_and_attempt(self) -> None:
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        first = self.client.post(
            "/api/frame", json={"session_id": session_id, "template_id": "dance_hallway"}
        ).json()
        jobs.wait(str(first["job_id"]))
        second = self.client.post(
            "/api/frame", json={"session_id": session_id, "template_id": "dance_hallway"}
        ).json()
        self.assertEqual(first["idempotency_key"], f"{session_id}:frame:1")
        self.assertEqual(second["idempotency_key"], f"{session_id}:frame:2")

    def test_templates_are_listed_with_their_availability(self) -> None:
        body = self.client.get("/api/templates").json()
        self.assertEqual(len(body["templates"]), 3)
        self.assertIn("available", body["templates"][0])
        self.assertEqual(body["availability"]["checked"], 3)

    def test_index_falls_back_to_a_placeholder_and_serves_the_real_file(self) -> None:
        # Negative control both ways: no file, then a file.
        self.assertIn("not built yet", self.client.get("/").text)
        static = Path(self.tmp.name) / "static"
        static.mkdir(parents=True, exist_ok=True)
        (static / "index.html").write_text("<h1>the real interface</h1>", encoding="utf-8")
        self.assertIn("the real interface", self.client.get("/").text)


class MoneyGuard(StudioCase):
    def test_video_without_consent_is_refused_and_nothing_is_charged(self) -> None:
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        self.make_frame(session_id)
        before = self.ledger.balance("u1")

        reply = self.client.post("/api/video", json={"session_id": session_id})

        self.assertEqual(reply.status_code, 409)
        self.assertEqual(reply.json()["outcome"], "fail")
        self.assertEqual(self.ledger.balance("u1"), before)

    def test_client_claiming_consent_in_the_body_does_not_get_a_video(self) -> None:
        # The word of the client is not evidence; only the recorded state is.
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        self.make_frame(session_id)
        reply = self.client.post("/api/video", json={"session_id": session_id, "consented": True})
        self.assertEqual(reply.status_code, 409)

    def test_video_before_any_frame_is_refused(self) -> None:
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        reply = self.client.post("/api/video", json={"session_id": session_id})
        self.assertEqual(reply.status_code, 409)
        self.assertIn("nothing to agree to", reply.json()["note"])

    def test_consent_cannot_be_recorded_before_the_frame_is_done(self) -> None:
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        reply = self.client.post("/api/consent", json={"session_id": session_id})
        self.assertEqual(reply.status_code, 409)

    def test_failed_generation_is_compensated_and_the_balance_is_restored(self) -> None:
        self.deps.frame_runner = runner_boom
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        before = self.ledger.balance("u1")

        reply = self.client.post(
            "/api/frame", json={"session_id": session_id, "template_id": "dance_hallway"}
        )
        state = jobs.wait(str(reply.json()["job_id"]))

        self.assertEqual(state["state"], "failed")
        self.assertEqual(self.ledger.balance("u1"), before)
        # The charge is not deleted: a compensating row is added beside it.
        deltas = [row["delta"] for row in self.ledger.rows[1:]]
        self.assertEqual(deltas, [-1, 1])

    def test_unknown_outcome_is_neither_refunded_nor_reported_as_success(self) -> None:
        self.deps.frame_runner = runner_silent
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        before = self.ledger.balance("u1")

        reply = self.client.post(
            "/api/frame", json={"session_id": session_id, "template_id": "dance_hallway"}
        )
        job_id = str(reply.json()["job_id"])
        state = jobs.wait(job_id)

        self.assertEqual(state["state"], "unknown")
        self.assertEqual(state["outcome"], "could not measure")
        # The money stays gone: the provider may have done the work.
        self.assertEqual(self.ledger.balance("u1"), before - 1)
        session = self.store.get(session_id) or {}
        self.assertEqual(session["stage"], "needs_review")

    def test_unknown_frame_does_not_unlock_the_expensive_video(self) -> None:
        self.deps.frame_runner = runner_silent
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        jobs.wait(
            str(
                self.client.post(
                    "/api/frame", json={"session_id": session_id, "template_id": "dance_hallway"}
                ).json()["job_id"]
            )
        )
        before = self.ledger.balance("u1")
        # "We cannot tell whether the frame exists" is answered as such (503),
        # not as a refusal the user could fix and not as a started video.
        consent = self.client.post("/api/consent", json={"session_id": session_id})
        self.assertEqual(consent.status_code, 503)
        video = self.client.post("/api/video", json={"session_id": session_id})
        self.assertEqual(video.status_code, 503)
        self.assertEqual(video.json()["outcome"], "could not measure")
        self.assertEqual(self.ledger.balance("u1"), before)

    def test_short_balance_refuses_the_video_and_nothing_is_charged(self) -> None:
        self.ledger.rows = [{"delta": 1, "key": "opening", "reason": "opening"}]
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        self.make_frame(session_id)
        self.client.post("/api/consent", json={"session_id": session_id})

        reply = self.client.post("/api/video", json={"session_id": session_id})

        self.assertEqual(reply.status_code, 402)
        self.assertEqual(self.ledger.balance("u1"), 0)

    def test_unreachable_journal_is_unmeasured_not_a_free_video(self) -> None:
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        self.make_frame(session_id)
        self.client.post("/api/consent", json={"session_id": session_id})
        self.ledger.broken = True

        reply = self.client.post("/api/video", json={"session_id": session_id})

        self.assertEqual(reply.status_code, 503)
        self.assertEqual(reply.json()["outcome"], "could not measure")


class Refusals(StudioCase):
    """Negative control: every endpoint has an input it must turn down."""

    def test_bad_photo_is_a_readable_refusal_not_a_500(self) -> None:
        self.deps.photo_intake = intake_no_face
        session_id = self.open_session()
        reply = self.client.post(
            "/api/selfie",
            data={"session_id": session_id},
            files={"file": ("me.png", io.BytesIO(b"x"), "image/png")},
        )
        self.assertEqual(reply.status_code, 400)
        self.assertIn("no face", reply.json()["note"])

    def test_blind_detector_is_unmeasured_not_a_rejected_photo(self) -> None:
        self.deps.photo_intake = intake_blind
        session_id = self.open_session()
        reply = self.client.post(
            "/api/selfie",
            data={"session_id": session_id},
            files={"file": ("me.png", io.BytesIO(b"x"), "image/png")},
        )
        self.assertEqual(reply.status_code, 503)
        self.assertEqual(reply.json()["outcome"], "could not measure")

    def test_refused_style_is_reported_with_its_reason(self) -> None:
        session_id = self.open_session()
        reply = self.client.post(
            "/api/style", json={"session_id": session_id, "text": "refuse this please"}
        )
        self.assertEqual(reply.status_code, 400)
        self.assertIn("not a style description", reply.json()["note"])

    def test_silent_style_model_is_unmeasured(self) -> None:
        session_id = self.open_session()
        reply = self.client.post(
            "/api/style", json={"session_id": session_id, "text": "silent model here"}
        )
        self.assertEqual(reply.status_code, 503)

    def test_frame_without_a_selfie_is_refused(self) -> None:
        session_id = self.open_session()
        self.set_style(session_id)
        reply = self.client.post(
            "/api/frame", json={"session_id": session_id, "template_id": "dance_hallway"}
        )
        self.assertEqual(reply.status_code, 409)

    def test_frame_without_a_style_is_refused(self) -> None:
        session_id = self.open_session()
        self.upload_selfie(session_id)
        reply = self.client.post(
            "/api/frame", json={"session_id": session_id, "template_id": "dance_hallway"}
        )
        self.assertEqual(reply.status_code, 409)

    def test_unknown_template_is_refused(self) -> None:
        session_id = self.open_session()
        self.upload_selfie(session_id)
        self.set_style(session_id)
        reply = self.client.post(
            "/api/frame", json={"session_id": session_id, "template_id": "no_such_template"}
        )
        self.assertEqual(reply.status_code, 400)

    def test_unknown_session_is_refused_by_every_endpoint_that_takes_one(self) -> None:
        for path, body in (
            ("/api/style", {"session_id": "ghost", "text": "warm"}),
            ("/api/frame", {"session_id": "ghost", "template_id": "dance_hallway"}),
            ("/api/consent", {"session_id": "ghost"}),
            ("/api/video", {"session_id": "ghost"}),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, json=body).status_code, 404)

    def test_unknown_job_id_is_answered_not_raised(self) -> None:
        reply = self.client.get("/api/job/does-not-exist")
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.json()["state"], "unknown")

    def test_uploaded_file_never_lands_under_the_client_s_own_name(self) -> None:
        session_id = self.open_session()
        reply = self.client.post(
            "/api/selfie",
            data={"session_id": session_id},
            files={"file": ("../../etc/passwd", io.BytesIO(b"x"), "image/png")},
        )
        self.assertEqual(reply.status_code, 200)
        saved = Path(reply.json()["selfie_path"])
        self.assertEqual(saved.parent, Path(self.tmp.name) / "uploads")
        self.assertEqual(saved.suffix, ".bin")


if __name__ == "__main__":
    unittest.main()
