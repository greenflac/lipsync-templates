"""Прибор, считающий недостижимую долю базы (критерий R3).

Т2: ожидаемое — литералы. Т4: сети нет, база читается с диска.
"""

from __future__ import annotations

import importlib.util
import unittest
import unittest.mock
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[3]


def _модуль():
    сп = importlib.util.spec_from_file_location(
        "check_reachability", КОРЕНЬ / "scripts" / "check_reachability.py"
    )
    м = importlib.util.module_from_spec(сп)
    assert сп.loader is not None
    сп.loader.exec_module(м)
    return м


r = _модуль()


class ПотолокНедостижимости(unittest.TestCase):
    """Потолок — условие релиза, а не украшение: он обязан УМЕТЬ покраснеть."""

    def test_порог_ровно_ноль(self) -> None:
        """Владелец потребовал 2026-09-05 довести достижимость до 95%; вышло
        100%, и потолок поставлен туда же, куда доехали. Ноль здесь — ИЗМЕРЕННОЕ
        состояние (0 недостижимых строк из 2127), а не круглое число: теперь
        новое имя атрибута обязано приехать вместе со своей семьёй."""
        self.assertEqual(0.0, r.ПОТОЛОК_ДОЛИ)

    def _подменить(self, доля: float):
        итог: dict[str, object] = {
            "outcome": "pass" if доля <= r.ПОТОЛОК_ДОЛИ else "fail",
            "checked": 1000,
            "violations": int(доля * 1000),
            "unmeasured": 0,
            "доля": доля,
            "семей": 17,
            "имён": 286,
            "молчат": [],
        }
        return unittest.mock.patch.object(r, "свести", lambda: итог)

    def test_доля_выше_потолка_краснеет(self) -> None:
        with self._подменить(0.283):
            self.assertEqual(1, r.main(["--check"]))

    def test_доля_под_потолком_проходит(self) -> None:
        with self._подменить(0.0):
            self.assertEqual(0, r.main(["--check"]))

    def test_одна_недостижимая_строка_из_тысячи_уже_краснеет(self) -> None:
        """Негативный контроль (И5) к нулевому потолку: он обязан ловить не
        «много недостижимого», а ЛЮБОЕ. 0.1% — это одна строка из тысячи."""
        with self._подменить(0.001):
            self.assertEqual(1, r.main(["--check"]))

    def test_ровно_потолок_считается_годным(self) -> None:
        """Граница включительно, и это записанное решение, а не случайность."""
        with self._подменить(r.ПОТОЛОК_ДОЛИ):
            self.assertEqual(0, r.main(["--check"]))


class ЖиваяБаза(unittest.TestCase):
    def test_сейчас_под_потолком(self) -> None:
        итог = r.свести()
        self.assertEqual("pass", итог["outcome"], f"{итог['доля']:.1%} недостижимо")
        self.assertGreater(итог["checked"], 1000, "база подозрительно мала")

    def test_пустая_база_это_третий_исход_а_не_ноль_нарушений(self) -> None:
        with unittest.mock.patch.object(r, "load_facts", lambda: []):
            self.assertEqual("could not measure", r.свести()["outcome"])


if __name__ == "__main__":
    unittest.main()
