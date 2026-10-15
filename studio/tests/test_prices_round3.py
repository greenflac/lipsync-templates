"""Находки независимого валидатора 2026-10-15 о ценах — каждая литералом (Т2).

1. «$a, $b, $c for 1080p, 2K, 4K respectively» — разрешения по порядку; режим
   «in `pro` mode … N times» — условный тариф, а не цена по умолчанию.
2. Цена считается по МАРШРУТУ (кто продаёт прогон); расхождения источников
   одного маршрута печатаются, а не съедаются молча «дороже».
3. «$0.08 per 1K characters» — тысяча знаков, а не токены.
4. Единица биллинга fal «units» — не прогон; хвост `_via_runwayml` — не «run».

Сети нет (Т4): факты синтетические, кроме одной сверки ФОРМЫ живой базы.
Константы-решения проверяются в обе стороны (Т1): подменённая константа
обязана менять ответ.
"""

from __future__ import annotations

import re
import unittest
from unittest import mock

import studio.planner as pn
from scripts import sync_fal_catalog as S
from studio import pricing
from studio.selfrag.facts import Fact, load_facts

BYTEDANCE = (
    "Upscaling to 1080p costs $0.0072/s, 2K costs $0.0144/s, and 4K costs $0.0288/s, at a "
    "30fps rate. Processing at 60fps doubles the cost for any resolution. Processing in `pro` "
    "mode makes the price 10 times of the normal price ($0.072/s, $0.144/s, $0.288/s for "
    "1080p,2K, 4K at 30fps respectively, at 60fps these prices are further doubled.)"
)
FLUX_UPSCALE = (
    "Billing is calculated per second of output video, by resolution and mode. In precise "
    "mode, 1080p costs $0.14 per second, 2K costs $0.25 per second, and 4K costs $0.55 per "
    "second. Creative mode costs more at each tier: $0.20, $0.35, and $0.79 per second "
    "respectively. A 10-second 1080p clip runs $1.40 in precise mode or $2.00 in creative mode."
)

ЛИТЛЛМ = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)


def факт(model: str, attribute: str, value: str, tier: str, url: str) -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=url,
        tier=tier,
        stated_on="2026-10-14",
    )


ELEVEN_V3: tuple[Fact, ...] = (
    факт(
        "eleven_v3",
        "price_per_character_usd_via_elevenlabs",
        "$0.00018",
        "portal",
        ЛИТЛЛМ,
    ),
    факт(
        "eleven_v3",
        "price_per_1000_chars",
        "$0.1",
        "portal",
        "https://fal.ai/models/fal-ai/elevenlabs/tts/eleven-v3",
    ),
    факт(
        "eleven_v3",
        "price_per_1000_chars",
        "$0.08 per 1K characters (API)",
        "vendor",
        "https://elevenlabs.io/pricing/api",
    ),
)

SYNC_LIPSYNC: tuple[Fact, ...] = (
    факт(
        "sync-lipsync",
        "price_per_minute",
        "Your request will cost $3 per minute of video.",
        "portal",
        "https://fal.ai/models/fal-ai/sync-lipsync",
    ),
    факт(
        "sync-lipsync",
        "price_unit_minute_usd",
        "$0.7 per minute",
        "portal",
        "https://fal.ai/models/fal-ai/sync-lipsync",
    ),
)


