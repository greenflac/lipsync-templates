"""Цена «за миллион токенов» не равна цене «за токен».

ВОСПРОИЗВЕДЕНО 2026-09-05 независимым аудитом на живой базе. Строка
`gpt-5.price_per_token` = «$1.25 per 1M input tokens, $0.125 per 1M cached
input, $10.00 per 1M output tokens». Разбор брал «за что» из ИМЕНИ атрибута
(`token`), а число — из текста (1.25), и получал:

    Price(amount=1.25, unit='usd', per='token')
    вердикт валидатора: не годно — «нижняя известная цена 1.25 usd за token
    выше потолка 0.5»

Ошибка в МИЛЛИОН РАЗ, и на ней продукт отвергает шаг. Заказчику это звучит как
«gpt-5 стоит доллар с четвертью за токен» — уверенно и неверно.

ЧТО СЧИТАЕТСЯ ПОЧИНКОЙ. Не деление на 10⁶ втихую: мы не знаем, к какому именно
токену вендор отнёс цену, и придумывать пересчёт значило бы заменить одно
уверенное неверное число другим. Правильный ответ — назвать НАСТОЯЩЕЕ «за
что» (`1m_tokens`), и тогда сравнение с потолком «за токен» честно станет
несравнимым, то есть третьим исходом вместо ложного отказа.

Ожидаемые значения — литералы (Т2).
"""

from __future__ import annotations

import unittest

from studio import pipeline as pl
from studio import pricing
from studio.selfrag.facts import Fact

ЗА_МИЛЛИОН = "1m_tokens"
ЗА_ТОКЕН = "token"


class ЦенаЗаМиллион(unittest.TestCase):
    def test_текст_про_1M_меняет_за_что(self) -> None:
        цена = pricing.parse(
            "$1.25 per 1M input tokens, $0.125 per 1M cached input, $10.00 per 1M output tokens",
            "price_per_token",
        )
        self.assertEqual(цена.per, ЗА_МИЛЛИОН)
        self.assertEqual(цена.amount, 1.25)

    def test_слово_million_тоже_считается(self) -> None:
        цена = pricing.parse("$2.00 per million output tokens", "price_per_token")
        self.assertEqual(цена.per, ЗА_МИЛЛИОН)

    def test_имя_атрибута_с_миллионом_разбирается(self) -> None:
        """Шесть строк базы названы честно (`price_per_million_input_usd`) и
        раньше теряли «за что» вовсе, уходя в третий исход."""
        единица, за = pricing.unit_and_per("price_per_million_input_usd")
        self.assertEqual(единица, "usd")
        self.assertEqual(за, ЗА_МИЛЛИОН)

    def test_настоящая_цена_за_токен_не_переехала(self) -> None:
        """Негативный контроль (И5): строка без миллиона остаётся за токен."""
        цена = pricing.parse("$0.000002 per token", "price_per_token")
        self.assertEqual(цена.per, ЗА_ТОКЕН)

    def test_валидатор_больше_не_отвергает_по_ложной_цене(self) -> None:
        факт = Fact(
            model="gpt-5",
            attribute="price_per_token",
            value="$1.25 per 1M input tokens, $10.00 per 1M output tokens",
            source_url="https://platform.openai.com/docs/models/gpt-5",
            tier="vendor",
            stated_on="2026-09-01",
        )
        проба = pl.probe_price(
            pl.Step(name="шаг", model="gpt-5", requirement="r", budget_usd=0.5), [факт]
        )
        self.assertNotEqual(проба.outcome, "fail", проба.note)
        self.assertIn("1m_tokens", проба.note)


if __name__ == "__main__":
    unittest.main()
