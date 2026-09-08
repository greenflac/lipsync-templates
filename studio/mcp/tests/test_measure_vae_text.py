"""Прибор «прошёл ли текст через модель»: ложная чистота дороже отказа судить.

ЗАЧЕМ. Ничто в крае буквы не доказывает, что текст НЕ проходил через модель:
модель, воспроизводящая вход точно, оставляет край неотличимым. Поэтому у
прибора два честных исхода — «за пределом самого грязного чистого контроля» и
«не смогли», а `pass` не предусмотрен вовсе.

ДЕФЕКТ, РАДИ КОТОРОГО ЕСТЬ ПОРОГ ШТРИХА: прибор сравнивал ВЫСОТУ РАМКИ вместо
толщины штриха, легко переваливал порог и отвечал «признаков модели нет» про
картинку, о которой было ИЗВЕСТНО, что она через модель прошла. Ложная чистота
хуже отсутствия ответа: чистое никто не перепроверяет.

ИЗМЕРЕНО 2026-09-06 независимой приёмкой: я объявил модуль непокрываемым «без
картинок» — и ошибся, он рисует их сам (`_render`). Ни сети, ни диска (Т4).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_SPEC = importlib.util.spec_from_file_location(
    "measure_vae_text", Path(__file__).resolve().parents[3] / "scripts" / "measure_vae_text.py"
)
assert _SPEC and _SPEC.loader
прибор = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(прибор)

РАМКА = (20, 40, 880, 190)


def нарисовать(каталог: Path, cap_px: int, quality: int = 92) -> Path:
    """Собственная отрисовка прибора, сохранённая файлом: никаких чужих картинок."""
    путь = каталог / f"cap{cap_px}.jpg"
    прибор._render(quality, cap_px).convert("RGB").save(путь, "JPEG", quality=quality)
    return путь


class МелкийКегльЭтоОтказСудить(unittest.TestCase):
    def test_тонкий_штрих_даёт_третий_исход_а_не_чистоту(self):
        with TemporaryDirectory() as каталог:
            итог = прибор.judge(нарисовать(Path(каталог), 12), РАМКА)
        self.assertEqual("could not measure", итог["outcome"])
        self.assertIn("ниже порога", итог["note"])
        self.assertNotIn("нет", итог["note"].split(":")[0])

    def test_крупный_кегль_до_суждения_доходит(self):
        """Негативный контроль (И5): прибор, всегда отвечающий «не смогли» по
        толщине штриха, ничего не измеряет."""
        with TemporaryDirectory() as каталог:
            итог = прибор.judge(нарисовать(Path(каталог), 90), РАМКА)
        self.assertIn("край", итог["note"])
        self.assertIn("stroke", итог)

    def test_пороги_названы_числами(self):
        """Т2: все три взяты из измеренной пары и обязаны быть решением, а не
        значением, доехавшим вместе с кодом."""
        self.assertEqual(5, прибор.MIN_STROKE_PX)
        self.assertEqual(1.30, прибор.WIDTH_RATIO)
        self.assertEqual(4.0, прибор.OVERSHOOT_RATIO)

    def test_исхода_годно_у_прибора_НЕТ(self):
        """Главное свойство: чистоты этот прибор не устанавливает никогда."""
        with TemporaryDirectory() as каталог:
            for кегль in (12, 90):
                итог = прибор.judge(нарисовать(Path(каталог), кегль), РАМКА)
                self.assertIn(итог["outcome"], ("fail", "could not measure"), кегль)

    def test_числа_обеих_сторон_печатаются(self):
        """Е3: вердикт без чисел контроля и подозреваемого не перепроверить."""
        with TemporaryDirectory() as каталог:
            итог = прибор.judge(нарисовать(Path(каталог), 90), РАМКА)
        self.assertIn("control", итог)
        self.assertIn("suspect", итог)
        self.assertIn("width", итог["control"])


if __name__ == "__main__":
    unittest.main()
