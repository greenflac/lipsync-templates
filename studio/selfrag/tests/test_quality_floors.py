"""Пороги оценщика качества промпта: сколько корпуса нужно и где проходит низ.

ЗАЧЕМ. `studio/selfrag/quality.py` решает по двум константам, и ни одну не
сторожил мутант.

* `MIN_CORPUS = 50` — ниже этого числа перцентиль не значит ничего, и прибор
  обязан ответить «не смогли» (Р1), а не выдать число. Опусти константу — и
  распределение по горстке строк начнёт выдаваться как стандарт корпуса.
* `GOOD_PERCENTILE = 0.10` — низ, ниже которого промпт назван непохожим ни на
  что в корпусе. Опусти до нуля — и оценщик перестанет браковать что-либо
  вообще, оставаясь при этом зелёным и разговорчивым.

Корпус здесь строится ДЕТЕРМИНИРОВАННО и растёт монотонно по длине, поэтому
позиция члена корпуса в его собственном распределении известна заранее: член
№1 стоит на 0.02, член №10 — на 0.2 и выше. Числа записаны литералами (Т2).
"""

from __future__ import annotations

import unittest

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.quality import calibrate, score

ФРАЗЫ = (
    "a rain-slick rooftop at dusk",
    "amber golden-hour light",
    "fine film grain",
    "soft rim light",
    "shallow depth of field",
    "a nostalgic mood",
    "muted teal shadows",
    "gentle handheld drift",
    "warm bounce from below",
    "hazy backlit haze",
    "slow dolly in",
    "low contrast highlights",
    "matte skin texture",
    "cool blue rim",
    "dim tungsten glow",
    "faint lens flare",
    "crisp foreground detail",
    "soft focus falloff",
    "pale overcast sky",
    "dusty air",
)


def _промпт(фраз: int) -> str:
    return ", ".join(ФРАЗЫ[i % len(ФРАЗЫ)] for i in range(фраз))


def _корпус(строк: int) -> list[str]:
    """Строк ровно `строк`, длина растёт на одну фразу за строку."""
    return [_промпт(n) for n in range(2, 2 + строк)]


class ПорогКорпуса(unittest.TestCase):
    def test_сорок_девять_строк_это_не_смогли(self) -> None:
        out = calibrate(_корпус(49))
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertEqual(out["checked"], 49)
        self.assertIsNone(out["model"])

    def test_пятьдесят_строк_уже_калибруются(self) -> None:
        out = calibrate(_корпус(50))
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual(out["checked"], 50)
        self.assertIsNotNone(out["model"])


class НизРаспределения(unittest.TestCase):
    def setUp(self) -> None:
        готово = calibrate(_корпус(50))
        self.assertEqual(готово["outcome"], PASS)
        self.model = готово["model"]

    def test_самый_короткий_член_корпуса_бракуется(self) -> None:
        """Он стоит на 0.02 — ниже низа, и это отказ с названной чертой."""
        out = score(_корпус(50)[0], model=self.model)
        self.assertEqual(out["percentiles"]["clauses"], 0.02)
        self.assertEqual(out["outcome"], FAIL)
        self.assertEqual(out["weakest"], "clauses")

    def test_десятый_член_корпуса_проходит(self) -> None:
        """Другая сторона мутации (Т1): подними низ — и это покраснеет.

        Его самая слабая черта стоит на 0.14, то есть ВЫШЕ 0.10 и ниже любого
        порога, который кто-нибудь захочет поднять «чуть-чуть».
        """
        out = score(_корпус(50)[9], model=self.model)
        self.assertEqual(min(out["percentiles"].values()), 0.14)
        self.assertEqual(out["outcome"], PASS)


if __name__ == "__main__":
    unittest.main()
