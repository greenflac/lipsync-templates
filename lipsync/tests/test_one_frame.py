"""Gate: the product has exactly one frame, and it is declared once.

Owner's decision 2026-08-26: «хочу единообразие кадров по разрешению».

Today three names hold three sizes — `pollinations.PLAN_SIZE` (1152x2048),
`fork_e2e.STYLED_SIZE` (720x1280) and `fork_plan.EXTEND_SIZE` (1152x2048).
All three are exact 9:16 and on the grid, so none is a defect on its own. The
defect is that there are three of them: every extra copy of one number is a
place where the next drift starts, and this repository has already paid for
that once — the 3:4 default survived on `compose` alone precisely because its
two siblings held their own copies of the size.

MEASURED: Kling returned 720x1280 on all six shipped clips, and all six final
videos are 720x1280. That is the product's real delivery frame, so it is the
one the rest of the pipeline is unified onto — a measurement, not a taste.

Written before the implementation. Never edited by the agent implementing it.
"""

from __future__ import annotations

import unittest

from lipsync import fork_e2e as E
from lipsync import fork_plan as P
from lipsync import frame as FR
from lipsync import pollinations as PO

# MEASURED 2026-08-23: six shipped clips, six kling_out.mp4 and six final.mp4,
# every one of them this size.
DELIVERED = (720, 1280)
GRID = 16


class ThereIsOneFrame(unittest.TestCase):
    def test_the_frame_is_declared_once_and_importable(self) -> None:
        self.assertTrue(hasattr(FR, "FRAME"), "the one frame must be named FRAME")
        self.assertEqual(tuple(FR.FRAME), DELIVERED)
        self.assertTrue(hasattr(P, "FRAME"), "the plan must keep offering the name")
        self.assertEqual(tuple(P.FRAME), DELIVERED)

    def test_every_name_for_a_frame_is_the_same_frame(self) -> None:
        sizes = {
            "frame.FRAME": tuple(FR.FRAME),
            "fork_plan.FRAME": tuple(P.FRAME),
            "pollinations.PLAN_SIZE": tuple(PO.PLAN_SIZE),
            "fork_e2e.STYLED_SIZE": tuple(E.STYLED_SIZE),
            "fork_plan.EXTEND_SIZE": tuple(P.EXTEND_SIZE),
        }
        self.assertEqual(
            len(set(sizes.values())),
            1,
            f"the pipeline still holds more than one frame: {sizes}",
        )

    def test_moving_the_frame_moves_every_user_of_it(self) -> None:
        """Imported, not copied: one edit must move them all.

        The declaration moved out of `fork_plan` into `frame` when the gateway
        stopped reaching up into the plan for it, so the edit is made where the
        frame is now declared. `fork_plan.FRAME` is one of the readers here and
        no longer the source: a re-export that did not follow would be a second
        frame under an old name, which is the very defect this class watches.
        """
        import importlib
        from unittest import mock

        with mock.patch.object(FR, "FRAME", (1152, 2048)):
            moved = (
                tuple(importlib.reload(P).FRAME),
                tuple(importlib.reload(PO).PLAN_SIZE),
                tuple(importlib.reload(E).STYLED_SIZE),
            )
        importlib.reload(P)
        importlib.reload(PO)
        importlib.reload(E)
        self.assertEqual(
            moved,
            ((1152, 2048), (1152, 2048), (1152, 2048)),
            f"the frame was moved and these did not follow: {moved}",
        )


class TheFrameIsOnThePlanAndOnTheGrid(unittest.TestCase):
    def test_it_is_exactly_nine_by_sixteen(self) -> None:
        width, height = P.FRAME
        self.assertEqual(width * 16, height * 9, f"{width}x{height} is not 9:16")

    def test_both_sides_sit_on_the_grid_the_model_snaps_to(self) -> None:
        width, height = P.FRAME
        self.assertEqual((width % GRID, height % GRID), (0, 0))

    def test_it_agrees_with_the_plan_ratio(self) -> None:
        width, height = P.FRAME
        self.assertLessEqual(abs(width / height - P.PLAN_RATIO), P.PLAN_TOLERANCE)


class NoFrameLiteralsSurviveOutsideTheDeclaration(unittest.TestCase):
    """A literal left behind is the next copy waiting to drift."""

    WATCHED = ("fork_plan", "fork_e2e", "pollinations", "fork_finish")

    def test_no_module_repeats_a_frame_as_a_literal_pair(self) -> None:
        import ast
        import importlib
        from pathlib import Path

        offenders = []
        for name in self.WATCHED:
            module = importlib.import_module(f"lipsync.{name}")
            source = module.__file__
            self.assertIsNotNone(source, f"lipsync.{name} has no file on disk")
            tree = ast.parse(Path(str(source)).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Tuple) or len(node.elts) != 2:
                    continue
                values = [
                    e.value
                    for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, int)
                ]
                if len(values) != 2:
                    continue
                width, height = values
                if width > 100 and height > 100 and width * 16 == height * 9:
                    if (width, height) != tuple(P.FRAME) or name != "fork_plan":
                        offenders.append(f"{name}: {width}x{height} line {node.lineno}")
        self.assertEqual(
            offenders,
            [],
            f"frame written as a literal instead of imported: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
