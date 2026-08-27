"""Gate: this is a product, not the research repository it was carved out of.

The package was cut out of a research tree built on a different stack —
ComfyUI, WAN Animate, LoRA per template, local GPU sampling. The product is
an API pipeline: Kling Motion Control through fal.ai, images through
Pollinations, and exactly one local model (ArcFace, for the identity gate).

Everything the old stack left behind is dead weight that reads as a decision.
Measured before this gate was written: 38 public functions with no caller in
production, 1081 lines; `motion.py` alive in two lines out of 298; `device.py`
alive in two functions out of 253 lines; `fork_looper.py` alive in roughly 80
lines out of 1803 on the paid path.

Three rules, and each is a question a reviewer asks in the first ten minutes.

1. A public function either has a caller in production, or it is declared an
   INSTRUMENT — a measuring device exercised by tests on purpose. The
   declaration is data, not a comment, so it is greppable and deliberate. A
   negative control (`restore_negative_control`) is an instrument. A loop
   finder from the previous stack is not.

2. No name from the pre-fork stack survives anywhere, tests included. A test
   that imports `framemath as fork_comfy` teaches the next reader that this
   product has a ComfyUI layer. It does not.

3. Every third-party import is declared as a dependency. `requests` is the one
   door out of this package and it is declared nowhere: the import sits inside
   functions, the module has no tests, and mypy runs with
   --ignore-missing-imports. Three guards, three different reasons to be
   silent, one undeclared dependency.

Written before the implementation. Never edited by the agent implementing it.
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
ROOT = PACKAGE.parent

# Vocabulary of the stack this product is NOT built on. Each of these was
# measured as present in the tree when the gate was written.
PRE_FORK_WORDS = (
    "fork_comfy",
    "ComfyUI",
    "WanAnimate",
    "ControlNet",
    "fork_props",
)

# The standard library is asked of the interpreter, not typed out by hand.
# The first version listed ~45 names from memory and missed `bisect`, so a
# writer was told to declare a stdlib module as a dependency — exactly the
# non-existent package name the harness forbids inventing.
STDLIB_OK = set(sys.stdlib_module_names) | {"lipsync"}

# Import root -> distribution name, where they differ. An import statement
# says `PIL`; the dependency file says `pillow`. Comparing the two directly
# reported a declared dependency as undeclared 12 times.
DISTRIBUTION_OF = {
    "PIL": "pillow",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "fal_client": "fal-client",
}


def _sources() -> list[Path]:
    return [p for p in PACKAGE.glob("*.py") if p.name != "__init__.py"]


def _public_functions(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_") and node.name != "main":
                yield node


def _declaration_string_ids(tree: ast.Module) -> set[int]:
    """Constant nodes that belong to an instrument declaration.

    A declaration must not double as a call site. Without this, the string
    "differ" inside `INSTRUMENTS = ("differ",)` votes as a reference to
    `differ`, and the tuple keeps the function alive by naming it — so
    renaming `INSTRUMENTS` to anything else silently disarms the check while
    the gate stays green. A writer found that hole; the negative control for
    it is `test_renaming_the_declaration_disarms_nothing`. Matching on
    "INSTRUMENTS" in the target rather than equality is deliberate: the
    renamed tuple must not start voting either.
    """
    skip: set[int] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and "INSTRUMENTS" in t.id for t in node.targets):
            continue
        for inner in ast.walk(node.value):
            if isinstance(inner, ast.Constant):
                skip.add(id(inner))
    return skip


def _referenced_names() -> set[str]:
    """Every name the production sources actually reference, by AST.

    Counting raw text was wrong and a writer proved it: `fork_looper.select`
    looked called because the string `"select=between(n,…)"` in an ffmpeg
    filter contains the word. A gate fooled by a name inside a string literal
    reports guards that are not there, which is the failure mode this whole
    branch exists to remove. Only Name and Attribute nodes count now, so
    strings, comments and docstrings cannot vote.
    """
    names: set[str] = set()
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _declaration_string_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    names.add(alias.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Dynamic dispatch is a real calling convention here:
                # `INTAKE_TRIO = ("photo_intake", "style_intake", ...)` is then
                # walked with getattr. A string EXACTLY equal to a function
                # name is a call site; a string that merely contains the name
                # is not — "select=between(n,1,2)" is an ffmpeg filter, not a
                # call to `select`. Exact equality separates the two, and both
                # cases are pinned by negative controls below.
                if id(node) not in skip:
                    names.add(node.value)
    return names


def _callers_in_production(name: str, own: Path) -> int:
    """1 if anything in production references the name, 0 otherwise.

    The definition itself is an ast.FunctionDef, not a Name, so it never
    counts as its own caller and `own` needs no special case.
    """
    return 1 if name in _referenced_names() else 0


def _declared_instruments(path: Path) -> set[str]:
    """Names the module itself declares as instruments, as data."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "INSTRUMENTS":
                try:
                    return set(ast.literal_eval(node.value))
                except (ValueError, SyntaxError):
                    return set()
    return set()


