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


class НастоящаяОшибкаЛовитсяДоСих_Пор(unittest.TestCase):
    """И2: наблюдение дефекта не удаляется вместе с переписыванием файла.

    Эти четыре охраны существовали до коммита 69975ac и были сняты им молча
    вместе с переписыванием файла целиком (10 тестов -> 9, общих 3). Возвращены
    поимённо; баланс охраны того коммита был отрицательным, и это названо.
    """

    def test_импорт_внутри_функции_без_try_это_нарушение(self):
        """Ровно то, что упало в CI 2026-08-31: импорт стоял внутри функции,
        но без `try`, и сборка упала вместо честного «не смогли»."""
        источник = "def make():\n    import imageio_ffmpeg\n    return imageio_ffmpeg\n"
        self.assertEqual(
            {"imageio-ffmpeg": ["t.py"]},
            проверка.undeclared({"t.py": источник}, "numpy==2.4.6\n"),
        )

    def test_имя_импорта_переводится_в_имя_пакета(self):
        """`PIL` ставится как `pillow`. Угадывать по подчёркиваниям значит
        однажды угадать неверно и промолчать."""
        self.assertEqual(
            {}, проверка.undeclared({"m.py": "from PIL import Image\n"}, "pillow==12.3.0\n")
        )


class ЗащищённыйИмпортНеобязателенПоЗамыслу(unittest.TestCase):
    ЗАЩИЩЁН = (
        "def probe():\n    try:\n        import torch\n    except Exception:\n        return None\n"
    )

    def test_импорт_внутри_try_except_не_требует_объявления(self):
        """Так устроены torch, sentence-transformers и pyarrow: отсутствие
        пакета превращается в честное «не смогли» с кодом ошибки."""
        self.assertEqual({}, проверка.undeclared({"m.py": self.ЗАЩИЩЁН}, "numpy==2.4.6\n"))

    def test_тот_же_пакет_без_защиты_в_другом_файле_всё_равно_ловится(self):
        """Граница проходит по защите, а не по имени пакета: один защищённый
        импорт не выдаёт индульгенцию всем остальным."""
        найдено = проверка.undeclared(
            {"safe.py": self.ЗАЩИЩЁН, "risky.py": "import torch\n"}, "numpy==2.4.6\n"
        )
        self.assertEqual({"torch": ["risky.py"]}, найдено)


class РазборRequirementsЧитаетТо_ЧтоТам(unittest.TestCase):
    def test_версии_и_комментарии_срезаются(self):
        """Комментарий бывает целой строкой и бывает хвостом БЕЗ версии рядом.

        Первая фикстура этого теста имела комментарий только после пина
        (`numpy==2.4.6  # пин`), и там его срезал разбор версии, а не разбор
        комментария: подмена «комментарии не срезаются» оставалась зелёной
        (Т1, проверено подменой 2026-09-06). Фикстура взята с обоих краёв (Т3).
        """
        реквизиты = "# целиком строка\nnumpy==2.4.6  # пин\n\nruff>=0.1\npyarrow  # руками\n"
        self.assertEqual({"numpy", "ruff", "pyarrow"}, проверка.declared(реквизиты))

    def test_подчёркивания_и_регистр_не_считаются(self):
        """`imageio_ffmpeg` в импорте и `imageio-ffmpeg` в requirements — один
        пакет. Без этого проверка ругалась бы на объявленное."""
        self.assertIn("imageio-ffmpeg", проверка.declared("Imageio_FFmpeg==0.6.0\n"))


if __name__ == "__main__":
    unittest.main()
