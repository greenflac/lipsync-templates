"""Два порога, которые сторожили ЛЮБЫЕ находки вместо СВОИХ.

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ (Ц2): соседние наборы писал другой автор; их фикстуры
здесь переиспользуются, а не копируются (Е1).

ЧТО ЭТО ЗАКРЫВАЕТ. Мутационный прогон 2026-09-04:

    MAX_ACTIONS = 2 -> 99   промолчал
    MAX_ACTIONS = 2 -> 0    промолчал
    SLOT_MAX = 120 -> 100000 промолчал

Первые два — из-за формы соседнего теста: он требует «есть ХОТЬ ОДНА находка
уровня RISK», а в том же черновике находок несколько, и правило про цепочку
действий можно было выключить целиком, не покрасив ничего. Здесь проверяется
находка ПО ИМЕНИ.

Третий — потому что верхнюю границу слота не проверял никто: слот на 100 000
знаков проехал бы в запрос к вендору целиком.
"""

from __future__ import annotations

import unittest

from studio.selfrag.reflect import MAX_ACTIONS, grade_draft
from studio.selfrag.spec import MODE_T2V, SLOT_MAX, GenSpec, assemble, gate_spec
from studio.selfrag.tests.test_reflect_state import STYLE


def _спек(*, subject: str = "a cyclist", action: str = "") -> GenSpec:
    """Спек с одним меняющимся полем.

    ЯВНЫЕ ИМЕНОВАННЫЕ ПАРАМЕТРЫ, А НЕ `**поля`: словарь со смешанными
    значениями проверке типов неизвестен, и она честно сказала, что в
    `GenSpec` летит `object` вместо `str` и `StyleSpec`.
    """
    return GenSpec(model="veo-3.1", mode=MODE_T2V, style=STYLE, subject=subject, action=action)


def _находки(спек: GenSpec) -> list[str]:
    return [f.rule for f in grade_draft(спек, assemble(спек))["findings"]]


class ЦепочкаДействий(unittest.TestCase):
    """Правило проверяется ПО ИМЕНИ, а не по уровню: уровень общий у многих."""

    ДВА = "rides slowly then stops"
    ТРИ = "rides slowly then stops and then waves"

    def test_порог_ровно_два(self) -> None:
        self.assertEqual(2, MAX_ACTIONS)

    def test_три_действия_называются_цепочкой(self) -> None:
        self.assertIn("action_count", _находки(_спек(action=self.ТРИ)))

    def test_два_действия_цепочкой_не_называются(self) -> None:
        """Вторая сторона (Т1): порог, срабатывающий всегда, — не порог."""
        self.assertNotIn("action_count", _находки(_спек(action=self.ДВА)))


class ПотолокСлота(unittest.TestCase):
    def test_потолок_ровно_сто_двадцать(self) -> None:
        self.assertEqual(120, SLOT_MAX)

    def test_слишком_длинный_слот_назван_проблемой(self) -> None:
        итог = gate_spec(_спек(subject="крупный план лица " * 40))
        self.assertEqual("fail", итог["outcome"], итог)
        self.assertIn("the cap is", итог["note"], итог)

    def test_обычный_слот_проблемой_не_называется(self) -> None:
        итог = gate_spec(_спек(subject="крупный план лица велосипедиста"))
        self.assertNotIn("the cap is", итог["note"])


if __name__ == "__main__":
    unittest.main()
