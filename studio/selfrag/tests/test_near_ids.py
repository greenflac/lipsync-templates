"""Подсказка о соседних именах: находит ли она модель, названную по-другому.

Поймано на живом вопросе владельца 2026-08-31: он спросил про «H3 max» — так
модель называет вендор, — а в базе она лежит под `minimax-h3-max`. Общего
НАЧАЛА у строк нет («h» против «m»), и подсказка возвращала пустоту при
четырнадцати записанных фактах.

Ожидаемые значения — литералы (правило Т2). Сеть не нужна (Т4): хранилище
собирается из фактов, переданных прямо в конструктор.
"""

from __future__ import annotations

import unittest

from studio.selfrag.facts import Fact, FactStore


def факт(model: str, attribute: str = "max_seconds") -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value="15",
        source_url="https://example.test/x",
        tier="vendor",
        stated_on="2026-08-31",
    )


class Near(unittest.TestCase):
    def store(self, *models: str) -> FactStore:
        return FactStore([факт(m) for m in models])

    def test_a_product_name_finds_the_vendor_prefixed_id(self):
        """Спрашивают продуктовым именем, хранится вендорским."""
        got = self.store("minimax-h3-max", "minimax-h3", "kling-3.0").near("h3-max")
        self.assertEqual(got, ["minimax-h3-max"])

    def test_a_prefix_neighbour_still_comes_first(self):
        """Точный сосед по началу строки не должен уступать вхождению."""
        got = self.store("seedance-2.5-i2v", "byte-seedance-2.5").near("seedance-2.5")
        self.assertEqual(got[0], "seedance-2.5-i2v")

    def test_a_name_too_short_to_be_a_signal_matches_nothing(self):
        """`h3` внутри чего угодно — это шум, а не подсказка."""
        self.assertEqual(self.store("minimax-h3-max").near("h3"), [])

    def test_three_characters_are_still_noise(self):
        """Порог держится и снизу: `gen` цепляло бы половину базы."""
        base = self.store("gen4_turbo", "gen3-alpha", "kling-3.0")
        self.assertEqual(base.near("gen"), [])

    def test_an_invented_name_still_matches_nothing(self):
        """Негативный контроль: подсказка обязана уметь молчать."""
        self.assertEqual(self.store("minimax-h3-max", "kling-3.0").near("зззывыдумка"), [])

    def test_the_id_itself_is_not_offered_as_its_own_neighbour(self):
        self.assertEqual(self.store("minimax-h3-max").near("minimax-h3-max"), [])

    def test_an_empty_name_asks_nothing(self):
        self.assertEqual(self.store("minimax-h3-max").near(""), [])

    def test_the_longer_id_containing_the_question_is_found_both_ways(self):
        """Работает и когда спрошенное длиннее хранимого."""
        got = self.store("kling-3.0").near("vendor-kling-3.0-turbo")
        self.assertEqual(got, ["kling-3.0"])


if __name__ == "__main__":
    unittest.main()
