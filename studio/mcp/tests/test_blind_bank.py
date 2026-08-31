"""Blinding: does the shuffle actually shuffle, and is it repeatable?

Fixtures are literals (rule T2) and nothing here reads the case bank, which is
gitignored — a test that needs it passes here and fails in CI.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "blind_bank", Path(__file__).resolve().parents[3] / "scripts" / "blind_bank.py"
)
assert _SPEC and _SPEC.loader
blind = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(blind)


def _cases(n: int) -> list[dict]:
    """Half video with a strip, half pictures shown as themselves."""
    out = []
    for i in range(n):
        if i % 2:
            out.append(
                {
                    "case_id": f"kv-{i}",
                    "media": "video",
                    "path": f"work/casebank/kv-{i}.mp4",
                    "sheet": f"work/casebank/kv-{i}_sheet.jpg",
                }
            )
        else:
            out.append(
                {"case_id": f"of-{i}", "media": "image", "path": f"work/casebank/of-{i}.jpg"}
            )
    return out


class TheOrderMustNotAnswerTheQuestion(unittest.TestCase):
    def test_the_blind_order_differs_from_the_bank_order(self) -> None:
        """Sorted by source, position alone gives the answer away."""
        cases = _cases(20)
        got = [real for _, real in blind.plan(cases)]
        assert got != [c["case_id"] for c in cases]
        assert sorted(got) == sorted(c["case_id"] for c in cases)

    def test_the_same_seed_gives_the_same_order(self) -> None:
        """Repeatable, or a claimed sign cannot be re-tested on the same cases."""
        cases = _cases(20)
        assert blind.plan(cases, seed=7) == blind.plan(cases, seed=7)

    def test_a_different_seed_gives_a_different_order(self) -> None:
        """The negative control on the seed: if the shuffle ignored it, the two
        halves of the test above would both pass on a constant order."""
        cases = _cases(20)
        assert blind.plan(cases, seed=7) != blind.plan(cases, seed=8)

    def test_blind_ids_are_sequential_and_carry_no_source(self) -> None:
        ids = [b for b, _ in blind.plan(_cases(12))]
        assert ids[0] == "case-001"
        assert ids[-1] == "case-012"
        assert not any("kv" in i or "of" in i for i in ids)


class WhatTheReaderIsShown(unittest.TestCase):
    def test_a_clip_is_shown_as_its_strip_never_as_the_mp4(self) -> None:
        """An `.mp4` beside a `.jpg` separates video from image for free."""
        case = {"case_id": "kv-1", "media": "video", "path": "a/kv-1.mp4", "sheet": "a/kv-1_s.jpg"}
        assert blind.shown_file(case) == "a/kv-1_s.jpg"

    def test_a_clip_with_no_strip_is_not_shown_at_all(self) -> None:
        """The negative control: falling back to the path would hand a reader an
        .mp4 and undo the whole point."""
        assert blind.shown_file({"case_id": "kv-2", "media": "video", "path": "a/kv-2.mp4"}) == ""

    def test_a_picture_is_shown_as_itself(self) -> None:
        assert blind.shown_file({"case_id": "of-1", "media": "image", "path": "a/of-1.jpg"}) == (
            "a/of-1.jpg"
        )

    def test_an_unshowable_case_is_left_out_of_the_plan(self) -> None:
        cases = _cases(4) + [{"case_id": "kv-broken", "media": "video", "path": "a/x.mp4"}]
        assert "kv-broken" not in [real for _, real in blind.plan(cases)]


if __name__ == "__main__":
    unittest.main()
