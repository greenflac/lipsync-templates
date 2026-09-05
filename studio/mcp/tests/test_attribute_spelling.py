"""Одно свойство — одно имя. Иначе половина фактов невидима для запроса.

ИЗМЕРЕНО 2026-08-31: в базе стояли `licence` (10 фактов) и `license` (9).
Спросивший одно написание получал ответ из половины базы и не знал об этом.
Столкновение было ровно одно из 267 имён атрибутов — и именно в лицензии, где
пропущенный факт означает research-only модель в продакшене.

Ожидаемое — литералы (правило Т2). Сеть не нужна (Т4).
"""

from __future__ import annotations

import collections
import importlib.util
import re
import unittest
from pathlib import Path

from studio.selfrag.facts import load_facts

SPEC = importlib.util.spec_from_file_location(
    "merge_model_ids", Path(__file__).resolve().parents[3] / "scripts" / "merge_model_ids.py"
)
assert SPEC and SPEC.loader
merge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(merge)


def свести(имя: str) -> str:
    """Написания, которые для человека одно и то же."""
    return re.sub(r"[^a-z0-9]", "", имя.lower()).replace("licence", "license")


class OneNamePerAttribute(unittest.TestCase):
    def test_the_british_spelling_maps_to_the_machine_readable_one(self):
        """Побеждает `license`: так поле зовётся в карточке HuggingFace (Е2)."""
        self.assertEqual(merge.ATTRIBUTE_MERGES["licence"], "license")

    def test_no_attribute_in_the_live_base_has_two_spellings(self):
        группы = collections.defaultdict(set)
        for факт in load_facts():
            группы[свести(факт.attribute)].add(факт.attribute)
        двойники = {k: sorted(v) for k, v in группы.items() if len(v) > 1}
        self.assertEqual(двойники, {})

    def test_the_merge_table_is_not_a_loop(self):
        """Написание не может сводиться к себе или к другому написанию."""
        for откуда, куда in merge.ATTRIBUTE_MERGES.items():
            self.assertNotEqual(откуда, куда)
            self.assertNotIn(куда, merge.ATTRIBUTE_MERGES)

    def test_canonical_of_renames_the_attribute_not_only_the_model(self):
        class Ф:
            model = "неизвестная-модель"
            attribute = "licence"

        self.assertEqual(merge.canonical_of(Ф()), ("неизвестная-модель", "license"))

    def test_canonical_of_leaves_an_unlisted_name_alone(self):
        class Ф:
            model = "kling-3.0"
            attribute = "max_seconds"

        self.assertEqual(merge.canonical_of(Ф()), ("kling-3.0", "max_seconds"))


if __name__ == "__main__":
    unittest.main()
