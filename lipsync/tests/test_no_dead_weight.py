"""Gate: nothing in the package claims to exist without doing anything.

Found while writing the interview course, every one of them by grep in under a
minute — which is exactly how a reviewer will find them:

  START_MIN_FACE_PX      one occurrence in the whole tree: its own definition
  KLING_PRO_PRICE_USD    a duplicate of KLING_PRO_PRICE_3S_USD, never read
  arcface_drift          96 lines, zero callers, a second implementation of
                         `distances` with a different default
  face_embedding         zero callers
  face_attributes        zero callers
  cosine_distance        docstring says "unit-tested"; there is no test file

A dead name is worse than no name: it reads as a decision that was made, so the
next person reasons from it. The course's honest answer to "why is this here"
cannot be "I forgot", so the code stops saying it.

The documented command is guarded too. README tells the reader to run
`discover -s lipsync/tests`, and that command fails — 645 tests collected and
an import error. A reviewer runs what the README says, not what works.

Written before the implementation. Never edited by the agent implementing it.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
ROOT = PACKAGE.parent

# Names the course found dead. Each must be gone, or wired to a caller.
FOUND_DEAD = (
    "START_MIN_FACE_PX",
    "KLING_PRO_PRICE_USD",
    "arcface_drift",
    "face_embedding",
    "face_attributes",
)


def _sources() -> list[Path]:
    return [p for p in PACKAGE.glob("*.py") if p.name != "__init__.py"]


def _occurrences(name: str, *, tests: bool = False) -> int:
    """How many times the name appears in package sources.

    `tests=True` counts the test files too. The distinction matters and the
    first version of this gate got it wrong: a constant read ONLY by a test is
    not dead weight, it is measured evidence pinned by a literal — for example
    `assertGreater(STYLE_HIT_REJECTED, STYLE_HIT_REFERENCE)`, the record that
    the rejected styliser scored higher and was rejected by eye anyway.
    Counting sources alone reported five such constants as "never read" and
    would have had them deleted. The writer refused and reported instead.
    """
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    files = list(_sources())
    if tests:
        files += sorted((PACKAGE / "tests").glob("test_*.py"))
    return sum(len(pattern.findall(p.read_text(encoding="utf-8"))) for p in files)


class NoNameIsDeclaredAndNeverUsed(unittest.TestCase):
    def test_the_names_the_course_found_dead_are_gone_or_wired(self) -> None:
        still_dead = {name: _occurrences(name) for name in FOUND_DEAD if _occurrences(name) == 1}
        self.assertEqual(
            still_dead,
            {},
            "these names appear exactly once in the package — their own "
            f"definition, and nothing else: {still_dead}",
        )

    def test_the_sweep_can_still_see_a_dead_name(self) -> None:
        """Negative control: the instrument must be able to say no."""
        marker = "ZZ_DEFINITELY_NOT_IN_THIS_PACKAGE"
        self.assertEqual(_occurrences(marker), 0)

    def test_no_new_module_level_constant_is_declared_and_unused(self) -> None:
        offenders = []
        for path in _sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    name = target.id
                    if not name.isupper() or name.startswith("_"):
                        continue
                    # Dead means read by NOBODY, tests included. A constant
                    # that only a test reads is evidence, not weight.
                    if _occurrences(name, tests=True) == 1:
                        offenders.append(f"{path.name}:{node.lineno} {name}")
        self.assertEqual(
            offenders,
            [],
            f"module-level constants read by nothing at all, tests included: {offenders}",
        )

    def test_a_constant_only_a_test_reads_is_not_called_dead(self) -> None:
        """Negative control for the fix above: evidence must survive the sweep."""
        pinned = "STYLE_HIT_REFERENCE"
        self.assertEqual(
            _occurrences(pinned),
            1,
            f"{pinned} is expected to be read only by tests",
        )
        self.assertGreater(
            _occurrences(pinned, tests=True),
            1,
            f"{pinned} must be visible as read once tests are counted",
        )


class ADocstringDoesNotClaimATestThatDoesNotExist(unittest.TestCase):
    def test_nothing_claims_to_be_unit_tested_without_a_test_file(self) -> None:
        claimers = []
        for path in _sources():
            if "unit-tested" not in path.read_text(encoding="utf-8"):
                continue
            expected = PACKAGE / "tests" / f"test_{path.stem}.py"
            if not expected.is_file():
                claimers.append(f"{path.name} claims unit-tested, no {expected.name}")
        self.assertEqual(claimers, [], str(claimers))


# The subprocess below runs the whole suite, which collects THIS module again.
# Without a guard that is unbounded recursion: the first version of this gate
# hung on exactly that, and the hang is the evidence. The child sets the
# variable, so the child skips instead of spawning a grandchild.
README_TEXT = (ROOT / "README.md").read_text(encoding="utf-8")
_INNER = "LIPSYNC_GATE_INNER_RUN"


class TheDocumentedCommandRuns(unittest.TestCase):
    """A reviewer runs what the README says, not what works."""

    def setUp(self) -> None:
        if os.environ.get(_INNER):
            self.skipTest("inner run: the outer gate already checks this")

    def _commands(self) -> list[str]:
        return re.findall(r"^(python3?\s+-m\s+unittest[^\n]*)$", README_TEXT, re.MULTILINE)

    def test_the_readme_documents_a_command(self) -> None:
        """Zero violations over zero checks is not a pass."""
        self.assertTrue(self._commands(), "README documents no test command")

    def test_every_documented_command_collects_the_whole_suite(self) -> None:
        failures: list[str] = []
        ran: list[int] = []
        for command in self._commands():
            # Anchored, and once: the two chained replaces used to substitute
            # into their own output whenever the running interpreter was named
            # `python` (the name `scripts/check` uses), producing
            # `/usr/local/bin//usr/local/bin/python` and exit 127 — CI red on
            # a defect in the gate, not in the product.
            argv = re.sub(r"^python3?\b", shlex.quote(sys.executable), command, count=1)
            done = subprocess.run(
                argv,
                shell=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=900,
                env=dict(os.environ, **{_INNER: "1"}),
            )
            tail = (done.stderr or "") + (done.stdout or "")
            match = re.search(r"Ran (\d+) tests?", tail)
            if done.returncode != 0 or match is None:
                # The whole text, not a slice of it: a diagnosis was once
                # made from a truncated error and the cause was in the part
                # that had been cut off.
                failures.append(f"{command!r} exited {done.returncode}\n{tail.strip()}")
                continue
            if "FAILED" in tail or "Error" in tail.split("\n")[-6:][0]:
                failures.append(f"{command!r} did not pass:\n{tail.strip()}")
                continue
            ran.append(int(match.group(1)))
        self.assertEqual(failures, [], str(failures))
        self.assertTrue(ran, "no command produced a count")
        # The README quotes the run twice, once per language. A quoted figure
        # is a copy of something the suite already knows, and both copies had
        # already drifted — 917 against a real 979 — by the time an auditor
        # looked. Comparing them against the run is what stops the drift.
        quoted = re.findall(r"^Ran (\d+) tests?", README_TEXT, re.MULTILINE)
        self.assertTrue(quoted, "README quotes no run")
        stale = [n for n in quoted if int(n) != ran[0]]
        self.assertEqual(stale, [], f"README quotes {stale}, the suite ran {ran[0]}")


if __name__ == "__main__":
    unittest.main()
