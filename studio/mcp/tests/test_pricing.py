"""Разбор цен: достаёт ли числа и молчит ли там, где не вышло.

Ожидаемое — литералы (Т2). Сети нет (Т4).
"""

from __future__ import annotations

import unittest

from studio.pricing import parse, total, unit_and_per


class Parsing(unittest.TestCase):
    def test_a_bare_number_is_a_price(self):
        p = parse("0.112", "price_per_second_usd")
        self.assertEqual(p.amount, 0.112)
        self.assertEqual(p.unit, "usd")
        self.assertEqual(p.outcome, "годно")

    def test_dollars_beat_credits_in_the_same_line(self):
        """«12 credits/s ($0.12/s at $0.01 per credit)» — доллар уже пересчитан
        вендором и ближе к тому, что платят."""
        p = parse("12 credits/s ($0.12/s at $0.01 per credit)", "price_per_second")
        self.assertEqual(p.amount, 0.12)
        self.assertEqual(p.unit, "usd")

    def test_credits_without_dollars_stay_credits(self):
        p = parse("5 credits/s", "price_per_second")
        self.assertEqual(p.amount, 5.0)
        self.assertEqual(p.unit, "credits")
        self.assertIn("НЕ ПЕРЕВОДЯТСЯ", p.note)

    def test_a_line_with_conditions_is_marked(self):
        """«40 с звуком, 20 без» — одно число не описывает цену."""
        p = parse("40 credits/s with audio, 20 credits/s without", "price_per_second")
        self.assertTrue(p.conditional)

    def test_a_plain_line_is_not_marked_conditional(self):
        self.assertFalse(parse("5 credits/s", "price_per_second").conditional)

    def test_a_line_without_numbers_is_the_third_outcome(self):
        p = parse("см. страницу тарифов", "price")
        self.assertEqual(p.outcome, "не смогли")
        self.assertIsNone(p.amount)

    def test_an_empty_value_is_the_third_outcome_too(self):
        self.assertEqual(parse("", "price").outcome, "не смогли")


class UnitFromAttributeName(unittest.TestCase):
    def test_the_unit_comes_from_the_attribute_not_the_text(self):
        """Имя атрибута — то, о чём договорились; текст пишет источник как хочет."""
        self.assertEqual(unit_and_per("price_per_second_usd"), ("usd", "second"))

    def test_per_what_is_read_too(self):
        self.assertEqual(unit_and_per("price_per_image_usd")[1], "image")

    def test_an_unknown_attribute_yields_empty_not_a_guess(self):
        self.assertEqual(unit_and_per("price_relative"), ("", ""))


class Total(unittest.TestCase):
    def test_credits_are_never_added_to_dollars(self):
        """Разные единицы — разные слагаемые; сложить их значит получить число,
        которое ничего не означает."""
        сумма = total(
            [parse("0.10", "price_per_second_usd"), parse("5 credits/s", "price_per_second")]
        )
        self.assertEqual(len(сумма["lower_bound"]), 2)

    def test_the_same_unit_adds_up(self):
        сумма = total(
            [parse("0.10", "price_per_second_usd"), parse("0.20", "price_per_second_usd")]
        )
        self.assertAlmostEqual(сумма["lower_bound"][("usd", "second")], 0.30)

    def test_unknown_terms_are_counted_not_hidden(self):
        """Е3: сумма, где треть слагаемых неизвестна, читается как полная."""
        сумма = total([parse("0.10", "price_per_second_usd"), parse("см. сайт", "price")])
        self.assertEqual(сумма["unknown"], 1)
        self.assertIn("неизвестных слагаемых 1", сумма["note"])

    def test_nothing_parsed_is_could_not_measure(self):
        self.assertEqual(total([parse("см. сайт", "price")])["outcome"], "не смогли")

    def test_an_empty_list_is_could_not_measure(self):
        self.assertEqual(total([])["outcome"], "не смогли")

    def test_the_bound_is_called_lower_not_total(self):
        """Имя поля — часть честности: это НЕ полная стоимость."""
        self.assertIn("lower_bound", total([parse("0.10", "price_per_second_usd")]))
        self.assertIn("не менее", total([parse("0.10", "price_per_second_usd")])["note"])


class ЗаЧтоЭтоЧастьВеличины(unittest.TestCase):
    """«$3 за минуту» и «$0.5 за картинку» не складываются в одно число.

    ИЗМЕРЕНО 2026-09-05 на живой базе: 34 годные цены из 214 не имеют «за
    что» — каждая шестая. До правки они попадали в общий мешок и суммировались,
    а рядом печаталось «неизвестных слагаемых 0».
    """

    def test_цена_без_за_что_не_слагаемое_а_неизвестное(self):
        сумма = total([parse("0.10", "price_per_second_usd"), parse("$3", "price")])
        self.assertEqual(сумма["unknown"], 1, "«за что» не выведено — это неизвестное")
        self.assertIn("неизвестных слагаемых 1", сумма["note"])
        self.assertNotIn("за ?", сумма["note"])

    def test_две_цены_без_за_что_не_складываются_между_собой(self):
        сумма = total([parse("$3", "price"), parse("$0.5", "price")])
        self.assertEqual(сумма["unknown"], 2)
        self.assertEqual(сумма["outcome"], "не смогли")

    def test_цены_с_одинаковым_за_что_по_прежнему_складываются(self):
        """Негативный контроль (И5): починка не смеет разучить складывать —
        иначе продукт перестанет отвечать на вопрос «сколько это стоит»."""
        сумма = total(
            [parse("0.10", "price_per_second_usd"), parse("0.20", "price_per_second_usd")]
        )
        self.assertEqual(сумма["unknown"], 0)
        self.assertIn("0.3 usd за second", сумма["note"])


if __name__ == "__main__":
    unittest.main()
