"""Проверка «есть ли тесты, которых гейт не запускает» — со своими тестами.

Ожидаемые значения здесь ЛИТЕРАЛЫ (Т2): импортировать их из проверяемого
модуля значило бы получить набор, который переедет вместе с ошибкой.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

_КОРЕНЬ = Path(__file__).resolve().parents[3]
_СПЕЦ = importlib.util.spec_from_file_location(
    "check_tests_gated", _КОРЕНЬ / "scripts" / "check_tests_gated.py"
)
assert _СПЕЦ and _СПЕЦ.loader
cg = importlib.util.module_from_spec(_СПЕЦ)
_СПЕЦ.loader.exec_module(cg)


def дерево(гейт: str, файлы: dict[str, str]) -> tuple[Path, Path]:
    корень = Path(tempfile.mkdtemp())
    (корень / "scripts").mkdir()
    путь_гейта = корень / "scripts" / "check"
    путь_гейта.write_text(гейт, encoding="utf-8")
    for имя, тело in файлы.items():
        цель = корень / имя
        цель.parent.mkdir(parents=True, exist_ok=True)
        цель.write_text(тело, encoding="utf-8")
    return корень, путь_гейта


class ЧтоСчитаетсяДостижимым(unittest.TestCase):
    def test_перебор_каталога_берёт_файл(self):
        корень, гейт = дерево(
            "python -m unittest discover -s studio/tests -t .\n",
            {"studio/tests/__init__.py": "", "studio/tests/test_один.py": ""},
        )
        итог = cg.проверить(корень, гейт)
        self.assertEqual((итог["violations"], итог["unmeasured"]), (0, 0))

    def test_поимённый_модуль_берёт_файл(self):
        """Вторая форма записи в гейте — список модулей, а не каталог."""
        корень, гейт = дерево(
            "python -m unittest studio.tests.test_один\n",
            {"studio/tests/test_один.py": ""},
        )
        итог = cg.проверить(корень, гейт)
        self.assertEqual(итог["violations"], 0)

    def test_файл_мимо_всех_корней_это_нарушение(self):
        """ИЗМЕРЕНО 2026-09-02: ровно так семь файлов studio/tests не гонялись."""
        корень, гейт = дерево(
            "python -m unittest discover -s studio/tests -t .\n",
            {
                "studio/tests/__init__.py": "",
                "studio/tests/test_виден.py": "",
                "studio/test_невиден.py": "",
            },
        )
        итог = cg.проверить(корень, гейт)
        self.assertEqual(итог["violations"], 1)
        self.assertEqual(итог["мимо"], ["studio/test_невиден.py"])
        self.assertEqual(итог["outcome"], "fail")

    def test_имя_мимо_образца_перебора_это_нарушение(self):
        """`unittest discover` берёт `test*.py`. Файл `foo_test.py` лежит в
        корне перебора, выглядит тестом для человека и не гоняется никем —
        молча, потому что и в отчёт он не попадает."""
        корень, гейт = дерево(
            "python -m unittest discover -s studio/tests -t .\n",
            {"studio/tests/__init__.py": "", "studio/tests/один_test.py": ""},
        )
        итог = cg.проверить(корень, гейт)
        self.assertEqual(итог["violations"], 1)
        self.assertEqual(итог["мимо"], ["studio/tests/один_test.py"])

    def test_подпакет_под_корнем_достижим(self):
        """`unittest discover` спускается в подпакеты, и проверка обязана
        знать это: ложная тревога учит выключать проверку."""
        корень, гейт = дерево(
            "python -m unittest discover -s studio/tests -t .\n",
            {
                "studio/tests/__init__.py": "",
                "studio/tests/глубже/__init__.py": "",
                "studio/tests/глубже/test_два.py": "",
            },
        )
        итог = cg.проверить(корень, гейт)
        self.assertEqual((итог["violations"], итог["unmeasured"]), (0, 0))

    def test_разорванная_цепочка_пакетов_это_третий_исход(self):
        """Р1: «не смогли» не сворачивается ни в «годно», ни в «не годно».
        Каталог назван в гейте, но без `__init__.py` не импортируется —
        и это ровно то, что закрывало studio/tests до 2026-09-02."""
        корень, гейт = дерево(
            "python -m unittest discover -s studio/tests -t .\n",
            {"studio/tests/test_один.py": ""},
        )
        итог = cg.проверить(корень, гейт)
        self.assertEqual((итог["violations"], итог["unmeasured"]), (0, 1))
        self.assertEqual(итог["outcome"], "could not measure")

    def test_подкаталог_без_init_под_корнем_тоже_третий_исход(self):
        корень, гейт = дерево(
            "python -m unittest discover -s studio/tests -t .\n",
            {"studio/tests/__init__.py": "", "studio/tests/глубже/test_два.py": ""},
        )
        итог = cg.проверить(корень, гейт)
        self.assertEqual((итог["violations"], итог["unmeasured"]), (0, 1))

    def test_нечитаемый_гейт_это_не_успех(self):
        корень = Path(tempfile.mkdtemp())
        итог = cg.проверить(корень, корень / "нет-такого")
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["unmeasured"], 1)

    def test_рабочие_копии_агентов_не_наше_дерево(self):
        """Ц2: чужая рабочая копия внутри .claude/ — не наши тесты."""
        корень, гейт = дерево(
            "python -m unittest discover -s studio/tests -t .\n",
            {
                "studio/tests/__init__.py": "",
                "studio/.claude/worktrees/чужая/tests/test_чужой.py": "",
            },
        )
        итог = cg.проверить(корень, гейт)
        self.assertEqual(итог["violations"], 0)


class НегативныйКонтроль(unittest.TestCase):
    def test_самопроверка_проходит(self):
        """И5: у прибора есть вход, на котором он обязан шевельнуться."""
        self.assertEqual(cg.самопроверка(), 0)


class ЖивоеДерево(unittest.TestCase):
    def test_на_этом_репозитории_нарушений_нет(self):
        итог = cg.проверить()
        self.assertEqual(итог["violations"], 0, итог["мимо"])
        self.assertEqual(итог["unmeasured"], 0, итог["не смогли"])
        self.assertGreater(итог["checked"], 50)


class ГейтМеритСвоиШаги(unittest.TestCase):
    """Секундомер гейта закрывает шаг на СЛЕДУЮЩЕМ вызове `step`, поэтому
    раздел, напечатавший заголовок голым `echo`, времени не получает — его
    секунды приписываются предыдущему шагу.

    ИЗМЕРЕНО по логу CI 2026-09-03: в сводке стояло «116 с — мутации каналов»
    при настоящих 8 с у каналов; 108 с принадлежали мутациям планировщика,
    заголовок которых печатался мимо `step`. Прибор, врущий о том, что
    дорого, хуже отсутствующего: по нему принимают решения.
    """

    def test_ни_один_заголовок_не_печатается_мимо_секундомера(self) -> None:
        гейт = (_КОРЕНЬ / "scripts" / "check").read_text(encoding="utf-8").splitlines()
        мимо = [
            (н, с.strip())
            for н, с in enumerate(гейт, 1)
            # Единственное законное место — тело самой функции `step`.
            if 'echo "== ' in с and "$1" not in с and not с.lstrip().startswith("#")
        ]
        self.assertEqual(мимо, [], "заголовок мимо `step`: секунды уедут соседу")

    def test_контроль_прибор_шевелится(self) -> None:
        """И5: та же проверка на подложенной строке обязана сказать «нашёл»."""
        подделка = ['step "честный"', 'echo "== мимо секундомера"', '# echo "== в комментарии"']
        мимо = [
            с
            for с in подделка
            if 'echo "== ' in с and "$1" not in с and not с.lstrip().startswith("#")
        ]
        self.assertEqual(мимо, ['echo "== мимо секундомера"'])


if __name__ == "__main__":
    unittest.main()
