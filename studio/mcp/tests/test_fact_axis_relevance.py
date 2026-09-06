"""Ретривер ошибается двумя разными способами, и они не сворачиваются в одно.

ЗАЧЕМ. Отношение строки к требованию решается по словам, значит бывает
подобрана строка «про другое, но со схожими словами» (ложный подбор) и
пропущена относящаяся, сказанная иначе (пропуск).

Разница дорогая: ПРОПУСК молча превращает `не годно` в `не смогли`, то есть
прячет известный отказ. Ложный подбор расширяет основание, а не подменяет его,
и держится под наблюдением ЧИСЛОМ — сверка идёт на РАВЕНСТВО, а не на «не
больше»: потолок «не больше» можно поднять до 500 зелёным, и это наблюдалось.

ИЗМЕРЕНО 2026-09-06 независимой приёмкой: константу сторожит собственный шаг
гейта (подмена в обе стороны даёт код 1), но ни один юнит-тест её не касался,
и развилка `relevance_verdict` проверялась только через живой прогон.

Ожидаемое — литералы (Т2), сети и диска нет (Т4, Т5).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_fact_axis", Path(__file__).resolve().parents[3] / "scripts" / "check_fact_axis.py"
)
assert _SPEC and _SPEC.loader
ось = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ось)


def пара(*, got: bool, expected: bool, model: str = "kling-3.0") -> dict:
    return {
        "got": got,
        "expected": expected,
        "model": model,
        "attribute": "max_seconds",
        "requirement": "как долго держится ролик",
    }


def набор(ложных: int, пропусков: int = 0, верных: int = 5) -> list[dict]:
    return (
        [пара(got=True, expected=False) for _ in range(ложных)]
        + [пара(got=False, expected=True) for _ in range(пропусков)]
        + [пара(got=True, expected=True) for _ in range(верных)]
    )


class ДваСпособаОшибитьсяСчитаютсяПорознь(unittest.TestCase):
    def test_измеренное_число_ложных_это_годно(self):
        итог = ось.relevance_verdict(набор(ось.FALSE_PICKUPS_MEASURED))
        self.assertEqual("pass", итог["outcome"])
        self.assertEqual(ось.FALSE_PICKUPS_MEASURED, итог["false_pickups"])
        self.assertEqual(0, итог["misses"])

    def test_число_ложных_ВЫРОСЛО_это_не_годно(self):
        итог = ось.relevance_verdict(набор(ось.FALSE_PICKUPS_MEASURED + 1))
        self.assertEqual("fail", итог["outcome"])
        self.assertIn("считать своим то, что про другое", итог["note"])

    def test_число_ложных_УПАЛО_это_тоже_не_годно(self):
        """Сверка на РАВЕНСТВО. Падение — событие: ретривер стал подбирать
        меньше чужого, число надо перемерить и записать, а не оставить слаком.
        Потолок «не больше» сторожил бы только одну сторону."""
        итог = ось.relevance_verdict(набор(ось.FALSE_PICKUPS_MEASURED - 1))
        self.assertEqual("fail", итог["outcome"])
        self.assertIn("перемерить", итог["note"])

    def test_пропуск_краснит_даже_при_измеренном_числе_ложных(self):
        """Пропуск прячет известный отказ — он красит независимо от ложных."""
        итог = ось.relevance_verdict(набор(ось.FALSE_PICKUPS_MEASURED, пропусков=1))
        self.assertEqual("fail", итог["outcome"])
        self.assertEqual(1, итог["misses"])
        self.assertTrue(any("пропущена относящаяся" in b for b in итог["problems"]))

    def test_пустой_набор_это_третий_исход(self):
        """Р1: ретривер, не проверенный ничем, — не «годно»."""
        итог = ось.relevance_verdict([])
        self.assertEqual("could not measure", итог["outcome"])
        self.assertEqual(0, итог["checked"])
        self.assertEqual(1, итог["unmeasured"])

    def test_измеренное_число_названо_литералом(self):
        """Т2. ИЗМЕРЕНО 2026-09-02 на 19 размеченных руками парах: ровно 4."""
        self.assertEqual(4, ось.FALSE_PICKUPS_MEASURED)

    def test_оба_числа_печатаются_рядом(self):
        """Е3: свернуть их в одно значило бы потерять разницу между «поверил
        лишнему» и «не увидел своего»."""
        итог = ось.relevance_verdict(набор(ось.FALSE_PICKUPS_MEASURED, пропусков=2))
        self.assertIn("false_pickups", итог)
        self.assertIn("misses", итог)
        self.assertEqual(2, итог["misses"])


if __name__ == "__main__":
    unittest.main()
