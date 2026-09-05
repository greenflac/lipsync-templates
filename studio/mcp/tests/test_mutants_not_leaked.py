"""Ловит ли проверка утёкшего мутанта — и не кричит ли она на чистое дерево.

ЗАЧЕМ ЭТОТ НАБОР. 2026-09-05 снимок убитого мутационного прогона уехал в
коммит 6bdc472: в `scripts/recheck_vendor.py` вместо решения стояло
`if False:`, и продукт два коммита подряд объявлял изменившейся любую
нестабильную страницу вендора. Проверка, написанная против этого, сама
обязана быть под присмотром: её ложное «нарушений 0» ничем не отличается от
её отсутствия.

Ожидаемое — литералы (Т2), сети нет (Т4), развилка вызывается функцией, а не
через процесс (Т5). Входы — с обоих краёв и из середины (Т3): применённый
мутант, исчезнувшая цель, неоднозначная цель, чистый файл.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_mutants_clean",
    Path(__file__).resolve().parents[3] / "scripts" / "check_mutants_clean.py",
)
assert _SPEC and _SPEC.loader
проверка = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(проверка)

#: Настоящая утечка, дословно с коммита 6bdc472 (И2: вход сохранён).
СТАРОЕ = "            if если_второй is None or если_второй != свежий:"
НОВОЕ = "            if False:"
ФАЙЛ = "scripts/recheck_vendor.py"
МУТАНТ = [(ФАЙЛ, СТАРОЕ, НОВОЕ, "страницы: второе чтение перестало сверяться")]


def _дерево(содержимое: str, каталог: str) -> Path:
    корень = Path(каталог)
    путь = корень / ФАЙЛ
    путь.parent.mkdir(parents=True, exist_ok=True)
    путь.write_text(содержимое, encoding="utf-8")
    return корень


class УтёкшийМутантНазываетсяВслух(unittest.TestCase):
    def test_применённый_мутант_это_не_годно(self) -> None:
        with tempfile.TemporaryDirectory() as каталог:
            итог = проверка.проверить(_дерево(f"код\n{НОВОЕ}\n    ещё\n", каталог), МУТАНТ)
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)
        self.assertEqual(итог["unmeasured"], 0)
        self.assertEqual(len(итог["утекли"]), 1)
        self.assertEqual(итог["исчезли"], [])

    def test_чистое_дерево_это_годно(self) -> None:
        """Негативный контроль (И5): проверка, которая краснеет всегда, не
        отличается от проверки, которая краснеет случайно."""
        with tempfile.TemporaryDirectory() as каталог:
            итог = проверка.проверить(_дерево(f"код\n{СТАРОЕ}\n    ещё\n", каталог), МУТАНТ)
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 0)

    def test_исчезнувшая_цель_это_не_годно_и_отдельным_классом(self) -> None:
        """Мутант, ищущий несуществующее, молчит не потому, что охрана крепка.
        За один день 2026-09-05 таких нашлось четыре, и все выглядели живыми."""
        with tempfile.TemporaryDirectory() as каталог:
            итог = проверка.проверить(_дерево("совсем другой код\n", каталог), МУТАНТ)
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)
        self.assertEqual(len(итог["исчезли"]), 1)
        self.assertEqual(итог["утекли"], [])

    def test_цель_в_двух_местах_это_не_годно(self) -> None:
        """Подмена делается только в первом месте, поэтому «старое на месте»
        при двух вхождениях больше ничего не доказывает."""
        with tempfile.TemporaryDirectory() as каталог:
            итог = проверка.проверить(_дерево(f"{СТАРОЕ}\nсередина\n{СТАРОЕ}\n", каталог), МУТАНТ)
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)
        self.assertEqual(len(итог["неоднозначны"]), 1)

    def test_файла_нет_это_третий_исход_а_не_успех(self) -> None:
        with tempfile.TemporaryDirectory() as каталог:
            итог = проверка.проверить(Path(каталог), МУТАНТ)
        self.assertEqual(итог["outcome"], "unmeasured")
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 1)

    def test_живое_дерево_проекта_чистое(self) -> None:
        """Р2: рядом с вердиктом печатаются числа. Ноль нарушений при нуле
        проверенных мутантов — не успех, поэтому проверяется и количество."""
        итог = проверка.проверить(Path(__file__).resolve().parents[3])
        self.assertEqual(итог["утекли"], [])
        self.assertEqual(итог["исчезли"], [])
        self.assertEqual(итог["неоднозначны"], [])
        self.assertGreater(итог["checked"], 300)
