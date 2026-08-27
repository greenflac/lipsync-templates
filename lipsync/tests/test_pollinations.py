"""Test the one door out of this package: what it asks for, and how it refuses.

WHY these tests exist. Until 2026-08-27 this module had none — 338 lines and
the only code in the package that spends the owner's money, covered by nothing.
Two things went unnoticed because of it: `requests` was imported and never
declared as a dependency, and a default that is 9:16 only in arithmetic still
comes back off-plan, because the model snaps each side to a 16px grid. A size
written once per route also drifts one route at a time — that is how a 3:4
default survived on `compose` while its two siblings were already vertical.

THE NETWORK IS CLOSED BY THE RUNNER, NOT BY AGREEMENT. Two independent locks,
each with its own negative control below:

  1. `socket.socket.connect` is replaced for the whole module, so any real
     call raises instead of leaving the machine.
  2. `sys.modules["requests"]` is replaced with a stub, so the module under
     test cannot reach the real client even if one is installed.

The account behind this gateway is out of balance and would answer HTTP 402, so
a test that quietly went to the wire would fail for the wrong reason and teach
the wrong lesson.

Expected values here are literals on purpose: importing them from the module
under test would let the module move and the test follow it in silence.
"""

from __future__ import annotations

import base64
import inspect
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from lipsync import pollinations as PO

# The frame the pipeline delivers, written out rather than imported: MEASURED
# on the six shipped clips, where Kling returned this size and all six final
# videos carry it. The module derives its default from `fork_plan.FRAME`, so
# importing the expectation would let the frame move and this test follow it.
EXPECTED_SIZE = (720, 1280)
SNAP_GRID = 16
ROUTES = ("image", "images_edit", "compose")

# The hosts the gateway talks to, as literals.
DEFAULT_BASE = "https://gen.pollinations.ai"
DEFAULT_MEDIA = "https://media.pollinations.ai"

KEY_VAR = "POLLINATIONS_API_KEY"
TEST_KEY = "sk_test"

_REAL_CONNECT = socket.socket.connect


def _no_network(self, *args, **kwargs):
    raise AssertionError(f"a test tried to open a socket to {args!r}")


def setUpModule() -> None:
    socket.socket.connect = _no_network  # type: ignore[method-assign]


def tearDownModule() -> None:
    socket.socket.connect = _REAL_CONNECT  # type: ignore[method-assign]


#: A body every JSON route can read, so a test that cares about the request can
#: stay silent about the answer. Steering the answer is opt-in, via `payload`.
DEFAULT_PAYLOAD = {
    "url": "https://media.pollinations.ai/stub",
    "id": "stub",
    "data": [{"b64_json": "c3R1Yi1ieXRlcw=="}],
}


class _FakeResponse:
    """A response the caller can steer: status, headers, body, json payload."""

    def __init__(self, *, status=200, headers=None, content=b"stub-bytes", payload=None, text=""):
        self.status_code = status
        self.ok = 200 <= status < 400
        self.headers = {"content-type": "image/png"} if headers is None else headers
        self.content = content
        self.text = text
        self._payload = payload

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return DEFAULT_PAYLOAD if self._payload is None else self._payload


class _Wire(unittest.TestCase):
    """Base case: the stub client, the key, and a temporary directory."""

    def setUp(self) -> None:
        self.calls: list[dict] = []
        self.responses: list = []
        fake = types.ModuleType("requests")

        def _record(verb, url, kwargs):
            self.calls.append({"verb": verb, "url": url, **kwargs})
            if self.responses:
                return self.responses.pop(0)
            return _FakeResponse()

        setattr(fake, "get", lambda url, **kw: _record("GET", url, kw))
        setattr(fake, "post", lambda url, **kw: _record("POST", url, kw))
        patcher = mock.patch.dict(sys.modules, {"requests": fake})
        patcher.start()
        self.addCleanup(patcher.stop)

        env = mock.patch.dict("os.environ", {KEY_VAR: TEST_KEY})
        env.start()
        self.addCleanup(env.stop)

        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def out(self, name: str = "out.png") -> Path:
        return Path(self._dir.name) / name

    def ref(self, name: str = "ref.jpg", data: bytes = b"jpeg-bytes") -> Path:
        path = self.out(name)
        path.write_bytes(data)
        return path

    @property
    def last(self) -> dict:
        return self.calls[-1]


