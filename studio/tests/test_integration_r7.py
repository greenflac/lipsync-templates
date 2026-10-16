"""Интеграция седьмого круга: то, что ломалось на СТЫКЕ веток knowledge/safety/routes."""

from __future__ import annotations

import unittest
from datetime import date

import studio.planner as pn
from studio.pricing import rates
from studio.selfrag.facts import Fact


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


def _факт(model: str, attribute: str, value: str, url: str = "") -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=url or f"https://fal.ai/models/fal-ai/{model}",
        tier="vendor",
        stated_on="2026-10-01",
    )


#: Синтетика по образу живой базы (n29): `deoldify` — открытые веса, маршрут
#: один (self-host), цены нет; fal-раскраска — с ценой, но кадр до 720p.
РАСКРАСКА: tuple[Fact, ...] = (
    _факт(
        "deoldify-mini",
        "license",
        "MIT",
        "https://raw.githubusercontent.com/x/deoldify-mini/master/LICENSE",
    ),
    _факт(
        "x-colorize",
        "availability",
        "on fal.ai as fal-ai/x-colorize/colorization (video-to-video); listing status public",
    ),
    _факт("x-colorize", "price_unit_second_usd", "$0.01 per second"),
    _факт("x-colorize", "resolution_enum", "480p, 720p"),
    _факт("x-vsr", "architecture", "video upscaler (super-resolution) model"),
    _факт("x-vsr", "price_per_second_usd", "$0.02 per second"),
    _факт("x-isr", "architecture", "image upscaler (super-resolution) model"),
    _факт("x-isr", "price_per_image_usd", "$0.02 per image"),
)


def _шаги(self_host: bool) -> list[tuple[str, str | None]]:
    spec: dict = {
        "task": "colorize",
        "inputs": [{"kind": "video", "owned": True, "duration_s": 60}],
        "outputs": ["video"],
        "resolution": "1080p",
    }
    if self_host:
        spec["self_host"] = True
    d = pn.plan(
        "spec-only call",
        facts=list(РАСКРАСКА),
        today=date(2026, 10, 15),
        full=True,
        spec=spec,
        spec_only=True,
    )
    return [(ш["step"], (ш.get("chosen") or {}).get("model")) for ш in d["steps"]]


class РаскраскаТолькоСвоиВеса(unittest.TestCase):
    """n29: узел «только у себя» — кандидат лишь в плане `self_host`."""

    def test_api_план_берёт_оценённую_раскраску_и_апскейл_видео(self) -> None:
        self.assertEqual([("раскраска", "x-colorize"), ("апскейл", "x-vsr")], _шаги(False))

    def test_план_своего_gpu_берёт_свои_веса(self) -> None:
        self.assertEqual([("раскраска", "deoldify-mini")], _шаги(True))

    def test_правило_общее_а_не_только_семья(self) -> None:
        from studio import endpoints as ep

        узел = ep.Endpoint(model="m", key="m", routes=(ep.ROUTE_SELF_HOST,))
        self.assertTrue(pn.семья_только_у_себя(узел))
        self.assertFalse(
            pn.семья_только_у_себя(
                ep.Endpoint(model="m", key="m", routes=("fal", ep.ROUTE_SELF_HOST))
            )
        )
        self.assertFalse(pn.семья_только_у_себя(ep.Endpoint(model="m", key="m")))


if __name__ == "__main__":
    unittest.main()