class ПоПорядкуИРежим(unittest.TestCase):
    def test_bytedance_разрешения_по_порядку_и_pro_условный(self) -> None:
        self.assertEqual(
            [
                (0.0072, "second", "", (1080,), False),
                (0.0144, "second", "", (1440,), False),
                (0.0288, "second", "", (2160,), False),
                (0.072, "second", "pro", (1080,), True),
                (0.144, "second", "pro", (1440,), True),
                (0.288, "second", "pro", (2160,), True),
            ],
            [
                (r.amount, r.per, r.tier, r.resolutions, r.conditional)
                for r in pricing.rates(BYTEDANCE, "price")
            ],
        )

    def test_bytedance_1080p_десять_секунд(self) -> None:
        варианты = pricing.estimate(
            pricing.rates(BYTEDANCE, "price"), pricing.Need(seconds=10, resolution=1080)
        )
        self.assertEqual(
            [("", 0.072, False), ("pro", 0.72, True)],
            [(o.tier, o.usd, o.conditional) for o in варианты],
        )

    def test_pro_не_цена_по_умолчанию_в_плане(self) -> None:
        ф = факт(
            "bytedance-upscaler-upscale-video",
            "price",
            BYTEDANCE,
            "portal",
            "https://fal.ai/models/fal-ai/bytedance-upscaler/upscale/video",
        )
        с = pn.стоимость([ф], pricing.Need(seconds=10, resolution=1080, images=0.0))
        assert с is not None
        self.assertEqual(("", 0.072, "fal"), (с.default.tier, с.default.usd, с.route))
        self.assertEqual(
            "0.07 usd за шаг: через fal — [1080p] 10 с × 0.0072 usd/с = 0.07 usd", с.словами()
        )

    def test_список_без_разрешений_берёт_их_у_предыдущих_ставок(self) -> None:
        self.assertEqual(
            [
                (0.14, "precise", (1080,), False),
                (0.25, "precise", (1440,), False),
                (0.55, "precise", (2160,), False),
                (0.2, "creative", (1080,), True),
                (0.35, "creative", (1440,), True),
                (0.79, "creative", (2160,), True),
            ],
            [
                (r.amount, r.tier, r.resolutions, r.conditional)
                for r in pricing.rates(FLUX_UPSCALE, "price_per_second_usd")
            ],
        )

    def test_число_разрешений_не_сошлось_не_сопоставляется(self) -> None:
        self.assertEqual(
            [(0.1, ()), (0.2, (720,))],
            [
                (r.amount, r.resolutions)
                for r in pricing.rates("$0.1/s, $0.2/s for 720p respectively", "price")
            ],
        )

    def test_режим_дешевле_не_условный(self) -> None:
        ставки = pricing.rates("In draft mode $0.05 per second", "price")
        self.assertEqual([("draft", False)], [(r.tier, r.conditional) for r in ставки])


class ТысячаЗнаков(unittest.TestCase):
    def test_per_1k_characters_это_тысяча_знаков(self) -> None:
        self.assertEqual(
            [(0.08, "1000_chars")],
            [
                (r.amount, r.per)
                for r in pricing.rates("$0.08 per 1K characters (API)", "price_per_1000_chars")
            ],
        )

    def test_per_1m_characters_в_тысячу_раз_мельче(self) -> None:
        self.assertEqual(
            [(0.1, "1000_chars")],
            [(r.amount, r.per) for r in pricing.rates("$100 per 1M characters", "price")],
        )

    def test_per_1k_tokens_по_прежнему_не_цена_шага(self) -> None:
        self.assertEqual([], pricing.rates("$0.08 per 1K tokens", "price"))
        self.assertEqual([], pricing.rates("$5 per 1M tokens", "price"))

    def test_оценка_eleven_v3_у_вендора(self) -> None:
        варианты = pricing.estimate(
            pricing.rates("$0.08 per 1K characters (API)", "price_per_1000_chars"),
            pricing.Need(chars=450),
        )
        self.assertEqual([0.036], [o.usd for o in варианты])


