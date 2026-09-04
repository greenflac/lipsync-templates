"""Прибор, считающий модули без мутантов (R7), и его собственные сторожа.

Т2: ожидаемое — литералы. Числа и слова исходов написаны руками.

ЗАЧЕМ ТЕСТЫ НА СЧЁТЧИК ДОЛГА. Он печатает число, по которому принимают решение
о релизе, и ошибиться в нём легко в обе стороны: занизить (объявить долг
меньшим, чем он есть) и завысить (потребовать мутантов там, где ветвления нет).
Первое опаснее, поэтому и определение, и его границы проверяются здесь.
"""

from __future__ import annotations

import importlib.util
import unittest
import unittest.mock
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[3]


def _модуль():
    сп = importlib.util.spec_from_file_location(
        "check_mutants_cover", КОРЕНЬ / "scripts" / "check_mutants_cover.py"
    )
    м = importlib.util.module_from_spec(сп)
    assert сп.loader is not None
    сп.loader.exec_module(м)
    return м


c = _модуль()


class ЧтоСчитаетсяРешением(unittest.TestCase):
    def test_константа_в_условии_считается(self) -> None:
        исходник = "ПОРОГ = 5\n\n\ndef f(x):\n    if x > ПОРОГ:\n        return 1\n    return 0\n"
        self.assertEqual({"ПОРОГ"}, c.решающие_константы(исходник))

    def test_константа_без_сравнения_тоже_считается(self) -> None:
        """`if ФЛАГ:` — ветвление без сравнения, и оно решает не меньше.

        Дыра, найденная мутацией: первый тест писал `if x > ПОРОГ`, то есть
        внутри `if` стояло ещё и сравнение, и ветку `ast.If` можно было
        выключить незаметно — её работу делал сосед `ast.Compare`.
        """
        исходник = "ФЛАГ = True\n\n\ndef f():\n    if ФЛАГ:\n        return 1\n    return 0\n"
        self.assertEqual({"ФЛАГ"}, c.решающие_константы(исходник))

    def test_константа_в_сравнении_считается(self) -> None:
        исходник = "РЕЖИМ = 'a'\n\n\ndef f(x):\n    return x == РЕЖИМ\n"
        self.assertEqual({"РЕЖИМ"}, c.решающие_константы(исходник))

    def test_константа_в_проверке_вхождения_считается(self) -> None:
        исходник = "СПИСОК = ('a',)\n\n\ndef f(x):\n    return x in СПИСОК\n"
        self.assertEqual({"СПИСОК"}, c.решающие_константы(исходник))

    def test_таблица_данных_решением_НЕ_считается(self) -> None:
        """Граница определения. Иначе счётчик объявил бы долгом каждый словарь
        печати, и число перестало бы значить что-либо."""
        исходник = "ПОДПИСИ = {'a': 'А'}\n\n\ndef f(x):\n    return ПОДПИСИ[x]\n"
        self.assertEqual(set(), c.решающие_константы(исходник))

    def test_строчное_имя_не_считается(self) -> None:
        исходник = "порог = 5\n\n\ndef f(x):\n    if x > порог:\n        return 1\n    return 0\n"
        self.assertEqual(set(), c.решающие_константы(исходник))


class ЧитаемыеТаблицы(unittest.TestCase):
    def test_пути_читаются_из_таблиц_мутантов(self) -> None:
        пути = c.покрытые()
        self.assertIn("studio/planner.py", пути)
        self.assertIn("studio/pipeline.py", пути)

    def test_счёт_идёт_по_живому_дереву(self) -> None:
        итог = c.свести()
        self.assertGreater(итог["checked"], 50, "модулей с решениями подозрительно мало")
        self.assertEqual(итог["checked"], итог["покрыто"] + итог["violations"])


class Потолок(unittest.TestCase):
    """Потолок обязан ловить РОСТ долга и требовать снижения при падении."""

    def _подменить(self, нарушений: int):
        итог = {
            "outcome": "fail",
            "checked": 100,
            "violations": нарушений,
            "unmeasured": 0,
            "покрыто": 100 - нарушений,
            "непокрытые": [],
        }
        return unittest.mock.patch.object(c, "свести", lambda: итог)

    def test_рост_долга_краснеет(self) -> None:
        with self._подменить(c.ПОТОЛОК + 1):
            self.assertEqual(1, c.main(["--check"]))

    def test_долг_по_потолку_проходит(self) -> None:
        with self._подменить(c.ПОТОЛОК):
            self.assertEqual(0, c.main(["--check"]))

    def test_упавший_долг_требует_опустить_потолок(self) -> None:
        """Иначе потолок отрывается от дерева и перестаёт ловить рост."""
        with self._подменить(c.ПОТОЛОК - 1):
            self.assertEqual(1, c.main(["--check"]))


if __name__ == "__main__":
    unittest.main()
