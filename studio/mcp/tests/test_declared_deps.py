"""Необъявленная зависимость: новая беда против записанного отступления.

ЗАЧЕМ. `imageio-ffmpeg` использовался ЧЕТЫРЬМЯ модулями и не был объявлен
нигде. Локально пакет стоял — он приезжает попутно с чужими зависимостями, —
поэтому и гейт, и зеркало CI были зелёными, а настоящий CI упал на первом же
тесте, которому пакет понадобился (2026-08-31). Необъявленная зависимость не
«почти работает»: она работает ровно там, где её случайно поставили.

Тот же класс подтвердился 2026-09-06 на свежем контейнере: `mypy` не стоял, и
гейт остановился на третьем шаге.

Разбор на новые и давние жил ВНУТРИ точки входа и был достижим только через
настоящее дерево файлов: список отступлений мог опустеть или разрастись, и ни
один тест бы не шевельнулся. Поймано ратчетом R7.

Ожидаемое — литералы (Т2), сети нет (Т4), файлов на диске не нужно (Т5).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_declared_deps",
    Path(__file__).resolve().parents[3] / "scripts" / "check_declared_deps.py",
)
assert _SPEC and _SPEC.loader
проверка = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(проверка)


class НоваяБедаОтличаетсяОтЗаписанногоОтступления(unittest.TestCase):
    def test_незнакомый_пакет_это_нарушение(self):
        новые, давние = проверка.развести({"imageio-ffmpeg": ["studio/mcp/creative.py"]})
        self.assertEqual(list(новые), ["imageio-ffmpeg"])
        self.assertEqual(давние, {})

    def test_записанное_отступление_это_третий_исход(self):
        """`insightface` числится давним с названным поводом («lipsync/**
        заморожен»). Красить сборку задним числом значило бы держать её
        красной ради красного — но и в успех оно не сворачивается."""
        новые, давние = проверка.развести({"insightface": ["lipsync/identity_arcface.py"]})
        self.assertEqual(новые, {})
        self.assertEqual(list(давние), ["insightface"])

    def test_у_каждого_отступления_назван_повод(self):
        """Отступление без повода — это не отступление, а забытый долг."""
        for пакет, повод in проверка.KNOWN_UNDECLARED.items():
            self.assertTrue(повод.strip(), пакет)

    def test_список_отступлений_ровно_семь_имён(self):
        """Литерал (Т2). Список обязан только СОКРАЩАТЬСЯ: молча дописать в
        него новый пакет — это способ пройти гейт, не объявив зависимость."""
        self.assertEqual(
            {
                "creative-eval",
                "fal-client",
                "insightface",
                "mediapipe",
                "requests",
                "pyarrow",
                "pydantic",
            },
            set(проверка.KNOWN_UNDECLARED),
        )

    def test_смешанный_случай_разводится_по_обе_стороны(self):
        """Е3: частичный результат печатается числами, а не одним флагом."""
        новые, давние = проверка.развести(
            {"imageio-ffmpeg": ["a.py"], "pydantic": ["b.py"], "httpx2": ["c.py"]}
        )
        self.assertEqual(sorted(новые), ["httpx2", "imageio-ffmpeg"])
        self.assertEqual(sorted(давние), ["pydantic"])

    def test_ничего_не_найдено_обе_стороны_пусты(self):
        self.assertEqual(({}, {}), проверка.развести({}))


class ИмпортыСверяютсяСоСписком(unittest.TestCase):
    def test_объявленный_пакет_не_беда(self):
        """Негативный контроль (И5): проверка, ругающаяся на всё, не
        отличается от отсутствия списка."""
        найдено = проверка.undeclared({"a.py": "import numpy\n"}, "numpy==2.4.6\n")
        self.assertEqual(найдено, {})

    def test_необъявленный_пакет_найден_с_именем_файла(self):
        найдено = проверка.undeclared({"studio/x.py": "import imageio_ffmpeg\n"}, "numpy==2.4.6\n")
        self.assertEqual(найдено, {"imageio-ffmpeg": ["studio/x.py"]})

    def test_стандартная_библиотека_и_свои_модули_не_считаются(self):
        источник = "import json\nimport studio.planner\nfrom scripts import x\n"
        self.assertEqual({}, проверка.undeclared({"a.py": источник}, ""))


if __name__ == "__main__":
    unittest.main()
