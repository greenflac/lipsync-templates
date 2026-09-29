"""Мост между русским вопросом и английской базой.

Главная опасность моста — не в том, что он мало переводит, а в том, что он
переводит слишком много: тогда негативный контроль перестаёт быть пустым и мы
получаем прибор, который на любой вход что-нибудь находит.

Ожидаемое — литералы (Т2). Сети нет (Т4).
"""

from __future__ import annotations

import unittest

from studio.factindex import FactIndex
from studio.selfrag.facts import Fact
from studio.terms import BRIDGE, bridge, bridged_words


def факт(model, value, attribute="architecture"):
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url="https://example.test/x",
        tier="vendor",
        stated_on="2026-08-31",
    )


class Bridging(unittest.TestCase):
    def test_a_domain_word_gets_its_english_twin(self):
        self.assertIn("color grade", bridge("сохранить цветокор"))

    def test_the_original_text_survives(self):
        """Спросили по-английски или назвали модель — обязано продолжать работать."""
        self.assertIn("kling-3.0", bridge("что умеет kling-3.0"))

    def test_a_word_outside_the_domain_adds_nothing(self):
        self.assertEqual(bridge("бухгалтерский учёт"), "бухгалтерский учёт")

    def test_bridged_words_are_reportable(self):
        """Читателю видно, ЧТО мост узнал, иначе его работу нечем проверить."""
        self.assertEqual(bridged_words("заменить персонажа"), ["заменить", "персонажа"])

    def test_an_empty_text_is_handled(self):
        self.assertEqual(bridge(""), "")
        self.assertEqual(bridged_words(""), [])


class TheBridgeMustNotBreakTheControls(unittest.TestCase):
    """Негативные контроли из замороженного набора — дословно."""

    КОНТРОЛИ = (
        "свести многодорожечный аудиомикс и выставить уровни",
        "бухгалтерский учёт основных средств по РСБУ",
        "зззывыдуманная-модель-которой-нет",
    )

    def test_no_control_word_is_in_the_bridge(self):
        for текст in self.КОНТРОЛИ:
            self.assertEqual(bridged_words(текст), [], f"мост тронул контроль: {текст}")

    def test_a_control_still_finds_nothing_after_bridging(self):
        индекс = FactIndex(
            [
                факт(
                    "wan-animate-replace", "replaces the character keeping lighting and color tone"
                ),
                факт("kling-3.0", "ten seconds per generation", "max_seconds"),
            ]
        )
        for текст in self.КОНТРОЛИ:
            self.assertEqual(индекс.search(bridge(текст)), [], f"контроль ожил: {текст}")


class TheBridgeActuallyHelps(unittest.TestCase):
    def test_the_russian_brief_reaches_the_english_fact(self):
        """Ровно бриф владельца: без моста он поднимал шум."""
        индекс = FactIndex(
            [
                факт(
                    "wan-animate-replace",
                    "replaces the character in a reference video, keeping lighting and color tone",
                ),
                факт("kling-3.0", "ten seconds per generation", "max_seconds"),
            ]
        )
        бриф = "заменить персонажа, сохранив цветокор и освещение"
        self.assertEqual(индекс.search(бриф), [])
        нашлось = индекс.search(bridge(бриф))
        self.assertEqual(нашлось[0].fact.model, "wan-animate-replace")


class TheGlossaryItself(unittest.TestCase):
    def test_every_key_is_lowercase_russian(self):
        """Ключ в другом регистре не сработает никогда и будет выглядеть рабочим."""
        for ключ in BRIDGE:
            self.assertEqual(ключ, ключ.lower())

    def test_no_value_is_empty(self):
        for ключ, значение in BRIDGE.items():
            self.assertTrue(значение.strip(), f"пустой перевод у {ключ}")

    def test_the_glossary_stays_readable_by_eye(self):
        """Словарь, который не прочитать целиком, правится вслепую."""
        self.assertLess(len(BRIDGE), 200)


if __name__ == "__main__":
    unittest.main()
