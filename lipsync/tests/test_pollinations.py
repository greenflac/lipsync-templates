"""What the image routes ask for when the caller asks for nothing.

WHY these tests exist: a default that is 9:16 only in arithmetic still comes
back off-plan, because the model snaps each side to a 16px grid. And a size
written once per route drifts one route at a time — that is how a 3:4 default
survived on `compose` while its two siblings were already vertical.

Expected values here are literals on purpose: importing them from the module
under test would let the module move and the test follow it in silence.
"""

from __future__ import annotations

import inspect
import sys
import types
import unittest
from unittest import mock

from lipsync import pollinations as PO

# The frame the pipeline delivers, written out rather than imported: MEASURED
# on the six shipped clips, where Kling returned this size and all six final
# videos carry it. The module now derives its default from `fork_plan.FRAME`,
# so importing the expectation would let the frame move and this test follow it
# in silence.
EXPECTED_SIZE = (720, 1280)
SNAP_GRID = 16
ROUTES = ("image", "images_edit", "compose")


def _defaults(name: str) -> tuple[int, int]:
    sig = inspect.signature(getattr(PO, name))
    return int(sig.parameters["width"].default), int(sig.parameters["height"].default)


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
    def test_checked_all_routes_with_no_violations_and_nothing_unmeasurable(self) -> None:
        """Three outcomes: agreed / disagreed / could not be read at all."""
        checked, violations, unmeasurable = 0, [], []
        for name in ROUTES:
            fn = getattr(PO, name, None)
            if fn is None:
                unmeasurable.append(f"{name}: route missing")
                continue
            try:
                got = _defaults(name)
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


class _FakeResponse:
    status_code = 200
    ok = True
    headers = {"content-type": "image/png"}
    content = b"stub-bytes"
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"data": [{"b64_json": "c3R1Yg=="}]}


class TheDefaultReachesTheWire(unittest.TestCase):
    """A caller passing nothing must put the plan frame in the request itself.

    The network is replaced, not merely avoided by agreement: `requests` is a
    stub module, so a real call would fail rather than spend the account.
    """

    def setUp(self) -> None:
        self.calls: list[dict] = []
        fake = types.ModuleType("requests")

        def _get(url, params=None, headers=None, timeout=None, **kw):
            self.calls.append(dict(params or {}))
            return _FakeResponse()

        def _post(url, headers=None, data=None, files=None, timeout=None, **kw):
            self.calls.append(dict(data or {}))
            return _FakeResponse()

        fake.get = _get
        fake.post = _post
        patcher = mock.patch.dict(sys.modules, {"requests": fake})
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict("os.environ", {"POLLINATIONS_API_KEY": "sk_test"})
        env.start()
        self.addCleanup(env.stop)

    def test_image_sends_the_plan_frame(self) -> None:
        PO.image("p", self._out())
        self.assertEqual(
            (self.calls[-1]["width"], self.calls[-1]["height"]), EXPECTED_SIZE
        )

    def test_compose_sends_the_plan_frame(self) -> None:
        PO.compose("p", ["u1", "u2"], self._out())
        self.assertEqual(
            (self.calls[-1]["width"], self.calls[-1]["height"]), EXPECTED_SIZE
        )

    def test_images_edit_sends_the_plan_frame(self) -> None:
        ref = self._out("ref.jpg")
        ref.write_bytes(b"x")
        PO.images_edit("p", ref, self._out())
        self.assertEqual(self.calls[-1]["size"], "720x1280")

    def _out(self, name: str = "out.png"):
        import tempfile
        from pathlib import Path

        if not hasattr(self, "_dir"):
            self._dir = tempfile.TemporaryDirectory()
            self.addCleanup(self._dir.cleanup)
        return Path(self._dir.name) / name


if __name__ == "__main__":
    unittest.main()
