"""Gate: no route may default to a size that is not the plan, on the grid.

WHY, and the owner's own evidence for it (2026-08-26): a run with a driving
video and a user photo but NO template never produced bands, while every run
with a template did. One image goes through `images_edit`, two images go
through `compose` — and the 3:4 default lived on `compose` alone. The route
choice, not the prompt, decided whether the frame came back vertical.

That default is gone. What remains is the same trap one step along: all three
routes now default to 1080x1920, which is exactly 0.5625 but OFF THE GRID —
1080 is not a multiple of 16. This module's sibling comment in fork_e2e says
it plainly: the model snaps each side to its own grid, so an off-grid request
comes back as something that is no longer 9:16. A default that is only
arithmetically 9:16 is a defect waiting for the next caller.

And the size is declared three times, once per route. Three copies of one
number is three chances for them to drift, which is exactly how the 3:4
default survived on one route while its two siblings were vertical.

Written before the implementation. Never edited by the agent implementing it.
"""

from __future__ import annotations

import inspect
import unittest

from lipsync import fork_plan as P
from lipsync import pollinations as PO

# Every function in `pollinations` that asks an image model for a picture.
IMAGE_ROUTES = ("image", "images_edit", "compose")

# CHOSEN: the grid the model measurably snaps to. Both sides of any size we
# ask for must sit on it, or the model moves them for us.
GRID = 16

PLAN = 0.5625
TOLERANCE = 0.001


def _default_size(name: str) -> tuple[int, int]:
    sig = inspect.signature(getattr(PO, name))
    return int(sig.parameters["width"].default), int(sig.parameters["height"].default)


class EveryRouteDefaultsToThePlan(unittest.TestCase):
    def test_there_are_routes_to_check(self) -> None:
        """Zero violations over zero checks is not a pass."""
        for name in IMAGE_ROUTES:
            self.assertTrue(hasattr(PO, name), f"missing route {name}")

    def test_no_route_defaults_to_three_by_four(self) -> None:
        """The defect itself: the shape that produced every shipped band."""
        for name in IMAGE_ROUTES:
            with self.subTest(route=name):
                width, height = _default_size(name)
                self.assertNotAlmostEqual(
                    width / height,
                    0.75,
                    places=2,
                    msg=f"{name} still defaults to 3:4 ({width}x{height})",
                )

    def test_every_route_defaults_to_the_plan(self) -> None:
        for name in IMAGE_ROUTES:
            with self.subTest(route=name):
                width, height = _default_size(name)
                self.assertLessEqual(
                    abs(width / height - PLAN),
                    TOLERANCE,
                    f"{name} defaults to {width}x{height} = {width / height:.4f}",
                )

    def test_every_route_default_sits_on_the_grid(self) -> None:
        """Arithmetically 9:16 is not enough; the model moves off-grid sides."""
        for name in IMAGE_ROUTES:
            with self.subTest(route=name):
                width, height = _default_size(name)
                self.assertEqual(
                    (width % GRID, height % GRID),
                    (0, 0),
                    f"{name} defaults to {width}x{height}, off the {GRID}px "
                    "grid the model snaps to, so the answer will not be 9:16",
                )


class TheDefaultIsOneNumberInOnePlace(unittest.TestCase):
    """Three copies of one size is how the 3:4 default survived alone."""

    def test_the_routes_agree_with_each_other(self) -> None:
        sizes = {name: _default_size(name) for name in IMAGE_ROUTES}
        self.assertEqual(
            len(set(sizes.values())),
            1,
            f"the routes disagree about the default frame: {sizes}",
        )

    def test_the_size_is_a_named_constant(self) -> None:
        self.assertTrue(
            hasattr(PO, "PLAN_SIZE"),
            "the default frame must be one importable constant, not a literal "
            "repeated once per route",
        )
        self.assertEqual(_default_size("compose"), tuple(PO.PLAN_SIZE))

    def test_the_constant_agrees_with_the_plan_module(self) -> None:
        width, height = PO.PLAN_SIZE
        self.assertLessEqual(abs(width / height - P.PLAN_RATIO), P.PLAN_TOLERANCE)


class WhatWeAskForAgreesWithTheDefault(unittest.TestCase):
    """A caller passing nothing must get the same frame as one passing the plan."""

    def test_the_styliser_asks_for_a_size_on_the_grid(self) -> None:
        from lipsync import fork_e2e as E

        width, height = E.STYLED_SIZE
        self.assertEqual((width % GRID, height % GRID), (0, 0))
        self.assertLessEqual(abs(width / height - PLAN), TOLERANCE)

    def test_the_outpaint_asks_for_a_size_on_the_grid(self) -> None:
        width, height = P.EXTEND_SIZE
        self.assertEqual((width % GRID, height % GRID), (0, 0))
        self.assertLessEqual(abs(width / height - PLAN), TOLERANCE)


if __name__ == "__main__":
    unittest.main()
