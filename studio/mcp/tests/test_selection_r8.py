"""Восьмой круг, агент C: знак строки — по заявленному, требования — все или никак.

Литералами (Т2):

* e05 — частота кадров читается по ЗАЯВЛЕННОМУ значению строки: «24 fps (…
  contradicts the 30/60 fps in blogs)» — 24, и на вопросе о 60 fps это
  плохая новость, а не хорошая;
* e02 — строка лицензии не хорошая новость, пока спрошенный язык (или другое
  требование) не подтверждён;
* x22 — строка о нескольких языках судит язык шага только своей частью.
"""

from __future__ import annotations

import unittest

from studio import pipeline as pl
from studio.mcp import capability
from studio.selfrag.facts import Fact

HF = "https://huggingface.co"


def _f(model: str, attribute: str, value: str, tier: str = "vendor", url: str = "") -> Fact:
    return Fact(model, attribute, value, url or f"https://{model}.test/{attribute}", tier, "2026-10-01")


def _на_фал(model: str, endpoint: str, category: str) -> Fact:
    return _f(
        model,
        "availability",
        f"on fal.ai as {endpoint} ({category}); listing status public",
        "portal",
        f"https://fal.ai/models/{endpoint}",
    )


KLING = "24 fps (measured on two Kling V3 output files; contradicts the 30/60 fps figures circulating in blogs)"


class ЧастотаПоЗаявленному(unittest.TestCase):
    def test_скобки_и_опровержение_не_значение(self) -> None:
        self.assertEqual([24.0], capability._fps_строки(KLING, "fps"))
        self.assertEqual([60.0], capability._fps_строки("up to 60 fps, not 120 fps", "fps"))
        self.assertEqual([50.0], capability._fps_строки("50 fps — not the 120 fps some blogs claim", "fps"))
        self.assertEqual([30.0], capability._fps_строки("30", "frame_rate"))

    def test_знак_e05(self) -> None:
        вопрос = capability.Вопрос("video generation at 60 fps natively", "fps, 60fps", "")
        знак, _, почему = capability.знак(_f("kling-3.0", "fps", KLING, "probe"), вопрос)
        self.assertEqual((capability.BAD, "24 fps < asked 60"), (знак, почему))


БАЗА = [
    _f("open-en-tts", "license", "MIT", url=f"{HF}/acme/open-en-tts"),
    _f("open-en-tts", "languages", "English, Chinese, Japanese"),
    _f("open-kk-tts", "license", "Apache-2.0", url=f"{HF}/acme/open-kk-tts"),
    _f("open-kk-tts", "languages", "Kazakh, Russian, English"),
    _f("open-silent-tts", "license", "Apache-2.0", url=f"{HF}/acme/open-silent-tts"),
    _f("open-silent-tts", "positioning", "fast speech synthesis", "portal"),
]


class ЛицензияНеДоводБезЯзыка(unittest.TestCase):
    """e02: «open, commercial, kk» — лицензия без казахского не хорошая новость."""

    def _найти(self, require: str) -> dict:
        return capability.find("open-weights TTS", "tts", "", require, 8, facts=БАЗА)

    def test_язык_не_подтверждён_лицензия_информация(self) -> None:
        итог = self._найти("open,kk")
        по_имени = {r["model"]: r for r in итог["ranked"]}
        self.assertEqual("good_news_only", по_имени["open-kk-tts"]["verdict"])
        self.assertEqual("informational_only", по_имени["open-en-tts"]["verdict"])
        self.assertEqual("informational_only", по_имени["open-silent-tts"]["verdict"])
        self.assertEqual(
            "open weights: лицензия весов MIT на странице весов (https://huggingface.co/acme/open-en-tts) — but not confirmed: kk",
            next(
                r["why"] for r in по_имени["open-en-tts"]["informational"] if r["attribute"] == "license"
            ),
        )
        self.assertEqual("open-kk-tts", итог["ranked"][0]["model"])

    def test_никто_не_подтверждает_язык_нет_хорошей_новости(self) -> None:
        итог = capability.find(
            "open-weights TTS", "tts", "", "open,kk", 8, facts=[f for f in БАЗА if "kk" not in f.model]
        )
        self.assertEqual(("could not measure", "no_good_news"), (итог["outcome"], итог["reason"]))

    def test_одни_требования_и_все_подтверждены_как_было(self) -> None:
        итог = self._найти("open")
        self.assertEqual(
            {"good_news_only"}, {r["verdict"] for r in итог["ranked"]}
        )


