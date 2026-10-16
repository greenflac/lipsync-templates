"""Все три объявленных типа генератора проверяются одинаково.

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ. Правило Ц2: чужие файлы не редактируются. Фикстура
соседнего `test_catalog.py` переиспользуется (Е1), а не копируется.

ЧТО ЭТО ЗАКРЫВАЕТ. Мутация «оставить в `GENERATOR_TYPES` один `text-to-video`»
2026-09-04 ПРОМОЛЧАЛА: единственная фикстура набора объявляет именно этот тип,
и два других можно было убрать незаметно. Тогда запись, объявленная
`image-to-video`, но названная операцией над готовым файлом (`eraser`,
`remove_background`), проехала бы в каталог как генератор — а каталог для
продукта это список того, чем МОЖНО СДЕЛАТЬ работу.
"""

from __future__ import annotations

import unittest

from studio.mcp import catalog
from studio.mcp.tests.test_catalog import healthy


class ВсеТриТипаСудятсяОдинаково(unittest.TestCase):
    def test_операция_над_файлом_отсекается_у_каждого_типа(self) -> None:
        for тип in ("text-to-video", "image-to-video", "text-to-image"):
            with self.subTest(тип):
                запись = healthy()
                запись["declared_type"] = тип
                запись["name"] = "acme/background_eraser"
                вердикт = catalog.classify(запись)
                self.assertEqual(catalog.REJECT, вердикт["verdict"], вердикт)
                self.assertEqual("edit_op", вердикт["rule"], вердикт)

    def test_здоровый_генератор_каждого_типа_проходит(self) -> None:
        """И5: прибор, отсекающий всё, проходит проверку «подсадные не доехали»
        на отлично и не измеряет ничего."""
        for тип in ("text-to-video", "image-to-video", "text-to-image"):
            with self.subTest(тип):
                запись = healthy()
                запись["declared_type"] = тип
                self.assertNotEqual(catalog.REJECT, catalog.classify(запись)["verdict"])

    def test_состав_типов_именно_такой(self) -> None:
        """Т2: ожидаемое литералом. Список решает, к кому применяется правило
        об операциях над готовым файлом."""
        self.assertEqual(
            ["image-to-video", "text-to-image", "text-to-video"],
            sorted(catalog.GENERATOR_TYPES),
        )


if __name__ == "__main__":
    unittest.main()
