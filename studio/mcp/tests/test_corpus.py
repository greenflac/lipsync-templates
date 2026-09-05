"""Счётчик корпуса: считает ли он утверждения, а не строки.

Модуль написан после того, как опубликованное «1047 фактов, 258 моделей»
разошлось с прибором на 8%: считались СТРОКИ файла минус отозванные, а прибор
считает УТВЕРЖДЕНИЯ. Пока способ счёта не один, замер «до и после» мерит
способ, а не знание.

Ожидаемое — литералы (правило Т2). Сети нет (Т4).
"""

from __future__ import annotations

import unittest

from studio.corpus import render, snapshot
from studio.selfrag.facts import Fact


def факт(model, attribute="max_seconds", value="5", tier="vendor", url="https://example.test/x"):
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=url,
        tier=tier,
        stated_on="2026-08-31",
    )


class Counting(unittest.TestCase):
    def test_a_class_fact_is_not_a_model(self):
        """Факт со скоупом `*` возвращается на любой запрос и моделью не является."""
        s = snapshot([факт("*"), факт("kling-3.0")])
        self.assertEqual(s.models, 1)
        self.assertEqual(s.class_facts, 1)
        self.assertEqual(s.facts, 2)

    def test_a_family_scope_is_a_scope_too(self):
        """`eleven-*` — скоуп вендорской линейки, а не модель по имени.

        Первая редакция сравнивала с литералом `"*"` и считала его моделью:
        второе определение одного понятия в модуле, написанном против этого.
        Поймано независимой приёмкой, не автором.
        """
        s = snapshot([факт("eleven-*"), факт("kling-3.0")])
        self.assertEqual(s.models, 1)
        self.assertEqual(s.class_facts, 1)

    def test_two_facts_about_one_model_are_one_model(self):
        s = snapshot([факт("kling-3.0", "max_seconds"), факт("kling-3.0", "fps")])
        self.assertEqual(s.models, 1)
        self.assertEqual(s.one_fact_only, 0)

    def test_one_fact_only_is_counted(self):
        s = snapshot([факт("kling-3.0"), факт("veo-3.1"), факт("veo-3.1", "fps")])
        self.assertEqual(s.one_fact_only, 1)

    def test_case_does_not_split_a_model(self):
        s = snapshot([факт("Kling-3.0"), факт("kling-3.0", "fps")])
        self.assertEqual(s.models, 1)


class Composition(unittest.TestCase):
    def test_applicability_is_counted_by_attribute_not_by_tier(self):
        s = snapshot([факт("a", "failure_mode", tier="blog")])
        self.assertEqual(s.with_applicability, 1)
        self.assertEqual(s.with_vendor, 0)

    def test_a_spec_attribute_is_not_applicability(self):
        """Способность и применимость — разное; счётчик обязан их различать."""
        s = snapshot([факт("a", "max_seconds", tier="vendor")])
        self.assertEqual(s.with_applicability, 0)
        self.assertEqual(s.with_vendor, 1)

    def test_a_witness_is_a_probe_or_an_operator(self):
        s = snapshot([факт("a", tier="probe"), факт("b", tier="vendor")])
        self.assertEqual(s.with_witness, 1)

    def test_a_paper_is_not_a_witness(self):
        """Статья описывает чужой прогон и своим свидетельством не становится."""
        s = snapshot([факт("a", tier="paper")])
        self.assertEqual(s.with_witness, 0)

    def test_an_operator_note_is_a_witness(self):
        """Сторож СУЖЕНИЯ: убрать `operator` из набора — и заголовочное число
        «кто-то запускал» правится одним словом при зелёном гейте."""
        s = snapshot([факт("a", tier="operator")])
        self.assertEqual(s.with_witness, 1)

    def test_runs_on_is_applicability(self):
        """Сторож СУЖЕНИЯ с другой стороны: из набора можно молча вынуть
        атрибут, и без этого теста ни один прогон не шевельнётся."""
        s = snapshot([факт("a", "runs_on", tier="blog")])
        self.assertEqual(s.with_applicability, 1)


class NeverJustASum(unittest.TestCase):
    def test_the_share_of_an_empty_base_is_not_zero_percent(self):
        """Ноль моделей — «нечего делить», а не «ноль процентов» (правило Р2)."""
        s = snapshot([])
        self.assertIsNone(s.share("with_vendor"))
        self.assertIn("нечего делить", render(s))

    def test_the_render_never_prints_a_bare_total(self):
        """Е3: агрегат читается как полная работа, поэтому идёт с распределением."""
        текст = render(snapshot([факт("a"), факт("b", "failure_mode")]))
        for имя in ("ровно один факт", "есть вендорский факт", "есть применимость"):
            self.assertIn(имя, текст)

    def test_a_before_snapshot_shows_both_numbers(self):
        было = snapshot([факт("a")])
        стало = snapshot([факт("a"), факт("b", "failure_mode")])
        self.assertIn("было", render(стало, было))


class OneDefinitionOnly(unittest.TestCase):
    def test_contested_comes_from_the_existing_instrument(self):
        """Своё определение спорности дало бы 76 против 7 у FactStore.

        Оно не знает про MULTI_VALUED — атрибуты, где несколько значений это
        список, а не противоречие. Второе определение одного понятия — тот же
        дефект Е1, ради которого модуль и написан; поймано на себе.
        """
        rows = [
            факт("a", "resolution", "720p"),
            факт("a", "resolution", "1080p"),
        ]
        # Ожидаемое ЛИТЕРАЛОМ (правило Т2): импорт `FactStore` сюда означал бы
        # проверку копии — тест поехал бы вместе с проверяемым модулем и
        # промолчал. `resolution` не входит в MULTI_VALUED, два разных значения
        # у одной пары — одно противоречие.
        self.assertEqual(snapshot(rows).contested_pairs, 1)


if __name__ == "__main__":
    unittest.main()
