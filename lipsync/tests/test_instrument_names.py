"""Gate: the report names the device that ran, not the device that imported.

An external audit planted a `creative_eval` that imports and then throws. The
run reported `creative_eval.style.similarity (external, shipped)` while the
number had in fact come from `palette_similarity`, the coarser fallback, and
the exception text — `model weights corrupt: checksum mismatch on style.bin`
— was discarded whole by a bare `except`. Nothing anywhere said a fallback
had happened.

That is the shape rule S13 names: a repair that hides a breakage. It is worse
than a plain bug because it is silent and self-confirming — every later run
reads the same instrument name and the numbers look comparable when they are
not. The tests that existed covered "the package is absent" and "the package
is present"; the case that ships is "present and broken", and it was the one
case nobody wrote.

Two claims here, and both are needed. The name must follow what executed, and
the reason a device dropped out must survive into the report; a fallback that
is named but unexplained is only half a report, and the half that is missing
is the one that says what to fix.

Written before the implementation. Never edited by the agent implementing it.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lipsync import fork_e2e as E  # noqa: E402

BOOM = "model weights corrupt: checksum mismatch on style.bin"
FALLBACK = "palette_similarity"
EXTERNAL = "creative_eval"


class _Planted:
    """Install a `creative_eval.style` whose `similarity` behaves as told."""

    def __init__(self, behaviour) -> None:
        self.behaviour = behaviour
        self.saved: dict[str, types.ModuleType | None] = {}

    def __enter__(self):
        pkg = types.ModuleType("creative_eval")
        style = types.ModuleType("creative_eval.style")
        style.similarity = self.behaviour
        pkg.style = style
        for name, mod in (("creative_eval", pkg), ("creative_eval.style", style)):
            self.saved[name] = sys.modules.get(name)
            sys.modules[name] = mod
        return self

    def __exit__(self, *exc) -> None:
        for name, mod in self.saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


def _throws(*_a, **_k):
    raise RuntimeError(BOOM)


def _works(*_a, **_k):
    return 0.9123


class TheNameFollowsWhatRan(unittest.TestCase):
    def _report(self, left, right) -> tuple[float | None, str]:
        """The value and the name the report would carry for it.

        Read through whatever the module offers so the gate does not dictate
        the shape of the fix: a pair returned together, or a name recorded by
        the measurement, are both acceptable answers.
        """
        value = E.shipped_similarity(left, right)
        if isinstance(value, tuple):
            return value[0], str(value[1])
        return value, E.similarity_source()

    def setUp(self) -> None:
        self.a = Path(__file__).resolve().parent.parent.parent / "assets"
        pngs = sorted(self.a.glob("*.png"))
        if len(pngs) < 2:
            self.skipTest("no two images in assets to compare")
        self.left, self.right = pngs[0], pngs[1]

    def test_a_broken_external_is_not_named_as_the_source(self) -> None:
        """The case that ships, and the one nobody had written."""
        with _Planted(_throws):
            value, name = self._report(self.left, self.right)
        self.assertNotIn(
            EXTERNAL,
            name,
            f"the number came from the fallback, the report said {name!r}",
        )
        self.assertIn(FALLBACK, name, f"the fallback is not named: {name!r}")
        self.assertIsNotNone(value, "no number was produced at all")

    def test_the_reason_the_external_dropped_out_is_not_discarded(self) -> None:
        """A named fallback with no reason does not say what to fix."""
        with _Planted(_throws):
            _, name = self._report(self.left, self.right)
        self.assertIn(
            BOOM,
            name,
            f"the exception text was thrown away; the report says {name!r}",
        )

    def test_a_working_external_is_named_and_is_the_one_that_answered(self) -> None:
        """Negative control: the check must not simply always say fallback."""
        with _Planted(_works):
            value, name = self._report(self.left, self.right)
        self.assertIn(EXTERNAL, name, f"the working external is not named: {name!r}")
        self.assertNotIn(BOOM, name)
        self.assertIsNotNone(value)
        self.assertAlmostEqual(float(value or 0.0), 0.9123, places=4)

    def test_an_absent_external_still_reads_as_the_fallback(self) -> None:
        """The other side: absence and breakage are both fallbacks, and the
        older of the two answers must not regress while the newer is fixed."""
        saved = {n: sys.modules.get(n) for n in ("creative_eval", "creative_eval.style")}
        for n in saved:
            sys.modules[n] = None  # type: ignore[assignment]
        try:
            _, name = self._report(self.left, self.right)
        finally:
            for n, mod in saved.items():
                if mod is None:
                    sys.modules.pop(n, None)
                else:
                    sys.modules[n] = mod
        self.assertIn(FALLBACK, name, f"absent external is not named: {name!r}")
        self.assertNotIn(EXTERNAL, name)


if __name__ == "__main__":
    unittest.main()
