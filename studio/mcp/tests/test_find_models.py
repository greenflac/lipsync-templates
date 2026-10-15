"""`find_models`: вопрос о способности по всей базе, ранжированный по свидетельству.

НАЙДЕНО валидатором 5-го круга: на «which lipsync handles profile faces»
вызывающая модель называла кандидатов по памяти и спрашивала `model_advice`
только о них — записанное о других моделях не всплывало. Здесь — фикстура
из литералов (Т2), не живая база.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from studio.mcp import capability, server
from studio.selfrag.facts import Fact


def _f(model: str, attribute: str, value: str, tier: str = "vendor", url: str = "", day: str = "2026-10-01") -> Fact:
    return Fact(model, attribute, value, url or f"https://{model}.test/{attribute}", tier, day)


БАЗА = [
    _f("alpha-lipsync", "observed_behaviour", "handles side profiles up to 80 degrees of rotation", "operator"),
    _f("beta-lipsync", "limitation", "no side profiles: face must be frontal", "vendor"),
    _f("gamma-lipsync", "observed_behaviour", "works on profile shots", "blog"),
    _f("gamma-lipsync", "failure_mode", "mouth smears on profile at 90 degrees", "blog"),
    _f("delta-lipsync", "license", "Apache-2.0"),
    _f("zeta-avatar", "produces_outputs", "talking head video from audio"),
    _f("*", "failure_mode", "every audio-driven model loses the mouth at full profile", "paper"),
    _f("open-tts", "license", "MIT"),
    _f("open-tts", "languages", "en, ru, de"),
    _f("closed-tts", "license", "proprietary, API only"),
    _f("closed-tts", "languages", "English, Russian"),
    _f("nolang-tts", "license", "Apache-2.0"),
]


class Ранжирование(unittest.TestCase):
    def test_хорошая_без_плохой_первой_потом_смешанная_потом_плохая(self) -> None:
        итог = capability.find("which lipsync handles profile faces", "lipsync", facts=БАЗА)
        self.assertEqual(("pass", "ranked_by_evidence"), (итог["outcome"], итог["reason"]))
        self.assertEqual(
            [("alpha-lipsync", "good_news_only"), ("gamma-lipsync", "mixed"), ("beta-lipsync", "bad_news_only")],
            [(r["model"], r["verdict"]) for r in итог["ranked"]],
        )

    def test_пробелы_названы(self) -> None:
        итог = capability.find("which lipsync handles profile faces", "lipsync", facts=БАЗА)
        # zeta-avatar — в функции по строке «talking head», а не по имени.
        self.assertEqual(5, итог["checked"])
        self.assertEqual({"models_without_evidence": 2, "examples": ["delta-lipsync", "zeta-avatar"],
                          "excluded_by_requirement": 0, "excluded_examples": []}, итог["gaps"])

    def test_находка_о_классе_отдельно(self) -> None:
        итог = capability.find("profile", "lipsync", facts=БАЗА)
        self.assertEqual(["*"], [к["scope"] for к in итог["class_findings"]])
        self.assertNotIn("*", [r["model"] for r in итог["ranked"]])

    def test_функция_по_описанию_а_не_только_по_имени(self) -> None:
        итог = capability.find("talking head", "lipsync", terms="talking head", facts=БАЗА)
        self.assertIn("zeta-avatar", [r["model"] for r in итог["ranked"]])


class Требования(unittest.TestCase):
    def test_открытая_и_русский(self) -> None:
        итог = capability.find("best open TTS for Russian", "tts", require="open, russian", facts=БАЗА)
        self.assertEqual(["open-tts"], [r["model"] for r in итог["ranked"]])
        self.assertEqual(2, итог["gaps"]["excluded_by_requirement"])

    def test_непонятое_требование_названо(self) -> None:
        итог = capability.find("tts", "tts", require="klingon", facts=БАЗА)
        self.assertEqual(["klingon"], итог["require_not_understood"])


class ЧестныйПробел(unittest.TestCase):
    def test_ни_одной_хорошей_новости_не_pass(self) -> None:
        итог = capability.find("profile", "lipsync", facts=[_f("beta-lipsync", "limitation", "no side profiles")])
        self.assertEqual(("could not measure", "no_good_news"), (итог["outcome"], итог["reason"]))

    def test_ничего_не_записано(self) -> None:
        итог = capability.find("profile", "lipsync", facts=[_f("delta-lipsync", "license", "MIT")])
        self.assertEqual(("could not measure", "no_evidence"), (итог["outcome"], итог["reason"]))

    def test_незнакомая_функция(self) -> None:
        итог = capability.find("x", "banana", facts=БАЗА)
        self.assertEqual(("could not measure", "function_unknown"), (итог["outcome"], итог["reason"]))


class Инструмент(unittest.TestCase):
    def test_обёртка_и_язык(self) -> None:
        настоящий = capability.find
        with mock.patch.object(capability, "find", lambda *a, **k: настоящий(*a, **{**k, "facts": БАЗА})):
            en = json.loads(server.find_models("which lipsync handles profile faces", "lipsync"))
            ru = json.loads(server.find_models("какой липсинк держит профиль", "lipsync", terms="profile"))
        self.assertEqual("alpha-lipsync", en["ranked"][0]["model"])
        self.assertIn("call model_advice", en["note"])
        self.assertIn("спросите о ней model_advice", ru["note"])

    def test_описание_учит_звать_вместо_догадки(self) -> None:
        self.assertIn("INSTEAD OF GUESSING CANDIDATES", server.find_models.__doc__ or "")


if __name__ == "__main__":
    unittest.main()
