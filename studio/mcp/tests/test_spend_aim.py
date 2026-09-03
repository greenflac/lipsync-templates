"""Куда нацелены деньги: заявки против того, что продукт рекомендует.

Т2: имена исходов и слова отчёта — литералы, а не импорт из проверяемого кода.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[3]


def _модуль():
    сп = importlib.util.spec_from_file_location(
        "check_spend_aim", КОРЕНЬ / "scripts" / "check_spend_aim.py"
    )
    м = importlib.util.module_from_spec(сп)
    assert сп.loader is not None
    сп.loader.exec_module(м)
    return м


s = _модуль()


class БрифыБерутсяИзНабора(unittest.TestCase):
    def test_второго_списка_брифов_не_заводится(self) -> None:
        """Е1: сверка обязана считать по тем же планам, что меряет голден-сет.

        Второй список разъехался бы с набором на первой правке, и деньги
        сверялись бы не с тем, что продукт выдаёт.
        """
        из_набора = s.брифы()
        self.assertTrue(из_набора)
        self.assertTrue(all("brief" in в for в in из_набора))


class ТриИсхода(unittest.TestCase):
    def test_живой_прогон_имеет_числа_рядом_с_исходом(self) -> None:
        итог = s.свести()
        self.assertIn(итог["outcome"], ("pass", "fail", "could not measure"))
        self.assertEqual(итог["violations"], итог["checked"] - len(итог["покрыты заявкой"]))

    def test_каждая_рекомендуемая_без_применимости_покрыта_заявкой(self) -> None:
        """Сегодняшнее состояние, и оно же — то, что нельзя потерять: деньги
        нацелены на модели, которые продукт действительно выбирает."""
        итог = s.свести()
        непокрытые = [м for м in итог["нужны замеры"] if м not in итог["покрыты заявкой"]]
        self.assertEqual([], непокрытые)

    def test_заявки_мимо_печатаются_но_не_нарушение(self) -> None:
        """Заявка на модель, которой продукт не выбирает, — не ложь, а другой
        приоритет владельца. Её видно в отчёте, и она не красит гейт."""
        итог = s.свести()
        self.assertIsInstance(итог["заявки мимо"], list)
        self.assertLessEqual(итог["violations"], итог["checked"])


class СверкаПоСвёрнутомуИмени(unittest.TestCase):
    def test_разное_написание_не_считается_промахом(self) -> None:
        """`sync-lipsync-2` и `sync-lipsync-v2` — одна модель; считать их
        разными значило бы объявить заявку промахом на написании."""
        from studio.selfrag.modelnames import fold

        self.assertEqual(fold("sync-lipsync-2"), fold("sync-lipsync-v2"))


if __name__ == "__main__":
    unittest.main()