class ЦенаПоМаршруту(unittest.TestCase):
    def test_eleven_v3_прямой_маршрут_и_расхождение(self) -> None:
        с = pn.стоимость(ELEVEN_V3, pricing.Need(seconds=30, chars=1000))
        assert с is not None
        self.assertEqual(("elevenlabs", 0.08), (с.route, с.default.usd))
        self.assertEqual([("fal", 0.1)], [(м, o.usd) for м, o in с.other_routes])
        self.assertEqual(
            [
                "elevenlabs: 0.08 usd (vendor: price_per_1000_chars = $0.08 per 1K characters "
                "(API)) против 0.18 usd (LiteLLM: price_per_character_usd_via_elevenlabs = "
                "$0.00018) — в смету взято 0.08 usd (ступень vendor)"
            ],
            list(с.contradictions),
        )
        self.assertTrue(с.словами().startswith("0.08 usd за шаг: через elevenlabs — "))
        self.assertIn("; другие маршруты: fal 0.1 usd; ИСТОЧНИКИ РАСХОДЯТСЯ: ", с.словами())

    def test_без_вендора_побеждает_маршрут_со_своей_страницей(self) -> None:
        с = pn.стоимость(ELEVEN_V3[:2], pricing.Need(seconds=30, chars=1000))
        assert с is not None
        self.assertEqual(("fal", 0.1), (с.route, с.default.usd))
        self.assertEqual([("elevenlabs", 0.18)], [(м, o.usd) for м, o in с.other_routes])
        self.assertEqual((), с.contradictions)

    def test_sync_lipsync_расхождение_одной_страницы_названо(self) -> None:
        с = pn.стоимость(SYNC_LIPSYNC, pricing.Need(seconds=60))
        assert с is not None
        self.assertEqual(("fal", 3.0), (с.route, с.default.usd))
        self.assertEqual(
            [
                "fal: 3 usd (portal: price_per_minute = Your request will cost $3 per minute "
                "of video.) против 0.7 usd (portal: price_unit_minute_usd = $0.7 per minute) — "
                "в смету взято 3 usd (ступень portal, из равных по ступени — дороже)"
            ],
            list(с.contradictions),
        )

    def test_порог_расхождения_в_обе_стороны(self) -> None:
        with mock.patch.object(pn, "РАСХОЖДЕНИЕ", 0.9):
            с = pn.стоимость(SYNC_LIPSYNC, pricing.Need(seconds=60))
            assert с is not None
            self.assertEqual((), с.contradictions)
        with mock.patch.object(pn, "РАСХОЖДЕНИЕ", 0.7):
            с = pn.стоимость(SYNC_LIPSYNC, pricing.Need(seconds=60))
            assert с is not None
            self.assertEqual(1, len(с.contradictions))

    def test_маршрут_хоста_в_обе_стороны(self) -> None:
        self.assertEqual(("fal", "portal"), pn.маршрут(ELEVEN_V3[1]))
        self.assertEqual(("elevenlabs", "LiteLLM"), pn.маршрут(ELEVEN_V3[0]))
        with mock.patch.dict(pn.МАРШРУТ_ХОСТА, {"fal.ai": "elevenlabs"}):
            self.assertEqual(("elevenlabs", "portal"), pn.маршрут(ELEVEN_V3[1]))
            с = pn.стоимость(ELEVEN_V3, pricing.Need(seconds=30, chars=1000))
            assert с is not None
            self.assertEqual((), с.other_routes)
        with mock.patch.dict(pn.МАРШРУТ_VIA, {"elevenlabs": "fal"}):
            self.assertEqual(("fal", "LiteLLM"), pn.маршрут(ELEVEN_V3[0]))

    def test_смета_называет_маршрут(self) -> None:
        с = pn.стоимость(ELEVEN_V3, pricing.Need(seconds=30, chars=1000))
        assert с is not None
        озвучка = next(о for о in pn.OPERATIONS if о.name == "озвучка")
        к = pn.Candidate("eleven_v3", (), 0, 1, 0, "", cost=с)
        итог = pn.смета_ролика({"note": "n"}, [(озвучка, к)], 30.0, None, (), False)
        шаг = итог["смета"]["steps"][0]
        self.assertEqual("elevenlabs", шаг["route"])
        self.assertEqual([{"route": "fal", "usd": 0.1}], шаг["other_routes"])
        self.assertEqual(1, len(шаг["contradictions"]))
        self.assertIn("озвучка eleven_v3 через elevenlabs: ", итог["note"])


class ЕдиницыИмпорта(unittest.TestCase):
    def test_units_у_fal_не_прогон(self) -> None:
        self.assertEqual("price_unit_usd", S.атрибут_цены_биллинга("units"))
        with mock.patch.dict(S.ЗА_ЧТО, {"units": "run"}):
            self.assertEqual("price_unit_run_usd", S.атрибут_цены_биллинга("units"))

    def test_находка_страницы_с_units(self) -> None:
        разбор = {
            "status": "public",
            "pricingInfoOverride": "",
            "deprecated": False,
            "removed": False,
            "hidePricing": False,
            "billing": {"unit": "units", "price": 1.0},
        }
        находки, _ = S.находки_страницы(
            "gpt-image-2.5-flare",
            "openai/gpt-image-2.5/flare/text-to-image",
            "text-to-image",
            разбор,
            None,
        )
        цена = [н for н in находки if н.атрибут.startswith("price")]
        self.assertEqual(
            [("price_unit_usd", "$1 per unit (billing unit 'units')")],
            [(н.атрибут, н.значение) for н in цена],
        )
        self.assertEqual(
            [],
            pricing.estimate(
                pricing.rates(цена[0].значение, цена[0].атрибут),
                pricing.Need(seconds=10, images=1.0),
            ),
        )

    def test_живая_база_без_прогона_за_unit(self) -> None:
        стоят = [
            f
            for f in load_facts()
            if f.attribute == "price_unit_run_usd" and re.fullmatch(r"\$\S+ per unit", f.value)
        ]
        self.assertEqual([], [(f.model, f.value) for f in стоят])
        flare = [
            f.value
            for f in load_facts()
            if f.model == "gpt-image-2.5-flare" and f.attribute == "price_unit_usd"
        ]
        self.assertEqual(["$1 per unit (billing unit 'units')"], flare)

    def test_хвост_via_не_единица(self) -> None:
        self.assertEqual(
            ("usd", "character"), pricing.unit_and_per("price_per_character_usd_via_runwayml")
        )
        self.assertEqual(("usd", "second"), pricing.unit_and_per("price_per_second_usd_via_fal_ai"))


if __name__ == "__main__":
    unittest.main()
