"""Одна модель — одно имя: написания, дробящие факты модели надвое.

ЗАЧЕМ, ИЗМЕРЕНО 2026-08-27. База держала 211 имён моделей, и пять из них были
одной моделью дважды или трижды:

    eleven-v3(6), eleven_v3(1), elevenlabs-eleven-v3(4)
    gpt-image-2(13), gpt_image_2(1)

Никто не замечает, потому что ничто не краснеет: спросивший `eleven-v3`
получает ответ по шести фактам, тогда как модель их держит одиннадцать.

Тот же дефект на именах АТРИБУТОВ дороже: `licence` против `license` — это
research-only модель, уехавшая в продакшен, потому что лицензионный факт лёг
под вторым написанием и в ответ не попал.

Обе таблицы стояли без охраны: поймано ратчетом R7 2026-09-06.
Ожидаемое — литералы (Т2), сети нет (Т4), диска не нужно (Т5).
"""

from __future__ import annotations

import importlib.util
import unittest
from dataclasses import dataclass
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "merge_model_ids",
    Path(__file__).resolve().parents[3] / "scripts" / "merge_model_ids.py",
)
assert _SPEC and _SPEC.loader
слияние = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(слияние)


@dataclass(frozen=True)
class Строка:
    model: str
    attribute: str


class ЧужоеНаписаниеСводитсяКВендорскому(unittest.TestCase):
    def test_имя_модели_сводится(self):
        self.assertEqual(("eleven_v3", "price"), слияние.canonical_of(Строка("eleven-v3", "price")))
        self.assertEqual(
            ("eleven_v3", "price"),
            слияние.canonical_of(Строка("elevenlabs-eleven-v3", "price")),
        )

    def test_имя_атрибута_сводится(self):
        """`licence` против `license`: пропущенный факт о лицензии — это
        research-only модель, уехавшая в продакшен."""
        self.assertEqual(
            ("kling-3.0", "license"), слияние.canonical_of(Строка("kling-3.0", "licence"))
        )

    def test_сводятся_оба_имени_разом(self):
        self.assertEqual(
            ("eleven_v3", "license"),
            слияние.canonical_of(Строка("eleven-v3", "licence")),
        )

    def test_незнакомое_написание_остаётся_собой(self):
        """Негативный контроль (И5): таблица, переписывающая всё подряд, слила
        бы разные модели в одну — это тот же дефект наоборот и дороже."""
        self.assertEqual(
            ("kling-3.0", "max_seconds"),
            слияние.canonical_of(Строка("kling-3.0", "max_seconds")),
        )
        self.assertEqual(
            ("eleven_v3_conversational", "price"),
            слияние.canonical_of(Строка("eleven_v3_conversational", "price")),
        )

    def test_цель_слияния_сама_не_слита(self):
        """Никакое каноническое имя не стоит слева: иначе слияние зациклится
        или уедет на третье написание, и «одно имя» перестанет быть одним."""
        for чужое, своё in слияние.MERGES.items():
            self.assertNotIn(своё, слияние.MERGES, f"{чужое} -> {своё} -> ещё дальше")
        for чужое, своё in слияние.ATTRIBUTE_MERGES.items():
            self.assertNotIn(своё, слияние.ATTRIBUTE_MERGES, f"{чужое} -> {своё}")

    def test_имя_не_сводится_само_к_себе(self):
        """Запись `x -> x` ничего не делает и читается как сделанная работа."""
        for чужое, своё in слияние.MERGES.items():
            self.assertNotEqual(чужое, своё)

    def test_атрибут_licence_в_таблице(self):
        """Литерал (Т2). Единственная запись таблицы атрибутов, и её пропажа
        молча вернула бы дефект, который дороже всех прочих в этом файле."""
        self.assertEqual({"licence": "license"}, dict(слияние.ATTRIBUTE_MERGES))


if __name__ == "__main__":
    unittest.main()