class TheRunnerClosesTheNetwork(_Wire):
    """Negative control on the locks themselves: both must be able to say no."""

    def test_a_real_socket_cannot_leave_the_machine(self) -> None:
        with socket.socket() as sock:
            with self.assertRaises(AssertionError):
                sock.connect(("example.invalid", 80))

    def test_the_module_uses_the_injected_client_and_not_a_real_one(self) -> None:
        """If the stub were bypassed, this raise could not be observed."""
        boom = types.ModuleType("requests")
        setattr(boom, "get", mock.Mock(side_effect=AssertionError("reached the wire")))
        setattr(boom, "post", mock.Mock(side_effect=AssertionError("reached the wire")))
        with mock.patch.dict(sys.modules, {"requests": boom}):
            with self.assertRaises(AssertionError):
                PO.image("p", self.out())

    def test_the_stub_is_what_records_the_calls(self) -> None:
        PO.image("p", self.out())
        self.assertEqual(len(self.calls), 1)


class TheKeyIsRequiredAndTheRemedyIsRunnable(_Wire):
    def test_a_missing_key_names_the_variable(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError) as caught:
                PO.image("p", self.out())
        self.assertIn(KEY_VAR, str(caught.exception))

    def test_a_missing_key_hands_the_reader_a_command_for_their_shell(self) -> None:
        """The remedy comes from `cure`, so a Windows reader gets `setx`."""
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError) as caught:
                PO.image("p", self.out())
        self.assertIn(f"export {KEY_VAR}=sk_...", str(caught.exception))

    def test_a_missing_key_stops_the_call_before_it_is_made(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                PO.image("p", self.out())
        self.assertEqual(self.calls, [])

    def test_the_key_travels_as_a_bearer_token(self) -> None:
        PO.image("p", self.out())
        self.assertEqual(self.last["headers"], {"Authorization": f"Bearer {TEST_KEY}"})


class TheHostsAreOverridableAndNormalised(_Wire):
    def test_the_generation_host_defaults_to_the_documented_one(self) -> None:
        PO.image("p", self.out())
        self.assertTrue(self.last["url"].startswith(f"{DEFAULT_BASE}/image/"))

    def test_the_media_host_defaults_to_the_documented_one(self) -> None:
        self.responses.append(_FakeResponse(payload={"url": "https://m/1"}))
        PO.upload(self.ref())
        self.assertEqual(self.last["url"], f"{DEFAULT_MEDIA}/upload")

    def test_an_override_is_honoured(self) -> None:
        with mock.patch.dict("os.environ", {"POLLINATIONS_BASE": "http://localhost:9"}):
            PO.image("p", self.out())
        self.assertTrue(self.last["url"].startswith("http://localhost:9/image/"))

    def test_a_trailing_slash_does_not_become_a_double_slash(self) -> None:
        """A `//` in the path is a different route to most servers."""
        with mock.patch.dict("os.environ", {"POLLINATIONS_BASE": "http://localhost:9/"}):
            PO.image("p", self.out())
        self.assertEqual(self.last["url"], "http://localhost:9/image/p")


class ThePromptIsCarriedInThePathAndFullyEscaped(_Wire):
    def test_a_slash_in_the_prompt_does_not_become_a_path_segment(self) -> None:
        PO.image("a/b", self.out())
        self.assertEqual(self.last["url"], f"{DEFAULT_BASE}/image/a%2Fb")

    def test_spaces_are_escaped(self) -> None:
        PO.image("a woman", self.out())
        self.assertEqual(self.last["url"], f"{DEFAULT_BASE}/image/a%20woman")

    def test_cyrillic_is_escaped_as_utf_eight(self) -> None:
        PO.image("да", self.out())
        self.assertEqual(self.last["url"], f"{DEFAULT_BASE}/image/%D0%B4%D0%B0")

    def test_compose_escapes_the_prompt_the_same_way(self) -> None:
        PO.compose("a/b", ["u1", "u2"], self.out())
        self.assertEqual(self.last["url"], f"{DEFAULT_BASE}/image/a%2Fb")


class PlanSizeIsAFrameTheModelWillNotMove(unittest.TestCase):
    def test_it_is_exactly_nine_by_sixteen(self) -> None:
        """Integer cross-multiplication, so no rounding hides a near miss."""
        width, height = PO.PLAN_SIZE
        self.assertEqual(width * 16, height * 9, f"{width}x{height} is not exactly 9:16")

    def test_both_sides_sit_on_the_snap_grid(self) -> None:
        width, height = PO.PLAN_SIZE
        self.assertEqual(
            (width % SNAP_GRID, height % SNAP_GRID),
            (0, 0),
            f"{width}x{height} is off the {SNAP_GRID}px grid, so the model moves it",
        )

    def test_it_is_the_point_that_was_chosen(self) -> None:
        self.assertEqual(tuple(PO.PLAN_SIZE), EXPECTED_SIZE)


class EveryRouteTakesItsDefaultFromTheConstant(unittest.TestCase):
    @staticmethod
    def _defaults(name: str) -> tuple[int, int]:
        sig = inspect.signature(getattr(PO, name))
        return int(sig.parameters["width"].default), int(sig.parameters["height"].default)

    def test_checked_all_routes_with_no_violations_and_nothing_unmeasurable(self) -> None:
        """Three outcomes: agreed / disagreed / could not be read at all."""
        checked, violations, unmeasurable = 0, [], []
        for name in ROUTES:
            fn = getattr(PO, name, None)
            if fn is None:
                unmeasurable.append(f"{name}: route missing")
                continue
            try:
                got = self._defaults(name)
            except (KeyError, TypeError, ValueError) as exc:
                unmeasurable.append(f"{name}: {exc}")
                continue
            checked += 1
            if got != EXPECTED_SIZE:
                violations.append(f"{name}={got[0]}x{got[1]}")
        verdict = (
            f"checked {checked}, violations {len(violations)}, "
            f"unmeasurable {len(unmeasurable)}: {violations or unmeasurable}"
        )
        self.assertEqual(len(unmeasurable), 0, verdict)
        self.assertEqual(checked, len(ROUTES), verdict)
        self.assertEqual(len(violations), 0, verdict)


class TheDefaultReachesTheWire(_Wire):
    """A caller passing nothing must put the plan frame in the request itself."""

    def test_image_sends_the_plan_frame(self) -> None:
        PO.image("p", self.out())
        params = self.last["params"]
        self.assertEqual((params["width"], params["height"]), EXPECTED_SIZE)

    def test_compose_sends_the_plan_frame(self) -> None:
        PO.compose("p", ["u1", "u2"], self.out())
        params = self.last["params"]
        self.assertEqual((params["width"], params["height"]), EXPECTED_SIZE)

    def test_images_edit_sends_the_plan_frame_as_one_string(self) -> None:
        PO.images_edit("p", self.ref(), self.out())
        self.assertEqual(self.last["data"]["size"], "720x1280")

    def test_a_caller_can_still_ask_for_another_frame(self) -> None:
        PO.image("p", self.out(), width=512, height=512)
        params = self.last["params"]
        self.assertEqual((params["width"], params["height"]), (512, 512))


class ImageBuildsTheRequestItSaysItDoes(_Wire):
    def test_the_model_and_seed_travel_as_parameters(self) -> None:
        PO.image("p", self.out(), model="flux", seed=7)
        self.assertEqual(self.last["params"]["model"], "flux")
        self.assertEqual(self.last["params"]["seed"], 7)

    def test_the_default_model_is_the_one_chosen(self) -> None:
        PO.image("p", self.out())
        self.assertEqual(self.last["params"]["model"], "flux")

    def test_no_reference_means_no_image_parameter(self) -> None:
        """An empty `image=` is not the same request as no `image` at all."""
        PO.image("p", self.out())
        self.assertNotIn("image", self.last["params"])

    def test_a_reference_is_passed_through_untouched(self) -> None:
        PO.image("p", self.out(), image_url="https://m/1")
        self.assertEqual(self.last["params"]["image"], "https://m/1")

    def test_the_bytes_are_written_where_the_caller_asked(self) -> None:
        dst = self.out("deep/nested/out.png")
        self.responses.append(_FakeResponse(content=b"PNGDATA"))
        got = PO.image("p", dst)
        self.assertEqual(dst.read_bytes(), b"PNGDATA")
        self.assertEqual(got, str(dst))

    def test_a_refusal_is_raised_rather_than_written_to_disk(self) -> None:
        dst = self.out()
        self.responses.append(_FakeResponse(status=402, text="out of balance"))
        with self.assertRaises(RuntimeError):
            PO.image("p", dst)
        self.assertFalse(dst.exists())


class ComposeRefusesBeforeItSpends(_Wire):
    def test_one_reference_is_the_wrong_route_and_says_so(self) -> None:
        with self.assertRaises(ValueError):
            PO.compose("p", ["u1"], self.out())

    def test_the_wrong_route_costs_nothing(self) -> None:
        with self.assertRaises(ValueError):
            PO.compose("p", ["u1"], self.out())
        self.assertEqual(self.calls, [])

    def test_two_references_are_joined_with_a_pipe(self) -> None:
        PO.compose("p", ["u1", "u2"], self.out())
        self.assertEqual(self.last["params"]["image"], "u1|u2")

    def test_three_references_are_all_carried(self) -> None:
        PO.compose("p", ["u1", "u2", "u3"], self.out())
        self.assertEqual(self.last["params"]["image"], "u1|u2|u3")

    def test_the_default_model_is_the_one_chosen(self) -> None:
        PO.compose("p", ["u1", "u2"], self.out())
        self.assertEqual(self.last["params"]["model"], "nanobanana")


class ComposeHasThreeOutcomesNotTwo(_Wire):
    """Bytes / a refusal / an answer that is not a picture — and they read apart.

    The third is the one that costs a run: a 200 carrying a JSON error is not
    an image, and writing it to `out.png` produces a file the next stage opens
    and fails on, far from the cause.
    """

    def test_an_image_answer_is_written(self) -> None:
        dst = self.out()
        self.responses.append(
            _FakeResponse(headers={"content-type": "image/jpeg"}, content=b"JPEGDATA")
        )
        PO.compose("p", ["u1", "u2"], dst)
        self.assertEqual(dst.read_bytes(), b"JPEGDATA")

    def test_a_refusal_names_the_status(self) -> None:
        self.responses.append(_FakeResponse(status=402, text="payment required"))
        with self.assertRaises(RuntimeError) as caught:
            PO.compose("p", ["u1", "u2"], self.out())
        self.assertIn("402", str(caught.exception))

    def test_a_two_hundred_that_is_not_a_picture_is_not_taken_for_one(self) -> None:
        self.responses.append(
            _FakeResponse(
                headers={"content-type": "application/json"},
                content=b'{"error":"no"}',
                text='{"error":"no"}',
            )
        )
        with self.assertRaises(RuntimeError) as caught:
            PO.compose("p", ["u1", "u2"], self.out())
        self.assertIn("application/json", str(caught.exception))

    def test_a_two_hundred_that_is_not_a_picture_writes_nothing(self) -> None:
        dst = self.out()
        self.responses.append(
            _FakeResponse(headers={"content-type": "application/json"}, content=b"{}", text="{}")
        )
        with self.assertRaises(RuntimeError):
            PO.compose("p", ["u1", "u2"], dst)
        self.assertFalse(dst.exists())

    def test_a_missing_content_type_is_refused_rather_than_assumed(self) -> None:
        self.responses.append(_FakeResponse(headers={}, content=b"...."))
        with self.assertRaises(RuntimeError):
            PO.compose("p", ["u1", "u2"], self.out())

    def test_the_three_outcomes_read_differently(self) -> None:
        """Negative control: three distinct results, not one verdict three times."""
        seen = []
        dst = self.out()
        self.responses.append(_FakeResponse(content=b"PNG"))
        PO.compose("p", ["u1", "u2"], dst)
        seen.append("wrote")
        for headers, status in (({"content-type": "image/png"}, 402), ({}, 200)):
            self.responses.append(_FakeResponse(status=status, headers=headers, text="x"))
            try:
                PO.compose("p", ["u1", "u2"], dst)
            except RuntimeError as exc:
                seen.append(str(exc)[:40])
        self.assertEqual(len(set(seen)), 3, seen)


class ImagesEditSendsTheReferenceItself(_Wire):
    def test_it_posts_to_the_edits_endpoint(self) -> None:
        PO.images_edit("p", self.ref(), self.out())
        self.assertEqual(self.last["verb"], "POST")
        self.assertEqual(self.last["url"], f"{DEFAULT_BASE}/v1/images/edits")

    def test_the_prompt_travels_in_the_body_not_the_path(self) -> None:
        """This route needs no media host, so the prompt is not URL-escaped."""
        PO.images_edit("a/b", self.ref(), self.out())
        self.assertEqual(self.last["data"]["prompt"], "a/b")

    def test_the_reference_is_attached_under_its_own_name(self) -> None:
        ref = self.ref("face.jpg")
        PO.images_edit("p", ref, self.out())
        name, handle, mime = self.last["files"]["image"]
        self.assertEqual(name, "face.jpg")
        self.assertEqual(mime, "image/jpeg")
        self.assertEqual(handle.name, str(ref))

    def test_the_default_model_is_the_one_chosen(self) -> None:
        PO.images_edit("p", self.ref(), self.out())
        self.assertEqual(self.last["data"]["model"], "kontext")

    def test_a_base_sixty_four_answer_is_decoded(self) -> None:
        dst = self.out()
        payload = {"data": [{"b64_json": base64.b64encode(b"PNGDATA").decode("ascii")}]}
        self.responses.append(_FakeResponse(payload=payload))
        PO.images_edit("p", self.ref(), dst)
        self.assertEqual(dst.read_bytes(), b"PNGDATA")

    def test_a_url_answer_is_fetched_with_the_key(self) -> None:
        dst = self.out()
        self.responses.append(_FakeResponse(payload={"data": [{"url": "https://m/9"}]}))
        self.responses.append(_FakeResponse(content=b"FETCHED"))
        PO.images_edit("p", self.ref(), dst)
        self.assertEqual(dst.read_bytes(), b"FETCHED")
        self.assertEqual(self.last["url"], "https://m/9")
        self.assertEqual(self.last["headers"], {"Authorization": f"Bearer {TEST_KEY}"})

    def test_an_answer_with_neither_is_refused_not_written(self) -> None:
        dst = self.out()
        self.responses.append(_FakeResponse(payload={"data": [{"revised_prompt": "x"}]}))
        with self.assertRaises(RuntimeError):
            PO.images_edit("p", self.ref(), dst)
        self.assertFalse(dst.exists())

    def test_a_refusal_is_raised(self) -> None:
        self.responses.append(_FakeResponse(status=402))
        with self.assertRaises(RuntimeError):
            PO.images_edit("p", self.ref(), self.out())


class UploadReturnsAUrlOrSaysWhyItCannot(_Wire):
    def test_a_url_in_the_answer_is_used_as_is(self) -> None:
        self.responses.append(_FakeResponse(payload={"url": "https://m/abc"}))
        self.assertEqual(PO.upload(self.ref()), "https://m/abc")

    def test_an_id_alone_is_turned_into_a_url_on_the_media_host(self) -> None:
        self.responses.append(_FakeResponse(payload={"id": "abc"}))
        self.assertEqual(PO.upload(self.ref()), f"{DEFAULT_MEDIA}/abc")

    def test_a_url_wins_over_an_id(self) -> None:
        self.responses.append(_FakeResponse(payload={"url": "https://m/u", "id": "abc"}))
        self.assertEqual(PO.upload(self.ref()), "https://m/u")

    def test_neither_is_refused_and_the_keys_are_named(self) -> None:
        """Three outcomes: url / id / neither — and the third names what came back."""
        self.responses.append(_FakeResponse(payload={"contentType": "image/jpeg"}))
        with self.assertRaises(RuntimeError) as caught:
            PO.upload(self.ref())
        self.assertIn("contentType", str(caught.exception))

    def test_the_file_is_sent_as_multipart(self) -> None:
        self.responses.append(_FakeResponse(payload={"url": "https://m/u"}))
        ref = self.ref()
        PO.upload(ref)
        self.assertEqual(self.last["files"]["file"].name, str(ref))

    def test_a_refusal_is_raised(self) -> None:
        self.responses.append(_FakeResponse(status=402))
        with self.assertRaises(RuntimeError):
            PO.upload(self.ref())


class EveryLiveRouteAuthenticates(_Wire):
    """Three outcomes over every route: authenticated / bare / not exercisable."""

    def test_checked_every_route_with_no_bare_calls(self) -> None:
        plans = {
            "upload": lambda: PO.upload(self.ref()),
            "image": lambda: PO.image("p", self.out()),
            "images_edit": lambda: PO.images_edit("p", self.ref(), self.out()),
            "compose": lambda: PO.compose("p", ["u1", "u2"], self.out()),
        }
        checked, bare, unexercisable = 0, [], []
        for name, call in plans.items():
            self.calls.clear()
            try:
                call()
            except Exception as exc:  # noqa: BLE001 — a route we cannot drive is outcome three
                unexercisable.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            checked += 1
            if self.calls[0].get("headers", {}).get("Authorization") != f"Bearer {TEST_KEY}":
                bare.append(f"{name}: {self.calls[0].get('headers')}")
        verdict = (
            f"checked {checked}, bare {len(bare)}, unexercisable {len(unexercisable)}: "
            f"{bare or unexercisable}"
        )
        self.assertEqual(len(unexercisable), 0, verdict)
        self.assertEqual(checked, len(plans), verdict)
        self.assertEqual(len(bare), 0, verdict)


class TheOtherStacksRoutesAreGone(unittest.TestCase):
    """Video, frames, judging and speech left with the stack that used them.

    Kling Motion Control through fal.ai makes the video; `fork_video` cuts the
    frames with ffmpeg; the aesthetic verdict comes from `creative_eval`. Each
    name below had a caller in the research tree and none in this product.
    """

    REMOVED = (
        "video",
        "video_loop",
        "extract_frames",
        "frame_names_sort_correctly",
        "chat",
        "judge_frame",
        "opinion_of",
        "tts",
        "LAST_VIDEO_USAGE",
        "JUDGE_SYSTEM",
        "FRAME_PATTERN",
    )

    def test_none_of_them_is_back(self) -> None:
        back = [name for name in self.REMOVED if hasattr(PO, name)]
        self.assertEqual(back, [], f"checked {len(self.REMOVED)}, back {len(back)}: {back}")

    def test_the_sweep_can_see_a_name_that_is_present(self) -> None:
        """Negative control on the check above."""
        self.assertTrue(hasattr(PO, "compose"))

    def test_the_frame_width_that_overflowed_is_not_declared_here(self) -> None:
        """`FRAME_PATTERN` was `%04d.png`: 9999 names against a 36000 ceiling.

        The surviving namer is `fork_video.NAME_DIGITS`, and it is five wide.
        One place to look, and the one that is wide enough.
        """
        from lipsync import fork_video

        self.assertEqual(fork_video.NAME_DIGITS, 5)
        self.assertFalse(hasattr(PO, "FRAME_PATTERN"))


if __name__ == "__main__":
    unittest.main()
