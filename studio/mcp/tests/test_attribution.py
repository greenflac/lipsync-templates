"""Атрибуция вендорских фактов: ловится ли подмена имени модели.

Абляция показала, что испорченную атрибуцию инструмент проглатывает молча.
Прибор для её обнаружения уже существовал — тир решается по URL, — но
применялся только при ЗАПИСИ и никогда к стоящим фактам.

Ожидаемое — литералы (Т2). Сети нет (Т4).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from studio.selfrag.facts import Fact

SPEC = importlib.util.spec_from_file_location(
    "check_attribution", Path(__file__).resolve().parents[3] / "scripts" / "check_attribution.py"
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def факт(model, url, tier="vendor", attribute="max_seconds"):
    return Fact(
        model=model,
        attribute=attribute,
        value="10",
        source_url=url,
        tier=tier,
        stated_on="2026-08-31",
    )


ВЕНДОРСКИЙ = "https://kling.ai/quickstart/text-to-video-prompt-guide"


class CatchesTheSwap(unittest.TestCase):
    def test_a_fact_moved_to_another_model_is_caught(self):
        """Ровно то, что делает перемешивание: текст остался, имя чужое."""
        плохие = gate.mismatches([факт("veo-3.1", ВЕНДОРСКИЙ)])
        self.assertEqual(len(плохие), 1)
        self.assertEqual(плохие[0]["model"], "veo-3.1")

    def test_the_right_model_on_its_own_vendor_page_passes(self):
        """Негативный контроль: прибор обязан пропускать законное."""
        self.assertEqual(gate.mismatches([факт("kling-3.0", ВЕНДОРСКИЙ)]), [])

    def test_a_lookalike_domain_is_not_the_vendor(self):
        подделка = "https://kling.ai.attacker.example/guide"
        self.assertEqual(len(gate.mismatches([факт("kling-3.0", подделка)])), 1)


class LimitsOfThisGate(unittest.TestCase):
    def test_a_portal_fact_is_not_judged_by_host(self):
        """Портальный факт не обязан лежать на хосте, связанном с моделью.

        Требовать этого значило бы выдумать проверку, которой нет: там связь
        модели с утверждением по устройству ничем не подтверждается.
        """
        чужой = факт("veo-3.1", "https://replicate.com/some/model", tier="portal")
        self.assertEqual(gate.mismatches([чужой]), [])

    def test_a_class_scope_has_no_vendor_to_check(self):
        self.assertEqual(gate.mismatches([факт("*", ВЕНДОРСКИЙ)]), [])
        self.assertEqual(gate.mismatches([факт("eleven-*", ВЕНДОРСКИЙ)]), [])


class ThreeOutcomes(unittest.TestCase):
    def test_no_vendor_facts_is_could_not_measure_not_a_pass(self):
        """Р2: ноль проверок не равен успеху."""
        self.assertEqual(gate.check([факт("a", "https://example.test/x", tier="blog")]), 2)

    def test_an_empty_base_is_could_not_measure(self):
        self.assertEqual(gate.check([]), 2)

    def test_a_clean_base_passes(self):
        self.assertEqual(gate.check([факт("kling-3.0", ВЕНДОРСКИЙ)]), 0)

    def test_a_swapped_fact_fails_the_build(self):
        self.assertEqual(gate.check([факт("veo-3.1", ВЕНДОРСКИЙ)]), 1)


if __name__ == "__main__":
    unittest.main()
