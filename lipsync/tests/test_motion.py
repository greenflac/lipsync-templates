"""Cut detection on synthetic frames: the bar, its two sides, and the sample.

These checks arrived with `cuts`, `read_gray` and `CUT_SIDE` when the loop
finder that used to hold them was deleted on 2026-08-31. What the finder did
with the answer — refusing loops that stepped across a cut — went with it; what
is left is the measurement itself, which the intake and the output acceptance
both run.

The pixels are DERIVED FROM A SKELETON so that a "cut" here means what it means
on real material: the picture jumps because the body jumped, not because a
number in the fixture was nudged.
"""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from .. import motion
from ..fork_identity import PASS, UNMEASURED

PERIOD = 44
NFRAMES = 96


def skeleton(phase, *, amp=0.10):
    """One frame of a pendulum: the arms swing, the rest of the body stands still."""
    ph = 2 * math.pi * phase
    ax, ay = amp * math.cos(ph), amp * math.sin(ph)
    pts = {
        "l_hip": (0.45, 0.60),
        "r_hip": (0.55, 0.60),
        "l_shoulder": (0.44, 0.40),
        "r_shoulder": (0.56, 0.40),
        "l_elbow": (0.40 + ax, 0.50 + ay),
        "r_elbow": (0.60 - ax, 0.50 + ay),
        "l_wrist": (0.38 + 2 * ax, 0.58 + 2 * ay),
        "r_wrist": (0.62 - 2 * ax, 0.58 + 2 * ay),
        "l_knee": (0.44, 0.75),
        "r_knee": (0.56, 0.75),
        "l_ankle": (0.44, 0.90),
        "r_ankle": (0.56, 0.90),
    }
    return {k: (x, y, 1.0) for k, (x, y) in pts.items()}


def loop_sequence(n=NFRAMES):
    """Build a pendulum: motion repeats exactly every PERIOD frames."""
    return [skeleton(t / PERIOD) for t in range(n)]


class Material:
    """Frames on disk plus a stubbed pixel reader."""

    def __init__(self, poses, *, size=(32, 32), cuts=(), blank=False):
        from PIL import Image

        self.dir = Path(tempfile.mkdtemp(prefix="motion_frames_"))
        self.poses = poses
        self.cuts = set(cuts)
        for k in range(len(poses)):
            f = self.dir / f"{k:04d}.png"
            if blank:
                # The pixel reader is stubbed in these cases, so the file only
                # has to exist. Writing 96 real images would measure Pillow.
                f.touch()
            else:
                Image.new("RGB", size, (k * 2 % 256, 40, 200 - k % 200)).save(f)

    def gray(self, path):
        """Return pixels DERIVED FROM THE SKELETON of this frame, plus a jump at cuts."""
        import numpy as np

        idx = int(Path(path).stem)
        pts = self.poses[idx]
        body = (4.0 * sum(x + y for x, y, _ in pts.values())) if pts else 0.0
        base = body + sum(5.0 for c in self.cuts if idx > c)
        return np.full((8, 8), base, dtype="float64")

    def paths(self):
        return sorted(str(p) for p in self.dir.iterdir() if p.suffix == ".png")


