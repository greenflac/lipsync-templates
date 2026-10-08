"""«Несравнима с потолком» — это не «не записана», и заказчик видит разницу.

ВОСПРОИЗВЕДЕНО 2026-09-07 продуктовой проверкой. Один и тот же продукт на
одну и ту же модель отвечал двумя способами по-разному:

    model_advice(model="latentsync", attribute="price")
      -> pass, «$0.2 for videos up to 40 seconds, then $0.005 per second»

    plan_pipeline("... 15 секунд, для рекламы кофейни")
      -> шаг озвучка: «цена не записана (несравнимых ценовых строк 1)»

Два способа узнать известное разошлись (Е1), и заказчик получал «не смогли»
на первый свой вопрос — сколько это стоит.

ЧИСЛО РЯДОМ С ПОТОЛКОМ ПО-ПРЕЖНЕМУ НЕ СТАВИТСЯ: сравнить «за 1000 знаков» с
«за прогон» значит сложить разное, и это правило старше находки. Изменилось
одно: записанное ПЕЧАТАЕТСЯ, а исход сравнения говорится отдельно.

Т2: ожидаемое — литералы. Т3: обе стороны — строки есть / строк нет.
Т4: сети нет.
"""

from __future__ import annotations

import unittest

from studio.planner import NO_PRICE, cheapest
from studio.selfrag.facts import Fact


def _факт(атрибут: str, значение: str) -> Fact:
    return Fact(
        model="elevenlabs-tts-eleven-v3",
        attribute=атрибут,
        value=значение,
        source_url="https://fal.ai/models/x",
        tier="portal",
        stated_on="2026-09-01",
    )


class ЗаписаннаяЦенаНазываетсяВслух(unittest.TestCase):
    def test_несравнимая_цена_печатается_с_именем_атрибута(self) -> None:
        _, словами = cheapest([_факт("price_per_1000_chars", "0.1")])
        self.assertIn("ЗАПИСАНА", словами)
        self.assertIn("price_per_1000_chars = 0.1", словами)
        self.assertNotIn(NO_PRICE, словами)

    def test_имя_атрибута_обязательно(self) -> None:
        """Без имени «0.1» читается как цена ролика, а это доллары за тысячу
        знаков — разница в тысячу раз."""
        _, словами = cheapest([_факт("price_per_1000_chars", "0.1")])
        self.assertIn("price_per_1000_chars", словами)

    def test_строк_нет_вовсе_это_другое_и_сказано_другим(self) -> None:
        """Вторая сторона (И5): прибор, который всегда говорит «записана»,
        ничего не различает."""
        _, словами = cheapest([])
        self.assertEqual(NO_PRICE, словами)

    def test_сравнимая_цена_печатается_числом_как_прежде(self) -> None:
        цена, словами = cheapest([_факт("price_per_run_usd", "$0.4 per run")])
        self.assertIsNotNone(цена)
        self.assertNotIn("ЗАПИСАНА", словами)


class ПродуктНеОтрицаетТогоЧтоЗнает(unittest.TestCase):
    """П3: то, что прочитает заказчик."""

    def test_в_плане_стоит_записанная_цена_а_не_её_отрицание(self) -> None:
        import json

        from studio.mcp import server

        ответ = json.loads(
            server.plan_pipeline("нужен ролик, женщина говорит в камеру, 15 секунд, для кофейни")
        )
        озвучка = [ш for ш in ответ["steps"] if ш["step"] == "озвучка"]
        self.assertTrue(озвучка, ответ["steps"])
        цена = str((озвучка[0].get("chosen") or {}).get("price", ""))
        self.assertIn("ЗАПИСАНА", цена, цена)
        self.assertIn("price_per_1000_chars", цена, цена)


if __name__ == "__main__":
    unittest.main()