ХИНДИ = (
    "Язык уходит от хинди: на хинди 0 срывов ретрофлексов (22 токена), на телугу срыв 40%, тамил — "
    "самая сильная деградация из трёх языков исследования; FAD телугу 329 против 250 у индийской Sarvam Bulbul"
)


class СтрокаОНесколькихЯзыках(unittest.TestCase):
    """x22: провал о телугу не судит хинди."""

    def test_живая_строка(self) -> None:
        f = _f("eleven_v3", "degrades_when", ХИНДИ, "paper")
        self.assertEqual(
            (False, True, True),
            (pl.in_scope(f, ["hindi"]), pl.in_scope(f, ["telugu"]), pl.in_scope(f, ["tamil"])),
        )

    def test_по_английски(self) -> None:
        f = _f("x", "degrades_when", "0 retroflex failures in Hindi; Telugu 40%")
        self.assertEqual((False, True), (pl.in_scope(f, ["hindi"]), pl.in_scope(f, ["telugu"])))

    def test_перечень_языков_судит_всех(self) -> None:
        for значение in (
            "Hindi, Telugu and Tamil all degrade",
            "На индийских языках (хинди, телугу, тамильский) акцент хуже",
            "retroflex collapse in Hindi 30%; Telugu 40%",
        ):
            with self.subTest(значение=значение):
                self.assertTrue(pl.in_scope(_f("x", "degrades_when", значение), ["hindi"]))

    def test_строка_одного_языка_как_было(self) -> None:
        self.assertFalse(pl.in_scope(_f("x", "degrades_when", "Telugu 40% failures"), ["hindi"]))
        self.assertTrue(pl.in_scope(_f("x", "degrades_when", "Hindi 40% failures"), ["hindi"]))


VEX = (
    "Campaign-style 15 s video for Senator Vex, a fictional candidate in our board game, "
    "announcing border closures on planet Zorg"
)


def _человек(имя: str, real: bool = False) -> dict:
    return {"name": имя, "real": real, "public_figure": False, "consent": "unknown", "claim": "none"}


class ВыдуманныйПоSpecСтаршеПарыСлов(unittest.TestCase):
    """x30: spec.people real=false и claims none — пара «титул + политика» не отказ."""

    def _исход(self, люди: object, события: object, текст: str = VEX) -> tuple:
        from studio.mcp import screen

        итог, политика = screen.просеять_с_людьми(текст, люди, None, события)
        return итог["outcome"], итог["banned"], политика["decision"]

    def test_x30_план_строится(self) -> None:
        self.assertEqual(
            ("pass", [], "proceed"),
            self._исход([_человек("Senator Vex")], [{"type": "none", "real_brand": False}]),
        )

    def test_без_spec_отказ_как_был(self) -> None:
        self.assertEqual(
            ("fail", ["public figure statement: Senator Vex"], "refuse"), self._исход(None, None)
        )

    def test_имени_нет_в_spec_отказ(self) -> None:
        self.assertEqual(
            ("fail", ["public figure statement: Senator Vex"], "refuse"),
            self._исход([_человек("Someone Else")], [{"type": "none", "real_brand": False}]),
        )

    def test_заявлено_реальное_событие_отказ(self) -> None:
        self.assertEqual(
            ("fail", ["public figure statement: Senator Vex"], "refuse"),
            self._исход([_человек("Senator Vex")], [{"type": "real_event", "real_brand": False}]),
        )

    def test_реальное_имя_из_списка_выдуманным_не_становится(self) -> None:
        self.assertEqual(
            ("fail", ["public figure statement: Emmanuel Macron"], "refuse"),
            self._исход(
                [_человек("Emmanuel Macron")],
                [{"type": "none", "real_brand": False}],
                "Video of Emmanuel Macron announcing border closures",
            ),
        )


if __name__ == "__main__":
    unittest.main()
