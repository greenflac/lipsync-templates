"""Предел площадки-перепродавца — это ОБЛАСТЬ, а не спор с вендором.

Аудит ae94057 (2026-10-14), пункт 7: хорошо изученные модели получали `fail`,
потому что Runway API (1080p) «спорил» с Google (4K) о veo-3.1. Ожидаемые
значения — литералы (Т2), сети нет (Т4), обе стороны правила (И5).
"""

from __future__ import annotations

import unittest

from studio.selfrag.facts import Fact, FactStore


def факт(value: str, tier: str, url: str, attribute: str = "max_resolution") -> Fact:
    return Fact(
        model="m",
        attribute=attribute,
        value=value,
        source_url=url,
        tier=tier,
        stated_on="2026-10-01",
    )


ВЕНДОР = "https://vendor.example/docs"
ПЛОЩАДКА = "https://reseller.example/openapi.json"
ВТОРАЯ_ПЛОЩАДКА = "https://other-portal.example/api"


class ОбластьНеСпор(unittest.TestCase):
    def test_вендор_против_площадки_это_область(self) -> None:
        got = FactStore([факт("4k", "vendor", ВЕНДОР), факт("1080p", "portal", ПЛОЩАДКА)]).claims(
            "m", "max_resolution"
        )
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(got["values"], ["4k"])
        self.assertEqual([r["value"] for r in got["claims"]], ["4k"])
        self.assertEqual(
            [(s["value"], s["venue"]) for s in got["scoped_elsewhere"]],
            [("1080p", "reseller.example")],
        )
        self.assertEqual(got["checked"], 2)
        self.assertIn("ОБЛАСТЬ, НЕ СПОР", got["note"])

    def test_вендор_против_вендора_остаётся_спором(self) -> None:
        """И5: `kling-3.0.max_seconds` — 15 против «5 или 10», оба вендорские."""
        got = FactStore(
            [факт("15", "vendor", ВЕНДОР), факт("10", "vendor", ВЕНДОР + "/old")]
        ).claims("m", "max_resolution")
        self.assertEqual(got["outcome"], "fail")

    def test_блог_против_вендора_остаётся_спором(self) -> None:
        got = FactStore(
            [факт("4k", "vendor", ВЕНДОР), факт("720p", "blog", "https://blog.example/x")]
        ).claims("m", "max_resolution")
        self.assertEqual(got["outcome"], "fail")

    def test_без_площадки_свои_спорят_область_не_спасает(self) -> None:
        """Площадка есть, но остальные сами расходятся — спор."""
        got = FactStore(
            [
                факт("12", "blog", "https://blog.example/a", "max_seconds"),
                факт("4 to 15", "blog", "https://blog.example/b", "max_seconds"),
                факт("15", "portal", ПЛОЩАДКА, "max_seconds"),
            ]
        ).claims("m", "max_seconds")
        self.assertEqual(got["outcome"], "fail")

    def test_остались_одни_блоги_область_не_спасает(self) -> None:
        """Без площадки ответ стоит на блоге — это не `pass`, и область его не делает."""
        got = FactStore(
            [факт("4k", "blog", "https://blog.example/a"), факт("1080p", "portal", ПЛОЩАДКА)]
        ).claims("m", "max_resolution")
        self.assertEqual(got["outcome"], "fail")

    def test_две_площадки_каждая_про_себя(self) -> None:
        got = FactStore(
            [факт("4K", "portal", ПЛОЩАДКА), факт("1K / 2K", "portal", ВТОРАЯ_ПЛОЩАДКА)]
        ).claims("m", "max_resolution")
        self.assertEqual(got["outcome"], "pass")
        self.assertIn("ПО ПЛОЩАДКАМ", got["note"])
        self.assertEqual(
            [g["venue"] for g in got["scoped_elsewhere"]],
            ["other-portal.example", "reseller.example"],
        )

    def test_одна_площадка_сама_с_собой_спорит(self) -> None:
        """И5: два разных значения С ОДНОГО хоста — это спор, не область."""
        got = FactStore(
            [факт("4K", "portal", ПЛОЩАДКА), факт("720p", "portal", ПЛОЩАДКА + "?v=2")]
        ).claims("m", "max_resolution")
        self.assertEqual(got["outcome"], "fail")

    def test_спорное_место_базы_уходит_из_аудита(self) -> None:
        store = FactStore([факт("4k", "vendor", ВЕНДОР), факт("1080p", "portal", ПЛОЩАДКА)])
        self.assertEqual(store.contested(), [])


if __name__ == "__main__":
    unittest.main()
