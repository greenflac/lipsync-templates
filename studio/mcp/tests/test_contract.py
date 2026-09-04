"""The contract gate: does it catch what the engine would catch, and refuse to guess?

Expected values here are LITERALS. Importing `WORDS_MIN` to assert against
`WORDS_MIN` would ride along with any change to it and pass in silence, which
is the one thing a guard must not do.
"""

from __future__ import annotations

import unittest

from studio.mcp import contract
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
        # FIVE, not three, since 2026-09-04: the gate also asks the studio's own
        # banned-topic list and looks for instructions addressed to the reader.
        # The number is asserted because "pass" means nothing without it — a
        # gate that quietly stops running a check keeps saying pass.
        assert out["checked"] == 5
        assert out["violations"] == 0
        assert out["leak"] == []
        assert out["banned"] == []
        assert out["injection"] == []

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


class ЧужойЯзык(unittest.TestCase):
    """Найдено чтением собственной выдачи (П3, 2026-09-02).

    На промпте «женщина говорит в камеру, тёплый янтарный свет, матовая
    кожа» прибор отвечал `fail` со словами «words 0, corpus band 9..67» и
    `leak: []`. Оба числа — неправда: слова движок считает по `[A-Za-z]`, а
    запретную зону сверяет с английским списком, поэтому «женщина» он не
    видит. Опаснее всего сочетание: почини кто-нибудь только счётчик слов —
    и промпт, называющий субъекта, получил бы `pass`.
    """

    РУССКИЙ_С_СУБЪЕКТОМ = "женщина говорит в камеру, тёплый янтарный свет, матовая кожа"
    АНГЛИЙСКИЙ_ЧИСТЫЙ = (
        "warm amber light, matte skin, muted colours, shallow depth of field, soft falloff"
    )

    def test_кириллица_это_не_смогли_а_не_нарушение(self) -> None:
        out = contract.gate(self.РУССКИЙ_С_СУБЪЕКТОМ)
        self.assertEqual(out["outcome"], "could not measure")
        self.assertEqual(out["checked"], 0)
        self.assertEqual(out["unmeasured"], 3)

    def test_и_сказано_что_именно_не_проверено(self) -> None:
        """Пустой `leak` обязан быть объяснён словами, иначе он читается как
        «чисто» — а это ровно то «уверенно и неверно», против чего пакет."""
        нота = contract.gate(self.РУССКИЙ_С_СУБЪЕКТОМ)["note"]
        self.assertIn("не латиницей", нота)
        self.assertIn("НЕ ПРОВЕРЕНЫ", нота)

    def test_английский_судится_как_прежде(self) -> None:
        """Вторая половина контроля (И5): без неё правило «ничего не судить»
        тоже дало бы ноль ложных срабатываний."""
        self.assertEqual(contract.gate(self.АНГЛИЙСКИЙ_ЧИСТЫЙ)["outcome"], "pass")
        плохой = "a woman talking to camera, warm amber light, matte skin, muted colours, film"
        self.assertEqual(contract.gate(плохой)["leak"], ["woman"])

    def test_текст_без_букв_судится(self) -> None:
        """«720p, 24 fps» — не чужой язык, а промпт без слов, и ноль слов там
        честный ноль. Свернуть эти два случая значило бы прятать нарушение
        полосы за «не смогли»."""
        self.assertEqual(contract.gate("720p, 24 fps, 1.85:1")["outcome"], "fail")

    def test_английский_с_парой_русских_слов_ещё_судится(self) -> None:
        """Граница выбрана широкой: пока латиницы больше половины, прибор
        отвечает за свои слова."""
        смесь = "warm amber light, matte skin, muted colours, shallow depth of field, свет"
        self.assertEqual(contract.gate(смесь)["outcome"], "pass")

    def test_доля_латиницы_считается_по_буквам_а_не_по_символам(self) -> None:
        """Т2: ожидаемое — литералы. Цифры и запятые долю не размывают."""
        self.assertEqual(contract._латиницы("abc"), 1.0)
        self.assertEqual(contract._латиницы("абв"), 0.0)
        self.assertEqual(contract._латиницы("ab вг"), 0.5)
        self.assertEqual(contract._латиницы("720, 24"), 1.0)
