"""The scorer: can the number it prints be trusted, and can it be red?

Four ways a validation score lies, and a test for each. Every fixture is written
here, so nothing needs the case bank — which is gitignored, and a test that
needs it passes on this machine and fails in CI.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from lipsync.fork_identity import PASS, UNMEASURED

_SPEC = importlib.util.spec_from_file_location(
    "score_validation", Path(__file__).resolve().parents[3] / "scripts" / "score_validation.py"
)
assert _SPEC and _SPEC.loader
scorer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scorer)


def _case(cid: str, model: str, *, source: str = "openfake", ok: bool = False) -> dict:
    return {
        "case_id": cid,
        "source": source,
        "commercial_ok": ok,
        "truth": {"model": model} if source == "openfake" else {"kling_version": model},
    }


def _answer(cid: str, said: str | None, *, recognised: bool = False) -> dict:
    if said is None:
        return {"case_id": cid, "outcome": "не смогли", "guess": {}, "recognised": recognised}
    return {
        "case_id": cid,
        "outcome": "назвал",
        "guess": {"exact": said, "family": said},
        "confidence": 0.6,
        "recognised": recognised,
    }


class GuessingCannotInflateTheNumber(unittest.TestCase):
    def test_could_not_measure_is_counted_apart_and_never_as_wrong(self) -> None:
        """The first way a score lies. A reader pushed to answer will answer,
        and with a dozen candidates a coin-flip lands 8% of the time. Refusing
        has to be free, or the bench teaches confidence instead of reading."""
        cases = [_case("a", "veo-3"), _case("b", "sora-2"), _case("c", "midjourney-7")]
        answers = [_answer("a", "veo-3"), _answer("b", None), _answer("c", None)]
        out = scorer.score(cases, answers)
        assert out["overall"]["answered"] == 1
        assert out["overall"]["could_not"] == 2
        # One answered, one right: the RATE is over what was answered, and the
        # refusals sit beside it rather than inside it.
        assert out["overall"]["family_rate"] == 1.0
        assert out["unmeasured"] == 2

    def test_a_small_bank_returns_COULD_NOT_MEASURE_not_a_percentage(self) -> None:
        """A rate over three cases is a rumour. The instrument says so itself
        rather than printing a number somebody will quote."""
        cases = [_case(str(i), "veo-3") for i in range(5)]
        answers = [_answer(str(i), "veo-3") for i in range(5)]
        out = scorer.score(cases, answers)
        assert out["outcome"] == UNMEASURED, out["note"]
        assert "слух" in out["note"]

    def test_enough_answers_make_it_measurable(self) -> None:
        """The other edge: the floor must let a real run through, or it is not a
        floor, it is a wall."""
        cases = [_case(str(i), "veo-3") for i in range(scorer.MIN_ANSWERED)]
        answers = [_answer(str(i), "veo-3") for i in range(scorer.MIN_ANSWERED)]
        out = scorer.score(cases, answers)
        assert out["outcome"] == PASS, out["note"]


class RecognitionIsNotReading(unittest.TestCase):
    def test_cases_the_reader_simply_remembered_are_scored_apart(self) -> None:
        """A famous picture recalled from memory is a correct answer and not a
        READ one. If the two numbers differ, the honest one excludes memory."""
        cases = [_case("a", "veo-3"), _case("b", "sora-2")]
        answers = [_answer("a", "veo-3", recognised=True), _answer("b", "midjourney-7")]
        out = scorer.score(cases, answers)
        assert out["узнал_по_памяти"] == 1
        assert out["overall"]["family_rate"] == 0.5
        assert out["без_узнавания"]["family_rate"] == 0.0


class TheLicenceChangesTheShapeOfTheReport(unittest.TestCase):
    def test_restricted_and_clean_populations_are_reported_apart(self) -> None:
        """The owner's ruling: restricted material is used and NAMED. A flag
        somebody might notice is not enough — the split is structural."""
        cases = [
            _case("a", "veo-3"),  # non-commercial
            _case("b", "1.5", source="kling", ok=True),  # clean
        ]
        answers = [_answer("a", "veo-3"), _answer("b", "kling-1.5")]
        out = scorer.score(cases, answers)
        assert out["ограниченные_non_commercial"]["cases"] == 1
        assert out["коммерчески_чистые"]["cases"] == 1

    def test_a_bank_with_no_restricted_cases_reports_zero_not_absence(self) -> None:
        """The negative control on the flag: if the restricted tally vanished
        when empty, a reader could not tell 'none' from 'not checked'."""
        cases = [_case("b", "1.5", source="kling", ok=True)]
        out = scorer.score(cases, [_answer("b", "kling-1.5")])
        assert out["ограниченные_non_commercial"]["cases"] == 0


class TheBlindingMapIsHowTheHalvesMeet(unittest.TestCase):
    def test_an_answer_under_a_blind_id_finds_its_truth(self) -> None:
        cases = [_case("of-real", "veo-3")]
        out = scorer.score(cases, [_answer("case-001", "veo-3")], {"case-001": "of-real"})
        assert out["overall"]["answered"] == 1
        assert out["overall"]["family_hits"] == 1

    def test_AN_ANSWER_THAT_MATCHES_NOTHING_IS_REPORTED_not_silently_dropped(self) -> None:
        """A reader that returns a mangled id would otherwise vanish from the
        denominator, and a smaller denominator flatters every rate above it."""
        cases = [_case("of-real", "veo-3")]
        out = scorer.score(cases, [_answer("case-999", "veo-3")], {"case-001": "of-real"})
        assert out["не_сошлись_идентификаторы"] == ["case-999"]
        assert out["checked"] == 0


if __name__ == "__main__":
    unittest.main()
