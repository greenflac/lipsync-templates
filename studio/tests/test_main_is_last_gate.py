"""Сторожа гейта `scripts/check_main_is_last.py` — прибора, а не продукта.

ЗАЧЕМ ОТДЕЛЬНЫЙ НАБОР. Гейт завёлся десятой приёмкой и сам оказался модулем с
константой-решения без единого мутанта: покрытие мутантами показало его
одиннадцатым в списке «БЕЗ МУТАНТОВ», и потолок долга вырос с 9 до 10. Прибор,
который никто не сторожит, снимается в одну строку и молчит.

НЕГАТИВНЫЙ КОНТРОЛЬ ОБЯЗАТЕЛЕН (И5): здесь есть вход, где гейт обязан сказать
«беда», и вход, где он обязан промолчать. Без второго «нарушений 0» значит
только, что прибор ничего не смотрел.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

_ФАЙЛ = Path(__file__).resolve().parents[2] / "scripts" / "check_main_is_last.py"
_СПЕЦ = importlib.util.spec_from_file_location("check_main_is_last", _ФАЙЛ)
assert _СПЕЦ and _СПЕЦ.loader
гейт = importlib.util.module_from_spec(_СПЕЦ)
_СПЕЦ.loader.exec_module(гейт)

ХВОСТ_ЧИСТ = """
import unittest


class Хорошо(unittest.TestCase):
    def test_раз(self) -> None:
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
"""

КЛАСС_ПОСЛЕ_MAIN = """
import unittest


class Первый(unittest.TestCase):
    def test_раз(self) -> None:
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()


class ПотерянныйКласс(unittest.TestCase):
    def test_два(self) -> None:
        self.assertTrue(True)
"""

ФУНКЦИЯ_ПОСЛЕ_MAIN = """
import unittest

if __name__ == "__main__":
    unittest.main()


def потерянная_функция() -> None:
    return None
"""

ПРИСВАИВАНИЕ_ПОСЛЕ_MAIN = """
import unittest

if __name__ == "__main__":
    unittest.main()

ХВОСТ = 1
"""


def _на_дереве(содержимое: str, потолок: int = 0) -> dict:
    """Прогнать гейт на одном временном файле теста."""
    with tempfile.TemporaryDirectory() as каталог:
        (Path(каталог) / "test_образец.py").write_text(содержимое, encoding="utf-8")
        return гейт.проверить(корни=(каталог,), потолок=потолок)


class НегативныйКонтроль(unittest.TestCase):
    """И5: прибор обязан и находить, и НЕ находить."""

    def test_чистый_хвост_молчит(self) -> None:
        итог = _на_дереве(ХВОСТ_ЧИСТ)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["outcome"], "годно")
        self.assertEqual(итог["checked"], 1)

    def test_класс_после_main_находится(self) -> None:
        итог = _на_дереве(КЛАСС_ПОСЛЕ_MAIN)
        self.assertEqual(итог["violations"], 1)
        self.assertEqual(итог["outcome"], "не годно")
        self.assertIn("ПотерянныйКласс", итог["беды"][0])

    def test_функция_после_main_тоже_теряется(self) -> None:
        """Сторож состава `ТЕРЯЕТСЯ`: класс — не единственная потеря."""
        итог = _на_дереве(ФУНКЦИЯ_ПОСЛЕ_MAIN)
        self.assertEqual(итог["violations"], 1)
        self.assertIn("потерянная_функция", итог["беды"][0])

    def test_присваивание_после_main_безвредно(self) -> None:
        """Другая сторона того же состава: не всё после main — беда."""
        self.assertEqual(_на_дереве(ПРИСВАИВАНИЕ_ПОСЛЕ_MAIN)["violations"], 0)

    def test_файл_без_main_не_смотрится(self) -> None:
        итог = _на_дереве("class Просто:\n    pass\n")
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["checked"], 1)


class ПотолокРаботаетВОбеСтороны(unittest.TestCase):
    """Т1: развилка «долг вырос» наблюдаема подменой порога."""

    def test_беда_под_потолком_это_годно(self) -> None:
        итог = _на_дереве(КЛАСС_ПОСЛЕ_MAIN, потолок=1)
        self.assertEqual(итог["violations"], 1)
        self.assertEqual(итог["outcome"], "годно")

    def test_беда_над_потолком_это_не_годно(self) -> None:
        self.assertEqual(_на_дереве(КЛАСС_ПОСЛЕ_MAIN, потолок=0)["outcome"], "не годно")


class ПотолокЭтоЗаписанныйДолг(unittest.TestCase):
    """Храповик: число долга — литерал в тесте (Т2), а не импорт-эхо.

    ИЗМЕРЕНО 2026-09-07 при заведении гейта: 34 файла тестов с `main()`
    посередине, почти все — чужая территория (Ц2). Число обязано падать, когда
    их чинят, и не обязано расти никогда.
    """

    def test_потолок_равен_измеренному_долгу(self) -> None:
        self.assertEqual(гейт.ПОТОЛОК, 34)

    def test_на_живом_дереве_долг_не_вырос(self) -> None:
        итог = гейт.проверить()
        self.assertLessEqual(итог["violations"], 34)
        self.assertEqual(итог["outcome"], "годно")
        self.assertEqual(итог["unmeasured"], 0)


if __name__ == "__main__":
    unittest.main()
