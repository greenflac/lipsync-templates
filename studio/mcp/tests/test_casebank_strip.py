"""Снимок в банке не должен нести своё происхождение. Проверка — на настоящем файле.

ЗАЧЕМ. Банк случаев показывают слепому оценщику: он смотрит на пиксели и не
должен узнать из метаданных, откуда снимок. Утечка не обязана называть ответ
прямо — довольно, чтобы она С НИМ КОРРЕЛИРОВАЛА: комментарий `Lavc61.3.100`
отделял видеокейс от картиночного, ни на что не глядя.

ИЗМЕРЕНО 2026-08-30 и записано в самом модуле: ни `convert("RGB")`, ни
`.copy()` НЕ роняют JPEG-комментарий — только по-настоящему новый Image чист.
PNG-чанки отваливаются сами, и первая версия выглядела исправной ровно потому,
что её пробовали на хрупком носителе.

ИЗМЕРЕНО 2026-09-06: у `strip_image` не было ни одного теста. Фикстуры —
картинки, собранные здесь же в памяти (Т4: ни сети, ни чужих файлов).
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from studio.mcp import casebank


def кадр(**info) -> bytes:
    """JPEG с заданными метаданными: носитель, а не картинка из интернета."""
    from PIL import Image

    буфер = io.BytesIO()
    Image.new("RGB", (32, 24), (90, 120, 150)).save(буфер, "JPEG", **info)
    return буфер.getvalue()


class ПроисхождениеНеЕдетВместеСоСнимком(unittest.TestCase):
    def test_комментарий_не_переживает_переупаковку(self):
        """Тот самый носитель, который пережил первую версию чистки."""
        with TemporaryDirectory() as каталог:
            итог = casebank.strip_image(
                кадр(comment=b"civitai:Lykon model=SDXL"), Path(каталог) / "a.jpg"
            )
            self.assertIn("comment", итог["stripped"])
            self.assertEqual([], итог["remaining"])

    def test_снятое_названо_поимённо_а_не_числом(self):
        """Отчёт «снято 1» не даёт перепроверить, ЧТО именно снято. Носитель
        назван, и по имени видно, был ли он тем самым."""
        with TemporaryDirectory() as каталог:
            путь = Path(каталог) / "b.jpg"
            итог = casebank.strip_image(кадр(comment=b"civitai:Lykon"), путь)
            self.assertEqual(["comment"], итог["stripped"])

            from PIL import Image

            self.assertNotIn("comment", set(Image.open(путь).info or {}))

    def test_безобидные_ключи_утечкой_не_считаются(self):
        """`jfif*` и `dpi` пишет сам формат: считать их утечкой значит объявить
        утечкой каждый JPEG на свете."""
        with TemporaryDirectory() as каталог:
            итог = casebank.strip_image(кадр(), Path(каталог) / "c.jpg")
            self.assertEqual([], итог["stripped"])
            self.assertEqual([], итог["remaining"])

    def test_список_безобидных_ключей_литералом(self):
        """Т2. Список обязан только СОКРАЩАТЬСЯ: дописать в него `comment` —
        это способ пройти проверку, не перестав нести происхождение."""
        self.assertEqual(
            {"jfif", "jfif_version", "jfif_unit", "jfif_density", "dpi"},
            set(casebank.ALLOWED_INFO_KEYS),
        )

    def test_файл_действительно_написан_и_читается(self):
        """П3: смотрим на произведённое, а не только на числа о нём."""
        from PIL import Image

        with TemporaryDirectory() as каталог:
            путь = Path(каталог) / "d.jpg"
            итог = casebank.strip_image(кадр(comment=b"x"), путь)
            self.assertTrue(путь.is_file())
            self.assertEqual(итог["bytes"], путь.stat().st_size)
            self.assertEqual((32, 24), Image.open(путь).size)


if __name__ == "__main__":
    unittest.main()
