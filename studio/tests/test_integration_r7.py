"""Интеграция седьмого круга: то, что ломалось на СТЫКЕ веток knowledge/safety/routes."""

from __future__ import annotations

import unittest

from studio.pricing import rates


def _ставки(текст: str, атрибут: str = "") -> list[tuple[float, str]]:
    return [(round(r.amount, 6), r.per) for r in rates(текст, атрибут)]


class ЗаМиллионЗнаков(unittest.TestCase):
    """«$30 per 1 million characters» — это $0.03 за 1000 знаков, не $30000."""

    def test_один_миллион_словом(self) -> None:
        self.assertEqual([(0.03, "1000_chars")], _ставки("$30 per 1 million characters"))

    def test_миллион_без_единицы(self) -> None:
        self.assertEqual([(0.03, "1000_chars")], _ставки("$30 per million characters"))

    def test_миллион_цифрами(self) -> None:
        self.assertEqual([(0.011, "1000_chars")], _ставки("about $11.00 per 1,000,000 characters"))

    def test_1m_как_было(self) -> None:
        self.assertEqual([(0.015, "1000_chars")], _ставки("$15.00 / 1M characters"))

    def test_тысяча_не_задета(self) -> None:
        self.assertEqual([(0.08, "1000_chars")], _ставки("$0.08 per 1K characters (API)"))
        self.assertEqual([(2.4, "1000_chars")], _ставки("$0.24 per 100 characters"))

    def test_миллион_токенов_по_прежнему_не_ставка(self) -> None:
        self.assertEqual([], _ставки("$1.25 per 1 million tokens"))

    def test_записанная_цена_chirp(self) -> None:
        """Запись базы, на которой ошибка была видна: вторая запись числа не дублирует первую."""
        текст = (
            "$0.03 per 1,000 characters (US$0.00003 per character, US$30 per 1 million "
            "characters; first 1 million characters per month free)"
        )
        for сумма, за in _ставки(текст, "price_per_1000_chars"):
            self.assertEqual("1000_chars", за)
            self.assertLess(сумма, 1.0)


if __name__ == "__main__":
    unittest.main()