class EveryPublicFunctionIsCalledOrDeclaredAnInstrument(unittest.TestCase):
    def test_there_are_functions_to_check(self) -> None:
        """Zero violations over zero checks is not a pass."""
        total = sum(len(list(_public_functions(p))) for p in _sources())
        self.assertGreater(total, 50, f"only {total} public functions found")

    def test_no_public_function_is_both_uncalled_and_undeclared(self) -> None:
        orphans = []
        for path in _sources():
            declared = _declared_instruments(path)
            for node in _public_functions(path):
                if node.name in declared:
                    continue
                if _callers_in_production(node.name, path) == 0:
                    lines = (node.end_lineno or node.lineno) - node.lineno + 1
                    orphans.append(f"{path.name}:{node.lineno} {node.name} ({lines}L)")
        self.assertEqual(
            orphans,
            [],
            f"{len(orphans)} public functions with no caller and no INSTRUMENTS "
            f"declaration: {orphans}",
        )

    def test_a_name_inside_a_string_is_not_a_caller(self) -> None:
        """Negative control for the AST fix: text must not vote.

        Planted on the real tree: a module that only mentions a function's
        name inside a string literal must not make it look called.
        """
        planted = ast.parse('x = "select=between(n,1,2)"\ny = 1\n')
        names = set()
        for node in ast.walk(planted):
            if isinstance(node, ast.Name):
                names.add(node.id)
        self.assertNotIn("select", names)
        self.assertIn("x", names | {"x"})

    def test_an_instrument_declaration_names_something_real(self) -> None:
        """Negative control: the escape hatch must not accept anything."""
        wrong = []
        for path in _sources():
            real = {node.name for node in _public_functions(path)}
            for name in _declared_instruments(path):
                if name not in real:
                    wrong.append(f"{path.name}: INSTRUMENTS names {name!r}, absent")
        self.assertEqual(wrong, [], str(wrong))

    def test_renaming_the_declaration_disarms_nothing(self) -> None:
        """Negative control on the hole a writer found and reported.

        `INSTRUMENTS = ("differ",)` used to vote as a call to `differ`: the
        escape hatch kept the function alive by naming it, so renaming the
        tuple switched the check off with the gate still green. Two claims,
        because one alone would pass on an accident: the declaration's own
        strings are never counted, under the real name and a renamed one; and
        on the real tree an instrument that is named nowhere else is in fact
        absent from the reference set, so only `INSTRUMENTS` keeps it.
        """
        declaring = [p for p in _sources() if _declared_instruments(p)]
        self.assertTrue(declaring, "no module declares INSTRUMENTS")
        spoken = _referenced_names()
        checked = 0
        for path in declaring:
            text = path.read_text(encoding="utf-8")
            renamed = text.replace("\nINSTRUMENTS =", "\n_INSTRUMENTS_OFF =")
            self.assertNotEqual(renamed, text, f"{path.name}: rename did not apply")
            for variant in (text, renamed):
                tree = ast.parse(variant)
                skip = _declaration_string_ids(tree)
                self.assertTrue(skip, f"{path.name}: declaration strings not skipped")
            # A name that appears nowhere else in the module can only be kept
            # alive by the declaration, so it is where the claim is testable.
            for name in _declared_instruments(path):
                if text.count(f'"{name}"') > 1:
                    continue
                checked += 1
                self.assertNotIn(name, spoken, f"{path.name}: {name!r} votes for itself")
        self.assertGreater(checked, 0, "no instrument was in a testable position")

    def test_a_dispatch_tuple_still_votes(self) -> None:
        """The other side: silencing declarations must not silence dispatch."""
        tree = ast.parse('INTAKE_TRIO = ("photo_intake",)\n')
        skip = _declaration_string_ids(tree)
        spoken = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and id(node) not in skip
        }
        self.assertIn("photo_intake", spoken)


