"""Сборка восьмого круга: две правки выбора генератора под 8K/4K.

Каждая — с литералом и в обе стороны (Т1, Т2):

* кадр допущения класса округляется до кратного 8 (было 3841x2160 — на
  пиксель шире 4K, и родной 4K читался «ниже»);
* своя строка о родном выходе старше строки семьи (`kling-3.0-4k-t2v`
  «4K native» при 1080p у семьи `kling-3.0`);
"""

from __future__ import annotations

import unittest

from studio import brief_spec as bs
from studio import planner as pn
from studio.recipes import apply as rc
from studio.selfrag.facts import Fact


def факт(model: str, attribute: str, value: str) -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url="https://fal.ai/models/example",
        tier="portal",
        stated_on="2026-10-16",
    )


def операция(имя: str) -> pn.Operation:
    return next(о for о in pn.OPERATIONS if о.name == имя)


class КадрДопущенияКратенВосьми(unittest.TestCase):
    def test_8k_видео_ранжируется_по_ровно_4k(self) -> None:
        spec, ошибки = bs.parse_spec(
            {
                "task": "generate",
                "outputs": ["video"],
                "duration_s": 10,
                "resolution": "8k",
                "inputs": [],
            }
        )
        self.assertEqual([], ошибки)
        кадр = rc.requirement_frame("генерация_видео", (7680, 4320), spec)
        self.assertEqual((3840, 2160), кадр)

    def test_кадр_в_пределах_класса_не_меняется(self) -> None:
        spec, _ = bs.parse_spec(
            {
                "task": "generate",
                "outputs": ["video"],
                "duration_s": 10,
                "resolution": "1080p",
                "inputs": [],
            }
        )
        self.assertEqual((1920, 1080), rc.requirement_frame("генерация_видео", (1920, 1080), spec))


class СвояСтрокаСтаршеСемьи(unittest.TestCase):
    СВОИ = [факт("kling-3.0-4k-t2v", "max_resolution", "4K native — directly outputs 4K video")]
    СЕМЬЯ = [("kling-3.0", [факт("kling-3.0", "native_resolution", "1080p native output")])]

    def test_4k_вариант_родной_при_1080p_у_семьи(self) -> None:
        self.assertIs(
            True,
            pn._кадр_родной(операция("генерация_видео"), self.СВОИ, None, (3840, 2160), self.СЕМЬЯ),
        )

    def test_без_своей_строки_решает_семья(self) -> None:
        self.assertIs(
            False, pn._кадр_родной(операция("генерация_видео"), [], None, (3840, 2160), self.СЕМЬЯ)
        )

    def test_предел_по_своей_строке(self) -> None:
        self.assertEqual(2160, pn.родной_предел(self.СВОИ, self.СЕМЬЯ, None))

    def test_тариф_без_своей_строки_опускается_семьёй(self) -> None:
        self.assertEqual(1079, pn.родной_предел([], self.СЕМЬЯ, 2160))


if __name__ == "__main__":
    unittest.main()
