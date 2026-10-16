"""Восьмой круг, агент C: требования до цены, ступени цены, строки о языке.

Каждая находка валидатора v8 — литералом (Т2): x17/w15 (8K у апскейлера,
чьи ступени кончаются на 4K), x25/w24 (дубляж с округлением до минуты),
n33 (gpt-image по заказанному размеру), n08/x35/w34/n14 (4K родным).

Т4: сети нет — живая база читается из репозитория.
"""

from __future__ import annotations

import unittest

from studio import planner as pn
from studio import pricing
from studio.selfrag.facts import load_facts

_FACTS = None


def _строки(модель: str) -> list:
    global _FACTS
    if _FACTS is None:
        _FACTS = load_facts()
    return [f for f in _FACTS if f.model == модель]


BYTEDANCE = (
    "Upscaling to 1080p costs $0.0072/s, 2K costs $0.0144/s, and 4K costs $0.0288/s, at a 30fps "
    "rate. Processing at 60fps doubles the cost for any resolution."
)


class ЗаказВышеВсехСтупеней(unittest.TestCase):
    """x17/w15: 8K у апскейлера, чьи ступени кончаются на 4K."""

    def test_голая_ставка_не_обгоняет_верхнюю_ступень(self) -> None:
        ставки = pricing.rates(BYTEDANCE, "price") + pricing.rates(
            "$0.0072 per second", "price_unit_second_usd"
        )
        варианты = pricing.estimate(ставки, pricing.Need(seconds=120, resolution=4320))
        self.assertEqual([(3.456, 2160)], [(o.usd, o.resolution) for o in варианты])
        self.assertIn("2160p — максимум тарифов эндпоинта: 4320p", варианты[0].formula)

    def test_ставка_отдельной_строкой_и_общий_верх(self) -> None:
        (голая,) = pricing.estimate(
            pricing.rates("$0.0072 per second", "price_unit_second_usd"),
            pricing.Need(seconds=120, resolution=4320),
            2160,
        )
        self.assertEqual(pricing.UNTIERED_ABOVE_TOP, голая.fit[0])
        self.assertEqual(4, pricing.UNTIERED_ABOVE_TOP)

    def test_внутри_ступеней_голая_по_прежнему_не_названа(self) -> None:
        (голая,) = pricing.estimate(
            pricing.rates("$0.0072 per second", "price_unit_second_usd"),
            pricing.Need(seconds=120, resolution=1080),
            2160,
        )
        self.assertEqual(1, голая.fit[0])

    def test_живая_база_bytedance_8k(self) -> None:
        сколько = pn.стоимость(
            _строки("bytedance-upscaler-upscale-video"), pricing.Need(seconds=120, resolution=4320)
        )
        assert сколько is not None
        self.assertEqual((3.456, 2160), (сколько.default.usd, сколько.default.resolution))

    def test_живая_база_bytedance_4k_как_было(self) -> None:
        сколько = pn.стоимость(
            _строки("bytedance-upscaler-upscale-video"), pricing.Need(seconds=120, resolution=2160)
        )
        assert сколько is not None
        self.assertEqual((3.456, 2160), (сколько.default.usd, сколько.default.resolution))


class ОкруглениеДоМинуты(unittest.TestCase):
    """x25: 30 с дубляжа стоят минуту; w24: округление в каждом языке."""

    def test_без_артикля(self) -> None:
        (r,) = pricing.rates("$0.6, rounded up to closest minute", "price_per_minute")
        self.assertEqual((0.6, "minute", 1.0), (r.amount, r.per, r.block))

    def test_после_округления_вверх(self) -> None:
        (r,) = pricing.rates(
            "Your request will cost $0.6 per minute. The calculation will be based on the closest "
            "minute after rounding upwards.",
            "price_per_minute",
        )
        self.assertEqual(1.0, r.block)

    def test_минута_без_слов_об_округлении_линейна(self) -> None:
        (r,) = pricing.rates("$0.6 per minute", "price_unit_minute_usd")
        self.assertIsNone(r.block)

    def test_x25_тридцать_секунд(self) -> None:
        сколько = pn.стоимость(_строки("elevenlabs-dubbing"), pricing.Need(seconds=30))
        assert сколько is not None
        self.assertEqual(0.6, сколько.default.usd)

    def test_w24_два_языка_по_90_секунд(self) -> None:
        сколько = pn.стоимость(_строки("elevenlabs-dubbing"), pricing.Need(seconds=180, jobs=2))
        assert сколько is not None
        self.assertEqual(2.4, сколько.default.usd)

    def test_нужда_шага_дубляжа_на_два_языка(self) -> None:
        op = next(o for o in pn.OPERATIONS if o.name == "дубляж")
        need = pn.нужда_шага(op, pn.dur.Запрос(90.0, "90 с"), None, языков=2, языки=("pl", "tr"))
        self.assertEqual((180.0, 2), (need.seconds, need.jobs))


class КартинкаПоЗаказанномуРазмеру(unittest.TestCase):
    """gpt-image: голая сумма — ступень `high 1024x768`, а не цена 4K."""

    def test_4k(self) -> None:
        сколько = pn.стоимость(
            _строки("gpt-image-2.5-flare"), pricing.Need(resolution=2160, images=1.0)
        )
        assert сколько is not None
        self.assertEqual(("high", 2160, 0.1001), (сколько.default.tier, сколько.default.resolution, сколько.default.usd))

    def test_1080(self) -> None:
        сколько = pn.стоимость(
            _строки("gpt-image-2.5-flare"), pricing.Need(resolution=1080, images=1.0)
        )
        assert сколько is not None
        self.assertEqual(("high", 1080, 0.0396), (сколько.default.tier, сколько.default.resolution, сколько.default.usd))

    def test_размер_не_заказан_умолчание_прежнее(self) -> None:
        сколько = pn.стоимость(_строки("gpt-image-2.5-flare"), pricing.Need(images=1.0))
        assert сколько is not None
        self.assertEqual(("", 0.0361), (сколько.default.tier, сколько.default.usd))


if __name__ == "__main__":
    unittest.main()