class Cuts(unittest.TestCase):
    def test_a_cut_is_found(self):
        m = Material(loop_sequence(), cuts=(47,), blank=True)
        got = motion.cuts(m.paths(), gray=m.gray)
        self.assertEqual(got["outcome"], PASS)
        self.assertEqual(got["cuts"], [47])
        self.assertEqual(got["steps"], NFRAMES - 1)
        self.assertAlmostEqual(got["worst"], 21.9, places=1)

    def test_a_cut_is_not_invented_on_smooth_material(self):
        """Run the other side's negative control: smooth motion is not a cut."""
        m = Material(loop_sequence(), blank=True)
        got = motion.cuts(m.paths(), gray=m.gray)
        self.assertEqual(got["cuts"], [])
        self.assertAlmostEqual(
            got["worst"],
            1.41,
            places=2,
            msg="the sharpest transition of a smooth pendulum is one and a half "
            "typical steps, far below the 4.0 bar",
        )

    def test_a_shake_is_not_a_cut_either(self):
        """A jump three times the typical is still motion, not editing."""
        import numpy as np

        m = Material(loop_sequence(), blank=True)
        m.gray = lambda path: np.full(
            (8, 8), float(sum(3 if k % 10 == 0 else 1 for k in range(int(Path(path).stem)))) % 200
        )
        got = motion.cuts(m.paths(), gray=m.gray)
        self.assertEqual(got["worst"], 3.0)
        self.assertEqual(
            got["cuts"],
            [],
            "the bar stands above shake and below editing; lowering it "
            "would declare every sharp swing a cut",
        )

    def test_the_bar_is_the_one_this_module_declares(self):
        """The bar is clamped from both sides: 3.0x is motion, 4.1x is a cut.

        The shake above sits just under `JUMP_MAX` and the cut far over it, so
        moving the constant either way changes an answer here. Without this
        pair the number could be anything between 3 and 21 in silence.
        """
        import numpy as np

        steps = [1.0] * 8 + [4.1]
        values, acc = [0.0], 0.0
        for d in steps:
            acc += d
            values.append(acc)
        got = motion.cuts(
            [str(i) for i in range(len(values))],
            gray=lambda p: np.full((2, 2), values[int(p)], dtype=float),
        )
        self.assertEqual(motion.JUMP_MAX, 4.0)
        self.assertEqual(got["cuts"], [8])

    def test_the_default_pixel_reader_downscales_to_the_declared_side(self):
        """Read the default injection point with a real frame, not a mock."""
        m = Material(loop_sequence(2), size=(240, 426))
        arr = motion.read_gray(m.paths()[0])
        self.assertEqual(arr.shape, (motion.CUT_SIDE, motion.CUT_SIDE))
        self.assertEqual(arr.shape, (96, 96))

    def test_the_default_pixel_reader_is_what_cuts_reaches_for(self):
        """The wiring, not just the reader: `cuts` called with no `gray` uses it."""
        m = Material(loop_sequence(4), size=(64, 64))
        got = motion.cuts(m.paths())
        self.assertEqual(got["steps"], 3)
        self.assertIn(got["outcome"], (PASS, UNMEASURED))

    def test_a_frozen_clip_cannot_be_asked_about_cuts(self):
        """'no cuts' and 'cuts not searched for' are different answers."""
        import numpy as np

        m = Material(loop_sequence(), blank=True)
        got = motion.cuts(m.paths(), gray=lambda p: np.zeros((8, 8)))
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertIn("NOT SEARCHED", got["note"])

    def test_a_single_frame_is_not_a_clip(self):
        """The third outcome again, from the other end: nothing to compare."""
        got = motion.cuts([], gray=lambda p: None)
        self.assertEqual(got["outcome"], UNMEASURED)
        self.assertEqual(got["steps"], 0)


class SeamFrameSample(unittest.TestCase):
    """E3: the cut note lists a sample and says how big the sample is."""

    def _cuts(self, n_cuts):
        import numpy as np

        # One quiet step, then a jump, repeated: the median stays at the quiet
        # step, so every jump clears the bar and is counted as a cut.
        steps = [1.0, 1.0, 100.0] * n_cuts
        values, acc = [0.0], 0.0
        for d in steps:
            acc += d
            values.append(acc)

        def gray(path):
            return np.full((2, 2), values[int(path)], dtype=float)

        return motion.cuts([str(i) for i in range(len(values))], gray=gray)

    def test_a_clipped_list_of_seam_frames_says_how_many_of_how_many(self):
        got = self._cuts(15)
        self.assertEqual(len(got["cuts"]), 15)
        self.assertIn("first 10 of 15", got["note"])

    def test_a_list_that_fits_is_not_announced_as_a_sample_of_something_bigger(self):
        got = self._cuts(3)
        self.assertEqual(len(got["cuts"]), 3)
        self.assertIn("first 3 of 3", got["note"])

    def test_a_clip_without_cuts_says_nothing_about_seam_frames(self):
        import numpy as np

        got = motion.cuts([str(i) for i in range(6)], gray=lambda p: np.full((2, 2), float(p)))
        self.assertEqual(got["cuts"], [])
        self.assertNotIn("seam frames", got["note"])


if __name__ == "__main__":
    unittest.main()
