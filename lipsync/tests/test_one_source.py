"""Gate: the package has one direction and one place for each fact.

Two properties of the whole tree, both mechanical, both currently violated.

**Acyclic imports.** Three cycles exist — `fork_e2e` with `fork_plan`,
`fork_e2e` with `fork_aesthetic`, `fork_plan` with `pollinations` — and every
one of them is held open by an import placed inside a function so the module
can still load. That works and it hides the shape: a reader cannot tell which
module is above which, and neither can a new caller. The cause is small and
worth naming, because it is what makes the fix small too: three prompt clauses
live in `fork_e2e` and are needed below it, and `pollinations` reaches into
`fork_plan` for one frame size.

A deferred import is a legitimate tool — for a heavy optional dependency, for
example. It stops being one when the only thing it defers is a cycle.

**One fact, one place.** `FRAME_SUFFIXES` is declared twice, as a set in one
module and a tuple in another; `MIN_VISIBILITY` is declared twice with the same
0.5. Both pass the test that matters: change one and the other must change, and
will not. `INSTRUMENTS` is excluded by name — it is a per-module declaration,
one per module by design, and a rule that cannot tell a convention from a
duplicate would be reporting noise.

Written before the implementation. Never edited by the agent implementing it.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent

#: Per-module declarations, one per module on purpose. Not duplicated knowledge.
PER_MODULE_BY_DESIGN = ("INSTRUMENTS", "EXIT_BY_OUTCOME")


def _module_names() -> set[str]:
    return {p.stem for p in PACKAGE.glob("*.py") if p.stem != "__init__"}


def _edges(source: dict[str, str]) -> dict[str, set[str]]:
    """module -> modules it imports, wherever the import is written.

    Function-level imports count. A cycle deferred into a function body is
    still a cycle; counting only module-level imports would report the tree
    acyclic precisely because someone worked around it.
    """
    mods = set(source)
    graph: dict[str, set[str]] = {}
    for name, text in source.items():
        tree = ast.parse(text)
        dep: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                if node.module in mods:
                    dep.add(node.module)
                dep |= {a.name for a in node.names if a.name in mods}
        graph[name] = dep - {name}
    return graph


def _cycles(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    """Every elementary cycle, each reported once, shortest first."""
    found: set[tuple[str, ...]] = set()

    def walk(node: str, path: list[str]) -> None:
        for nxt in sorted(graph.get(node, ())):
            if nxt in path:
                ring = path[path.index(nxt) :]
                found.add(tuple(sorted(ring)) if len(ring) > 1 else (nxt,))
            elif len(path) < 6:
                walk(nxt, [*path, nxt])

    for start in sorted(graph):
        walk(start, [start])
    return sorted(found, key=lambda c: (len(c), c))


def _literal_constants(source: dict[str, str]) -> dict[str, list[tuple[str, int]]]:
    """Public upper-case names assigned a literal, by name -> [(module, line)]."""
    seen: dict[str, list[tuple[str, int]]] = {}
    for name, text in source.items():
        for node in ast.parse(text).body:
            if not isinstance(node, ast.Assign):
                continue
            try:
                ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if not target.id.isupper() or target.id.startswith("_"):
                    continue
                if target.id in PER_MODULE_BY_DESIGN:
                    continue
                seen.setdefault(target.id, []).append((name, node.lineno))
    return seen


def _read() -> dict[str, str]:
    return {
        p.stem: p.read_text(encoding="utf-8")
        for p in sorted(PACKAGE.glob("*.py"))
        if p.stem != "__init__"
    }


class TheImportGraphHasOneDirection(unittest.TestCase):
    def test_there_are_edges_to_check(self) -> None:
        """Zero cycles over an empty graph is not a pass."""
        graph = _edges(_read())
        self.assertGreater(sum(len(v) for v in graph.values()), 20, str(graph))

    def test_no_module_imports_something_that_imports_it_back(self) -> None:
        rings = _cycles(_edges(_read()))
        self.assertEqual(
            rings, [], f"{len(rings)} import cycles: {[' <-> '.join(r) for r in rings]}"
        )

    def test_a_planted_cycle_is_seen(self) -> None:
        """Negative control, through the same finder the real check runs."""
        planted = {
            "a": "from .b import X\n",
            "b": "def f():\n    from .a import Y\n",
            "c": "from .a import Z\n",
        }
        self.assertEqual(_cycles(_edges(planted)), [("a", "b")])

    def test_a_one_way_chain_is_not_a_cycle(self) -> None:
        """The other side: a device that always says yes measures nothing."""
        chain = {"a": "from .b import X\n", "b": "from .c import Y\n", "c": "\n"}
        self.assertEqual(_cycles(_edges(chain)), [])


class OneFactLivesInOnePlace(unittest.TestCase):
    def test_there_are_constants_to_check(self) -> None:
        found = _literal_constants(_read())
        self.assertGreater(len(found), 50, f"only {len(found)} constants found")

    def test_no_name_is_declared_in_two_modules(self) -> None:
        twice = {
            name: places for name, places in _literal_constants(_read()).items() if len(places) > 1
        }
        listed = [
            f"{name}: " + ", ".join(f"{m}.py:{ln}" for m, ln in places)
            for name, places in sorted(twice.items())
        ]
        self.assertEqual(listed, [], f"{len(listed)} names declared twice: {listed}")

    def test_a_planted_duplicate_is_seen(self) -> None:
        """Negative control on the finder itself."""
        planted = {"a": "SIZE = 3\n", "b": "SIZE = 3\n"}
        self.assertEqual(sorted(_literal_constants(planted)["SIZE"]), [("a", 1), ("b", 1)])

    def test_a_per_module_declaration_is_not_a_duplicate(self) -> None:
        """Clamps the rule from above: a convention is not duplicated knowledge."""
        planted = {"a": "INSTRUMENTS = ('x',)\n", "b": "INSTRUMENTS = ('y',)\n"}
        self.assertNotIn("INSTRUMENTS", _literal_constants(planted))


if __name__ == "__main__":
    unittest.main()
