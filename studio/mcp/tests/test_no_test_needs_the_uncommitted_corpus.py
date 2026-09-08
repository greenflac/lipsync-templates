"""No test may depend on a file this repository does not commit.

THE DEFECT, THREE TIMES IN TWO DAYS

The prompt corpora — `gallery_prompts.jsonl` (4601 rows) and
`civitai_prompts.jsonl` (473) — are deliberately not committed: the repository
is public and the material is a third party's. Every machine that clones it
therefore has a DIFFERENT corpus from the one the author was looking at, and a
test that builds the real index passes here and fails in CI with "index holds no
examples".

That is not hypothetical. It has now happened three times:

  * `probe` tests patched the environment without `clear=True`, so a real
    KLING_KEY leaked in and the test depended on the machine;
  * `load_craft_records` defaulted to the real directory, so two tests that
    disable every source silently got one back — "no sources" became "one";
  * the knowledge-lane tests built the real index and were pushed green from a
    machine that has the corpora, straight into a red CI.

Each was fixed where it was found. This is the fix for the SHAPE (rule I7): a
test that calls `build_index()` without saying where its corpus comes from is
the defect, and it is now caught by reading the source rather than by waiting
for CI to disagree with a laptop.

WHY AN AST WALK AND NOT A CONVENTION

Because a convention is a thing people remember, and all three of the above were
written by somebody who knew the rule. This reads what the code actually does.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

#: Sources whose files are gitignored. A test that leaves one unset gets whatever
#: is on the machine — which is the whole problem.
CORPUS_PARAMS = frozenset({"gallery_prompts", "community_prompts", "craft_records"})

#: Test files that may call `build_index()` bare. Empty on purpose: every entry
#: here would be a test that behaves differently on two machines, and the point
#: of the list is that adding to it has to be an argument somebody makes out
#: loud, not something that happens by forgetting.
ALLOWED: frozenset[str] = frozenset()


def _test_files() -> list[Path]:
    return sorted(
        p
        for d in ("studio/tests", "studio/mcp/tests", "studio/selfrag/tests")
        for p in (REPO / d).glob("test_*.py")
    )


class NoTestReadsWhateverIsOnTheMachine(unittest.TestCase):
    def test_every_build_index_call_in_a_test_names_its_corpus(self) -> None:
        offenders: list[str] = []
        checked = 0
        for path in _test_files():
            if path.name in ALLOWED:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name != "build_index":
                    continue
                checked += 1
                named = {kw.arg for kw in node.keywords if kw.arg}
                if not (CORPUS_PARAMS & named):
                    offenders.append(
                        f"{path.relative_to(REPO)}:{node.lineno} — build_index() без "
                        "указания корпуса: на машине с корпусом зелёный, в CI красный"
                    )
        # Rule R2: zero violations out of zero calls is not a pass. If this ever
        # finds nothing to look at, the walk has broken, not the codebase.
        assert checked > 0, "ни одного вызова build_index не найдено — обход сломан"
        assert not offenders, "\n".join(offenders)

    def test_THE_NEGATIVE_CONTROL_the_walk_can_actually_see_a_violation(self) -> None:
        """Rule I5. Without this, a walk that matched nothing would report a
        clean codebase — which is exactly how a check stops checking."""
        source = "build_index(core_rules=x)\nbuild_index(gallery_prompts=y)\n"
        tree = ast.parse(source)
        bare = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "build_index"
            and not (CORPUS_PARAMS & {kw.arg for kw in node.keywords if kw.arg})
        ]
        assert len(bare) == 1, "обход не отличает вызов с корпусом от вызова без него"


if __name__ == "__main__":
    unittest.main()
