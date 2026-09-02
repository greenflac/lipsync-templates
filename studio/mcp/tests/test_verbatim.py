"""Прибор чужой прозы обязан ловить чужое и молчать на своём.

Обе половины контроля здесь равноправны (И5): прибор уже дважды соврал при
постройке — считал наши собственные ноты нарушением и находил «имена» в
словах `by the`. Ожидаемое — литералы (Т2). Сети нет (Т4), файлов не пишем.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from studio import verbatim as vb

ЧУЖОЕ = "https://huggingface.co/org/model/discussions/12"
ВЕНДОРСКОЕ = "https://huggingface.co/org/model"
ДЛИННОЕ = " ".join(f"слово{i}" for i in range(30))


def _файл(записи: list[dict]) -> Path:
    п = Path(tempfile.mkdtemp()) / "проба.jsonl"
    п.write_text("\n".join(json.dumps(з, ensure_ascii=False) for з in записи), encoding="utf-8")
    return п


class Ловит(unittest.TestCase):
    def test_длинная_реплика_человека(self):
        и = vb.проверить_файл(_файл([{"value": ДЛИННОЕ, "source_url": ЧУЖОЕ}]))
        self.assertEqual(и.outcome, "fail")
        self.assertEqual(len(и.длинных), 1)
        self.assertEqual(и.длинных[0].слов, 30)

    def test_имя_в_ноте(self):
        и = vb.проверить_файл(
            _файл(
                [{"value": "коротко", "note": "тело треда #7, автор dzft3w", "source_url": ЧУЖОЕ}]
            )
        )
        self.assertEqual(и.outcome, "fail")
        self.assertEqual(и.с_именем[0].имя, "dzft3w")

    def test_имя_ловится_и_на_вендорском_адресе(self):
        """Имя — это персональные данные, хост тут ни при чём."""
        и = vb.проверить_файл(
            _файл([{"value": "коротко", "note": "автор kto-to", "source_url": ВЕНДОРСКОЕ}])
        )
        self.assertEqual(len(и.с_именем), 1)


class Молчит(unittest.TestCase):
    def test_наша_длинная_нота_не_нарушение(self):
        """1543 таких прибор считал нарушением в первой редакции."""
        и = vb.проверить_файл(_файл([{"value": "коротко", "note": ДЛИННОЕ, "source_url": ЧУЖОЕ}]))
        self.assertEqual(и.outcome, "pass")
        self.assertEqual(и.длинных, [])

    def test_длинная_вендорская_спецификация_не_нарушение(self):
        """Документ, опубликованный для чтения, — не чужое высказывание."""
        и = vb.проверить_файл(_файл([{"value": ДЛИННОЕ, "source_url": ВЕНДОРСКОЕ}]))
        self.assertEqual(и.outcome, "pass")

    def test_by_the_не_имя(self):
        """515 «имён» первой редакции были такими словами."""
        для = "VBench does not name these dimensions, by the way, and by family they differ"
        self.assertEqual(vb.имя_в(для), "")

    def test_автор_неизвестен_не_имя(self):
        self.assertEqual(vb.имя_в("тело треда #7, автор неизвестен"), "")
        self.assertEqual(vb.имя_в("author unknown"), "")

    def test_короткая_реплика_человека_проходит(self):
        и = vb.проверить_файл(
            _файл([{"value": "On a 3090 it desyncs after six seconds.", "source_url": ЧУЖОЕ}])
        )
        self.assertEqual(и.outcome, "pass")


class ТриИсхода(unittest.TestCase):
    def test_файла_нет_это_не_успех(self):
        и = vb.проверить_файл(Path("/нет/такого.jsonl"))
        self.assertEqual(и.outcome, "could not measure")
        self.assertEqual(и.unmeasured, 1)

    def test_пустой_файл_это_не_успех(self):
        self.assertEqual(vb.проверить_файл(_файл([])).outcome, "could not measure")

    def test_битая_строка_считается_отдельно(self):
        п = _файл([{"value": "коротко", "source_url": ЧУЖОЕ}])
        п.write_text(п.read_text(encoding="utf-8") + "\nне json\n", encoding="utf-8")
        и = vb.проверить_файл(п)
        self.assertEqual(и.checked, 1)
        self.assertEqual(и.unmeasured, 1)


class Границы(unittest.TestCase):
    """Края диапазона и середина (Т3)."""

    def test_ровно_на_пороге_проходит(self):
        текст = " ".join(f"с{i}" for i in range(15))
        self.assertEqual(
            vb.проверить_файл(_файл([{"value": текст, "source_url": ЧУЖОЕ}])).outcome, "pass"
        )

    def test_на_слово_за_порогом_краснеет(self):
        текст = " ".join(f"с{i}" for i in range(16))
        self.assertEqual(
            vb.проверить_файл(_файл([{"value": текст, "source_url": ЧУЖОЕ}])).outcome, "fail"
        )

    def test_порог_один_во_всех_местах_где_он_известен(self):
        """Е1: расхождение двух мест обязано краснеть."""
        import re as _re

        корень = Path(__file__).resolve().parents[3]
        ремесло = (корень / "scripts" / "check_craft.py").read_text(encoding="utf-8")
        канал = (корень / "scripts" / "ingest_hf.py").read_text(encoding="utf-8")
        self.assertEqual(vb.ДОСЛОВНО_СЛОВ, 15)
        self.assertEqual(int(_re.search(r"VERBATIM_MAX_WORDS\s*=\s*(\d+)", ремесло).group(1)), 15)
        self.assertEqual(int(_re.search(r"ДОСЛОВНО_СЛОВ\s*=\s*(\d+)", канал).group(1)), 15)


if __name__ == "__main__":
    unittest.main()


class ПолНеПоднимается(unittest.TestCase):
    """Пол долга обязан РАВНЯТЬСЯ измеренному, а не быть выше него.

    Поднять пол — самый тихий способ спрятать новое нарушение: гейт останется
    зелёным, а долг вырастет. Поймано мутацией: 356 -> 357 проходило и гейт, и
    тесты. Равенство красит в обе стороны — и когда долг вырос, и когда его
    вычистили, а пол забыли опустить.
    """

    def test_пол_равен_измеренному(self):
        import importlib.util

        корень = Path(__file__).resolve().parents[3]
        сп = importlib.util.spec_from_file_location(
            "гейт", корень / "scripts" / "check_verbatim.py"
        )
        гейт = importlib.util.module_from_spec(сп)
        сп.loader.exec_module(гейт)
        итог = гейт.свести(корень)
        self.assertEqual(
            гейт.ПОЛ_ЦИТАТ,
            итог["цитат"],
            "пол цитат разошёлся с измеренным: подняли, чтобы спрятать, или "
            "вычистили и забыли опустить",
        )
        self.assertEqual(гейт.ПОЛ_ИМЁН, итог["имён"], "пол имён разошёлся с измеренным")
