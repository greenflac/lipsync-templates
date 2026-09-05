"""Zero violations out of zero checks is not a pass.

THE DEFECT, OBSERVED 2026-08-28 BEFORE THE FIX

`scripts/ingest_harvest.py --check` on an existing but empty harvest file:

    проверено 0
    расхождений 0
    уступлено разбору 0
    EXIT=0

Three steps of `scripts/check` run that command. A green light there could mean
"every harvested claim is applied" or "not one row was read", and nothing in the
output or the exit code told them apart — which is house rule R2 broken inside
the gate that exists to enforce it.

WHY A TEST AND NOT A COMMENT

The shape `return 1 if <violations> else 0` appears in five places in `scripts/`
(rule I7: grep for the shape before fixing one instance). Two of them count
something DATA-DRIVEN that can genuinely reach zero — `ingest_harvest.py`, wired
into the gate three times, and `ab_run.py`, which spends money. The other three
(`merge_model_ids.py` twice, `read_sources.py` once) count the length of a
module-level table, which is never empty unless somebody deletes the table, so
they are the same shape but not the same defect; this test says so rather than
leaving a reader to re-derive it.

Expected exit codes are literals here, not imports from the scripts (rule T2).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HARVEST = REPO / "scripts" / "ingest_harvest.py"

#: The house's three outcomes, written out so a reader does not have to know
#: them, and so a change to the convention shows up as an edit to this list.
PASS_CODE = 0
FAIL_CODE = 1
UNMEASURED_CODE = 2


def _run(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(HARVEST), "--check", "--path", str(path)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


class ZeroChecksIsNotAPass(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def test_an_empty_but_present_file_is_COULD_NOT_MEASURE(self) -> None:
        """The defect itself. Before the fix this exited 0."""
        empty = self.tmp / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        out = _run(empty)
        assert out.returncode == UNMEASURED_CODE, out.stdout + out.stderr
        assert "проверено 0" in out.stdout
        assert "не смогли 1" in out.stdout

    def test_a_file_of_only_blank_lines_is_also_COULD_NOT_MEASURE(self) -> None:
        """Readable bytes, zero readable rows. `is_file()` cannot see this, which
        is why the file-missing branch alone did not cover it."""
        blanks = self.tmp / "blanks.jsonl"
        blanks.write_text("\n\n   \n", encoding="utf-8")
        out = _run(blanks)
        assert out.returncode == UNMEASURED_CODE, out.stdout + out.stderr

    def test_a_missing_file_stays_COULD_NOT_MEASURE(self) -> None:
        """The branch that already worked. Kept so a future edit cannot fix the
        new hole by collapsing this one into it."""
        out = _run(self.tmp / "nope.jsonl")
        assert out.returncode == UNMEASURED_CODE, out.stdout + out.stderr

    def test_THE_NEGATIVE_CONTROL_a_real_harvest_still_passes(self) -> None:
        """Rule I5. Without this, the fix could be "always return 2" and every
        assertion above would still be green while the gate measured nothing."""
        out = _run(REPO / "studio" / "knowledge" / "harvest_2026-08-27.jsonl")
        assert out.returncode == PASS_CODE, out.stdout + out.stderr
        assert "не смогли 0" in out.stdout
        assert "расхождений 0" in out.stdout

    def test_a_row_that_is_NOT_in_the_base_is_a_violation_not_an_unmeasured(self) -> None:
        """The other edge of the three: something WAS checked and it disagreed.
        Folding this into `could not measure` would hide a real divergence."""
        bad = self.tmp / "bad.jsonl"
        bad.write_text(
            '{"model": "no-such-model-9x7", "attribute": "max_seconds", '
            '"value": "999", "source_url": "https://example.invalid/nope"}\n',
            encoding="utf-8",
        )
        out = _run(bad)
        assert out.returncode == FAIL_CODE, out.stdout + out.stderr
        assert "проверено 1" in out.stdout
        assert "расхождений 1" in out.stdout


if __name__ == "__main__":
    unittest.main()
