"""The contract gate: does it catch what the engine would catch, and refuse to guess?

Expected values here are LITERALS. Importing `WORDS_MIN` to assert against
`WORDS_MIN` would ride along with any change to it and pass in silence, which
is the one thing a guard must not do.
"""

from __future__ import annotations

import unittest

from studio.mcp.contract import BANDS, gate

# The engine's bands as of 2026-08-27, written out rather than imported. If the
# engine moves them, this test is SUPPOSED to fail and make somebody look.
WORDS_BAND = (9, 67)
CLAUSES_BAND = (1, 13)

CLEAN = (
    "a palette of ivory, slate and charcoal, low-key shadowed lighting, "
    "desaturated restrained colour, matte, photographic look"
)


class ContractGate(unittest.TestCase):
    def test_the_bands_are_the_engines_bands(self) -> None:
        assert BANDS["words"][:2] == WORDS_BAND
        assert BANDS["clauses"][:2] == CLAUSES_BAND

    def test_a_clean_look_prompt_passes_and_says_how_many_checks_ran(self) -> None:
        out = gate(CLEAN)
        assert out["outcome"] == "pass"
        assert out["checked"] == 3
        assert out["violations"] == 0
        assert out["leak"] == []

    def test_naming_the_subject_fails_and_names_every_word_found(self) -> None:
        out = gate("a woman with long hair wearing a red dress, soft light, matte finish")
        assert out["outcome"] == "fail"
        assert out["broke"] == ["subject_zone"]
        assert set(out["leak"]) >= {"woman", "hair", "wearing", "dress"}

    def test_an_empty_prompt_is_could_not_measure_and_never_pass(self) -> None:
        for blank in ("", "   ", "\n"):
            out = gate(blank)
            assert out["outcome"] == "could not measure"
            assert out["checked"] == 0, "zero checks must never be reported as a pass"

    def test_both_edges_and_the_middle_of_the_word_band(self) -> None:
        # 8 words: one under the floor. 9: exactly on it. 24: the corpus median.
        under = " ".join(["matte"] * 8)
        on_floor = " ".join(["matte"] * 9)
        middle = " ".join(["matte"] * 24)
        on_ceiling = " ".join(["matte"] * 67)
        over = " ".join(["matte"] * 68)

        assert gate(under)["outcome"] == "fail"
        assert gate(on_floor)["outcome"] == "pass"
        assert gate(middle)["outcome"] == "pass"
        assert gate(on_ceiling)["outcome"] == "pass"
        assert gate(over)["outcome"] == "fail"

    def test_over_the_clause_ceiling_fails(self) -> None:
        # 14 clauses, each two words, so the word band stays satisfied and the
        # clause band is the only thing that can break.
        text = ", ".join(["matte finish"] * 14)
        out = gate(text)
        assert out["outcome"] == "fail"
        assert "clauses" in out["broke"]

    def test_two_broken_rules_are_counted_as_two_not_one(self) -> None:
        out = gate("a woman")
        assert out["outcome"] == "fail"
        assert out["violations"] == 2
        assert set(out["broke"]) == {"subject_zone", "words"}

    def test_a_violation_is_returned_unrepaired(self) -> None:
        dirty = "a woman in silk, matte finish, soft light, low-key shadow, film grain"
        out = gate(dirty)
        assert out["outcome"] == "fail"
        assert out["prompt"] == dirty, "the gate must not trim a prompt into shape"


if __name__ == "__main__":
    unittest.main()
