"""Пропуск теста: виден ли он, и отличается ли «данных нет» от «выключен».

Ничего не запускает — развилка вынесена наружу именно затем (Т5). Ожидаемое —
литералы (Т2), сети нет (Т4).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_skips", Path(__file__).resolve().parents[3] / "scripts" / "check_skips.py"
)
assert _SPEC and _SPEC.loader
skips = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(skips)

#: Настоящая причина с прогона 2026-08-31, дословно.
REAL = "no buffalo_l weights or demo/lora_dataset — nothing to reproduce the numbers with"


class DataAbsentIsNotTheSameAsSwitchedOff(unittest.TestCase):
    def test_the_real_reason_counts_as_data_absent(self) -> None:
        honest, off = skips.classify([REAL])
        assert honest == [REAL]
        assert off == []

    def test_причина_из_studio_tests_тоже_данных_нет(self) -> None:
        """Дословная причина двух пропусков в `studio/tests`, снятая с прогона
        2026-09-02, когда каталог впервые попал под этот сторож. Литерал (Т2):
        импортированная из проверяемого модуля, она переехала бы вместе с ним."""
        причина = "the prompt fixtures are not on this machine"
        honest, off = skips.classify([причина])
        assert honest == [причина]
        assert off == []

    def test_ANY_other_reason_is_a_switched_off_test(self) -> None:
        """Т7: ретрай и выключение — машинные способы превратить «не смогли» в
        «прошло». Причина, которой нет в списке, красит гейт."""
        honest, off = skips.classify(["flaky on CI", "TODO: fix later"])
        assert honest == []
        assert off == ["flaky on CI", "TODO: fix later"]

    def test_a_mixed_run_separates_them(self) -> None:
        honest, off = skips.classify([REAL, "temporarily disabled"])
        assert honest == [REAL]
        assert off == ["temporarily disabled"]

    def test_no_skips_at_all_yields_two_empty_lists(self) -> None:
        """Негативный контроль (И5): прибор, который всегда что-то находит,
        ничего не измеряет."""
        assert skips.classify([]) == ([], [])

    def test_the_allowed_list_is_matched_as_a_SUBSTRING_not_whole_string(self) -> None:
        """Причина приходит из unittest с хвостом, который мы не пишем. Точное
        сравнение развалилось бы от первой же правки текста в чужом тесте —
        а lipsync/** заморожен, править его нельзя (Ц2)."""
        honest, off = skips.classify(["no buffalo_l weights, and nothing else either"])
        assert off == []
        assert len(honest) == 1

    def test_an_empty_allowlist_makes_every_skip_a_violation(self) -> None:
        """Другая сторона константы: если список пуст, честных пропусков не
        бывает вовсе."""
        honest, off = skips.classify([REAL], allowed=())
        assert honest == []
        assert off == [REAL]


class TheSkipLineIsParsedFromUnittestOutput(unittest.TestCase):
    def test_a_skip_line_yields_its_reason(self) -> None:
        """Формат вывода unittest, дословно с прогона."""
        line = "test_x (mod.Case.test_x) ... skipped 'nothing to reproduce'"
        assert skips._SKIPPED.findall(line) == ["nothing to reproduce"]

    def test_a_passing_line_yields_nothing(self) -> None:
        """Негативный контроль на разбор: строка «ok» не должна считаться
        пропуском, иначе счётчик покажет пропуск на каждом зелёном тесте."""
        assert skips._SKIPPED.findall("test_x (mod.Case.test_x) ... ok") == []

    def test_double_quotes_are_read_too(self) -> None:
        line = 'test_x (mod.Case.test_x) ... skipped "нет весов"'
        assert skips._SKIPPED.findall(line) == ["нет весов"]


class ЗаКакимиНаборамиСледим(unittest.TestCase):
    """Список наборов раньше стоял литералом и разъехался с гейтом молча:
    `studio/tests` гейт перебирал, а сторож пропусков про него не знал — 503
    теста и два пропуска в них никем не сторожились (ИЗМЕРЕНО 2026-09-02)."""

    def test_наборы_взяты_из_самого_гейта(self) -> None:
        # Ожидаемое — литерал (Т2): импорт из проверяемого модуля переехал бы
        # вместе с ошибкой.
        self.assertEqual(
            sorted(skips.SUITES),
            [
                "lipsync/tests",
                "studio/mcp/tests",
                "studio/selfrag/tests",
                "studio/tests",
            ],
        )

    def test_каждый_набор_существует_в_дереве(self) -> None:
        корень = Path(__file__).resolve().parents[3]
        for набор in skips.SUITES:
            self.assertTrue((корень / набор).is_dir(), набор)


if __name__ == "__main__":
    unittest.main()