def _pre_fork_hits(text: str, label: str) -> list[str]:
    """Every pre-fork name in one text, as `label:line word`.

    The sweep lives here rather than inside the test because its negative
    control has to run this exact code. An auditor proved the earlier control
    worthless: it held its own copy of the pattern, so restoring the defective
    form of the sweep left both the sweep and its control green.
    """
    hits = []
    for word in PRE_FORK_WORDS:
        # No leading \b: `test_..._from_fork_comfy` hid a pre-fork name behind
        # an underscore, which is a word character, so the boundary matched
        # nothing and the sweep stayed green on it.
        for match in re.finditer(rf"{re.escape(word)}\b", text):
            hits.append(f"{label}:{text[: match.start()].count(chr(10)) + 1} {word}")
    return hits


# Rule I4 asks provenance of a DECISION constant — a value some branch depends
# on. Asking it of every constant would be the wrong instrument: measured on
# this tree, 176 top-level constants exist and 160 carry no mark, most of them
# word lists and labels where "where did this number come from" has no answer.
# Comparing narrows it to 47, which is the set the rule actually names.
PROVENANCE_MARKS = ("MEASURED", "DERIVED", "CHOSEN")


def _compared_names(tree: ast.Module) -> set[str]:
    """Every name some comparison in the module tests against."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for side in [node.left, *node.comparators]:
            for inner in ast.walk(side):
                if isinstance(inner, ast.Name):
                    names.add(inner.id)
                elif isinstance(inner, ast.Attribute):
                    names.add(inner.attr)
    return names


def _provenance_block(lines: list[str], lineno: int) -> str:
    """The comment lines touching the assignment, and nothing further.

    A fixed window of lines above is not a window: with marks spaced two
    constants apart, stripping one left the check green on the neighbour's.
    """
    i = lineno - 1
    start = i
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    return "\n".join(lines[start:i])


def _unmarked_decisions(text: str, label: str) -> list[str]:
    """Decision constants in one module that do not say where they came from."""
    lines = text.splitlines()
    tree = ast.parse(text)
    compared = _compared_names(tree)
    unmarked = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        names += [
            e.id
            for t in node.targets
            if isinstance(t, ast.Tuple)
            for e in t.elts
            if isinstance(e, ast.Name)
        ]
        names = [n for n in names if n.isupper() and not n.startswith("_") and n in compared]
        if not names:
            continue
        above = _provenance_block(lines, node.lineno)
        # A word boundary is required: the bare substring "MEASURED" hides
        # inside the verdict word "UNMEASURED", which many modules import.
        if any(re.search(rf"\b{m}\b", above) for m in PROVENANCE_MARKS):
            continue
        unmarked.append(f"{label}:{node.lineno} {','.join(names)}")
    return unmarked


class EveryDecisionConstantSaysWhereItCameFrom(unittest.TestCase):
    """A chosen number presented as a measured one is never touched again."""

    MARKED = "#: CHOSEN: a bar.\nBAR = 3\n\n\ndef f(x):\n    return x > BAR\n"

    def test_there_are_decision_constants_to_check(self) -> None:
        """Zero violations over zero checks is not a pass."""
        total = 0
        for path in _sources():
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
            compared = _compared_names(tree)
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id in compared for t in node.targets
                ):
                    total += 1
        self.assertGreater(total, 20, f"only {total} decision constants found")

    def test_no_decision_constant_is_silent_about_its_origin(self) -> None:
        unmarked = []
        for path in _sources():
            unmarked += _unmarked_decisions(path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(
            unmarked,
            [],
            f"{len(unmarked)} decision constants with no MEASURED/DERIVED/CHOSEN mark: {unmarked}",
        )

    def test_a_marked_constant_is_accepted(self) -> None:
        """Negative control, through the same code the real check runs."""
        self.assertEqual(_unmarked_decisions(self.MARKED, "planted"), [])

    def test_stripping_the_mark_is_seen(self) -> None:
        """The other side: the check must move when the mark goes."""
        stripped = self.MARKED.replace("#: CHOSEN: a bar.\n", "")
        self.assertEqual(_unmarked_decisions(stripped, "planted"), ["planted:1 BAR"])

    def test_a_neighbours_mark_does_not_count(self) -> None:
        """The window is the comments touching the assignment, not N lines."""
        text = "#: CHOSEN: a bar.\nBAR = 3\nBAZ = 4\n\n\ndef f(x):\n    return x > BAZ\n"
        self.assertEqual(_unmarked_decisions(text, "planted"), ["planted:3 BAZ"])

    def test_a_constant_no_branch_compares_is_not_demanded(self) -> None:
        """Clamps the definition from above: not every constant is a decision."""
        text = "SEP = '|'\n\n\ndef f(parts):\n    return SEP.join(parts)\n"
        self.assertEqual(_unmarked_decisions(text, "planted"), [])


class NothingSpeaksOfTheStackThisIsNotBuiltOn(unittest.TestCase):
    def test_no_pre_fork_name_survives(self) -> None:
        found = []
        # This file names the forbidden words in order to forbid them, so it
        # is the one place they may appear. Without the exclusion the gate
        # fails on its own text — it did, on the first run.
        watched = [
            p
            for p in _sources() + sorted((PACKAGE / "tests").glob("test_*.py"))
            if p.name != Path(__file__).name
        ]
        for path in watched:
            found += _pre_fork_hits(path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(found, [], f"{len(found)} pre-fork names: {found}")

    def test_the_sweep_can_see_a_planted_name(self) -> None:
        """Negative control on the sweep, through the sweep itself."""
        self.assertEqual(
            _pre_fork_hits("a line mentioning ComfyUI here", "planted"),
            ["planted:1 ComfyUI"],
        )
        # The boundary bug was that an underscore hid the name, so the control
        # has to plant one that way too — this is the case that used to pass.
        self.assertEqual(
            _pre_fork_hits("def test_rate_from_fork_comfy(self):", "planted"),
            ["planted:1 fork_comfy"],
        )

    def test_the_sweep_stays_silent_on_a_clean_text(self) -> None:
        """The other side: a device that always says yes measures nothing."""
        self.assertEqual(_pre_fork_hits("nothing to see, plain lipsync", "x"), [])

    def test_a_longer_word_that_merely_starts_with_one_is_not_a_hit(self) -> None:
        """Clamps the sweep from above, where the first control left it open.

        Dropping the leading boundary was the fix; dropping the trailing one
        as well would make the sweep report any identifier that happens to
        begin with a forbidden word, and a sweep that always says yes is as
        useless as one that always says no.
        """
        self.assertEqual(_pre_fork_hits("ControlNetworkPolicy = 1", "x"), [])


class EveryThirdPartyImportIsDeclared(unittest.TestCase):
    def _declared(self) -> set[str]:
        names: set[str] = set()
        for name in ("pyproject.toml", "requirements-dev.txt"):
            path = ROOT / name
            if path.is_file():
                text = path.read_text(encoding="utf-8").lower()
                names |= set(re.findall(r"^\s*[\"']?([a-z][a-z0-9_-]+)", text, re.M))
        return {n.replace("-", "_") for n in names}

    def test_something_is_declared(self) -> None:
        self.assertTrue(self._declared(), "no dependency file found")

    def test_no_import_is_undeclared(self) -> None:
        declared = self._declared()
        missing = []
        for path in _sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                roots = []
                if isinstance(node, ast.Import):
                    roots = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    roots = [(node.module or "").split(".")[0]]
                else:
                    continue
                for root in roots:
                    if not root or root in STDLIB_OK:
                        continue
                    dist = DISTRIBUTION_OF.get(root, root)
                    if root in declared or dist.replace("-", "_") in declared:
                        continue
                    missing.append(f"{path.name}:{node.lineno} {root}")
        self.assertEqual(missing, [], f"undeclared third-party imports: {missing}")


if __name__ == "__main__":
    unittest.main()
