"""Смета дороже потолка по наименьшей известной — `fail` с числом (Р1).

НАЙДЕНО валидатором 5-го круга (2026-10-15): «$0.10 за 8 с 4K со звуком»
стоит не меньше 2.40 usd — в 24 раза дороже, — а план отвечал «could not
measure»: провал сметы тонул в исходе валидатора-2. Правило: известная нижняя
граница выше потолка — `fail` (`дороже_потолка`) с числом; цен нет — смета
сама «не смогли», и исход не трогается.
"""

from __future__ import annotations

import unittest

from studio import planner as pn


def _цена(сколько: float, потолок: float) -> dict:
    return {
        "outcome": "не годно",
        "over_ceiling": {"least_known_usd": сколько, "ceiling_usd": потолок},
    }


class ДорожеПотолка(unittest.TestCase):
    def test_известный_минимум_выше_потолка_провал_с_числом(self) -> None:
        исход, причина, нота = pn.дороже_потолка(
            "could not measure", "план_не_подтверждён", "валидатор-2 …", _цена(2.4, 0.1), False
        )
        self.assertEqual(("fail", "дороже_потолка"), (исход, причина))
        self.assertIn("наименьшая известная стоимость 2.40 usd против потолка 0.1 usd, в 24.0 раза", нота)

    def test_цен_нет_исход_не_трогается(self) -> None:
        """Только недостающие цены — «не смогли», а не провал."""
        цена = {"outcome": "не смогли", "steps_without_price": ["липсинк"]}
        self.assertEqual(
            ("could not measure", "план_не_подтверждён", "н"),
            pn.дороже_потолка("could not measure", "план_не_подтверждён", "н", цена, False),
        )

    def test_не_годно_без_числа_не_провал(self) -> None:
        """И5: без `over_ceiling` числа нет — и провала по смете нет."""
        self.assertEqual(
            ("pass", "план_подтверждён", "н"),
            pn.дороже_потолка("pass", "план_подтверждён", "н", {"outcome": "не годно"}, False),
        )

    def test_вопрос_о_догадке_старше(self) -> None:
        """Видео из догадки: от ответа зависит, будет ли дорогой шаг."""
        self.assertEqual(
            ("could not measure", "нужен_ответ_заказчика", "н"),
            pn.дороже_потолка("could not measure", "нужен_ответ_заказчика", "н", _цена(5.0, 1.0), True),
        )
        self.assertEqual(
            "дороже_потолка",
            pn.дороже_потолка("could not measure", "нужен_ответ_заказчика", "н", _цена(5.0, 1.0), False)[1],
        )

    def test_совет_и_сводка_называют_сумму(self) -> None:
        итог = {
            "outcome": "fail",
            "reason": "дороже_потолка",
            "по_английски": True,
            "pipeline_price": _цена(2.4, 0.1),
            "steps": [],
        }
        self.assertEqual(
            "the job costs at least 2.40 usd at the cheapest known rates: raise the budget to at "
            "least that, or make the clip shorter, lower-resolution or simpler",
            pn.что_дальше(итог),
        )
        self.assertIn(
            "OVER BUDGET — the least known cost is 2.40 usd against a ceiling of 0.1 usd", pn.сводка(итог)
        )

    def test_причина_в_словаре(self) -> None:
        self.assertIn("дороже_потолка", pn.REASONS)


if __name__ == "__main__":
    unittest.main()
