"""Gate: the package holds the product's operations and nothing else.

A module with a command-line entry point is a thing an operator can run. That
makes the set of entry points a statement about what this package IS, and it
should be readable in one list rather than discovered by grepping for `main`.

The list below is the product's operations. It lives in the gate, not beside
the code, for the same reason a judge does not take instructions from the
defendant: a module cannot legitimise itself by declaring itself.

The case that produced this gate. `fork_looper` carried an entry point
described as "Select loops in the driving: rank seams and write GIFs" — a tool
for choosing which stretch of the driving clip to use. The product does not
choose that stretch: the operator names it with `--window`, and the pipeline
checks and cuts what it was given. So the module was 1633 lines of function
bodies of which the pipeline reaches 66, and the rest answered a question the
product does not ask.

Why the existing dead-weight gate did not see it: that gate asks whether a
function has a caller, and inside such a module the functions call each other.
A self-referential island passes a check written for orphans. This gate asks a
different question — not "is anything calling it" but "is this one of the
things we do" — and the two together leave no room for a subsystem to live in
the package unnoticed.

Written before the implementation. Never edited by the agent implementing it.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent

#: The product's operations, each a thing an operator runs on purpose.
#: `fork_e2e` is the pipeline; `fork_batch` runs it over a matrix; `fork_finish`
#: is the final assembly on its own; `fork_video` is the decoding utility every
#: stage borrows; `fork_aesthetic_publish` is the owner's own step, added by the
#: contract of 01.09.2026 — decision 7 makes publishing a separate command a
#: person runs after looking at the draft, so it is an operation of the product
#: and not a tool that wandered in. Anything else with an entry point is.
DECLARED_OPERATIONS = (
    "fork_aesthetic_publish",
    "fork_batch",
    "fork_e2e",
    "fork_finish",
    "fork_video",
)


def _has_entry_point(text: str) -> bool:
    """True when the module can be launched: it defines `main`."""
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
        for node in ast.parse(text).body
    )


def _entry_points(source: dict[str, str]) -> list[str]:
    return sorted(name for name, text in source.items() if _has_entry_point(text))


def _read() -> dict[str, str]:
    return {
        p.stem: p.read_text(encoding="utf-8")
        for p in sorted(PACKAGE.glob("*.py"))
        if p.stem != "__init__"
    }


class EveryEntryPointIsAnOperationOfThisProduct(unittest.TestCase):
    def test_there_are_entry_points_to_check(self) -> None:
        """Zero undeclared entry points over zero entry points is not a pass."""
        found = _entry_points(_read())
        self.assertGreater(len(found), 2, f"only {found} entry points found")

    def test_no_entry_point_is_undeclared(self) -> None:
        stray = [n for n in _entry_points(_read()) if n not in DECLARED_OPERATIONS]
        self.assertEqual(
            stray,
            [],
            f"{len(stray)} runnable modules that are not operations of this "
            f"product: {stray}. Either the product gained an operation and this "
            f"gate should say so, or a tool is living in the package.",
        )

    def test_every_declared_operation_still_exists(self) -> None:
        """The other side: a list naming things that are gone is not a list."""
        present = set(_read())
        missing = [n for n in DECLARED_OPERATIONS if n not in present]
        self.assertEqual(missing, [], f"declared but absent: {missing}")

    def test_a_planted_tool_is_seen(self) -> None:
        """Negative control, through the same finder the real check uses."""
        planted = {
            "fork_e2e": "def main(argv=None):\n    return 0\n",
            "loop_picker": "def main(argv=None):\n    return 0\n",
            "quiet": "def helper():\n    return 1\n",
        }
        found = _entry_points(planted)
        self.assertEqual(found, ["fork_e2e", "loop_picker"])
        self.assertEqual([n for n in found if n not in DECLARED_OPERATIONS], ["loop_picker"])

    def test_a_module_without_an_entry_point_is_not_a_tool(self) -> None:
        """Clamps it from above: a library is not a stray operation."""
        self.assertEqual(_entry_points({"lib": "def measure(x):\n    return x\n"}), [])


if __name__ == "__main__":
    unittest.main()
